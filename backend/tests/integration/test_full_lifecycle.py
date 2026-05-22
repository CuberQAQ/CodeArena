"""Integration test: full user lifecycle across game modes.

Tests the complete journey from user creation through PvE challenge,
training session, and ranking verification, ensuring all subsystems
(Elo, PP, tokens, history) integrate correctly end-to-end.
"""

from app.models.elo_history import EloHistory
from app.models.pp_record import PPRecord
from app.models.pve_challenge_session import PvEChallengeSession
from app.models.token_transaction import TokenTransaction
from app.models.training_problem_record import TrainingProblemRecord
from app.models.training_session import TrainingSession

from .conftest import (
    create_test_topic,
    create_test_user,
    make_cf_problems_response,
    mock_cf_service,
)

# ---------------------------------------------------------------------------
# PvE Full Lifecycle
# ---------------------------------------------------------------------------


class TestPvEFullLifecycle:
    """End-to-end lifecycle: register -> PvE -> submit -> verify all subsystems."""

    async def test_register_login_pve_submit_verify_elo_pp_token(self, db_session):
        """Full PvE lifecycle: create user, start challenge, solve, verify Elo/PP/tokens/history."""
        from sqlalchemy import select

        from app.services.pve_challenge_service import PvEChallengeService

        # 1. Create user with 0 tokens
        user = await create_test_user(db_session, tokens=0)
        await db_session.commit()

        assert user.elo == 1200
        assert user.pp == 0.0
        assert user.tokens == 0

        # 2. Mock CF API with problems in user's Elo range (1100-1400)
        cf = mock_cf_service(make_cf_problems_response(count=10, base_rating=1000))

        # 3. Start PvE challenge
        start_result = await PvEChallengeService.start_challenge(db_session, user, cf)
        await db_session.commit()

        assert start_result.status == "active"
        assert start_result.session_id is not None
        assert start_result.problem is not None
        assert start_result.problem.rating is not None

        # 4. Submit result as solved
        submit_result = await PvEChallengeService.submit_result(
            db_session,
            user,
            session_id=start_result.session_id,
            solved=True,
            time_spent=120.0,
            attempts=1,
            error_count=0,
            cf_service=cf,
        )
        await db_session.commit()

        assert submit_result.solved is True
        assert submit_result.status == "completed"
        assert submit_result.elo_change > 0, "Solving should increase Elo"
        assert submit_result.tokens_earned > 0, "Solving should award tokens"

        # 5. Verify user state updated
        await db_session.refresh(user)
        assert user.elo > 1200, f"Elo should have increased from 1200, got {user.elo}"
        assert user.pp > 0, f"PP should be positive after solve, got {user.pp}"
        assert user.tokens > 0, f"Tokens should be positive after reward, got {user.tokens}"

        # 6. Verify EloHistory record exists
        elo_stmt = select(EloHistory).where(EloHistory.user_id == user.id)
        elo_result = await db_session.execute(elo_stmt)
        elo_records = list(elo_result.scalars().all())
        assert len(elo_records) >= 1, "At least one EloHistory record should exist"
        elo_rec = elo_records[0]
        assert elo_rec.elo_before == 1200
        assert elo_rec.elo_after == user.elo
        assert elo_rec.elo_change > 0

        # 7. Verify PPRecord exists
        pp_stmt = select(PPRecord).where(PPRecord.user_id == user.id)
        pp_result = await db_session.execute(pp_stmt)
        pp_records = list(pp_result.scalars().all())
        assert len(pp_records) >= 1, "At least one PPRecord should exist after solving"

        # 8. Verify token transaction exists
        tx_stmt = select(TokenTransaction).where(TokenTransaction.user_id == user.id)
        tx_result = await db_session.execute(tx_stmt)
        tx_records = list(tx_result.scalars().all())
        assert len(tx_records) >= 1, "At least one TokenTransaction should exist"
        # AC reward transaction should be positive
        positive_txs = [t for t in tx_records if t.amount > 0]
        assert len(positive_txs) >= 1, "Should have at least one positive token transaction"

        # 9. Verify PvE session is marked completed
        session_stmt = select(PvEChallengeSession).where(PvEChallengeSession.id == start_result.session_id)
        session_result = await db_session.execute(session_stmt)
        pve_session = session_result.scalar_one()
        assert pve_session.status == "completed"
        assert pve_session.elo_change == submit_result.elo_change

    async def test_pve_not_solved_no_pp_gain(self, db_session):
        """Failing a PvE challenge: Elo stays at 1200 (or lower), PP stays at 0."""
        from app.services.pve_challenge_service import PvEChallengeService

        user = await create_test_user(db_session, tokens=0)
        await db_session.commit()

        cf = mock_cf_service(make_cf_problems_response(count=10, base_rating=1000))

        # Start and fail
        start_result = await PvEChallengeService.start_challenge(db_session, user, cf)
        await db_session.commit()

        submit_result = await PvEChallengeService.submit_result(
            db_session,
            user,
            session_id=start_result.session_id,
            solved=False,
            time_spent=300.0,
            attempts=3,
            error_count=2,
            cf_service=cf,
        )
        await db_session.commit()

        assert submit_result.solved is False
        assert submit_result.status == "completed"

        # Verify: Elo should be <= 1200 (loss or no change depending on expected score)
        await db_session.refresh(user)
        assert user.elo <= 1200, f"Elo should not increase on failure, got {user.elo}"

        # Verify: PP stays at 0 (no PP for unsolved problems)
        assert user.pp == 0.0, f"PP should stay 0 on failure, got {user.pp}"


# ---------------------------------------------------------------------------
# Training Full Lifecycle
# ---------------------------------------------------------------------------


class TestTrainingFullLifecycle:
    """End-to-end lifecycle: start training -> submit problem -> verify updates."""

    async def test_training_session_submit_verify_updates(self, db_session):
        """Full training lifecycle: start session, solve a problem, verify tokens/PP/session."""
        from sqlalchemy import select

        from app.services.training_service import TrainingService

        # 1. Create user and topic
        user = await create_test_user(db_session)
        topic = await create_test_topic(db_session)
        await db_session.commit()

        # 2. Mock CF API with problems matching topic tags
        cf = mock_cf_service(make_cf_problems_response(count=5, base_rating=1200, tags=["dp", "math"]))

        # 3. Start training session
        session_info = await TrainingService.start_training(db_session, user, topic.id, cf)
        await db_session.commit()

        assert session_info.status == "active"
        assert session_info.topic_id == topic.id
        assert session_info.problems_solved == 0
        session_id = session_info.id

        # 4. Submit a solved problem
        submit_result = await TrainingService.submit_problem(
            db_session,
            user,
            session_id=session_id,
            problem_id="1000A",
            solved=True,
            attempts=1,
            time_spent=300.0,
            cf_service=cf,
        )
        await db_session.commit()

        assert submit_result.solved is True
        assert submit_result.tokens_earned > 0, "Solving should award tokens"
        assert submit_result.elo_change is not None

        # 5. Verify user state
        await db_session.refresh(user)
        assert user.tokens > 0, f"User should have tokens, got {user.tokens}"
        assert user.pp > 0, f"User should have PP after solving, got {user.pp}"

        # 6. Verify training session updated
        training_stmt = select(TrainingSession).where(TrainingSession.id == session_id)
        training_result = await db_session.execute(training_stmt)
        training_session = training_result.scalar_one()
        assert training_session.problems_solved == 1
        assert training_session.streak_count >= 1

        # 7. Verify problem record created
        record_stmt = select(TrainingProblemRecord).where(
            TrainingProblemRecord.session_id == session_id,
            TrainingProblemRecord.problem_id == "1000A",
        )
        record_result = await db_session.execute(record_stmt)
        problem_record = record_result.scalar_one_or_none()
        assert problem_record is not None
        assert problem_record.solved is True
        assert problem_record.attempts == 1

        # 8. Verify PP record created
        pp_stmt = select(PPRecord).where(
            PPRecord.user_id == user.id,
            PPRecord.cf_problem_id == "1000A",
        )
        pp_result = await db_session.execute(pp_stmt)
        pp_record = pp_result.scalar_one_or_none()
        assert pp_record is not None, "PPRecord should exist for solved problem"

        # 9. Verify Elo history created (training generates Elo change)
        elo_stmt = select(EloHistory).where(EloHistory.user_id == user.id)
        elo_result = await db_session.execute(elo_stmt)
        elo_records = list(elo_result.scalars().all())
        # Training Elo changes may or may not be recorded depending on whether change is non-zero
        # But solving a 1200-rated problem at 1200 Elo should produce a positive change
        assert len(elo_records) >= 1, "At least one EloHistory record should exist"


# ---------------------------------------------------------------------------
# Ranking Lifecycle
# ---------------------------------------------------------------------------


class TestRankingLifecycle:
    """Test that user activity feeds into the ranking system correctly."""

    async def test_user_appears_in_ranking_after_activity(self, db_session):
        """After solving problems (earning PP), users appear in arena ranking by Elo order."""
        from sqlalchemy import select

        from app.services.pp_service import PPService

        # 1. Create 3 users with different Elo ratings
        user_low = await create_test_user(db_session, username="rank_low", email="rank_low@test.com", elo=1000)
        user_mid = await create_test_user(db_session, username="rank_mid", email="rank_mid@test.com", elo=1500)
        user_high = await create_test_user(db_session, username="rank_high", email="rank_high@test.com", elo=2000)
        await db_session.commit()

        # 2. Give each user PP by recording problem solves
        # User low solves a problem at rating 1000 -> PP > 0
        await PPService.record_pp(db_session, user_low.id, cf_problem_id="1000A", problem_rating=1000)
        # User mid solves a problem at rating 1500 -> PP > 0
        await PPService.record_pp(db_session, user_mid.id, cf_problem_id="1500A", problem_rating=1500)
        # User high solves a problem at rating 2000 -> PP > 0
        await PPService.record_pp(db_session, user_high.id, cf_problem_id="2000A", problem_rating=2000)

        # 3. Query users directly sorted by Elo descending, filtered by pp > 0
        # (This mirrors what get_arena_ranking does without needing full FastAPI context)
        from app.models.user import User

        stmt = (
            select(User.username, User.pp, User.elo)
            .where(User.is_active == True, User.pp > 0)  # noqa: E712
            .order_by(User.elo.desc())
        )
        result = await db_session.execute(stmt)
        rows = result.all()

        # 4. Verify users appear in correct Elo order (high -> mid -> low)
        assert len(rows) == 3, f"Expected 3 ranked users, got {len(rows)}"
        assert rows[0].username == "rank_high", f"First should be rank_high, got {rows[0].username}"
        assert rows[1].username == "rank_mid", f"Second should be rank_mid, got {rows[1].username}"
        assert rows[2].username == "rank_low", f"Third should be rank_low, got {rows[2].username}"

        # 5. Verify Elo values are correct
        assert rows[0].elo == 2000
        assert rows[1].elo == 1500
        assert rows[2].elo == 1000

        # 6. Verify all have positive PP
        for row in rows:
            assert row.pp > 0, f"User {row.username} should have PP > 0, got {row.pp}"

    async def test_pp_ranking_orders_by_pp(self, db_session):
        """PP ranking correctly orders users by total PP (hardest problem solver first)."""
        from app.services.pp_service import PPService

        # Create users
        user_a = await create_test_user(db_session, username="pp_rank_a", email="pp_rank_a@test.com", elo=1200)
        user_b = await create_test_user(db_session, username="pp_rank_b", email="pp_rank_b@test.com", elo=1200)
        user_c = await create_test_user(db_session, username="pp_rank_c", email="pp_rank_c@test.com", elo=1200)
        await db_session.commit()

        # User A solves hardest (2000) -> highest PP
        await PPService.record_pp(db_session, user_a.id, cf_problem_id="2000A", problem_rating=2000)
        # User B solves medium (1500)
        await PPService.record_pp(db_session, user_b.id, cf_problem_id="1500A", problem_rating=1500)
        # User C solves easiest (1000)
        await PPService.record_pp(db_session, user_c.id, cf_problem_id="1000A", problem_rating=1000)

        ranking, total = await PPService.get_pp_ranking(db_session)

        assert total >= 3

        # Find our users' ranks
        ranks = {}
        for rank, username, pp in ranking:
            ranks[username] = (rank, pp)

        assert "pp_rank_a" in ranks, "User A should appear in PP ranking"
        assert "pp_rank_b" in ranks, "User B should appear in PP ranking"
        assert "pp_rank_c" in ranks, "User C should appear in PP ranking"

        # User A (hardest problem) should be ranked highest (lowest rank number)
        assert ranks["pp_rank_a"][0] < ranks["pp_rank_b"][0], "User A should outrank User B"
        assert ranks["pp_rank_b"][0] < ranks["pp_rank_c"][0], "User B should outrank User C"
