"""Integration test: training full flow.

Tests topic listing, session creation, problem submission,
streak tracking, and token/PP rewards.
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from .conftest import (
    create_test_topic,
    create_test_user,
    make_cf_problems_response,
    mock_cf_service,
)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestTrainingTopicList:
    """Test topic listing."""

    async def test_list_topics_returns_predefined(self, db_session):
        """list_topics creates and returns predefined topics."""
        from app.services.training_service import TrainingService

        topics = await TrainingService.list_topics(db_session)
        assert len(topics) > 0

        names = [t.name for t in topics]
        assert "Dynamic Programming" in names
        assert "Greedy" in names
        assert "Math" in names

    async def test_list_topics_with_user_shows_solved_count(self, db_session):
        """list_topics with user_id shows solved count per topic."""
        user = await create_test_user(db_session)
        await db_session.commit()

        from app.services.training_service import TrainingService

        topics = await TrainingService.list_topics(db_session, user_id=user.id)
        for t in topics:
            assert t.solved_count == 0  # new user, no solved problems


class TestTrainingStart:
    """Test starting training sessions."""

    async def test_start_training_creates_session(self, db_session):
        """Starting training creates a new session."""
        user = await create_test_user(db_session)
        topic = await create_test_topic(db_session)
        await db_session.commit()

        from app.services.training_service import TrainingService

        cf = mock_cf_service(make_cf_problems_response(count=5))

        result = await TrainingService.start_training(db_session, user, topic.id, cf)
        assert result.status == "active"
        assert str(result.topic_id) == topic.id
        assert result.topic_name == topic.name
        assert result.problems_solved == 0

    async def test_cannot_start_two_sessions_for_same_topic(self, db_session):
        """User cannot start two active sessions for the same topic."""
        user = await create_test_user(db_session)
        topic = await create_test_topic(db_session)
        await db_session.commit()

        from app.services.training_service import TrainingService

        cf = mock_cf_service(make_cf_problems_response(count=5))

        await TrainingService.start_training(db_session, user, topic.id, cf)

        with pytest.raises(Exception, match="Already have an active"):
            await TrainingService.start_training(db_session, user, topic.id, cf)

    async def test_start_training_nonexistent_topic_fails(self, db_session):
        """Starting training with invalid topic ID raises NotFoundException."""
        user = await create_test_user(db_session)
        await db_session.commit()

        from app.services.training_service import TrainingService

        cf = mock_cf_service()
        with pytest.raises(Exception, match="Topic not found"):
            await TrainingService.start_training(
                db_session, user, uuid.uuid4(), cf
            )


class TestTrainingSubmit:
    """Test submitting problem results in training."""

    async def test_submit_solved_awards_tokens_and_pp(self, db_session):
        """Solving a problem awards tokens and PP."""
        user = await create_test_user(db_session)
        topic = await create_test_topic(db_session)
        await db_session.commit()

        from app.services.training_service import TrainingService

        cf = mock_cf_service(make_cf_problems_response(count=5, base_rating=1200))

        session_info = await TrainingService.start_training(db_session, user, topic.id, cf)

        result = await TrainingService.submit_problem(
            db_session, user, session_info.id,
            problem_id="1000A", solved=True, attempts=1, time_spent=300.0,
            cf_service=cf,
        )
        assert result.solved is True
        assert result.tokens_earned > 0

        await db_session.refresh(user)
        assert user.tokens > 0
        assert user.pp > 0

    async def test_submit_unsolved_awards_attempt_tokens(self, db_session):
        """Failing to solve awards smaller attempt tokens."""
        user = await create_test_user(db_session)
        topic = await create_test_topic(db_session)
        await db_session.commit()

        from app.services.training_service import TrainingService

        cf = mock_cf_service(make_cf_problems_response(count=5, base_rating=1200))

        session_info = await TrainingService.start_training(db_session, user, topic.id, cf)

        result = await TrainingService.submit_problem(
            db_session, user, session_info.id,
            problem_id="1000A", solved=False, attempts=3, time_spent=600.0,
            cf_service=cf,
        )
        assert result.solved is False
        assert result.tokens_earned > 0  # attempt tokens

    async def test_streak_continues_with_increasing_difficulty(self, db_session):
        """Solving harder problems in sequence builds a streak."""
        user = await create_test_user(db_session)
        topic = await create_test_topic(db_session)
        await db_session.commit()

        from app.services.training_service import TrainingService

        cf = mock_cf_service(make_cf_problems_response(count=10, base_rating=1000))

        session_info = await TrainingService.start_training(db_session, user, topic.id, cf)

        # Solve problem at rating 1000
        r1 = await TrainingService.submit_problem(
            db_session, user, session_info.id,
            problem_id="1000A", solved=True, attempts=1, time_spent=100.0,
            cf_service=cf,
        )
        assert r1.solved is True

        # Solve problem at rating 1100 (higher)
        r2 = await TrainingService.submit_problem(
            db_session, user, session_info.id,
            problem_id="1001B", solved=True, attempts=1, time_spent=200.0,
            cf_service=cf,
        )
        assert r2.solved is True
        assert r2.streak_count >= 1  # streak continued

    async def test_elo_updates_on_solve(self, db_session):
        """Solving a problem in training gives a small Elo gain."""
        user = await create_test_user(db_session, elo=1200)
        topic = await create_test_topic(db_session)
        await db_session.commit()

        from app.services.training_service import TrainingService

        cf = mock_cf_service(make_cf_problems_response(count=5, base_rating=1500))

        session_info = await TrainingService.start_training(db_session, user, topic.id, cf)

        result = await TrainingService.submit_problem(
            db_session, user, session_info.id,
            problem_id="1000A", solved=True, attempts=1, time_spent=300.0,
            cf_service=cf,
        )
        assert result.elo_change is not None
        assert result.elo_change > 0  # solving should increase Elo

        await db_session.refresh(user)
        assert user.elo > 1200

    async def test_cannot_solve_same_problem_twice(self, db_session):
        """Cannot solve the same problem twice in one session."""
        user = await create_test_user(db_session)
        topic = await create_test_topic(db_session)
        await db_session.commit()

        from app.services.training_service import TrainingService

        cf = mock_cf_service(make_cf_problems_response(count=5, base_rating=1000))

        session_info = await TrainingService.start_training(db_session, user, topic.id, cf)

        await TrainingService.submit_problem(
            db_session, user, session_info.id,
            problem_id="1000A", solved=True, attempts=1, time_spent=100.0,
            cf_service=cf,
        )

        with pytest.raises(Exception, match="already solved"):
            await TrainingService.submit_problem(
                db_session, user, session_info.id,
                problem_id="1000A", solved=True, attempts=1, time_spent=100.0,
                cf_service=cf,
            )


class TestTrainingAbandon:
    """Test abandoning training sessions."""

    async def test_abandon_marks_session_abandoned(self, db_session):
        """Abandoning an active session sets status to abandoned."""
        user = await create_test_user(db_session)
        topic = await create_test_topic(db_session)
        await db_session.commit()

        from app.services.training_service import TrainingService

        cf = mock_cf_service(make_cf_problems_response(count=5))
        session_info = await TrainingService.start_training(db_session, user, topic.id, cf)

        result = await TrainingService.abandon_training(db_session, user, session_info.id)
        assert result.status == "abandoned"

    async def test_cannot_abandon_already_abandoned(self, db_session):
        """Cannot abandon a session that is already abandoned."""
        user = await create_test_user(db_session)
        topic = await create_test_topic(db_session)
        await db_session.commit()

        from app.services.training_service import TrainingService

        cf = mock_cf_service(make_cf_problems_response(count=5))
        session_info = await TrainingService.start_training(db_session, user, topic.id, cf)

        await TrainingService.abandon_training(db_session, user, session_info.id)

        with pytest.raises(Exception, match="not active"):
            await TrainingService.abandon_training(db_session, user, session_info.id)


class TestTrainingSessionStatus:
    """Test getting session status."""

    async def test_get_session_status(self, db_session):
        """Can retrieve session status after starting."""
        user = await create_test_user(db_session)
        topic = await create_test_topic(db_session)
        await db_session.commit()

        from app.services.training_service import TrainingService

        cf = mock_cf_service(make_cf_problems_response(count=5))
        session_info = await TrainingService.start_training(db_session, user, topic.id, cf)

        status = await TrainingService.get_session_status(db_session, user, session_info.id)
        assert status.status == "active"
        assert status.topic_name == topic.name
        assert status.problems_solved == 0
