"""Integration test: concurrent safety and sequential rapid operations.

Tests that rapid sequential operations maintain data integrity, that
insufficient-balance checks work correctly, and that business rules
enforce session uniqueness. Uses real PostgreSQL via testcontainers.

Note: true multi-session concurrency is difficult in asyncio integration
tests because the event loop serializes coroutines. These tests focus on
application-level correctness invariants rather than database-level race
conditions.
"""

import pytest

from app.models.pp_record import PPRecord
from app.models.pve_challenge_session import PvEChallengeSession
from app.models.token_transaction import TokenTransaction
from app.models.training_session import TrainingSession

from .conftest import (
    create_test_topic,
    create_test_user,
    make_cf_problems_response,
    mock_cf_service,
)

# ---------------------------------------------------------------------------
# Concurrent Token Spending
# ---------------------------------------------------------------------------


class TestConcurrentTokenSpending:
    """Test token balance integrity under rapid operations."""

    async def test_sequential_rapid_spends_correct_balance(self, db_session):
        """5 sequential spend_tokens calls of 10 each: 100 - 50 = 50."""
        from app.services import economy_service

        user = await create_test_user(db_session, tokens=100)
        await db_session.commit()

        # Spend 5 times, 10 tokens each
        for i in range(5):
            spent = await economy_service.spend_tokens(
                db_session,
                user,
                amount=10,
                tx_type=f"test_spend_{i}",
            )
            assert spent == 10

        await db_session.commit()

        # Verify final balance
        await db_session.refresh(user)
        assert user.tokens == 50, f"Expected 50 tokens after 5x10 spends, got {user.tokens}"

        # Verify 5 transactions recorded
        from sqlalchemy import select

        stmt = select(TokenTransaction).where(TokenTransaction.user_id == user.id)
        result = await db_session.execute(stmt)
        txns = list(result.scalars().all())
        assert len(txns) == 5, f"Expected 5 transactions, got {len(txns)}"

        # All should be negative
        assert all(t.amount == -10 for t in txns), "All transactions should be -10"

    async def test_insufficient_balance_raises_error(self, db_session):
        """Spending more than the balance raises BadRequestException."""
        from app.core.exceptions import BadRequestException
        from app.services import economy_service

        user = await create_test_user(db_session, tokens=100)
        await db_session.commit()

        with pytest.raises(BadRequestException, match="Insufficient tokens"):
            await economy_service.spend_tokens(
                db_session,
                user,
                amount=200,
                tx_type="overspend_test",
            )

        # Verify balance unchanged
        await db_session.refresh(user)
        assert user.tokens == 100, "Balance should remain unchanged after failed spend"

    async def test_spend_then_check_balance_consistency(self, db_session):
        """After multiple spend/award cycles, balance equals sum of all transactions."""
        from app.services import economy_service

        user = await create_test_user(db_session, tokens=0)
        await db_session.commit()

        # Award 50
        await economy_service.award_tokens(db_session, user, amount=50, tx_type="award_1")
        # Spend 20
        await economy_service.spend_tokens(db_session, user, amount=20, tx_type="spend_1")
        # Award 30
        await economy_service.award_tokens(db_session, user, amount=30, tx_type="award_2")
        # Spend 10
        await economy_service.spend_tokens(db_session, user, amount=10, tx_type="spend_2")

        await db_session.commit()

        # Balance should be 0 + 50 - 20 + 30 - 10 = 50
        await db_session.refresh(user)
        assert user.tokens == 50, f"Expected 50 tokens, got {user.tokens}"

        # Verify sum of transactions matches
        from sqlalchemy import func, select

        stmt = select(func.sum(TokenTransaction.amount)).where(TokenTransaction.user_id == user.id)
        result = await db_session.execute(stmt)
        tx_sum = result.scalar_one()
        assert tx_sum == 50, f"Sum of transactions should be 50, got {tx_sum}"

    async def test_balance_never_goes_negative(self, db_session):
        """Token balance invariant: tokens >= 0 after any sequence of operations."""
        from app.core.exceptions import BadRequestException
        from app.services import economy_service

        user = await create_test_user(db_session, tokens=15)
        await db_session.commit()

        # Spend 10 successfully
        await economy_service.spend_tokens(db_session, user, amount=10, tx_type="spend_1")

        # Try to spend 10 more (only 5 left) -- should fail
        with pytest.raises(BadRequestException):
            await economy_service.spend_tokens(db_session, user, amount=10, tx_type="spend_2")

        # Balance should be exactly 5
        await db_session.refresh(user)
        assert user.tokens == 5
        assert user.tokens >= 0, "Balance must never be negative"


# ---------------------------------------------------------------------------
# Concurrent Elo Settlement
# ---------------------------------------------------------------------------


class TestConcurrentEloSettlement:
    """Test that multiple PP/Elo record calls all apply correctly."""

    async def test_multiple_pp_records_all_applied(self, db_session):
        """Recording PP for 3 different problems creates 3 PPRecords and updates total PP."""
        from sqlalchemy import select

        from app.services.pp_service import PPConfig, PPService

        user = await create_test_user(db_session, elo=1200)
        await db_session.commit()

        config = PPConfig()
        pp_values = []

        # Record PP for 3 problems at different ratings
        for i, rating in enumerate([1200, 1500, 1800]):
            pid = f"prob_{i}"
            record = await PPService.record_pp(
                db_session,
                user.id,
                cf_problem_id=pid,
                problem_rating=rating,
                wa_count=0,
                time_spent=0.0,
                user_elo=user.elo,
            )
            pp_values.append(record.final_pp)

        await db_session.commit()

        # Verify 3 PPRecords exist
        stmt = select(PPRecord).where(PPRecord.user_id == user.id).order_by(PPRecord.final_pp.desc())
        result = await db_session.execute(stmt)
        records = list(result.scalars().all())
        assert len(records) == 3, f"Expected 3 PPRecords, got {len(records)}"

        # Verify total PP matches aggregation
        await db_session.refresh(user)
        expected_total = PPService.aggregate_total_pp(sorted(pp_values, reverse=True), config)
        assert abs(user.pp - expected_total) < 0.1, f"Expected PP ~{expected_total}, got {user.pp}"

        # Verify total PP is positive
        assert user.pp > 0

    async def test_pp_record_same_problem_id_uses_highest_rating(self, db_session):
        """Re-recording PP for the same problem with lower rating does not downgrade."""
        from sqlalchemy import select

        from app.services.pp_service import PPService

        user = await create_test_user(db_session)
        await db_session.commit()

        # First record at high rating
        await PPService.record_pp(db_session, user.id, cf_problem_id="1000A", problem_rating=1800)
        await db_session.commit()
        pp_after_high = user.pp

        # Second record at lower rating -- should NOT downgrade
        await PPService.record_pp(db_session, user.id, cf_problem_id="1000A", problem_rating=1200)
        await db_session.commit()
        pp_after_low = user.pp

        # PP should not decrease (same problem, lower rating = no update)
        assert pp_after_low >= pp_after_high, f"PP should not decrease: was {pp_after_high}, became {pp_after_low}"

        # Verify only 1 PPRecord for this problem
        stmt = select(PPRecord).where(
            PPRecord.user_id == user.id,
            PPRecord.cf_problem_id == "1000A",
        )
        result = await db_session.execute(stmt)
        records = list(result.scalars().all())
        assert len(records) == 1, "Should have exactly 1 PPRecord per problem"
        assert records[0].problem_rating == 1800, "Should keep the higher rating"


# ---------------------------------------------------------------------------
# Concurrent Session Creation
# ---------------------------------------------------------------------------


class TestConcurrentSessionCreation:
    """Test that duplicate session creation is properly prevented."""

    async def test_cannot_create_duplicate_pve_sessions(self, db_session):
        """Starting a second PvE session while one is active raises BadRequestException."""
        from sqlalchemy import select

        from app.core.exceptions import BadRequestException
        from app.services.pve_challenge_service import PvEChallengeService

        user = await create_test_user(db_session)
        await db_session.commit()

        cf = mock_cf_service(make_cf_problems_response(count=10, base_rating=1000))

        # Start first session
        result1 = await PvEChallengeService.start_challenge(db_session, user, cf)
        await db_session.commit()
        assert result1.status == "active"

        # Try to start second session -- should fail
        with pytest.raises(BadRequestException, match="already have an active"):
            await PvEChallengeService.start_challenge(db_session, user, cf)

        # Verify only 1 active session exists
        stmt = select(PvEChallengeSession).where(
            PvEChallengeSession.user_id == user.id,
            PvEChallengeSession.status == "active",
        )
        db_result = await db_session.execute(stmt)
        active_sessions = list(db_result.scalars().all())
        assert len(active_sessions) == 1, "Should have exactly 1 active PvE session"

    async def test_cannot_create_duplicate_training_sessions(self, db_session):
        """Starting a second training session for the same topic raises BadRequestException."""
        from sqlalchemy import select

        from app.core.exceptions import BadRequestException
        from app.services.training_service import TrainingService

        user = await create_test_user(db_session)
        topic = await create_test_topic(db_session)
        await db_session.commit()

        cf = mock_cf_service(make_cf_problems_response(count=5))

        # Start first session
        result1 = await TrainingService.start_training(db_session, user, topic.id, cf)
        await db_session.commit()
        assert result1.status == "active"

        # Try to start second session -- should fail
        with pytest.raises(BadRequestException, match="Already have an active"):
            await TrainingService.start_training(db_session, user, topic.id, cf)

        # Verify only 1 active session exists
        stmt = select(TrainingSession).where(
            TrainingSession.user_id == user.id,
            TrainingSession.topic_id == topic.id,
            TrainingSession.status == "active",
        )
        db_result = await db_session.execute(stmt)
        active_sessions = list(db_result.scalars().all())
        assert len(active_sessions) == 1, "Should have exactly 1 active training session"

    async def test_can_start_new_pve_session_after_completing_previous(self, db_session):
        """After completing a PvE session, user can start a new one."""
        from app.services.pve_challenge_service import PvEChallengeService

        user = await create_test_user(db_session)
        await db_session.commit()

        cf = mock_cf_service(make_cf_problems_response(count=10, base_rating=1000))

        # Start and complete first session
        result1 = await PvEChallengeService.start_challenge(db_session, user, cf)
        await db_session.commit()

        await PvEChallengeService.submit_result(
            db_session,
            user,
            session_id=result1.session_id,
            solved=True,
            time_spent=60.0,
            attempts=1,
            error_count=0,
            cf_service=cf,
        )
        await db_session.commit()

        # Start new session -- should succeed
        result2 = await PvEChallengeService.start_challenge(db_session, user, cf)
        await db_session.commit()
        assert result2.status == "active"
        assert result2.session_id != result1.session_id, "New session should have different ID"

    async def test_can_start_new_training_session_after_abandoning_previous(self, db_session):
        """After abandoning a training session, user can start a new one for the same topic."""
        from app.services.training_service import TrainingService

        user = await create_test_user(db_session)
        topic = await create_test_topic(db_session)
        await db_session.commit()

        cf = mock_cf_service(make_cf_problems_response(count=5))

        # Start and abandon first session
        result1 = await TrainingService.start_training(db_session, user, topic.id, cf)
        await db_session.commit()

        await TrainingService.abandon_training(db_session, user, result1.id)
        await db_session.commit()

        # Start new session -- should succeed
        result2 = await TrainingService.start_training(db_session, user, topic.id, cf)
        await db_session.commit()
        assert result2.status == "active"
        assert result2.id != result1.id, "New session should have different ID"
