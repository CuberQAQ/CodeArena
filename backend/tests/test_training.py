"""Tests for the training system: topics, sessions, streaks, stars, and progress.

Uses lightweight SQLite-compatible test models and mocks for external services
(CF API). The key technique is patching the production model references in
training_service with test-compatible models so SQLAlchemy queries target the
SQLite tables with the correct column set.
"""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import JSON, Boolean, DateTime, Float, Integer, String, event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core.exceptions import BadRequestException, ForbiddenException, NotFoundException
from app.schemas.training import RecommendedProblemResponse
from app.services import config_service as config_svc_module
from app.services import economy_service as economy_svc_module
from app.services import elo_service as elo_svc_module
from app.services import training_service as training_svc_module
from app.services.training_service import (
    TrainingService,
    _attempt_tokens_for_rating,
    _tokens_for_rating,
    calculate_stars,
    calculate_stars_from_melo,
)

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
    elo: Mapped[int] = mapped_column(Integer, default=1200, nullable=False)
    pp: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


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
    """Provide an async session with patched model references.

    Patches model references in training_service with SQLite-compatible
    test models.  Also patches economy_svc.award_tokens to directly add
    tokens to user (bypassing daily cap / production-column logic).
    Also patches MEloService methods (shield/elo logic) and config_svc
    so _calculate_training_elo does not hit real DB tables or config.
    """
    session_factory = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)

    async def _mock_award_tokens(db, user, amount, tx_type=None, reference_type=None, reference_id=None):
        """Side-effect mock: add tokens directly to user object."""
        user.tokens += amount
        return amount

    # Default mock M-Elo methods -- return safe defaults
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

    # Mock HintService so _calculate_training_elo doesn't query hint_purchases
    _mock_hint_service = AsyncMock()
    _mock_hint_service.get_max_hint_level = AsyncMock(return_value=0)

    # Default K factor config: use k_newbie=8 to match the previous hard-coded K=8
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

    # Mock batch_update_melo_for_problem so it matches the old _mock_melo_service.update_melo
    _mock_melo_service.batch_update_melo_for_problem = AsyncMock(return_value={"dp": 0})

    async with session_factory() as session:
        # Clear the bulk-fetch cache so each test starts fresh
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
    db: AsyncSession,
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


# ---------------------------------------------------------------------------
# 1. Star calculation tests
# ---------------------------------------------------------------------------


class TestStarCalculation:
    def test_zero_percent_is_zero_stars(self):
        assert calculate_stars(0) == 0

    def test_one_percent_is_one_star(self):
        assert calculate_stars(1) == 1

    def test_twenty_percent_is_one_star(self):
        """Exactly 20% should be 1 star (<= 20)."""
        assert calculate_stars(20) == 1

    def test_twenty_one_percent_is_two_stars(self):
        assert calculate_stars(20.01) == 2

    def test_forty_percent_is_two_stars(self):
        assert calculate_stars(40) == 2

    def test_sixty_percent_is_three_stars(self):
        assert calculate_stars(60) == 3

    def test_eighty_percent_is_four_stars(self):
        assert calculate_stars(80) == 4

    def test_eighty_one_percent_is_five_stars(self):
        assert calculate_stars(80.01) == 5

    def test_one_hundred_percent_is_five_stars(self):
        assert calculate_stars(100) == 5


class TestStarCalculationFromMElo:
    """Tests for calculate_stars_from_melo."""

    def test_none_is_zero_stars(self):
        assert calculate_stars_from_melo(None) == 0

    def test_below_1000_is_one_star(self):
        assert calculate_stars_from_melo(800) == 1
        assert calculate_stars_from_melo(999) == 1

    def test_1000_is_two_stars(self):
        assert calculate_stars_from_melo(1000) == 2

    def test_1199_is_two_stars(self):
        assert calculate_stars_from_melo(1199) == 2

    def test_1200_is_three_stars(self):
        assert calculate_stars_from_melo(1200) == 3

    def test_1399_is_three_stars(self):
        assert calculate_stars_from_melo(1399) == 3

    def test_1400_is_four_stars(self):
        assert calculate_stars_from_melo(1400) == 4

    def test_1599_is_four_stars(self):
        assert calculate_stars_from_melo(1599) == 4

    def test_1600_is_five_stars(self):
        assert calculate_stars_from_melo(1600) == 5

    def test_1799_is_five_stars(self):
        assert calculate_stars_from_melo(1799) == 5

    def test_1800_is_six_stars(self):
        assert calculate_stars_from_melo(1800) == 6

    def test_1999_is_six_stars(self):
        assert calculate_stars_from_melo(1999) == 6

    def test_2000_is_seven_stars(self):
        assert calculate_stars_from_melo(2000) == 7

    def test_3000_is_seven_stars(self):
        assert calculate_stars_from_melo(3000) == 7


# ---------------------------------------------------------------------------
# 2. Token tier tests
# ---------------------------------------------------------------------------


class TestTokenTiers:
    def test_ac_tokens_gray(self):
        assert _tokens_for_rating(800) == 10
        assert _tokens_for_rating(1199) == 10

    def test_ac_tokens_green(self):
        assert _tokens_for_rating(1200) == 20
        assert _tokens_for_rating(1399) == 20

    def test_ac_tokens_cyan(self):
        assert _tokens_for_rating(1400) == 25
        assert _tokens_for_rating(1599) == 25

    def test_ac_tokens_blue(self):
        assert _tokens_for_rating(1600) == 35
        assert _tokens_for_rating(1899) == 35

    def test_ac_tokens_purple(self):
        assert _tokens_for_rating(1900) == 45
        assert _tokens_for_rating(2099) == 45

    def test_ac_tokens_orange(self):
        assert _tokens_for_rating(2100) == 55
        assert _tokens_for_rating(2399) == 55

    def test_ac_tokens_red(self):
        assert _tokens_for_rating(2400) == 65
        assert _tokens_for_rating(3000) == 65

    def test_attempt_tokens_gray(self):
        assert _attempt_tokens_for_rating(800) == 2
        assert _attempt_tokens_for_rating(1199) == 2

    def test_attempt_tokens_green(self):
        assert _attempt_tokens_for_rating(1200) == 3

    def test_attempt_tokens_cyan(self):
        assert _attempt_tokens_for_rating(1400) == 4

    def test_attempt_tokens_blue(self):
        assert _attempt_tokens_for_rating(1600) == 5

    def test_attempt_tokens_purple(self):
        assert _attempt_tokens_for_rating(1900) == 6

    def test_attempt_tokens_orange(self):
        assert _attempt_tokens_for_rating(2100) == 7

    def test_attempt_tokens_red(self):
        assert _attempt_tokens_for_rating(2400) == 8


# ---------------------------------------------------------------------------
# 3. Topic listing tests
# ---------------------------------------------------------------------------


class TestListTopics:
    async def test_list_topics_returns_all_predefined(self, db):
        """ensure_topics creates all 12 predefined topics."""
        topics = await TrainingService.list_topics(db)
        assert len(topics) == 12

    async def test_list_topics_idempotent(self, db):
        """Calling ensure_topics twice should not create duplicates."""
        await TrainingService.list_topics(db)
        topics = await TrainingService.list_topics(db)
        assert len(topics) == 12

    async def test_list_topics_has_expected_slugs(self, db):
        topics = await TrainingService.list_topics(db)
        slugs = [t.slug for t in topics]
        expected = [
            "dp",
            "greedy",
            "math",
            "graphs",
            "strings",
            "data_structures",
            "binary_search",
            "sorting",
            "constructive",
            "number_theory",
            "trees",
            "geometry",
        ]
        assert slugs == expected


# ---------------------------------------------------------------------------
# 4. Topic detail tests
# ---------------------------------------------------------------------------


class TestGetTopicDetail:
    async def test_topic_detail_not_found(self, db, cf_mock):
        user = _make_test_user(db)
        db.add(user)
        await db.flush()

        with pytest.raises(NotFoundException, match="Topic not found"):
            await TrainingService.get_topic_detail(db, uuid.uuid4(), user.id, cf_mock)

    async def test_topic_detail_with_problems(self, db, cf_mock):
        user = _make_test_user(db)
        topic = _make_test_topic(db)
        db.add_all([user, topic])
        await db.flush()

        detail = await TrainingService.get_topic_detail(db, topic.id, user.id, cf_mock)
        assert detail.name == "Dynamic Programming"
        assert detail.total_problems == 5
        assert len(detail.problems) == 5

    async def test_topic_detail_problems_sorted_by_rating(self, db, cf_mock):
        user = _make_test_user(db)
        topic = _make_test_topic(db)
        db.add_all([user, topic])
        await db.flush()

        detail = await TrainingService.get_topic_detail(db, topic.id, user.id, cf_mock)
        ratings = [p.rating for p in detail.problems]
        assert ratings == sorted(ratings)

    async def test_topic_detail_shows_solved_status(self, db, cf_mock):
        user = _make_test_user(db)
        topic = _make_test_topic(db)
        db.add_all([user, topic])
        await db.flush()

        # Create a session and a solved record
        session_id = uuid.uuid4()
        session = _TestTrainingSession(
            id=session_id,
            user_id=user.id,
            topic_id=topic.id,
            problems_solved=1,
            total_problems=5,
            status="completed",
        )
        db.add(session)

        record = _TestTrainingProblemRecord(
            session_id=session_id,
            user_id=user.id,
            topic_id=topic.id,
            problem_id="100A",
            problem_rating=800,
            solved=True,
            attempts=1,
            time_spent=60.0,
            solved_at=datetime.now(UTC),
        )
        db.add(record)
        await db.flush()

        detail = await TrainingService.get_topic_detail(db, topic.id, user.id, cf_mock)
        solved_problems = [p for p in detail.problems if p.solved]
        assert len(solved_problems) == 1
        assert solved_problems[0].problem_id == "100A"


# ---------------------------------------------------------------------------
# 5. Start training session tests
# ---------------------------------------------------------------------------


class TestStartTraining:
    async def test_start_training_topic_not_found(self, db, cf_mock):
        user = _make_test_user(db)
        db.add(user)
        await db.flush()

        with pytest.raises(NotFoundException, match="Topic not found"):
            await TrainingService.start_training(db, user, uuid.uuid4(), cf_mock)

    async def test_start_training_success(self, db, cf_mock):
        user = _make_test_user(db)
        topic = _make_test_topic(db)
        db.add_all([user, topic])
        await db.flush()

        result = await TrainingService.start_training(db, user, topic.id, cf_mock)
        assert result.status == "active"
        assert result.topic_id == topic.id
        assert result.total_problems == 5
        assert result.problems_solved == 0

    async def test_start_training_duplicate_session_rejected(self, db, cf_mock):
        user = _make_test_user(db)
        topic = _make_test_topic(db)
        db.add_all([user, topic])
        await db.flush()

        await TrainingService.start_training(db, user, topic.id, cf_mock)
        with pytest.raises(BadRequestException, match="Already have an active"):
            await TrainingService.start_training(db, user, topic.id, cf_mock)


# ---------------------------------------------------------------------------
# 6. Get session status tests
# ---------------------------------------------------------------------------


class TestGetSessionStatus:
    async def test_session_not_found(self, db):
        user = _make_test_user(db)
        db.add(user)
        await db.flush()

        with pytest.raises(NotFoundException, match="Training session not found"):
            await TrainingService.get_session_status(db, user, uuid.uuid4())

    async def test_session_not_owner(self, db):
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
            await TrainingService.get_session_status(db, other, session.id)

    async def test_session_status_active(self, db):
        user = _make_test_user(db)
        topic = _make_test_topic(db)
        db.add_all([user, topic])
        await db.flush()

        session = _TestTrainingSession(
            user_id=user.id,
            topic_id=topic.id,
            total_problems=5,
            problems_solved=2,
            streak_count=1,
            status="active",
        )
        db.add(session)
        await db.flush()

        result = await TrainingService.get_session_status(db, user, session.id)
        assert result.status == "active"
        assert result.problems_solved == 2
        assert result.total_problems == 5
        assert result.streak_count == 1


# ---------------------------------------------------------------------------
# 7. Submit problem tests
# ---------------------------------------------------------------------------


class TestSubmitProblem:
    @patch.object(training_svc_module, "PPService")
    async def test_submit_solved_problem(self, mock_pp_cls, db, cf_mock):
        mock_pp_cls.record_pp = AsyncMock()
        mock_pp_cls.calculate_overkill_multiplier = staticmethod(lambda *a, **kw: 1.0)

        user = _make_test_user(db, tokens=0)
        topic = _make_test_topic(db)
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

        result = await TrainingService.submit_problem(
            db=db,
            user=user,
            session_id=session.id,
            problem_id="100A",
            solved=True,
            attempts=1,
            time_spent=60.0,
            cf_service=cf_mock,
        )

        assert result.solved is True
        assert result.problem_id == "100A"
        # Gray rating (800) -> 10 tokens AC reward
        assert result.tokens_earned >= 10

    @patch.object(training_svc_module, "PPService")
    async def test_submit_unsolved_problem(self, mock_pp_cls, db, cf_mock):
        mock_pp_cls.record_pp = AsyncMock()
        mock_pp_cls.calculate_overkill_multiplier = staticmethod(lambda *a, **kw: 1.0)

        user = _make_test_user(db, tokens=0)
        topic = _make_test_topic(db)
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

        result = await TrainingService.submit_problem(
            db=db,
            user=user,
            session_id=session.id,
            problem_id="200B",
            solved=False,
            attempts=3,
            time_spent=120.0,
            cf_service=cf_mock,
        )

        assert result.solved is False
        # Attempt reward for 1200 rating -> 3 tokens
        assert result.tokens_earned == 3
        # Elo change is now computed for failures too (Task 16.3)
        # With shield inactive, a failure should produce a negative or zero change
        assert result.elo_change is not None

    async def test_submit_not_active_session(self, db, cf_mock):
        user = _make_test_user(db)
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
            await TrainingService.submit_problem(
                db=db,
                user=user,
                session_id=session.id,
                problem_id="100A",
                solved=True,
                attempts=1,
                time_spent=60.0,
                cf_service=cf_mock,
            )

    @patch.object(training_svc_module, "PPService")
    async def test_submit_already_solved_rejected(self, mock_pp_cls, db, cf_mock):
        mock_pp_cls.record_pp = AsyncMock()
        mock_pp_cls.calculate_overkill_multiplier = staticmethod(lambda *a, **kw: 1.0)

        user = _make_test_user(db)
        topic = _make_test_topic(db)
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

        # First submission (solved)
        await TrainingService.submit_problem(
            db=db,
            user=user,
            session_id=session.id,
            problem_id="100A",
            solved=True,
            attempts=1,
            time_spent=60.0,
            cf_service=cf_mock,
        )

        # Second submission (already solved)
        with pytest.raises(BadRequestException, match="already solved"):
            await TrainingService.submit_problem(
                db=db,
                user=user,
                session_id=session.id,
                problem_id="100A",
                solved=True,
                attempts=2,
                time_spent=30.0,
                cf_service=cf_mock,
            )

    async def test_submit_session_not_found(self, db, cf_mock):
        user = _make_test_user(db)
        db.add(user)
        await db.flush()

        with pytest.raises(NotFoundException, match="Training session not found"):
            await TrainingService.submit_problem(
                db=db,
                user=user,
                session_id=uuid.uuid4(),
                problem_id="100A",
                solved=True,
                attempts=1,
                time_spent=60.0,
                cf_service=cf_mock,
            )


# ---------------------------------------------------------------------------
# 8. Streak tests
# ---------------------------------------------------------------------------


class TestStreakMechanism:
    @patch.object(training_svc_module, "PPService")
    async def test_streak_increases_on_every_ac(self, mock_pp_cls, db, cf_mock):
        """Every AC increments the consecutive AC count (streak)."""
        mock_pp_cls.record_pp = AsyncMock()
        mock_pp_cls.calculate_overkill_multiplier = staticmethod(lambda *a, **kw: 1.0)

        user = _make_test_user(db, tokens=0)
        topic = _make_test_topic(db)
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

        # Solve 800 rating problem -> streak = 1 (first AC)
        result1 = await TrainingService.submit_problem(
            db=db,
            user=user,
            session_id=session.id,
            problem_id="100A",
            solved=True,
            attempts=1,
            time_spent=60.0,
            cf_service=cf_mock,
        )
        assert result1.streak_count == 1  # First AC

        # Solve 1200 rating problem -> streak = 2 (consecutive AC)
        result2 = await TrainingService.submit_problem(
            db=db,
            user=user,
            session_id=session.id,
            problem_id="200B",
            solved=True,
            attempts=1,
            time_spent=120.0,
            cf_service=cf_mock,
        )
        assert result2.streak_count == 2  # Second consecutive AC
        assert result2.streak_tokens == 2 * 5  # 2 * 5 = 10 tokens

    @patch.object(training_svc_module, "PPService")
    async def test_streak_resets_on_failure(self, mock_pp_cls, db, cf_mock):
        """Failing a problem resets the streak to 0."""
        mock_pp_cls.record_pp = AsyncMock()
        mock_pp_cls.calculate_overkill_multiplier = staticmethod(lambda *a, **kw: 1.0)

        user = _make_test_user(db, tokens=0)
        topic = _make_test_topic(db)
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

        # Solve 1200 rating problem -> streak = 1
        r1 = await TrainingService.submit_problem(
            db=db,
            user=user,
            session_id=session.id,
            problem_id="200B",
            solved=True,
            attempts=1,
            time_spent=120.0,
            cf_service=cf_mock,
        )
        assert r1.streak_count == 1

        # Fail 800 rating problem -> streak resets to 0
        r2 = await TrainingService.submit_problem(
            db=db,
            user=user,
            session_id=session.id,
            problem_id="100A",
            solved=False,
            attempts=3,
            time_spent=60.0,
            cf_service=cf_mock,
        )
        assert r2.streak_count == 0

    @patch.object(training_svc_module, "PPService")
    async def test_streak_continues_on_same_rating(self, mock_pp_cls, db, cf_mock):
        """Solving same rating problem continues the streak (every AC counts)."""
        mock_pp_cls.record_pp = AsyncMock()
        mock_pp_cls.calculate_overkill_multiplier = staticmethod(lambda *a, **kw: 1.0)

        user = _make_test_user(db, tokens=0)
        topic = _make_test_topic(db)
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

        # Add extra problems with same rating to the mock
        cf_mock.get_problemset_problems.return_value = {
            "problems": [
                {"contestId": 100, "index": "A", "name": "Problem A", "rating": 800, "tags": ["dp"]},
                {"contestId": 100, "index": "B", "name": "Problem B", "rating": 800, "tags": ["dp"]},
            ],
        }

        # Solve first 800 -> streak = 1
        r1 = await TrainingService.submit_problem(
            db=db,
            user=user,
            session_id=session.id,
            problem_id="100A",
            solved=True,
            attempts=1,
            time_spent=60.0,
            cf_service=cf_mock,
        )
        assert r1.streak_count == 1

        # Solve another 800 (same rating) -> streak continues = 2
        r2 = await TrainingService.submit_problem(
            db=db,
            user=user,
            session_id=session.id,
            problem_id="100B",
            solved=True,
            attempts=1,
            time_spent=60.0,
            cf_service=cf_mock,
        )
        assert r2.streak_count == 2

    @patch.object(training_svc_module, "PPService")
    async def test_streak_token_cap(self, mock_pp_cls, db, cf_mock):
        """Streak tokens are capped at 50 per session."""
        mock_pp_cls.record_pp = AsyncMock()
        mock_pp_cls.calculate_overkill_multiplier = staticmethod(lambda *a, **kw: 1.0)

        user = _make_test_user(db, tokens=0)
        topic = _make_test_topic(db)
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

        # Solve all 5 problems -> streak = 5 (every AC counts)
        problems = [
            ("100A", 800),
            ("200B", 1200),
            ("300C", 1600),
            ("400D", 2000),
            ("500E", 2400),
        ]
        total_streak_tokens = 0
        for pid, _rating in problems:
            result = await TrainingService.submit_problem(
                db=db,
                user=user,
                session_id=session.id,
                problem_id=pid,
                solved=True,
                attempts=1,
                time_spent=60.0,
                cf_service=cf_mock,
            )
            total_streak_tokens = result.total_streak_tokens

        # Streak goes 1, 2, 3, 4, 5. Bonuses: 5, 10, 15, 20, 25 = 75 potential
        # But capped at 50 per session
        assert total_streak_tokens <= 50

    @patch.object(training_svc_module, "PPService")
    async def test_streak_interrupted_by_failure_resets_and_rebuilds(self, mock_pp_cls, db, cf_mock):
        """A failure resets streak to 0, next AC starts a new streak at 1."""
        mock_pp_cls.record_pp = AsyncMock()
        mock_pp_cls.calculate_overkill_multiplier = staticmethod(lambda *a, **kw: 1.0)

        user = _make_test_user(db, tokens=0)
        topic = _make_test_topic(db)
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

        # Solve 800 -> streak = 1
        r1 = await TrainingService.submit_problem(
            db=db,
            user=user,
            session_id=session.id,
            problem_id="100A",
            solved=True,
            attempts=1,
            time_spent=60.0,
            cf_service=cf_mock,
        )
        assert r1.streak_count == 1

        # Fail on 1200 -> streak resets to 0
        r2 = await TrainingService.submit_problem(
            db=db,
            user=user,
            session_id=session.id,
            problem_id="200B",
            solved=False,
            attempts=3,
            time_spent=120.0,
            cf_service=cf_mock,
        )
        assert r2.streak_count == 0

        # Now solve 1200 (same as failed) -> new streak starts at 1
        result = await TrainingService.submit_problem(
            db=db,
            user=user,
            session_id=session.id,
            problem_id="200B",
            solved=True,
            attempts=5,
            time_spent=180.0,
            cf_service=cf_mock,
        )
        assert result.streak_count == 1


# ---------------------------------------------------------------------------
# 8b. Get active session for topic tests (session recovery)
# ---------------------------------------------------------------------------


class TestGetActiveSessionForTopic:
    async def test_no_active_session_returns_none(self, db):
        """When no active session exists, returns None."""
        user = _make_test_user(db)
        topic = _make_test_topic(db)
        db.add_all([user, topic])
        await db.flush()

        result = await TrainingService.get_active_session_for_topic(db, user, topic.id)
        assert result is None

    async def test_active_session_found(self, db):
        """Returns the active session when one exists."""
        user = _make_test_user(db)
        topic = _make_test_topic(db)
        db.add_all([user, topic])
        await db.flush()

        now = datetime.now(UTC)
        session = _TestTrainingSession(
            user_id=user.id,
            topic_id=topic.id,
            total_problems=5,
            problems_solved=2,
            streak_count=1,
            status="active",
            started_at=now,
        )
        db.add(session)
        await db.flush()

        result = await TrainingService.get_active_session_for_topic(db, user, topic.id)
        assert result is not None
        assert result.status == "active"
        assert result.topic_id == topic.id
        assert result.problems_solved == 2
        assert result.total_problems == 5
        assert result.streak_count == 1
        assert result.started_at is not None
        assert result.topic_name == "Dynamic Programming"

    async def test_completed_session_not_returned(self, db):
        """Completed sessions should not be returned."""
        user = _make_test_user(db)
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

        result = await TrainingService.get_active_session_for_topic(db, user, topic.id)
        assert result is None

    async def test_abandoned_session_not_returned(self, db):
        """Abandoned sessions should not be returned."""
        user = _make_test_user(db)
        topic = _make_test_topic(db)
        db.add_all([user, topic])
        await db.flush()

        session = _TestTrainingSession(
            user_id=user.id,
            topic_id=topic.id,
            total_problems=5,
            status="abandoned",
        )
        db.add(session)
        await db.flush()

        result = await TrainingService.get_active_session_for_topic(db, user, topic.id)
        assert result is None

    async def test_other_user_session_not_returned(self, db):
        """Active sessions from other users should not be returned."""
        user1 = _make_test_user(db, username="user1")
        user2 = _make_test_user(db, username="user2")
        topic = _make_test_topic(db)
        db.add_all([user1, user2, topic])
        await db.flush()

        session = _TestTrainingSession(
            user_id=user1.id,
            topic_id=topic.id,
            total_problems=5,
            status="active",
        )
        db.add(session)
        await db.flush()

        # user2 should not see user1's active session
        result = await TrainingService.get_active_session_for_topic(db, user2, topic.id)
        assert result is None

    async def test_other_topic_session_not_returned(self, db):
        """Active sessions for a different topic should not be returned."""
        user = _make_test_user(db)
        topic1 = _make_test_topic(db, name="DP", slug="dp")
        topic2 = _TestTopicCategory(
            id=uuid.uuid4(),
            name="Greedy",
            slug="greedy",
            description="Greedy topic",
            cf_tags=["greedy"],
            display_order=1,
        )
        db.add_all([user, topic1, topic2])
        await db.flush()

        session = _TestTrainingSession(
            user_id=user.id,
            topic_id=topic1.id,
            total_problems=5,
            status="active",
        )
        db.add(session)
        await db.flush()

        # Querying for topic2 should not return topic1's session
        result = await TrainingService.get_active_session_for_topic(db, user, topic2.id)
        assert result is None


# ---------------------------------------------------------------------------
# 9. Abandon training tests
# ---------------------------------------------------------------------------


class TestAbandonTraining:
    async def test_abandon_success(self, db):
        user = _make_test_user(db)
        topic = _make_test_topic(db)
        db.add_all([user, topic])
        await db.flush()

        session = _TestTrainingSession(
            user_id=user.id,
            topic_id=topic.id,
            total_problems=5,
            problems_solved=2,
            status="active",
        )
        db.add(session)
        await db.flush()

        result = await TrainingService.abandon_training(db, user, session.id)
        assert result.status == "abandoned"
        assert result.problems_solved == 2

    async def test_abandon_not_active(self, db):
        user = _make_test_user(db)
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
            await TrainingService.abandon_training(db, user, session.id)

    async def test_abandon_not_owner(self, db):
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
            await TrainingService.abandon_training(db, other, session.id)


# ---------------------------------------------------------------------------
# 10. Progress tests
# ---------------------------------------------------------------------------


class TestProgress:
    async def test_get_progress_returns_all_topics(self, db, cf_mock):
        user = _make_test_user(db)
        db.add(user)
        await db.flush()

        progress = await TrainingService.get_progress(db, user.id, cf_mock)
        assert len(progress.topics) == 12
        assert progress.total_solved == 0

    async def test_get_progress_with_solved_problems(self, db, cf_mock):
        user = _make_test_user(db)
        db.add(user)
        await db.flush()

        # Create a topic
        topics = await TrainingService.list_topics(db)
        dp_topic = next(t for t in topics if t.slug == "dp")

        # Create a completed session with solved records
        training_session = _TestTrainingSession(
            user_id=user.id,
            topic_id=dp_topic.id,
            total_problems=5,
            problems_solved=2,
            status="completed",
        )
        db.add(training_session)
        await db.flush()  # Flush to generate session.id

        # Add solved records
        record1 = _TestTrainingProblemRecord(
            session_id=training_session.id,
            user_id=user.id,
            topic_id=dp_topic.id,
            problem_id="100A",
            problem_rating=800,
            solved=True,
            attempts=1,
            time_spent=60.0,
            solved_at=datetime.now(UTC),
        )
        record2 = _TestTrainingProblemRecord(
            session_id=training_session.id,
            user_id=user.id,
            topic_id=dp_topic.id,
            problem_id="200B",
            problem_rating=1200,
            solved=True,
            attempts=2,
            time_spent=90.0,
            solved_at=datetime.now(UTC),
        )
        db.add_all([record1, record2])
        await db.flush()

        progress = await TrainingService.get_progress(db, user.id, cf_mock)
        dp_progress = next(p for p in progress.topics if p.slug == "dp")
        assert dp_progress.solved_count == 2
        assert dp_progress.total_problems == 5
        assert dp_progress.completion_rate == 40.0
        assert dp_progress.stars == 3  # M-Elo 1200 -> 3 stars
        assert dp_progress.melo == 1200.0

    async def test_get_topic_progress_not_found(self, db, cf_mock):
        user = _make_test_user(db)
        db.add(user)
        await db.flush()

        with pytest.raises(NotFoundException, match="Topic not found"):
            await TrainingService.get_topic_progress(db, user.id, uuid.uuid4(), cf_mock)

    async def test_get_topic_progress_detail(self, db, cf_mock):
        user = _make_test_user(db)
        db.add(user)
        await db.flush()

        topics = await TrainingService.list_topics(db)
        dp_topic = next(t for t in topics if t.slug == "dp")

        progress = await TrainingService.get_topic_progress(db, user.id, dp_topic.id, cf_mock)
        assert progress.topic_name == "Dynamic Programming"
        assert progress.slug == "dp"
        assert progress.solved_count == 0
        assert progress.stars == 3  # M-Elo 1200 (get_or_create_melo mock) -> 3 stars
        assert progress.melo == 1200.0


# ---------------------------------------------------------------------------
# 11. Cross-session progress tests
# ---------------------------------------------------------------------------


class TestCrossSessionProgress:
    @patch.object(training_svc_module, "PPService")
    async def test_progress_persists_across_sessions(self, mock_pp_cls, db, cf_mock):
        """Progress from a previous session should be visible in a new session."""
        mock_pp_cls.record_pp = AsyncMock()
        mock_pp_cls.calculate_overkill_multiplier = staticmethod(lambda *a, **kw: 1.0)

        user = _make_test_user(db)
        db.add(user)
        await db.flush()

        # Create topic
        topics = await TrainingService.list_topics(db)
        dp_topic = next(t for t in topics if t.slug == "dp")

        # First session - solve one problem
        session1 = _TestTrainingSession(
            user_id=user.id,
            topic_id=dp_topic.id,
            total_problems=5,
            problems_solved=1,
            status="completed",
            completed_at=datetime.now(UTC),
        )
        db.add(session1)
        await db.flush()  # Flush to generate session1.id

        record1 = _TestTrainingProblemRecord(
            session_id=session1.id,
            user_id=user.id,
            topic_id=dp_topic.id,
            problem_id="100A",
            problem_rating=800,
            solved=True,
            attempts=1,
            time_spent=60.0,
            solved_at=datetime.now(UTC),
        )
        db.add(record1)
        await db.flush()

        # Second session - solve another problem
        session2 = _TestTrainingSession(
            user_id=user.id,
            topic_id=dp_topic.id,
            total_problems=5,
            problems_solved=1,
            status="completed",
            completed_at=datetime.now(UTC),
        )
        db.add(session2)
        await db.flush()  # Flush to generate session2.id

        record2 = _TestTrainingProblemRecord(
            session_id=session2.id,
            user_id=user.id,
            topic_id=dp_topic.id,
            problem_id="200B",
            problem_rating=1200,
            solved=True,
            attempts=1,
            time_spent=90.0,
            solved_at=datetime.now(UTC),
        )
        db.add(record2)
        await db.flush()

        # Check progress shows both solves
        progress = await TrainingService.get_topic_progress(db, user.id, dp_topic.id, cf_mock)
        assert progress.solved_count == 2
        assert progress.completion_rate == 40.0
        assert progress.stars == 3  # M-Elo 1200 (get_or_create_melo mock) -> 3 stars


# ---------------------------------------------------------------------------
# 12. Token reward tests
# ---------------------------------------------------------------------------


class TestTokenRewards:
    @patch.object(training_svc_module, "PPService")
    async def test_ac_reward_correct_amount(self, mock_pp_cls, db, cf_mock):
        """Solving a problem awards the correct AC tokens."""
        mock_pp_cls.record_pp = AsyncMock()
        mock_pp_cls.calculate_overkill_multiplier = staticmethod(lambda *a, **kw: 1.0)

        user = _make_test_user(db, tokens=0)
        topic = _make_test_topic(db)
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

        # Solve a 1600 (blue) problem -> 30 tokens
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
        assert result.tokens_earned >= 30

        # Check user tokens updated
        await db.refresh(user)
        assert user.tokens >= 30

    @patch.object(training_svc_module, "PPService")
    async def test_attempt_reward_on_failure(self, mock_pp_cls, db, cf_mock):
        """Failing a problem awards attempt tokens."""
        mock_pp_cls.record_pp = AsyncMock()
        mock_pp_cls.calculate_overkill_multiplier = staticmethod(lambda *a, **kw: 1.0)

        user = _make_test_user(db, tokens=0)
        topic = _make_test_topic(db)
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

        # Fail a 1200 (green) problem -> 3 attempt tokens
        result = await TrainingService.submit_problem(
            db=db,
            user=user,
            session_id=session.id,
            problem_id="200B",
            solved=False,
            attempts=2,
            time_spent=60.0,
            cf_service=cf_mock,
        )
        assert result.tokens_earned == 3

        await db.refresh(user)
        assert user.tokens == 3

    @patch.object(training_svc_module, "PPService")
    async def test_streak_bonus_tokens(self, mock_pp_cls, db, cf_mock):
        """Streak bonus tokens are correctly calculated."""
        mock_pp_cls.record_pp = AsyncMock()
        mock_pp_cls.calculate_overkill_multiplier = staticmethod(lambda *a, **kw: 1.0)

        user = _make_test_user(db, tokens=0)
        topic = _make_test_topic(db)
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

        # Solve 800 -> streak=1, bonus=5
        r1 = await TrainingService.submit_problem(
            db=db,
            user=user,
            session_id=session.id,
            problem_id="100A",
            solved=True,
            attempts=1,
            time_spent=60.0,
            cf_service=cf_mock,
        )
        assert r1.streak_tokens == 5
        assert r1.streak_count == 1

        # Solve 1200 -> streak=2, bonus=10
        r2 = await TrainingService.submit_problem(
            db=db,
            user=user,
            session_id=session.id,
            problem_id="200B",
            solved=True,
            attempts=1,
            time_spent=60.0,
            cf_service=cf_mock,
        )
        assert r2.streak_tokens == 10
        assert r2.streak_count == 2

        # Solve 1600 -> streak=3, bonus=15
        r3 = await TrainingService.submit_problem(
            db=db,
            user=user,
            session_id=session.id,
            problem_id="300C",
            solved=True,
            attempts=1,
            time_spent=60.0,
            cf_service=cf_mock,
        )
        assert r3.streak_tokens == 15
        assert r3.streak_count == 3

        # Total: AC tokens (10+20+35=65) + streak (5+10+15=30) = 95 tokens
        await db.refresh(user)
        assert user.tokens == 10 + 20 + 35 + 5 + 10 + 15


# ---------------------------------------------------------------------------
# 13. Elo update tests
# ---------------------------------------------------------------------------


class TestEloUpdate:
    @patch.object(training_svc_module, "PPService")
    async def test_elo_increases_on_solve(self, mock_pp_cls, db, cf_mock):
        """Solving a training problem increases Elo."""
        mock_pp_cls.record_pp = AsyncMock()
        mock_pp_cls.calculate_overkill_multiplier = staticmethod(lambda *a, **kw: 1.0)

        user = _make_test_user(db, elo=1200)
        topic = _make_test_topic(db)
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

        # Solve a 1600 problem with user at 1200 elo -> should gain
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

        assert result.elo_change is not None
        assert result.elo_change > 0

        await db.refresh(user)
        assert user.elo > 1200

    @patch.object(training_svc_module, "PPService")
    async def test_no_elo_change_on_failure(self, mock_pp_cls, db, cf_mock):
        """Failing a training problem with shield active produces no Elo change."""
        mock_pp_cls.record_pp = AsyncMock()
        mock_pp_cls.calculate_overkill_multiplier = staticmethod(lambda *a, **kw: 1.0)

        user = _make_test_user(db, elo=1200)
        topic = _make_test_topic(db)
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

        # Mock shield as active so failure produces no Elo change
        training_svc_module.MEloService.is_shield_active = AsyncMock(return_value=True)

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

        # With shield active, failure should produce None elo_change
        assert result.elo_change is None

        await db.refresh(user)
        assert user.elo == 1200


# ---------------------------------------------------------------------------
# 14. Full training flow integration test
# ---------------------------------------------------------------------------


class TestFullTrainingFlow:
    """Integration test for the complete training lifecycle."""

    @patch.object(training_svc_module, "PPService")
    async def test_complete_training_flow(self, mock_pp_cls, db, cf_mock):
        mock_pp_cls.record_pp = AsyncMock()
        mock_pp_cls.calculate_overkill_multiplier = staticmethod(lambda *a, **kw: 1.0)

        # Step 1: List topics
        topics = await TrainingService.list_topics(db)
        assert len(topics) == 12

        dp_topic = next(t for t in topics if t.slug == "dp")

        # Step 2: Create user
        user = _make_test_user(db, elo=1200, tokens=0)
        db.add(user)
        await db.flush()

        # Step 3: Get topic detail
        detail = await TrainingService.get_topic_detail(db, dp_topic.id, user.id, cf_mock)
        assert detail.total_problems == 5
        assert all(not p.solved for p in detail.problems)

        # Step 4: Start training session
        session_info = await TrainingService.start_training(db, user, dp_topic.id, cf_mock)
        assert session_info.status == "active"
        session_id = session_info.id

        # Step 5: Solve problems in increasing difficulty
        # Solve 800 rating -> streak=1
        r1 = await TrainingService.submit_problem(
            db=db,
            user=user,
            session_id=session_id,
            problem_id="100A",
            solved=True,
            attempts=1,
            time_spent=60.0,
            cf_service=cf_mock,
        )
        assert r1.solved is True
        assert r1.streak_count == 1

        # Solve 1200 rating -> streak=2
        r2 = await TrainingService.submit_problem(
            db=db,
            user=user,
            session_id=session_id,
            problem_id="200B",
            solved=True,
            attempts=1,
            time_spent=120.0,
            cf_service=cf_mock,
        )
        assert r2.streak_count == 2

        # Solve 1600 rating -> streak=3
        r3 = await TrainingService.submit_problem(
            db=db,
            user=user,
            session_id=session_id,
            problem_id="300C",
            solved=True,
            attempts=1,
            time_spent=180.0,
            cf_service=cf_mock,
        )
        assert r3.streak_count == 3

        # Step 6: Check session status
        status = await TrainingService.get_session_status(db, user, session_id)
        assert status.problems_solved == 3
        assert status.streak_count == 3

        # Step 7: Abandon
        abandon_result = await TrainingService.abandon_training(db, user, session_id)
        assert abandon_result.status == "abandoned"
        assert abandon_result.problems_solved == 3

        # Step 8: Check progress
        progress = await TrainingService.get_topic_progress(db, user.id, dp_topic.id, cf_mock)
        assert progress.solved_count == 3
        assert progress.total_problems == 5
        assert progress.completion_rate == 60.0
        assert progress.stars == 3  # M-Elo 1200 (get_or_create_melo mock) -> 3 stars

        # Step 9: Verify user gained tokens and Elo
        await db.refresh(user)
        assert user.tokens > 0
        assert user.elo > 1200

        # Step 10: PP was recorded for each solve
        assert mock_pp_cls.record_pp.call_count == 3

    @patch.object(training_svc_module, "PPService")
    async def test_new_session_can_start_after_abandon(self, mock_pp_cls, db, cf_mock):
        """After abandoning a session, a new session can be started for the same topic."""
        mock_pp_cls.record_pp = AsyncMock()
        mock_pp_cls.calculate_overkill_multiplier = staticmethod(lambda *a, **kw: 1.0)

        user = _make_test_user(db)
        db.add(user)
        await db.flush()

        topics = await TrainingService.list_topics(db)
        dp_topic = next(t for t in topics if t.slug == "dp")

        # Start and abandon session 1
        s1 = await TrainingService.start_training(db, user, dp_topic.id, cf_mock)
        await TrainingService.abandon_training(db, user, s1.id)

        # Start session 2 (should succeed since session 1 is no longer active)
        s2 = await TrainingService.start_training(db, user, dp_topic.id, cf_mock)
        assert s2.status == "active"
        assert s2.id != s1.id

    @patch.object(training_svc_module, "PPService")
    async def test_new_session_can_start_after_completion(self, mock_pp_cls, db, cf_mock):
        """After a session is completed/abandoned, user can start a new one."""
        mock_pp_cls.record_pp = AsyncMock()
        mock_pp_cls.calculate_overkill_multiplier = staticmethod(lambda *a, **kw: 1.0)

        user = _make_test_user(db)
        topic = _make_test_topic(db)
        db.add_all([user, topic])
        await db.flush()

        # Manually create a completed session
        old_session = _TestTrainingSession(
            user_id=user.id,
            topic_id=topic.id,
            total_problems=5,
            problems_solved=3,
            status="completed",
            completed_at=datetime.now(UTC),
        )
        db.add(old_session)
        await db.flush()

        # Should be able to start a new session
        new_session = await TrainingService.start_training(db, user, topic.id, cf_mock)
        assert new_session.status == "active"


# ---------------------------------------------------------------------------
# 15. Edge case tests
# ---------------------------------------------------------------------------


class TestEdgeCases:
    @patch.object(training_svc_module, "PPService")
    async def test_submit_unsolved_then_solved_same_problem(self, mock_pp_cls, db, cf_mock):
        """Can re-submit a problem after failing it."""
        mock_pp_cls.record_pp = AsyncMock()
        mock_pp_cls.calculate_overkill_multiplier = staticmethod(lambda *a, **kw: 1.0)

        user = _make_test_user(db, tokens=0)
        topic = _make_test_topic(db)
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

        # First attempt: fail
        r1 = await TrainingService.submit_problem(
            db=db,
            user=user,
            session_id=session.id,
            problem_id="100A",
            solved=False,
            attempts=2,
            time_spent=60.0,
            cf_service=cf_mock,
        )
        assert r1.solved is False

        # Second attempt: solve (update the existing record)
        r2 = await TrainingService.submit_problem(
            db=db,
            user=user,
            session_id=session.id,
            problem_id="100A",
            solved=True,
            attempts=5,
            time_spent=120.0,
            cf_service=cf_mock,
        )
        assert r2.solved is True

    async def test_cf_api_failure_returns_empty_problems(self, db, cf_mock):
        """CF API failure should not crash topic detail retrieval."""
        user = _make_test_user(db)
        topic = _make_test_topic(db)
        db.add_all([user, topic])
        await db.flush()

        # Make CF API throw an exception
        cf_mock.get_problemset_problems.side_effect = Exception("CF down")

        detail = await TrainingService.get_topic_detail(db, topic.id, user.id, cf_mock)
        assert detail.total_problems == 0
        assert len(detail.problems) == 0

        # Reset mock
        cf_mock.get_problemset_problems.side_effect = None

    @patch.object(training_svc_module, "PPService")
    async def test_free_choice_any_problem(self, mock_pp_cls, db, cf_mock):
        """User can choose any problem in any order (free choice)."""
        mock_pp_cls.record_pp = AsyncMock()
        mock_pp_cls.calculate_overkill_multiplier = staticmethod(lambda *a, **kw: 1.0)

        user = _make_test_user(db, tokens=0)
        topic = _make_test_topic(db)
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

        # Solve in non-sequential order: 2000 first, then 800
        r1 = await TrainingService.submit_problem(
            db=db,
            user=user,
            session_id=session.id,
            problem_id="400D",
            solved=True,
            attempts=1,
            time_spent=180.0,
            cf_service=cf_mock,
        )
        assert r1.solved is True
        assert r1.streak_count == 1  # First AC

        # Solve 800 after 2000 (decreasing) -> streak continues (every AC counts)
        r2 = await TrainingService.submit_problem(
            db=db,
            user=user,
            session_id=session.id,
            problem_id="100A",
            solved=True,
            attempts=1,
            time_spent=60.0,
            cf_service=cf_mock,
        )
        assert r2.solved is True
        assert r2.streak_count == 2  # Second consecutive AC


# ---------------------------------------------------------------------------
# 16. Adaptive problem recommendation tests
# ---------------------------------------------------------------------------


class _FakeMEloRecord:
    """Minimal stand-in for a UserTagElo ORM object."""

    def __init__(self, elo: int = 1200, tag: str = "dp"):
        self.elo = elo
        self.tag = tag
        self.total_submissions = 0
        self.first_ac_at = None


class TestAdaptiveRecommendation:
    """Tests for TrainingService.get_adaptive_problem."""

    async def test_recommend_uses_melo_not_global_elo(self, db, cf_mock):
        """Recommended problem rating should be based on M-Elo, not Global Elo."""
        user = _make_test_user(db, elo=1000)  # Global Elo = 1000
        topic = _make_test_topic(db)
        db.add_all([user, topic])
        await db.flush()

        # M-Elo is 1500, far from Global Elo of 1000
        fake_melo = _FakeMEloRecord(elo=1500, tag="dp")

        with patch.object(training_svc_module, "MEloService") as mock_melo_cls:
            mock_melo_cls.get_or_create_melo = AsyncMock(return_value=fake_melo)
            result = await TrainingService.get_adaptive_problem(db, user, topic.id, cf_mock)

        assert result is not None
        assert result.melo == 1500
        # With M-Elo=1500, base range is [1400, 1700]
        # The only problem in that range from cf_mock is 1600 (contestId=300, index=C)
        assert result.rating == 1600

    async def test_base_range_correct(self, db, cf_mock):
        """Base range is [M-Elo - 100, M-Elo + 200]."""
        user = _make_test_user(db, elo=1200)
        topic = _make_test_topic(db)
        db.add_all([user, topic])
        await db.flush()

        # M-Elo = 1000, base range = [900, 1200]
        fake_melo = _FakeMEloRecord(elo=1000, tag="dp")

        with patch.object(training_svc_module, "MEloService") as mock_melo_cls:
            mock_melo_cls.get_or_create_melo = AsyncMock(return_value=fake_melo)
            result = await TrainingService.get_adaptive_problem(db, user, topic.id, cf_mock)

        assert result is not None
        lo, hi = result.search_range
        assert lo == 900  # 1000 - 100
        assert hi == 1200  # 1000 + 200
        assert 900 <= result.rating <= 1200

    async def test_fallback_round_1(self, db, cf_mock):
        """When base range has no match, fallback round 1 expands to [M-Elo - 200, M-Elo + 300]."""
        user = _make_test_user(db, elo=1200)
        topic = _make_test_topic(db)
        db.add_all([user, topic])
        await db.flush()

        # M-Elo = 500 -- base range [400, 700], round 1 = [300, 800]
        # Only 800-rating problem exists, so round 1 should find it
        fake_melo = _FakeMEloRecord(elo=500, tag="dp")

        with patch.object(training_svc_module, "MEloService") as mock_melo_cls:
            mock_melo_cls.get_or_create_melo = AsyncMock(return_value=fake_melo)
            result = await TrainingService.get_adaptive_problem(db, user, topic.id, cf_mock)

        assert result is not None
        lo, hi = result.search_range
        assert lo == 300  # 500 - 200
        assert hi == 800  # 500 + 300
        assert result.rating == 800

    async def test_fallback_round_2(self, db, cf_mock):
        """When round 1 has no match, round 2 expands to [M-Elo - 300, M-Elo + 400]."""
        # Provide a single problem far from M-Elo
        cf_mock.get_problemset_problems.return_value = {
            "problems": [
                {"contestId": 999, "index": "Z", "name": "Far Problem", "rating": 3000, "tags": ["dp"]},
            ],
        }

        user = _make_test_user(db, elo=1200)
        topic = _make_test_topic(db)
        db.add_all([user, topic])
        await db.flush()

        # M-Elo = 1000: base [900,1200], round1 [800,1300], round2 [700,1400]
        # None contain 3000, but [700,1400] doesn't either. Need to go wider.
        # Actually 3000 is way above. Let me test with a closer problem.
        # M-Elo = 2600: base [2500,2800], round1 [2400,2900], round2 [2300,3000]
        fake_melo = _FakeMEloRecord(elo=2600, tag="dp")

        with patch.object(training_svc_module, "MEloService") as mock_melo_cls:
            mock_melo_cls.get_or_create_melo = AsyncMock(return_value=fake_melo)
            result = await TrainingService.get_adaptive_problem(db, user, topic.id, cf_mock)

        assert result is not None
        lo, hi = result.search_range
        assert lo == 2300  # 2600 - 300
        assert hi == 3000  # 2600 + 400
        assert result.rating == 3000

    async def test_returns_none_when_no_problem_found(self, db, cf_mock):
        """Returns None when all rounds fail to find a match."""
        # All problems are at 800-2400, but M-Elo is extremely high
        user = _make_test_user(db, elo=1200)
        topic = _make_test_topic(db)
        db.add_all([user, topic])
        await db.flush()

        # M-Elo = 5000, max round range = [4700, 5400]
        fake_melo = _FakeMEloRecord(elo=5000, tag="dp")

        with patch.object(training_svc_module, "MEloService") as mock_melo_cls:
            mock_melo_cls.get_or_create_melo = AsyncMock(return_value=fake_melo)
            result = await TrainingService.get_adaptive_problem(db, user, topic.id, cf_mock)

        assert result is None

    async def test_filters_solved_problems(self, db, cf_mock):
        """Already-solved problems should not be recommended."""
        user = _make_test_user(db, elo=1200)
        topic = _make_test_topic(db)
        db.add_all([user, topic])
        await db.flush()

        # Mark problem "200B" (rating 1200) as solved
        session_id = uuid.uuid4()
        session = _TestTrainingSession(
            id=session_id,
            user_id=user.id,
            topic_id=topic.id,
            total_problems=5,
            status="completed",
        )
        db.add(session)
        record = _TestTrainingProblemRecord(
            session_id=session_id,
            user_id=user.id,
            topic_id=topic.id,
            problem_id="200B",
            problem_rating=1200,
            solved=True,
            attempts=1,
            time_spent=60.0,
            solved_at=datetime.now(UTC),
        )
        db.add(record)
        await db.flush()

        # M-Elo = 1000, range = [900, 1200]
        # "200B" (1200) is solved, "100A" (800) is out of range
        # So there should be NO problems in the base range
        fake_melo = _FakeMEloRecord(elo=1000, tag="dp")

        with patch.object(training_svc_module, "MEloService") as mock_melo_cls:
            mock_melo_cls.get_or_create_melo = AsyncMock(return_value=fake_melo)
            result = await TrainingService.get_adaptive_problem(db, user, topic.id, cf_mock)

        # Should fall through to round 1 [800, 1300] which has "100A" (800)
        assert result is not None
        assert result.problem_id != "200B"
        assert result.rating == 800  # Only unsolved in round 1 range

    async def test_melo_dynamic_after_update(self, db, cf_mock):
        """After M-Elo changes, the recommended problem range follows."""
        user = _make_test_user(db, elo=1200)
        topic = _make_test_topic(db)
        db.add_all([user, topic])
        await db.flush()

        # First call with M-Elo = 1000
        fake_melo_low = _FakeMEloRecord(elo=1000, tag="dp")
        with patch.object(training_svc_module, "MEloService") as mock_melo_cls:
            mock_melo_cls.get_or_create_melo = AsyncMock(return_value=fake_melo_low)
            result_low = await TrainingService.get_adaptive_problem(db, user, topic.id, cf_mock)

        assert result_low is not None
        assert result_low.melo == 1000
        assert 900 <= result_low.rating <= 1200  # base range

        # Second call with M-Elo = 1800 (simulating improvement)
        fake_melo_high = _FakeMEloRecord(elo=1800, tag="dp")
        with patch.object(training_svc_module, "MEloService") as mock_melo_cls:
            mock_melo_cls.get_or_create_melo = AsyncMock(return_value=fake_melo_high)
            result_high = await TrainingService.get_adaptive_problem(db, user, topic.id, cf_mock)

        assert result_high is not None
        assert result_high.melo == 1800
        assert 1700 <= result_high.rating <= 2000  # base range

    async def test_topic_not_found_raises(self, db, cf_mock):
        """Non-existent topic raises NotFoundException."""
        user = _make_test_user(db)
        db.add(user)
        await db.flush()

        with pytest.raises(NotFoundException, match="Topic not found"):
            await TrainingService.get_adaptive_problem(db, user, uuid.uuid4(), cf_mock)

    async def test_returns_none_when_no_cf_problems(self, db, cf_mock):
        """Returns None when CF API returns empty problems."""
        cf_mock.get_problemset_problems.return_value = {"problems": []}

        user = _make_test_user(db, elo=1200)
        topic = _make_test_topic(db)
        db.add_all([user, topic])
        await db.flush()

        fake_melo = _FakeMEloRecord(elo=1200, tag="dp")
        with patch.object(training_svc_module, "MEloService") as mock_melo_cls:
            mock_melo_cls.get_or_create_melo = AsyncMock(return_value=fake_melo)
            result = await TrainingService.get_adaptive_problem(db, user, topic.id, cf_mock)

        assert result is None

    async def test_returns_none_when_all_problems_solved(self, db, cf_mock):
        """Returns None when all problems in the topic are already solved."""
        user = _make_test_user(db, elo=1200)
        topic = _make_test_topic(db)
        db.add_all([user, topic])
        await db.flush()

        # Mark all problems as solved
        session_id = uuid.uuid4()
        session = _TestTrainingSession(
            id=session_id,
            user_id=user.id,
            topic_id=topic.id,
            total_problems=5,
            status="completed",
        )
        db.add(session)
        for pid in ["100A", "200B", "300C", "400D", "500E"]:
            record = _TestTrainingProblemRecord(
                session_id=session_id,
                user_id=user.id,
                topic_id=topic.id,
                problem_id=pid,
                problem_rating=800,
                solved=True,
                attempts=1,
                time_spent=60.0,
                solved_at=datetime.now(UTC),
            )
            db.add(record)
        await db.flush()

        fake_melo = _FakeMEloRecord(elo=1200, tag="dp")
        with patch.object(training_svc_module, "MEloService") as mock_melo_cls:
            mock_melo_cls.get_or_create_melo = AsyncMock(return_value=fake_melo)
            result = await TrainingService.get_adaptive_problem(db, user, topic.id, cf_mock)

        assert result is None

    async def test_topic_with_no_cf_tags_returns_none(self, db, cf_mock):
        """A topic with empty cf_tags returns None immediately."""
        user = _make_test_user(db, elo=1200)
        # Manually create topic with empty cf_tags (bypassing the "or" default)
        topic = _TestTopicCategory(
            id=uuid.uuid4(),
            name="No Tags Topic",
            slug="no_tags_topic",
            description="A topic without CF tags",
            cf_tags=[],
            display_order=99,
        )
        db.add_all([user, topic])
        await db.flush()

        fake_melo = _FakeMEloRecord(elo=1200, tag="dp")
        with patch.object(training_svc_module, "MEloService") as mock_melo_cls:
            mock_melo_cls.get_or_create_melo = AsyncMock(return_value=fake_melo)
            result = await TrainingService.get_adaptive_problem(db, user, topic.id, cf_mock)

        assert result is None

    async def test_filters_problems_without_rating(self, db, cf_mock):
        """Problems without a rating field are excluded from recommendation."""
        cf_mock.get_problemset_problems.return_value = {
            "problems": [
                {"contestId": 100, "index": "A", "name": "No Rating", "tags": ["dp"]},  # no rating
                {"contestId": 200, "index": "B", "name": "Has Rating", "rating": 1200, "tags": ["dp"]},
            ],
        }

        user = _make_test_user(db, elo=1200)
        topic = _make_test_topic(db)
        db.add_all([user, topic])
        await db.flush()

        fake_melo = _FakeMEloRecord(elo=1000, tag="dp")
        with patch.object(training_svc_module, "MEloService") as mock_melo_cls:
            mock_melo_cls.get_or_create_melo = AsyncMock(return_value=fake_melo)
            result = await TrainingService.get_adaptive_problem(db, user, topic.id, cf_mock)

        assert result is not None
        assert result.problem_id == "200B"
        assert result.rating == 1200

    async def test_response_schema_fields_populated(self, db, cf_mock):
        """Response includes all expected fields with correct values."""
        user = _make_test_user(db, elo=1200)
        topic = _make_test_topic(db)
        db.add_all([user, topic])
        await db.flush()

        fake_melo = _FakeMEloRecord(elo=1100, tag="dp")
        with patch.object(training_svc_module, "MEloService") as mock_melo_cls:
            mock_melo_cls.get_or_create_melo = AsyncMock(return_value=fake_melo)
            result = await TrainingService.get_adaptive_problem(db, user, topic.id, cf_mock)

        assert result is not None
        assert isinstance(result, RecommendedProblemResponse)
        assert result.problem_id is not None
        assert result.contest_id > 0
        assert result.index != ""
        assert result.name != ""
        assert result.rating is not None
        assert result.tags == ["dp"]
        assert "codeforces.com" in result.url
        assert result.melo == 1100
        assert len(result.search_range) == 2
