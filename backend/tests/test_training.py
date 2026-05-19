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
from app.services import training_service as training_svc_module
from app.services.training_service import (
    TrainingService,
    _attempt_tokens_for_rating,
    _tokens_for_rating,
    calculate_stars,
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


@pytest.fixture
async def db(async_engine):
    """Provide an async session with patched model references."""
    session_factory = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as session:
        with (
            patch.object(training_svc_module, "User", _TestUser),
            patch.object(training_svc_module, "TopicCategory", _TestTopicCategory),
            patch.object(training_svc_module, "TrainingSession", _TestTrainingSession),
            patch.object(training_svc_module, "TrainingProblemRecord", _TestTrainingProblemRecord),
            patch.object(training_svc_module, "TokenTransaction", _TestTokenTransaction),
            patch.object(training_svc_module, "EloHistory", _TestEloHistory),
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


# ---------------------------------------------------------------------------
# 2. Token tier tests
# ---------------------------------------------------------------------------


class TestTokenTiers:
    def test_ac_tokens_gray(self):
        assert _tokens_for_rating(800) == 10
        assert _tokens_for_rating(1099) == 10

    def test_ac_tokens_green(self):
        assert _tokens_for_rating(1100) == 20
        assert _tokens_for_rating(1399) == 20

    def test_ac_tokens_blue(self):
        assert _tokens_for_rating(1400) == 30
        assert _tokens_for_rating(1699) == 30

    def test_ac_tokens_purple(self):
        assert _tokens_for_rating(1700) == 40
        assert _tokens_for_rating(1999) == 40

    def test_ac_tokens_yellow_red(self):
        assert _tokens_for_rating(2000) == 50
        assert _tokens_for_rating(3000) == 50

    def test_attempt_tokens_gray(self):
        assert _attempt_tokens_for_rating(800) == 2
        assert _attempt_tokens_for_rating(1099) == 2

    def test_attempt_tokens_green(self):
        assert _attempt_tokens_for_rating(1100) == 3

    def test_attempt_tokens_blue(self):
        assert _attempt_tokens_for_rating(1400) == 4

    def test_attempt_tokens_purple(self):
        assert _attempt_tokens_for_rating(1700) == 5

    def test_attempt_tokens_yellow_red(self):
        assert _attempt_tokens_for_rating(2000) == 6


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
            "dp", "greedy", "math", "graphs", "strings", "data_structures",
            "binary_search", "sorting", "constructive", "number_theory", "trees", "geometry",
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
        assert result.elo_change is None

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
            db=db, user=user, session_id=session.id,
            problem_id="100A", solved=True, attempts=1, time_spent=60.0,
            cf_service=cf_mock,
        )

        # Second submission (already solved)
        with pytest.raises(BadRequestException, match="already solved"):
            await TrainingService.submit_problem(
                db=db, user=user, session_id=session.id,
                problem_id="100A", solved=True, attempts=2, time_spent=30.0,
                cf_service=cf_mock,
            )

    async def test_submit_session_not_found(self, db, cf_mock):
        user = _make_test_user(db)
        db.add(user)
        await db.flush()

        with pytest.raises(NotFoundException, match="Training session not found"):
            await TrainingService.submit_problem(
                db=db, user=user, session_id=uuid.uuid4(),
                problem_id="100A", solved=True, attempts=1, time_spent=60.0,
                cf_service=cf_mock,
            )


# ---------------------------------------------------------------------------
# 8. Streak tests
# ---------------------------------------------------------------------------


class TestStreakMechanism:
    @patch.object(training_svc_module, "PPService")
    async def test_streak_increases_on_higher_rating(self, mock_pp_cls, db, cf_mock):
        """Solving a harder problem after an easier one triggers a streak."""
        mock_pp_cls.record_pp = AsyncMock()

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

        # Solve 800 rating problem
        result1 = await TrainingService.submit_problem(
            db=db, user=user, session_id=session.id,
            problem_id="100A", solved=True, attempts=1, time_spent=60.0,
            cf_service=cf_mock,
        )
        assert result1.streak_count == 0  # First solve, no streak yet

        # Solve 1200 rating problem (higher) -> streak
        result2 = await TrainingService.submit_problem(
            db=db, user=user, session_id=session.id,
            problem_id="200B", solved=True, attempts=1, time_spent=120.0,
            cf_service=cf_mock,
        )
        assert result2.streak_count == 1  # Streak = 1
        assert result2.streak_tokens == 1 * 5  # 1 * 5 = 5 tokens

    @patch.object(training_svc_module, "PPService")
    async def test_streak_resets_on_lower_rating(self, mock_pp_cls, db, cf_mock):
        """Solving an easier problem after a harder one breaks the streak."""
        mock_pp_cls.record_pp = AsyncMock()

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

        # Solve 1200 rating problem
        await TrainingService.submit_problem(
            db=db, user=user, session_id=session.id,
            problem_id="200B", solved=True, attempts=1, time_spent=120.0,
            cf_service=cf_mock,
        )

        # Solve 800 rating problem (lower) -> streak breaks
        result = await TrainingService.submit_problem(
            db=db, user=user, session_id=session.id,
            problem_id="100A", solved=True, attempts=1, time_spent=60.0,
            cf_service=cf_mock,
        )
        assert result.streak_count == 0

    @patch.object(training_svc_module, "PPService")
    async def test_streak_resets_on_same_rating(self, mock_pp_cls, db, cf_mock):
        """Solving same rating problem breaks the streak (not >)."""
        mock_pp_cls.record_pp = AsyncMock()

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

        # Solve first 800
        await TrainingService.submit_problem(
            db=db, user=user, session_id=session.id,
            problem_id="100A", solved=True, attempts=1, time_spent=60.0,
            cf_service=cf_mock,
        )

        # Solve another 800 (same rating) -> streak breaks
        result = await TrainingService.submit_problem(
            db=db, user=user, session_id=session.id,
            problem_id="100B", solved=True, attempts=1, time_spent=60.0,
            cf_service=cf_mock,
        )
        assert result.streak_count == 0

    @patch.object(training_svc_module, "PPService")
    async def test_streak_token_cap(self, mock_pp_cls, db, cf_mock):
        """Streak tokens are capped at 50 per session."""
        mock_pp_cls.record_pp = AsyncMock()

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

        # Solve in increasing order: 800 -> 1200 -> 1600 -> 2000 -> 2400
        problems = [
            ("100A", 800), ("200B", 1200), ("300C", 1600), ("400D", 2000), ("500E", 2400),
        ]
        total_streak_tokens = 0
        for pid, _rating in problems:
            result = await TrainingService.submit_problem(
                db=db, user=user, session_id=session.id,
                problem_id=pid, solved=True, attempts=1, time_spent=60.0,
                cf_service=cf_mock,
            )
            total_streak_tokens = result.total_streak_tokens

        # Maximum streak = 4 (4 increases: 1200>800, 1600>1200, 2000>1600, 2400>2000)
        # Streak bonus at streak=4 would be 4*5=20, which is under the 50 cap
        # Total accumulated should not exceed 50
        assert total_streak_tokens <= 50

    @patch.object(training_svc_module, "PPService")
    async def test_streak_interrupted_by_unsolved(self, mock_pp_cls, db, cf_mock):
        """Submitting an unsolved result doesn't affect streak directly,
        but the next solved with non-increasing rating breaks it."""
        mock_pp_cls.record_pp = AsyncMock()

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

        # Solve 800
        await TrainingService.submit_problem(
            db=db, user=user, session_id=session.id,
            problem_id="100A", solved=True, attempts=1, time_spent=60.0,
            cf_service=cf_mock,
        )

        # Fail on 1200
        await TrainingService.submit_problem(
            db=db, user=user, session_id=session.id,
            problem_id="200B", solved=False, attempts=3, time_spent=120.0,
            cf_service=cf_mock,
        )

        # Now solve 1200 (same as failed) - streak should still check last solved
        result = await TrainingService.submit_problem(
            db=db, user=user, session_id=session.id,
            problem_id="200B", solved=True, attempts=5, time_spent=180.0,
            cf_service=cf_mock,
        )
        # 1200 > 800 (last solved rating) so streak should continue
        assert result.streak_count >= 1


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
        assert dp_progress.stars == 2  # 40% -> 2 stars

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
        assert progress.stars == 0


# ---------------------------------------------------------------------------
# 11. Cross-session progress tests
# ---------------------------------------------------------------------------


class TestCrossSessionProgress:
    @patch.object(training_svc_module, "PPService")
    async def test_progress_persists_across_sessions(self, mock_pp_cls, db, cf_mock):
        """Progress from a previous session should be visible in a new session."""
        mock_pp_cls.record_pp = AsyncMock()

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
        assert progress.stars == 2


# ---------------------------------------------------------------------------
# 12. Token reward tests
# ---------------------------------------------------------------------------


class TestTokenRewards:
    @patch.object(training_svc_module, "PPService")
    async def test_ac_reward_correct_amount(self, mock_pp_cls, db, cf_mock):
        """Solving a problem awards the correct AC tokens."""
        mock_pp_cls.record_pp = AsyncMock()

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
            db=db, user=user, session_id=session.id,
            problem_id="300C", solved=True, attempts=1, time_spent=120.0,
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
            db=db, user=user, session_id=session.id,
            problem_id="200B", solved=False, attempts=2, time_spent=60.0,
            cf_service=cf_mock,
        )
        assert result.tokens_earned == 3

        await db.refresh(user)
        assert user.tokens == 3

    @patch.object(training_svc_module, "PPService")
    async def test_streak_bonus_tokens(self, mock_pp_cls, db, cf_mock):
        """Streak bonus tokens are correctly calculated."""
        mock_pp_cls.record_pp = AsyncMock()

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

        # Solve 800 -> no streak
        r1 = await TrainingService.submit_problem(
            db=db, user=user, session_id=session.id,
            problem_id="100A", solved=True, attempts=1, time_spent=60.0,
            cf_service=cf_mock,
        )
        assert r1.streak_tokens == 0

        # Solve 1200 -> streak=1, bonus=5
        r2 = await TrainingService.submit_problem(
            db=db, user=user, session_id=session.id,
            problem_id="200B", solved=True, attempts=1, time_spent=60.0,
            cf_service=cf_mock,
        )
        assert r2.streak_tokens == 5
        assert r2.streak_count == 1

        # Solve 1600 -> streak=2, bonus=10
        r3 = await TrainingService.submit_problem(
            db=db, user=user, session_id=session.id,
            problem_id="300C", solved=True, attempts=1, time_spent=60.0,
            cf_service=cf_mock,
        )
        assert r3.streak_tokens == 10
        assert r3.streak_count == 2

        # Total: 10 + 20 + 30 + 5 + 10 = 75 tokens (AC: 10+20+30=60, streak: 5+10=15)
        await db.refresh(user)
        assert user.tokens == 10 + 20 + 30 + 5 + 10


# ---------------------------------------------------------------------------
# 13. Elo update tests
# ---------------------------------------------------------------------------


class TestEloUpdate:
    @patch.object(training_svc_module, "PPService")
    async def test_elo_increases_on_solve(self, mock_pp_cls, db, cf_mock):
        """Solving a training problem increases Elo."""
        mock_pp_cls.record_pp = AsyncMock()

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
            db=db, user=user, session_id=session.id,
            problem_id="300C", solved=True, attempts=1, time_spent=120.0,
            cf_service=cf_mock,
        )

        assert result.elo_change is not None
        assert result.elo_change > 0

        await db.refresh(user)
        assert user.elo > 1200

    @patch.object(training_svc_module, "PPService")
    async def test_no_elo_change_on_failure(self, mock_pp_cls, db, cf_mock):
        """Failing a training problem does not change Elo."""
        mock_pp_cls.record_pp = AsyncMock()

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

        result = await TrainingService.submit_problem(
            db=db, user=user, session_id=session.id,
            problem_id="300C", solved=False, attempts=3, time_spent=120.0,
            cf_service=cf_mock,
        )

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
        # Solve 800 rating
        r1 = await TrainingService.submit_problem(
            db=db, user=user, session_id=session_id,
            problem_id="100A", solved=True, attempts=1, time_spent=60.0,
            cf_service=cf_mock,
        )
        assert r1.solved is True

        # Solve 1200 rating (streak)
        r2 = await TrainingService.submit_problem(
            db=db, user=user, session_id=session_id,
            problem_id="200B", solved=True, attempts=1, time_spent=120.0,
            cf_service=cf_mock,
        )
        assert r2.streak_count == 1

        # Solve 1600 rating (streak continues)
        r3 = await TrainingService.submit_problem(
            db=db, user=user, session_id=session_id,
            problem_id="300C", solved=True, attempts=1, time_spent=180.0,
            cf_service=cf_mock,
        )
        assert r3.streak_count == 2

        # Step 6: Check session status
        status = await TrainingService.get_session_status(db, user, session_id)
        assert status.problems_solved == 3
        assert status.streak_count == 2

        # Step 7: Abandon
        abandon_result = await TrainingService.abandon_training(db, user, session_id)
        assert abandon_result.status == "abandoned"
        assert abandon_result.problems_solved == 3

        # Step 8: Check progress
        progress = await TrainingService.get_topic_progress(db, user.id, dp_topic.id, cf_mock)
        assert progress.solved_count == 3
        assert progress.total_problems == 5
        assert progress.completion_rate == 60.0
        assert progress.stars == 3  # 60% -> 3 stars

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
            db=db, user=user, session_id=session.id,
            problem_id="100A", solved=False, attempts=2, time_spent=60.0,
            cf_service=cf_mock,
        )
        assert r1.solved is False

        # Second attempt: solve (update the existing record)
        r2 = await TrainingService.submit_problem(
            db=db, user=user, session_id=session.id,
            problem_id="100A", solved=True, attempts=5, time_spent=120.0,
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
            db=db, user=user, session_id=session.id,
            problem_id="400D", solved=True, attempts=1, time_spent=180.0,
            cf_service=cf_mock,
        )
        assert r1.solved is True

        # Solve 800 after 2000 (decreasing) -> streak breaks
        r2 = await TrainingService.submit_problem(
            db=db, user=user, session_id=session.id,
            problem_id="100A", solved=True, attempts=1, time_spent=60.0,
            cf_service=cf_mock,
        )
        assert r2.solved is True
        assert r2.streak_count == 0  # Streak broken (800 < 2000)
