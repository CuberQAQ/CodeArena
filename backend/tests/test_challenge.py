"""Tests for the challenge system: matchmaking, challenge lifecycle, and settlement.

Uses lightweight SQLite-compatible test models and mocks for external services
(CF API). The key technique is patching the production model references in
challenge_service with test-compatible models so SQLAlchemy queries target the
SQLite tables with the correct column set.

Redis-dependent services (MatchService, pending match store) use fakeredis
for in-memory testing without a real Redis instance.
"""

import uuid
from datetime import datetime
from unittest.mock import AsyncMock, patch

import fakeredis.aioredis
import pytest
from sqlalchemy import Boolean, DateTime, Float, Integer, String, event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core.exceptions import BadRequestException, ForbiddenException, NotFoundException
from app.services import challenge_service as challenge_svc_module
from app.services import economy_service as economy_svc_module
from app.services.challenge_service import (
    ChallengeService,
    _build_problem_info,
    _elo_change_for_user,
    _get_pending,
    _pending_key,
    _remove_pending,
    _result_for_user,
    _set_pending,
    _tokens_for_rating,
)
from app.services.config_service import ConfigService
from app.services.elo_service import EloService
from app.services.match_service import MatchResult, MatchService, QueueEntry
from app.services.submission_tracker import SubmissionTracker

# ---------------------------------------------------------------------------
# Lightweight SQLite-compatible test models
# ---------------------------------------------------------------------------


class _TestBase(DeclarativeBase):
    pass


class _TestUser(_TestBase):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(String(50), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    cf_handle: Mapped[str | None] = mapped_column(String(100), nullable=True)
    elo: Mapped[int] = mapped_column(Integer, default=1200, nullable=False)
    pp: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class _TestChallengeSession(_TestBase):
    __tablename__ = "challenge_sessions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    challenger_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    opponent_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    problem_id: Mapped[str] = mapped_column(String(50), default="", nullable=False)
    problem_rating: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    challenger_submissions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    opponent_submissions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    challenger_solved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    opponent_solved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    challenger_time: Mapped[float | None] = mapped_column(Float, nullable=True)
    opponent_time: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    result: Mapped[str | None] = mapped_column(String(20), nullable=True)
    elo_change: Mapped[int | None] = mapped_column(Integer, nullable=True)
    opponent_elo_change: Mapped[int | None] = mapped_column(Integer, nullable=True)
    opponent_tokens_earned: Mapped[int | None] = mapped_column(Integer, nullable=True)
    challenger_tokens_earned: Mapped[int | None] = mapped_column(Integer, nullable=True)
    problem_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    hints_used_challenger: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    hints_used_opponent: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class _TestTokenTransaction(_TestBase):
    __tablename__ = "token_transactions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    type: Mapped[str] = mapped_column(String(30), nullable=False)
    reference_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    reference_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    balance_after: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def fake_redis():
    """Provide a fakeredis instance for testing."""
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    yield redis
    await redis.aclose()


@pytest.fixture
async def match_service(fake_redis):
    """Provide a MatchService backed by fakeredis."""
    with patch("app.services.match_service.get_redis", return_value=fake_redis):
        svc = MatchService()
        yield svc


@pytest.fixture
async def async_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)

    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as conn:
        await conn.run_sync(_TestBase.metadata.create_all)

    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(_TestBase.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
async def db(async_engine, fake_redis):
    """Provide an async session with patched model references.

    Patches User and ChallengeSession in the challenge_service module
    so that db.get() and select() calls resolve to the SQLite-compatible
    test models. Also patches economy_svc.award_tokens to directly add
    tokens to user (bypassing daily cap / TokenTransaction logic that
    requires production columns).

    Also patches get_redis to return the fakeredis instance so pending
    match state works without a real Redis server.
    """
    session_factory = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)

    async def _mock_award_tokens(db, user, amount, tx_type=None, reference_type=None, reference_id=None):
        """Side-effect mock: add tokens directly to user object."""
        user.tokens += amount
        return amount

    async def _mock_get_config(db, key):
        """Return default elo config for tests."""
        from app.core.default_config import DEFAULT_CONFIG
        return DEFAULT_CONFIG.get("elo", {})

    async def _mock_get_submission_count(db, user_id):
        """Return 0 submissions for tests (no PP records table)."""
        return 0

    async with session_factory() as session:
        with (
            patch.object(challenge_svc_module, "User", _TestUser),
            patch.object(challenge_svc_module, "ChallengeSession", _TestChallengeSession),
            patch.object(economy_svc_module, "award_tokens", _mock_award_tokens),
            patch.object(ConfigService, "get_config", _mock_get_config),
            patch.object(EloService, "get_submission_count", _mock_get_submission_count),
            patch.object(SubmissionTracker, "register_pending", AsyncMock()),
            patch("app.services.challenge_service.get_redis", return_value=fake_redis),
        ):
            yield session


def _make_test_user(
    db: AsyncSession,
    user_id: uuid.UUID | None = None,
    username: str = "testuser",
    elo: int = 1200,
    tokens: int = 0,
    cf_handle: str | None = None,
) -> _TestUser:
    """Create a test user instance (not yet added to session)."""
    return _TestUser(
        id=user_id or uuid.uuid4(),
        username=username,
        email=f"{username}@test.com",
        password_hash="$2b$12$fakehash",
        elo=elo,
        tokens=tokens,
        cf_handle=cf_handle,
    )


def _make_test_session(
    challenger_id: uuid.UUID,
    opponent_id: uuid.UUID,
    status: str = "active",
    problem_id: str = "800A",
    problem_rating: int = 1200,
) -> _TestChallengeSession:
    """Create a test challenge session instance."""
    return _TestChallengeSession(
        challenger_id=challenger_id,
        opponent_id=opponent_id,
        problem_id=problem_id,
        problem_rating=problem_rating,
        status=status,
    )


# ---------------------------------------------------------------------------
# 1. MatchService tests
# ---------------------------------------------------------------------------


class TestMatchServiceQueue:
    async def test_join_queue_success(self, match_service):
        uid = uuid.uuid4()
        result = await match_service.join_queue(uid, 1200, "player1")
        assert result is True
        assert await match_service.get_queue_size() == 1

    async def test_join_queue_duplicate_rejected(self, match_service):
        uid = uuid.uuid4()
        await match_service.join_queue(uid, 1200, "player1")
        result = await match_service.join_queue(uid, 1200, "player1")
        assert result is False
        assert await match_service.get_queue_size() == 1

    async def test_leave_queue_success(self, match_service):
        uid = uuid.uuid4()
        await match_service.join_queue(uid, 1200, "player1")
        result = await match_service.leave_queue(uid)
        assert result is True
        assert await match_service.get_queue_size() == 0

    async def test_leave_queue_not_present(self, match_service):
        uid = uuid.uuid4()
        result = await match_service.leave_queue(uid)
        assert result is False

    async def test_is_in_queue(self, match_service):
        uid = uuid.uuid4()
        assert await match_service.is_in_queue(uid) is False
        await match_service.join_queue(uid, 1200, "player1")
        assert await match_service.is_in_queue(uid) is True
        await match_service.leave_queue(uid)
        assert await match_service.is_in_queue(uid) is False


class TestMatchServiceMatching:
    async def test_try_match_no_candidates(self, match_service):
        uid = uuid.uuid4()
        await match_service.join_queue(uid, 1200, "player1")
        result = await match_service.try_match(uid)
        assert result is None

    async def test_try_match_not_in_queue(self, match_service):
        uid = uuid.uuid4()
        result = await match_service.try_match(uid)
        assert result is None

    async def test_try_match_success(self, match_service):
        uid_a = uuid.uuid4()
        uid_b = uuid.uuid4()
        await match_service.join_queue(uid_a, 1200, "player_a")
        await match_service.join_queue(uid_b, 1250, "player_b")

        result = await match_service.try_match(uid_a)
        assert result is not None
        assert isinstance(result, MatchResult)
        assert result.player_a.user_id == uid_a
        assert result.player_b.user_id == uid_b
        assert result.avg_elo == 1225.0

        # Both should be removed from queue
        assert await match_service.get_queue_size() == 0

    async def test_match_removes_both_players(self, match_service):
        uid_a = uuid.uuid4()
        uid_b = uuid.uuid4()
        uid_c = uuid.uuid4()
        await match_service.join_queue(uid_a, 1200, "a")
        await match_service.join_queue(uid_b, 1200, "b")
        await match_service.join_queue(uid_c, 1300, "c")

        result = await match_service.try_match(uid_a)
        assert result is not None
        # One player matched, one remains
        assert await match_service.get_queue_size() == 1

    async def test_try_match_any(self, match_service):
        uid_a = uuid.uuid4()
        uid_b = uuid.uuid4()
        uid_c = uuid.uuid4()
        uid_d = uuid.uuid4()
        await match_service.join_queue(uid_a, 1200, "a")
        await match_service.join_queue(uid_b, 1200, "b")
        await match_service.join_queue(uid_c, 1300, "c")
        await match_service.join_queue(uid_d, 1300, "d")

        results = await match_service.try_match_any()
        assert len(results) == 2
        assert await match_service.get_queue_size() == 0

    async def test_match_atomic_no_double_match(self, match_service, fake_redis):
        """Verify that two concurrent match attempts don't both succeed with the same player."""
        uid_a = uuid.uuid4()
        uid_b = uuid.uuid4()
        uid_c = uuid.uuid4()
        await match_service.join_queue(uid_a, 1200, "a")
        await match_service.join_queue(uid_b, 1200, "b")
        await match_service.join_queue(uid_c, 1250, "c")

        result_ab = await match_service.try_match(uid_a)
        # After first match, only one player remains; second match should fail
        result_c = await match_service.try_match(uid_c)

        # At least one should be None (no double matching)
        if result_ab is not None:
            assert result_c is None
        else:
            assert result_c is not None


class TestMatchServiceWeights:
    """Test the probability-weighted matching algorithm."""

    def test_weight_close(self, match_service):
        assert match_service._calculate_weight(0) == 0.50
        assert match_service._calculate_weight(50) == 0.50
        assert match_service._calculate_weight(100) == 0.50
        assert match_service._calculate_weight(-100) == 0.50

    def test_weight_challenge_zone(self, match_service):
        # Opponent stronger (positive gap) -> challenge
        assert match_service._calculate_weight(200) == 0.25
        assert match_service._calculate_weight(300) == 0.25

    def test_weight_consolidate_zone(self, match_service):
        # Opponent weaker (negative gap) -> consolidate
        assert match_service._calculate_weight(-200) == 0.15
        assert match_service._calculate_weight(-300) == 0.15

    def test_weight_far(self, match_service):
        assert match_service._calculate_weight(500) == 0.10
        assert match_service._calculate_weight(-500) == 0.10
        assert match_service._calculate_weight(1000) == 0.10

    async def test_select_opponent_prefers_close_elo(self, match_service):
        """Run many trials to verify probability weighting is roughly correct."""
        player = QueueEntry(user_id=uuid.uuid4(), elo=1200, username="player")

        close = QueueEntry(user_id=uuid.uuid4(), elo=1250, username="close")
        challenge = QueueEntry(user_id=uuid.uuid4(), elo=1450, username="challenge")
        consolidate = QueueEntry(user_id=uuid.UUID(int=0), elo=950, username="consolidate")
        far = QueueEntry(user_id=uuid.uuid4(), elo=1800, username="far")

        candidates = [close, challenge, consolidate, far]

        counts = {c.username: 0 for c in candidates}
        trials = 10000
        for _ in range(trials):
            selected = match_service._select_opponent(player, candidates)
            assert selected is not None
            counts[selected.username] += 1

        # Close should be selected most often (~50%)
        close_ratio = counts["close"] / trials
        assert 0.40 < close_ratio < 0.60, f"Close ratio {close_ratio} outside expected range"

        # Far should be selected least often (~10%)
        far_ratio = counts["far"] / trials
        assert 0.05 < far_ratio < 0.15, f"Far ratio {far_ratio} outside expected range"

    async def test_select_opponent_no_candidates(self, match_service):
        player = QueueEntry(user_id=uuid.uuid4(), elo=1200, username="player")
        result = match_service._select_opponent(player, [])
        assert result is None


# ---------------------------------------------------------------------------
# 2. ChallengeService - join/leave queue
# ---------------------------------------------------------------------------


class TestChallengeQueue:
    async def test_join_queue_no_match(self, db, match_service):
        user = _make_test_user(db, username="user1", elo=1200)
        db.add(user)
        await db.flush()

        result = await ChallengeService.join_queue(db, user, match_service)
        assert result["matched"] is False
        assert "Added to queue" in result["message"] or "Waiting" in result["message"]

    async def test_join_queue_already_in_queue(self, db, match_service):
        user = _make_test_user(db, username="user1", elo=1200)
        db.add(user)
        await db.flush()

        await ChallengeService.join_queue(db, user, match_service)
        with pytest.raises(BadRequestException, match="Already in match queue"):
            await ChallengeService.join_queue(db, user, match_service)

    async def test_join_queue_with_match(self, db, match_service):
        user_a = _make_test_user(db, username="user_a", elo=1200)
        user_b = _make_test_user(db, username="user_b", elo=1250)
        db.add_all([user_a, user_b])
        await db.flush()

        # User A joins first (no match)
        await ChallengeService.join_queue(db, user_a, match_service)

        # User B joins and should match with A
        result = await ChallengeService.join_queue(db, user_b, match_service)
        assert result["matched"] is True
        assert result["session_id"] is not None
        assert result["opponent"] is not None

    async def test_leave_queue(self, db, match_service):
        user = _make_test_user(db, username="user1", elo=1200)
        db.add(user)
        await db.flush()

        await ChallengeService.join_queue(db, user, match_service)
        removed = await ChallengeService.leave_queue(user, match_service)
        assert removed is True

    async def test_leave_queue_not_present(self, db, match_service):
        user = _make_test_user(db, username="user1", elo=1200)
        db.add(user)
        await db.flush()

        removed = await ChallengeService.leave_queue(user, match_service)
        assert removed is False


# ---------------------------------------------------------------------------
# 3. ChallengeService - start challenge
# ---------------------------------------------------------------------------


class TestStartChallenge:
    async def test_start_challenge_not_found(self, db):
        user = _make_test_user(db, username="user1")
        db.add(user)
        await db.flush()

        cf_mock = AsyncMock()
        with pytest.raises(NotFoundException, match="Challenge session not found"):
            await ChallengeService.start_challenge(db, user, uuid.uuid4(), cf_mock)

    async def test_start_challenge_not_participant(self, db):
        user_a = _make_test_user(db, username="user_a")
        user_b = _make_test_user(db, username="user_b")
        outsider = _make_test_user(db, username="outsider")
        db.add_all([user_a, user_b, outsider])
        await db.flush()

        session = _make_test_session(user_a.id, user_b.id, status="pending")
        db.add(session)
        await db.flush()

        cf_mock = AsyncMock()
        with pytest.raises(ForbiddenException, match="Not a participant"):
            await ChallengeService.start_challenge(db, outsider, session.id, cf_mock)

    async def test_start_challenge_waiting_opponent(self, db):
        user_a = _make_test_user(db, username="user_a", elo=1200)
        user_b = _make_test_user(db, username="user_b", elo=1200)
        db.add_all([user_a, user_b])
        await db.flush()

        session = _make_test_session(user_a.id, user_b.id, status="pending")
        db.add(session)
        await db.flush()

        # Set up pending state
        await _set_pending(session.id, {
            "player_a_id": user_a.id,
            "player_b_id": user_b.id,
            "avg_elo": 1200.0,
            "confirmed": set(),
        })

        cf_mock = AsyncMock()
        result = await ChallengeService.start_challenge(db, user_a, session.id, cf_mock)
        assert result.status == "waiting_opponent"

        await _remove_pending(session.id)

    async def test_start_challenge_both_confirm_reveals_problem(self, db):
        user_a = _make_test_user(db, username="user_a", elo=1200)
        user_b = _make_test_user(db, username="user_b", elo=1200)
        db.add_all([user_a, user_b])
        await db.flush()

        session = _make_test_session(user_a.id, user_b.id, status="pending")
        db.add(session)
        await db.flush()

        # Set up pending state with A already confirmed
        await _set_pending(session.id, {
            "player_a_id": user_a.id,
            "player_b_id": user_b.id,
            "avg_elo": 1200.0,
            "confirmed": {user_a.id},
        })

        cf_mock = AsyncMock()
        cf_mock.get_problemset_problems.return_value = {
            "problems": [
                {"contestId": 800, "index": "A", "name": "Test Problem", "rating": 1200, "tags": ["math"]},
            ],
        }

        # B confirms -> both confirmed -> problem revealed
        result = await ChallengeService.start_challenge(db, user_b, session.id, cf_mock)
        assert result.status == "problem_revealed"
        assert result.problem is not None
        assert result.problem.rating == 1200
        assert cf_mock.get_problemset_problems.called

        await _remove_pending(session.id)


# ---------------------------------------------------------------------------
# 4. ChallengeService - submit result
# ---------------------------------------------------------------------------


class TestSubmitResult:
    async def test_submit_result_not_found(self, db):
        user = _make_test_user(db, username="user1")
        db.add(user)
        await db.flush()

        with pytest.raises(NotFoundException):
            await ChallengeService.submit_result(db, user, uuid.uuid4(), True, 60.0, 1)

    async def test_submit_result_not_active(self, db):
        user_a = _make_test_user(db, username="user_a")
        user_b = _make_test_user(db, username="user_b")
        db.add_all([user_a, user_b])
        await db.flush()

        session = _make_test_session(user_a.id, user_b.id, status="completed")
        db.add(session)
        await db.flush()

        with pytest.raises(BadRequestException, match="not active"):
            await ChallengeService.submit_result(db, user_a, session.id, True, 60.0, 1)

    async def test_submit_first_result_waits_for_second(self, db):
        user_a = _make_test_user(db, username="user_a", elo=1200, tokens=0)
        user_b = _make_test_user(db, username="user_b", elo=1200, tokens=0)
        db.add_all([user_a, user_b])
        await db.flush()

        session = _make_test_session(user_a.id, user_b.id)
        db.add(session)
        await db.flush()

        result = await ChallengeService.submit_result(db, user_a, session.id, True, 60.0, 2)
        assert result.settled is False
        assert result.status == "result_submitted"

        # Verify challenger data saved
        await db.refresh(session)
        assert session.challenger_solved is True
        assert session.challenger_time == 60.0
        assert session.challenger_submissions == 2

    async def test_submit_duplicate_rejected(self, db):
        user_a = _make_test_user(db, username="user_a", elo=1200)
        user_b = _make_test_user(db, username="user_b", elo=1200)
        db.add_all([user_a, user_b])
        await db.flush()

        session = _make_test_session(user_a.id, user_b.id)
        db.add(session)
        await db.flush()

        await ChallengeService.submit_result(db, user_a, session.id, True, 60.0, 1)
        with pytest.raises(BadRequestException, match="Already submitted"):
            await ChallengeService.submit_result(db, user_a, session.id, False, 120.0, 2)


# ---------------------------------------------------------------------------
# 5. ChallengeService - settlement (both submitted)
# ---------------------------------------------------------------------------


def _setup_elo_mocks(mock_elo_cls):
    """Add K-factor related async mocks to an EloService mock."""
    mock_elo_cls.get_submission_count = AsyncMock(return_value=0)


def _setup_pp_mocks(mock_pp_cls):
    """Add calculate_overkill_multiplier mock to a PPService mock."""
    mock_pp_cls.calculate_overkill_multiplier = staticmethod(
        lambda *args, **kwargs: 1.0
    )


def _setup_config_mocks(mock_config_cls):
    """Add get_config mock to a ConfigService mock."""
    mock_config_cls.get_config = AsyncMock(return_value=_get_elo_config())


def _get_elo_config():
    """Return default elo config for tests."""
    return {
        "k_newbie": 40,
        "k_veteran": 20,
        "k_newbie_threshold": 20,
        "k_veteran_threshold": 100,
    }


class TestSettlement:
    @patch.object(challenge_svc_module, "ConfigService")
    @patch.object(challenge_svc_module, "PPService")
    @patch.object(challenge_svc_module, "EloService")
    async def test_settlement_challenger_wins(self, mock_elo_cls, mock_pp_cls, mock_config_cls, db):
        _setup_config_mocks(mock_config_cls)
        _setup_elo_mocks(mock_elo_cls)
        _setup_pp_mocks(mock_pp_cls)
        user_a = _make_test_user(db, username="user_a", elo=1200, tokens=0)
        user_b = _make_test_user(db, username="user_b", elo=1200, tokens=0)
        db.add_all([user_a, user_b])
        await db.flush()

        session = _make_test_session(user_a.id, user_b.id)
        db.add(session)
        await db.flush()

        # Challenger submits first (solved)
        await ChallengeService.submit_result(db, user_a, session.id, True, 60.0, 1)

        # Mock EloService for settlement
        mock_elo_cls.process_challenge_result = AsyncMock(return_value=(1230, 1170, 30, -30))
        mock_pp_cls.record_pp = AsyncMock()

        # Opponent submits (not solved) -> triggers settlement
        result = await ChallengeService.submit_result(db, user_b, session.id, False, 120.0, 3)
        assert result.settled is True
        # user_b is opponent, challenger won -> opponent sees "loss"
        assert result.result == "loss"

        await db.refresh(session)
        assert session.status == "completed"
        assert session.result == "challenger_win"
        assert session.elo_change == 30

    @patch.object(challenge_svc_module, "ConfigService")
    @patch.object(challenge_svc_module, "PPService")
    @patch.object(challenge_svc_module, "EloService")
    async def test_settlement_opponent_wins(self, mock_elo_cls, mock_pp_cls, mock_config_cls, db):
        _setup_config_mocks(mock_config_cls)
        _setup_elo_mocks(mock_elo_cls)
        _setup_pp_mocks(mock_pp_cls)
        user_a = _make_test_user(db, username="user_a", elo=1200, tokens=0)
        user_b = _make_test_user(db, username="user_b", elo=1200, tokens=0)
        db.add_all([user_a, user_b])
        await db.flush()

        session = _make_test_session(user_a.id, user_b.id)
        db.add(session)
        await db.flush()

        # Challenger submits (not solved)
        await ChallengeService.submit_result(db, user_a, session.id, False, 120.0, 3)

        mock_elo_cls.process_challenge_result = AsyncMock(return_value=(1170, 1230, -30, 30))
        mock_pp_cls.record_pp = AsyncMock()

        # Opponent submits (solved) -> settlement
        result = await ChallengeService.submit_result(db, user_b, session.id, True, 60.0, 1)
        assert result.settled is True
        # user_b is opponent, opponent won -> opponent sees "win"
        assert result.result == "win"

    @patch.object(challenge_svc_module, "ConfigService")
    @patch.object(challenge_svc_module, "PPService")
    @patch.object(challenge_svc_module, "EloService")
    async def test_settlement_both_solved_faster_wins(self, mock_elo_cls, mock_pp_cls, mock_config_cls, db):
        _setup_config_mocks(mock_config_cls)
        _setup_elo_mocks(mock_elo_cls)
        _setup_pp_mocks(mock_pp_cls)
        user_a = _make_test_user(db, username="user_a", elo=1200, tokens=0)
        user_b = _make_test_user(db, username="user_b", elo=1200, tokens=0)
        db.add_all([user_a, user_b])
        await db.flush()

        session = _make_test_session(user_a.id, user_b.id)
        db.add(session)
        await db.flush()

        # Challenger solved in 60s
        await ChallengeService.submit_result(db, user_a, session.id, True, 60.0, 1)

        mock_elo_cls.process_challenge_result = AsyncMock(return_value=(1230, 1170, 30, -30))
        mock_pp_cls.record_pp = AsyncMock()

        # Opponent solved in 90s -> challenger wins (faster)
        result = await ChallengeService.submit_result(db, user_b, session.id, True, 90.0, 1)
        assert result.settled is True
        # user_b is opponent, challenger won -> opponent sees "loss"
        assert result.result == "loss"

    @patch.object(challenge_svc_module, "ConfigService")
    @patch.object(challenge_svc_module, "PPService")
    @patch.object(challenge_svc_module, "EloService")
    async def test_settlement_neither_solved_draw(self, mock_elo_cls, mock_pp_cls, mock_config_cls, db):
        _setup_config_mocks(mock_config_cls)
        _setup_elo_mocks(mock_elo_cls)
        _setup_pp_mocks(mock_pp_cls)
        user_a = _make_test_user(db, username="user_a", elo=1200, tokens=0)
        user_b = _make_test_user(db, username="user_b", elo=1200, tokens=0)
        db.add_all([user_a, user_b])
        await db.flush()

        session = _make_test_session(user_a.id, user_b.id)
        db.add(session)
        await db.flush()

        await ChallengeService.submit_result(db, user_a, session.id, False, 120.0, 3)

        mock_elo_cls.process_challenge_result = AsyncMock(return_value=(1200, 1200, 0, 0))
        mock_pp_cls.record_pp = AsyncMock()

        result = await ChallengeService.submit_result(db, user_b, session.id, False, 120.0, 3)
        assert result.settled is True
        assert result.result == "draw"

    @patch.object(challenge_svc_module, "ConfigService")
    @patch.object(challenge_svc_module, "PPService")
    @patch.object(challenge_svc_module, "EloService")
    async def test_settlement_awards_tokens(self, mock_elo_cls, mock_pp_cls, mock_config_cls, db):
        _setup_config_mocks(mock_config_cls)
        _setup_elo_mocks(mock_elo_cls)
        _setup_pp_mocks(mock_pp_cls)
        user_a = _make_test_user(db, username="user_a", elo=1200, tokens=0)
        user_b = _make_test_user(db, username="user_b", elo=1200, tokens=0)
        db.add_all([user_a, user_b])
        await db.flush()

        session = _make_test_session(user_a.id, user_b.id)
        db.add(session)
        await db.flush()

        await ChallengeService.submit_result(db, user_a, session.id, True, 60.0, 1)

        mock_elo_cls.process_challenge_result = AsyncMock(return_value=(1230, 1170, 30, -30))
        mock_pp_cls.record_pp = AsyncMock()

        result = await ChallengeService.submit_result(db, user_b, session.id, False, 120.0, 3)
        assert result.settled is True

        # Winner should get tokens
        await db.refresh(user_a)
        assert user_a.tokens > 0


# ---------------------------------------------------------------------------
# 6. ChallengeService - quit challenge
# ---------------------------------------------------------------------------


class TestQuitChallenge:
    @patch.object(challenge_svc_module, "ConfigService")
    @patch.object(challenge_svc_module, "EloService")
    async def test_quit_zero_submissions(self, mock_elo_cls, mock_config_cls, db):
        _setup_config_mocks(mock_config_cls)
        _setup_elo_mocks(mock_elo_cls)
        user_a = _make_test_user(db, username="user_a", elo=1200)
        user_b = _make_test_user(db, username="user_b", elo=1200)
        db.add_all([user_a, user_b])
        await db.flush()

        session = _make_test_session(user_a.id, user_b.id)
        db.add(session)
        await db.flush()

        mock_elo_cls.process_quit_penalty = AsyncMock(return_value=(1200, 0))

        result = await ChallengeService.quit_challenge(db, user_a, session.id, submissions=0)
        assert result["status"] == "quit"
        assert result["penalty"] == 0

    @patch.object(challenge_svc_module, "ConfigService")
    @patch.object(challenge_svc_module, "EloService")
    async def test_quit_with_penalty(self, mock_elo_cls, mock_config_cls, db):
        _setup_config_mocks(mock_config_cls)
        _setup_elo_mocks(mock_elo_cls)
        user_a = _make_test_user(db, username="user_a", elo=1200)
        user_b = _make_test_user(db, username="user_b", elo=1200)
        db.add_all([user_a, user_b])
        await db.flush()

        session = _make_test_session(user_a.id, user_b.id)
        db.add(session)
        await db.flush()

        mock_elo_cls.process_quit_penalty = AsyncMock(return_value=(1192, -8))

        result = await ChallengeService.quit_challenge(db, user_a, session.id, submissions=2)
        assert result["status"] == "quit"
        assert result["elo_change"] == -8
        assert result["penalty"] == 8

    async def test_quit_not_participant(self, db):
        user_a = _make_test_user(db, username="user_a")
        user_b = _make_test_user(db, username="user_b")
        outsider = _make_test_user(db, username="outsider")
        db.add_all([user_a, user_b, outsider])
        await db.flush()

        session = _make_test_session(user_a.id, user_b.id)
        db.add(session)
        await db.flush()

        with pytest.raises(ForbiddenException, match="Not a participant"):
            await ChallengeService.quit_challenge(db, outsider, session.id, submissions=0)

    async def test_quit_completed_session_rejected(self, db):
        user_a = _make_test_user(db, username="user_a")
        user_b = _make_test_user(db, username="user_b")
        db.add_all([user_a, user_b])
        await db.flush()

        session = _make_test_session(user_a.id, user_b.id, status="completed")
        db.add(session)
        await db.flush()

        with pytest.raises(BadRequestException, match="not active"):
            await ChallengeService.quit_challenge(db, user_a, session.id, submissions=0)


# ---------------------------------------------------------------------------
# 7. ChallengeService - get challenge detail
# ---------------------------------------------------------------------------


class TestGetChallengeDetail:
    async def test_get_detail_success(self, db):
        user_a = _make_test_user(db, username="user_a")
        user_b = _make_test_user(db, username="user_b")
        db.add_all([user_a, user_b])
        await db.flush()

        session = _make_test_session(user_a.id, user_b.id)
        db.add(session)
        await db.flush()

        result = await ChallengeService.get_challenge_detail(db, user_a, session.id)
        assert result.id == session.id
        assert result.problem_id == "800A"
        assert result.problem_rating == 1200

    async def test_get_detail_not_participant(self, db):
        user_a = _make_test_user(db, username="user_a")
        user_b = _make_test_user(db, username="user_b")
        outsider = _make_test_user(db, username="outsider")
        db.add_all([user_a, user_b, outsider])
        await db.flush()

        session = _make_test_session(user_a.id, user_b.id)
        db.add(session)
        await db.flush()

        with pytest.raises(ForbiddenException, match="Not a participant"):
            await ChallengeService.get_challenge_detail(db, outsider, session.id)

    async def test_get_detail_not_found(self, db):
        user = _make_test_user(db, username="user1")
        db.add(user)
        await db.flush()

        with pytest.raises(NotFoundException):
            await ChallengeService.get_challenge_detail(db, user, uuid.uuid4())


# ---------------------------------------------------------------------------
# 8. Token reward tiers
# ---------------------------------------------------------------------------


class TestTokenTiers:
    def test_tokens_for_gray_rating(self):
        # gray (800-1199)
        assert _tokens_for_rating(500) == 10
        assert _tokens_for_rating(800) == 10
        assert _tokens_for_rating(1199) == 10

    def test_tokens_for_green_rating(self):
        # green (1200-1399)
        assert _tokens_for_rating(1200) == 20
        assert _tokens_for_rating(1300) == 20
        assert _tokens_for_rating(1399) == 20

    def test_tokens_for_cyan_rating(self):
        # cyan (1400-1599)
        assert _tokens_for_rating(1400) == 25
        assert _tokens_for_rating(1500) == 25
        assert _tokens_for_rating(1599) == 25

    def test_tokens_for_blue_rating(self):
        # blue (1600-1899)
        assert _tokens_for_rating(1600) == 35
        assert _tokens_for_rating(1750) == 35
        assert _tokens_for_rating(1899) == 35

    def test_tokens_for_purple_rating(self):
        # purple (1900-2099)
        assert _tokens_for_rating(1900) == 45
        assert _tokens_for_rating(2000) == 45
        assert _tokens_for_rating(2099) == 45

    def test_tokens_for_orange_rating(self):
        # orange (2100-2399)
        assert _tokens_for_rating(2100) == 55
        assert _tokens_for_rating(2250) == 55
        assert _tokens_for_rating(2399) == 55

    def test_tokens_for_red_rating(self):
        # red (2400+)
        assert _tokens_for_rating(2400) == 65
        assert _tokens_for_rating(2500) == 65
        assert _tokens_for_rating(3000) == 65
        assert _tokens_for_rating(3500) == 65


# ---------------------------------------------------------------------------
# 9. Problem info builder
# ---------------------------------------------------------------------------


class TestBuildProblemInfo:
    def test_standard_problem_id(self):
        info = _build_problem_info("1234A", 1200)
        assert info.contest_id == 1234
        assert info.index == "A"
        assert info.rating == 1200
        assert "1234" in info.url and "A" in info.url

    def test_multi_letter_index(self):
        info = _build_problem_info("5678AB", 1500)
        assert info.contest_id == 5678
        assert info.index == "AB"
        assert info.rating == 1500

    def test_no_numeric_prefix(self):
        info = _build_problem_info("ABC", 800)
        assert info.contest_id == 0
        assert info.index == "ABC"


# ---------------------------------------------------------------------------
# 10. Full challenge flow integration test
# ---------------------------------------------------------------------------


class TestFullChallengeFlow:
    """Integration test for the complete challenge lifecycle."""

    @patch.object(challenge_svc_module, "ConfigService")
    @patch.object(challenge_svc_module, "PPService")
    @patch.object(challenge_svc_module, "EloService")
    async def test_complete_flow(self, mock_elo_cls, mock_pp_cls, mock_config_cls, db, match_service):
        _setup_config_mocks(mock_config_cls)
        _setup_elo_mocks(mock_elo_cls)
        _setup_pp_mocks(mock_pp_cls)
        # Create two users
        user_a = _make_test_user(db, username="player_a", elo=1200, tokens=0)
        user_b = _make_test_user(db, username="player_b", elo=1250, tokens=0)
        db.add_all([user_a, user_b])
        await db.flush()

        # Step 1: User A joins queue (no match)
        result_a = await ChallengeService.join_queue(db, user_a, match_service)
        assert result_a["matched"] is False

        # Step 2: User B joins queue (match found)
        result_b = await ChallengeService.join_queue(db, user_b, match_service)
        assert result_b["matched"] is True
        session_id = uuid.UUID(result_b["session_id"])

        # Step 3: Confirm start with CF mock
        cf_mock = AsyncMock()
        cf_mock.get_problemset_problems.return_value = {
            "problems": [
                {"contestId": 1500, "index": "C", "name": "Flow Test Problem", "rating": 1200, "tags": ["dp"]},
            ],
        }

        # Set up pending state (normally done by join_queue)
        await _set_pending(session_id, {
            "player_a_id": user_a.id,
            "player_b_id": user_b.id,
            "avg_elo": 1225.0,
            "confirmed": set(),
        })

        # Player A confirms first -> waiting
        start_a = await ChallengeService.start_challenge(db, user_a, session_id, cf_mock)
        assert start_a.status == "waiting_opponent"

        # Player B confirms -> problem revealed
        start_b = await ChallengeService.start_challenge(db, user_b, session_id, cf_mock)
        assert start_b.status == "problem_revealed"
        assert start_b.problem.rating == 1200

        # Step 4: Submit results
        mock_elo_cls.process_challenge_result = AsyncMock(return_value=(1232, 1218, 32, -32))
        mock_pp_cls.record_pp = AsyncMock()

        # Player A submits (solved, 60s)
        submit_a = await ChallengeService.submit_result(db, user_a, session_id, True, 60.0, 1)
        assert submit_a.settled is False

        # Player B submits (not solved) -> triggers settlement
        # Note: user_b is the challenger (joined second and triggered match),
        # user_a is the opponent. Since user_a solved and user_b didn't,
        # the DB result is "opponent_win". From user_b's (challenger's) perspective,
        # opponent winning means "loss".
        submit_b = await ChallengeService.submit_result(db, user_b, session_id, False, 120.0, 3)
        assert submit_b.settled is True
        assert submit_b.result == "loss"

        # Verify session completed
        test_session = await db.get(_TestChallengeSession, session_id)
        assert test_session is not None
        assert test_session.status == "completed"
        assert test_session.result == "opponent_win"

        # Verify user tokens updated (opponent = user_a wins)
        await db.refresh(user_a)
        assert user_a.tokens > 0


# ---------------------------------------------------------------------------
# 11. Queue status tests
# ---------------------------------------------------------------------------


class TestQueueStatus:
    async def test_status_not_in_queue(self, db, match_service):
        user = _make_test_user(db, username="user1")
        db.add(user)
        await db.flush()

        result = await ChallengeService.get_queue_status(db, user, match_service)
        assert result["in_queue"] is False
        assert result["matched"] is False

    async def test_status_in_queue(self, db, match_service):
        user = _make_test_user(db, username="user1")
        db.add(user)
        await db.flush()

        await ChallengeService.join_queue(db, user, match_service)
        result = await ChallengeService.get_queue_status(db, user, match_service)
        assert result["in_queue"] is True
        assert result["matched"] is False

    async def test_status_matched_pending(self, db, match_service):
        user_a = _make_test_user(db, username="user_a", elo=1200)
        user_b = _make_test_user(db, username="user_b", elo=1200)
        db.add_all([user_a, user_b])
        await db.flush()

        await ChallengeService.join_queue(db, user_a, match_service)
        result_b = await ChallengeService.join_queue(db, user_b, match_service)
        assert result_b["matched"] is True

        status = await ChallengeService.get_queue_status(db, user_a, match_service)
        assert status["matched"] is True
        assert status["session_id"] == result_b["session_id"]


# ---------------------------------------------------------------------------
# 12. Pending match state (Redis-backed)
# ---------------------------------------------------------------------------


class TestPendingState:
    async def test_set_and_get_pending(self, fake_redis):
        with patch("app.services.challenge_service.get_redis", return_value=fake_redis):
            sid = uuid.uuid4()
            data = {"confirmed": set(), "avg_elo": 1200.0, "player_a_id": uuid.uuid4(), "player_b_id": uuid.uuid4()}
            await _set_pending(sid, data)
            result = await _get_pending(sid)
            assert result is not None
            assert result["avg_elo"] == 1200.0

    async def test_remove_pending(self, fake_redis):
        with patch("app.services.challenge_service.get_redis", return_value=fake_redis):
            sid = uuid.uuid4()
            await _set_pending(sid, {
                "confirmed": set(),
                "player_a_id": uuid.uuid4(),
                "player_b_id": uuid.uuid4(),
                "avg_elo": 1000,
            })
            await _remove_pending(sid)
            result = await _get_pending(sid)
            assert result is None

    async def test_remove_nonexistent_pending(self, fake_redis):
        with patch("app.services.challenge_service.get_redis", return_value=fake_redis):
            await _remove_pending(uuid.uuid4())  # Should not raise

    async def test_pending_ttl_expiry(self, fake_redis):
        """Verify that pending keys have TTL set."""
        with patch("app.services.challenge_service.get_redis", return_value=fake_redis):
            sid = uuid.uuid4()
            await _set_pending(sid, {
                "confirmed": set(),
                "player_a_id": uuid.uuid4(),
                "player_b_id": uuid.uuid4(),
                "avg_elo": 1000,
            })
            ttl = await fake_redis.ttl(_pending_key(sid))
            assert ttl > 0  # Should have a TTL
            assert ttl <= 300  # Should be at most 5 minutes

    async def test_pending_confirmed_set_roundtrip(self, fake_redis):
        """Verify that the confirmed set survives serialization/deserialization."""
        with patch("app.services.challenge_service.get_redis", return_value=fake_redis):
            uid_a = uuid.uuid4()
            uid_b = uuid.uuid4()
            sid = uuid.uuid4()
            data = {"confirmed": {uid_a}, "player_a_id": uid_a, "player_b_id": uid_b, "avg_elo": 1500.0}
            await _set_pending(sid, data)

            result = await _get_pending(sid)
            assert result is not None
            assert uid_a in result["confirmed"]
            assert uid_b not in result["confirmed"]


# ---------------------------------------------------------------------------
# 13. Problem name persistence
# ---------------------------------------------------------------------------


class TestProblemNamePersistence:
    async def test_problem_name_saved_on_start(self, db):
        """When both confirm start and a problem is selected, problem_name is saved to session."""
        user_a = _make_test_user(db, username="user_a", elo=1200)
        user_b = _make_test_user(db, username="user_b", elo=1200)
        db.add_all([user_a, user_b])
        await db.flush()

        session = _make_test_session(user_a.id, user_b.id, status="pending")
        db.add(session)
        await db.flush()

        # Set up pending state with A already confirmed
        await _set_pending(session.id, {
            "player_a_id": user_a.id,
            "player_b_id": user_b.id,
            "avg_elo": 1200.0,
            "confirmed": {user_a.id},
        })

        cf_mock = AsyncMock()
        cf_mock.get_problemset_problems.return_value = {
            "problems": [
                {
                    "contestId": 1234,
                    "index": "B",
                    "name": "Interesting Problem Name",
                    "rating": 1200,
                    "tags": ["dp"],
                },
            ],
        }

        # B confirms -> both confirmed -> problem selected
        result = await ChallengeService.start_challenge(db, user_b, session.id, cf_mock)
        assert result.status == "problem_revealed"
        assert result.problem.name == "Interesting Problem Name"

        # Verify problem_name persisted to DB
        await db.refresh(session)
        assert session.problem_name == "Interesting Problem Name"

        await _remove_pending(session.id)

    async def test_problem_name_in_detail(self, db):
        """get_challenge_detail returns the persisted problem_name."""
        user_a = _make_test_user(db, username="user_a")
        user_b = _make_test_user(db, username="user_b")
        db.add_all([user_a, user_b])
        await db.flush()

        session = _make_test_session(user_a.id, user_b.id)
        session.problem_name = "Persisted Problem Name"
        db.add(session)
        await db.flush()

        detail = await ChallengeService.get_challenge_detail(db, user_a, session.id)
        assert detail.problem is not None
        assert detail.problem.name == "Persisted Problem Name"

    async def test_problem_name_fallback_to_problem_id(self, db):
        """When problem_name is null, _build_problem_info falls back to problem_id."""
        user_a = _make_test_user(db, username="user_a")
        user_b = _make_test_user(db, username="user_b")
        db.add_all([user_a, user_b])
        await db.flush()

        session = _make_test_session(user_a.id, user_b.id, problem_id="1234C")
        # problem_name is None (default)
        db.add(session)
        await db.flush()

        detail = await ChallengeService.get_challenge_detail(db, user_a, session.id)
        assert detail.problem is not None
        assert detail.problem.name == "1234C"  # Falls back to problem_id

    def test_build_problem_info_with_name(self):
        """_build_problem_info uses provided problem_name."""
        info = _build_problem_info("1234A", 1200, problem_name="Theatre Square")
        assert info.name == "Theatre Square"
        assert info.contest_id == 1234
        assert info.index == "A"

    def test_build_problem_info_without_name(self):
        """_build_problem_info falls back to problem_id when name is None."""
        info = _build_problem_info("1234A", 1200)
        assert info.name == "1234A"


# ---------------------------------------------------------------------------
# 14. Settlement stores opponent fields
# ---------------------------------------------------------------------------


class TestSettlementOpponentFields:
    @patch.object(challenge_svc_module, "ConfigService")
    @patch.object(challenge_svc_module, "PPService")
    @patch.object(challenge_svc_module, "EloService")
    async def test_settlement_stores_opponent_elo_change(self, mock_elo_cls, mock_pp_cls, mock_config_cls, db):
        """_settle_challenge saves opponent_elo_change to the session."""
        _setup_config_mocks(mock_config_cls)
        _setup_elo_mocks(mock_elo_cls)
        _setup_pp_mocks(mock_pp_cls)

        user_a = _make_test_user(db, username="user_a", elo=1200, tokens=0)
        user_b = _make_test_user(db, username="user_b", elo=1300, tokens=0)
        db.add_all([user_a, user_b])
        await db.flush()

        session = _make_test_session(user_a.id, user_b.id, problem_rating=1200)
        db.add(session)
        await db.flush()

        await ChallengeService.submit_result(db, user_a, session.id, True, 60.0, 1)

        mock_elo_cls.process_challenge_result = AsyncMock(return_value=(1230, 1270, 30, -30))
        mock_pp_cls.record_pp = AsyncMock()

        result = await ChallengeService.submit_result(db, user_b, session.id, False, 120.0, 3)
        assert result.settled is True

        await db.refresh(session)
        assert session.elo_change == 30
        assert session.opponent_elo_change == -30

    @patch.object(challenge_svc_module, "ConfigService")
    @patch.object(challenge_svc_module, "PPService")
    @patch.object(challenge_svc_module, "EloService")
    async def test_settlement_stores_opponent_tokens_earned(self, mock_elo_cls, mock_pp_cls, mock_config_cls, db):
        """_settle_challenge saves opponent_tokens_earned to the session."""
        _setup_config_mocks(mock_config_cls)
        _setup_elo_mocks(mock_elo_cls)
        _setup_pp_mocks(mock_pp_cls)

        user_a = _make_test_user(db, username="user_a", elo=1200, tokens=0)
        user_b = _make_test_user(db, username="user_b", elo=1200, tokens=0)
        db.add_all([user_a, user_b])
        await db.flush()

        session = _make_test_session(user_a.id, user_b.id, problem_rating=1200)
        db.add(session)
        await db.flush()

        await ChallengeService.submit_result(db, user_a, session.id, False, 120.0, 3)

        mock_elo_cls.process_challenge_result = AsyncMock(return_value=(1170, 1230, -30, 30))
        mock_pp_cls.record_pp = AsyncMock()

        # Opponent wins -> gets tokens
        result = await ChallengeService.submit_result(db, user_b, session.id, True, 60.0, 1)
        assert result.settled is True
        # user_b is opponent, opponent won -> sees "win"
        assert result.result == "win"

        await db.refresh(session)
        # Rating 1200 -> green tier -> 20 tokens for winner
        assert session.opponent_tokens_earned == 20
        # Challenger got 0 tokens (lost)
        assert session.elo_change == -30

    @patch.object(challenge_svc_module, "ConfigService")
    @patch.object(challenge_svc_module, "PPService")
    @patch.object(challenge_svc_module, "EloService")
    async def test_settlement_detail_includes_opponent_fields(self, mock_elo_cls, mock_pp_cls, mock_config_cls, db):
        """get_challenge_detail returns opponent_elo_change and opponent_tokens_earned."""
        _setup_config_mocks(mock_config_cls)
        _setup_elo_mocks(mock_elo_cls)
        _setup_pp_mocks(mock_pp_cls)

        user_a = _make_test_user(db, username="user_a", elo=1200, tokens=0)
        user_b = _make_test_user(db, username="user_b", elo=1200, tokens=0)
        db.add_all([user_a, user_b])
        await db.flush()

        session = _make_test_session(user_a.id, user_b.id, problem_rating=1400)
        db.add(session)
        await db.flush()

        await ChallengeService.submit_result(db, user_a, session.id, True, 60.0, 1)

        mock_elo_cls.process_challenge_result = AsyncMock(return_value=(1230, 1170, 30, -30))
        mock_pp_cls.record_pp = AsyncMock()

        await ChallengeService.submit_result(db, user_b, session.id, False, 120.0, 3)

        # Now fetch the detail
        detail = await ChallengeService.get_challenge_detail(db, user_a, session.id)
        assert detail.opponent_elo_change == -30
        # Opponent lost but made 3 submissions -> gets attempt tokens
        # Rating 1400 -> cyan tier -> attempt_tokens = 4
        assert detail.opponent_tokens_earned == 4


# ---------------------------------------------------------------------------
# Perspective transformation tests
# ---------------------------------------------------------------------------


class TestPerspectiveTransformation:
    """Tests for _result_for_user, _elo_change_for_user helper methods."""

    @pytest.mark.parametrize(
        "db_result,is_challenger,expected",
        [
            ("draw", True, "draw"),
            ("draw", False, "draw"),
            ("challenger_win", True, "win"),
            ("challenger_win", False, "loss"),
            ("opponent_win", True, "loss"),
            ("opponent_win", False, "win"),
            ("challenger_quit", True, "quit"),
            ("challenger_quit", False, "win"),
            ("opponent_quit", True, "win"),
            ("opponent_quit", False, "quit"),
        ],
    )
    async def test_result_for_user_all_cases(self, db, db_result, is_challenger, expected):
        """_result_for_user converts DB result to user perspective correctly."""
        user_a = _make_test_user(db, username="user_a", elo=1200, tokens=0)
        user_b = _make_test_user(db, username="user_b", elo=1200, tokens=0)
        db.add_all([user_a, user_b])
        await db.flush()

        session = _make_test_session(user_a.id, user_b.id)
        session.result = db_result
        session.elo_change = 30
        session.opponent_elo_change = -30
        db.add(session)
        await db.flush()

        user_id = user_a.id if is_challenger else user_b.id
        assert _result_for_user(session, user_id) == expected

    async def test_result_for_user_none(self, db):
        """_result_for_user returns None when session has no result."""
        user_a = _make_test_user(db, username="user_a", elo=1200, tokens=0)
        user_b = _make_test_user(db, username="user_b", elo=1200, tokens=0)
        db.add_all([user_a, user_b])
        await db.flush()

        session = _make_test_session(user_a.id, user_b.id)
        session.result = None
        db.add(session)
        await db.flush()

        assert _result_for_user(session, user_a.id) is None

    async def test_elo_change_for_user_challenger(self, db):
        """_elo_change_for_user returns session.elo_change for challenger."""
        user_a = _make_test_user(db, username="user_a", elo=1200, tokens=0)
        user_b = _make_test_user(db, username="user_b", elo=1200, tokens=0)
        db.add_all([user_a, user_b])
        await db.flush()

        session = _make_test_session(user_a.id, user_b.id)
        session.elo_change = 25
        session.opponent_elo_change = -25
        db.add(session)
        await db.flush()

        assert _elo_change_for_user(session, user_a.id) == 25

    async def test_elo_change_for_user_opponent(self, db):
        """_elo_change_for_user returns session.opponent_elo_change for opponent."""
        user_a = _make_test_user(db, username="user_a", elo=1200, tokens=0)
        user_b = _make_test_user(db, username="user_b", elo=1200, tokens=0)
        db.add_all([user_a, user_b])
        await db.flush()

        session = _make_test_session(user_a.id, user_b.id)
        session.elo_change = 25
        session.opponent_elo_change = -25
        db.add(session)
        await db.flush()

        assert _elo_change_for_user(session, user_b.id) == -25

    @patch.object(challenge_svc_module, "ConfigService")
    @patch.object(challenge_svc_module, "PPService")
    @patch.object(challenge_svc_module, "EloService")
    async def test_get_detail_returns_user_perspective_result(self, mock_elo_cls, mock_pp_cls, mock_config_cls, db):
        """get_challenge_detail returns result and elo_change from the requesting user's perspective."""
        _setup_config_mocks(mock_config_cls)
        _setup_elo_mocks(mock_elo_cls)
        _setup_pp_mocks(mock_pp_cls)

        user_a = _make_test_user(db, username="user_a", elo=1200, tokens=0)
        user_b = _make_test_user(db, username="user_b", elo=1200, tokens=0)
        db.add_all([user_a, user_b])
        await db.flush()

        session = _make_test_session(user_a.id, user_b.id, problem_rating=1200)
        db.add(session)
        await db.flush()

        # Challenger (user_a) solved, opponent (user_b) didn't -> challenger_win
        await ChallengeService.submit_result(db, user_a, session.id, True, 60.0, 1)

        mock_elo_cls.process_challenge_result = AsyncMock(return_value=(1230, 1170, 30, -30))
        mock_pp_cls.record_pp = AsyncMock()

        await ChallengeService.submit_result(db, user_b, session.id, False, 120.0, 3)

        # Challenger (user_a) sees "win"
        detail_a = await ChallengeService.get_challenge_detail(db, user_a, session.id)
        assert detail_a.result == "win"
        assert detail_a.elo_change == 30
        assert detail_a.is_challenger is True

        # Opponent (user_b) sees "loss"
        detail_b = await ChallengeService.get_challenge_detail(db, user_b, session.id)
        assert detail_b.result == "loss"
        assert detail_b.elo_change == -30
        assert detail_b.is_challenger is False

        # DB session result unchanged
        await db.refresh(session)
        assert session.result == "challenger_win"

    @patch.object(challenge_svc_module, "ConfigService")
    @patch.object(challenge_svc_module, "PPService")
    @patch.object(challenge_svc_module, "EloService")
    async def test_submit_result_returns_perspective_elo_and_tokens(
        self, mock_elo_cls, mock_pp_cls, mock_config_cls, db,
    ):
        """submit_result returns elo_change and tokens_earned from the submitting user's perspective."""
        _setup_config_mocks(mock_config_cls)
        _setup_elo_mocks(mock_elo_cls)
        _setup_pp_mocks(mock_pp_cls)

        user_a = _make_test_user(db, username="user_a", elo=1200, tokens=0)
        user_b = _make_test_user(db, username="user_b", elo=1200, tokens=0)
        db.add_all([user_a, user_b])
        await db.flush()

        session = _make_test_session(user_a.id, user_b.id, problem_rating=1500)
        db.add(session)
        await db.flush()

        # Opponent (user_b) submits first (solved)
        await ChallengeService.submit_result(db, user_b, session.id, True, 60.0, 1)

        mock_elo_cls.process_challenge_result = AsyncMock(return_value=(1170, 1230, -30, 30))
        mock_pp_cls.record_pp = AsyncMock()

        # Challenger (user_a) submits (not solved) -> triggers settlement
        result = await ChallengeService.submit_result(db, user_a, session.id, False, 120.0, 3)
        assert result.settled is True
        # user_a is challenger, opponent won -> "loss"
        assert result.result == "loss"
        # Challenger elo change is -30
        assert result.elo_change == -30
        # Challenger lost but made 3 submissions -> gets attempt tokens
        # Rating 1500 -> cyan tier -> attempt_tokens = 4
        assert result.tokens_earned == 4

    async def test_quit_returns_quit_result_for_quitter(self, db):
        """quit_challenge returns 'quit' result for the quitter."""
        user_a = _make_test_user(db, username="user_a", elo=1200, tokens=0)
        user_b = _make_test_user(db, username="user_b", elo=1200, tokens=0)
        db.add_all([user_a, user_b])
        await db.flush()

        session = _make_test_session(user_a.id, user_b.id, problem_rating=1200)
        session.status = "active"
        db.add(session)
        await db.flush()

        with (
            patch.object(challenge_svc_module, "ConfigService") as mock_config_cls,
            patch.object(challenge_svc_module, "EloService") as mock_elo_cls,
        ):
            _setup_config_mocks(mock_config_cls)
            mock_elo_cls.get_submission_count = AsyncMock(return_value=0)
            mock_elo_cls.process_quit_penalty = AsyncMock(return_value=(1180, -20))

            result = await ChallengeService.quit_challenge(
                db, user_a, session.id, submissions=1,
            )
            assert result["result"] == "quit"
            assert result["elo_change"] == -20


# ---------------------------------------------------------------------------
# BUG-001: quit_challenge elo_change semantic consistency
# ---------------------------------------------------------------------------


class TestQuitEloChangeSemantics:
    """Verify that session.elo_change always stores challenger's Elo change
    and session.opponent_elo_change always stores opponent's Elo change,
    regardless of who quit.
    """

    @patch.object(challenge_svc_module, "ConfigService")
    @patch.object(challenge_svc_module, "EloService")
    async def test_challenger_quit_stores_challenger_penalty_in_elo_change(
        self, mock_elo_cls, mock_config_cls, db,
    ):
        """When challenger quits with 1-2 submissions, session.elo_change = challenger's penalty."""
        _setup_config_mocks(mock_config_cls)
        mock_elo_cls.get_submission_count = AsyncMock(return_value=0)
        mock_elo_cls.process_quit_penalty = AsyncMock(return_value=(1185, -15))

        user_a = _make_test_user(db, username="user_a", elo=1200, tokens=0)
        user_b = _make_test_user(db, username="user_b", elo=1200, tokens=0)
        db.add_all([user_a, user_b])
        await db.flush()

        session = _make_test_session(user_a.id, user_b.id)
        session.status = "active"
        db.add(session)
        await db.flush()

        await ChallengeService.quit_challenge(db, user_a, session.id, submissions=1)

        await db.refresh(session)
        assert session.elo_change == -15  # challenger's penalty
        assert session.opponent_elo_change == 0  # opponent unaffected
        assert session.result == "challenger_quit"

    @patch.object(challenge_svc_module, "ConfigService")
    @patch.object(challenge_svc_module, "EloService")
    async def test_opponent_quit_stores_opponent_penalty_in_opponent_elo_change(
        self, mock_elo_cls, mock_config_cls, db,
    ):
        """When opponent quits with 1-2 submissions, session.opponent_elo_change = opponent's penalty."""
        _setup_config_mocks(mock_config_cls)
        mock_elo_cls.get_submission_count = AsyncMock(return_value=0)
        mock_elo_cls.process_quit_penalty = AsyncMock(return_value=(1185, -15))

        user_a = _make_test_user(db, username="user_a", elo=1200, tokens=0)
        user_b = _make_test_user(db, username="user_b", elo=1200, tokens=0)
        db.add_all([user_a, user_b])
        await db.flush()

        session = _make_test_session(user_a.id, user_b.id)
        session.status = "active"
        db.add(session)
        await db.flush()

        await ChallengeService.quit_challenge(db, user_b, session.id, submissions=1)

        await db.refresh(session)
        assert session.elo_change == 0  # challenger unaffected
        assert session.opponent_elo_change == -15  # opponent's penalty
        assert session.result == "opponent_quit"

    @patch.object(challenge_svc_module, "ConfigService")
    @patch.object(challenge_svc_module, "EloService")
    async def test_challenger_quit_3plus_submissions_stores_both_elo_changes(
        self, mock_elo_cls, mock_config_cls, db,
    ):
        """When challenger quits with 3+ submissions, both Elo changes are stored correctly."""
        _setup_config_mocks(mock_config_cls)
        mock_elo_cls.get_submission_count = AsyncMock(return_value=0)
        # 3+ submissions: process_quit_penalty treats as normal loss
        # Returns (new_rating_for_quitter, elo_change_for_quitter)
        mock_elo_cls.process_quit_penalty = AsyncMock(return_value=(1170, -30))

        user_a = _make_test_user(db, username="user_a", elo=1200, tokens=0)
        user_b = _make_test_user(db, username="user_b", elo=1300, tokens=0)
        db.add_all([user_a, user_b])
        await db.flush()

        session = _make_test_session(user_a.id, user_b.id)
        session.status = "active"
        db.add(session)
        await db.flush()

        await ChallengeService.quit_challenge(db, user_a, session.id, submissions=3)

        await db.refresh(session)
        assert session.elo_change == -30  # challenger's loss
        # opponent_elo_change should be computed from opponent's updated Elo
        # process_quit_penalty updated opponent Elo to (1300 + positive change)
        await db.refresh(user_b)
        opponent_change = user_b.elo - 1300
        assert session.opponent_elo_change == opponent_change

    @patch.object(challenge_svc_module, "ConfigService")
    @patch.object(challenge_svc_module, "EloService")
    async def test_opponent_quit_3plus_submissions_stores_both_elo_changes(
        self, mock_elo_cls, mock_config_cls, db,
    ):
        """When opponent quits with 3+ submissions, both Elo changes are stored correctly."""
        _setup_config_mocks(mock_config_cls)
        mock_elo_cls.get_submission_count = AsyncMock(return_value=0)
        mock_elo_cls.process_quit_penalty = AsyncMock(return_value=(1270, -30))

        user_a = _make_test_user(db, username="user_a", elo=1200, tokens=0)
        user_b = _make_test_user(db, username="user_b", elo=1300, tokens=0)
        db.add_all([user_a, user_b])
        await db.flush()

        session = _make_test_session(user_a.id, user_b.id)
        session.status = "active"
        db.add(session)
        await db.flush()

        await ChallengeService.quit_challenge(db, user_b, session.id, submissions=3)

        await db.refresh(session)
        # challenger Elo should reflect the win
        await db.refresh(user_a)
        challenger_change = user_a.elo - 1200
        assert session.elo_change == challenger_change
        assert session.opponent_elo_change == -30  # opponent's loss

    @patch.object(challenge_svc_module, "ConfigService")
    @patch.object(challenge_svc_module, "EloService")
    async def test_quit_detail_shows_correct_elo_change_for_both_players(
        self, mock_elo_cls, mock_config_cls, db,
    ):
        """After opponent quits, both players see correct elo_change in detail."""
        _setup_config_mocks(mock_config_cls)
        mock_elo_cls.get_submission_count = AsyncMock(return_value=0)
        mock_elo_cls.process_quit_penalty = AsyncMock(return_value=(1185, -15))

        user_a = _make_test_user(db, username="user_a", elo=1200, tokens=0)
        user_b = _make_test_user(db, username="user_b", elo=1200, tokens=0)
        db.add_all([user_a, user_b])
        await db.flush()

        session = _make_test_session(user_a.id, user_b.id)
        session.status = "active"
        db.add(session)
        await db.flush()

        # Opponent (user_b) quits
        await ChallengeService.quit_challenge(db, user_b, session.id, submissions=1)

        # Challenger (user_a) sees 0 elo change
        detail_a = await ChallengeService.get_challenge_detail(db, user_a, session.id)
        assert detail_a.result == "win"
        assert detail_a.elo_change == 0  # challenger unaffected

        # Opponent (user_b) sees -15 elo change
        detail_b = await ChallengeService.get_challenge_detail(db, user_b, session.id)
        assert detail_b.result == "quit"
        assert detail_b.elo_change == -15  # opponent's penalty


# ---------------------------------------------------------------------------
# BUG-002: ChallengeDetail tokens_earned + challenger_tokens persistence
# ---------------------------------------------------------------------------


class TestChallengerTokensPersistence:
    """Verify that challenger_tokens_earned is persisted and returned in detail."""

    @patch.object(challenge_svc_module, "ConfigService")
    @patch.object(challenge_svc_module, "PPService")
    @patch.object(challenge_svc_module, "EloService")
    async def test_settlement_stores_challenger_tokens_earned(
        self, mock_elo_cls, mock_pp_cls, mock_config_cls, db,
    ):
        """_settle_challenge saves challenger_tokens_earned to the session."""
        _setup_config_mocks(mock_config_cls)
        _setup_elo_mocks(mock_elo_cls)
        _setup_pp_mocks(mock_pp_cls)

        user_a = _make_test_user(db, username="user_a", elo=1200, tokens=0)
        user_b = _make_test_user(db, username="user_b", elo=1200, tokens=0)
        db.add_all([user_a, user_b])
        await db.flush()

        session = _make_test_session(user_a.id, user_b.id, problem_rating=1200)
        db.add(session)
        await db.flush()

        # Challenger solves, opponent does not
        await ChallengeService.submit_result(db, user_a, session.id, True, 60.0, 1)

        mock_elo_cls.process_challenge_result = AsyncMock(return_value=(1230, 1170, 30, -30))
        mock_pp_cls.record_pp = AsyncMock()

        await ChallengeService.submit_result(db, user_b, session.id, False, 120.0, 3)

        await db.refresh(session)
        # Rating 1200 -> green tier -> 20 tokens for winner (challenger)
        assert session.challenger_tokens_earned == 20
        # Opponent made 3 submissions but didn't solve -> attempt tokens = 3
        assert session.opponent_tokens_earned == 3

    @patch.object(challenge_svc_module, "ConfigService")
    @patch.object(challenge_svc_module, "PPService")
    @patch.object(challenge_svc_module, "EloService")
    async def test_detail_returns_tokens_earned_for_challenger(
        self, mock_elo_cls, mock_pp_cls, mock_config_cls, db,
    ):
        """get_challenge_detail returns tokens_earned from challenger's perspective."""
        _setup_config_mocks(mock_config_cls)
        _setup_elo_mocks(mock_elo_cls)
        _setup_pp_mocks(mock_pp_cls)

        user_a = _make_test_user(db, username="user_a", elo=1200, tokens=0)
        user_b = _make_test_user(db, username="user_b", elo=1200, tokens=0)
        db.add_all([user_a, user_b])
        await db.flush()

        session = _make_test_session(user_a.id, user_b.id, problem_rating=1200)
        db.add(session)
        await db.flush()

        await ChallengeService.submit_result(db, user_a, session.id, True, 60.0, 1)

        mock_elo_cls.process_challenge_result = AsyncMock(return_value=(1230, 1170, 30, -30))
        mock_pp_cls.record_pp = AsyncMock()

        await ChallengeService.submit_result(db, user_b, session.id, False, 120.0, 3)

        detail = await ChallengeService.get_challenge_detail(db, user_a, session.id)
        assert detail.tokens_earned == 20  # challenger won: green tier = 20

    @patch.object(challenge_svc_module, "ConfigService")
    @patch.object(challenge_svc_module, "PPService")
    @patch.object(challenge_svc_module, "EloService")
    async def test_detail_returns_tokens_earned_for_opponent(
        self, mock_elo_cls, mock_pp_cls, mock_config_cls, db,
    ):
        """get_challenge_detail returns tokens_earned from opponent's perspective."""
        _setup_config_mocks(mock_config_cls)
        _setup_elo_mocks(mock_elo_cls)
        _setup_pp_mocks(mock_pp_cls)

        user_a = _make_test_user(db, username="user_a", elo=1200, tokens=0)
        user_b = _make_test_user(db, username="user_b", elo=1200, tokens=0)
        db.add_all([user_a, user_b])
        await db.flush()

        session = _make_test_session(user_a.id, user_b.id, problem_rating=1200)
        db.add(session)
        await db.flush()

        # Challenger does not solve, opponent solves
        await ChallengeService.submit_result(db, user_a, session.id, False, 120.0, 3)

        mock_elo_cls.process_challenge_result = AsyncMock(return_value=(1170, 1230, -30, 30))
        mock_pp_cls.record_pp = AsyncMock()

        await ChallengeService.submit_result(db, user_b, session.id, True, 60.0, 1)

        # Opponent (user_b) sees their tokens
        detail = await ChallengeService.get_challenge_detail(db, user_b, session.id)
        assert detail.tokens_earned == 20  # opponent won: green tier = 20


# ---------------------------------------------------------------------------
# get_active_challenge tests
# ---------------------------------------------------------------------------


class TestGetActiveChallenge:
    """Tests for ChallengeService.get_active_challenge."""

    async def test_returns_none_when_no_active_session(self, db):
        """Returns None when user has no active challenge sessions."""
        user = _make_test_user(db, username="user1")
        db.add(user)
        await db.flush()

        result = await ChallengeService.get_active_challenge(db, user)
        assert result is None

    async def test_returns_active_session_for_challenger(self, db):
        """Returns active session info when user is the challenger."""
        user_a = _make_test_user(db, username="challenger", elo=1300)
        user_b = _make_test_user(db, username="opponent", elo=1400)
        db.add_all([user_a, user_b])
        await db.flush()

        session = _make_test_session(
            user_a.id, user_b.id, status="active", problem_id="1234B", problem_rating=1400,
        )
        session.problem_name = "Test Problem"
        from datetime import datetime as _dt
        session.created_at = _dt(2026, 1, 15, 10, 30, 0)
        db.add(session)
        await db.flush()

        result = await ChallengeService.get_active_challenge(db, user_a)
        assert result is not None
        assert result.id == session.id
        assert result.is_challenger is True
        assert result.problem_name == "Test Problem"
        assert result.problem_rating == 1400
        assert result.opponent_username == "opponent"
        assert result.opponent_elo == 1400
        assert result.status == "active"

    async def test_returns_active_session_for_opponent(self, db):
        """Returns active session info when user is the opponent."""
        user_a = _make_test_user(db, username="challenger", elo=1300)
        user_b = _make_test_user(db, username="opponent", elo=1400)
        db.add_all([user_a, user_b])
        await db.flush()

        session = _make_test_session(
            user_a.id, user_b.id, status="active", problem_id="1234B", problem_rating=1400,
        )
        session.problem_name = "Test Problem"
        db.add(session)
        await db.flush()

        result = await ChallengeService.get_active_challenge(db, user_b)
        assert result is not None
        assert result.id == session.id
        assert result.is_challenger is False
        assert result.opponent_username == "challenger"
        assert result.opponent_elo == 1300

    async def test_ignores_completed_session(self, db):
        """Does not return completed sessions."""
        user_a = _make_test_user(db, username="challenger", elo=1300)
        user_b = _make_test_user(db, username="opponent", elo=1400)
        db.add_all([user_a, user_b])
        await db.flush()

        session = _make_test_session(
            user_a.id, user_b.id, status="completed", problem_rating=1400,
        )
        db.add(session)
        await db.flush()

        result = await ChallengeService.get_active_challenge(db, user_a)
        assert result is None

    async def test_ignores_pending_session(self, db):
        """Does not return pending sessions."""
        user_a = _make_test_user(db, username="challenger", elo=1300)
        user_b = _make_test_user(db, username="opponent", elo=1400)
        db.add_all([user_a, user_b])
        await db.flush()

        session = _make_test_session(
            user_a.id, user_b.id, status="pending", problem_rating=1400,
        )
        db.add(session)
        await db.flush()

        result = await ChallengeService.get_active_challenge(db, user_a)
        assert result is None

    async def test_returns_most_recent_active_session(self, db):
        """When multiple active sessions exist, returns the most recent one."""
        user_a = _make_test_user(db, username="challenger", elo=1300)
        user_b = _make_test_user(db, username="opponent", elo=1400)
        db.add_all([user_a, user_b])
        await db.flush()

        from datetime import datetime as _dt

        old_session = _make_test_session(
            user_a.id, user_b.id, status="active", problem_id="1111A", problem_rating=1200,
        )
        old_session.problem_name = "Old Problem"
        old_session.created_at = _dt(2026, 1, 1, 10, 0, 0)
        db.add(old_session)

        new_session = _make_test_session(
            user_a.id, user_b.id, status="active", problem_id="2222B", problem_rating=1500,
        )
        new_session.problem_name = "New Problem"
        new_session.created_at = _dt(2026, 1, 15, 10, 0, 0)
        db.add(new_session)
        await db.flush()

        result = await ChallengeService.get_active_challenge(db, user_a)
        assert result is not None
        assert result.problem_name == "New Problem"
        assert result.problem_rating == 1500


# ---------------------------------------------------------------------------
# Overkill achievement detection tests
# ---------------------------------------------------------------------------


class TestOverkillAchievement:
    """Tests for overkill achievement event detection in _settle_challenge.

    Verifies that both challenger and opponent can trigger overkill
    achievements when solving problems above their Elo level.
    """

    @patch.object(challenge_svc_module, "ConfigService")
    @patch.object(challenge_svc_module, "PPService")
    @patch.object(challenge_svc_module, "EloService")
    async def test_challenger_overkill_achievement(self, mock_elo_cls, mock_pp_cls, mock_config_cls, db):
        """Challenger solving a hard problem triggers overkill achievement."""
        _setup_config_mocks(mock_config_cls)
        _setup_elo_mocks(mock_elo_cls)
        # Overkill multiplier > 1.0 means the problem is above user's Elo
        mock_pp_cls.calculate_overkill_multiplier = staticmethod(
            lambda elo, rating: 1.5 if rating > elo else 1.0
        )
        mock_pp_cls.record_pp = AsyncMock()

        user_a = _make_test_user(db, username="user_a", elo=1200, tokens=0)
        user_b = _make_test_user(db, username="user_b", elo=1600, tokens=0)
        db.add_all([user_a, user_b])
        await db.flush()

        # Problem rating 1600 is well above challenger's 1200
        session = _make_test_session(user_a.id, user_b.id, problem_rating=1600)
        db.add(session)
        await db.flush()

        # Challenger submits first (solved)
        await ChallengeService.submit_result(db, user_a, session.id, True, 60.0, 1)

        mock_elo_cls.process_challenge_result = AsyncMock(return_value=(1260, 1580, 60, -20))

        # Opponent submits (not solved) -> triggers settlement
        result = await ChallengeService.submit_result(db, user_b, session.id, False, 120.0, 3)
        assert result.settled is True
        # The settlement response should include achievements
        assert len(result.achievements) >= 1
        assert result.achievements[0]["type"] == "overkill_bonus"

    @patch.object(challenge_svc_module, "ConfigService")
    @patch.object(challenge_svc_module, "PPService")
    @patch.object(challenge_svc_module, "EloService")
    async def test_opponent_overkill_achievement(self, mock_elo_cls, mock_pp_cls, mock_config_cls, db):
        """Opponent solving a hard problem triggers overkill achievement."""
        _setup_config_mocks(mock_config_cls)
        _setup_elo_mocks(mock_elo_cls)
        mock_pp_cls.calculate_overkill_multiplier = staticmethod(
            lambda elo, rating: 1.5 if rating > elo else 1.0
        )
        mock_pp_cls.record_pp = AsyncMock()

        # Opponent has lower Elo than the problem
        user_a = _make_test_user(db, username="user_a", elo=1600, tokens=0)
        user_b = _make_test_user(db, username="user_b", elo=1200, tokens=0)
        db.add_all([user_a, user_b])
        await db.flush()

        session = _make_test_session(user_a.id, user_b.id, problem_rating=1600)
        db.add(session)
        await db.flush()

        # Challenger submits first (not solved)
        await ChallengeService.submit_result(db, user_a, session.id, False, 120.0, 3)

        # Opponent wins (solved faster), new_elo=1260, elo_change=60
        mock_elo_cls.process_challenge_result = AsyncMock(return_value=(1580, 1260, -20, 60))

        # Opponent submits (solved) -> triggers settlement
        result = await ChallengeService.submit_result(db, user_b, session.id, True, 60.0, 1)
        assert result.settled is True
        # Opponent overkill should generate an achievement event
        assert len(result.achievements) >= 1
        assert result.achievements[0]["type"] == "overkill_bonus"

    @patch.object(challenge_svc_module, "ConfigService")
    @patch.object(challenge_svc_module, "PPService")
    @patch.object(challenge_svc_module, "EloService")
    async def test_both_players_overkill_achievement(self, mock_elo_cls, mock_pp_cls, mock_config_cls, db):
        """Both players solving a hard problem each triggers two overkill achievements."""
        _setup_config_mocks(mock_config_cls)
        _setup_elo_mocks(mock_elo_cls)
        mock_pp_cls.calculate_overkill_multiplier = staticmethod(
            lambda elo, rating: 1.5 if rating > elo else 1.0
        )
        mock_pp_cls.record_pp = AsyncMock()

        # Both players have lower Elo than the problem
        user_a = _make_test_user(db, username="user_a", elo=1200, tokens=0)
        user_b = _make_test_user(db, username="user_b", elo=1200, tokens=0)
        db.add_all([user_a, user_b])
        await db.flush()

        session = _make_test_session(user_a.id, user_b.id, problem_rating=1600)
        db.add(session)
        await db.flush()

        # Challenger solves first
        await ChallengeService.submit_result(db, user_a, session.id, True, 60.0, 1)

        mock_elo_cls.process_challenge_result = AsyncMock(return_value=(1260, 1260, 60, 60))

        # Opponent also solves (slower) -> draw but both get overkill
        result = await ChallengeService.submit_result(db, user_b, session.id, True, 90.0, 1)
        assert result.settled is True
        # Both players should trigger overkill achievements
        overkill_achievements = [a for a in result.achievements if a["type"] == "overkill_bonus"]
        assert len(overkill_achievements) == 2

    @patch.object(challenge_svc_module, "ConfigService")
    @patch.object(challenge_svc_module, "PPService")
    @patch.object(challenge_svc_module, "EloService")
    async def test_no_overkill_when_problem_easy(self, mock_elo_cls, mock_pp_cls, mock_config_cls, db):
        """No overkill achievement when problem rating is at or below user Elo."""
        _setup_config_mocks(mock_config_cls)
        _setup_elo_mocks(mock_elo_cls)
        mock_pp_cls.calculate_overkill_multiplier = staticmethod(
            lambda elo, rating: 1.0  # No overkill
        )
        mock_pp_cls.record_pp = AsyncMock()

        user_a = _make_test_user(db, username="user_a", elo=1600, tokens=0)
        user_b = _make_test_user(db, username="user_b", elo=1600, tokens=0)
        db.add_all([user_a, user_b])
        await db.flush()

        # Problem at same level as users
        session = _make_test_session(user_a.id, user_b.id, problem_rating=1600)
        db.add(session)
        await db.flush()

        await ChallengeService.submit_result(db, user_a, session.id, True, 60.0, 1)

        mock_elo_cls.process_challenge_result = AsyncMock(return_value=(1630, 1570, 30, -30))

        result = await ChallengeService.submit_result(db, user_b, session.id, False, 120.0, 3)
        assert result.settled is True
        assert len(result.achievements) == 0
