"""Tests for Task 47.1: Topics medal data + protection period + skip-problem + login_time.

Covers:
- FR-26.2: Medal info (level, type, current_medal_threshold, next_medal_threshold) in topics
- FR-28.1: Protection period (300s) -- no Elo deduction within protection
- FR-28.2: Post-protection abandon penalty -- exactly -5 M-Elo for 0 submissions
- Skip problem endpoint: POST /training/session/{id}/skip-problem
- Login time field: POST /auth/login includes login_time as ISO 8601

Uses the same lightweight SQLite + mock patterns from test_training.py.
"""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import JSON, Boolean, DateTime, Float, Integer, String, event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core.exceptions import BadRequestException, ForbiddenException
from app.schemas.training import SkipProblemResponse
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


# ---------------------------------------------------------------------------
# Fake helper classes
# ---------------------------------------------------------------------------


class _FakeMEloRecord:
    """Minimal stand-in for a UserTagElo ORM object."""

    def __init__(self, elo: int = 1200, tag: str = "dp", first_ac_at=None):
        self.elo = elo
        self.tag = tag
        self.total_submissions = 0
        self.first_ac_at = first_ac_at


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
        return_value=_FakeMEloRecord(elo=1200, tag="dp"),
    )
    _mock_melo_service.deactivate_shield = AsyncMock(
        return_value=_FakeMEloRecord(elo=1200, tag="dp"),
    )
    _mock_melo_service.update_melo = AsyncMock(
        return_value=_FakeMEloRecord(elo=1200, tag="dp"),
    )
    _mock_melo_service.get_all_melos = AsyncMock(
        return_value=[_FakeMEloRecord(elo=1200, tag="dp")],
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
    db: AsyncSession,
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


def _make_test_topic(
    db: AsyncSession,
    topic_id: uuid.UUID | None = None,
    name: str = "Dynamic Programming",
    slug: str = "dp",
    cf_tags: list | None = None,
    display_order: int = 0,
) -> _TestTopicCategory:
    return _TestTopicCategory(
        id=topic_id or uuid.uuid4(),
        name=name,
        slug=slug,
        description=f"Test topic: {name}",
        cf_tags=cf_tags or ["dp"],
        display_order=display_order,
    )


# ===========================================================================
# SECTION 1: Medal data tests (FR-26.2)
# ===========================================================================


class TestMedalInfoComputation:
    """Tests for _compute_medal_info function -- pure unit tests."""

    def test_melo_none_returns_unranked(self):
        """melo=None means unranked, next threshold 1200."""
        medal, current, nxt = _compute_medal_info(None)
        assert medal.level == "unranked"
        assert medal.type is None
        assert current is None
        assert nxt == 1200

    def test_melo_below_1200_returns_unranked(self):
        """melo=800 -> unranked, next threshold 1200."""
        medal, current, nxt = _compute_medal_info(800.0)
        assert medal.level == "unranked"
        assert medal.type is None
        assert current is None
        assert nxt == 1200

    def test_melo_1199_returns_unranked(self):
        """melo=1199 -> still unranked (below 1200 threshold)."""
        medal, current, nxt = _compute_medal_info(1199.0)
        assert medal.level == "unranked"
        assert current is None
        assert nxt == 1200

    def test_melo_1200_provincial_bronze(self):
        """melo=1200 -> provincial bronze, current=1200, next=1400."""
        medal, current, nxt = _compute_medal_info(1200.0)
        assert medal.level == "provincial"
        assert medal.type == "bronze"
        assert current == 1200
        assert nxt == 1400

    def test_melo_1300_provincial_bronze(self):
        """melo=1300 -> still provincial bronze."""
        medal, current, nxt = _compute_medal_info(1300.0)
        assert medal.level == "provincial"
        assert medal.type == "bronze"
        assert current == 1200
        assert nxt == 1400

    def test_melo_1399_provincial_bronze(self):
        """melo=1399 -> still provincial bronze (just below silver)."""
        medal, current, nxt = _compute_medal_info(1399.0)
        assert medal.level == "provincial"
        assert medal.type == "bronze"

    def test_melo_1400_provincial_silver(self):
        """melo=1400 -> provincial silver, current=1400, next=1600."""
        medal, current, nxt = _compute_medal_info(1400.0)
        assert medal.level == "provincial"
        assert medal.type == "silver"
        assert current == 1400
        assert nxt == 1600

    def test_melo_1500_provincial_silver(self):
        """melo=1500 -> provincial silver."""
        medal, current, nxt = _compute_medal_info(1500.0)
        assert medal.level == "provincial"
        assert medal.type == "silver"

    def test_melo_1600_provincial_gold(self):
        """melo=1600 -> provincial gold, current=1600, next=2200."""
        medal, current, nxt = _compute_medal_info(1600.0)
        assert medal.level == "provincial"
        assert medal.type == "gold"
        assert current == 1600
        assert nxt == 2200

    def test_melo_2199_provincial_gold(self):
        """melo=2199 -> still provincial gold."""
        medal, current, nxt = _compute_medal_info(2199.0)
        assert medal.level == "provincial"
        assert medal.type == "gold"

    def test_melo_2200_regional_gold(self):
        """melo=2200 -> regional gold, current=2200, next=2600."""
        medal, current, nxt = _compute_medal_info(2200.0)
        assert medal.level == "regional"
        assert medal.type == "gold"
        assert current == 2200
        assert nxt == 2600

    def test_melo_2500_regional_gold(self):
        """melo=2500 -> still regional gold."""
        medal, current, nxt = _compute_medal_info(2500.0)
        assert medal.level == "regional"
        assert medal.type == "gold"

    def test_melo_2599_regional_gold(self):
        """melo=2599 -> still regional gold."""
        medal, current, nxt = _compute_medal_info(2599.0)
        assert medal.level == "regional"
        assert medal.type == "gold"

    def test_melo_2600_ec_final_gold(self):
        """melo=2600 -> EC Final gold, current=2600, next=2800."""
        medal, current, nxt = _compute_medal_info(2600.0)
        assert medal.level == "ec_final"
        assert medal.type == "gold"
        assert current == 2600
        assert nxt == 2800

    def test_melo_2700_ec_final_gold(self):
        """melo=2700 -> EC Final gold."""
        medal, current, nxt = _compute_medal_info(2700.0)
        assert medal.level == "ec_final"
        assert medal.type == "gold"

    def test_melo_2800_world_finals_gold(self):
        """melo=2800 -> World Finals gold, current=2800, next=None (highest)."""
        medal, current, nxt = _compute_medal_info(2800.0)
        assert medal.level == "world_finals"
        assert medal.type == "gold"
        assert current == 2800
        assert nxt is None

    def test_melo_3500_world_finals_gold(self):
        """melo=3500 -> still World Finals gold (highest tier)."""
        medal, current, nxt = _compute_medal_info(3500.0)
        assert medal.level == "world_finals"
        assert medal.type == "gold"
        assert nxt is None


class TestMedalInfoInTopicsList:
    """Integration test: medal data appears in list_topics response."""

    async def test_topic_without_melo_has_unranked_medal(self, db, cf_mock):
        """When user has no M-Elo record for a tag, medal is unranked."""
        user = _make_test_user(db)
        db.add(user)
        await db.flush()

        # Mock get_all_melos to return empty (no M-Elo records)
        training_svc_module.MEloService.get_all_melos = AsyncMock(return_value=[])

        topics = await TrainingService.list_topics(db, user_id=user.id, cf_service=cf_mock)
        assert len(topics) > 0

        # All topics should have medal data
        for topic in topics:
            assert topic.medal is not None, f"Topic {topic.slug} missing medal info"
            assert topic.medal.level == "unranked"
            assert topic.medal.type is None
            assert topic.current_medal_threshold is None
            assert topic.next_medal_threshold == 1200

    async def test_topic_with_melo_1200_has_provincial_bronze(self, db, cf_mock):
        """M-Elo 1200 maps to provincial bronze medal."""
        user = _make_test_user(db)
        db.add(user)
        await db.flush()

        # Mock get_all_melos to return melo=1200 for dp tag
        training_svc_module.MEloService.get_all_melos = AsyncMock(
            return_value=[_FakeMEloRecord(elo=1200, tag="dp")],
        )

        topics = await TrainingService.list_topics(db, user_id=user.id, cf_service=cf_mock)
        dp_topic = next(t for t in topics if t.slug == "dp")

        assert dp_topic.medal is not None
        assert dp_topic.medal.level == "provincial"
        assert dp_topic.medal.type == "bronze"
        assert dp_topic.current_medal_threshold == 1200
        assert dp_topic.next_medal_threshold == 1400

    async def test_topic_with_melo_2800_has_world_finals_gold(self, db, cf_mock):
        """M-Elo 2800 maps to World Finals gold medal."""
        user = _make_test_user(db)
        db.add(user)
        await db.flush()

        training_svc_module.MEloService.get_all_melos = AsyncMock(
            return_value=[_FakeMEloRecord(elo=2800, tag="dp")],
        )

        topics = await TrainingService.list_topics(db, user_id=user.id, cf_service=cf_mock)
        dp_topic = next(t for t in topics if t.slug == "dp")

        assert dp_topic.medal is not None
        assert dp_topic.medal.level == "world_finals"
        assert dp_topic.medal.type == "gold"
        assert dp_topic.current_medal_threshold == 2800
        assert dp_topic.next_medal_threshold is None

    async def test_topics_without_user_have_unranked_medal(self, db):
        """list_topics without user_id still returns medal data (unranked)."""
        topics = await TrainingService.list_topics(db)
        assert len(topics) > 0
        for topic in topics:
            assert topic.medal is not None
            assert topic.medal.level == "unranked"


# ===========================================================================
# SECTION 2: Protection period abandon tests (FR-28.1, FR-28.2)
# ===========================================================================


class TestProtectionPeriodAbandon:
    """Tests for abandon_training with 300s protection period."""

    async def test_abandon_within_300s_zero_subs_no_elo_change(self, db):
        """FR-28.1: Within protection period, 0 subs, no Elo change."""
        user = _make_test_user(db, elo=1200)
        topic = _make_test_topic(db)
        db.add_all([user, topic])
        await db.flush()

        now = datetime.now(UTC)
        session = _TestTrainingSession(
            user_id=user.id,
            topic_id=topic.id,
            total_problems=5,
            status="active",
            started_at=now,  # Just started, within protection
        )
        db.add(session)
        await db.flush()

        result = await TrainingService.abandon_training(db, user, session.id)
        assert result.elo_change is None
        assert result.status == "abandoned"

    async def test_abandon_within_300s_with_subs_no_elo_change(self, db):
        """FR-28.1: Within protection period, 2 subs, still no Elo change."""
        user = _make_test_user(db, elo=1200)
        topic = _make_test_topic(db)
        db.add_all([user, topic])
        await db.flush()

        now = datetime.now(UTC)
        session = _TestTrainingSession(
            user_id=user.id,
            topic_id=topic.id,
            total_problems=5,
            problems_solved=2,
            status="active",
            started_at=now,  # Within protection
        )
        db.add(session)
        await db.flush()

        # Add 2 submission records
        for i in range(2):
            record = _TestTrainingProblemRecord(
                session_id=session.id,
                user_id=user.id,
                topic_id=topic.id,
                problem_id=f"100{chr(65 + i)}",
                problem_rating=800,
                solved=True,
                attempts=1,
                time_spent=60.0,
                solved_at=now,
            )
            db.add(record)
        await db.flush()

        result = await TrainingService.abandon_training(db, user, session.id)
        assert result.elo_change is None
        assert result.problems_solved == 2

    async def test_abandon_after_300s_zero_subs_exactly_minus_5(self, db):
        """FR-28.2: Protection expired, 0 subs, exactly -5 M-Elo deduction."""
        user = _make_test_user(db, elo=1200)
        topic = _make_test_topic(db)
        db.add_all([user, topic])
        await db.flush()

        # started 400 seconds ago (beyond 300s protection)
        started = datetime.now(UTC) - timedelta(seconds=400)
        session = _TestTrainingSession(
            user_id=user.id,
            topic_id=topic.id,
            total_problems=5,
            status="active",
            started_at=started,
        )
        db.add(session)
        await db.flush()

        # Mock MEloService to return a melo record and track update_melo
        updated_melo = _FakeMEloRecord(elo=1195, tag="dp")
        training_svc_module.MEloService.get_or_create_melo = AsyncMock(
            return_value=_FakeMEloRecord(elo=1200, tag="dp"),
        )
        training_svc_module.MEloService.update_melo = AsyncMock(
            return_value=updated_melo,
        )
        training_svc_module.MEloService.is_shield_active = AsyncMock(return_value=False)

        result = await TrainingService.abandon_training(db, user, session.id)
        assert result.elo_change == -5
        # Verify update_melo was called with -5
        # Signature: update_melo(db, user_id, tag, elo_change)
        training_svc_module.MEloService.update_melo.assert_called_once()
        call_args = training_svc_module.MEloService.update_melo.call_args
        assert call_args[0][3] == -5  # Fourth positional arg is the elo_change delta

    async def test_abandon_after_300s_with_subs_normal_calculation(self, db):
        """FR-28.2: Protection expired, 3 subs, normal failure calculation."""
        user = _make_test_user(db, elo=1200)
        topic = _make_test_topic(db)
        db.add_all([user, topic])
        await db.flush()

        started = datetime.now(UTC) - timedelta(seconds=400)
        session = _TestTrainingSession(
            user_id=user.id,
            topic_id=topic.id,
            total_problems=5,
            problems_solved=3,
            status="active",
            started_at=started,
        )
        db.add(session)
        await db.flush()

        # Add 3 submission records
        for i in range(3):
            record = _TestTrainingProblemRecord(
                session_id=session.id,
                user_id=user.id,
                topic_id=topic.id,
                problem_id=f"100{chr(65 + i)}",
                problem_rating=1200,
                solved=(i < 2),  # 2 solved, 1 failed
                attempts=1,
                time_spent=60.0,
                solved_at=datetime.now(UTC) if i < 2 else None,
            )
            db.add(record)
        await db.flush()

        training_svc_module.MEloService.is_shield_active = AsyncMock(return_value=False)

        result = await TrainingService.abandon_training(db, user, session.id)
        # With submissions, the code delegates to _calculate_training_elo
        # elo_change should be a number (could be negative or zero)
        assert result.elo_change is not None

    async def test_abandon_after_300s_zero_subs_with_shield_no_deduction(self, db):
        """Learning shield active, protection expired, 0 subs: no deduction."""
        user = _make_test_user(db, elo=1200)
        topic = _make_test_topic(db)
        db.add_all([user, topic])
        await db.flush()

        started = datetime.now(UTC) - timedelta(seconds=400)
        session = _TestTrainingSession(
            user_id=user.id,
            topic_id=topic.id,
            total_problems=5,
            status="active",
            started_at=started,
        )
        db.add(session)
        await db.flush()

        # Shield active means first_ac_at is None
        training_svc_module.MEloService.is_shield_active = AsyncMock(return_value=True)

        result = await TrainingService.abandon_training(db, user, session.id)
        assert result.elo_change is None
        assert result.shield_active is True

    async def test_abandon_exactly_at_300s_boundary(self, db):
        """Boundary test: exactly at 300s should be outside protection (>=300)."""
        user = _make_test_user(db, elo=1200)
        topic = _make_test_topic(db)
        db.add_all([user, topic])
        await db.flush()

        # started exactly 300 seconds ago -- the condition is `< 300`, so 300
        # is NOT within protection
        started = datetime.now(UTC) - timedelta(seconds=300)
        session = _TestTrainingSession(
            user_id=user.id,
            topic_id=topic.id,
            total_problems=5,
            status="active",
            started_at=started,
        )
        db.add(session)
        await db.flush()

        training_svc_module.MEloService.is_shield_active = AsyncMock(return_value=False)
        training_svc_module.MEloService.get_or_create_melo = AsyncMock(
            return_value=_FakeMEloRecord(elo=1200, tag="dp"),
        )
        training_svc_module.MEloService.update_melo = AsyncMock(
            return_value=_FakeMEloRecord(elo=1195, tag="dp"),
        )

        result = await TrainingService.abandon_training(db, user, session.id)
        # At 300s boundary, (now - started_at) >= 300, so NOT in protection
        assert result.elo_change == -5

    async def test_abandon_just_under_300s_still_protected(self, db):
        """Boundary test: 299s should still be within protection."""
        user = _make_test_user(db, elo=1200)
        topic = _make_test_topic(db)
        db.add_all([user, topic])
        await db.flush()

        started = datetime.now(UTC) - timedelta(seconds=299)
        session = _TestTrainingSession(
            user_id=user.id,
            topic_id=topic.id,
            total_problems=5,
            status="active",
            started_at=started,
        )
        db.add(session)
        await db.flush()

        result = await TrainingService.abandon_training(db, user, session.id)
        # 299s is < 300, so protection is active
        assert result.elo_change is None

    async def test_abandon_no_started_at_treated_as_protected(self, db):
        """Session with no started_at is treated as within protection."""
        user = _make_test_user(db, elo=1200)
        topic = _make_test_topic(db)
        db.add_all([user, topic])
        await db.flush()

        session = _TestTrainingSession(
            user_id=user.id,
            topic_id=topic.id,
            total_problems=5,
            status="active",
            started_at=None,  # No started_at
        )
        db.add(session)
        await db.flush()

        result = await TrainingService.abandon_training(db, user, session.id)
        assert result.elo_change is None


# ===========================================================================
# SECTION 3: Skip problem tests (FR-28.2 skip-problem endpoint)
# ===========================================================================


class TestSkipProblem:
    """Tests for TrainingService.skip_problem."""

    async def test_skip_during_protection_no_penalty(self, db):
        """Skip within protection period: no penalty."""
        user = _make_test_user(db, elo=1200)
        topic = _make_test_topic(db)
        db.add_all([user, topic])
        await db.flush()

        now = datetime.now(UTC)
        session = _TestTrainingSession(
            user_id=user.id,
            topic_id=topic.id,
            total_problems=5,
            status="active",
            started_at=now,  # Just started
        )
        db.add(session)
        await db.flush()

        result = await TrainingService.skip_problem(
            db=db,
            user=user,
            session_id=session.id,
            problem_id="100A",
        )

        assert isinstance(result, SkipProblemResponse)
        assert result.session_id == session.id
        assert result.problem_id == "100A"
        assert result.elo_change is None  # No penalty during protection
        assert result.new_melo is not None  # Should return current melo

    async def test_skip_after_protection_minus_5(self, db):
        """Skip after protection period: -5 M-Elo."""
        user = _make_test_user(db, elo=1200)
        topic = _make_test_topic(db)
        db.add_all([user, topic])
        await db.flush()

        started = datetime.now(UTC) - timedelta(seconds=400)
        session = _TestTrainingSession(
            user_id=user.id,
            topic_id=topic.id,
            total_problems=5,
            status="active",
            started_at=started,
        )
        db.add(session)
        await db.flush()

        # Create a fake melo record whose elo attribute will be updated
        fake_melo = _FakeMEloRecord(elo=1200, tag="dp")

        async def _fake_update_melo(db, user_id, tag, elo_change):
            fake_melo.elo += elo_change
            return fake_melo

        # Mock MEloService for post-protection skip
        training_svc_module.MEloService.is_shield_active = AsyncMock(return_value=False)
        training_svc_module.MEloService.get_or_create_melo = AsyncMock(
            return_value=fake_melo,
        )
        training_svc_module.MEloService.update_melo = AsyncMock(
            side_effect=_fake_update_melo,
        )

        # The skip_problem code calls db.refresh(melo_record) which fails on
        # non-mapped objects.  Patch db.refresh to be a no-op so the fake
        # record's .elo attribute (updated by _fake_update_melo) is used.
        original_refresh = db.refresh

        async def _noop_refresh(instance, **kwargs):
            pass

        db.refresh = _noop_refresh

        result = await TrainingService.skip_problem(
            db=db,
            user=user,
            session_id=session.id,
            problem_id="100A",
        )

        # Restore
        db.refresh = original_refresh

        assert result.elo_change == -5
        assert result.new_melo == 1195  # 1200 - 5
        # Signature: update_melo(db, user_id, tag, elo_change)
        training_svc_module.MEloService.update_melo.assert_called_once()
        call_args = training_svc_module.MEloService.update_melo.call_args
        assert call_args[0][3] == -5  # Fourth positional arg is the elo_change delta

    async def test_skip_with_shield_active_no_penalty(self, db):
        """Skip after protection but with learning shield: no penalty."""
        user = _make_test_user(db, elo=1200)
        topic = _make_test_topic(db)
        db.add_all([user, topic])
        await db.flush()

        started = datetime.now(UTC) - timedelta(seconds=400)
        session = _TestTrainingSession(
            user_id=user.id,
            topic_id=topic.id,
            total_problems=5,
            status="active",
            started_at=started,
        )
        db.add(session)
        await db.flush()

        training_svc_module.MEloService.is_shield_active = AsyncMock(return_value=True)
        training_svc_module.MEloService.get_or_create_melo = AsyncMock(
            return_value=_FakeMEloRecord(elo=1200, tag="dp"),
        )

        result = await TrainingService.skip_problem(
            db=db,
            user=user,
            session_id=session.id,
            problem_id="100A",
        )

        assert result.elo_change is None  # Shield prevents deduction
        # update_melo should NOT have been called
        training_svc_module.MEloService.update_melo.assert_not_called()

    async def test_skip_creates_problem_record(self, db):
        """Skip creates a TrainingProblemRecord with solved=False."""
        user = _make_test_user(db, elo=1200)
        topic = _make_test_topic(db)
        db.add_all([user, topic])
        await db.flush()

        now = datetime.now(UTC)
        session = _TestTrainingSession(
            user_id=user.id,
            topic_id=topic.id,
            total_problems=5,
            status="active",
            started_at=now,
        )
        db.add(session)
        await db.flush()

        await TrainingService.skip_problem(
            db=db,
            user=user,
            session_id=session.id,
            problem_id="100A",
        )

        # Verify a problem record was created
        from sqlalchemy import select

        stmt = select(_TestTrainingProblemRecord).where(
            _TestTrainingProblemRecord.session_id == session.id,
            _TestTrainingProblemRecord.problem_id == "100A",
        )
        record_result = await db.execute(stmt)
        record = record_result.scalar_one_or_none()
        assert record is not None
        assert record.solved is False

    async def test_skip_returns_correct_response_shape(self, db):
        """Skip response includes all required fields."""
        user = _make_test_user(db, elo=1200)
        topic = _make_test_topic(db)
        db.add_all([user, topic])
        await db.flush()

        now = datetime.now(UTC)
        session = _TestTrainingSession(
            user_id=user.id,
            topic_id=topic.id,
            total_problems=5,
            status="active",
            started_at=now,
        )
        db.add(session)
        await db.flush()

        result = await TrainingService.skip_problem(
            db=db,
            user=user,
            session_id=session.id,
            problem_id="200B",
        )

        assert hasattr(result, "session_id")
        assert hasattr(result, "problem_id")
        assert hasattr(result, "elo_change")
        assert hasattr(result, "new_melo")
        assert result.session_id == session.id
        assert result.problem_id == "200B"

    async def test_skip_not_active_session_raises(self, db):
        """Skip on completed session raises BadRequestException."""
        user = _make_test_user(db, elo=1200)
        topic = _make_test_topic(db)
        db.add_all([user, topic])
        await db.flush()

        session = _TestTrainingSession(
            user_id=user.id,
            topic_id=topic.id,
            total_problems=5,
            status="completed",
        )
        db.add(session)
        await db.flush()

        with pytest.raises(BadRequestException, match="not active"):
            await TrainingService.skip_problem(
                db=db,
                user=user,
                session_id=session.id,
                problem_id="100A",
            )

    async def test_skip_not_owner_raises(self, db):
        """Skip on another user's session raises ForbiddenException."""
        owner = _make_test_user(db, username="owner")
        other = _make_test_user(db, username="other")
        topic = _make_test_topic(db)
        db.add_all([owner, other, topic])
        await db.flush()

        session = _TestTrainingSession(
            user_id=owner.id,
            topic_id=topic.id,
            total_problems=5,
            status="active",
        )
        db.add(session)
        await db.flush()

        with pytest.raises(ForbiddenException, match="Not your training session"):
            await TrainingService.skip_problem(
                db=db,
                user=other,
                session_id=session.id,
                problem_id="100A",
            )


# ===========================================================================
# SECTION 4: Login time tests (FR-28 login_time)
# ===========================================================================


class TestLoginTime:
    """Tests for auth_service.build_login_response login_time field."""

    def test_build_login_response_contains_login_time(self):
        """build_login_response must include login_time field."""
        from app.services.auth_service import build_login_response

        user = _TestUser(
            id=uuid.uuid4(),
            username="testuser",
            email="test@test.com",
            password_hash="fakehash",  # pragma: allowlist secret
            elo=1200,
        )
        tokens = {
            "access_token": "fake_access_token",
            "refresh_token": "fake_refresh_token",
        }
        result = build_login_response(user, tokens)

        assert "login_time" in result
        assert "access_token" in result
        assert "refresh_token" in result
        assert result["access_token"] == "fake_access_token"
        assert result["refresh_token"] == "fake_refresh_token"
        assert result["token_type"] == "bearer"

    def test_login_time_is_iso_8601_format(self):
        """login_time must be a valid ISO 8601 UTC timestamp."""
        from datetime import datetime

        from app.services.auth_service import build_login_response

        user = _TestUser(
            id=uuid.uuid4(),
            username="testuser",
            email="test@test.com",
            password_hash="fakehash",  # pragma: allowlist secret
        )
        tokens = {
            "access_token": "fake_access",
            "refresh_token": "fake_refresh",
        }

        before = datetime.now(UTC)
        result = build_login_response(user, tokens)
        after = datetime.now(UTC)

        login_time_str = result["login_time"]
        # Parse the ISO 8601 string
        parsed = datetime.fromisoformat(login_time_str)

        # Verify it is a valid timestamp between before and after
        # (may not have microseconds if they were zero, so compare with tolerance)
        assert before <= parsed <= after or abs((parsed - before).total_seconds()) < 1

        # Verify ISO 8601 format (contains 'T' and timezone info)
        # Python's datetime.isoformat() with UTC timezone produces "+00:00" suffix
        assert isinstance(login_time_str, str)
        assert "T" in login_time_str
        # Should have timezone info
        assert "+00:00" in login_time_str or "Z" in login_time_str

    def test_login_time_changes_on_each_call(self):
        """Each call to build_login_response produces a different login_time."""
        from app.services.auth_service import build_login_response

        user = _TestUser(
            id=uuid.uuid4(),
            username="testuser",
            email="test@test.com",
            password_hash="fakehash",  # pragma: allowlist secret
        )
        tokens = {
            "access_token": "fake_access",
            "refresh_token": "fake_refresh",
        }

        import time

        result1 = build_login_response(user, tokens)
        time.sleep(0.01)  # Small delay to ensure different timestamp
        result2 = build_login_response(user, tokens)

        assert result1["login_time"] != result2["login_time"]


class TestLoginTimeAPIRoute:
    """Verify the login route actually calls build_login_response."""

    def test_login_endpoint_calls_build_login_response(self):
        """Auth login route must call build_login_response to include login_time."""
        # Verify that the login route in auth.py imports and calls
        # auth_service.build_login_response. This is an import/reachability check.
        from app.api.v1 import auth as auth_api_module

        # Verify the login endpoint function exists
        assert hasattr(auth_api_module, "login")

        # Verify auth_service has build_login_response
        from app.services import auth_service

        assert hasattr(auth_service, "build_login_response")

    def test_build_login_response_is_called_in_login_flow(self):
        """Verify the login route code references build_login_response."""
        import inspect

        from app.api.v1 import auth as auth_api_module

        source = inspect.getsource(auth_api_module.login)
        assert "build_login_response" in source
