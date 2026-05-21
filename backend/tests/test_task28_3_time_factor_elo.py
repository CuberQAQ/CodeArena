"""Tests for Task 28.3: Time factor integration into Elo settlement (FR-16.4).

Verifies that the time_factor is correctly applied to Elo calculations in all
four game modes:
- PvE (Player vs Environment) challenge
- PvP (Player vs Player) challenge
- Training mode
- Contest mode

Cross-cutting checks:
- Fast solve -> time_factor > 1 (Elo bonus)
- Slow solve -> time_factor < 1 (Elo reduction)
- S=0 (failure) -> time_factor = 1.0 (no effect)
- WA penalty increases effective_time
- Hint attenuation + time factor stack multiplicatively
"""

import json
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import DateTime, Float, Integer, String, TypeDecorator, event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.services import contest_service as contest_svc_module
from app.services import economy_service as economy_svc_module
from app.services import pve_challenge_service as pve_svc_module
from app.services import training_service as training_svc_module
from app.services.elo_service import EloService
from app.services.pp_service import PPService as _RealPPService
from app.services.time_factor_service import TimeFactorService

# ---------------------------------------------------------------------------
# SQLite JSON type helper
# ---------------------------------------------------------------------------


class JSONText(TypeDecorator):
    impl = String(2000)
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
# Shared lightweight test models
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
    time_factor: Mapped[float | None] = mapped_column(Float, nullable=True)
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


# PvE-specific models
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


# Contest-specific models
class _TestContestSession(_TestBase):
    __tablename__ = "contest_sessions"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    contest_tier: Mapped[str] = mapped_column(String(20), default="beginner", nullable=False)
    problems: Mapped[str | None] = mapped_column(JSONText, nullable=True)
    total_problems: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    problems_solved: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    submissions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    time_limit: Mapped[int] = mapped_column(Integer, default=90, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    elo_change: Mapped[int | None] = mapped_column(Integer, nullable=True)


class _TestContestProblemRecord(_TestBase):
    __tablename__ = "contest_problem_records"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    contest_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    problem_id: Mapped[str] = mapped_column(String(50), nullable=False)
    problem_rating: Mapped[int] = mapped_column(Integer, default=1000, nullable=False)
    solved: Mapped[bool] = mapped_column(Integer, default=0, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    time_spent: Mapped[float | None] = mapped_column(Float, nullable=True)
    solved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


# Training-specific models
class _TestTopicCategory(_TestBase):
    __tablename__ = "topic_categories"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    slug: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    cf_tags: Mapped[str | None] = mapped_column(JSONText, nullable=True)
    display_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class _TestTrainingSession(_TestBase):
    __tablename__ = "training_sessions"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    topic_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    total_problems: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    problems_solved: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    streak_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class _TestTrainingProblemRecord(_TestBase):
    __tablename__ = "training_problem_records"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    topic_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    problem_id: Mapped[str] = mapped_column(String(50), nullable=False)
    problem_rating: Mapped[int] = mapped_column(Integer, default=1000, nullable=False)
    solved: Mapped[bool] = mapped_column(Integer, default=0, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    time_spent: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    solved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class _TestUserTagElo(_TestBase):
    __tablename__ = "user_tag_elos"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    tag: Mapped[str] = mapped_column(String(100), nullable=False)
    elo: Mapped[int] = mapped_column(Integer, default=1200, nullable=False)
    total_submissions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    first_ac_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


# ---------------------------------------------------------------------------
# Shared engine fixture
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


def _make_test_user(
    user_id: uuid.UUID | None = None,
    username: str = "testuser",
    elo: int = 1200,
    tokens: int = 0,
) -> _TestUser:
    return _TestUser(
        id=user_id or uuid.uuid4(),
        username=username,
        email=f"{username}@test.com",
        password_hash="$2b$12$fakehash",
        elo=elo,
        tokens=tokens,
    )


# Helper to create a cf_service mock that returns a specific expected_time
def _make_cf_service_mock(expected_time_seconds: float = 1800.0):
    """Create a cf_service mock whose calculate_expected_time returns expected_time_seconds."""
    mock = AsyncMock()
    # calculate_expected_time is a static method on TimeFactorService
    # We'll patch TimeFactorService.calculate_expected_time instead
    return mock


# ===========================================================================
# PART 1: Unit tests for TimeFactorService core functions
# ===========================================================================


class TestTimeFactorUnit:
    """Verify TimeFactorService core math used by the Elo integration."""

    def test_compute_effective_time_no_wa(self):
        """No WA: effective_time = solve_time."""
        result = TimeFactorService.compute_effective_time(600.0, 0)
        assert result == 600.0

    def test_compute_effective_time_with_wa(self):
        """3 WA: effective_time = solve_time + 3*20*60."""
        result = TimeFactorService.compute_effective_time(600.0, 3)
        # 600 + 3*20*60 = 600 + 3600 = 4200
        assert result == 4200.0

    def test_calculate_time_factor_fast_solve(self):
        """Fast solve: expected=1800, effective=600 -> factor=1800/600=1.5 clamped."""
        result = TimeFactorService.calculate_time_factor(600.0, 1800.0, 1.0)
        assert result == 1.5

    def test_calculate_time_factor_slow_solve(self):
        """Slow solve: expected=600, effective=1800 -> factor=600/1800=0.333 clamped to 0.5."""
        result = TimeFactorService.calculate_time_factor(1800.0, 600.0, 1.0)
        assert result == 0.5

    def test_calculate_time_factor_s0_returns_1(self):
        """S=0 (failure): time_factor is 1.0 regardless of time."""
        result = TimeFactorService.calculate_time_factor(600.0, 1800.0, 0.0)
        assert result == 1.0

    def test_calculate_time_factor_equal_times(self):
        """effective == expected: factor = 1.0."""
        result = TimeFactorService.calculate_time_factor(1800.0, 1800.0, 1.0)
        assert result == pytest.approx(1.0)


# ===========================================================================
# PART 2: PvE Challenge mode time factor
# ===========================================================================


@pytest.fixture
async def pve_db(async_engine):
    """PvE test session with all mocks."""
    session_factory = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)

    async def _mock_award_tokens(db, user, amount, **kwargs):
        user.tokens += amount
        return amount

    async def _mock_get_config(db, key):
        from app.core.default_config import DEFAULT_CONFIG

        return DEFAULT_CONFIG.get("elo", {})

    async def _mock_get_submission_count(db, user_id):
        return 0

    async def _mock_record_pp(db, **kwargs):
        pass

    async def _mock_record_elo_history(db, user_id, elo_before, elo_after, reason, reference_id=None, time_factor=None):
        pass

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
            patch.object(pve_svc_module, "AchievementService") as mock_ach_cls,
            patch.object(pve_svc_module, "TimeFactorService") as mock_tf_cls,
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
            mock_elo_cls.apply_hint_attenuation = staticmethod(EloService.apply_hint_attenuation)
            mock_pp_cls.record_pp = _mock_record_pp
            mock_pp_cls.calculate_overkill_multiplier = staticmethod(_RealPPService.calculate_overkill_multiplier)
            mock_hint_cls.get_max_hint_level = AsyncMock(return_value=0)
            mock_ach_cls.check_overkill = staticmethod(lambda **kwargs: None)
            mock_ach_cls.check_personal_best_pp = staticmethod(lambda **kwargs: None)
            # Use REAL TimeFactorService for unit correctness
            mock_tf_cls.compute_effective_time = staticmethod(TimeFactorService.compute_effective_time)
            mock_tf_cls.calculate_time_factor = staticmethod(TimeFactorService.calculate_time_factor)
            mock_tf_cls.calculate_expected_time = AsyncMock(return_value=1800.0)

            yield session


async def _setup_pve_session(db, user, problem_id="800A", problem_rating=1500):
    """Create an active PvE session in the DB."""
    session = _TestPvESession(
        user_id=user.id,
        problem_id=problem_id,
        problem_rating=problem_rating,
        problem_tags=["math"],
        status="active",
    )
    db.add(session)
    await db.flush()
    return session


class TestPvETimeFactor:
    """PvE challenge: verify time factor on Elo changes."""

    @pytest.mark.asyncio
    async def test_fast_solve_elo_bonus(self, pve_db):
        """PvE - Fast solve (600s < expected 1800s) should increase Elo gain."""
        db = pve_db
        user = _make_test_user(elo=1200)
        db.add(user)
        pve_session = await _setup_pve_session(db, user, problem_rating=1500)
        await db.flush()

        # Expected time = 1800s, solve time = 600s -> factor = 1.5
        result_fast = await pve_svc_module.PvEChallengeService.submit_result(
            db=db,
            user=user,
            session_id=pve_session.id,
            solved=True,
            time_spent=600.0,
            attempts=1,
            cf_service=AsyncMock(),
        )

        # Baseline: no time factor (cf_service=None)
        user2 = _make_test_user(elo=1200, username="user2")
        db.add(user2)
        pve_session2 = await _setup_pve_session(db, user2, problem_rating=1500)
        await db.flush()

        result_baseline = await pve_svc_module.PvEChallengeService.submit_result(
            db=db,
            user=user2,
            session_id=pve_session2.id,
            solved=True,
            time_spent=600.0,
            attempts=1,
            cf_service=None,
        )

        assert result_fast.elo_change > result_baseline.elo_change, (
            f"Fast solve ({result_fast.elo_change}) should give more Elo than baseline ({result_baseline.elo_change})"
        )

    @pytest.mark.asyncio
    async def test_slow_solve_elo_reduction(self, pve_db):
        """PvE - Slow solve (3600s > expected 1800s) should reduce Elo gain."""
        db = pve_db
        user = _make_test_user(elo=1200)
        db.add(user)
        pve_session = await _setup_pve_session(db, user, problem_rating=1500)
        await db.flush()

        # Expected time = 1800s, solve time = 3600s -> factor = 1800/3600 = 0.5
        result_slow = await pve_svc_module.PvEChallengeService.submit_result(
            db=db,
            user=user,
            session_id=pve_session.id,
            solved=True,
            time_spent=3600.0,
            attempts=1,
            cf_service=AsyncMock(),
        )

        # Baseline: no time factor
        user2 = _make_test_user(elo=1200, username="user2")
        db.add(user2)
        pve_session2 = await _setup_pve_session(db, user2, problem_rating=1500)
        await db.flush()

        result_baseline = await pve_svc_module.PvEChallengeService.submit_result(
            db=db,
            user=user2,
            session_id=pve_session2.id,
            solved=True,
            time_spent=600.0,
            attempts=1,
            cf_service=None,
        )

        assert result_slow.elo_change < result_baseline.elo_change, (
            f"Slow solve ({result_slow.elo_change}) should give less Elo than baseline ({result_baseline.elo_change})"
        )

    @pytest.mark.asyncio
    async def test_failure_no_time_factor_effect(self, pve_db):
        """PvE - Failed solve: time_factor does not affect Elo loss."""
        db = pve_db
        user = _make_test_user(elo=1200)
        db.add(user)
        pve_session = await _setup_pve_session(db, user, problem_rating=800)
        await db.flush()

        result_with_tf = await pve_svc_module.PvEChallengeService.submit_result(
            db=db,
            user=user,
            session_id=pve_session.id,
            solved=False,
            time_spent=600.0,
            attempts=3,
            cf_service=AsyncMock(),
        )

        user2 = _make_test_user(elo=1200, username="user2")
        db.add(user2)
        pve_session2 = await _setup_pve_session(db, user2, problem_rating=800)
        await db.flush()

        result_no_tf = await pve_svc_module.PvEChallengeService.submit_result(
            db=db,
            user=user2,
            session_id=pve_session2.id,
            solved=False,
            time_spent=600.0,
            attempts=3,
            cf_service=None,
        )

        assert result_with_tf.elo_change == result_no_tf.elo_change, (
            f"Failure should be same with/without time factor: {result_with_tf.elo_change} vs {result_no_tf.elo_change}"
        )

    @pytest.mark.asyncio
    async def test_wa_penalty_increases_effective_time(self, pve_db):
        """PvE - 3 WA adds 60 min to effective time, reducing Elo gain."""
        db = pve_db

        # Fast solve with 0 WA
        user1 = _make_test_user(elo=1200, username="user1")
        db.add(user1)
        pve_session1 = await _setup_pve_session(db, user1, problem_rating=1500)
        await db.flush()

        result_no_wa = await pve_svc_module.PvEChallengeService.submit_result(
            db=db,
            user=user1,
            session_id=pve_session1.id,
            solved=True,
            time_spent=600.0,
            attempts=1,
            error_count=0,
            cf_service=AsyncMock(),
        )

        # Same solve time but 3 WA -> effective_time = 600 + 3*20*60 = 4200
        user2 = _make_test_user(elo=1200, username="user2")
        db.add(user2)
        pve_session2 = await _setup_pve_session(db, user2, problem_rating=1500)
        await db.flush()

        result_with_wa = await pve_svc_module.PvEChallengeService.submit_result(
            db=db,
            user=user2,
            session_id=pve_session2.id,
            solved=True,
            time_spent=600.0,
            attempts=4,
            error_count=3,
            cf_service=AsyncMock(),
        )

        assert result_no_wa.elo_change > result_with_wa.elo_change, (
            f"No WA ({result_no_wa.elo_change}) should give more Elo than 3 WA ({result_with_wa.elo_change})"
        )

    @pytest.mark.asyncio
    async def test_hint_attenuation_and_time_factor_stack(self, pve_db):
        """PvE - Hint level 2 (x0.50) + fast solve (x1.5) stack multiplicatively."""
        db = pve_db

        # No hint, no time factor baseline
        user1 = _make_test_user(elo=1200, username="user1")
        db.add(user1)
        pve_session1 = await _setup_pve_session(db, user1, problem_rating=1500)
        await db.flush()

        result_baseline = await pve_svc_module.PvEChallengeService.submit_result(
            db=db,
            user=user1,
            session_id=pve_session1.id,
            solved=True,
            time_spent=600.0,
            attempts=1,
            cf_service=None,
        )

        # Hint level 2 + fast solve (tf=1.5)
        user2 = _make_test_user(elo=1200, username="user2")
        db.add(user2)
        pve_session2 = await _setup_pve_session(db, user2, problem_rating=1500)
        await db.flush()

        with patch.object(pve_svc_module.HintService, "get_max_hint_level", AsyncMock(return_value=2)):
            result_stacked = await pve_svc_module.PvEChallengeService.submit_result(
                db=db,
                user=user2,
                session_id=pve_session2.id,
                solved=True,
                time_spent=600.0,
                attempts=1,
                cf_service=AsyncMock(),
            )

        # Expected: baseline * 0.50 (hint) * 1.5 (time factor) = baseline * 0.75
        expected_stacked = round(result_baseline.elo_change * 0.50 * 1.5)
        assert result_stacked.elo_change == expected_stacked, (
            f"Stacked: {result_stacked.elo_change} vs expected "
            f"{expected_stacked} (baseline={result_baseline.elo_change})"
        )


# ===========================================================================
# PART 3: PvP Challenge mode time factor
# ===========================================================================


class TestEloServiceTimeFactor:
    """Test EloService.process_challenge_result with time_factor parameters."""

    @pytest.mark.asyncio
    async def test_time_factor_applied_to_positive_challenger(self):
        """PvP - time_factor_challenger > 1 increases challenger Elo gain."""
        db_mock = AsyncMock()
        db_mock.flush = AsyncMock()

        # Challenger wins with expected score 0.5 -> raw_change = 32 * (1 - 0.5) = 16
        # With time_factor 1.5: 16 * 1.5 = 24
        new_a, new_b, change_a, change_b = await EloService.process_challenge_result(
            db=db_mock,
            challenger_id=uuid.uuid4(),
            opponent_id=uuid.uuid4(),
            challenger_rating=1200,
            opponent_rating=1200,
            actual_score_a=1.0,
            session_id=uuid.uuid4(),
            time_factor_challenger=1.5,
            time_factor_opponent=None,
        )

        # Challenger: 1200 + round(32 * (1.0 - 0.5) * 1.5) = 1200 + 24 = 1224
        assert change_a == 24, f"Expected 24, got {change_a}"
        assert new_a == 1224

    @pytest.mark.asyncio
    async def test_time_factor_not_applied_to_loss(self):
        """PvP - time_factor does not affect negative Elo changes (losses)."""
        db_mock = AsyncMock()
        db_mock.flush = AsyncMock()

        # Challenger loses: raw_change = 32 * (0 - 0.5) = -16
        new_a, new_b, change_a, change_b = await EloService.process_challenge_result(
            db=db_mock,
            challenger_id=uuid.uuid4(),
            opponent_id=uuid.uuid4(),
            challenger_rating=1200,
            opponent_rating=1200,
            actual_score_a=0.0,
            session_id=uuid.uuid4(),
            time_factor_challenger=1.5,
        )

        # Challenger: 1200 + round(32 * (0 - 0.5)) = 1200 - 16 = 1184
        assert change_a == -16, f"Loss should not be affected by time_factor: {change_a}"

    @pytest.mark.asyncio
    async def test_time_factor_stacks_with_hint_attenuation(self):
        """PvP - Hint level 2 (x0.50) + time_factor 1.5 stack on positive gains."""
        db_mock = AsyncMock()
        db_mock.flush = AsyncMock()

        new_a, _, change_a, _ = await EloService.process_challenge_result(
            db=db_mock,
            challenger_id=uuid.uuid4(),
            opponent_id=uuid.uuid4(),
            challenger_rating=1200,
            opponent_rating=1200,
            actual_score_a=1.0,
            session_id=uuid.uuid4(),
            hint_level_challenger=2,
            time_factor_challenger=1.5,
        )

        # raw = 32 * (1 - 0.5) = 16
        # hint attenuation level 2: 16 * 0.50 = 8
        # time factor: 8 * 1.5 = 12
        assert change_a == 12, f"Expected 12 (16*0.5*1.5), got {change_a}"

    @pytest.mark.asyncio
    async def test_none_time_factor_no_effect(self):
        """PvP - None time_factor has no effect on Elo calculation."""
        db_mock = AsyncMock()
        db_mock.flush = AsyncMock()

        new_a, _, change_a, _ = await EloService.process_challenge_result(
            db=db_mock,
            challenger_id=uuid.uuid4(),
            opponent_id=uuid.uuid4(),
            challenger_rating=1200,
            opponent_rating=1200,
            actual_score_a=1.0,
            session_id=uuid.uuid4(),
            time_factor_challenger=None,
        )

        # Standard Elo: 32 * (1 - 0.5) = 16
        assert change_a == 16


# ===========================================================================
# PART 4: Training mode time factor
# ===========================================================================


@pytest.fixture
async def training_db(async_engine):
    """Training test session with all mocks."""
    session_factory = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)

    async def _mock_award_tokens(db, user, amount, **kwargs):
        user.tokens += amount
        return amount

    _mock_hint_service = AsyncMock()
    _mock_hint_service.get_max_hint_level = AsyncMock(return_value=0)

    async def _mock_get_config(db, key):
        from app.core.default_config import DEFAULT_CONFIG

        configs = {
            "melo.training_global_coefficient": 0.5,
            "melo.training_melo_coefficient": 2.0,
        }
        if key in configs:
            return configs[key]
        return DEFAULT_CONFIG.get(key, {})

    from app.services import config_service as config_svc_module

    async with session_factory() as session:
        with (
            patch.object(training_svc_module, "User", _TestUser),
            patch.object(training_svc_module, "TopicCategory", _TestTopicCategory),
            patch.object(training_svc_module, "TrainingSession", _TestTrainingSession),
            patch.object(training_svc_module, "TrainingProblemRecord", _TestTrainingProblemRecord),
            patch.object(training_svc_module, "TokenTransaction", _TestTokenTransaction),
            patch.object(training_svc_module, "EloHistory", _TestEloHistory),
            patch.object(training_svc_module, "HintService", _mock_hint_service),
            patch.object(economy_svc_module, "award_tokens", _mock_award_tokens),
            patch.object(training_svc_module, "AchievementService") as mock_ach_cls,
            patch.object(config_svc_module.ConfigService, "get_config", _mock_get_config),
            patch.object(training_svc_module, "TimeFactorService") as mock_tf_cls,
        ):
            mock_tf_cls.compute_effective_time = staticmethod(TimeFactorService.compute_effective_time)
            mock_tf_cls.calculate_time_factor = staticmethod(TimeFactorService.calculate_time_factor)
            mock_tf_cls.calculate_expected_time = AsyncMock(return_value=1800.0)

            from app.services import melo_service as melo_svc_module

            with (
                patch.object(melo_svc_module, "UserTagElo", _TestUserTagElo),
                patch.object(melo_svc_module, "User", _TestUser),
            ):
                mock_ach_cls.check_overkill = staticmethod(lambda **kwargs: None)
                yield session


async def _setup_training_topic(db):
    """Create a test topic."""
    topic = _TestTopicCategory(
        name="Dynamic Programming",
        slug="dp",
        description="DP problems",
        cf_tags=["dp"],
        display_order=0,
    )
    db.add(topic)
    await db.flush()
    return topic


async def _setup_training_session(db, user, topic):
    """Create an active training session."""
    session = _TestTrainingSession(
        user_id=user.id,
        topic_id=topic.id,
        total_problems=10,
        problems_solved=0,
        streak_count=0,
        status="active",
    )
    db.add(session)
    await db.flush()
    return session


class TestTrainingTimeFactor:
    """Training mode: verify time factor on Global Elo and M-Elo."""

    @pytest.mark.asyncio
    async def test_fast_solve_elo_bonus(self, training_db):
        """Training - Fast solve increases Global Elo gain via time_factor."""
        db = training_db
        user = _make_test_user(elo=1000)
        db.add(user)
        topic = await _setup_training_topic(db)
        session = await _setup_training_session(db, user, topic)

        melo = _TestUserTagElo(
            user_id=user.id,
            tag="dp",
            elo=1000,
            total_submissions=0,
            first_ac_at=datetime.now(UTC),
        )
        db.add(melo)
        await db.flush()

        # With time factor (expected=1800, solve=600 -> factor=1.5)
        result_with_tf = await training_svc_module.TrainingService._calculate_training_elo(
            db,
            user,
            problem_rating=1500,
            session_id=session.id,
            topic_id=topic.id,
            solved=True,
            attempts=1,
            problem_id="100A",
            time_spent=600.0,
            cf_service=AsyncMock(),
        )
        elo_with_tf = result_with_tf["global_elo_change"]
        user.elo = 1000  # Reset

        # Without time factor (cf_service=None)
        result_no_tf = await training_svc_module.TrainingService._calculate_training_elo(
            db,
            user,
            problem_rating=1500,
            session_id=session.id,
            topic_id=topic.id,
            solved=True,
            attempts=1,
            problem_id="100A",
            time_spent=600.0,
            cf_service=None,
        )
        elo_no_tf = result_no_tf["global_elo_change"]

        assert elo_no_tf > 0, "AC should produce positive Global Elo change"
        assert elo_with_tf > elo_no_tf, f"Fast solve ({elo_with_tf}) should give more Elo than no TF ({elo_no_tf})"

    @pytest.mark.asyncio
    async def test_slow_solve_elo_reduction(self, training_db):
        """Training - Slow solve reduces Global Elo gain via time_factor."""
        db = training_db
        user = _make_test_user(elo=1000)
        db.add(user)
        topic = await _setup_training_topic(db)
        session = await _setup_training_session(db, user, topic)
        await db.flush()

        # Slow solve: expected=1800, effective=3600 -> factor=0.5
        result_slow = await training_svc_module.TrainingService._calculate_training_elo(
            db,
            user,
            problem_rating=1500,
            session_id=session.id,
            topic_id=topic.id,
            solved=True,
            attempts=1,
            problem_id="100A",
            time_spent=3600.0,
            cf_service=AsyncMock(),
        )
        elo_slow = result_slow["global_elo_change"]
        user.elo = 1000  # Reset

        # Without time factor
        result_no_tf = await training_svc_module.TrainingService._calculate_training_elo(
            db,
            user,
            problem_rating=1500,
            session_id=session.id,
            topic_id=topic.id,
            solved=True,
            attempts=1,
            problem_id="100A",
            time_spent=600.0,
            cf_service=None,
        )
        elo_no_tf = result_no_tf["global_elo_change"]

        assert elo_slow < elo_no_tf, f"Slow solve ({elo_slow}) should give less Elo than baseline ({elo_no_tf})"

    @pytest.mark.asyncio
    async def test_failure_no_time_factor(self, training_db):
        """Training - Failure (S=0): time_factor = 1.0, no effect."""
        db = training_db
        user = _make_test_user(elo=2000)
        db.add(user)
        topic = await _setup_training_topic(db)
        session = await _setup_training_session(db, user, topic)

        melo = _TestUserTagElo(
            user_id=user.id,
            tag="dp",
            elo=2000,
            total_submissions=0,
            first_ac_at=datetime.now(UTC),
        )
        db.add(melo)
        await db.flush()

        result_with_tf = await training_svc_module.TrainingService._calculate_training_elo(
            db,
            user,
            problem_rating=800,
            session_id=session.id,
            topic_id=topic.id,
            solved=False,
            attempts=3,
            problem_id="100A",
            time_spent=600.0,
            cf_service=AsyncMock(),
        )
        elo_with_tf = result_with_tf["global_elo_change"]

        user.elo = 2000
        result_no_tf = await training_svc_module.TrainingService._calculate_training_elo(
            db,
            user,
            problem_rating=800,
            session_id=session.id,
            topic_id=topic.id,
            solved=False,
            attempts=3,
            problem_id="100A",
        )
        elo_no_tf = result_no_tf["global_elo_change"]

        assert elo_with_tf == elo_no_tf, f"Failure Elo should be same: {elo_with_tf} vs {elo_no_tf}"

    @pytest.mark.asyncio
    async def test_hint_and_time_factor_stack(self, training_db):
        """Training - Hint level 2 (x0.50) + fast solve (x1.5) stack."""
        db = training_db
        user = _make_test_user(elo=1000)
        db.add(user)
        topic = await _setup_training_topic(db)
        session = await _setup_training_session(db, user, topic)
        await db.flush()

        # Baseline: no hint, no time factor
        from app.services import training_service as ts_mod

        with patch.object(ts_mod.HintService, "get_max_hint_level", AsyncMock(return_value=0)):
            result_baseline = await training_svc_module.TrainingService._calculate_training_elo(
                db,
                user,
                problem_rating=1500,
                session_id=session.id,
                topic_id=topic.id,
                solved=True,
                attempts=1,
                problem_id="100A",
            )
        elo_baseline = result_baseline["global_elo_change"]
        user.elo = 1000  # Reset

        # Hint level 2 + fast solve
        with patch.object(ts_mod.HintService, "get_max_hint_level", AsyncMock(return_value=2)):
            result_stacked = await training_svc_module.TrainingService._calculate_training_elo(
                db,
                user,
                problem_rating=1500,
                session_id=session.id,
                topic_id=topic.id,
                solved=True,
                attempts=1,
                problem_id="100A",
                time_spent=600.0,
                cf_service=AsyncMock(),
            )
        elo_stacked = result_stacked["global_elo_change"]

        # Expected: hint_attenuation first (round), then time factor (round)
        # hint_level=2 -> attenuation=0.5 -> round(baseline*0.5), then *1.5 -> round
        after_hint = round(elo_baseline * 0.50)
        expected = round(after_hint * 1.5)
        assert elo_stacked == expected, f"Stacked: {elo_stacked} vs expected {expected} (baseline={elo_baseline})"


# ===========================================================================
# PART 5: Contest mode time factor
# ===========================================================================


@pytest.fixture
async def contest_db(async_engine):
    """Contest test session with all mocks."""
    session_factory = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)

    async def _mock_award_tokens(db, user, amount, **kwargs):
        user.tokens += amount
        return amount

    async def _mock_get_config(db, key):
        from app.core.default_config import DEFAULT_CONFIG

        return DEFAULT_CONFIG.get("elo", {})

    async def _mock_get_submission_count(db, user_id):
        return 0

    async def _mock_get_max_hint_level(db, user_id, problem_id):
        return 0

    async def _mock_record_elo_history(db, **kwargs):
        pass

    from app.services import config_service as config_svc_module
    from app.services import contest_simulation_service as sim_svc_module
    from app.services import elo_service as elo_svc_module
    from app.services import hint_service as hint_svc_module
    from app.services import pp_service as pp_svc_module

    async with session_factory() as session:
        with (
            patch.object(contest_svc_module, "ContestSession", _TestContestSession),
            patch.object(contest_svc_module, "ContestProblemRecord", _TestContestProblemRecord),
            patch.object(contest_svc_module, "EloHistory", _TestEloHistory),
            patch.object(pp_svc_module.PPService, "record_pp", AsyncMock(return_value=None)),
            patch.object(
                elo_svc_module.EloService,
                "record_elo_history",
                _mock_record_elo_history,
            ),
            patch.object(economy_svc_module, "award_tokens", _mock_award_tokens),
            patch.object(config_svc_module.ConfigService, "get_config", _mock_get_config),
            patch.object(elo_svc_module.EloService, "get_submission_count", _mock_get_submission_count),
            patch.object(
                elo_svc_module.EloService,
                "apply_hint_attenuation",
                staticmethod(EloService.apply_hint_attenuation),
            ),
            patch.object(hint_svc_module.HintService, "get_max_hint_level", _mock_get_max_hint_level),
            patch.object(sim_svc_module.ContestSimulationService, "generate_bots", AsyncMock(return_value=[])),
            patch.object(sim_svc_module.ContestSimulationService, "stop_simulation", AsyncMock(return_value=False)),
            patch.object(sim_svc_module.ContestSimulationService, "start_simulation", AsyncMock(return_value=None)),
            patch.object(
                sim_svc_module.ContestSimulationService,
                "calculate_performance_rating",
                AsyncMock(return_value=1600),
            ),
            patch.object(
                sim_svc_module.ContestSimulationService,
                "build_leaderboard",
                AsyncMock(side_effect=Exception("no leaderboard in test")),
            ),
            patch.object(contest_svc_module, "TimeFactorService") as mock_tf_cls,
        ):
            mock_tf_cls.compute_effective_time = staticmethod(TimeFactorService.compute_effective_time)
            mock_tf_cls.calculate_time_factor = staticmethod(TimeFactorService.calculate_time_factor)
            mock_tf_cls.calculate_expected_time = AsyncMock(return_value=1800.0)

            yield session


async def _setup_contest_session(db, user, problems_solved=3, submissions=5):
    """Create a completed contest session with solved problems."""
    problems = [
        {"problem_id": "1000A", "contest_id": 1000, "index": "A", "name": "P1", "rating": 1200, "url": ""},
        {"problem_id": "1000B", "contest_id": 1000, "index": "B", "name": "P2", "rating": 1400, "url": ""},
        {"problem_id": "1000C", "contest_id": 1000, "index": "C", "name": "P3", "rating": 1600, "url": ""},
    ]
    session = _TestContestSession(
        user_id=user.id,
        contest_tier="beginner",
        problems=problems,
        total_problems=3,
        problems_solved=problems_solved,
        submissions=submissions,
        time_limit=90,
        started_at=datetime.now(UTC),
        status="active",
    )
    db.add(session)
    await db.flush()
    return session


async def _setup_contest_records(db, contest_id, user_id, solved=True, time_spent=600.0, attempts=1):
    """Create problem records for a contest session."""
    problems = [
        ("1000A", 1200),
        ("1000B", 1400),
        ("1000C", 1600),
    ]
    for pid, prating in problems:
        record = _TestContestProblemRecord(
            contest_id=contest_id,
            problem_id=pid,
            problem_rating=prating,
            solved=1 if solved else 0,
            attempts=attempts,
            time_spent=time_spent,
        )
        db.add(record)
    await db.flush()


class TestContestTimeFactor:
    """Contest mode: verify time factor on PR-based Elo settlement."""

    @pytest.mark.asyncio
    async def test_fast_solve_elo_bonus(self, contest_db):
        """Contest - Fast solves increase Elo gain via time_factor."""
        db = contest_db
        user = _make_test_user(elo=1200)
        db.add(user)
        contest_session = await _setup_contest_session(db, user)
        await _setup_contest_records(db, contest_session.id, user.id, time_spent=600.0, attempts=1)
        await db.flush()

        from app.services import hint_service as hint_svc_module

        with patch.object(hint_svc_module.HintService, "get_max_hint_level", AsyncMock(return_value=0)):
            elo_fast, _ = await contest_svc_module.ContestService._settle_with_pr(
                db=db,
                user=user,
                session=contest_session,
                contest_id=contest_session.id,
                cf_service=AsyncMock(),
            )

        user.elo = 1200  # Reset

        # Without time factor
        with patch.object(hint_svc_module.HintService, "get_max_hint_level", AsyncMock(return_value=0)):
            elo_no_tf, _ = await contest_svc_module.ContestService._settle_with_pr(
                db=db,
                user=user,
                session=contest_session,
                contest_id=contest_session.id,
                cf_service=None,
            )

        assert elo_no_tf > 0, "PR=1600 > user.elo=1200 should give positive change"
        assert elo_fast > elo_no_tf, f"Fast solve ({elo_fast}) should give more Elo than no TF ({elo_no_tf})"

    @pytest.mark.asyncio
    async def test_slow_solve_elo_reduction(self, contest_db):
        """Contest - Slow solves reduce Elo gain via time_factor."""
        db = contest_db
        user = _make_test_user(elo=1200)
        db.add(user)
        contest_session = await _setup_contest_session(db, user)
        await _setup_contest_records(db, contest_session.id, user.id, time_spent=3600.0, attempts=1)
        await db.flush()

        from app.services import hint_service as hint_svc_module

        with patch.object(hint_svc_module.HintService, "get_max_hint_level", AsyncMock(return_value=0)):
            elo_slow, _ = await contest_svc_module.ContestService._settle_with_pr(
                db=db,
                user=user,
                session=contest_session,
                contest_id=contest_session.id,
                cf_service=AsyncMock(),
            )

        user.elo = 1200  # Reset

        with patch.object(hint_svc_module.HintService, "get_max_hint_level", AsyncMock(return_value=0)):
            elo_no_tf, _ = await contest_svc_module.ContestService._settle_with_pr(
                db=db,
                user=user,
                session=contest_session,
                contest_id=contest_session.id,
                cf_service=None,
            )

        assert elo_slow < elo_no_tf, f"Slow solve ({elo_slow}) should give less Elo than no TF ({elo_no_tf})"

    @pytest.mark.asyncio
    async def test_hint_does_not_attenuate_when_time_factor_applied(self, contest_db):
        """Contest - Hints do NOT attenuate Elo; only time factor applies (per requirements 3.6.4)."""
        db = contest_db
        user = _make_test_user(elo=1200)
        db.add(user)
        contest_session = await _setup_contest_session(db, user)
        await _setup_contest_records(db, contest_session.id, user.id, time_spent=600.0, attempts=1)
        await db.flush()

        from app.services import hint_service as hint_svc_module

        # No hint, no time factor baseline
        with patch.object(hint_svc_module.HintService, "get_max_hint_level", AsyncMock(return_value=0)):
            elo_baseline, _ = await contest_svc_module.ContestService._settle_with_pr(
                db=db,
                user=user,
                session=contest_session,
                contest_id=contest_session.id,
                cf_service=None,
            )

        user.elo = 1200

        # Hint level 2 + fast solve (tf=1.5) -- hints should NOT attenuate in contest
        hint_map = {"1000A": 2, "1000B": 2, "1000C": 2}

        async def _hint_by_problem(db, user_id, problem_id):
            return hint_map.get(problem_id, 0)

        with patch.object(hint_svc_module.HintService, "get_max_hint_level", _hint_by_problem):
            elo_with_hint_and_tf, _ = await contest_svc_module.ContestService._settle_with_pr(
                db=db,
                user=user,
                session=contest_session,
                contest_id=contest_session.id,
                cf_service=AsyncMock(),
            )

        # Only time factor applies (no hint attenuation in contest)
        # baseline * 1.5 (time factor only)
        expected = round(elo_baseline * 1.5)
        assert elo_with_hint_and_tf == expected, (
            f"Should be baseline*1.5 (no hint attenuation): "
            f"{elo_with_hint_and_tf} vs {expected} (baseline={elo_baseline})"
        )

    @pytest.mark.asyncio
    async def test_negative_pr_not_affected(self, contest_db):
        """Contest - Negative PR-based Elo change is not affected by time factor."""
        db = contest_db
        user = _make_test_user(elo=2000)
        db.add(user)
        contest_session = await _setup_contest_session(db, user)
        await _setup_contest_records(db, contest_session.id, user.id, time_spent=600.0, attempts=1)
        await db.flush()

        from app.services import hint_service as hint_svc_module

        with patch.object(hint_svc_module.HintService, "get_max_hint_level", AsyncMock(return_value=0)):
            elo_with_tf, _ = await contest_svc_module.ContestService._settle_with_pr(
                db=db,
                user=user,
                session=contest_session,
                contest_id=contest_session.id,
                cf_service=AsyncMock(),
            )

        user.elo = 2000

        with patch.object(hint_svc_module.HintService, "get_max_hint_level", AsyncMock(return_value=0)):
            elo_no_tf, _ = await contest_svc_module.ContestService._settle_with_pr(
                db=db,
                user=user,
                session=contest_session,
                contest_id=contest_session.id,
                cf_service=None,
            )

        assert elo_with_tf < 0, "PR=1600 < user.elo=2000 should give negative change"
        assert elo_with_tf == elo_no_tf, f"Negative change should be same: {elo_with_tf} vs {elo_no_tf}"


# ===========================================================================
# PART 6: Reachability verification
# ===========================================================================


class TestReachability:
    """Verify that time_factor is reachable from user actions."""

    def test_pve_submit_calls_time_factor_service(self):
        """PvE submit_result imports and calls TimeFactorService."""
        import inspect

        source = inspect.getsource(pve_svc_module.PvEChallengeService.submit_result)
        assert "TimeFactorService" in source, "submit_result should reference TimeFactorService"
        assert "compute_effective_time" in source
        assert "calculate_time_factor" in source

    def test_challenge_settle_calls_time_factor_service(self):
        """Challenge _settle_challenge calls TimeFactorService."""
        import inspect

        from app.services import challenge_service as challenge_svc_module

        source = inspect.getsource(challenge_svc_module._settle_challenge)
        assert "TimeFactorService" in source
        assert "compute_effective_time" in source
        assert "time_factor_challenger" in source
        assert "time_factor_opponent" in source

    def test_training_elo_calls_time_factor_service(self):
        """Training _calculate_training_elo calls TimeFactorService."""
        import inspect

        source = inspect.getsource(training_svc_module.TrainingService._calculate_training_elo)
        assert "TimeFactorService" in source
        assert "compute_effective_time" in source
        assert "calculate_time_factor" in source

    def test_contest_settle_calls_time_factor_service(self):
        """Contest _settle_with_pr calls TimeFactorService."""
        import inspect

        source = inspect.getsource(contest_svc_module.ContestService._settle_with_pr)
        assert "TimeFactorService" in source
        assert "compute_effective_time" in source
        assert "calculate_time_factor" in source

    def test_pve_api_passes_cf_service(self):
        """PvE API submit endpoint passes cf_service to service."""
        import importlib

        with open(importlib.import_module("app.api.v1.pve_challenge").__file__) as f:
            source = f.read()
        assert "cf_service" in source

    def test_challenge_api_passes_cf_service(self):
        """Challenge API submit endpoint passes cf_service to service."""
        import importlib

        with open(importlib.import_module("app.api.v1.challenge").__file__) as f:
            source = f.read()
        assert "cf_service" in source

    def test_contest_api_passes_cf_service(self):
        """Contest API end endpoint passes cf_service to service."""
        import importlib

        with open(importlib.import_module("app.api.v1.contest").__file__) as f:
            source = f.read()
        assert "cf_service" in source
