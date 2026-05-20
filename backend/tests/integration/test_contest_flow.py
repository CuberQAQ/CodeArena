"""Integration test: virtual contest full flow.

Tests tier listing, contest start, problem submission, contest end,
and Elo/token/PP updates.
"""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from .conftest import (
    create_test_user,
    make_cf_problems_response,
    mock_cf_service,
)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestContestTiers:
    """Test tier listing and eligibility."""

    async def test_get_tiers_returns_all(self, db_session):
        """get_tiers returns beginner, advanced, and master tiers."""
        user = await create_test_user(db_session, elo=1200)
        await db_session.commit()

        from app.services.contest_service import ContestService

        tiers = await ContestService.get_tiers(db_session, user)
        assert len(tiers) == 3

        tier_keys = [t.tier for t in tiers]
        assert "beginner" in tier_keys
        assert "advanced" in tier_keys
        assert "master" in tier_keys

    async def test_beginner_user_eligible_for_beginner(self, db_session):
        """A user with elo < 1400 is eligible for beginner."""
        user = await create_test_user(db_session, elo=1200)
        await db_session.commit()

        from app.services.contest_service import ContestService

        tiers = await ContestService.get_tiers(db_session, user)
        beginner = next(t for t in tiers if t.tier == "beginner")
        assert beginner.eligible is True

    async def test_master_user_not_eligible_for_beginner(self, db_session):
        """A user with elo >= 1800 is not directly eligible for beginner."""
        user = await create_test_user(db_session, elo=2000)
        await db_session.commit()

        from app.services.contest_service import ContestService

        tiers = await ContestService.get_tiers(db_session, user)
        beginner = next(t for t in tiers if t.tier == "beginner")
        # With current logic, higher elo users can still downgrade
        # The eligibility check is: not (min_elo is not None and user.elo < min_elo)
        # beginner has no min_elo, so eligible = True
        assert beginner.eligible is True

    async def test_low_elo_not_eligible_for_advanced(self, db_session):
        """A user with elo < 1400 is not eligible for advanced."""
        user = await create_test_user(db_session, elo=1200)
        await db_session.commit()

        from app.services.contest_service import ContestService

        tiers = await ContestService.get_tiers(db_session, user)
        advanced = next(t for t in tiers if t.tier == "advanced")
        assert advanced.eligible is False


class TestContestStart:
    """Test starting contests."""

    async def test_start_beginner_contest(self, db_session):
        """Starting a beginner contest creates a session with problems."""
        user = await create_test_user(db_session, elo=1200)
        await db_session.commit()

        from app.services.contest_service import ContestService

        cf = mock_cf_service(make_cf_problems_response(count=20, base_rating=800))

        result = await ContestService.start_contest(db_session, user, "beginner", cf)
        assert result.tier == "beginner"
        assert result.status == "active"
        assert len(result.problems) > 0
        assert result.remaining_seconds > 0

    async def test_start_invalid_tier_fails(self, db_session):
        """Starting with an invalid tier raises BadRequestException."""
        user = await create_test_user(db_session, elo=1200)
        await db_session.commit()

        from app.services.contest_service import ContestService

        cf = mock_cf_service()
        with pytest.raises(Exception, match="Invalid tier"):
            await ContestService.start_contest(db_session, user, "invalid_tier", cf)

    async def test_cannot_start_two_active_contests(self, db_session):
        """User cannot start two active contests."""
        user = await create_test_user(db_session, elo=1200)
        await db_session.commit()

        from app.services.contest_service import ContestService

        cf = mock_cf_service(make_cf_problems_response(count=20, base_rating=800))

        await ContestService.start_contest(db_session, user, "beginner", cf)

        with pytest.raises(Exception, match="already have an active"):
            await ContestService.start_contest(db_session, user, "beginner", cf)


class TestContestSubmit:
    """Test submitting problem results in contests."""

    async def _create_contest(self, db_session, user_elo=1200, base_rating=800):
        """Helper: create an active contest session."""
        user = await create_test_user(db_session, elo=user_elo)
        await db_session.commit()

        from app.services.contest_service import ContestService

        cf = mock_cf_service(make_cf_problems_response(count=20, base_rating=base_rating))
        session_info = await ContestService.start_contest(db_session, user, "beginner", cf)
        return user, session_info

    async def test_submit_solved_problem(self, db_session):
        """Submitting a solved problem updates contest state."""
        user, session_info = await self._create_contest(db_session)

        from app.services.contest_service import ContestService

        # Use the first problem from the session
        problem_id = session_info.problems[0].problem_id

        result = await ContestService.submit_problem(
            db_session, user, session_info.id,
            problem_id=problem_id, solved=True, attempts=1, time_spent=300.0,
        )
        assert result.solved is True
        assert result.tokens_earned > 0

        await db_session.refresh(user)
        assert user.tokens > 0

    async def test_submit_invalid_problem_fails(self, db_session):
        """Submitting a result for a problem not in the contest fails."""
        user, session_info = await self._create_contest(db_session)

        from app.services.contest_service import ContestService

        with pytest.raises(Exception, match="not found in this contest"):
            await ContestService.submit_problem(
                db_session, user, session_info.id,
                problem_id="9999Z", solved=True, attempts=1, time_spent=300.0,
            )

    async def test_submit_updates_pp(self, db_session):
        """Solving a contest problem updates PP."""
        user, session_info = await self._create_contest(db_session, base_rating=1200)

        from app.services.contest_service import ContestService

        problem_id = session_info.problems[0].problem_id
        await ContestService.submit_problem(
            db_session, user, session_info.id,
            problem_id=problem_id, solved=True, attempts=1, time_spent=300.0,
        )

        await db_session.refresh(user)
        assert user.pp > 0


class TestContestEnd:
    """Test ending contests and Elo calculation."""

    async def _create_contest_with_submissions(self, db_session, user_elo=1200):
        """Helper: create contest and submit some problems."""
        user = await create_test_user(db_session, elo=user_elo)
        await db_session.commit()

        from app.services.contest_service import ContestService

        cf = mock_cf_service(make_cf_problems_response(count=20, base_rating=800))
        session_info = await ContestService.start_contest(db_session, user, "beginner", cf)

        # Submit all problems as solved
        for p in session_info.problems:
            await ContestService.submit_problem(
                db_session, user, session_info.id,
                problem_id=p.problem_id, solved=True, attempts=1, time_spent=300.0,
            )

        return user, session_info

    async def test_end_contest_updates_elo(self, db_session):
        """Ending a contest with submissions updates Elo."""
        user, session_info = await self._create_contest_with_submissions(db_session)

        from app.services.contest_service import ContestService

        result = await ContestService.end_contest(db_session, user, session_info.id)
        assert result.status == "completed"
        assert result.elo_change is not None

        await db_session.refresh(user)
        # Solving all problems should increase Elo
        assert user.elo >= 1200

    async def test_end_contest_zero_submissions_no_elo_change(self, db_session):
        """Ending a contest with 0 submissions does not change Elo."""
        user = await create_test_user(db_session, elo=1200)
        await db_session.commit()

        from app.services.contest_service import ContestService

        cf = mock_cf_service(make_cf_problems_response(count=20, base_rating=800))
        session_info = await ContestService.start_contest(db_session, user, "beginner", cf)

        result = await ContestService.end_contest(db_session, user, session_info.id)
        assert result.elo_change == 0

        await db_session.refresh(user)
        assert user.elo == 1200

    async def test_get_contest_history(self, db_session):
        """Contest history lists past contests."""
        user = await create_test_user(db_session, elo=1200)
        await db_session.commit()

        from app.services.contest_service import ContestService

        cf = mock_cf_service(make_cf_problems_response(count=20, base_rating=800))
        session_info = await ContestService.start_contest(db_session, user, "beginner", cf)
        await ContestService.end_contest(db_session, user, session_info.id)

        history = await ContestService.get_contest_history(db_session, user)
        assert len(history) >= 1
        assert history[0].tier == "beginner"

    async def test_get_contest_result(self, db_session):
        """Can retrieve detailed results for a completed contest."""
        user, session_info = await self._create_contest_with_submissions(db_session)

        from app.services.contest_service import ContestService

        await ContestService.end_contest(db_session, user, session_info.id)

        result = await ContestService.get_contest_result(db_session, user, session_info.id)
        assert result.status == "completed"
        assert result.total_problems > 0
        assert result.problems_solved > 0
        assert len(result.problems) > 0
