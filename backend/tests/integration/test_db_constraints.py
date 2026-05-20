"""Integration tests: PostgreSQL-specific database constraints.

Tests ForeignKey constraints, Unique constraints, server_default values,
and basic CRUD for models that have zero test coverage.
"""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.challenge_session import ChallengeSession
from app.models.contest_bot import ContestBot
from app.models.contest_session import ContestSession
from app.models.pve_challenge_session import PvEChallengeSession
from app.models.submission_tracking import SubmissionTracking
from app.models.user import User
from app.models.user_tag_elo import UserTagElo

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _make_user(db: AsyncSession, suffix: str = "") -> User:
    """Create and return a fresh user with a unique username/email."""
    uid = uuid.uuid4().hex[:8]
    user = User(
        username=f"u_{uid}{suffix}",
        email=f"{uid}{suffix}@test.com",
        password_hash="$2b$12$fakehash",
    )
    db.add(user)
    await db.flush()
    return user


# ---------------------------------------------------------------------------
# ForeignKey constraint tests
# ---------------------------------------------------------------------------


class TestForeignKeyConstraints:
    """Verify PostgreSQL enforces FK constraints on real tables."""

    async def test_challenge_session_challenger_fk(self, db_session: AsyncSession):
        """ChallengeSession.challenger_id pointing to non-existent user raises IntegrityError."""
        fake_user_id = uuid.uuid4()
        session = ChallengeSession(
            challenger_id=fake_user_id,
            opponent_id=fake_user_id,
            problem_id="800A",
            problem_rating=800,
        )
        db_session.add(session)
        with pytest.raises(IntegrityError):
            await db_session.flush()
        await db_session.rollback()

    async def test_user_tag_elo_user_fk(self, db_session: AsyncSession):
        """UserTagElo.user_id pointing to non-existent user raises IntegrityError."""
        fake_user_id = uuid.uuid4()
        tag_elo = UserTagElo(
            user_id=fake_user_id,
            tag="dp",
        )
        db_session.add(tag_elo)
        with pytest.raises(IntegrityError):
            await db_session.flush()
        await db_session.rollback()


# ---------------------------------------------------------------------------
# Unique constraint tests
# ---------------------------------------------------------------------------


class TestUniqueConstraints:
    """Verify PostgreSQL enforces UNIQUE constraints."""

    async def test_duplicate_username(self, db_session: AsyncSession):
        """Two users with the same username raises IntegrityError."""
        uid = uuid.uuid4().hex[:8]
        shared_username = f"dup_{uid}"
        user1 = User(
            username=shared_username,
            email=f"{uid}_first@test.com",
            password_hash="$2b$12$fakehash",
        )
        db_session.add(user1)
        await db_session.flush()

        # Second user with the same username
        dup = User(
            username=shared_username,
            email=f"{uid}_second@test.com",
            password_hash="$2b$12$fakehash",
        )
        db_session.add(dup)
        with pytest.raises(IntegrityError):
            await db_session.flush()
        await db_session.rollback()

    async def test_duplicate_user_tag_elo_pair(self, db_session: AsyncSession):
        """Duplicate (user_id, tag) pair in UserTagElo raises IntegrityError."""
        user = await _make_user(db_session, suffix="_tagelo")
        tag_elo1 = UserTagElo(user_id=user.id, tag="dp")
        db_session.add(tag_elo1)
        await db_session.flush()

        tag_elo2 = UserTagElo(user_id=user.id, tag="dp")
        db_session.add(tag_elo2)
        with pytest.raises(IntegrityError):
            await db_session.flush()
        await db_session.rollback()

    async def test_different_tags_same_user_allowed(self, db_session: AsyncSession):
        """Same user with different tags is allowed."""
        user = await _make_user(db_session, suffix="_multitag")
        for tag in ["dp", "greedy", "math"]:
            db_session.add(UserTagElo(user_id=user.id, tag=tag))
        await db_session.flush()
        # No error means the unique constraint only applies to (user_id, tag) pairs


# ---------------------------------------------------------------------------
# server_default tests
# ---------------------------------------------------------------------------


class TestServerDefaults:
    """Verify PostgreSQL server_default values are populated."""

    async def test_user_id_auto_generated_uuid(self, db_session: AsyncSession):
        """User.id is auto-generated as a UUID by PostgreSQL."""
        user = await _make_user(db_session, suffix="_autoid")
        assert user.id is not None
        assert isinstance(user.id, uuid.UUID)

    async def test_user_created_at_auto_set(self, db_session: AsyncSession):
        """User.created_at is auto-set by PostgreSQL (server_default=now())."""
        user = await _make_user(db_session, suffix="_autots")
        assert user.created_at is not None
        assert isinstance(user.created_at, datetime)
        # Should be timezone-aware
        assert user.created_at.tzinfo is not None


# ---------------------------------------------------------------------------
# Zero-coverage model CRUD tests
# ---------------------------------------------------------------------------


class TestUserTagEloCRUD:
    """UserTagElo: create -> read -> update lifecycle."""

    async def test_create_read_update(self, db_session: AsyncSession):
        user = await _make_user(db_session, suffix="_elo_crud")

        # CREATE
        tag_elo = UserTagElo(user_id=user.id, tag="greedy")
        db_session.add(tag_elo)
        await db_session.flush()
        assert tag_elo.id is not None
        assert tag_elo.elo == 1200  # server_default
        assert tag_elo.total_submissions == 0  # server_default

        # READ
        result = await db_session.execute(
            select(UserTagElo).where(UserTagElo.user_id == user.id, UserTagElo.tag == "greedy")
        )
        found = result.scalar_one()
        assert found.id == tag_elo.id
        assert found.elo == 1200

        # UPDATE
        found.elo = 1350
        found.total_submissions = 5
        await db_session.flush()

        result2 = await db_session.execute(
            select(UserTagElo).where(UserTagElo.id == tag_elo.id)
        )
        updated = result2.scalar_one()
        assert updated.elo == 1350
        assert updated.total_submissions == 5


class TestPvEChallengeSessionCRUD:
    """PvEChallengeSession: create with JSON problem_tags -> read."""

    async def test_create_with_json_tags_and_read(self, db_session: AsyncSession):
        user = await _make_user(db_session, suffix="_pve")

        # CREATE with JSON problem_tags
        problem_tags = {"dp": 3, "math": 2}
        session = PvEChallengeSession(
            user_id=user.id,
            problem_id="1500B",
            problem_rating=1500,
            problem_tags=problem_tags,
        )
        db_session.add(session)
        await db_session.flush()
        assert session.id is not None
        assert session.status == "active"  # server_default

        # READ
        result = await db_session.execute(
            select(PvEChallengeSession).where(PvEChallengeSession.user_id == user.id)
        )
        found = result.scalar_one()
        assert found.problem_id == "1500B"
        assert found.problem_rating == 1500
        assert found.problem_tags == problem_tags
        assert found.error_count == 0  # server_default
        assert found.hints_used == 0  # server_default


class TestSubmissionTrackingCRUD:
    """SubmissionTracking: create -> update status (pending -> matched -> settled)."""

    async def test_create_and_status_transitions(self, db_session: AsyncSession):
        user = await _make_user(db_session, suffix="_subtrack")
        fake_session_id = uuid.uuid4()
        now = datetime.now(UTC)

        # CREATE (status defaults to "pending")
        tracking = SubmissionTracking(
            user_id=user.id,
            session_type="pve",
            session_id=fake_session_id,
            problem_id="1200A",
            expected_at=now,
        )
        db_session.add(tracking)
        await db_session.flush()
        assert tracking.id is not None
        assert tracking.status == "pending"  # server_default

        # UPDATE: pending -> matched
        tracking.status = "matched"
        tracking.cf_submission_id = 12345678
        tracking.matched_at = datetime.now(UTC)
        await db_session.flush()

        # Verify matched state
        result = await db_session.execute(
            select(SubmissionTracking).where(SubmissionTracking.id == tracking.id)
        )
        matched = result.scalar_one()
        assert matched.status == "matched"
        assert matched.cf_submission_id == 12345678

        # UPDATE: matched -> settled
        matched.status = "settled"
        matched.cf_verdict = "OK"
        await db_session.flush()

        result2 = await db_session.execute(
            select(SubmissionTracking).where(SubmissionTracking.id == tracking.id)
        )
        settled = result2.scalar_one()
        assert settled.status == "settled"
        assert settled.cf_verdict == "OK"


class TestContestBotCRUD:
    """ContestBot: create -> read (requires a ContestSession parent)."""

    async def test_create_and_read(self, db_session: AsyncSession):
        user = await _make_user(db_session, suffix="_bot")

        # Need a ContestSession first (ContestBot has FK to contest_sessions)
        contest = ContestSession(
            user_id=user.id,
            contest_tier="beginner",
            total_problems=4,
            time_limit=90,
            started_at=datetime.now(UTC),
        )
        db_session.add(contest)
        await db_session.flush()
        assert contest.id is not None

        # CREATE ContestBot
        bot = ContestBot(
            contest_id=contest.id,
            bot_name="BotAlpha",
            bot_elo=1100,
        )
        db_session.add(bot)
        await db_session.flush()
        assert bot.id is not None
        assert bot.problems_solved == 0  # server_default
        assert bot.total_attempts == 0  # server_default

        # READ
        result = await db_session.execute(
            select(ContestBot).where(ContestBot.contest_id == contest.id)
        )
        found = result.scalar_one()
        assert found.bot_name == "BotAlpha"
        assert found.bot_elo == 1100
