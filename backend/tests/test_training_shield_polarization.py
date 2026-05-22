"""Tests for Task 16.2 (Learning Shield) and Task 16.3 (Weight Polarization).

Uses lightweight SQLite-compatible test models and mocks for external services.
Patches production model references in training_service with test-compatible
models so SQLAlchemy queries target the SQLite tables.

Test coverage:
- Shield: failure with shield active -> no Elo deduction
- Shield: abandon with shield active -> no Elo deduction
- Shield: AC with shield active -> normal Elo gain + shield deactivated
- Shield: AC then failure -> normal deduction (shield off)
- Shield: independent per-tag shields
- Polarization: Global Elo x0.5 on AC
- Polarization: M-Elo x2.0 on AC
- Polarization: Global Elo x0.5 on failure (deduction also attenuated)
- Polarization: M-Elo uses its own Elo for P(AC)
- Polarization: coefficients read from config
"""

import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import JSON, Boolean, DateTime, Float, Integer, String, UniqueConstraint, event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.services import config_service as config_svc_module
from app.services import economy_service as economy_svc_module
from app.services import elo_service as elo_svc_module
from app.services import training_service as training_svc_module
from app.services.time_factor_service import TimeFactorService
from app.services.training_service import TrainingService

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
    cf_handle_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    cf_verification_code: Mapped[str | None] = mapped_column(String(8), nullable=True)
    elo: Mapped[int] = mapped_column(Integer, default=1200, nullable=False)
    pp: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    daily_tokens_earned: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    daily_tokens_reset_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class _TestTopicCategory(_TestBase):
    __tablename__ = "topic_categories"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    cf_tags: Mapped[dict | list | None] = mapped_column(JSON, nullable=True)
    display_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class _TestTrainingSession(_TestBase):
    __tablename__ = "training_sessions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    topic_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    problems_solved: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_problems: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    streak_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class _TestTrainingProblemRecord(_TestBase):
    __tablename__ = "training_problem_records"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    topic_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    problem_id: Mapped[str] = mapped_column(String(50), nullable=False)
    problem_rating: Mapped[int] = mapped_column(Integer, default=1000, nullable=False)
    solved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    time_spent: Mapped[float | None] = mapped_column(Float, nullable=True)
    hints_used: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    solved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


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


class _TestEloHistory(_TestBase):
    __tablename__ = "elo_history"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    elo_before: Mapped[int] = mapped_column(Integer, nullable=False)
    elo_after: Mapped[int] = mapped_column(Integer, nullable=False)
    elo_change: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(String(50), nullable=False)
    time_factor: Mapped[float | None] = mapped_column(Float, nullable=True)
    reference_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class _TestUserTagElo(_TestBase):
    __tablename__ = "user_tag_elo"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    tag: Mapped[str] = mapped_column(String(100), nullable=False)
    elo: Mapped[int] = mapped_column(Integer, default=1200, nullable=False)
    total_submissions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    first_ac_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    __table_args__ = (UniqueConstraint("user_id", "tag", name="uq_user_tag_elo_user_tag"),)


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

    # Mock HintService so _calculate_training_elo doesn't query hint_purchases
    _mock_hint_service = AsyncMock()
    _mock_hint_service.get_max_hint_level = AsyncMock(return_value=0)

    # Default K factor config: use k_newbie=8 to match the previous hard-coded K=8
    # so existing test expectations remain valid without recalculating every assertion.
    _default_elo_config = {
        "k_newbie": 8,
        "k_veteran": 8,
        "k_newbie_threshold": 20,
        "k_veteran_threshold": 100,
    }

    # Track per-key overrides so individual tests can customise coefficients
    _config_overrides: dict[str, object] = {}

    async def _mock_get_config(db, key):
        if key in _config_overrides:
            return _config_overrides[key]
        if key == "elo":
            return _default_elo_config
        raise KeyError(key)

    async with session_factory() as session:
        with (
            patch.object(training_svc_module, "User", _TestUser),
            patch.object(training_svc_module, "TopicCategory", _TestTopicCategory),
            patch.object(training_svc_module, "TrainingSession", _TestTrainingSession),
            patch.object(training_svc_module, "TrainingProblemRecord", _TestTrainingProblemRecord),
            patch.object(training_svc_module, "TokenTransaction", _TestTokenTransaction),
            patch.object(training_svc_module, "EloHistory", _TestEloHistory),
            patch.object(training_svc_module, "HintService", _mock_hint_service),
            patch.object(training_svc_module.SubmissionTracker, "register_pending", AsyncMock()),
            patch.object(economy_svc_module, "award_tokens", _mock_award_tokens),
            patch.object(training_svc_module, "TimeFactorService") as mock_tf_cls,
            patch.object(config_svc_module.ConfigService, "get_config", _mock_get_config),
            patch.object(elo_svc_module.EloService, "get_submission_count", AsyncMock(return_value=0)),
        ):
            # Neutralize time factor: always return 1.0 so existing tests pass
            mock_tf_cls.calculate_expected_time = AsyncMock(return_value=999999.0)
            mock_tf_cls.compute_effective_time = staticmethod(TimeFactorService.compute_effective_time)
            mock_tf_cls.calculate_time_factor = staticmethod(lambda effective_time, expected_time, s_value: 1.0)
            # Also patch MEloService to use test models via the melo_svc module
            from app.services import melo_service as melo_svc_module

            with (
                patch.object(melo_svc_module, "UserTagElo", _TestUserTagElo),
                patch.object(melo_svc_module, "User", _TestUser),
            ):
                yield session


@pytest.fixture
def cf_mock():
    """Provide a mocked CFApiService."""
    mock = AsyncMock()
    mock.get_problemset_problems.return_value = {
        "problems": [
            {"contestId": 100, "index": "A", "name": "Easy DP", "rating": 800, "tags": ["dp"]},
            {"contestId": 200, "index": "B", "name": "Medium DP", "rating": 1200, "tags": ["dp"]},
            {"contestId": 300, "index": "C", "name": "Hard DP", "rating": 1600, "tags": ["dp"]},
            {"contestId": 400, "index": "D", "name": "Expert DP", "rating": 2000, "tags": ["dp"]},
            {"contestId": 500, "index": "E", "name": "Master DP", "rating": 2400, "tags": ["dp"]},
        ],
    }
    return mock


def _make_test_user(
    user_id: uuid.UUID | None = None,
    username: str = "testuser",
    elo: int = 1200,
    tokens: int = 0,
) -> _TestUser:
    """Create a test user instance (not yet added to session)."""
    return _TestUser(
        id=user_id or uuid.uuid4(),
        username=username,
        email=f"{username}@test.com",
        password_hash="$2b$12$fakehash",
        elo=elo,
        tokens=tokens,
    )


def _make_test_topic(
    topic_id: uuid.UUID | None = None,
    name: str = "Dynamic Programming",
    slug: str = "dp",
    cf_tags: list | None = None,
    display_order: int = 0,
) -> _TestTopicCategory:
    """Create a test topic instance."""
    return _TestTopicCategory(
        id=topic_id or uuid.uuid4(),
        name=name,
        slug=slug,
        description=f"Test topic: {name}",
        cf_tags=cf_tags or ["dp"],
        display_order=display_order,
    )


# Helper to set up a session with user + topic + active training session
async def _setup_training_session(db, user_elo=1200, cf_tags=None):
    """Create user, topic, and active training session, return (user, topic, session)."""
    user = _make_test_user(elo=user_elo)
    topic = _make_test_topic(cf_tags=cf_tags)
    db.add_all([user, topic])
    await db.flush()

    session = _TestTrainingSession(
        user_id=user.id,
        topic_id=topic.id,
        total_problems=5,
        status="active",
    )
    db.add(session)
    await db.flush()
    return user, topic, session


# ---------------------------------------------------------------------------
# Task 16.2: Learning Shield Tests
# ---------------------------------------------------------------------------


class TestLearningShield:
    """Tests for the learning shield mechanism (Task 16.2)."""

    @patch.object(training_svc_module, "PPService")
    async def test_shield_failure_no_deduction(self, mock_pp_cls, db, cf_mock):
        """Shield active + failure: Global Elo and M-Elo unchanged."""
        mock_pp_cls.record_pp = AsyncMock()
        mock_pp_cls.calculate_overkill_multiplier = MagicMock(return_value=1.0)

        user, topic, session = await _setup_training_session(db, user_elo=1200)

        # Submit failure
        result = await TrainingService.submit_problem(
            db=db,
            user=user,
            session_id=session.id,
            problem_id="300C",
            solved=False,
            attempts=3,
            time_spent=120.0,
            cf_service=cf_mock,
        )

        # Elo should not change -- shield is active
        assert result.elo_change is None

        await db.refresh(user)
        assert user.elo == 1200

    @patch.object(training_svc_module, "PPService")
    async def test_shield_abandon_no_deduction(self, mock_pp_cls, db, cf_mock):
        """Shield active + abandon: no Elo deduction."""
        mock_pp_cls.record_pp = AsyncMock()
        mock_pp_cls.calculate_overkill_multiplier = MagicMock(return_value=1.0)

        user, topic, session = await _setup_training_session(db, user_elo=1200)

        # Submit one problem (failure) first so there are submissions
        await TrainingService.submit_problem(
            db=db,
            user=user,
            session_id=session.id,
            problem_id="100A",
            solved=False,
            attempts=2,
            time_spent=60.0,
            cf_service=cf_mock,
        )

        # Now abandon
        result = await TrainingService.abandon_training(db, user, session.id)

        assert result.shield_active is True
        assert result.elo_change is None

        await db.refresh(user)
        assert user.elo == 1200

    @patch.object(training_svc_module, "PPService")
    async def test_shield_ac_normal_gain(self, mock_pp_cls, db, cf_mock):
        """Shield active + AC: normal Elo gain + shield deactivated."""
        mock_pp_cls.record_pp = AsyncMock()
        mock_pp_cls.calculate_overkill_multiplier = MagicMock(return_value=1.0)

        user, topic, session = await _setup_training_session(db, user_elo=1200)

        # AC a problem
        result = await TrainingService.submit_problem(
            db=db,
            user=user,
            session_id=session.id,
            problem_id="300C",
            solved=True,
            attempts=1,
            time_spent=120.0,
            cf_service=cf_mock,
        )

        assert result.solved is True
        assert result.elo_change is not None
        assert result.elo_change > 0

        await db.refresh(user)
        assert user.elo > 1200

        # Verify shield is deactivated by checking that a subsequent failure
        # DOES deduct Elo
        from app.services.melo_service import MEloService

        shield_active = await MEloService.is_shield_active(db, user.id, "dp")
        assert shield_active is False

    @patch.object(training_svc_module, "PPService")
    async def test_shield_ac_then_failure_deducts(self, mock_pp_cls, db, cf_mock):
        """After first AC (shield off), failure deducts Elo normally."""
        mock_pp_cls.record_pp = AsyncMock()
        mock_pp_cls.calculate_overkill_multiplier = MagicMock(return_value=1.0)

        user, topic, session = await _setup_training_session(db, user_elo=1500)

        # First: AC to deactivate shield
        await TrainingService.submit_problem(
            db=db,
            user=user,
            session_id=session.id,
            problem_id="300C",
            solved=True,
            attempts=1,
            time_spent=120.0,
            cf_service=cf_mock,
        )

        elo_after_ac = user.elo
        assert elo_after_ac > 1500

        # Second: failure -- should deduct Elo (shield off)
        result = await TrainingService.submit_problem(
            db=db,
            user=user,
            session_id=session.id,
            problem_id="200B",
            solved=False,
            attempts=3,
            time_spent=60.0,
            cf_service=cf_mock,
        )

        # With polarization, failure also reduces Elo (x0.5 coefficient)
        assert result.elo_change is not None
        assert result.elo_change < 0

        await db.refresh(user)
        assert user.elo < elo_after_ac

    @patch.object(training_svc_module, "PPService")
    async def test_shield_independent_per_tag(self, mock_pp_cls, db, cf_mock):
        """Shield for tag A does not affect tag B."""
        mock_pp_cls.record_pp = AsyncMock()
        mock_pp_cls.calculate_overkill_multiplier = MagicMock(return_value=1.0)

        # Create user with two topics: dp and greedy
        user = _make_test_user(elo=1200)
        dp_topic = _make_test_topic(name="DP", slug="dp", cf_tags=["dp"])
        greedy_topic = _make_test_topic(
            name="Greedy",
            slug="greedy_test",
            cf_tags=["greedy"],
            display_order=99,
        )
        db.add_all([user, dp_topic, greedy_topic])
        await db.flush()

        # AC a dp problem -> deactivates dp shield
        dp_session = _TestTrainingSession(
            user_id=user.id,
            topic_id=dp_topic.id,
            total_problems=5,
            status="active",
        )
        db.add(dp_session)
        await db.flush()

        await TrainingService.submit_problem(
            db=db,
            user=user,
            session_id=dp_session.id,
            problem_id="300C",
            solved=True,
            attempts=1,
            time_spent=120.0,
            cf_service=cf_mock,
        )

        # Now fail a greedy problem -- shield should still be active for greedy
        greedy_session = _TestTrainingSession(
            user_id=user.id,
            topic_id=greedy_topic.id,
            total_problems=5,
            status="active",
        )
        db.add(greedy_session)
        await db.flush()

        elo_before = user.elo

        result = await TrainingService.submit_problem(
            db=db,
            user=user,
            session_id=greedy_session.id,
            problem_id="100A",
            solved=False,
            attempts=2,
            time_spent=60.0,
            cf_service=cf_mock,
        )

        # Shield should protect against deduction for greedy tag
        assert result.elo_change is None

        await db.refresh(user)
        assert user.elo == elo_before

        # DP shield should be off
        from app.services.melo_service import MEloService

        dp_shield = await MEloService.is_shield_active(db, user.id, "dp")
        greedy_shield = await MEloService.is_shield_active(db, user.id, "greedy")
        assert dp_shield is False
        assert greedy_shield is True

    @patch.object(training_svc_module, "PPService")
    async def test_shield_abandon_zero_submissions_no_change(self, mock_pp_cls, db, cf_mock):
        """Abandon with 0 submissions: Elo unchanged regardless of shield."""
        mock_pp_cls.record_pp = AsyncMock()
        mock_pp_cls.calculate_overkill_multiplier = MagicMock(return_value=1.0)

        user, topic, session = await _setup_training_session(db, user_elo=1200)

        # Abandon without any submissions
        result = await TrainingService.abandon_training(db, user, session.id)

        assert result.elo_change is None
        assert result.shield_active is True

        await db.refresh(user)
        assert user.elo == 1200


# ---------------------------------------------------------------------------
# Task 16.3: Weight Polarization Tests
# ---------------------------------------------------------------------------


class TestWeightPolarization:
    """Tests for the weight polarization mechanism (Task 16.3)."""

    @patch.object(training_svc_module, "PPService")
    async def test_global_elo_half_on_ac(self, mock_pp_cls, db, cf_mock):
        """Global Elo gain is multiplied by 0.5 on AC."""
        mock_pp_cls.record_pp = AsyncMock()
        mock_pp_cls.calculate_overkill_multiplier = MagicMock(return_value=1.0)

        user, topic, session = await _setup_training_session(db, user_elo=1200)

        # AC a 1600 problem with user at 1200
        result = await TrainingService.submit_problem(
            db=db,
            user=user,
            session_id=session.id,
            problem_id="300C",
            solved=True,
            attempts=1,
            time_spent=120.0,
            cf_service=cf_mock,
        )

        # Calculate expected unattenuated Elo change:
        # K=8, expected = 1/(1+10^((1600-1200)/400)) = 1/(1+10^1) = 1/11 ≈ 0.0909
        # raw_change = 8 * (1.0 - 0.0909) = 8 * 0.9091 ≈ 7.27
        # global_change = round(7.27 * 0.5) = round(3.636) = 4
        assert result.elo_change is not None
        assert result.elo_change == 4

        await db.refresh(user)
        assert user.elo == 1204

    @patch.object(training_svc_module, "PPService")
    async def test_melo_double_on_ac(self, mock_pp_cls, db, cf_mock):
        """M-Elo gain is multiplied by 2.0 on AC."""
        mock_pp_cls.record_pp = AsyncMock()
        mock_pp_cls.calculate_overkill_multiplier = MagicMock(return_value=1.0)

        user, topic, session = await _setup_training_session(db, user_elo=1200)

        # AC a 1600 problem
        await TrainingService.submit_problem(
            db=db,
            user=user,
            session_id=session.id,
            problem_id="300C",
            solved=True,
            attempts=1,
            time_spent=120.0,
            cf_service=cf_mock,
        )

        # Check M-Elo for dp tag
        from app.services.melo_service import MEloService

        melo = await MEloService.get_or_create_melo(db, user.id, "dp")

        # M-Elo starts at 1200 (global elo inheritance)
        # expected = 1/(1+10^((1600-1200)/400)) = 1/11 ≈ 0.0909
        # raw_change = 8 * (1.0 - 0.0909) ≈ 7.27
        # melo_change = round(7.27 * 2.0) = round(14.545) = 14 or 15
        # Note: MEloService.update_melo also increments total_submissions
        assert melo.elo > 1200
        # M-Elo should have gained more than 2x the global change
        assert melo.elo >= 1214

    @patch.object(training_svc_module, "PPService")
    async def test_global_elo_half_deduction_on_failure(self, mock_pp_cls, db, cf_mock):
        """Global Elo deduction is also multiplied by 0.5 on failure."""
        mock_pp_cls.record_pp = AsyncMock()
        mock_pp_cls.calculate_overkill_multiplier = MagicMock(return_value=1.0)

        user, topic, session = await _setup_training_session(db, user_elo=1500)

        # First AC (1600 rated) to deactivate shield and raise Elo
        await TrainingService.submit_problem(
            db=db,
            user=user,
            session_id=session.id,
            problem_id="300C",
            solved=True,
            attempts=1,
            time_spent=120.0,
            cf_service=cf_mock,
        )

        assert user.elo > 1500

        # Now fail a problem -- should deduct
        result = await TrainingService.submit_problem(
            db=db,
            user=user,
            session_id=session.id,
            problem_id="200B",
            solved=False,
            attempts=3,
            time_spent=60.0,
            cf_service=cf_mock,
        )

        # Should have Elo deduction, attenuated by 0.5
        assert result.elo_change is not None
        assert result.elo_change < 0

    @patch.object(training_svc_module, "PPService")
    async def test_melo_uses_own_elo_for_expected(self, mock_pp_cls, db, cf_mock):
        """M-Elo P(AC) is calculated using the M-Elo value, not Global Elo."""
        mock_pp_cls.record_pp = AsyncMock()
        mock_pp_cls.calculate_overkill_multiplier = MagicMock(return_value=1.0)

        # User starts at 1200, then AC some problems to raise global elo
        # Then verify M-Elo diverges
        user, topic, session = await _setup_training_session(db, user_elo=1200)

        # First AC to set up M-Elo
        await TrainingService.submit_problem(
            db=db,
            user=user,
            session_id=session.id,
            problem_id="300C",
            solved=True,
            attempts=1,
            time_spent=120.0,
            cf_service=cf_mock,
        )

        # After first AC, global elo and M-Elo should differ
        from app.services.melo_service import MEloService

        melo = await MEloService.get_or_create_melo(db, user.id, "dp")

        # Global Elo gained 4 (from 1200 to 1204)
        # M-Elo gained ~14 (from 1200 to ~1214)
        assert melo.elo > user.elo, "M-Elo should be higher than Global Elo after polarization"

    @patch.object(training_svc_module, "PPService")
    async def test_coefficients_from_config(self, mock_pp_cls, db, cf_mock):
        """Coefficients are read from config_service."""
        mock_pp_cls.record_pp = AsyncMock()
        mock_pp_cls.calculate_overkill_multiplier = MagicMock(return_value=1.0)

        from app.services import config_service as config_svc_module

        # Patch ConfigService.get_config to return custom coefficients
        async def _mock_get_config(db, key):
            if key == "melo.training_global_coefficient":
                return 1.0  # No attenuation
            if key == "melo.training_melo_coefficient":
                return 3.0  # Triple
            if key == "elo":
                return {"k_newbie": 8, "k_veteran": 8, "k_newbie_threshold": 20, "k_veteran_threshold": 100}
            raise KeyError(key)

        with patch.object(config_svc_module.ConfigService, "get_config", _mock_get_config):
            user, topic, session = await _setup_training_session(db, user_elo=1200)

            result = await TrainingService.submit_problem(
                db=db,
                user=user,
                session_id=session.id,
                problem_id="300C",
                solved=True,
                attempts=1,
                time_spent=120.0,
                cf_service=cf_mock,
            )

            # With global_coeff=1.0:
            # raw_change = round(8 * (1 - 1/(1+10^1))) = round(8*0.9091) = round(7.27) = 7
            assert result.elo_change == 7

            await db.refresh(user)
            assert user.elo == 1207

            # M-Elo with coeff=3.0:
            from app.services.melo_service import MEloService

            melo = await MEloService.get_or_create_melo(db, user.id, "dp")
            # melo_change = round(7.27 * 3.0) = round(21.82) = 22
            assert melo.elo == 1222

    @patch.object(training_svc_module, "PPService")
    async def test_shield_and_polarization_together(self, mock_pp_cls, db, cf_mock):
        """Full flow: shield protects failure, then AC uses polarization."""
        mock_pp_cls.record_pp = AsyncMock()
        mock_pp_cls.calculate_overkill_multiplier = MagicMock(return_value=1.0)

        user, topic, session = await _setup_training_session(db, user_elo=1200)

        # 1. Fail a problem with shield active -- no Elo change
        r1 = await TrainingService.submit_problem(
            db=db,
            user=user,
            session_id=session.id,
            problem_id="200B",
            solved=False,
            attempts=3,
            time_spent=60.0,
            cf_service=cf_mock,
        )
        assert r1.elo_change is None
        await db.refresh(user)
        assert user.elo == 1200

        # 2. AC a problem -- shield deactivates, polarization applies
        r2 = await TrainingService.submit_problem(
            db=db,
            user=user,
            session_id=session.id,
            problem_id="300C",
            solved=True,
            attempts=1,
            time_spent=120.0,
            cf_service=cf_mock,
        )
        assert r2.elo_change is not None
        assert r2.elo_change > 0
        # With default coeff 0.5: global_change = round(7.27 * 0.5) = 4
        assert r2.elo_change == 4

        await db.refresh(user)
        assert user.elo == 1204

        # 3. Fail another problem -- shield off, normal deduction with polarization
        r3 = await TrainingService.submit_problem(
            db=db,
            user=user,
            session_id=session.id,
            problem_id="100A",
            solved=False,
            attempts=2,
            time_spent=30.0,
            cf_service=cf_mock,
        )
        # Should have a small deduction (attenuated by 0.5)
        assert r3.elo_change is not None
        assert r3.elo_change < 0

    @patch.object(training_svc_module, "PPService")
    async def test_no_tag_no_crash(self, mock_pp_cls, db, cf_mock):
        """Topic with no cf_tags should not crash -- just skip M-Elo."""
        mock_pp_cls.record_pp = AsyncMock()
        mock_pp_cls.calculate_overkill_multiplier = MagicMock(return_value=1.0)

        user, topic, session = await _setup_training_session(db, user_elo=1200, cf_tags=[])

        result = await TrainingService.submit_problem(
            db=db,
            user=user,
            session_id=session.id,
            problem_id="300C",
            solved=True,
            attempts=1,
            time_spent=120.0,
            cf_service=cf_mock,
        )

        # Should still work, just no M-Elo update
        assert result.solved is True
        assert result.elo_change is not None
        assert result.elo_change > 0
