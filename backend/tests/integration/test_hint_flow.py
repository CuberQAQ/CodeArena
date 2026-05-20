"""Integration test: hint system full flow.

Tests hint status checking, progressive unlocking, content retrieval,
purchase history, and token deduction.
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from .conftest import (
    _TestHintPurchase,
    _TestUser,
    create_test_user,
)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestHintStatus:
    """Test checking hint status for a problem."""

    async def test_no_hints_unlocked(self, db_session):
        """For a problem with no hints, status shows no unlocked levels."""
        from app.services.hint_service import HintService

        user = await create_test_user(db_session)
        await db_session.commit()

        status = await HintService.get_hint_status(
            db_session, user, problem_id="1000A", problem_rating=1200
        )
        assert status.problem_id == "1000A"
        assert status.unlocked_levels == []
        assert status.next_level == 1
        assert status.next_level_price is not None

    async def test_status_shows_prices_for_all_levels(self, db_session):
        """Status shows prices for all three hint levels."""
        from app.services.hint_service import HintService

        user = await create_test_user(db_session)
        await db_session.commit()

        status = await HintService.get_hint_status(
            db_session, user, problem_id="1000A", problem_rating=1200
        )
        assert len(status.prices) == 3
        # Prices should increase with level
        assert status.prices[0].tokens < status.prices[1].tokens < status.prices[2].tokens

    async def test_status_shows_elo_decay_preview(self, db_session):
        """Status shows Elo decay multipliers for each level."""
        from app.services.hint_service import HintService

        user = await create_test_user(db_session)
        await db_session.commit()

        status = await HintService.get_hint_status(
            db_session, user, problem_id="1000A", problem_rating=1200
        )
        assert len(status.elo_decay_preview) == 3
        assert status.elo_decay_preview[0].multiplier == 0.75
        assert status.elo_decay_preview[1].multiplier == 0.50
        assert status.elo_decay_preview[2].multiplier == 0.25


class TestHintUnlock:
    """Test unlocking hint levels."""

    async def test_unlock_level_1(self, db_session):
        """Can unlock hint level 1 for a problem."""
        from app.services.hint_service import HintService

        user = await create_test_user(db_session, tokens=100)
        await db_session.commit()

        result = await HintService.unlock_hint(
            db_session, user, problem_id="1000A", problem_rating=1200, level=1
        )
        assert result.level == 1
        assert result.tokens_spent > 0
        assert result.tokens_remaining == 100 - result.tokens_spent

    async def test_unlock_level_2_after_level_1(self, db_session):
        """Can unlock level 2 after unlocking level 1."""
        from app.services.hint_service import HintService

        user = await create_test_user(db_session, tokens=100)
        await db_session.commit()

        await HintService.unlock_hint(
            db_session, user, problem_id="1000A", problem_rating=1200, level=1
        )
        result = await HintService.unlock_hint(
            db_session, user, problem_id="1000A", problem_rating=1200, level=2
        )
        assert result.level == 2

    async def test_unlock_level_3_after_levels_1_and_2(self, db_session):
        """Can unlock level 3 after unlocking levels 1 and 2."""
        from app.services.hint_service import HintService

        user = await create_test_user(db_session, tokens=200)
        await db_session.commit()

        await HintService.unlock_hint(
            db_session, user, problem_id="1000A", problem_rating=1200, level=1
        )
        await HintService.unlock_hint(
            db_session, user, problem_id="1000A", problem_rating=1200, level=2
        )
        result = await HintService.unlock_hint(
            db_session, user, problem_id="1000A", problem_rating=1200, level=3
        )
        assert result.level == 3

    async def test_cannot_skip_level_1(self, db_session):
        """Cannot unlock level 2 without first unlocking level 1."""
        from app.services.hint_service import HintService

        user = await create_test_user(db_session, tokens=100)
        await db_session.commit()

        with pytest.raises(Exception, match="Must unlock hint level 1"):
            await HintService.unlock_hint(
                db_session, user, problem_id="1000A", problem_rating=1200, level=2
            )

    async def test_cannot_skip_level_2(self, db_session):
        """Cannot unlock level 3 without first unlocking level 2."""
        from app.services.hint_service import HintService

        user = await create_test_user(db_session, tokens=100)
        await db_session.commit()

        await HintService.unlock_hint(
            db_session, user, problem_id="1000A", problem_rating=1200, level=1
        )

        with pytest.raises(Exception, match="Must unlock hint levels 1 and 2"):
            await HintService.unlock_hint(
                db_session, user, problem_id="1000A", problem_rating=1200, level=3
            )

    async def test_cannot_reunlock_same_level(self, db_session):
        """Cannot re-unlock an already unlocked level."""
        from app.services.hint_service import HintService

        user = await create_test_user(db_session, tokens=100)
        await db_session.commit()

        await HintService.unlock_hint(
            db_session, user, problem_id="1000A", problem_rating=1200, level=1
        )

        with pytest.raises(Exception, match="already unlocked"):
            await HintService.unlock_hint(
                db_session, user, problem_id="1000A", problem_rating=1200, level=1
            )

    async def test_insufficient_tokens_fails(self, db_session):
        """Cannot unlock if user has insufficient tokens."""
        from app.services.hint_service import HintService

        user = await create_test_user(db_session, tokens=0)
        await db_session.commit()

        with pytest.raises(Exception, match="Insufficient tokens"):
            await HintService.unlock_hint(
                db_session, user, problem_id="1000A", problem_rating=1200, level=1
            )

    async def test_unlock_deducts_tokens(self, db_session):
        """Unlocking a hint deducts the correct number of tokens."""
        from app.services.hint_service import HintService, get_hint_prices

        user = await create_test_user(db_session, tokens=100)
        await db_session.commit()

        prices = get_hint_prices(1200)
        expected_cost = prices[0]

        await HintService.unlock_hint(
            db_session, user, problem_id="1000A", problem_rating=1200, level=1
        )

        assert user.tokens == 100 - expected_cost

    async def test_invalid_level_fails(self, db_session):
        """Invalid level (0, 4) raises BadRequestException."""
        from app.services.hint_service import HintService

        user = await create_test_user(db_session, tokens=100)
        await db_session.commit()

        with pytest.raises(Exception, match="must be 1, 2, or 3"):
            await HintService.unlock_hint(
                db_session, user, problem_id="1000A", problem_rating=1200, level=0
            )

        with pytest.raises(Exception, match="must be 1, 2, or 3"):
            await HintService.unlock_hint(
                db_session, user, problem_id="1000A", problem_rating=1200, level=4
            )


class TestHintContent:
    """Test retrieving hint content."""

    async def test_get_content_for_unlocked_level(self, db_session):
        """Can retrieve content for an unlocked hint level."""
        from app.services.hint_service import HintService

        user = await create_test_user(db_session, tokens=100)
        await db_session.commit()

        await HintService.unlock_hint(
            db_session, user, problem_id="1000A", problem_rating=1200, level=1
        )

        content = await HintService.get_hint_content(
            db_session, user, problem_id="1000A", level=1, problem_rating=1200
        )
        assert content.unlocked is True
        assert len(content.content) > 0

    async def test_cannot_get_content_for_locked_level(self, db_session):
        """Cannot retrieve content for a locked hint level."""
        from app.services.hint_service import HintService

        user = await create_test_user(db_session, tokens=100)
        await db_session.commit()

        # Level 2 is not unlocked
        with pytest.raises(Exception, match="not unlocked"):
            await HintService.get_hint_content(
                db_session, user, problem_id="1000A", level=2, problem_rating=1200
            )


class TestHintHistory:
    """Test hint purchase history."""

    async def test_empty_history_for_new_problem(self, db_session):
        """No history for a problem with no hint purchases."""
        from app.services.hint_service import HintService

        user = await create_test_user(db_session)
        await db_session.commit()

        history = await HintService.get_hint_history(
            db_session, user, problem_id="1000A"
        )
        assert history.total_spent == 0
        assert len(history.purchases) == 0

    async def test_history_shows_purchases(self, db_session):
        """History shows all hint purchases for a problem."""
        from app.services.hint_service import HintService

        user = await create_test_user(db_session, tokens=200)
        await db_session.commit()

        await HintService.unlock_hint(
            db_session, user, problem_id="1000A", problem_rating=1200, level=1
        )
        await HintService.unlock_hint(
            db_session, user, problem_id="1000A", problem_rating=1200, level=2
        )

        history = await HintService.get_hint_history(
            db_session, user, problem_id="1000A"
        )
        assert len(history.purchases) == 2
        assert history.total_spent > 0
        levels = [p.hint_level for p in history.purchases]
        assert 1 in levels
        assert 2 in levels


class TestHintPricing:
    """Test hint pricing tiers."""

    def test_gray_problem_pricing(self):
        """Gray problems (800-1199) have lowest prices."""
        from app.services.hint_service import get_hint_prices
        prices = get_hint_prices(800)
        assert prices == [3, 10, 20]

    def test_green_problem_pricing(self):
        """Green problems (1200-1399) have moderate prices."""
        from app.services.hint_service import get_hint_prices
        prices = get_hint_prices(1200)
        assert prices == [5, 15, 30]

    def test_cyan_problem_pricing(self):
        """Cyan problems (1400-1599) have moderate prices."""
        from app.services.hint_service import get_hint_prices
        prices = get_hint_prices(1500)
        assert prices == [6, 18, 35]

    def test_blue_problem_pricing(self):
        """Blue problems (1600-1899) have higher prices."""
        from app.services.hint_service import get_hint_prices
        prices = get_hint_prices(1700)
        assert prices == [8, 20, 40]

    def test_purple_problem_pricing(self):
        """Purple problems (1900-2099) have even higher prices."""
        from app.services.hint_service import get_hint_prices
        prices = get_hint_prices(2000)
        assert prices == [10, 25, 50]

    def test_orange_problem_pricing(self):
        """Orange problems (2100-2399) have higher prices."""
        from app.services.hint_service import get_hint_prices
        prices = get_hint_prices(2200)
        assert prices == [12, 28, 55]

    def test_red_problem_pricing(self):
        """Red problems (2400+) have highest prices."""
        from app.services.hint_service import get_hint_prices
        prices = get_hint_prices(2500)
        assert prices == [15, 30, 60]


class TestEloDecayMultiplier:
    """Test Elo decay multiplier calculation."""

    def test_no_hints_no_decay(self):
        """Level 0 gives no decay (multiplier 1.0)."""
        from app.services.hint_service import get_elo_decay_multiplier
        assert get_elo_decay_multiplier(0) == 1.0

    def test_level_1_decay(self):
        from app.services.hint_service import get_elo_decay_multiplier
        assert get_elo_decay_multiplier(1) == 0.75

    def test_level_2_decay(self):
        from app.services.hint_service import get_elo_decay_multiplier
        assert get_elo_decay_multiplier(2) == 0.50

    def test_level_3_decay(self):
        from app.services.hint_service import get_elo_decay_multiplier
        assert get_elo_decay_multiplier(3) == 0.25
