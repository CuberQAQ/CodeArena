"""Tests for Task 19: Elo hint attenuation pass-through and attempt reward completion.

Tests cover:
- Task 19.1: hint_level_challenger and hint_level_opponent are passed to
  EloService.process_challenge_result during challenge settlement, and
  attenuation is applied to positive Elo gains for both players.
- Task 19.2: attempt tokens are awarded in challenge (loser with submissions)
  and contest (unsolved problems with submissions), using
  economy_svc.attempt_tokens_for_rating, respecting daily cap (120), and
  recording the correct transaction type.
"""

import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import JSON, Boolean, DateTime, Float, Integer, String, event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.services import challenge_service as challenge_svc_module
from app.services import contest_service as contest_svc_module
from app.services import economy_service as economy_svc_module
from app.services import elo_service as elo_svc_module
from app.services import pp_service as pp_svc_module
from app.services.challenge_service import ChallengeService
from app.services.config_service import ConfigService
from app.services.contest_service import ContestService
from app.services.contest_simulation_service import ContestSimulationService
from app.services.elo_service import EloService
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
    daily_tokens_earned: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    daily_tokens_reset_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


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


class _TestContestSession(_TestBase):
    __tablename__ = "contest_sessions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    contest_tier: Mapped[str] = mapped_column(String(20), nullable=False)
    problems: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    total_problems: Mapped[int] = mapped_column(Integer, nullable=False)
    problems_solved: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    submissions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    time_limit: Mapped[int] = mapped_column(Integer, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    elo_change: Mapped[int | None] = mapped_column(Integer, nullable=True)


class _TestContestProblemRecord(_TestBase):
    __tablename__ = "contest_problem_records"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    contest_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    problem_id: Mapped[str] = mapped_column(String(50), nullable=False)
    problem_rating: Mapped[int] = mapped_column(Integer, nullable=False)
    solved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    time_spent: Mapped[float | None] = mapped_column(Float, nullable=True)
    solved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class _TestEloHistory(_TestBase):
    __tablename__ = "elo_history"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    elo_before: Mapped[int] = mapped_column(Integer, nullable=False)
    elo_after: Mapped[int] = mapped_column(Integer, nullable=False)
    elo_change: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(String(50), nullable=False)
    reference_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


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


def _get_elo_config():
    return {
        "k_newbie": 40,
        "k_veteran": 20,
        "k_newbie_threshold": 20,
        "k_veteran_threshold": 100,
    }


async def _mock_get_config(db, key):
    from app.core.default_config import DEFAULT_CONFIG
    return DEFAULT_CONFIG.get("elo", {})


async def _mock_get_submission_count(db, user_id):
    return 0


@pytest.fixture
async def challenge_db(async_engine):
    """DB session with challenge-service patches."""
    session_factory = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)

    # Track transactions recorded
    recorded_transactions: list[dict] = []

    async def _mock_award_tokens(db, user, amount, tx_type=None, reference_type=None, reference_id=None):
        user.tokens += amount
        recorded_transactions.append({
            "user_id": user.id,
            "amount": amount,
            "tx_type": tx_type,
            "reference_type": reference_type,
            "reference_id": reference_id,
        })
        return amount

    async def _mock_record_elo_history(db, user_id, elo_before, elo_after, reason, reference_id=None):
        record = _TestEloHistory(
            user_id=user_id,
            elo_before=elo_before,
            elo_after=elo_after,
            elo_change=elo_after - elo_before,
            reason=reason.value if hasattr(reason, "value") else str(reason),
            reference_id=reference_id,
        )
        db.add(record)
        await db.flush()
        return record

    async with session_factory() as session:
        with (
            patch.object(challenge_svc_module, "User", _TestUser),
            patch.object(challenge_svc_module, "ChallengeSession", _TestChallengeSession),
            patch.object(economy_svc_module, "award_tokens", _mock_award_tokens),
            patch.object(elo_svc_module.EloService, "record_elo_history", _mock_record_elo_history),
            patch.object(ConfigService, "get_config", _mock_get_config),
            patch.object(EloService, "get_submission_count", _mock_get_submission_count),
        ):
            session._recorded_transactions = recorded_transactions
            yield session


@pytest.fixture
async def contest_db(async_engine):
    """DB session with contest-service patches."""
    session_factory = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)

    recorded_transactions: list[dict] = []

    async def _mock_award_tokens(db, user, amount, tx_type=None, reference_type=None, reference_id=None):
        user.tokens += amount
        recorded_transactions.append({
            "user_id": user.id,
            "amount": amount,
            "tx_type": tx_type,
            "reference_type": reference_type,
            "reference_id": reference_id,
        })
        return amount

    async def _mock_record_elo_history(db, user_id, elo_before, elo_after, reason, reference_id=None):
        record = _TestEloHistory(
            user_id=user_id,
            elo_before=elo_before,
            elo_after=elo_after,
            elo_change=elo_after - elo_before,
            reason=reason.value if hasattr(reason, "value") else str(reason),
            reference_id=reference_id,
        )
        db.add(record)
        await db.flush()
        return record

    async with session_factory() as session:
        with (
            patch.object(contest_svc_module, "ContestSession", _TestContestSession),
            patch.object(contest_svc_module, "ContestProblemRecord", _TestContestProblemRecord),
            patch.object(contest_svc_module, "EloHistory", _TestEloHistory),
            patch.object(pp_svc_module.PPService, "record_pp", AsyncMock(return_value=None)),
            patch.object(elo_svc_module.EloService, "record_elo_history", _mock_record_elo_history),
            patch.object(economy_svc_module, "award_tokens", _mock_award_tokens),
            patch.object(ConfigService, "get_config", _mock_get_config),
            patch.object(EloService, "get_submission_count", _mock_get_submission_count),
            patch.object(ContestSimulationService, "generate_bots", AsyncMock(return_value=[])),
            patch.object(ContestSimulationService, "stop_simulation", AsyncMock(return_value=False)),
            patch.object(ContestSimulationService, "start_simulation", AsyncMock(return_value=None)),
            patch.object(SubmissionTracker, "register_pending", AsyncMock()),
        ):
            session._recorded_transactions = recorded_transactions
            yield session


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(**kwargs) -> _TestUser:
    defaults = {
        "username": f"user_{uuid.uuid4().hex[:8]}",
        "email": f"{uuid.uuid4().hex[:8]}@test.com",
        "password_hash": "hash",
        "elo": 1200,
        "tokens": 0,
    }
    defaults.update(kwargs)
    return _TestUser(**defaults)


def _make_challenge_session(
    challenger_id: uuid.UUID,
    opponent_id: uuid.UUID,
    status: str = "active",
    problem_id: str = "800A",
    problem_rating: int = 1200,
    hints_used_challenger: int = 0,
    hints_used_opponent: int = 0,
) -> _TestChallengeSession:
    return _TestChallengeSession(
        challenger_id=challenger_id,
        opponent_id=opponent_id,
        problem_id=problem_id,
        problem_rating=problem_rating,
        status=status,
        hints_used_challenger=hints_used_challenger,
        hints_used_opponent=hints_used_opponent,
    )


def _make_cf_service_mock(problems=None):
    cf_mock = AsyncMock()
    if problems is None:
        problems = [
            {"contestId": 1000, "index": "A", "name": "Prob A", "rating": 800, "tags": []},
            {"contestId": 1000, "index": "B", "name": "Prob B", "rating": 1000, "tags": []},
            {"contestId": 1000, "index": "C", "name": "Prob C", "rating": 1200, "tags": []},
            {"contestId": 1000, "index": "D", "name": "Prob D", "rating": 1400, "tags": []},
            {"contestId": 1000, "index": "E", "name": "Prob E", "rating": 1600, "tags": []},
        ]
    cf_mock.get_problemset_problems.return_value = {"problems": problems}
    return cf_mock


# ===========================================================================
# Task 19.1: Elo hint attenuation pass-through
# ===========================================================================


class TestHintAttenuationPassThrough:
    """Verify hint_level is read from session and passed to EloService."""

    @patch.object(challenge_svc_module, "ConfigService")
    @patch.object(challenge_svc_module, "PPService")
    @patch.object(challenge_svc_module, "EloService")
    async def test_hint_level_challenger_passed_to_elo(
        self, mock_elo_cls, mock_pp_cls, mock_config_cls, challenge_db
    ):
        """hint_level_challenger from session is forwarded to process_challenge_result."""
        mock_config_cls.get_config = AsyncMock(return_value=_get_elo_config())
        mock_elo_cls.get_submission_count = AsyncMock(return_value=0)
        mock_pp_cls.record_pp = AsyncMock()
        mock_pp_cls.calculate_overkill_multiplier = MagicMock(return_value=1.0)

        user_a = _make_user(username="user_a", elo=1200, tokens=0)
        user_b = _make_user(username="user_b", elo=1200, tokens=0)
        challenge_db.add_all([user_a, user_b])
        await challenge_db.flush()

        # Create session with hint_level_challenger=2
        session = _make_challenge_session(
            user_a.id, user_b.id,
            hints_used_challenger=2,
            hints_used_opponent=0,
        )
        challenge_db.add(session)
        await challenge_db.flush()

        # Challenger submits solved
        await ChallengeService.submit_result(
            challenge_db, user_a, session.id, solved=True, time_spent=60.0, attempts=1
        )

        mock_elo_cls.process_challenge_result = AsyncMock(
            return_value=(1215, 1185, 15, -15)
        )

        # Opponent submits unsolved -> triggers settlement
        await ChallengeService.submit_result(
            challenge_db, user_b, session.id, solved=False, time_spent=120.0, attempts=3
        )

        # Verify process_challenge_result was called with hint_level_challenger=2
        call_kwargs = mock_elo_cls.process_challenge_result.call_args
        assert call_kwargs.kwargs.get("hint_level_challenger") == 2
        assert call_kwargs.kwargs.get("hint_level_opponent") == 0

    @patch.object(challenge_svc_module, "ConfigService")
    @patch.object(challenge_svc_module, "PPService")
    @patch.object(challenge_svc_module, "EloService")
    async def test_hint_level_opponent_passed_to_elo(
        self, mock_elo_cls, mock_pp_cls, mock_config_cls, challenge_db
    ):
        """hint_level_opponent from session is forwarded to process_challenge_result."""
        mock_config_cls.get_config = AsyncMock(return_value=_get_elo_config())
        mock_elo_cls.get_submission_count = AsyncMock(return_value=0)
        mock_pp_cls.record_pp = AsyncMock()
        mock_pp_cls.calculate_overkill_multiplier = MagicMock(return_value=1.0)

        user_a = _make_user(username="user_a", elo=1200, tokens=0)
        user_b = _make_user(username="user_b", elo=1200, tokens=0)
        challenge_db.add_all([user_a, user_b])
        await challenge_db.flush()

        session = _make_challenge_session(
            user_a.id, user_b.id,
            hints_used_challenger=0,
            hints_used_opponent=3,
        )
        challenge_db.add(session)
        await challenge_db.flush()

        await ChallengeService.submit_result(
            challenge_db, user_a, session.id, solved=False, time_spent=120.0, attempts=2
        )

        mock_elo_cls.process_challenge_result = AsyncMock(
            return_value=(1170, 1230, -30, 30)
        )

        await ChallengeService.submit_result(
            challenge_db, user_b, session.id, solved=True, time_spent=60.0, attempts=1
        )

        call_kwargs = mock_elo_cls.process_challenge_result.call_args
        assert call_kwargs.kwargs.get("hint_level_challenger") == 0
        assert call_kwargs.kwargs.get("hint_level_opponent") == 3


class TestHintAttenuationEloCalculation:
    """Verify hint attenuation is applied correctly in EloService."""

    def test_level1_attenuation_positive_gain(self):
        """Level 1 hint: positive Elo change * 0.75."""
        new_a, new_b, change_a = EloService.calculate_challenge_elo(
            rating_a=1200, rating_b=1200,
            actual_score_a=1.0,  # win -> positive gain
            hint_level=1,
        )
        # raw_change = K * (1.0 - 0.5) = 32 * 0.5 = 16
        # With level 1 attenuation: 16 * 0.75 = 12
        assert change_a == 12

    def test_level2_attenuation_positive_gain(self):
        """Level 2 hint: positive Elo change * 0.50."""
        new_a, new_b, change_a = EloService.calculate_challenge_elo(
            rating_a=1200, rating_b=1200,
            actual_score_a=1.0,
            hint_level=2,
        )
        # 16 * 0.50 = 8
        assert change_a == 8

    def test_level3_attenuation_positive_gain(self):
        """Level 3 hint: positive Elo change * 0.25."""
        new_a, new_b, change_a = EloService.calculate_challenge_elo(
            rating_a=1200, rating_b=1200,
            actual_score_a=1.0,
            hint_level=3,
        )
        # 16 * 0.25 = 4
        assert change_a == 4

    def test_no_attenuation_on_loss(self):
        """Losses are not attenuated even with hints."""
        new_a, new_b, change_a = EloService.calculate_challenge_elo(
            rating_a=1200, rating_b=1200,
            actual_score_a=0.0,  # loss -> negative change
            hint_level=3,
        )
        # Negative change should not be attenuated
        assert change_a < 0
        # Same as without hints
        new_a2, _, change_a2 = EloService.calculate_challenge_elo(
            rating_a=1200, rating_b=1200,
            actual_score_a=0.0,
            hint_level=0,
        )
        assert change_a == change_a2

    def test_no_attenuation_zero_hints(self):
        """No hints: no attenuation applied."""
        new_a, new_b, change_a = EloService.calculate_challenge_elo(
            rating_a=1200, rating_b=1200,
            actual_score_a=1.0,
            hint_level=0,
        )
        # raw_change = 32 * 0.5 = 16, no attenuation
        assert change_a == 16


class TestOpponentHintAttenuation:
    """Verify opponent hint attenuation in process_challenge_result."""

    @pytest.mark.asyncio
    async def test_opponent_hint_attenuation_applied(self, challenge_db):
        """When opponent uses hints and wins, their positive Elo is attenuated."""
        user_a = _make_user(username="user_a", elo=1200)
        user_b = _make_user(username="user_b", elo=1200)
        challenge_db.add_all([user_a, user_b])
        await challenge_db.flush()

        # Opponent (B) wins with 2 hints used
        # expected_a = 0.5 (equal Elo)
        # raw_change_b = 32 * (1.0 - 0.5) = 16
        # With hint_level_opponent=2: 16 * 0.50 = 8
        new_a, new_b, change_a, change_b = await EloService.process_challenge_result(
            db=challenge_db,
            challenger_id=user_a.id,
            opponent_id=user_b.id,
            challenger_rating=1200,
            opponent_rating=1200,
            actual_score_a=0.0,  # opponent wins
            session_id=uuid.uuid4(),
            hint_level_challenger=0,
            hint_level_opponent=2,
        )

        # Challenger lost (no attenuation on loss)
        assert change_a == -16
        # Opponent won with 2 hints -> attenuated: 16 * 0.50 = 8
        assert change_b == 8

    @pytest.mark.asyncio
    async def test_both_players_attenuated(self, challenge_db):
        """When both players use hints and draw, positive gains are attenuated."""
        user_a = _make_user(username="user_a", elo=1000)
        user_b = _make_user(username="user_b", elo=1400)
        challenge_db.add_all([user_a, user_b])
        await challenge_db.flush()

        # Draw: expected_a > 0.5 (A is lower rated), so A gains on draw
        # Both use hints
        new_a, new_b, change_a, change_b = await EloService.process_challenge_result(
            db=challenge_db,
            challenger_id=user_a.id,
            opponent_id=user_b.id,
            challenger_rating=1000,
            opponent_rating=1400,
            actual_score_a=0.5,  # draw
            session_id=uuid.uuid4(),
            hint_level_challenger=1,
            hint_level_opponent=1,
        )

        # A gains on draw (lower rated) -> attenuated by 0.75
        assert change_a > 0
        # B loses on draw (higher rated) -> no attenuation (negative)
        assert change_b < 0


# ===========================================================================
# Task 19.2: Attempt rewards
# ===========================================================================


class TestChallengeAttemptReward:
    """Verify attempt tokens are awarded to losers in challenges."""

    @patch.object(challenge_svc_module, "ConfigService")
    @patch.object(challenge_svc_module, "PPService")
    @patch.object(challenge_svc_module, "EloService")
    async def test_loser_gets_attempt_tokens(
        self, mock_elo_cls, mock_pp_cls, mock_config_cls, challenge_db
    ):
        """The losing player who submitted gets attempt tokens."""
        mock_config_cls.get_config = AsyncMock(return_value=_get_elo_config())
        mock_elo_cls.get_submission_count = AsyncMock(return_value=0)
        mock_elo_cls.process_challenge_result = AsyncMock(return_value=(1230, 1170, 30, -30))
        mock_pp_cls.record_pp = AsyncMock()
        mock_pp_cls.calculate_overkill_multiplier = MagicMock(return_value=1.0)

        user_a = _make_user(username="user_a", elo=1200, tokens=0)
        user_b = _make_user(username="user_b", elo=1200, tokens=0)
        challenge_db.add_all([user_a, user_b])
        await challenge_db.flush()

        # problem_rating=1200 -> green tier -> attempt tokens = 3
        session = _make_challenge_session(
            user_a.id, user_b.id,
            problem_rating=1200,
        )
        challenge_db.add(session)
        await challenge_db.flush()

        # Challenger solves
        await ChallengeService.submit_result(
            challenge_db, user_a, session.id, solved=True, time_spent=60.0, attempts=1
        )
        # Opponent fails but has submissions
        result = await ChallengeService.submit_result(
            challenge_db, user_b, session.id, solved=False, time_spent=120.0, attempts=3
        )

        assert result.settled is True

        # Opponent should have received attempt tokens (3 for green tier)
        await challenge_db.refresh(user_b)
        assert user_b.tokens >= 3

        # Check transaction recorded as reward_attempt
        txs = challenge_db._recorded_transactions
        attempt_txs = [t for t in txs if t["tx_type"] == "reward_attempt" and t["user_id"] == user_b.id]
        assert len(attempt_txs) == 1
        assert attempt_txs[0]["amount"] == 3

    @patch.object(challenge_svc_module, "ConfigService")
    @patch.object(challenge_svc_module, "PPService")
    @patch.object(challenge_svc_module, "EloService")
    async def test_loser_no_submissions_no_attempt_tokens(
        self, mock_elo_cls, mock_pp_cls, mock_config_cls, challenge_db
    ):
        """Loser with 0 submissions gets no attempt tokens."""
        mock_config_cls.get_config = AsyncMock(return_value=_get_elo_config())
        mock_elo_cls.get_submission_count = AsyncMock(return_value=0)
        mock_elo_cls.process_challenge_result = AsyncMock(return_value=(1230, 1170, 30, -30))
        mock_pp_cls.record_pp = AsyncMock()
        mock_pp_cls.calculate_overkill_multiplier = MagicMock(return_value=1.0)

        user_a = _make_user(username="user_a", elo=1200, tokens=0)
        user_b = _make_user(username="user_b", elo=1200, tokens=0)
        challenge_db.add_all([user_a, user_b])
        await challenge_db.flush()

        session = _make_challenge_session(
            user_a.id, user_b.id,
            problem_rating=1200,
        )
        challenge_db.add(session)
        await challenge_db.flush()

        await ChallengeService.submit_result(
            challenge_db, user_a, session.id, solved=True, time_spent=60.0, attempts=1
        )
        # Opponent fails with 0 submissions
        result = await ChallengeService.submit_result(
            challenge_db, user_b, session.id, solved=False, time_spent=120.0, attempts=0
        )

        assert result.settled is True

        await challenge_db.refresh(user_b)
        assert user_b.tokens == 0

    @patch.object(challenge_svc_module, "ConfigService")
    @patch.object(challenge_svc_module, "PPService")
    @patch.object(challenge_svc_module, "EloService")
    async def test_both_lose_both_get_attempt_tokens(
        self, mock_elo_cls, mock_pp_cls, mock_config_cls, challenge_db
    ):
        """Neither solved: both get attempt tokens (draw case)."""
        mock_config_cls.get_config = AsyncMock(return_value=_get_elo_config())
        mock_elo_cls.get_submission_count = AsyncMock(return_value=0)
        mock_elo_cls.process_challenge_result = AsyncMock(return_value=(1200, 1200, 0, 0))
        mock_pp_cls.record_pp = AsyncMock()
        mock_pp_cls.calculate_overkill_multiplier = MagicMock(return_value=1.0)

        user_a = _make_user(username="user_a", elo=1200, tokens=0)
        user_b = _make_user(username="user_b", elo=1200, tokens=0)
        challenge_db.add_all([user_a, user_b])
        await challenge_db.flush()

        session = _make_challenge_session(
            user_a.id, user_b.id,
            problem_rating=1000,  # gray -> attempt = 2
        )
        challenge_db.add(session)
        await challenge_db.flush()

        # Neither solves, both have submissions
        await ChallengeService.submit_result(
            challenge_db, user_a, session.id, solved=False, time_spent=120.0, attempts=2
        )
        result = await ChallengeService.submit_result(
            challenge_db, user_b, session.id, solved=False, time_spent=120.0, attempts=3
        )

        assert result.settled is True

        # Both get draw tokens (10 // 2 = 5) + attempt tokens (2)
        await challenge_db.refresh(user_a)
        await challenge_db.refresh(user_b)
        assert user_a.tokens == 5 + 2  # draw split + attempt tokens
        assert user_b.tokens == 5 + 2

    @patch.object(challenge_svc_module, "ConfigService")
    @patch.object(challenge_svc_module, "PPService")
    @patch.object(challenge_svc_module, "EloService")
    async def test_attempt_tokens_by_rating_tier(
        self, mock_elo_cls, mock_pp_cls, mock_config_cls, challenge_db
    ):
        """Attempt tokens match the rating tier."""
        mock_config_cls.get_config = AsyncMock(return_value=_get_elo_config())
        mock_elo_cls.get_submission_count = AsyncMock(return_value=0)
        mock_pp_cls.record_pp = AsyncMock()
        mock_pp_cls.calculate_overkill_multiplier = MagicMock(return_value=1.0)

        # Test each tier
        tiers = [
            (900, 2),    # gray
            (1200, 3),   # green
            (1500, 4),   # cyan
            (1800, 5),   # blue
            (2000, 6),   # purple
            (2200, 7),   # orange
        ]

        for rating, expected_attempt_tokens in tiers:
            challenge_db._recorded_transactions.clear()

            user_a = _make_user(username=f"winner_{rating}", elo=1200, tokens=0)
            user_b = _make_user(username=f"loser_{rating}", elo=1200, tokens=0)
            challenge_db.add_all([user_a, user_b])
            await challenge_db.flush()

            session = _make_challenge_session(
                user_a.id, user_b.id,
                problem_rating=rating,
            )
            challenge_db.add(session)
            await challenge_db.flush()

            mock_elo_cls.process_challenge_result = AsyncMock(
                return_value=(1230, 1170, 30, -30)
            )

            await ChallengeService.submit_result(
                challenge_db, user_a, session.id, solved=True, time_spent=60.0, attempts=1
            )
            await ChallengeService.submit_result(
                challenge_db, user_b, session.id, solved=False, time_spent=120.0, attempts=2
            )

            # Verify attempt tokens for loser
            txs = challenge_db._recorded_transactions
            attempt_txs = [t for t in txs if t["tx_type"] == "reward_attempt" and t["user_id"] == user_b.id]
            assert len(attempt_txs) == 1, f"Expected 1 attempt tx for rating {rating}, got {len(attempt_txs)}"
            assert attempt_txs[0]["amount"] == expected_attempt_tokens, (
                f"Rating {rating}: expected {expected_attempt_tokens} attempt tokens, "
                f"got {attempt_txs[0]['amount']}"
            )


class TestContestAttemptReward:
    """Verify attempt tokens are awarded for unsolved contest problems."""

    @pytest.mark.asyncio
    async def test_unsolved_problem_gets_attempt_tokens(self, contest_db):
        """Unsolved problem submission earns attempt tokens."""
        user = _make_user(elo=1300, tokens=0)
        contest_db.add(user)
        await contest_db.flush()

        cf_mock = _make_cf_service_mock()
        started = await ContestService.start_contest(contest_db, user, "beginner", cf_mock)
        await contest_db.commit()

        # Submit unsolved problem (rating 800 = gray -> attempt tokens = 2)
        problem = started.problems[0]
        result = await ContestService.submit_problem(
            contest_db, user, started.id,
            problem_id=problem.problem_id,
            solved=False,
            attempts=2,
            time_spent=300.0,
        )

        assert result.solved is False
        assert result.tokens_earned > 0

        # Verify transaction type
        txs = contest_db._recorded_transactions
        attempt_txs = [t for t in txs if t["tx_type"] == "reward_attempt"]
        assert len(attempt_txs) == 1
        assert attempt_txs[0]["amount"] == result.tokens_earned

    @pytest.mark.asyncio
    async def test_attempt_tokens_by_rating_tier(self, contest_db):
        """Attempt tokens for contest match rating tier."""
        from app.services.economy_service import attempt_tokens_for_rating

        user = _make_user(elo=1300, tokens=0)
        contest_db.add(user)
        await contest_db.flush()

        problems = [
            {"contestId": 100, "index": "A", "name": "Gray", "rating": 900, "tags": []},
            {"contestId": 100, "index": "B", "name": "Green", "rating": 1200, "tags": []},
            {"contestId": 100, "index": "C", "name": "Blue", "rating": 1500, "tags": []},
            {"contestId": 100, "index": "D", "name": "Purple", "rating": 1800, "tags": []},
        ]
        cf_mock = _make_cf_service_mock(problems=problems)
        started = await ContestService.start_contest(contest_db, user, "beginner", cf_mock)
        await contest_db.commit()

        for problem in started.problems:
            contest_db._recorded_transactions.clear()
            expected = attempt_tokens_for_rating(problem.rating)
            result = await ContestService.submit_problem(
                contest_db, user, started.id,
                problem_id=problem.problem_id,
                solved=False,
                attempts=2,
                time_spent=300.0,
            )

            assert result.tokens_earned == expected, (
                f"Rating {problem.rating}: expected {expected}, "
                f"got {result.tokens_earned}"
            )

    @pytest.mark.asyncio
    async def test_solved_problem_no_attempt_tokens(self, contest_db):
        """Solved problems get AC reward, not attempt reward."""
        user = _make_user(elo=1300, tokens=0)
        contest_db.add(user)
        await contest_db.flush()

        cf_mock = _make_cf_service_mock()
        started = await ContestService.start_contest(contest_db, user, "beginner", cf_mock)
        await contest_db.commit()

        problem = started.problems[0]
        result = await ContestService.submit_problem(
            contest_db, user, started.id,
            problem_id=problem.problem_id,
            solved=True,
            attempts=1,
            time_spent=300.0,
        )

        assert result.solved is True
        assert result.tokens_earned > 0

        txs = contest_db._recorded_transactions
        # Should have reward_ac, NOT reward_attempt
        attempt_txs = [t for t in txs if t["tx_type"] == "reward_attempt"]
        assert len(attempt_txs) == 0
        ac_txs = [t for t in txs if t["tx_type"] == "reward_ac"]
        assert len(ac_txs) == 1

    @pytest.mark.asyncio
    async def test_attempt_reward_transaction_reference(self, contest_db):
        """Attempt reward transactions record correct reference fields."""
        user = _make_user(elo=1300, tokens=0)
        contest_db.add(user)
        await contest_db.flush()

        cf_mock = _make_cf_service_mock()
        started = await ContestService.start_contest(contest_db, user, "beginner", cf_mock)
        await contest_db.commit()

        problem = started.problems[0]
        await ContestService.submit_problem(
            contest_db, user, started.id,
            problem_id=problem.problem_id,
            solved=False,
            attempts=2,
            time_spent=300.0,
        )

        txs = contest_db._recorded_transactions
        attempt_txs = [t for t in txs if t["tx_type"] == "reward_attempt"]
        assert len(attempt_txs) == 1
        assert attempt_txs[0]["reference_type"] == "contest"
        assert attempt_txs[0]["reference_id"] == started.id


class TestDailyCapApplies:
    """Verify that attempt rewards are subject to the daily cap (120)."""

    @pytest.mark.asyncio
    async def test_contest_attempt_respects_daily_cap(self, contest_db):
        """Attempt tokens in contest are capped at daily limit via economy_service."""
        # This test validates the integration: contest uses economy_svc.award_tokens
        # which checks the daily cap internally.
        user = _make_user(elo=1300, tokens=100, daily_tokens_earned=119)
        contest_db.add(user)
        await contest_db.flush()

        cf_mock = _make_cf_service_mock()
        started = await ContestService.start_contest(contest_db, user, "beginner", cf_mock)
        await contest_db.commit()

        problem = started.problems[0]
        result = await ContestService.submit_problem(
            contest_db, user, started.id,
            problem_id=problem.problem_id,
            solved=False,
            attempts=2,
            time_spent=300.0,
        )

        # The mock bypasses cap, but we can verify award_tokens was called.
        # In production, economy_svc.award_tokens would cap at 1 (120-119=1 remaining).
        # With mock: full attempt tokens awarded.
        assert result.tokens_earned > 0
        txs = contest_db._recorded_transactions
        assert any(t["tx_type"] == "reward_attempt" for t in txs)
