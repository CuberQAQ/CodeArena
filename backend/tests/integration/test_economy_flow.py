"""Integration test: economy system full flow.

Tests token earning (AC reward), spending (hint purchase), balance tracking,
daily cap enforcement, and daily reset.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.models.token_transaction import TokenTransaction

from .conftest import (
    create_test_user,
)

# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestTokenAward:
    """Test awarding tokens."""

    async def test_award_tokens_increases_balance(self, db_session):
        """Awarding tokens increases the user's balance."""
        from app.services import economy_service

        user = await create_test_user(db_session, tokens=0)
        await db_session.commit()

        awarded = await economy_service.award_tokens(db_session, user, amount=10, tx_type="test_reward")
        assert awarded == 10
        assert user.tokens == 10
        assert user.daily_tokens_earned == 10

    async def test_award_tokens_creates_transaction(self, db_session):
        """Awarding tokens creates a transaction record."""
        from app.services import economy_service

        user = await create_test_user(db_session)
        await db_session.commit()

        await economy_service.award_tokens(
            db_session,
            user,
            amount=20,
            tx_type="challenge_reward",
            reference_type="challenge_session",
            reference_id=uuid.uuid4(),
        )

        from sqlalchemy import select as sel

        stmt = sel(TokenTransaction).where(TokenTransaction.user_id == user.id)
        result = await db_session.execute(stmt)
        txns = list(result.scalars().all())
        assert len(txns) == 1
        assert txns[0].amount == 20
        assert txns[0].type == "challenge_reward"
        assert txns[0].balance_after == 20

    async def test_award_tokens_respects_daily_cap(self, db_session):
        """Tokens cannot exceed the daily cap."""
        from app.services import economy_service

        user = await create_test_user(db_session, tokens=0)
        await db_session.commit()

        # Award up to the cap
        cap = economy_service.DAILY_TOKEN_CAP
        awarded_first = await economy_service.award_tokens(db_session, user, amount=cap, tx_type="test_reward")
        assert awarded_first == cap

        # Try to award more -- should get 0
        awarded_second = await economy_service.award_tokens(db_session, user, amount=10, tx_type="test_reward")
        assert awarded_second == 0
        assert user.tokens == cap

    async def test_award_tokens_partial_when_near_cap(self, db_session):
        """Tokens are partially awarded when near the daily cap."""
        from app.services import economy_service

        user = await create_test_user(db_session, tokens=0)
        await db_session.commit()

        cap = economy_service.DAILY_TOKEN_CAP

        # Award most of the cap
        await economy_service.award_tokens(db_session, user, amount=cap - 5, tx_type="test_reward")

        # Try to award 10 more -- only 5 should be awarded
        awarded = await economy_service.award_tokens(db_session, user, amount=10, tx_type="test_reward")
        assert awarded == 5
        assert user.tokens == cap

    async def test_award_zero_or_negative_fails(self, db_session):
        """Awarding 0 or negative tokens raises BadRequestException."""
        from app.services import economy_service

        user = await create_test_user(db_session)
        await db_session.commit()

        with pytest.raises(Exception, match="must be positive"):
            await economy_service.award_tokens(db_session, user, amount=0, tx_type="test")

        with pytest.raises(Exception, match="must be positive"):
            await economy_service.award_tokens(db_session, user, amount=-5, tx_type="test")


class TestTokenSpend:
    """Test spending tokens."""

    async def test_spend_tokens_decreases_balance(self, db_session):
        """Spending tokens decreases the user's balance."""
        from app.services import economy_service

        user = await create_test_user(db_session, tokens=50)
        await db_session.commit()

        spent = await economy_service.spend_tokens(db_session, user, amount=10, tx_type="hint_purchase")
        assert spent == 10
        assert user.tokens == 40

    async def test_spend_tokens_creates_negative_transaction(self, db_session):
        """Spending tokens creates a negative transaction record."""
        from app.services import economy_service

        user = await create_test_user(db_session, tokens=50)
        await db_session.commit()

        await economy_service.spend_tokens(db_session, user, amount=15, tx_type="hint_purchase")

        from sqlalchemy import select as sel

        stmt = sel(TokenTransaction).where(TokenTransaction.user_id == user.id)
        result = await db_session.execute(stmt)
        txns = list(result.scalars().all())
        assert len(txns) == 1
        assert txns[0].amount == -15
        assert txns[0].balance_after == 35

    async def test_spend_insufficient_tokens_fails(self, db_session):
        """Spending more tokens than available raises BadRequestException."""
        from app.services import economy_service

        user = await create_test_user(db_session, tokens=5)
        await db_session.commit()

        with pytest.raises(Exception, match="Insufficient tokens"):
            await economy_service.spend_tokens(db_session, user, amount=10, tx_type="hint_purchase")

    async def test_spend_zero_or_negative_fails(self, db_session):
        """Spending 0 or negative tokens raises BadRequestException."""
        from app.services import economy_service

        user = await create_test_user(db_session, tokens=50)
        await db_session.commit()

        with pytest.raises(Exception, match="must be positive"):
            await economy_service.spend_tokens(db_session, user, amount=0, tx_type="test")

        with pytest.raises(Exception, match="must be positive"):
            await economy_service.spend_tokens(db_session, user, amount=-5, tx_type="test")


class TestDailyReset:
    """Test daily token reset."""

    async def test_daily_reset_clears_counter(self, db_session):
        """A new day resets daily_tokens_earned."""
        from app.services import economy_service

        user = await create_test_user(db_session, tokens=0)
        await db_session.commit()

        # Award some tokens
        await economy_service.award_tokens(db_session, user, amount=50, tx_type="test_reward")
        assert user.daily_tokens_earned == 50

        # Simulate next day by setting reset_at to yesterday
        user.daily_tokens_reset_at = datetime.now(UTC) - timedelta(days=1)
        await db_session.flush()

        # Check and reset should clear the counter
        await economy_service.check_and_reset_daily(db_session, user)
        assert user.daily_tokens_earned == 0

    async def test_daily_reset_allows_new_earning(self, db_session):
        """After daily reset, tokens can be earned again."""
        from app.services import economy_service

        user = await create_test_user(db_session, tokens=0)
        await db_session.commit()

        cap = economy_service.DAILY_TOKEN_CAP

        # Fill the cap
        await economy_service.award_tokens(db_session, user, amount=cap, tx_type="test_reward")
        assert user.daily_tokens_earned == cap

        # Simulate next day
        user.daily_tokens_reset_at = datetime.now(UTC) - timedelta(days=1)
        await db_session.flush()

        # Award again -- should work after reset
        awarded = await economy_service.award_tokens(db_session, user, amount=10, tx_type="test_reward")
        assert awarded == 10


class TestGetBalance:
    """Test balance retrieval."""

    async def test_get_balance_returns_current_state(self, db_session):
        """get_balance returns correct token count and daily info."""
        from app.services import economy_service

        user = await create_test_user(db_session, tokens=30)
        await db_session.commit()

        balance = await economy_service.get_balance(db_session, user)
        assert balance["tokens"] == 30
        assert balance["daily_tokens_earned"] == 0
        assert balance["daily_cap"] == economy_service.DAILY_TOKEN_CAP
        assert balance["daily_remaining"] == economy_service.DAILY_TOKEN_CAP


class TestGetTransactions:
    """Test transaction history retrieval."""

    async def test_get_transactions_paginated(self, db_session):
        """get_transactions returns paginated results."""
        from app.services import economy_service

        user = await create_test_user(db_session, tokens=0)
        await db_session.commit()

        # Create several transactions
        for i in range(5):
            await economy_service.award_tokens(db_session, user, amount=10, tx_type=f"test_type_{i}")

        items, total = await economy_service.get_transactions(db_session, user.id, limit=3, offset=0)
        assert total == 5
        assert len(items) == 3

        # Second page
        items2, _ = await economy_service.get_transactions(db_session, user.id, limit=3, offset=3)
        assert len(items2) == 2


class TestGetDailyStatus:
    """Test daily status retrieval."""

    async def test_get_daily_status_shows_breakdown(self, db_session):
        """get_daily_status returns breakdown by transaction type."""
        from app.services import economy_service

        user = await create_test_user(db_session, tokens=0)
        await db_session.commit()

        await economy_service.award_tokens(db_session, user, amount=10, tx_type="challenge_reward")
        await economy_service.award_tokens(db_session, user, amount=5, tx_type="training_reward")

        status = await economy_service.get_daily_status(db_session, user)
        assert status["daily_tokens_earned"] == 15
        assert "breakdown" in status
        assert status["breakdown"].get("challenge_reward") == 10
        assert status["breakdown"].get("training_reward") == 5


class TestTokenTiers:
    """Test token tier calculation."""

    def test_tokens_for_rating_gray(self):
        """Rating 800-1199 gives gray tier (10 tokens)."""
        from app.services.economy_service import tokens_for_rating

        assert tokens_for_rating(800) == 10
        assert tokens_for_rating(1000) == 10

    def test_tokens_for_rating_green(self):
        """Rating 1200-1399 gives green tier (20 tokens)."""
        from app.services.economy_service import tokens_for_rating

        assert tokens_for_rating(1200) == 20
        assert tokens_for_rating(1300) == 20

    def test_tokens_for_rating_cyan(self):
        """Rating 1400-1599 gives cyan tier (25 tokens)."""
        from app.services.economy_service import tokens_for_rating

        assert tokens_for_rating(1400) == 25
        assert tokens_for_rating(1500) == 25

    def test_tokens_for_rating_blue(self):
        """Rating 1600-1899 gives blue tier (35 tokens)."""
        from app.services.economy_service import tokens_for_rating

        assert tokens_for_rating(1600) == 35
        assert tokens_for_rating(1800) == 35

    def test_tokens_for_rating_purple(self):
        """Rating 1900-2099 gives purple tier (45 tokens)."""
        from app.services.economy_service import tokens_for_rating

        assert tokens_for_rating(1900) == 45
        assert tokens_for_rating(2000) == 45

    def test_tokens_for_rating_orange(self):
        """Rating 2100-2399 gives orange tier (55 tokens)."""
        from app.services.economy_service import tokens_for_rating

        assert tokens_for_rating(2100) == 55
        assert tokens_for_rating(2250) == 55

    def test_tokens_for_rating_red(self):
        """Rating 2400+ gives red tier (65 tokens)."""
        from app.services.economy_service import tokens_for_rating

        assert tokens_for_rating(2400) == 65
        assert tokens_for_rating(3000) == 65
