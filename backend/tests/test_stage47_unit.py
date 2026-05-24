"""Stage 47 unit tests — _compute_medal_info, protection period, skip_problem, login_time.

Tests cover edge cases, boundary conditions, and cross-cutting consistency.
Uses the same SQLite-compatible test model approach as test_training.py.
"""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import JSON, Boolean, DateTime, Float, Integer, String, event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core.exceptions import BadRequestException, ForbiddenException, NotFoundException
from app.services import config_service as config_svc_module
from app.services import economy_service as economy_svc_module
from app.services import elo_service as elo_svc_module
from app.services import training_service as training_svc_module
from app.services.training_service import TrainingService, _compute_medal_info

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


# ---------------------------------------------------------------------------
# Fake MElo record for mocking
# ---------------------------------------------------------------------------


class _FakeMEloRecord:
    def __init__(self, elo=1200, tag="dp", first_ac_at=None):
        self.elo = elo
        self.tag = tag
        self.first_ac_at = first_ac_at
        self.total_submissions = 0


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
        user.tokens += amount
        return amount

    _mock_melo_service = AsyncMock()
    _mock_melo_service.is_shield_active = AsyncMock(return_value=False)
    _mock_melo_service.get_or_create_melo = AsyncMock(
        return_value=_FakeMEloRecord(elo=1500, tag="dp"),
    )
    _mock_melo_service.update_melo = AsyncMock(
        return_value=_FakeMEloRecord(elo=1495, tag="dp"),
    )
    _mock_melo_service.get_all_melos = AsyncMock(
        return_value=[_FakeMEloRecord(elo=1500, tag="dp")],
    )
    _mock_melo_service.batch_update_melo_for_problem = AsyncMock(return_value={"dp": 0})

    _mock_hint_service = AsyncMock()
    _mock_hint_service.get_max_hint_level = AsyncMock(return_value=0)

    _default_elo_config = {
        "k_newbie": 8,
        "k_veteran": 8,
        "k_newbie_threshold": 20,
        "k_veteran_threshold": 100,
    }

    async def _mock_get_config(db, key):
        if key == "elo":
            return _default_elo_config
        if key == "melo.training_global_coefficient":
            return 0.5
        if key == "melo.training_melo_coefficient":
            return 2.0
        raise KeyError(key)

    async with session_factory() as session:
        TrainingService._problems_cache.clear()

        with (
            patch.object(training_svc_module, "User", _TestUser),
            patch.object(training_svc_module, "TopicCategory", _TestTopicCategory),
            patch.object(training_svc_module, "TrainingSession", _TestTrainingSession),
            patch.object(training_svc_module, "TrainingProblemRecord", _TestTrainingProblemRecord),
            patch.object(training_svc_module, "TokenTransaction", _TestTokenTransaction),
            patch.object(training_svc_module, "EloHistory", _TestEloHistory),
            patch.object(training_svc_module, "MEloService", _mock_melo_service),
            patch.object(training_svc_module, "HintService", _mock_hint_service),
            patch.object(training_svc_module.SubmissionTracker, "register_pending", AsyncMock()),
            patch.object(economy_svc_module, "award_tokens", _mock_award_tokens),
            patch.object(config_svc_module.ConfigService, "get_config", _mock_get_config),
            patch.object(elo_svc_module.EloService, "get_submission_count", AsyncMock(return_value=0)),
        ):
            yield session


def _make_test_user(user_id=None, username="testuser", elo=1500, tokens=0):
    return _TestUser(
        id=user_id or uuid.uuid4(),
        username=username,
        email=f"{username}@test.com",
        password_hash="$2b$12$fakehash",
        elo=elo,
        tokens=tokens,
    )


def _make_test_topic(topic_id=None, slug="dp", cf_tags=None):
    return _TestTopicCategory(
        id=topic_id or uuid.uuid4(),
        name=f"Test {slug}",
        slug=slug,
        description=f"Test topic: {slug}",
        cf_tags=cf_tags or ["dp"],
        display_order=0,
    )


def _make_test_session(user_id, topic_id, started_at=None, status="active"):
    return _TestTrainingSession(
        id=uuid.uuid4(),
        user_id=user_id,
        topic_id=topic_id,
        status=status,
        started_at=started_at,
        problems_solved=0,
        total_problems=10,
        streak_count=0,
    )


# ===========================================================================
# TEST SUITES
# ===========================================================================


# ---------------------------------------------------------------------------
# _compute_medal_info pure function tests
# ---------------------------------------------------------------------------


class TestComputeMedalInfo:
    """Test _compute_medal_info at all medal thresholds and edge cases."""

    @pytest.mark.parametrize(
        "melo,expected_level,expected_type,expected_current,expected_next",
        [
            # Unranked (below 1200)
            (0, "unranked", None, None, 1200),
            (500, "unranked", None, None, 1200),
            (1199, "unranked", None, None, 1200),
            # Provincial bronze (1200-1399)
            (1200, "provincial", "bronze", 1200, 1400),
            (1300, "provincial", "bronze", 1200, 1400),
            (1399, "provincial", "bronze", 1200, 1400),
            # Provincial silver (1400-1599)
            (1400, "provincial", "silver", 1400, 1600),
            (1500, "provincial", "silver", 1400, 1600),
            (1599, "provincial", "silver", 1400, 1600),
            # Provincial gold (1600-2199 per D-31)
            (1600, "provincial", "gold", 1600, 2200),
            (1800, "provincial", "gold", 1600, 2200),
            (2199, "provincial", "gold", 1600, 2200),
            # Regional gold (2200-2599 per D-31)
            (2200, "regional", "gold", 2200, 2600),
            (2400, "regional", "gold", 2200, 2600),
            (2599, "regional", "gold", 2200, 2600),
            # EC Final gold (2600-2799)
            (2600, "ec_final", "gold", 2600, 2800),
            (2700, "ec_final", "gold", 2600, 2800),
            (2799, "ec_final", "gold", 2600, 2800),
            # World Finals gold (2800+)
            (2800, "world_finals", "gold", 2800, None),
            (3000, "world_finals", "gold", 2800, None),
            (5000, "world_finals", "gold", 2800, None),
        ],
    )
    def test_medal_thresholds(self, melo, expected_level, expected_type, expected_current, expected_next):
        medal_info, current_threshold, next_threshold = _compute_medal_info(melo)
        assert medal_info.level == expected_level
        assert medal_info.type == expected_type
        assert current_threshold == expected_current
        assert next_threshold == expected_next

    def test_melo_none_returns_unranked(self):
        medal_info, current_threshold, next_threshold = _compute_medal_info(None)
        assert medal_info.level == "unranked"
        assert medal_info.type is None
        assert current_threshold is None
        assert next_threshold == 1200

    def test_negative_melo(self):
        medal_info, current_threshold, next_threshold = _compute_medal_info(-100)
        assert medal_info.level == "unranked"
        assert medal_info.type is None
        assert current_threshold is None
        assert next_threshold == 1200

    def test_float_melo_truncates_to_int(self):
        # 1199.9 -> int(1199.9) = 1199 -> unranked
        medal_info, _, _ = _compute_medal_info(1199.9)
        assert medal_info.level == "unranked"

        # 1200.1 -> int(1200.1) = 1200 -> provincial bronze
        medal_info, _, _ = _compute_medal_info(1200.1)
        assert medal_info.level == "provincial"
        assert medal_info.type == "bronze"

    def test_very_high_melo(self):
        medal_info, current_threshold, next_threshold = _compute_medal_info(10000)
        assert medal_info.level == "world_finals"
        assert medal_info.type == "gold"
        assert current_threshold == 2800
        assert next_threshold is None


class TestMedalMapConsistency:
    """Verify _compute_medal_info is consistent with MedalService._rating_to_medal."""

    def test_consistency_with_medal_service(self):
        from app.services.medal_service import _FLAT_MEDAL_MAP, MedalService

        for threshold, level, medal_type in _FLAT_MEDAL_MAP:
            medal_info, current, next_t = _compute_medal_info(threshold)
            direct_medal = MedalService._rating_to_medal(threshold)
            assert medal_info.level == direct_medal["level"], f"Level mismatch at {threshold}"
            assert medal_info.type == direct_medal["type"], f"Type mismatch at {threshold}"
            assert current == threshold

    def test_backend_matches_frontend_flat_map(self):
        from app.services.medal_service import _FLAT_MEDAL_MAP

        frontend_map = [
            (2800, "world_finals", "gold"),
            (2600, "ec_final", "gold"),
            (2200, "regional", "gold"),
            (1600, "provincial", "gold"),
            (1400, "provincial", "silver"),
            (1200, "provincial", "bronze"),
        ]

        assert len(_FLAT_MEDAL_MAP) == len(frontend_map)
        for i, (be, fe) in enumerate(zip(_FLAT_MEDAL_MAP, frontend_map, strict=False)):
            assert be[0] == fe[0], f"Threshold mismatch at index {i}"
            assert be[1] == fe[1], f"Level mismatch at index {i}"
            assert be[2] == fe[2], f"Type mismatch at index {i}"

    def test_d31_highest_gold_priority(self):
        """D-31: 2200 should be regional gold, NOT provincial something."""
        medal_info, _, _ = _compute_medal_info(2200)
        assert medal_info.level == "regional"
        assert medal_info.type == "gold"

        medal_info, _, _ = _compute_medal_info(2199)
        assert medal_info.level == "provincial"
        assert medal_info.type == "gold"


# ---------------------------------------------------------------------------
# Protection period + abandon tests (using real SQLite db)
# ---------------------------------------------------------------------------


class TestAbandonProtectionPeriod:
    """Test abandon_training with protection period edge cases."""

    @pytest.mark.asyncio
    async def test_abandon_within_protection_no_elo_change(self, db):
        """Abandon within 300s should not deduct any Elo."""
        user = _make_test_user(elo=1500)
        topic = _make_test_topic()
        db.add(user)
        db.add(topic)
        await db.flush()

        # Session started 100s ago
        session = _make_test_session(
            user_id=user.id,
            topic_id=topic.id,
            started_at=datetime.now(UTC) - timedelta(seconds=100),
        )
        db.add(session)
        await db.flush()

        result = await TrainingService.abandon_training(db, user, session.id)
        assert result.elo_change is None
        assert result.status == "abandoned"

    @pytest.mark.asyncio
    async def test_abandon_just_under_300s(self, db):
        """Abandon at 299.5s -- should still be within protection."""
        user = _make_test_user(elo=1500)
        topic = _make_test_topic()
        db.add(user)
        db.add(topic)
        await db.flush()

        session = _make_test_session(
            user_id=user.id,
            topic_id=topic.id,
            started_at=datetime.now(UTC) - timedelta(seconds=299, milliseconds=500),
        )
        db.add(session)
        await db.flush()

        result = await TrainingService.abandon_training(db, user, session.id)
        assert result.elo_change is None

    @pytest.mark.asyncio
    async def test_abandon_after_protection_0_subs_deducts_5_melo(self, db):
        """Abandon after protection with 0 submissions should deduct 5 M-Elo."""
        user = _make_test_user(elo=1500)
        topic = _make_test_topic()
        db.add(user)
        db.add(topic)
        await db.flush()

        # Session started 10 min ago (well past protection)
        session = _make_test_session(
            user_id=user.id,
            topic_id=topic.id,
            started_at=datetime.now(UTC) - timedelta(seconds=600),
        )
        db.add(session)
        await db.flush()

        result = await TrainingService.abandon_training(db, user, session.id)
        assert result.elo_change == -5

    @pytest.mark.asyncio
    async def test_abandon_no_started_at_treated_as_protection(self, db):
        """Session with started_at=None should be treated as within protection."""
        user = _make_test_user(elo=1500)
        topic = _make_test_topic()
        db.add(user)
        db.add(topic)
        await db.flush()

        session = _make_test_session(
            user_id=user.id,
            topic_id=topic.id,
            started_at=None,
        )
        db.add(session)
        await db.flush()

        result = await TrainingService.abandon_training(db, user, session.id)
        assert result.elo_change is None

    @pytest.mark.asyncio
    async def test_abandon_session_not_active_raises(self, db):
        """Abandoning a non-active session should raise BadRequestException."""
        user = _make_test_user(elo=1500)
        topic = _make_test_topic()
        db.add(user)
        db.add(topic)
        await db.flush()

        session = _make_test_session(
            user_id=user.id,
            topic_id=topic.id,
            status="completed",
        )
        db.add(session)
        await db.flush()

        with pytest.raises(BadRequestException, match="not active"):
            await TrainingService.abandon_training(db, user, session.id)

    @pytest.mark.asyncio
    async def test_abandon_wrong_user_raises(self, db):
        """Abandoning another user's session should raise ForbiddenException."""
        user1 = _make_test_user(username="user1")
        user2 = _make_test_user(username="user2")
        topic = _make_test_topic()
        db.add_all([user1, user2, topic])
        await db.flush()

        session = _make_test_session(
            user_id=user1.id,
            topic_id=topic.id,
        )
        db.add(session)
        await db.flush()

        with pytest.raises(ForbiddenException, match="Not your"):
            await TrainingService.abandon_training(db, user2, session.id)

    @pytest.mark.asyncio
    async def test_abandon_nonexistent_session_raises(self, db):
        """Abandoning a non-existent session should raise NotFoundException."""
        user = _make_test_user()
        db.add(user)
        await db.flush()

        with pytest.raises(NotFoundException):
            await TrainingService.abandon_training(db, user, uuid.uuid4())


# ---------------------------------------------------------------------------
# skip_problem tests
# ---------------------------------------------------------------------------


class TestSkipProblem:
    """Test skip_problem endpoint logic."""

    @pytest.mark.asyncio
    async def test_skip_within_protection_no_penalty(self, db):
        """Skip within protection period: no penalty."""
        user = _make_test_user(elo=1500)
        topic = _make_test_topic()
        db.add(user)
        db.add(topic)
        await db.flush()

        session = _make_test_session(
            user_id=user.id,
            topic_id=topic.id,
            started_at=datetime.now(UTC) - timedelta(seconds=100),
        )
        db.add(session)
        await db.flush()

        result = await TrainingService.skip_problem(db, user, session.id, "1234A")
        assert result.elo_change is None
        assert result.new_melo is not None

    @pytest.mark.asyncio
    async def test_skip_after_protection_deducts_5_melo(self, db):
        """Skip after protection period: deducts 5 M-Elo.

        Note: MEloService.update_melo is mocked, so we verify elo_change==-5.
        The actual M-Elo value comes from the mock.
        """
        user = _make_test_user(elo=1500)
        topic = _make_test_topic()
        db.add(user)
        db.add(topic)
        await db.flush()

        session = _make_test_session(
            user_id=user.id,
            topic_id=topic.id,
            started_at=datetime.now(UTC) - timedelta(seconds=400),
        )
        db.add(session)
        await db.flush()

        # The mock MEloService.update_melo is already patched in the db fixture.
        # After update_melo, skip_problem calls db.refresh(melo_record).
        # Since melo_record is a mock (_FakeMEloRecord), db.refresh fails.
        # We need to patch the MEloService.get_or_create_melo to return a real
        # UserTagElo model, but that requires a real DB table.
        # Instead, we verify the elo_change field which doesn't depend on refresh.

        # The mock returns _FakeMEloRecord(elo=1495) from update_melo.
        # skip_problem reads new_melo from melo_record.elo after refresh.
        # With the mock, db.refresh is called on _FakeMEloRecord which fails
        # because it's not a mapped class.
        # This reveals a BUG: skip_problem calls db.refresh() on a non-mapped object.

        # Workaround: patch get_or_create_melo to return a real DB-backed UserTagElo
        melo_record = _TestUserTagElo(
            user_id=user.id,
            tag="dp",
            elo=1500,
        )
        db.add(melo_record)
        await db.flush()

        from unittest.mock import AsyncMock

        # Re-patch MEloService methods to use real DB record
        melo_svc = training_svc_module.MEloService
        melo_svc.is_shield_active = AsyncMock(return_value=False)
        melo_svc.get_or_create_melo = AsyncMock(return_value=melo_record)
        melo_svc.update_melo = AsyncMock()

        result = await TrainingService.skip_problem(db, user, session.id, "1234A")
        assert result.elo_change == -5

    @pytest.mark.asyncio
    async def test_skip_no_started_at_treated_as_protection(self, db):
        """Skip with no started_at: treated as within protection."""
        user = _make_test_user(elo=1500)
        topic = _make_test_topic()
        db.add(user)
        db.add(topic)
        await db.flush()

        session = _make_test_session(
            user_id=user.id,
            topic_id=topic.id,
            started_at=None,
        )
        db.add(session)
        await db.flush()

        result = await TrainingService.skip_problem(db, user, session.id, "1234A")
        assert result.elo_change is None

    @pytest.mark.asyncio
    async def test_skip_session_not_found_raises(self, db):
        """Skip on non-existent session raises NotFoundException."""
        user = _make_test_user()
        db.add(user)
        await db.flush()

        with pytest.raises(NotFoundException):
            await TrainingService.skip_problem(db, user, uuid.uuid4(), "1234A")

    @pytest.mark.asyncio
    async def test_skip_session_not_active_raises(self, db):
        """Skip on a completed session raises BadRequestException."""
        user = _make_test_user()
        topic = _make_test_topic()
        db.add_all([user, topic])
        await db.flush()

        session = _make_test_session(
            user_id=user.id,
            topic_id=topic.id,
            status="completed",
        )
        db.add(session)
        await db.flush()

        with pytest.raises(BadRequestException, match="not active"):
            await TrainingService.skip_problem(db, user, session.id, "1234A")

    @pytest.mark.asyncio
    async def test_skip_creates_problem_record(self, db):
        """Skip should create a TrainingProblemRecord with solved=False."""
        user = _make_test_user(elo=1500)
        topic = _make_test_topic()
        db.add(user)
        db.add(topic)
        await db.flush()

        session = _make_test_session(
            user_id=user.id,
            topic_id=topic.id,
            started_at=datetime.now(UTC),
        )
        db.add(session)
        await db.flush()

        await TrainingService.skip_problem(db, user, session.id, "999Z")

        # Verify record was created
        from sqlalchemy import select

        stmt = select(_TestTrainingProblemRecord).where(
            _TestTrainingProblemRecord.session_id == session.id,
            _TestTrainingProblemRecord.problem_id == "999Z",
        )
        result = await db.execute(stmt)
        record = result.scalar_one_or_none()
        assert record is not None
        assert record.solved is False
        assert record.problem_id == "999Z"

    @pytest.mark.asyncio
    async def test_skip_returns_session_id_and_problem_id(self, db):
        """Skip response must include session_id and problem_id."""
        user = _make_test_user()
        topic = _make_test_topic()
        db.add_all([user, topic])
        await db.flush()

        session = _make_test_session(user.id, topic.id, started_at=datetime.now(UTC))
        db.add(session)
        await db.flush()

        result = await TrainingService.skip_problem(db, user, session.id, "555B")
        assert str(result.session_id) == str(session.id)
        assert result.problem_id == "555B"


# ---------------------------------------------------------------------------
# build_login_response tests
# ---------------------------------------------------------------------------


class TestBuildLoginResponse:
    """Test that login response includes login_time field."""

    def test_login_response_includes_login_time(self):
        from app.services.auth_service import build_login_response

        user = type("User", (), {})()
        tokens = {"access_token": "test-access", "refresh_token": "test-refresh"}

        result = build_login_response(user, tokens)

        assert "login_time" in result
        assert result["access_token"] == "test-access"
        assert result["refresh_token"] == "test-refresh"
        assert result["token_type"] == "bearer"

        # Verify ISO 8601 format
        login_time = result["login_time"]
        parsed = datetime.fromisoformat(login_time.replace("Z", "+00:00"))
        assert isinstance(parsed, datetime)

    def test_login_time_is_recent(self):
        from app.services.auth_service import build_login_response

        user = type("User", (), {})()
        tokens = {"access_token": "a", "refresh_token": "r"}

        before = datetime.now(UTC)
        result = build_login_response(user, tokens)
        after = datetime.now(UTC)

        login_time = datetime.fromisoformat(result["login_time"].replace("Z", "+00:00"))
        assert before <= login_time <= after


# ---------------------------------------------------------------------------
# Protection period constant verification
# ---------------------------------------------------------------------------


class TestProtectionDuration:
    """Verify protection period is exactly 300 seconds."""

    def test_abandon_uses_300_seconds(self):
        import inspect

        source = inspect.getsource(TrainingService.abandon_training)
        assert "300" in source

    def test_skip_uses_300_seconds(self):
        import inspect

        source = inspect.getsource(TrainingService.skip_problem)
        assert "300" in source


# ---------------------------------------------------------------------------
# Topic medal data in list_topics
# ---------------------------------------------------------------------------


class TestTopicsMedalData:
    """Verify list_topics returns medal data correctly."""

    @pytest.mark.asyncio
    async def test_topics_return_medal_fields(self, db):
        """GET /training/topics should return medal, current_medal_threshold, next_medal_threshold."""
        user = _make_test_user(elo=1500)
        topic = _make_test_topic(slug="dp", cf_tags=["dp"])
        db.add(user)
        db.add(topic)
        await db.flush()

        cf_mock = AsyncMock()
        cf_mock.get_problemset_problems.return_value = {"problems": []}

        # list_topics expects melo data
        topics = await TrainingService.list_topics(db, user_id=user.id, cf_service=cf_mock)

        assert len(topics) > 0
        dp_topic = next((t for t in topics if t.slug == "dp"), None)
        assert dp_topic is not None
        assert dp_topic.medal is not None
        assert dp_topic.current_medal_threshold is not None or dp_topic.next_medal_threshold is not None

    @pytest.mark.asyncio
    async def test_topics_unranked_user_has_correct_thresholds(self, db):
        """User with no M-Elo should see medal=unranked, next=1200, current=None."""
        user = _make_test_user(elo=1000)
        topic = _make_test_topic(slug="strings", cf_tags=["strings"])
        db.add(user)
        db.add(topic)
        await db.flush()

        cf_mock = AsyncMock()
        cf_mock.get_problemset_problems.return_value = {"problems": []}

        topics = await TrainingService.list_topics(db, user_id=user.id, cf_service=cf_mock)

        strings_topic = next((t for t in topics if t.slug == "strings"), None)
        assert strings_topic is not None
        assert strings_topic.medal.level == "unranked"
        assert strings_topic.current_medal_threshold is None
        assert strings_topic.next_medal_threshold == 1200


# ---------------------------------------------------------------------------
# Cross-mode protection period consistency check
# ---------------------------------------------------------------------------


class TestCrossModeProtection:
    """Verify protection period is only in training, not other modes."""

    def test_pve_challenge_has_no_protection(self):
        """PvE challenge service should NOT have 300-second protection logic."""
        import inspect

        from app.services import pve_challenge_service as pve_svc

        # Check if abandonTraining or equivalent uses 300
        source = inspect.getsource(pve_svc)
        # We expect PvE to NOT have a protection period concept
        # If it does, that's a design deviation worth noting
        if "300" in source and "protection" in source.lower():
            pytest.fail("PvE challenge has protection period logic -- verify this is intentional")
