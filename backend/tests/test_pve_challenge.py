"""Tests for the PvE challenge system: problem selection, lifecycle, settlement, and quit.

Uses lightweight SQLite-compatible test models and mocks for external services
(CF API). Patches the production model references in pve_challenge_service with
test-compatible models so SQLAlchemy queries target SQLite tables.
"""

import json
import uuid
from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import DateTime, Float, Integer, String, TypeDecorator, event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core.exceptions import BadRequestException, ForbiddenException, NotFoundException
from app.services import economy_service as economy_svc_module
from app.services import pve_challenge_service as pve_svc_module
from app.services.pp_service import PPService as _RealPPService
from app.services.pve_challenge_service import PvEChallengeService
from app.services.submission_tracker import SubmissionTracker


class JSONText(TypeDecorator):
    """A SQLite-compatible JSON type that stores data as JSON text."""

    impl = String(500)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None:
            return json.dumps(value)
        return value

    def process_result_value(self, value, dialect):
        if value is not None:
            return json.loads(value)
        return value


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
    daily_tokens_earned: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Integer, default=1, nullable=False)


class _TestPvESession(_TestBase):
    __tablename__ = "pve_challenge_sessions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    problem_id: Mapped[str] = mapped_column(String(50), default="", nullable=False)
    problem_rating: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    problem_tags: Mapped[str | None] = mapped_column(JSONText, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    error_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    time_spent: Mapped[float | None] = mapped_column(Float, nullable=True)
    hints_used: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    elo_change: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pp_change: Mapped[float | None] = mapped_column(Float, nullable=True)
    s_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class _TestPPRecord(_TestBase):
    __tablename__ = "pp_records"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    cf_problem_id: Mapped[str] = mapped_column(String(50), nullable=False)
    problem_rating: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    base_pp: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    final_pp: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)


class _TestEloHistory(_TestBase):
    __tablename__ = "elo_history"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    elo_before: Mapped[int] = mapped_column(Integer, default=1200, nullable=False)
    elo_after: Mapped[int] = mapped_column(Integer, default=1200, nullable=False)
    elo_change: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    reason: Mapped[str] = mapped_column(String(30), nullable=False)
    reference_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


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
async def db(async_engine):
    """Provide an async session with patched model references."""
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
        """Return 0 submissions for tests."""
        return 0

    async def _mock_record_pp(db, user_id, cf_problem_id, problem_rating, **kwargs):
        """No-op PP recording for tests."""
        pass

    async def _mock_record_elo_history(db, user_id, elo_before, elo_after, reason, reference_id=None):
        """No-op Elo history recording for tests."""
        pass

    async def _mock_get_max_hint_level(db, user_id, problem_id):
        """No hints purchased in tests -- return 0."""
        return 0

    async with session_factory() as session:
        with (
            patch.object(pve_svc_module, "PvEChallengeSession", _TestPvESession),
            patch.object(pve_svc_module, "User", _TestUser),
            patch.object(pve_svc_module, "PPRecord", _TestPPRecord),
            patch.object(economy_svc_module, "award_tokens", _mock_award_tokens),
            patch.object(pve_svc_module, "ConfigService") as mock_config_cls,
            patch.object(pve_svc_module, "EloService") as mock_elo_cls,
            patch.object(pve_svc_module, "PPService") as mock_pp_cls,
            patch.object(pve_svc_module, "HintService") as mock_hint_cls,
            patch.object(SubmissionTracker, "register_pending", AsyncMock()),
            patch.object(pve_svc_module.MEloService, "batch_update_melo_for_problem", AsyncMock(return_value={})),
        ):
            mock_config_cls.get_config = _mock_get_config
            mock_elo_cls.get_submission_count = _mock_get_submission_count
            mock_elo_cls.calculate_s_value = staticmethod(
                lambda is_solved, is_first_ac, error_count: (
                    1.0 if is_solved and is_first_ac else (max(0.7, 1.0 - 0.05 * error_count) if is_solved else 0.0)
                )
            )
            mock_elo_cls.calculate_expected_score = staticmethod(
                lambda rating_a, rating_b: 1.0 / (1.0 + 10.0 ** ((rating_b - rating_a) / 400.0))
            )
            mock_elo_cls.calculate_k_factor = staticmethod(lambda *args, **kwargs: 32.0)
            mock_elo_cls.record_elo_history = _mock_record_elo_history
            mock_elo_cls.apply_hint_attenuation = staticmethod(lambda elo_change, hint_level, config=None: elo_change)
            mock_pp_cls.record_pp = _mock_record_pp
            mock_pp_cls.calculate_overkill_multiplier = staticmethod(_RealPPService.calculate_overkill_multiplier)
            mock_hint_cls.get_max_hint_level = _mock_get_max_hint_level

            yield session


def _make_test_user(
    db: AsyncSession,
    user_id: uuid.UUID | None = None,
    username: str = "testuser",
    elo: int = 1200,
    tokens: int = 0,
    cf_handle: str | None = None,
) -> _TestUser:
    """Create a test user instance."""
    return _TestUser(
        id=user_id or uuid.uuid4(),
        username=username,
        email=f"{username}@test.com",
        password_hash="$2b$12$fakehash",
        elo=elo,
        tokens=tokens,
        cf_handle=cf_handle,
    )


def _make_cf_problems_response(ratings=None):
    """Build a CF API problemset response.

    ratings: list of (contestId, index, rating, tags) tuples.
    """
    if ratings is None:
        ratings = [
            (800, "A", 1100, ["math"]),
            (800, "B", 1200, ["dp"]),
            (800, "C", 1300, ["greedy"]),
            (800, "D", 1400, ["graphs"]),
            (800, "E", 1500, ["strings"]),
            (800, "F", 800, ["brute force"]),
            (800, "G", 900, ["implementation"]),
            (800, "H", 1600, ["binary search"]),
            (800, "I", 2000, ["combinatorics"]),
        ]
    problems = []
    for contest_id, index, rating, tags in ratings:
        problems.append(
            {
                "contestId": contest_id,
                "index": index,
                "name": f"Problem {index}",
                "rating": rating,
                "tags": tags,
            }
        )
    return {"problems": problems}


def _make_cf_mock(problems_response=None):
    """Create a mock CF service."""
    cf_mock = AsyncMock()
    cf_mock.get_problemset_problems.return_value = problems_response or _make_cf_problems_response()
    return cf_mock


# ---------------------------------------------------------------------------
# 1. Problem selection range tests
# ---------------------------------------------------------------------------


class TestProblemSelectionRanges:
    """Test that problem selection respects Elo-based ranges."""

    async def test_selects_problem_in_primary_range(self, db):
        """Round 1 range [Elo-100, Elo+200] should be preferred."""
        user = _make_test_user(db, elo=1200)
        db.add(user)
        await db.flush()

        # Only one problem in [1100, 1400] range
        cf_mock = _make_cf_mock(
            _make_cf_problems_response(
                [
                    (100, "A", 1100, ["math"]),  # In range [1100, 1400]
                    (100, "B", 900, ["dp"]),  # Below range
                    (100, "C", 1500, ["greedy"]),  # Above range
                ]
            )
        )

        result = await PvEChallengeService.start_challenge(db, user, cf_mock)
        assert result.problem.rating == 1100

    async def test_selects_from_correct_range(self, db):
        """When multiple problems are in range, one should be selected."""
        user = _make_test_user(db, elo=1200)
        db.add(user)
        await db.flush()

        cf_mock = _make_cf_mock(
            _make_cf_problems_response(
                [
                    (100, "A", 1250, ["math"]),
                    (100, "B", 1350, ["dp"]),
                    (100, "C", 1100, ["greedy"]),
                ]
            )
        )

        result = await PvEChallengeService.start_challenge(db, user, cf_mock)
        assert result.problem.rating in [1100, 1250, 1350]

    async def test_range_for_high_elo(self, db):
        """High Elo user should get appropriate range."""
        user = _make_test_user(db, elo=2000)
        db.add(user)
        await db.flush()

        cf_mock = _make_cf_mock(
            _make_cf_problems_response(
                [
                    (100, "A", 1900, ["math"]),  # In [1900, 2200]
                    (100, "B", 1200, ["dp"]),  # Below range
                    (100, "C", 2300, ["greedy"]),  # Above range
                ]
            )
        )

        result = await PvEChallengeService.start_challenge(db, user, cf_mock)
        assert result.problem.rating == 1900


# ---------------------------------------------------------------------------
# 2. Unsolved problem filter tests
# ---------------------------------------------------------------------------


class TestUnsolvedFilter:
    """Test that solved problems are filtered out."""

    async def test_excludes_solved_problems(self, db):
        """Problems in PP records should be excluded from selection."""
        user = _make_test_user(db, elo=1200)
        db.add(user)
        await db.flush()

        # Add a PP record indicating user solved problem 100A
        pp_record = _TestPPRecord(
            user_id=user.id,
            cf_problem_id="100A",
            problem_rating=1200,
            base_pp=5.0,
            final_pp=5.0,
        )
        db.add(pp_record)
        await db.flush()

        cf_mock = _make_cf_mock(
            _make_cf_problems_response(
                [
                    (100, "A", 1200, ["math"]),  # Solved - should be excluded
                    (100, "B", 1250, ["dp"]),  # Unsolved - should be selected
                ]
            )
        )

        result = await PvEChallengeService.start_challenge(db, user, cf_mock)
        assert result.problem.rating == 1250
        assert result.problem.index == "B"


# ---------------------------------------------------------------------------
# 3. Fallback strategy (3 rounds) tests
# ---------------------------------------------------------------------------


class TestFallbackStrategy:
    """Test the 3-round fallback range expansion."""

    async def test_round_1_success(self, db):
        """Round 1 [Elo-100, Elo+200] finds problem."""
        user = _make_test_user(db, elo=1200)
        db.add(user)
        await db.flush()

        cf_mock = _make_cf_mock(
            _make_cf_problems_response(
                [
                    (100, "A", 1250, ["math"]),  # In [1100, 1400]
                ]
            )
        )

        result = await PvEChallengeService.start_challenge(db, user, cf_mock)
        assert result.problem is not None

    async def test_round_2_fallback(self, db):
        """Round 2 [Elo-200, Elo+300] is tried when Round 1 has no match."""
        user = _make_test_user(db, elo=1200)
        db.add(user)
        await db.flush()

        # Round 1 range [1100, 1400]: no problems
        # Round 2 range [1000, 1500]: 1450 is in range
        cf_mock = _make_cf_mock(
            _make_cf_problems_response(
                [
                    (100, "A", 1450, ["math"]),  # Only in Round 2 range
                    (100, "B", 900, ["dp"]),  # Too low for any round
                ]
            )
        )

        result = await PvEChallengeService.start_challenge(db, user, cf_mock)
        assert result.problem.rating == 1450

    async def test_round_3_fallback(self, db):
        """Round 3 [Elo-300, Elo+400] is tried when Rounds 1-2 have no match."""
        user = _make_test_user(db, elo=1200)
        db.add(user)
        await db.flush()

        # Round 1 [1100, 1400]: none
        # Round 2 [1000, 1500]: none
        # Round 3 [900, 1600]: 950 is in range
        cf_mock = _make_cf_mock(
            _make_cf_problems_response(
                [
                    (100, "A", 950, ["math"]),  # Only in Round 3 range
                    (100, "B", 1700, ["dp"]),  # Above all ranges
                ]
            )
        )

        result = await PvEChallengeService.start_challenge(db, user, cf_mock)
        assert result.problem.rating == 950

    async def test_all_rounds_fail(self, db):
        """Returns None when no suitable problem in any round."""
        user = _make_test_user(db, elo=1200)
        db.add(user)
        await db.flush()

        cf_mock = _make_cf_mock(
            _make_cf_problems_response(
                [
                    (100, "A", 500, ["math"]),  # Way too low
                    (100, "B", 3000, ["dp"]),  # Way too high
                ]
            )
        )

        with pytest.raises(NotFoundException, match="No suitable problem found"):
            await PvEChallengeService.start_challenge(db, user, cf_mock)

    async def test_cf_api_unavailable(self, db):
        """Returns None when CF API is unavailable."""
        user = _make_test_user(db, elo=1200)
        db.add(user)
        await db.flush()

        cf_mock = AsyncMock()
        cf_mock.get_problemset_problems.side_effect = Exception("API down")

        with pytest.raises(NotFoundException, match="No suitable problem found"):
            await PvEChallengeService.start_challenge(db, user, cf_mock)

    async def test_empty_problem_list(self, db):
        """Returns None when CF returns empty problem list."""
        user = _make_test_user(db, elo=1200)
        db.add(user)
        await db.flush()

        cf_mock = _make_cf_mock({"problems": []})

        with pytest.raises(NotFoundException, match="No suitable problem found"):
            await PvEChallengeService.start_challenge(db, user, cf_mock)


# ---------------------------------------------------------------------------
# 4. AC settlement tests (S-value + Elo + PP + tokens)
# ---------------------------------------------------------------------------


class TestACSettlement:
    """Test successful AC submission settlement."""

    async def test_ac_first_attempt(self, db):
        """AC on first attempt should give S=1.0 and maximum Elo gain."""
        user = _make_test_user(db, elo=1200, tokens=0)
        db.add(user)
        await db.flush()

        session = _TestPvESession(
            user_id=user.id,
            problem_id="800A",
            problem_rating=1200,
            status="active",
        )
        db.add(session)
        await db.flush()

        result = await PvEChallengeService.submit_result(
            db=db,
            user=user,
            session_id=session.id,
            solved=True,
            time_spent=300.0,  # 5 min
            attempts=1,
            error_count=0,
        )

        assert result.solved is True
        assert result.status == "completed"
        assert result.s_value == 1.0
        assert result.elo_change > 0  # Won against expected 0.5
        assert result.tokens_earned > 0

        await db.refresh(session)
        assert session.status == "completed"
        assert session.elo_change > 0

    async def test_ac_with_errors(self, db):
        """AC with errors should give reduced S-value."""
        user = _make_test_user(db, elo=1200, tokens=0)
        db.add(user)
        await db.flush()

        session = _TestPvESession(
            user_id=user.id,
            problem_id="800A",
            problem_rating=1200,
            status="active",
        )
        db.add(session)
        await db.flush()

        result = await PvEChallengeService.submit_result(
            db=db,
            user=user,
            session_id=session.id,
            solved=True,
            time_spent=600.0,
            attempts=3,
            error_count=2,
        )

        assert result.solved is True
        assert result.s_value == max(0.7, 1.0 - 0.05 * 2)  # 0.9

    async def test_failed_attempt(self, db):
        """Not solved should give S=0 and Elo loss."""
        user = _make_test_user(db, elo=1200, tokens=0)
        db.add(user)
        await db.flush()

        session = _TestPvESession(
            user_id=user.id,
            problem_id="800A",
            problem_rating=1200,
            status="active",
        )
        db.add(session)
        await db.flush()

        result = await PvEChallengeService.submit_result(
            db=db,
            user=user,
            session_id=session.id,
            solved=False,
            time_spent=1200.0,
            attempts=5,
            error_count=4,
        )

        assert result.solved is False
        assert result.s_value == 0.0
        assert result.elo_change < 0  # Lost
        assert result.tokens_earned == 3  # Attempt tokens for green-tier (1200) non-AC

    async def test_tokens_awarded_on_solve(self, db):
        """Tokens should be awarded based on problem rating tier."""
        user = _make_test_user(db, elo=1200, tokens=0)
        db.add(user)
        await db.flush()

        # 1200 rating -> green tier -> 20 tokens
        session = _TestPvESession(
            user_id=user.id,
            problem_id="800A",
            problem_rating=1200,
            status="active",
        )
        db.add(session)
        await db.flush()

        result = await PvEChallengeService.submit_result(
            db=db,
            user=user,
            session_id=session.id,
            solved=True,
            time_spent=300.0,
            attempts=1,
            error_count=0,
        )

        assert result.tokens_earned == 20

    async def test_time_bonus_awarded(self, db):
        """Time bonus should be awarded when time_spent > 20 min."""
        user = _make_test_user(db, elo=1200, tokens=0)
        db.add(user)
        await db.flush()

        # 1200 rating -> green tier -> 20 tokens + 10 time bonus
        session = _TestPvESession(
            user_id=user.id,
            problem_id="800A",
            problem_rating=1200,
            status="active",
        )
        db.add(session)
        await db.flush()

        result = await PvEChallengeService.submit_result(
            db=db,
            user=user,
            session_id=session.id,
            solved=True,
            time_spent=1500.0,  # 25 minutes > 20 min threshold
            attempts=1,
            error_count=0,
        )

        # 20 base + 10 time bonus = 30
        assert result.tokens_earned == 30

    async def test_elo_updated_on_user(self, db):
        """User's Elo should be updated after submission."""
        user = _make_test_user(db, elo=1200, tokens=0)
        db.add(user)
        await db.flush()

        session = _TestPvESession(
            user_id=user.id,
            problem_id="800A",
            problem_rating=1200,
            status="active",
        )
        db.add(session)
        await db.flush()

        await PvEChallengeService.submit_result(
            db=db,
            user=user,
            session_id=session.id,
            solved=True,
            time_spent=300.0,
            attempts=1,
            error_count=0,
        )

        # With S=1.0 and expected_score=0.5 against same rating,
        # Elo should increase
        assert user.elo > 1200


# ---------------------------------------------------------------------------
# 5. Quit penalty tests (3 tiers)
# ---------------------------------------------------------------------------


class TestQuitPenalty:
    """Test the tiered quit penalty system."""

    async def test_quit_zero_submissions_no_penalty(self, db):
        """0 submissions: no Elo change."""
        user = _make_test_user(db, elo=1200)
        db.add(user)
        await db.flush()

        session = _TestPvESession(
            user_id=user.id,
            problem_id="800A",
            problem_rating=1200,
            status="active",
        )
        db.add(session)
        await db.flush()

        result = await PvEChallengeService.quit_challenge(
            db=db,
            user=user,
            session_id=session.id,
            submissions=0,
        )

        assert result["status"] == "quit"
        assert result["elo_change"] == 0
        assert result["penalty"] == 0
        assert result["new_elo"] == 1200

    async def test_quit_1_to_2_submissions_mild_penalty(self, db):
        """1-2 submissions: Elo drops 5-10."""
        user = _make_test_user(db, elo=1200)
        db.add(user)
        await db.flush()

        session = _TestPvESession(
            user_id=user.id,
            problem_id="800A",
            problem_rating=1200,
            status="active",
        )
        db.add(session)
        await db.flush()

        result = await PvEChallengeService.quit_challenge(
            db=db,
            user=user,
            session_id=session.id,
            submissions=1,
        )

        assert result["status"] == "quit"
        assert -10 <= result["elo_change"] <= -5
        assert 5 <= result["penalty"] <= 10

    async def test_quit_2_submissions_mild_penalty(self, db):
        """2 submissions: Elo drops 5-10."""
        user = _make_test_user(db, elo=1200)
        db.add(user)
        await db.flush()

        session = _TestPvESession(
            user_id=user.id,
            problem_id="800A",
            problem_rating=1200,
            status="active",
        )
        db.add(session)
        await db.flush()

        result = await PvEChallengeService.quit_challenge(
            db=db,
            user=user,
            session_id=session.id,
            submissions=2,
        )

        assert result["status"] == "quit"
        assert -10 <= result["elo_change"] <= -5

    async def test_quit_3_plus_submissions_normal_failure(self, db):
        """3+ submissions: treated as normal failure (S=0)."""
        user = _make_test_user(db, elo=1200)
        db.add(user)
        await db.flush()

        session = _TestPvESession(
            user_id=user.id,
            problem_id="800A",
            problem_rating=1200,
            status="active",
        )
        db.add(session)
        await db.flush()

        result = await PvEChallengeService.quit_challenge(
            db=db,
            user=user,
            session_id=session.id,
            submissions=3,
        )

        assert result["status"] == "quit"
        # With S=0 and expected=0.5, Elo should drop by K*0.5
        assert result["elo_change"] < 0
        # Should be a more significant drop than the mild penalty
        assert result["elo_change"] <= -10

    async def test_quit_updates_session_status(self, db):
        """Quit should mark session as 'quit'."""
        user = _make_test_user(db, elo=1200)
        db.add(user)
        await db.flush()

        session = _TestPvESession(
            user_id=user.id,
            problem_id="800A",
            problem_rating=1200,
            status="active",
        )
        db.add(session)
        await db.flush()

        await PvEChallengeService.quit_challenge(
            db=db,
            user=user,
            session_id=session.id,
            submissions=0,
        )

        await db.refresh(session)
        assert session.status == "quit"
        assert session.completed_at is not None


# ---------------------------------------------------------------------------
# 6. Session state machine tests
# ---------------------------------------------------------------------------


class TestSessionStateMachine:
    """Test session state transitions and validation."""

    async def test_submit_on_completed_session_rejected(self, db):
        """Cannot submit result on a completed session."""
        user = _make_test_user(db, elo=1200)
        db.add(user)
        await db.flush()

        session = _TestPvESession(
            user_id=user.id,
            problem_id="800A",
            problem_rating=1200,
            status="completed",
        )
        db.add(session)
        await db.flush()

        with pytest.raises(BadRequestException, match="not active"):
            await PvEChallengeService.submit_result(
                db=db,
                user=user,
                session_id=session.id,
                solved=True,
                time_spent=300.0,
                attempts=1,
            )

    async def test_quit_on_completed_session_rejected(self, db):
        """Cannot quit a completed session."""
        user = _make_test_user(db, elo=1200)
        db.add(user)
        await db.flush()

        session = _TestPvESession(
            user_id=user.id,
            problem_id="800A",
            problem_rating=1200,
            status="completed",
        )
        db.add(session)
        await db.flush()

        with pytest.raises(BadRequestException, match="not active"):
            await PvEChallengeService.quit_challenge(
                db=db,
                user=user,
                session_id=session.id,
                submissions=0,
            )

    async def test_submit_on_quit_session_rejected(self, db):
        """Cannot submit result on a quit session."""
        user = _make_test_user(db, elo=1200)
        db.add(user)
        await db.flush()

        session = _TestPvESession(
            user_id=user.id,
            problem_id="800A",
            problem_rating=1200,
            status="quit",
        )
        db.add(session)
        await db.flush()

        with pytest.raises(BadRequestException, match="not active"):
            await PvEChallengeService.submit_result(
                db=db,
                user=user,
                session_id=session.id,
                solved=True,
                time_spent=300.0,
                attempts=1,
            )

    async def test_session_not_found(self, db):
        """Should raise NotFoundException for nonexistent session."""
        user = _make_test_user(db, elo=1200)
        db.add(user)
        await db.flush()

        with pytest.raises(NotFoundException, match="not found"):
            await PvEChallengeService.submit_result(
                db=db,
                user=user,
                session_id=uuid.uuid4(),
                solved=True,
                time_spent=300.0,
                attempts=1,
            )

    async def test_session_not_owner(self, db):
        """Should raise ForbiddenException when accessing another user's session."""
        user_a = _make_test_user(db, username="user_a", elo=1200)
        user_b = _make_test_user(db, username="user_b", elo=1300)
        db.add_all([user_a, user_b])
        await db.flush()

        session = _TestPvESession(
            user_id=user_a.id,
            problem_id="800A",
            problem_rating=1200,
            status="active",
        )
        db.add(session)
        await db.flush()

        with pytest.raises(ForbiddenException, match="Not the owner"):
            await PvEChallengeService.submit_result(
                db=db,
                user=user_b,
                session_id=session.id,
                solved=True,
                time_spent=300.0,
                attempts=1,
            )

    async def test_active_to_completed(self, db):
        """Active session should transition to completed on submit."""
        user = _make_test_user(db, elo=1200)
        db.add(user)
        await db.flush()

        session = _TestPvESession(
            user_id=user.id,
            problem_id="800A",
            problem_rating=1200,
            status="active",
        )
        db.add(session)
        await db.flush()

        await PvEChallengeService.submit_result(
            db=db,
            user=user,
            session_id=session.id,
            solved=True,
            time_spent=300.0,
            attempts=1,
        )

        await db.refresh(session)
        assert session.status == "completed"
        assert session.completed_at is not None

    async def test_active_to_quit(self, db):
        """Active session should transition to quit."""
        user = _make_test_user(db, elo=1200)
        db.add(user)
        await db.flush()

        session = _TestPvESession(
            user_id=user.id,
            problem_id="800A",
            problem_rating=1200,
            status="active",
        )
        db.add(session)
        await db.flush()

        await PvEChallengeService.quit_challenge(
            db=db,
            user=user,
            session_id=session.id,
            submissions=0,
        )

        await db.refresh(session)
        assert session.status == "quit"


# ---------------------------------------------------------------------------
# 7. Concurrent active session tests
# ---------------------------------------------------------------------------


class TestActiveSessionConstraint:
    """Test that only one active PvE session is allowed per user."""

    async def test_cannot_start_with_active_session(self, db):
        """Should reject starting a new challenge when one is already active."""
        user = _make_test_user(db, elo=1200)
        db.add(user)
        await db.flush()

        # Create an active session
        active_session = _TestPvESession(
            user_id=user.id,
            problem_id="800A",
            problem_rating=1200,
            status="active",
        )
        db.add(active_session)
        await db.flush()

        cf_mock = _make_cf_mock()

        with pytest.raises(BadRequestException, match="already have an active"):
            await PvEChallengeService.start_challenge(db, user, cf_mock)

    async def test_can_start_after_completing(self, db):
        """Should allow starting a new challenge after completing the previous one."""
        user = _make_test_user(db, elo=1200)
        db.add(user)
        await db.flush()

        # Create a completed session
        completed_session = _TestPvESession(
            user_id=user.id,
            problem_id="800A",
            problem_rating=1200,
            status="completed",
        )
        db.add(completed_session)
        await db.flush()

        cf_mock = _make_cf_mock(
            _make_cf_problems_response(
                [
                    (100, "B", 1300, ["dp"]),
                ]
            )
        )

        result = await PvEChallengeService.start_challenge(db, user, cf_mock)
        assert result.status == "active"

    async def test_can_start_after_quitting(self, db):
        """Should allow starting a new challenge after quitting the previous one."""
        user = _make_test_user(db, elo=1200)
        db.add(user)
        await db.flush()

        # Create a quit session
        quit_session = _TestPvESession(
            user_id=user.id,
            problem_id="800A",
            problem_rating=1200,
            status="quit",
        )
        db.add(quit_session)
        await db.flush()

        cf_mock = _make_cf_mock(
            _make_cf_problems_response(
                [
                    (100, "B", 1300, ["dp"]),
                ]
            )
        )

        result = await PvEChallengeService.start_challenge(db, user, cf_mock)
        assert result.status == "active"


# ---------------------------------------------------------------------------
# 8. History tests (paginated)
# ---------------------------------------------------------------------------


class TestHistory:
    """Test paginated history retrieval."""

    async def test_empty_history(self, db):
        """Should return empty list for user with no history."""
        user = _make_test_user(db, elo=1200)
        db.add(user)
        await db.flush()

        result = await PvEChallengeService.get_history(db, user, page=1, page_size=20)
        assert result.total == 0
        assert result.items == []
        assert result.page == 1
        assert result.page_size == 20

    async def test_history_with_sessions(self, db):
        """Should return sessions ordered by created_at desc."""
        user = _make_test_user(db, elo=1200)
        db.add(user)
        await db.flush()

        # Create multiple sessions
        s1 = _TestPvESession(
            user_id=user.id,
            problem_id="800A",
            problem_rating=1200,
            status="completed",
            elo_change=10,
            created_at=datetime(2026, 1, 1),
        )
        s2 = _TestPvESession(
            user_id=user.id,
            problem_id="800B",
            problem_rating=1300,
            status="quit",
            elo_change=-5,
            created_at=datetime(2026, 1, 2),
        )
        s3 = _TestPvESession(
            user_id=user.id,
            problem_id="800C",
            problem_rating=1400,
            status="completed",
            elo_change=15,
            created_at=datetime(2026, 1, 3),
        )
        db.add_all([s1, s2, s3])
        await db.flush()

        result = await PvEChallengeService.get_history(db, user, page=1, page_size=20)
        assert result.total == 3
        assert len(result.items) == 3
        # Most recent first
        assert result.items[0].problem_id == "800C"
        assert result.items[1].problem_id == "800B"
        assert result.items[2].problem_id == "800A"

    async def test_history_pagination(self, db):
        """Should correctly paginate results."""
        user = _make_test_user(db, elo=1200)
        db.add(user)
        await db.flush()

        # Create 5 sessions
        for i in range(5):
            s = _TestPvESession(
                user_id=user.id,
                problem_id=f"800{chr(65 + i)}",
                problem_rating=1200 + i * 100,
                status="completed",
                created_at=datetime(2026, 1, i + 1),
            )
            db.add(s)
        await db.flush()

        # Page 1: 2 items
        page1 = await PvEChallengeService.get_history(db, user, page=1, page_size=2)
        assert page1.total == 5
        assert len(page1.items) == 2
        assert page1.page == 1
        assert page1.page_size == 2

        # Page 2: 2 items
        page2 = await PvEChallengeService.get_history(db, user, page=2, page_size=2)
        assert page2.total == 5
        assert len(page2.items) == 2

        # Page 3: 1 item
        page3 = await PvEChallengeService.get_history(db, user, page=3, page_size=2)
        assert page3.total == 5
        assert len(page3.items) == 1

    async def test_history_only_shows_own_sessions(self, db):
        """Should only return sessions for the requesting user."""
        user_a = _make_test_user(db, username="user_a", elo=1200)
        user_b = _make_test_user(db, username="user_b", elo=1300)
        db.add_all([user_a, user_b])
        await db.flush()

        s_a = _TestPvESession(
            user_id=user_a.id,
            problem_id="800A",
            problem_rating=1200,
            status="completed",
        )
        s_b = _TestPvESession(
            user_id=user_b.id,
            problem_id="800B",
            problem_rating=1300,
            status="completed",
        )
        db.add_all([s_a, s_b])
        await db.flush()

        result = await PvEChallengeService.get_history(db, user_a, page=1, page_size=20)
        assert result.total == 1
        assert result.items[0].problem_id == "800A"


# ---------------------------------------------------------------------------
# 9. Get challenge detail tests
# ---------------------------------------------------------------------------


class TestGetChallengeDetail:
    """Test getting challenge detail."""

    async def test_get_detail_success(self, db):
        """Should return full challenge details."""
        user = _make_test_user(db, elo=1200)
        db.add(user)
        await db.flush()

        session = _TestPvESession(
            user_id=user.id,
            problem_id="800A",
            problem_rating=1200,
            status="completed",
            elo_change=10,
            s_value=1.0,
        )
        db.add(session)
        await db.flush()

        result = await PvEChallengeService.get_challenge(db, user, session.id)
        assert result.id == session.id
        assert result.problem_id == "800A"
        assert result.problem_rating == 1200
        assert result.status == "completed"
        assert result.elo_change == 10
        assert result.s_value == 1.0

    async def test_get_detail_not_found(self, db):
        """Should raise NotFoundException for nonexistent session."""
        user = _make_test_user(db, elo=1200)
        db.add(user)
        await db.flush()

        with pytest.raises(NotFoundException):
            await PvEChallengeService.get_challenge(db, user, uuid.uuid4())

    async def test_get_detail_not_owner(self, db):
        """Should raise ForbiddenException for another user's session."""
        user_a = _make_test_user(db, username="user_a", elo=1200)
        user_b = _make_test_user(db, username="user_b", elo=1300)
        db.add_all([user_a, user_b])
        await db.flush()

        session = _TestPvESession(
            user_id=user_a.id,
            problem_id="800A",
            problem_rating=1200,
            status="active",
        )
        db.add(session)
        await db.flush()

        with pytest.raises(ForbiddenException):
            await PvEChallengeService.get_challenge(db, user_b, session.id)


# ---------------------------------------------------------------------------
# 10. Full PvE flow integration test
# ---------------------------------------------------------------------------


class TestFullPvEFlow:
    """Integration test for the complete PvE challenge lifecycle."""

    async def test_complete_pve_flow(self, db):
        """Test: start -> submit -> verify settlement."""
        user = _make_test_user(db, elo=1200, tokens=0)
        db.add(user)
        await db.flush()

        # Step 1: Start challenge
        cf_mock = _make_cf_mock(
            _make_cf_problems_response(
                [
                    (100, "A", 1200, ["math", "dp"]),
                ]
            )
        )
        start_result = await PvEChallengeService.start_challenge(db, user, cf_mock)
        assert start_result.status == "active"
        session_id = start_result.session_id

        # Step 2: Get detail
        detail = await PvEChallengeService.get_challenge(db, user, session_id)
        assert detail.status == "active"
        assert detail.problem_id == "100A"
        assert detail.problem_rating == 1200

        # Step 3: Submit result (AC)
        submit_result = await PvEChallengeService.submit_result(
            db=db,
            user=user,
            session_id=session_id,
            solved=True,
            time_spent=300.0,
            attempts=1,
            error_count=0,
        )
        assert submit_result.solved is True
        assert submit_result.status == "completed"
        assert submit_result.elo_change > 0
        assert submit_result.tokens_earned > 0

        # Step 4: Verify history
        history = await PvEChallengeService.get_history(db, user, page=1, page_size=20)
        assert history.total == 1
        assert history.items[0].status == "completed"
        assert history.items[0].elo_change == submit_result.elo_change

    async def test_start_quit_start_flow(self, db):
        """Test: start -> quit -> start another."""
        user = _make_test_user(db, elo=1200, tokens=0)
        db.add(user)
        await db.flush()

        # Step 1: Start challenge
        cf_mock = _make_cf_mock(
            _make_cf_problems_response(
                [
                    (100, "A", 1200, ["math"]),
                    (100, "B", 1300, ["dp"]),
                ]
            )
        )
        start_result = await PvEChallengeService.start_challenge(db, user, cf_mock)
        session_id = start_result.session_id

        # Step 2: Quit
        quit_result = await PvEChallengeService.quit_challenge(
            db=db,
            user=user,
            session_id=session_id,
            submissions=0,
        )
        assert quit_result["status"] == "quit"
        assert quit_result["elo_change"] == 0

        # Step 3: Start another
        start_result2 = await PvEChallengeService.start_challenge(db, user, cf_mock)
        assert start_result2.status == "active"

        # Step 4: Verify history has 2 sessions
        history = await PvEChallengeService.get_history(db, user, page=1, page_size=20)
        assert history.total == 2


# ---------------------------------------------------------------------------
# 11. Overkill bonus tests (BUG-001 / BUG-002 regression)
# ---------------------------------------------------------------------------


class TestOverkillBonusInPvE:
    """Verify that PvE challenge passes user_elo to record_pp (BUG-001)
    and that the response includes overkill_multiplier (BUG-002)."""

    async def test_record_pp_receives_user_elo(self, db):
        """PPService.record_pp must receive user_elo=user.elo on solve."""
        user = _make_test_user(db, elo=1000, tokens=0)
        db.add(user)
        await db.flush()

        session = _TestPvESession(
            user_id=user.id,
            problem_id="800A",
            problem_rating=1500,
            status="active",
        )
        db.add(session)
        await db.flush()

        captured_kwargs = {}

        async def _capturing_record_pp(*args, **kwargs):
            captured_kwargs.update(kwargs)
            # Call original mock (no-op)

        with patch.object(pve_svc_module.PPService, "record_pp", _capturing_record_pp):
            await PvEChallengeService.submit_result(
                db=db,
                user=user,
                session_id=session.id,
                solved=True,
                time_spent=300.0,
                attempts=1,
                error_count=0,
            )

        assert "user_elo" in captured_kwargs
        assert captured_kwargs["user_elo"] == 1000

    async def test_overkill_multiplier_in_response_on_overkill(self, db):
        """Response should include overkill_multiplier > 1.0 for large gap."""
        user = _make_test_user(db, elo=1000, tokens=0)
        db.add(user)
        await db.flush()

        session = _TestPvESession(
            user_id=user.id,
            problem_id="800A",
            problem_rating=1500,
            status="active",
        )
        db.add(session)
        await db.flush()

        result = await PvEChallengeService.submit_result(
            db=db,
            user=user,
            session_id=session.id,
            solved=True,
            time_spent=300.0,
            attempts=1,
            error_count=0,
        )

        # gap = 1500 - 1000 = 500 -> x2.0
        assert result.overkill_multiplier == pytest.approx(2.0, abs=1e-6)

    async def test_overkill_multiplier_default_no_overkill(self, db):
        """Response overkill_multiplier should be 1.0 when gap is small."""
        user = _make_test_user(db, elo=1200, tokens=0)
        db.add(user)
        await db.flush()

        session = _TestPvESession(
            user_id=user.id,
            problem_id="800A",
            problem_rating=1300,
            status="active",
        )
        db.add(session)
        await db.flush()

        result = await PvEChallengeService.submit_result(
            db=db,
            user=user,
            session_id=session.id,
            solved=True,
            time_spent=300.0,
            attempts=1,
            error_count=0,
        )

        # gap = 100 -> no overkill
        assert result.overkill_multiplier == pytest.approx(1.0, abs=1e-6)

    async def test_overkill_multiplier_default_on_failure(self, db):
        """Response overkill_multiplier should be 1.0 on failure."""
        user = _make_test_user(db, elo=1000, tokens=0)
        db.add(user)
        await db.flush()

        session = _TestPvESession(
            user_id=user.id,
            problem_id="800A",
            problem_rating=1500,
            status="active",
        )
        db.add(session)
        await db.flush()

        result = await PvEChallengeService.submit_result(
            db=db,
            user=user,
            session_id=session.id,
            solved=False,
            time_spent=600.0,
            attempts=3,
            error_count=2,
        )

        assert result.overkill_multiplier == pytest.approx(1.0, abs=1e-6)

    async def test_overkill_tier1_multiplier(self, db):
        """gap=200 should give x1.2 multiplier."""
        user = _make_test_user(db, elo=1200, tokens=0)
        db.add(user)
        await db.flush()

        session = _TestPvESession(
            user_id=user.id,
            problem_id="800A",
            problem_rating=1400,
            status="active",
        )
        db.add(session)
        await db.flush()

        result = await PvEChallengeService.submit_result(
            db=db,
            user=user,
            session_id=session.id,
            solved=True,
            time_spent=300.0,
            attempts=1,
            error_count=0,
        )

        # gap = 200 -> x1.2
        assert result.overkill_multiplier == pytest.approx(1.2, abs=1e-6)

    async def test_overkill_tier2_multiplier(self, db):
        """gap=300 should give x1.5 multiplier."""
        user = _make_test_user(db, elo=1100, tokens=0)
        db.add(user)
        await db.flush()

        session = _TestPvESession(
            user_id=user.id,
            problem_id="800A",
            problem_rating=1400,
            status="active",
        )
        db.add(session)
        await db.flush()

        result = await PvEChallengeService.submit_result(
            db=db,
            user=user,
            session_id=session.id,
            solved=True,
            time_spent=300.0,
            attempts=1,
            error_count=0,
        )

        # gap = 300 -> x1.5
        assert result.overkill_multiplier == pytest.approx(1.5, abs=1e-6)
