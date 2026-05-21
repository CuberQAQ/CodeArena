"""Tests for the contest system: tier eligibility, timing, settlement, and rewards.

Uses lightweight SQLite-compatible test models and mocks for external services
(CF API).  The key technique is patching the production model references in
contest_service with test-compatible models so SQLAlchemy queries target the
SQLite tables with the correct column set.
"""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import JSON, Boolean, DateTime, Float, Integer, String, event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core.exceptions import BadRequestException, ForbiddenException, NotFoundException
from app.services import contest_service as contest_svc_module
from app.services import economy_service as economy_svc_module
from app.services import elo_service as elo_svc_module
from app.services import hint_service as hint_svc_module
from app.services import pp_service as pp_svc_module
from app.services.config_service import ConfigService
from app.services.contest_service import TIER_CONFIGS, ContestService, _tokens_for_rating
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


class _TestPPRecord(_TestBase):
    __tablename__ = "pp_records"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    cf_problem_id: Mapped[str] = mapped_column(String(50), nullable=False)
    problem_rating: Mapped[int] = mapped_column(Integer, nullable=False)
    base_pp: Mapped[float] = mapped_column(Float, nullable=False)
    solved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    hints_used: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


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


async def _mock_record_elo_history(db, user_id, elo_before, elo_after, reason, reference_id=None):
    """Test replacement for EloService.record_elo_history using test model."""
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


@pytest.fixture
async def db(async_engine):
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

    async def _mock_get_max_hint_level(db, user_id, problem_id):
        """No hints purchased in tests -- return 0."""
        return 0

    async with session_factory() as session:
        # Patch all model references in contest_service module
        with (
            patch.object(contest_svc_module, "ContestSession", _TestContestSession),
            patch.object(contest_svc_module, "ContestProblemRecord", _TestContestProblemRecord),
            patch.object(contest_svc_module, "EloHistory", _TestEloHistory),
            # Patch PPService.record_pp to avoid querying PPRecord/User models
            patch.object(pp_svc_module.PPService, "record_pp", AsyncMock(return_value=None)),
            # Patch EloService.record_elo_history to use test model
            patch.object(
                elo_svc_module.EloService,
                "record_elo_history",
                _mock_record_elo_history,
            ),
            # Patch economy_svc.award_tokens to directly add tokens
            patch.object(economy_svc_module, "award_tokens", _mock_award_tokens),
            # Patch ConfigService and EloService.get_submission_count for K-factor
            patch.object(ConfigService, "get_config", _mock_get_config),
            patch.object(EloService, "get_submission_count", _mock_get_submission_count),
            # Patch HintService.get_max_hint_level for hint attenuation
            patch.object(hint_svc_module.HintService, "get_max_hint_level", _mock_get_max_hint_level),
            # Patch ContestSimulationService to avoid DB operations on contest_bots table
            patch.object(ContestSimulationService, "generate_bots", AsyncMock(return_value=[])),
            patch.object(ContestSimulationService, "stop_simulation", AsyncMock(return_value=False)),
            patch.object(ContestSimulationService, "start_simulation", AsyncMock(return_value=None)),
            # Patch calculate_performance_rating: returns PR scaled by solve ratio
            # PR = 800 + player_solved * 400 (0 solved -> 800, all solved -> 2800)
            patch.object(
                ContestSimulationService,
                "calculate_performance_rating",
                AsyncMock(side_effect=lambda db, contest_id, player_solved: 800 + player_solved * 400),
            ),
            # Patch SubmissionTracker.register_pending to avoid submission_tracking table
            patch.object(SubmissionTracker, "register_pending", AsyncMock()),
        ):
            yield session


def _make_user(**kwargs) -> _TestUser:
    """Create a test user with sensible defaults."""
    defaults = {
        "username": f"user_{uuid.uuid4().hex[:8]}",
        "email": f"{uuid.uuid4().hex[:8]}@test.com",
        "password_hash": "hash",
        "elo": 1200,
        "tokens": 0,
    }
    defaults.update(kwargs)
    return _TestUser(**defaults)


def _make_cf_service_mock(problems=None):
    """Create a mock CF API service returning given problems."""
    cf_mock = AsyncMock()
    if problems is None:
        problems = [
            {"contestId": 1000, "index": "A", "name": "Prob A", "rating": 800, "tags": []},
            {"contestId": 1000, "index": "B", "name": "Prob B", "rating": 1000, "tags": []},
            {"contestId": 1000, "index": "C", "name": "Prob C", "rating": 1200, "tags": []},
            {"contestId": 1000, "index": "D", "name": "Prob D", "rating": 1400, "tags": []},
            {"contestId": 1000, "index": "E", "name": "Prob E", "rating": 1600, "tags": []},
            {"contestId": 1000, "index": "F", "name": "Prob F", "rating": 1800, "tags": []},
            {"contestId": 1000, "index": "G", "name": "Prob G", "rating": 2000, "tags": []},
            {"contestId": 1000, "index": "H", "name": "Prob H", "rating": 2200, "tags": []},
            {"contestId": 1000, "index": "I", "name": "Prob I", "rating": 2400, "tags": []},
            {"contestId": 1000, "index": "J", "name": "Prob J", "rating": 2600, "tags": []},
        ]
    cf_mock.get_problemset_problems.return_value = {"problems": problems}
    return cf_mock


# ===========================================================================
# Test: Tier configuration
# ===========================================================================


class TestTierConfigs:
    """Verify the three contest tiers are correctly configured."""

    def test_beginner_config(self):
        cfg = TIER_CONFIGS["beginner"]
        assert cfg["max_elo"] == 1400
        assert cfg["min_elo"] is None
        assert cfg["duration_minutes"] == 90
        assert cfg["problem_count"] == 4
        assert cfg["rating_range"] == [800, 1400]

    def test_advanced_config(self):
        cfg = TIER_CONFIGS["advanced"]
        assert cfg["min_elo"] == 1400
        assert cfg["max_elo"] == 1800
        assert cfg["duration_minutes"] == 120
        assert cfg["problem_count"] == 5
        assert cfg["rating_range"] == [1200, 2000]

    def test_master_config(self):
        cfg = TIER_CONFIGS["master"]
        assert cfg["min_elo"] == 1800
        assert cfg["max_elo"] is None
        assert cfg["duration_minutes"] == 150
        assert cfg["problem_count"] == 6
        assert cfg["rating_range"] == [1600, 2600]


# ===========================================================================
# Test: Tier eligibility
# ===========================================================================


class TestTierEligibility:
    """Verify tier access control based on user Elo."""

    @pytest.mark.asyncio
    async def test_beginner_eligible_low_elo(self, db):
        """Elo 1300 can participate in beginner contest."""
        user = _make_user(elo=1300)
        db.add(user)
        await db.flush()

        tiers = await ContestService.get_tiers(db, user)
        beginner = next(t for t in tiers if t.tier == "beginner")
        assert beginner.eligible is True

    @pytest.mark.asyncio
    async def test_downgrade_eligible(self, db):
        """Elo 1600 can downgrade to beginner contest."""
        user = _make_user(elo=1600)
        db.add(user)
        await db.flush()

        tiers = await ContestService.get_tiers(db, user)
        beginner = next(t for t in tiers if t.tier == "beginner")
        advanced = next(t for t in tiers if t.tier == "advanced")
        master = next(t for t in tiers if t.tier == "master")

        assert beginner.eligible is True
        assert advanced.eligible is True
        assert master.eligible is False

    @pytest.mark.asyncio
    async def test_cannot_join_above_level(self, db):
        """Elo 1300 cannot join advanced contest."""
        user = _make_user(elo=1300)
        db.add(user)
        await db.flush()

        tiers = await ContestService.get_tiers(db, user)
        advanced = next(t for t in tiers if t.tier == "advanced")
        master = next(t for t in tiers if t.tier == "master")

        assert advanced.eligible is False
        assert master.eligible is False

    @pytest.mark.asyncio
    async def test_high_elo_eligible_for_all(self, db):
        """Elo 1900 can join all tiers."""
        user = _make_user(elo=1900)
        db.add(user)
        await db.flush()

        tiers = await ContestService.get_tiers(db, user)
        for tier in tiers:
            assert tier.eligible is True


# ===========================================================================
# Test: Start contest
# ===========================================================================


class TestStartContest:
    """Verify contest session creation."""

    @pytest.mark.asyncio
    async def test_start_beginner_contest(self, db):
        """Can start beginner contest with low Elo."""
        user = _make_user(elo=1300)
        db.add(user)
        await db.flush()

        cf_mock = _make_cf_service_mock()
        result = await ContestService.start_contest(db, user, "beginner", cf_mock)

        assert result.tier == "beginner"
        assert result.total_problems == 4
        assert result.time_limit_minutes == 90
        assert result.status == "active"
        assert result.remaining_seconds == 90 * 60
        assert len(result.problems) == 4

    @pytest.mark.asyncio
    async def test_start_rejects_invalid_tier(self, db):
        """Rejects unknown tier name."""
        user = _make_user(elo=1300)
        db.add(user)
        await db.flush()

        cf_mock = _make_cf_service_mock()
        with pytest.raises(BadRequestException, match="Invalid tier"):
            await ContestService.start_contest(db, user, "legendary", cf_mock)

    @pytest.mark.asyncio
    async def test_start_rejects_insufficient_elo(self, db):
        """Rejects starting a contest above user's level."""
        user = _make_user(elo=1300)
        db.add(user)
        await db.flush()

        cf_mock = _make_cf_service_mock()
        with pytest.raises(BadRequestException, match="too low"):
            await ContestService.start_contest(db, user, "advanced", cf_mock)

    @pytest.mark.asyncio
    async def test_start_rejects_duplicate_active(self, db):
        """Cannot start a second contest while one is active."""
        user = _make_user(elo=1300)
        db.add(user)
        await db.flush()

        cf_mock = _make_cf_service_mock()
        await ContestService.start_contest(db, user, "beginner", cf_mock)
        await db.commit()

        with pytest.raises(BadRequestException, match="already have an active"):
            await ContestService.start_contest(db, user, "beginner", cf_mock)


# ===========================================================================
# Test: Timing system
# ===========================================================================


class TestTimingSystem:
    """Verify contest timing and auto-expiry."""

    @pytest.mark.asyncio
    async def test_remaining_time_accurate(self, db):
        """Remaining time is calculated accurately."""
        user = _make_user(elo=1300)
        db.add(user)
        await db.flush()

        cf_mock = _make_cf_service_mock()
        started = await ContestService.start_contest(db, user, "beginner", cf_mock)
        await db.commit()

        # Get status -- should have ~90min remaining
        status = await ContestService.get_contest_status(db, user, started.id)

        # Should be very close to 90*60 seconds
        assert status.remaining_seconds is not None
        assert 89 * 60 < status.remaining_seconds <= 90 * 60

    @pytest.mark.asyncio
    async def test_auto_end_on_expiry(self, db):
        """Contest auto-ends when time runs out."""
        user = _make_user(elo=1300)
        db.add(user)
        await db.flush()

        cf_mock = _make_cf_service_mock()
        started = await ContestService.start_contest(db, user, "beginner", cf_mock)
        await db.commit()

        # Manually set started_at to past to simulate expiry
        session = await db.get(_TestContestSession, started.id)
        session.started_at = datetime.now(UTC) - timedelta(minutes=91)
        await db.flush()

        # Get status -- should trigger auto-end
        status = await ContestService.get_contest_status(db, user, started.id)
        assert status.status == "completed"
        assert status.remaining_seconds == 0.0


# ===========================================================================
# Test: Problem submission
# ===========================================================================


class TestSubmitProblem:
    """Verify problem submission and token rewards."""

    @pytest.mark.asyncio
    async def test_submit_solved_problem(self, db):
        """Submitting a solved problem awards correct tokens."""
        user = _make_user(elo=1300)
        db.add(user)
        await db.flush()

        cf_mock = _make_cf_service_mock()
        started = await ContestService.start_contest(db, user, "beginner", cf_mock)
        await db.commit()

        problem = started.problems[0]
        result = await ContestService.submit_problem(
            db,
            user,
            started.id,
            problem_id=problem.problem_id,
            solved=True,
            attempts=1,
            time_spent=300.0,
        )

        assert result.solved is True
        assert result.tokens_earned > 0
        assert user.tokens > 0

    @pytest.mark.asyncio
    async def test_submit_unsolved_problem(self, db):
        """Submitting an unsolved problem awards attempt tokens."""
        user = _make_user(elo=1300)
        db.add(user)
        await db.flush()

        cf_mock = _make_cf_service_mock()
        started = await ContestService.start_contest(db, user, "beginner", cf_mock)
        await db.commit()

        problem = started.problems[0]
        result = await ContestService.submit_problem(
            db,
            user,
            started.id,
            problem_id=problem.problem_id,
            solved=False,
            attempts=2,
            time_spent=300.0,
        )

        assert result.solved is False
        # Unsolved problems now award attempt tokens based on difficulty
        assert result.tokens_earned > 0

    @pytest.mark.asyncio
    async def test_submit_updates_session_counters(self, db):
        """Submission increments session counters."""
        user = _make_user(elo=1300)
        db.add(user)
        await db.flush()

        cf_mock = _make_cf_service_mock()
        started = await ContestService.start_contest(db, user, "beginner", cf_mock)
        await db.commit()

        problem = started.problems[0]
        await ContestService.submit_problem(
            db,
            user,
            started.id,
            problem_id=problem.problem_id,
            solved=True,
            attempts=1,
            time_spent=300.0,
        )
        await db.commit()

        status = await ContestService.get_contest_status(db, user, started.id)
        assert status.submissions == 1
        assert status.problems_solved == 1

    @pytest.mark.asyncio
    async def test_submit_rejects_invalid_problem(self, db):
        """Cannot submit a problem not in this contest."""
        user = _make_user(elo=1300)
        db.add(user)
        await db.flush()

        cf_mock = _make_cf_service_mock()
        started = await ContestService.start_contest(db, user, "beginner", cf_mock)
        await db.commit()

        with pytest.raises(BadRequestException, match="not found"):
            await ContestService.submit_problem(
                db,
                user,
                started.id,
                problem_id="nonexistent",
                solved=True,
                attempts=1,
                time_spent=300.0,
            )

    @pytest.mark.asyncio
    async def test_submit_rejects_already_solved(self, db):
        """Cannot re-submit an already solved problem."""
        user = _make_user(elo=1300)
        db.add(user)
        await db.flush()

        cf_mock = _make_cf_service_mock()
        started = await ContestService.start_contest(db, user, "beginner", cf_mock)
        await db.commit()

        problem = started.problems[0]
        await ContestService.submit_problem(
            db,
            user,
            started.id,
            problem_id=problem.problem_id,
            solved=True,
            attempts=1,
            time_spent=300.0,
        )
        await db.commit()

        with pytest.raises(BadRequestException, match="already solved"):
            await ContestService.submit_problem(
                db,
                user,
                started.id,
                problem_id=problem.problem_id,
                solved=True,
                attempts=2,
                time_spent=600.0,
            )


# ===========================================================================
# Test: Token rewards by difficulty
# ===========================================================================


class TestTokenRewards:
    """Verify token reward tiers for different problem difficulties."""

    @pytest.mark.parametrize(
        "rating,expected",
        [
            (800, 10),
            (900, 10),
            (1199, 10),
            (1200, 20),
            (1300, 20),
            (1399, 20),
            (1400, 25),
            (1500, 25),
            (1599, 25),
            (1600, 35),
            (1750, 35),
            (1899, 35),
            (1900, 45),
            (2000, 45),
            (2099, 45),
            (2100, 55),
            (2250, 55),
            (2399, 55),
            (2400, 65),
            (2500, 65),
            (3000, 65),
        ],
    )
    def test_tokens_for_rating(self, rating, expected):
        """Token reward matches difficulty tier."""
        assert _tokens_for_rating(rating) == expected

    @pytest.mark.asyncio
    async def test_gray_problem_awards_10_tokens(self, db):
        """Gray (800-1199) problem awards 10 tokens on AC."""
        user = _make_user(elo=1300)
        db.add(user)
        await db.flush()

        problems = [
            {"contestId": 100, "index": "A", "name": "Gray", "rating": 900, "tags": []},
            {"contestId": 100, "index": "B", "name": "B", "rating": 1000, "tags": []},
            {"contestId": 100, "index": "C", "name": "C", "rating": 1200, "tags": []},
            {"contestId": 100, "index": "D", "name": "D", "rating": 1300, "tags": []},
        ]
        cf_mock = _make_cf_service_mock(problems=problems)
        started = await ContestService.start_contest(db, user, "beginner", cf_mock)
        await db.commit()

        gray_problem = next(p for p in started.problems if p.rating == 900)
        result = await ContestService.submit_problem(
            db,
            user,
            started.id,
            problem_id=gray_problem.problem_id,
            solved=True,
            attempts=1,
            time_spent=300.0,
        )
        assert result.tokens_earned == 10

    @pytest.mark.asyncio
    async def test_green_problem_awards_20_tokens(self, db):
        """Green (1200-1399) problem awards 20 tokens on AC."""
        user = _make_user(elo=1300)
        db.add(user)
        await db.flush()

        problems = [
            {"contestId": 100, "index": "A", "name": "A", "rating": 800, "tags": []},
            {"contestId": 100, "index": "B", "name": "Green", "rating": 1200, "tags": []},
            {"contestId": 100, "index": "C", "name": "C", "rating": 1300, "tags": []},
            {"contestId": 100, "index": "D", "name": "D", "rating": 1400, "tags": []},
        ]
        cf_mock = _make_cf_service_mock(problems=problems)
        started = await ContestService.start_contest(db, user, "beginner", cf_mock)
        await db.commit()

        green_problem = next(p for p in started.problems if p.rating == 1200)
        result = await ContestService.submit_problem(
            db,
            user,
            started.id,
            problem_id=green_problem.problem_id,
            solved=True,
            attempts=1,
            time_spent=300.0,
        )
        assert result.tokens_earned == 20


# ===========================================================================
# Test: Contest settlement (Elo calculation)
# ===========================================================================


class TestContestSettlement:
    """Verify Elo changes after contest completion."""

    @pytest.mark.asyncio
    async def test_end_contest_0_submissions_no_elo_change(self, db):
        """0 submissions: Elo unchanged."""
        user = _make_user(elo=1300)
        db.add(user)
        await db.flush()

        cf_mock = _make_cf_service_mock()
        started = await ContestService.start_contest(db, user, "beginner", cf_mock)
        await db.commit()

        result = await ContestService.end_contest(db, user, started.id)
        assert result.elo_change == 0
        assert user.elo == 1300

    @pytest.mark.asyncio
    async def test_end_contest_1_submission_penalty(self, db):
        """1 submission: Elo drops 5-10."""
        user = _make_user(elo=1300)
        db.add(user)
        await db.flush()

        cf_mock = _make_cf_service_mock()
        started = await ContestService.start_contest(db, user, "beginner", cf_mock)
        await db.commit()

        # Submit one problem (unsolved) to count as 1 submission
        problem = started.problems[0]
        await ContestService.submit_problem(
            db,
            user,
            started.id,
            problem_id=problem.problem_id,
            solved=False,
            attempts=1,
            time_spent=300.0,
        )
        await db.commit()

        result = await ContestService.end_contest(db, user, started.id)
        assert -10 <= result.elo_change <= -5
        assert user.elo == 1300 + result.elo_change

    @pytest.mark.asyncio
    async def test_end_contest_2_submissions_penalty(self, db):
        """2 submissions: Elo drops 5-10."""
        user = _make_user(elo=1300)
        db.add(user)
        await db.flush()

        cf_mock = _make_cf_service_mock()
        started = await ContestService.start_contest(db, user, "beginner", cf_mock)
        await db.commit()

        # Submit two problems
        for i in range(2):
            problem = started.problems[i]
            await ContestService.submit_problem(
                db,
                user,
                started.id,
                problem_id=problem.problem_id,
                solved=False,
                attempts=1,
                time_spent=300.0,
            )
            await db.commit()

        result = await ContestService.end_contest(db, user, started.id)
        assert -10 <= result.elo_change <= -5

    @pytest.mark.asyncio
    async def test_end_contest_3plus_submissions_melo(self, db):
        """3+ submissions: M-Elo formula used."""
        user = _make_user(elo=1300)
        db.add(user)
        await db.flush()

        cf_mock = _make_cf_service_mock()
        started = await ContestService.start_contest(db, user, "beginner", cf_mock)
        await db.commit()

        # Submit 3 problems, solve 2
        for i in range(3):
            problem = started.problems[i]
            await ContestService.submit_problem(
                db,
                user,
                started.id,
                problem_id=problem.problem_id,
                solved=(i < 2),
                attempts=1,
                time_spent=300.0,
            )
            await db.commit()

        result = await ContestService.end_contest(db, user, started.id)
        # M-Elo should calculate based on 2/4 solved
        assert result.elo_change is not None
        assert user.elo != 1300

    @pytest.mark.asyncio
    async def test_end_contest_all_solved_high_elo_gain(self, db):
        """All problems solved: significant Elo gain."""
        user = _make_user(elo=1300)
        db.add(user)
        await db.flush()

        cf_mock = _make_cf_service_mock()
        started = await ContestService.start_contest(db, user, "beginner", cf_mock)
        await db.commit()

        # Submit 4 problems, all solved
        for i in range(4):
            problem = started.problems[i]
            await ContestService.submit_problem(
                db,
                user,
                started.id,
                problem_id=problem.problem_id,
                solved=True,
                attempts=1,
                time_spent=300.0,
            )
            await db.commit()

        result = await ContestService.end_contest(db, user, started.id)
        # Full solve should give positive Elo
        assert result.elo_change is not None
        assert result.elo_change > 0
        assert user.elo > 1300

    @pytest.mark.asyncio
    async def test_end_contest_zero_solved_elo_decrease(self, db):
        """3+ submissions with 0 solved: Elo decreases."""
        user = _make_user(elo=1300)
        db.add(user)
        await db.flush()

        cf_mock = _make_cf_service_mock()
        started = await ContestService.start_contest(db, user, "beginner", cf_mock)
        await db.commit()

        # Submit 3 problems, none solved
        for i in range(3):
            problem = started.problems[i]
            await ContestService.submit_problem(
                db,
                user,
                started.id,
                problem_id=problem.problem_id,
                solved=False,
                attempts=2,
                time_spent=600.0,
            )
            await db.commit()

        result = await ContestService.end_contest(db, user, started.id)
        assert result.elo_change is not None
        assert result.elo_change < 0
        assert user.elo < 1300


# ===========================================================================
# Test: Contest history
# ===========================================================================


class TestContestHistory:
    """Verify contest history retrieval."""

    @pytest.mark.asyncio
    async def test_history_returns_all_contests(self, db):
        """History returns all contest sessions for the user."""
        user = _make_user(elo=1300)
        db.add(user)
        await db.flush()

        cf_mock = _make_cf_service_mock()

        # Start and end two contests
        c1 = await ContestService.start_contest(db, user, "beginner", cf_mock)
        await db.commit()
        await ContestService.end_contest(db, user, c1.id)
        await db.commit()

        c2 = await ContestService.start_contest(db, user, "beginner", cf_mock)
        await db.commit()
        await ContestService.end_contest(db, user, c2.id)
        await db.commit()

        history = await ContestService.get_contest_history(db, user)
        assert len(history) == 2

    @pytest.mark.asyncio
    async def test_history_ordered_newest_first(self, db):
        """History is ordered newest first."""
        user = _make_user(elo=1300)
        db.add(user)
        await db.flush()

        cf_mock = _make_cf_service_mock()

        c1 = await ContestService.start_contest(db, user, "beginner", cf_mock)
        await db.commit()
        await ContestService.end_contest(db, user, c1.id)
        await db.commit()

        c2 = await ContestService.start_contest(db, user, "beginner", cf_mock)
        await db.commit()
        await ContestService.end_contest(db, user, c2.id)
        await db.commit()

        history = await ContestService.get_contest_history(db, user)
        assert history[0].id == c2.id
        assert history[1].id == c1.id

    @pytest.mark.asyncio
    async def test_history_empty_for_new_user(self, db):
        """History is empty for a user with no contests."""
        user = _make_user(elo=1300)
        db.add(user)
        await db.flush()

        history = await ContestService.get_contest_history(db, user)
        assert len(history) == 0


# ===========================================================================
# Test: Contest result
# ===========================================================================


class TestContestResult:
    """Verify contest result retrieval."""

    @pytest.mark.asyncio
    async def test_result_shows_problem_details(self, db):
        """Result includes problem details with solve status."""
        user = _make_user(elo=1300)
        db.add(user)
        await db.flush()

        cf_mock = _make_cf_service_mock()
        started = await ContestService.start_contest(db, user, "beginner", cf_mock)
        await db.commit()

        # Solve first two problems
        for i in range(2):
            problem = started.problems[i]
            await ContestService.submit_problem(
                db,
                user,
                started.id,
                problem_id=problem.problem_id,
                solved=True,
                attempts=1,
                time_spent=300.0,
            )
            await db.commit()

        # End contest
        await ContestService.end_contest(db, user, started.id)
        await db.commit()

        # Get result
        result = await ContestService.get_contest_result(db, user, started.id)

        assert result.problems_solved == 2
        assert result.total_problems == 4
        assert len(result.problems) == 4

        solved_count = sum(1 for p in result.problems if p.solved)
        assert solved_count == 2


# ===========================================================================
# Test: Access control
# ===========================================================================


class TestAccessControl:
    """Verify session ownership checks."""

    @pytest.mark.asyncio
    async def test_cannot_access_other_users_contest(self, db):
        """Cannot access another user's contest session."""
        user1 = _make_user(elo=1300)
        user2 = _make_user(elo=1300)
        db.add_all([user1, user2])
        await db.flush()

        cf_mock = _make_cf_service_mock()
        started = await ContestService.start_contest(db, user1, "beginner", cf_mock)
        await db.commit()

        with pytest.raises(ForbiddenException, match="Not your"):
            await ContestService.get_contest_status(db, user2, started.id)

    @pytest.mark.asyncio
    async def test_cannot_submit_to_other_users_contest(self, db):
        """Cannot submit to another user's contest."""
        user1 = _make_user(elo=1300)
        user2 = _make_user(elo=1300)
        db.add_all([user1, user2])
        await db.flush()

        cf_mock = _make_cf_service_mock()
        started = await ContestService.start_contest(db, user1, "beginner", cf_mock)
        await db.commit()

        problem = started.problems[0]
        with pytest.raises(ForbiddenException, match="Not your"):
            await ContestService.submit_problem(
                db,
                user2,
                started.id,
                problem_id=problem.problem_id,
                solved=True,
                attempts=1,
                time_spent=300.0,
            )

    @pytest.mark.asyncio
    async def test_not_found_for_nonexistent_contest(self, db):
        """Raises NotFoundException for non-existent contest."""
        user = _make_user(elo=1300)
        db.add(user)
        await db.flush()

        with pytest.raises(NotFoundException, match="not found"):
            await ContestService.get_contest_status(db, user, uuid.uuid4())


# ===========================================================================
# Test: Only one active contest
# ===========================================================================


class TestConcurrentContest:
    """Verify only one active contest at a time."""

    @pytest.mark.asyncio
    async def test_cannot_start_second_active_contest(self, db):
        """Cannot start a second contest while one is active."""
        user = _make_user(elo=1300)
        db.add(user)
        await db.flush()

        cf_mock = _make_cf_service_mock()
        await ContestService.start_contest(db, user, "beginner", cf_mock)
        await db.commit()

        with pytest.raises(BadRequestException, match="already have an active"):
            await ContestService.start_contest(db, user, "beginner", cf_mock)

    @pytest.mark.asyncio
    async def test_can_start_after_ending(self, db):
        """Can start a new contest after ending the previous one."""
        user = _make_user(elo=1300)
        db.add(user)
        await db.flush()

        cf_mock = _make_cf_service_mock()
        c1 = await ContestService.start_contest(db, user, "beginner", cf_mock)
        await db.commit()

        await ContestService.end_contest(db, user, c1.id)
        await db.commit()

        c2 = await ContestService.start_contest(db, user, "beginner", cf_mock)
        assert c2.id != c1.id
        assert c2.status == "active"


# ===========================================================================
# Test: Problem selection
# ===========================================================================


class TestProblemSelection:
    """Verify problem selection from CF API."""

    @pytest.mark.asyncio
    async def test_problems_within_rating_range(self, db):
        """All selected problems are within the tier's rating range."""
        user = _make_user(elo=1300)
        db.add(user)
        await db.flush()

        cf_mock = _make_cf_service_mock()
        result = await ContestService.start_contest(db, user, "beginner", cf_mock)

        for problem in result.problems:
            assert 800 <= problem.rating <= 1400

    @pytest.mark.asyncio
    async def test_correct_problem_count_per_tier(self, db):
        """Each tier selects the correct number of problems."""
        user = _make_user(elo=2000)
        db.add(user)
        await db.flush()

        cf_mock = _make_cf_service_mock()

        # Beginner: 4 problems
        beginner = await ContestService.start_contest(db, user, "beginner", cf_mock)
        assert len(beginner.problems) == 4
        await ContestService.end_contest(db, user, beginner.id)
        await db.commit()

        # Advanced: 5 problems
        advanced = await ContestService.start_contest(db, user, "advanced", cf_mock)
        assert len(advanced.problems) == 5
        await ContestService.end_contest(db, user, advanced.id)
        await db.commit()

        # Master: 6 problems
        master = await ContestService.start_contest(db, user, "master", cf_mock)
        assert len(master.problems) == 6

    @pytest.mark.asyncio
    async def test_cf_api_failure_uses_placeholders(self, db):
        """When CF API fails, placeholder problems are generated."""
        user = _make_user(elo=1300)
        db.add(user)
        await db.flush()

        cf_mock = AsyncMock()
        cf_mock.get_problemset_problems.side_effect = Exception("API down")

        result = await ContestService.start_contest(db, user, "beginner", cf_mock)

        assert len(result.problems) == 4
        for p in result.problems:
            assert "placeholder" in p.problem_id


# ===========================================================================
# Test: Elo change via M-Elo formula
# ===========================================================================


class TestMEloCalculation:
    """Verify M-Elo formula produces correct Elo changes."""

    @pytest.mark.asyncio
    async def test_full_solve_gives_positive_elo(self, db):
        """Solving all problems gives positive Elo change."""
        user = _make_user(elo=1500)
        db.add(user)
        await db.flush()

        cf_mock = _make_cf_service_mock()
        started = await ContestService.start_contest(db, user, "advanced", cf_mock)
        await db.commit()

        for problem in started.problems:
            await ContestService.submit_problem(
                db,
                user,
                started.id,
                problem_id=problem.problem_id,
                solved=True,
                attempts=1,
                time_spent=300.0,
            )
            await db.commit()

        result = await ContestService.end_contest(db, user, started.id)
        assert result.elo_change > 0

    @pytest.mark.asyncio
    async def test_zero_solve_3plus_gives_negative_elo(self, db):
        """3+ submissions with 0 solved gives negative Elo."""
        user = _make_user(elo=1500)
        db.add(user)
        await db.flush()

        cf_mock = _make_cf_service_mock()
        started = await ContestService.start_contest(db, user, "advanced", cf_mock)
        await db.commit()

        for i in range(3):
            problem = started.problems[i]
            await ContestService.submit_problem(
                db,
                user,
                started.id,
                problem_id=problem.problem_id,
                solved=False,
                attempts=3,
                time_spent=600.0,
            )
            await db.commit()

        result = await ContestService.end_contest(db, user, started.id)
        assert result.elo_change < 0

    @pytest.mark.asyncio
    async def test_partial_solve_proportional_elo(self, db):
        """Partial solve gives proportionally smaller Elo than full solve."""
        user1 = _make_user(elo=1500)
        db.add(user1)
        await db.flush()

        user2 = _make_user(elo=1500)
        db.add(user2)
        await db.flush()

        cf_mock = _make_cf_service_mock()

        # User1 solves all
        started1 = await ContestService.start_contest(db, user1, "advanced", cf_mock)
        await db.commit()
        for problem in started1.problems:
            await ContestService.submit_problem(
                db,
                user1,
                started1.id,
                problem_id=problem.problem_id,
                solved=True,
                attempts=1,
                time_spent=300.0,
            )
            await db.commit()
        result1 = await ContestService.end_contest(db, user1, started1.id)
        await db.commit()

        # User2 solves half
        started2 = await ContestService.start_contest(db, user2, "advanced", cf_mock)
        await db.commit()
        for i in range(3):
            problem = started2.problems[i]
            await ContestService.submit_problem(
                db,
                user2,
                started2.id,
                problem_id=problem.problem_id,
                solved=(i < 2),
                attempts=1,
                time_spent=300.0,
            )
            await db.commit()
        result2 = await ContestService.end_contest(db, user2, started2.id)
        await db.commit()

        # Full solve should give more Elo than partial
        assert result1.elo_change > result2.elo_change


# ===========================================================================
# Test: End contest rejects inactive sessions
# ===========================================================================


class TestEndContestValidation:
    """Verify end contest validates session state."""

    @pytest.mark.asyncio
    async def test_cannot_end_completed_contest(self, db):
        """Cannot end an already completed contest."""
        user = _make_user(elo=1300)
        db.add(user)
        await db.flush()

        cf_mock = _make_cf_service_mock()
        started = await ContestService.start_contest(db, user, "beginner", cf_mock)
        await db.commit()

        await ContestService.end_contest(db, user, started.id)
        await db.commit()

        with pytest.raises(BadRequestException, match="not active"):
            await ContestService.end_contest(db, user, started.id)


# ===========================================================================
# Test: Get active contest
# ===========================================================================


class TestGetActiveContest:
    """Verify get_active_contest returns the active session or None."""

    @pytest.mark.asyncio
    async def test_returns_none_when_no_active(self, db):
        """Returns None when the user has no active contest."""
        user = _make_user(elo=1300)
        db.add(user)
        await db.flush()

        result = await ContestService.get_active_contest(db, user)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_after_ended(self, db):
        """Returns None after contest has been ended."""
        user = _make_user(elo=1300)
        db.add(user)
        await db.flush()

        cf_mock = _make_cf_service_mock()
        started = await ContestService.start_contest(db, user, "beginner", cf_mock)
        await db.commit()

        await ContestService.end_contest(db, user, started.id)
        await db.commit()

        result = await ContestService.get_active_contest(db, user)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_active_contest_info(self, db):
        """Returns ContestSessionInfo when user has an active contest."""
        user = _make_user(elo=1300)
        db.add(user)
        await db.flush()

        cf_mock = _make_cf_service_mock()
        started = await ContestService.start_contest(db, user, "beginner", cf_mock)
        await db.commit()

        result = await ContestService.get_active_contest(db, user)
        assert result is not None
        assert result.id == started.id
        assert result.tier == "beginner"
        assert result.status == "active"
        assert result.remaining_seconds is not None
        assert result.remaining_seconds > 0
        assert len(result.problems) == 4

    @pytest.mark.asyncio
    async def test_auto_ends_expired_contest(self, db):
        """Auto-ends contest and returns None when time has expired."""
        user = _make_user(elo=1300)
        db.add(user)
        await db.flush()

        cf_mock = _make_cf_service_mock()
        started = await ContestService.start_contest(db, user, "beginner", cf_mock)
        await db.commit()

        # Manually set started_at to past to simulate expiry
        session = await db.get(_TestContestSession, started.id)
        session.started_at = datetime.now(UTC) - timedelta(minutes=91)
        await db.flush()

        result = await ContestService.get_active_contest(db, user)
        assert result is None

        # Verify the contest was auto-ended
        await db.refresh(session)
        assert session.status == "completed"

    @pytest.mark.asyncio
    async def test_includes_problem_info(self, db):
        """Returned info includes problem details with solve status."""
        user = _make_user(elo=1300)
        db.add(user)
        await db.flush()

        cf_mock = _make_cf_service_mock()
        started = await ContestService.start_contest(db, user, "beginner", cf_mock)
        await db.commit()

        # Solve one problem
        problem = started.problems[0]
        await ContestService.submit_problem(
            db,
            user,
            started.id,
            problem_id=problem.problem_id,
            solved=True,
            attempts=1,
            time_spent=300.0,
        )
        await db.commit()

        result = await ContestService.get_active_contest(db, user)
        assert result is not None
        assert result.problems_solved == 1

        solved_problem = next(p for p in result.problems if p.problem_id == problem.problem_id)
        assert solved_problem.solved is True

    @pytest.mark.asyncio
    async def test_does_not_return_other_users_contest(self, db):
        """Only returns active contests belonging to the requesting user."""
        user1 = _make_user(elo=1300)
        user2 = _make_user(elo=1300)
        db.add_all([user1, user2])
        await db.flush()

        cf_mock = _make_cf_service_mock()
        await ContestService.start_contest(db, user1, "beginner", cf_mock)
        await db.commit()

        # user2 should have no active contest
        result = await ContestService.get_active_contest(db, user2)
        assert result is None
