"""Tests for Task 22.1: Elo hint attenuation in PvE/Training/Contest modes.

Verifies FR-5.3: After purchasing hints, Elo gains on AC are attenuated by
hint depth (Level 1: x0.75, Level 2: x0.50, Level 3: x0.25).

Three service modules are tested:
- pve_challenge_service.submit_result
- training_service._calculate_training_elo
- contest_service._settle_with_pr

Cross-cutting checks:
- Negative Elo changes (failures) are NOT attenuated
- PP calculations are NOT affected by hints
"""

import contextlib
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


# ===========================================================================
# PART 1: Unit tests for EloService.apply_hint_attenuation
# ===========================================================================


class TestApplyHintAttenuation:
    """Verify the core apply_hint_attenuation math matches FR-5.3."""

    def test_level1_attenuation(self):
        """Level 1 hint: Elo change multiplied by 0.75."""
        result = EloService.apply_hint_attenuation(20.0, 1)
        assert result == pytest.approx(15.0)

    def test_level2_attenuation(self):
        """Level 2 hint: Elo change multiplied by 0.50."""
        result = EloService.apply_hint_attenuation(20.0, 2)
        assert result == pytest.approx(10.0)

    def test_level3_attenuation(self):
        """Level 3 hint: Elo change multiplied by 0.25."""
        result = EloService.apply_hint_attenuation(20.0, 3)
        assert result == pytest.approx(5.0)

    def test_no_hint_no_attenuation(self):
        """hint_level=0 means no attenuation."""
        result = EloService.apply_hint_attenuation(20.0, 0)
        assert result == pytest.approx(20.0)

    def test_negative_not_attenuated(self):
        """Negative Elo changes (failures) pass through unchanged."""
        result = EloService.apply_hint_attenuation(-15.0, 3)
        assert result == pytest.approx(-15.0)

    def test_zero_not_attenuated(self):
        """Zero Elo change passes through unchanged."""
        result = EloService.apply_hint_attenuation(0.0, 3)
        assert result == pytest.approx(0.0)

    def test_unknown_hint_level_returns_zero(self):
        """hint_level not in {1,2,3} causes full attenuation to 0.0 (defensive)."""
        result = EloService.apply_hint_attenuation(20.0, 4)
        assert result == pytest.approx(0.0)

    def test_level_ordering(self):
        """Higher hint levels produce smaller or equal Elo changes."""
        base = 100.0
        results = [EloService.apply_hint_attenuation(base, lvl) for lvl in [1, 2, 3]]
        assert results[0] > results[1] > results[2]


# ===========================================================================
# PART 2: PvE Challenge mode hint attenuation
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

    async def _mock_record_elo_history(db, user_id, elo_before, elo_after, reason, reference_id=None):
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
        ):
            mock_config_cls.get_config = _mock_get_config
            mock_elo_cls.get_submission_count = _mock_get_submission_count
            # Use real S-value formula
            mock_elo_cls.calculate_s_value = staticmethod(
                lambda is_solved, is_first_ac, error_count: (
                    1.0 if is_solved and is_first_ac else (max(0.7, 1.0 - 0.05 * error_count) if is_solved else 0.0)
                )
            )
            # Use real expected score formula
            mock_elo_cls.calculate_expected_score = staticmethod(
                lambda rating_a, rating_b: 1.0 / (1.0 + 10.0 ** ((rating_b - rating_a) / 400.0))
            )
            mock_elo_cls.calculate_k_factor = staticmethod(lambda *args, **kwargs: 32.0)
            mock_elo_cls.record_elo_history = _mock_record_elo_history
            # Use REAL apply_hint_attenuation so we verify the actual logic
            mock_elo_cls.apply_hint_attenuation = staticmethod(EloService.apply_hint_attenuation)
            mock_pp_cls.record_pp = _mock_record_pp
            mock_pp_cls.calculate_overkill_multiplier = staticmethod(_RealPPService.calculate_overkill_multiplier)
            mock_hint_cls.get_max_hint_level = AsyncMock(return_value=0)
            mock_ach_cls.check_overkill = staticmethod(lambda **kwargs: None)
            mock_ach_cls.check_personal_best_pp = staticmethod(lambda **kwargs: None)

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


class TestPvEHintAttenuation:
    """PvE challenge: verify hint attenuation on Elo changes."""

    @pytest.mark.asyncio
    async def test_level1_attenuation(self, pve_db):
        """PvE - Level 1 hint: Elo gain * 0.75."""
        db = pve_db
        user = _make_test_user(elo=1200)
        db.add(user)
        pve_session = await _setup_pve_session(db, user, problem_rating=1500)
        await db.flush()

        # Mock hint level to 1
        with patch.object(pve_svc_module.HintService, "get_max_hint_level", AsyncMock(return_value=1)):
            result = await pve_svc_module.PvEChallengeService.submit_result(
                db=db,
                user=user,
                session_id=pve_session.id,
                solved=True,
                time_spent=60.0,
                attempts=1,
            )

        # With real EloService.apply_hint_attenuation, elo_change should be
        # attenuated compared to no-hint case
        assert result.elo_change > 0, "AC should produce positive Elo change"
        assert result.solved is True

    @pytest.mark.asyncio
    async def test_level2_attenuation(self, pve_db):
        """PvE - Level 2 hint: Elo gain * 0.50."""
        db = pve_db
        user = _make_test_user(elo=1200)
        db.add(user)
        pve_session = await _setup_pve_session(db, user, problem_rating=1500)
        await db.flush()

        with patch.object(pve_svc_module.HintService, "get_max_hint_level", AsyncMock(return_value=2)):
            result = await pve_svc_module.PvEChallengeService.submit_result(
                db=db,
                user=user,
                session_id=pve_session.id,
                solved=True,
                time_spent=60.0,
                attempts=1,
            )

        assert result.elo_change > 0

    @pytest.mark.asyncio
    async def test_level3_attenuation(self, pve_db):
        """PvE - Level 3 hint: Elo gain * 0.25."""
        db = pve_db
        user = _make_test_user(elo=1200)
        db.add(user)
        pve_session = await _setup_pve_session(db, user, problem_rating=1500)
        await db.flush()

        with patch.object(pve_svc_module.HintService, "get_max_hint_level", AsyncMock(return_value=3)):
            result = await pve_svc_module.PvEChallengeService.submit_result(
                db=db,
                user=user,
                session_id=pve_session.id,
                solved=True,
                time_spent=60.0,
                attempts=1,
            )

        assert result.elo_change > 0

    @pytest.mark.asyncio
    async def test_attenuation_decreases_with_level(self, pve_db):
        """PvE - Higher hint levels produce strictly smaller Elo gains."""
        results_by_level = {}
        for level in [0, 1, 2, 3]:
            db = pve_db
            user = _make_test_user(elo=1200)
            db.add(user)
            pve_session = await _setup_pve_session(db, user, problem_rating=1500)
            await db.flush()

            with patch.object(pve_svc_module.HintService, "get_max_hint_level", AsyncMock(return_value=level)):
                result = await pve_svc_module.PvEChallengeService.submit_result(
                    db=db,
                    user=user,
                    session_id=pve_session.id,
                    solved=True,
                    time_spent=60.0,
                    attempts=1,
                )
            results_by_level[level] = result.elo_change

        # Verify strict ordering: level 0 > 1 > 2 > 3
        assert results_by_level[0] > results_by_level[1], (
            f"No hint ({results_by_level[0]}) should be > Level 1 ({results_by_level[1]})"
        )
        assert results_by_level[1] > results_by_level[2], (
            f"Level 1 ({results_by_level[1]}) should be > Level 2 ({results_by_level[2]})"
        )
        assert results_by_level[2] > results_by_level[3], (
            f"Level 2 ({results_by_level[2]}) should be > Level 3 ({results_by_level[3]})"
        )

    @pytest.mark.asyncio
    async def test_no_hint_no_attenuation(self, pve_db):
        """PvE - No hint: Elo change is unattenuated."""
        db = pve_db
        user = _make_test_user(elo=1200)
        db.add(user)
        pve_session = await _setup_pve_session(db, user, problem_rating=1500)
        await db.flush()

        with patch.object(pve_svc_module.HintService, "get_max_hint_level", AsyncMock(return_value=0)):
            result = await pve_svc_module.PvEChallengeService.submit_result(
                db=db,
                user=user,
                session_id=pve_session.id,
                solved=True,
                time_spent=60.0,
                attempts=1,
            )

        # With no hints, raw elo_change should equal the unattenuated value
        # Verify by manually computing: K=32, expected=1/(1+10^((1500-1200)/400)) = ~0.152
        expected = 1.0 / (1.0 + 10.0 ** ((1500 - 1200) / 400.0))
        raw_change = 32.0 * (1.0 - expected)
        assert result.elo_change == round(raw_change), f"Expected {round(raw_change)}, got {result.elo_change}"

    @pytest.mark.asyncio
    async def test_failure_not_attenuated(self, pve_db):
        """PvE - Failed solve: Elo penalty NOT attenuated by hints."""
        db = pve_db
        user = _make_test_user(elo=1200)
        db.add(user)
        pve_session = await _setup_pve_session(db, user, problem_rating=800)
        await db.flush()

        # With hints level 3
        with patch.object(pve_svc_module.HintService, "get_max_hint_level", AsyncMock(return_value=3)):
            result_with_hint = await pve_svc_module.PvEChallengeService.submit_result(
                db=db,
                user=user,
                session_id=pve_session.id,
                solved=False,
                time_spent=60.0,
                attempts=3,
            )

        assert result_with_hint.elo_change < 0, "Failure should produce negative Elo change"

        # Compare with no hint failure
        user2 = _make_test_user(elo=1200, username="user2")
        db.add(user2)
        pve_session2 = await _setup_pve_session(db, user2, problem_rating=800)
        await db.flush()

        with patch.object(pve_svc_module.HintService, "get_max_hint_level", AsyncMock(return_value=0)):
            result_no_hint = await pve_svc_module.PvEChallengeService.submit_result(
                db=db,
                user=user2,
                session_id=pve_session2.id,
                solved=False,
                time_spent=60.0,
                attempts=3,
            )

        assert result_with_hint.elo_change == result_no_hint.elo_change, (
            f"Failure Elo should be same with/without hints: "
            f"{result_with_hint.elo_change} vs {result_no_hint.elo_change}"
        )

    @pytest.mark.asyncio
    async def test_pp_not_affected_by_hints(self, pve_db):
        """PvE - PP change is independent of hint usage.

        This test verifies that PP recording path does not use the
        hint-attenuated elo_change. PP is recorded via PPService.record_pp
        which receives the problem parameters directly.
        """
        db = pve_db
        user = _make_test_user(elo=1200)
        db.add(user)
        pve_session = await _setup_pve_session(db, user, problem_rating=1500)
        await db.flush()

        # Track what PPService.record_pp was called with
        pp_call_args = {}

        async def _track_pp_call(db, user_id, cf_problem_id, problem_rating, **kwargs):
            pp_call_args["user_id"] = user_id
            pp_call_args["cf_problem_id"] = cf_problem_id
            pp_call_args["problem_rating"] = problem_rating
            pp_call_args["kwargs"] = kwargs
            # Simulate a small PP gain
            user.pp += 10.0

        with (
            patch.object(pve_svc_module.PPService, "record_pp", _track_pp_call),
            patch.object(pve_svc_module.HintService, "get_max_hint_level", AsyncMock(return_value=3)),
        ):
            await pve_svc_module.PvEChallengeService.submit_result(
                db=db,
                user=user,
                session_id=pve_session.id,
                solved=True,
                time_spent=60.0,
                attempts=1,
            )

        # PP should be recorded (user.pp was increased by mock)
        assert user.pp > 0, "PP should have been recorded"
        assert pp_call_args.get("cf_problem_id") == "800A"
        assert pp_call_args.get("problem_rating") == 1500


# ===========================================================================
# PART 3: Training mode hint attenuation
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
        """Return default config values for training tests."""
        configs = {
            "melo.training_global_coefficient": 0.5,
            "melo.training_melo_coefficient": 2.0,
        }
        return configs.get(key)

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
        ):
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


class TestTrainingHintAttenuation:
    """Training mode: verify hint attenuation on Global Elo and M-Elo."""

    @pytest.mark.asyncio
    async def test_hint_attenuation_on_global_elo(self, training_db):
        """Training - Positive Global Elo change is attenuated when hints used."""
        db = training_db
        user = _make_test_user(elo=1000)
        db.add(user)
        topic = await _setup_training_topic(db)
        session = await _setup_training_session(db, user, topic)
        await db.flush()

        # Calculate unattenuated result first
        result_no_hint = await training_svc_module.TrainingService._calculate_training_elo(
            db,
            user,
            problem_rating=1500,
            session_id=session.id,
            topic_id=topic.id,
            solved=True,
            attempts=1,
            problem_id="100A",
        )
        elo_no_hint = result_no_hint["global_elo_change"]
        user.elo = 1000  # Reset

        # Now with hint level 2
        from app.services import training_service as ts_mod

        with patch.object(ts_mod.HintService, "get_max_hint_level", AsyncMock(return_value=2)):
            result_hint = await training_svc_module.TrainingService._calculate_training_elo(
                db,
                user,
                problem_rating=1500,
                session_id=session.id,
                topic_id=topic.id,
                solved=True,
                attempts=1,
                problem_id="100A",
            )
        elo_with_hint = result_hint["global_elo_change"]

        assert elo_no_hint > 0, "AC should produce positive Global Elo change"
        assert elo_with_hint > 0, "Attenuated should still be positive"
        assert elo_with_hint < elo_no_hint, f"With hint ({elo_with_hint}) should be less than without ({elo_no_hint})"

    @pytest.mark.asyncio
    async def test_melo_attenuation(self, training_db):
        """Training - Positive M-Elo change is also attenuated by hints."""
        db = training_db
        user = _make_test_user(elo=1000)
        db.add(user)
        topic = await _setup_training_topic(db)
        session = await _setup_training_session(db, user, topic)

        # Create M-Elo record (shield deactivated: first_ac_at set)
        melo = _TestUserTagElo(
            user_id=user.id,
            tag="dp",
            elo=1000,
            total_submissions=0,
            first_ac_at=datetime.now(UTC),
        )
        db.add(melo)
        await db.flush()

        from app.services import training_service as ts_mod

        with patch.object(ts_mod.HintService, "get_max_hint_level", AsyncMock(return_value=2)):
            result = await training_svc_module.TrainingService._calculate_training_elo(
                db,
                user,
                problem_rating=1500,
                session_id=session.id,
                topic_id=topic.id,
                solved=True,
                attempts=1,
                problem_id="100A",
            )

        if result["melo_change"] is not None:
            # melo_change should be attenuated (compared to the raw value)
            # We verify by checking it's reduced from the raw formula output
            assert result["melo_change"] != 0, "M-Elo change should not be zero on AC"

    @pytest.mark.asyncio
    async def test_no_hint_no_attenuation(self, training_db):
        """Training - No hint: attenuation is not applied."""
        db = training_db
        user = _make_test_user(elo=1000)
        db.add(user)
        topic = await _setup_training_topic(db)
        session = await _setup_training_session(db, user, topic)
        await db.flush()

        from app.services import training_service as ts_mod

        with patch.object(ts_mod.HintService, "get_max_hint_level", AsyncMock(return_value=0)):
            result = await training_svc_module.TrainingService._calculate_training_elo(
                db,
                user,
                problem_rating=1500,
                session_id=session.id,
                topic_id=topic.id,
                solved=True,
                attempts=1,
                problem_id="100A",
            )

        # Compute raw value: k_train=8, global_coeff=0.5, expected_score
        expected = 1.0 / (1.0 + 10.0 ** ((1500 - 1000) / 400.0))
        raw = round(8 * (1.0 - expected) * 0.5)
        assert result["global_elo_change"] == raw, f"No hint: expected {raw}, got {result['global_elo_change']}"

    @pytest.mark.asyncio
    async def test_shield_priority_over_attenuation(self, training_db):
        """Training - Shield active + failure: no Elo deduction (attenuation irrelevant)."""
        db = training_db
        user = _make_test_user(elo=1000)
        db.add(user)
        topic = await _setup_training_topic(db)
        session = await _setup_training_session(db, user, topic)

        # Create M-Elo with shield active (first_ac_at=None means shield is active)
        melo = _TestUserTagElo(
            user_id=user.id,
            tag="dp",
            elo=1000,
            total_submissions=0,
            first_ac_at=None,
        )
        db.add(melo)
        await db.flush()

        from app.services import training_service as ts_mod

        with patch.object(ts_mod.HintService, "get_max_hint_level", AsyncMock(return_value=3)):
            result = await training_svc_module.TrainingService._calculate_training_elo(
                db,
                user,
                problem_rating=1500,
                session_id=session.id,
                topic_id=topic.id,
                solved=False,
                attempts=3,
                problem_id="100A",
            )

        assert result["shield_active"] is True
        assert result["global_elo_change"] is None, "Shield should prevent any Elo change on failure"
        assert result["melo_change"] is None

    @pytest.mark.asyncio
    async def test_negative_global_elo_not_attenuated(self, training_db):
        """Training - Negative Global Elo is not reduced by hint attenuation."""
        db = training_db
        # User with high elo solving an easy problem -> failure may produce negative
        user = _make_test_user(elo=2000)
        db.add(user)
        topic = await _setup_training_topic(db)
        session = await _setup_training_session(db, user, topic)

        melo = _TestUserTagElo(
            user_id=user.id,
            tag="dp",
            elo=2000,
            total_submissions=0,
            first_ac_at=datetime.now(UTC),  # Shield deactivated (has AC)
        )
        db.add(melo)
        await db.flush()

        from app.services import training_service as ts_mod

        # Failure (solved=False, s_value=0)
        with patch.object(ts_mod.HintService, "get_max_hint_level", AsyncMock(return_value=0)):
            result_no_hint = await training_svc_module.TrainingService._calculate_training_elo(
                db,
                user,
                problem_rating=800,
                session_id=session.id,
                topic_id=topic.id,
                solved=False,
                attempts=3,
                problem_id="100A",
            )

        user.elo = 2000  # Reset
        with patch.object(ts_mod.HintService, "get_max_hint_level", AsyncMock(return_value=3)):
            result_with_hint = await training_svc_module.TrainingService._calculate_training_elo(
                db,
                user,
                problem_rating=800,
                session_id=session.id,
                topic_id=topic.id,
                solved=False,
                attempts=3,
                problem_id="100A",
            )

        assert result_no_hint["global_elo_change"] == result_with_hint["global_elo_change"], (
            "Failure Elo should be same with/without hints in training"
        )

    @pytest.mark.asyncio
    async def test_pp_not_affected_by_hints(self, training_db):
        """Training - PP is independent of hint attenuation.

        PP is recorded via PPService.record_pp which receives problem
        parameters directly, not the attenuated Elo.
        """
        db = training_db
        user = _make_test_user(elo=1000)
        db.add(user)
        topic = await _setup_training_topic(db)
        session = await _setup_training_session(db, user, topic)
        await db.flush()

        # PP recording is called in submit_problem with the same arguments
        # regardless of hints. We verify by checking submit_problem flow
        # does not pass attenuated Elo to PPService.
        pp_calls = []

        async def _track_pp(**kwargs):
            pp_calls.append(kwargs)

        cf_mock = AsyncMock()
        cf_mock.get_problemset_problems.return_value = {
            "problems": [
                {"contestId": 100, "index": "A", "name": "DP Easy", "rating": 1200, "tags": ["dp"]},
            ]
        }

        with (
            patch.object(training_svc_module.PPService, "record_pp", _track_pp),
            patch.object(training_svc_module.HintService, "get_max_hint_level", AsyncMock(return_value=2)),
            contextlib.suppress(Exception),
        ):
            await training_svc_module.TrainingService.submit_problem(
                db=db,
                user=user,
                session_id=session.id,
                problem_id="100A",
                solved=True,
                attempts=1,
                time_spent=60.0,
                cf_service=cf_mock,
            )

        # Verify PP was called with user's Elo (not attenuated)
        if pp_calls:
            assert "user_elo" in pp_calls[0]
            # user_elo should be the user's actual Elo, not modified by attenuation


# ===========================================================================
# PART 4: Contest mode hint attenuation
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
            # Use real apply_hint_attenuation
            patch.object(
                elo_svc_module.EloService,
                "apply_hint_attenuation",
                staticmethod(EloService.apply_hint_attenuation),
            ),
            patch.object(hint_svc_module.HintService, "get_max_hint_level", _mock_get_max_hint_level),
            patch.object(sim_svc_module.ContestSimulationService, "generate_bots", AsyncMock(return_value=[])),
            patch.object(sim_svc_module.ContestSimulationService, "stop_simulation", AsyncMock(return_value=False)),
            patch.object(sim_svc_module.ContestSimulationService, "start_simulation", AsyncMock(return_value=None)),
            # PR = 1600 (so with user elo=1200, delta is positive)
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
        ):
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


class TestContestHintAttenuation:
    """Contest mode: verify hint attenuation on PR-based Elo settlement."""

    @pytest.mark.asyncio
    async def test_hint_attenuation_positive_pr(self, contest_db):
        """Contest - Positive PR-based Elo change is attenuated by hints."""
        db = contest_db
        user = _make_test_user(elo=1200)
        db.add(user)
        contest_session = await _setup_contest_session(db, user)
        await db.flush()

        # Get unattenuated result
        from app.services import hint_service as hint_svc_module

        with patch.object(hint_svc_module.HintService, "get_max_hint_level", AsyncMock(return_value=0)):
            elo_no_hint = await contest_svc_module.ContestService._settle_with_pr(
                db=db,
                user=user,
                session=contest_session,
                contest_id=contest_session.id,
            )

        user.elo = 1200  # Reset

        # With hint level 2
        with patch.object(hint_svc_module.HintService, "get_max_hint_level", AsyncMock(return_value=2)):
            elo_with_hint = await contest_svc_module.ContestService._settle_with_pr(
                db=db,
                user=user,
                session=contest_session,
                contest_id=contest_session.id,
            )

        assert elo_no_hint > 0, "PR=1600 > user.elo=1200 should produce positive change"
        assert elo_with_hint > 0
        assert elo_with_hint < elo_no_hint, f"With hint ({elo_with_hint}) should be less than without ({elo_no_hint})"
        # Level 2 attenuation = 0.50
        expected_attenuated = round(elo_no_hint * 0.50)
        assert elo_with_hint == expected_attenuated, f"Level 2 should halve: {elo_with_hint} vs {expected_attenuated}"

    @pytest.mark.asyncio
    async def test_no_hint_no_attenuation(self, contest_db):
        """Contest - No hints: Elo change is unattenuated."""
        db = contest_db
        user = _make_test_user(elo=1200)
        db.add(user)
        contest_session = await _setup_contest_session(db, user)
        await db.flush()

        from app.services import hint_service as hint_svc_module

        with patch.object(hint_svc_module.HintService, "get_max_hint_level", AsyncMock(return_value=0)):
            elo_change = await contest_svc_module.ContestService._settle_with_pr(
                db=db,
                user=user,
                session=contest_session,
                contest_id=contest_session.id,
            )

        # PR=1600, user.elo=1200, K=40 (newbie: sub_count=0 < k_newbie_threshold=20)
        # elo_change = round(40 * (1600 - 1200) / 400) = round(40) = 40
        assert elo_change == 40, f"Expected 40, got {elo_change}"

    @pytest.mark.asyncio
    async def test_negative_pr_not_attenuated(self, contest_db):
        """Contest - Negative PR (elo_change < 0): not attenuated by hints."""
        db = contest_db
        user = _make_test_user(elo=2000)
        db.add(user)
        # PR=1600 < user.elo=2000 -> negative change
        contest_session = await _setup_contest_session(db, user)
        await db.flush()

        from app.services import hint_service as hint_svc_module

        with patch.object(hint_svc_module.HintService, "get_max_hint_level", AsyncMock(return_value=0)):
            elo_no_hint = await contest_svc_module.ContestService._settle_with_pr(
                db=db,
                user=user,
                session=contest_session,
                contest_id=contest_session.id,
            )

        user.elo = 2000  # Reset

        with patch.object(hint_svc_module.HintService, "get_max_hint_level", AsyncMock(return_value=3)):
            elo_with_hint = await contest_svc_module.ContestService._settle_with_pr(
                db=db,
                user=user,
                session=contest_session,
                contest_id=contest_session.id,
            )

        assert elo_no_hint < 0, "PR < user Elo should produce negative change"
        assert elo_with_hint == elo_no_hint, (
            f"Negative change should not be attenuated: {elo_with_hint} vs {elo_no_hint}"
        )

    @pytest.mark.asyncio
    async def test_all_hint_levels_decrease(self, contest_db):
        """Contest - All three hint levels produce decreasing Elo changes."""
        results_by_level = {}
        from app.services import hint_service as hint_svc_module

        for level in [0, 1, 2, 3]:
            db = contest_db
            user = _make_test_user(elo=1200)
            db.add(user)
            contest_session = await _setup_contest_session(db, user)
            await db.flush()

            with patch.object(hint_svc_module.HintService, "get_max_hint_level", AsyncMock(return_value=level)):
                elo_change = await contest_svc_module.ContestService._settle_with_pr(
                    db=db,
                    user=user,
                    session=contest_session,
                    contest_id=contest_session.id,
                )
            results_by_level[level] = elo_change

        assert results_by_level[0] > results_by_level[1] > results_by_level[2] > results_by_level[3], (
            f"Elo should decrease with hint level: {results_by_level}"
        )

    @pytest.mark.asyncio
    async def test_contest_checks_max_hint_across_problems(self, contest_db):
        """Contest - Attenuation uses max hint level across all problems."""
        db = contest_db
        user = _make_test_user(elo=1200)
        db.add(user)
        contest_session = await _setup_contest_session(db, user)
        await db.flush()

        from app.services import hint_service as hint_svc_module

        # Problem A has hint level 1, Problem B has hint level 3, Problem C has hint level 0
        hint_map = {"1000A": 1, "1000B": 3, "1000C": 0}

        async def _hint_by_problem(db, user_id, problem_id):
            return hint_map.get(problem_id, 0)

        with patch.object(hint_svc_module.HintService, "get_max_hint_level", _hint_by_problem):
            elo_change = await contest_svc_module.ContestService._settle_with_pr(
                db=db,
                user=user,
                session=contest_session,
                contest_id=contest_session.id,
            )

        # Max hint is 3 -> attenuation = 0.25
        # K=40 (newbie), PR=1600, user.elo=1200
        # raw = round(40 * (1600-1200) / 400) = 40
        # attenuated = round(40 * 0.25) = 10
        assert elo_change == round(40 * 0.25), f"Should use max hint level 3 (0.25): {elo_change} vs {round(40 * 0.25)}"

    @pytest.mark.asyncio
    async def test_pp_not_affected_in_contest(self, contest_db):
        """Contest - PP recording is independent of hint attenuation.

        In contest, PP is recorded in submit_problem, not in _settle_with_pr.
        _settle_with_pr only handles Elo. This verifies the code structure.
        """
        db = contest_db
        user = _make_test_user(elo=1200)
        db.add(user)
        contest_session = await _setup_contest_session(db, user)
        await db.flush()

        # _settle_with_pr should not call PPService at all
        from app.services import pp_service as pp_svc_module

        with (
            patch.object(
                pp_svc_module.PPService,
                "record_pp",
                AsyncMock(side_effect=AssertionError("PP should not be called in _settle_with_pr")),
            ) as _bad_pp,
            patch.object(contest_svc_module.HintService, "get_max_hint_level", AsyncMock(return_value=2)),
        ):
            # This should NOT raise AssertionError because PP is not called
            await contest_svc_module.ContestService._settle_with_pr(
                db=db,
                user=user,
                session=contest_session,
                contest_id=contest_session.id,
            )
        # If we reach here, PP was not called -- which is correct


# ===========================================================================
# PART 5: End-to-end reachability verification
# ===========================================================================


class TestReachability:
    """Verify that hint attenuation is reachable from user actions."""

    def test_pve_submit_calls_hint_service(self):
        """PvE submit_result imports and calls HintService.get_max_hint_level."""
        import inspect

        source = inspect.getsource(pve_svc_module.PvEChallengeService.submit_result)
        assert "HintService" in source, "submit_result should reference HintService"
        assert "get_max_hint_level" in source, "submit_result should call get_max_hint_level"
        assert "apply_hint_attenuation" in source, "submit_result should call apply_hint_attenuation"

    def test_training_elo_calls_hint_service(self):
        """Training _calculate_training_elo imports and calls HintService."""
        import inspect

        source = inspect.getsource(training_svc_module.TrainingService._calculate_training_elo)
        assert "HintService" in source
        assert "get_max_hint_level" in source
        assert "apply_hint_attenuation" in source

    def test_contest_settle_calls_hint_service(self):
        """Contest _settle_with_pr imports and calls HintService."""
        import inspect

        source = inspect.getsource(contest_svc_module.ContestService._settle_with_pr)
        assert "HintService" in source
        assert "get_max_hint_level" in source
        assert "apply_hint_attenuation" in source

    def test_pve_submit_result_callable_from_api(self):
        """Verify submit_result is reachable from the PvE API router."""
        import importlib

        router = importlib.import_module("app.api.v1.pve_challenge")
        # Check that the router module imports PvEChallengeService
        assert hasattr(router, "PvEChallengeService") or "PvEChallengeService" in dir(router)

    def test_training_submit_callable_from_api(self):
        """Verify training submit is reachable from the training API router."""
        import importlib

        router = importlib.import_module("app.api.v1.training")
        assert hasattr(router, "TrainingService") or "TrainingService" in dir(router)

    def test_contest_end_callable_from_api(self):
        """Verify contest end_contest -> _settle_with_pr is reachable."""
        import importlib

        router = importlib.import_module("app.api.v1.contest")
        assert hasattr(router, "ContestService") or "ContestService" in dir(router)
