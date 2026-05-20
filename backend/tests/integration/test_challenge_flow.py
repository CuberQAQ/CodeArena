"""Integration test: random challenge matching, problem reveal, submission, settlement.

Tests the complete challenge lifecycle through the service layer (not HTTP)
since matching requires two in-memory players interacting concurrently.
"""

import uuid

import pytest
from sqlalchemy import select

from .conftest import (
    _TestChallengeSession,
    _TestUser,
    create_test_user,
    make_cf_problems_response,
    mock_cf_service,
)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestChallengeJoinQueue:
    """Test joining/leaving the match queue."""

    async def test_join_queue_returns_matched_when_opponent_present(self, db_session):
        """When two players join, they are matched."""
        user_a = await create_test_user(db_session, username="player_a", email="a@test.com", elo=1200)
        user_b = await create_test_user(db_session, username="player_b", email="b@test.com", elo=1200)
        await db_session.commit()

        from app.services.match_service import MatchService
        from app.services.challenge_service import ChallengeService

        match_svc = MatchService()

        # Player A joins -- no opponent, returns unmatched
        result_a = await ChallengeService.join_queue(db_session, user_a, match_svc)
        assert result_a["matched"] is False

        # Player B joins -- matched with A
        result_b = await ChallengeService.join_queue(db_session, user_b, match_svc)
        assert result_b["matched"] is True
        assert "session_id" in result_b
        assert "opponent" in result_b

    async def test_join_queue_twice_fails(self, db_session):
        """A user already in the queue cannot join again."""
        user = await create_test_user(db_session, username="q_user", email="q@test.com")
        await db_session.commit()

        from app.services.match_service import MatchService
        from app.services.challenge_service import ChallengeService

        match_svc = MatchService()
        await ChallengeService.join_queue(db_session, user, match_svc)

        with pytest.raises(Exception):
            await ChallengeService.join_queue(db_session, user, match_svc)

    async def test_leave_queue(self, db_session):
        """A user can leave the queue."""
        user = await create_test_user(db_session, username="leave_user", email="leave@test.com")
        await db_session.commit()

        from app.services.match_service import MatchService
        from app.services.challenge_service import ChallengeService

        match_svc = MatchService()
        await ChallengeService.join_queue(db_session, user, match_svc)

        removed = await ChallengeService.leave_queue(user, match_svc)
        assert removed is True


class TestChallengeStartAndSubmit:
    """Test start (problem reveal), submit, and settlement."""

    async def test_start_challenge_both_confirm_reveals_problem(self, db_session):
        """When both players confirm start, a problem is selected."""
        user_a = await create_test_user(db_session, username="start_a", email="sa@test.com", elo=1200)
        user_b = await create_test_user(db_session, username="start_b", email="sb@test.com", elo=1200)
        await db_session.commit()

        from app.services.match_service import MatchService
        from app.services.challenge_service import ChallengeService

        match_svc = MatchService()

        # Match them
        await ChallengeService.join_queue(db_session, user_a, match_svc)
        result = await ChallengeService.join_queue(db_session, user_b, match_svc)
        assert result["matched"] is True
        session_id = uuid.UUID(result["session_id"])

        cf = mock_cf_service(make_cf_problems_response(count=20, base_rating=1000))

        # Player A confirms -- should get waiting status
        resp_a = await ChallengeService.start_challenge(db_session, user_a, session_id, cf)
        assert resp_a.status == "waiting_opponent"

        # Player B confirms -- both confirmed, problem revealed
        resp_b = await ChallengeService.start_challenge(db_session, user_b, session_id, cf)
        assert resp_b.status == "problem_revealed"
        assert resp_b.problem is not None
        assert resp_b.problem.rating > 0

        # Player A calls start again -- should get the problem too
        resp_a2 = await ChallengeService.start_challenge(db_session, user_a, session_id, cf)
        assert resp_a2.status == "problem_revealed"

    async def test_submit_both_solved_faster_wins(self, db_session):
        """When both solve, the faster player wins and gets Elo."""
        user_a = await create_test_user(db_session, username="fast_a", email="fast_a@test.com", elo=1200)
        user_b = await create_test_user(db_session, username="fast_b", email="fast_b@test.com", elo=1200)
        await db_session.commit()

        from app.services.challenge_service import ChallengeService

        # Create session directly using test model
        session = _TestChallengeSession(
            challenger_id=user_a.id,
            opponent_id=user_b.id,
            problem_id="1000A",
            problem_rating=1200,
            status="active",
        )
        db_session.add(session)
        await db_session.flush()

        # Player A solves in 300 seconds
        resp_a = await ChallengeService.submit_result(
            db_session, user_a, session.id, solved=True, time_spent=300.0, attempts=1
        )
        assert resp_a.settled is False  # waiting for opponent

        # Player B solves in 600 seconds (slower)
        resp_b = await ChallengeService.submit_result(
            db_session, user_b, session.id, solved=True, time_spent=600.0, attempts=2
        )
        assert resp_b.settled is True
        assert resp_b.result == "challenger_win"

        # Check Elo changes
        await db_session.refresh(user_a)
        await db_session.refresh(user_b)
        assert user_a.elo > 1200  # winner gains Elo
        assert user_a.elo > user_b.elo  # winner gains more than loser

    async def test_submit_one_solved_one_not(self, db_session):
        """When only one player solves, they win."""
        user_a = await create_test_user(db_session, username="solve_a", email="solve_a@test.com", elo=1200)
        user_b = await create_test_user(db_session, username="solve_b", email="solve_b@test.com", elo=1200)
        await db_session.commit()

        from app.services.challenge_service import ChallengeService

        session = _TestChallengeSession(
            challenger_id=user_a.id,
            opponent_id=user_b.id,
            problem_id="1001B",
            problem_rating=1000,
            status="active",
        )
        db_session.add(session)
        await db_session.flush()

        await ChallengeService.submit_result(
            db_session, user_a, session.id, solved=True, time_spent=200.0, attempts=1
        )
        resp_b = await ChallengeService.submit_result(
            db_session, user_b, session.id, solved=False, time_spent=600.0, attempts=5
        )
        assert resp_b.result == "challenger_win"

        await db_session.refresh(user_a)
        assert user_a.elo > 1200

    async def test_submit_neither_solved_draw(self, db_session):
        """When neither solves, it's a draw."""
        user_a = await create_test_user(db_session, username="draw_a", email="draw_a@test.com", elo=1200)
        user_b = await create_test_user(db_session, username="draw_b", email="draw_b@test.com", elo=1200)
        await db_session.commit()

        from app.services.challenge_service import ChallengeService

        session = _TestChallengeSession(
            challenger_id=user_a.id,
            opponent_id=user_b.id,
            problem_id="1002C",
            problem_rating=1000,
            status="active",
        )
        db_session.add(session)
        await db_session.flush()

        await ChallengeService.submit_result(
            db_session, user_a, session.id, solved=False, time_spent=600.0, attempts=3
        )
        resp_b = await ChallengeService.submit_result(
            db_session, user_b, session.id, solved=False, time_spent=600.0, attempts=3
        )
        assert resp_b.result == "draw"

    async def test_quit_with_penalty(self, db_session):
        """Quitting a challenge applies Elo penalty."""
        user_a = await create_test_user(db_session, username="quit_a", email="quit_a@test.com", elo=1200)
        user_b = await create_test_user(db_session, username="quit_b", email="quit_b@test.com", elo=1200)
        await db_session.commit()

        from app.services.challenge_service import ChallengeService

        session = _TestChallengeSession(
            challenger_id=user_a.id,
            opponent_id=user_b.id,
            problem_id="1003D",
            problem_rating=1000,
            status="active",
        )
        db_session.add(session)
        await db_session.flush()

        result = await ChallengeService.quit_challenge(
            db_session, user_a, session.id, submissions=1
        )
        assert result["status"] == "quit"
        assert result["elo_change"] is not None
        assert result["elo_change"] < 0  # penalty is negative

        await db_session.refresh(user_a)
        assert user_a.elo < 1200

    async def test_tokens_awarded_on_win(self, db_session):
        """Winning a challenge awards tokens to the winner."""
        user_a = await create_test_user(db_session, username="token_a", email="token_a@test.com", elo=1200)
        user_b = await create_test_user(db_session, username="token_b", email="token_b@test.com", elo=1200)
        await db_session.commit()

        from app.services.challenge_service import ChallengeService

        session = _TestChallengeSession(
            challenger_id=user_a.id,
            opponent_id=user_b.id,
            problem_id="1004A",
            problem_rating=1200,
            status="active",
        )
        db_session.add(session)
        await db_session.flush()

        await ChallengeService.submit_result(
            db_session, user_a, session.id, solved=True, time_spent=200.0, attempts=1
        )
        resp_b = await ChallengeService.submit_result(
            db_session, user_b, session.id, solved=False, time_spent=600.0, attempts=3
        )
        assert resp_b.result == "challenger_win"

        await db_session.refresh(user_a)
        assert user_a.tokens > 0

    async def test_pp_updated_on_solve(self, db_session):
        """Solving a challenge problem updates PP."""
        user_a = await create_test_user(db_session, username="pp_a", email="pp_a@test.com", elo=1200)
        user_b = await create_test_user(db_session, username="pp_b", email="pp_b@test.com", elo=1200)
        await db_session.commit()

        from app.services.challenge_service import ChallengeService

        session = _TestChallengeSession(
            challenger_id=user_a.id,
            opponent_id=user_b.id,
            problem_id="1005A",
            problem_rating=1500,
            status="active",
        )
        db_session.add(session)
        await db_session.flush()

        await ChallengeService.submit_result(
            db_session, user_a, session.id, solved=True, time_spent=300.0, attempts=1
        )
        await ChallengeService.submit_result(
            db_session, user_b, session.id, solved=False, time_spent=600.0, attempts=3
        )

        await db_session.refresh(user_a)
        assert user_a.pp > 0

    async def test_cannot_submit_twice(self, db_session):
        """A player cannot submit results twice."""
        user_a = await create_test_user(db_session, username="dbl_a", email="dbl_a@test.com", elo=1200)
        user_b = await create_test_user(db_session, username="dbl_b", email="dbl_b@test.com", elo=1200)
        await db_session.commit()

        from app.services.challenge_service import ChallengeService

        session = _TestChallengeSession(
            challenger_id=user_a.id,
            opponent_id=user_b.id,
            problem_id="1006A",
            problem_rating=1000,
            status="active",
        )
        db_session.add(session)
        await db_session.flush()

        await ChallengeService.submit_result(
            db_session, user_a, session.id, solved=True, time_spent=200.0, attempts=1
        )

        with pytest.raises(Exception, match="Already submitted"):
            await ChallengeService.submit_result(
                db_session, user_a, session.id, solved=False, time_spent=600.0, attempts=5
            )
