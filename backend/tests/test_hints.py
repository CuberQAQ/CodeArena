"""Tests for the hint system: pricing, sequential unlocking, Elo decay, and purchase history.

Uses lightweight SQLite-compatible test models and mocks for external services.
The key technique is patching the production model references in hint_service
with test-compatible models so SQLAlchemy queries target the SQLite tables.
"""

import uuid
from datetime import datetime
from unittest.mock import patch

import pytest
from sqlalchemy import Boolean, DateTime, Float, Integer, String, event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core.exceptions import BadRequestException
from app.services import economy_service as economy_svc_module
from app.services import hint_service as hint_svc_module
from app.services.hint_service import HintService, get_elo_decay_multiplier, get_hint_prices

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
    cf_handle: Mapped[str | None] = mapped_column(String(100), nullable=True)
    elo: Mapped[int] = mapped_column(Integer, default=1200, nullable=False)
    pp: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    daily_tokens_earned: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    daily_tokens_reset_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class _TestHintPurchase(_TestBase):
    __tablename__ = "hint_purchases"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    problem_id: Mapped[str] = mapped_column(String(50), nullable=False)
    problem_rating: Mapped[int] = mapped_column(Integer, nullable=False)
    hint_level: Mapped[int] = mapped_column(Integer, nullable=False)
    tokens_cost: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


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


async def _mock_spend_tokens(db, user, amount, tx_type=None, reference_type=None, reference_id=None):
    """Side-effect mock: deduct tokens from user, create transaction record."""
    user.tokens -= amount
    tx = _TestTokenTransaction(
        user_id=user.id,
        amount=-amount,
        type=tx_type or "hint_purchase",
        reference_type=reference_type,
        reference_id=reference_id,
        balance_after=user.tokens,
    )
    db.add(tx)
    await db.flush()
    return amount


@pytest.fixture
async def db(async_engine):
    session_factory = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as session:
        with (
            patch.object(hint_svc_module, "HintPurchase", _TestHintPurchase),
            patch.object(economy_svc_module, "spend_tokens", _mock_spend_tokens),
        ):
            yield session


def _make_user(**kwargs) -> _TestUser:
    """Create a test user with sensible defaults."""
    defaults = {
        "username": f"user_{uuid.uuid4().hex[:8]}",
        "email": f"{uuid.uuid4().hex[:8]}@test.com",
        "password_hash": "hash",
        "elo": 1200,
        "tokens": 100,
    }
    defaults.update(kwargs)
    return _TestUser(**defaults)


# ===========================================================================
# Test: Hint pricing tiers
# ===========================================================================


class TestHintPricing:
    """Verify hint prices match the specification."""

    @pytest.mark.parametrize(
        "rating,expected_prices",
        [
            (800, [3, 10, 20]),      # gray
            (900, [3, 10, 20]),      # gray
            (1099, [3, 10, 20]),     # gray
            (1100, [5, 15, 30]),     # green
            (1200, [5, 15, 30]),     # green
            (1399, [5, 15, 30]),     # green
            (1400, [8, 20, 40]),     # blue
            (1500, [8, 20, 40]),     # blue
            (1699, [8, 20, 40]),     # blue
            (1700, [10, 25, 50]),    # purple
            (1800, [10, 25, 50]),    # purple
            (1999, [10, 25, 50]),    # purple
            (2000, [15, 30, 60]),    # yellow/red
            (2500, [15, 30, 60]),    # yellow/red
            (3000, [15, 30, 60]),    # yellow/red
        ],
    )
    def test_prices_by_rating(self, rating, expected_prices):
        """Prices match the specification table."""
        assert get_hint_prices(rating) == expected_prices

    @pytest.mark.parametrize(
        "rating,expected_total",
        [
            (800, 33),    # gray: 3+10+20
            (1100, 50),   # green: 5+15+30
            (1400, 68),   # blue: 8+20+40
            (1700, 85),   # purple: 10+25+50
            (2000, 105),  # yellow/red: 15+30+60
        ],
    )
    def test_cumulative_prices(self, rating, expected_total):
        """Cumulative cost for all 3 levels matches the specification."""
        prices = get_hint_prices(rating)
        assert sum(prices) == expected_total


# ===========================================================================
# Test: Elo decay multipliers
# ===========================================================================


class TestEloDecay:
    """Verify Elo decay multipliers."""

    def test_no_decay_for_level_0(self):
        """No hint used: multiplier is 1.0."""
        assert get_elo_decay_multiplier(0) == 1.0

    def test_level_1_decay(self):
        """Level 1: Elo gain * 0.75."""
        assert get_elo_decay_multiplier(1) == 0.75

    def test_level_2_decay(self):
        """Level 2: Elo gain * 0.50."""
        assert get_elo_decay_multiplier(2) == 0.50

    def test_level_3_decay(self):
        """Level 3: Elo gain * 0.25."""
        assert get_elo_decay_multiplier(3) == 0.25

    def test_negative_level_no_decay(self):
        """Negative levels default to no decay."""
        assert get_elo_decay_multiplier(-1) == 1.0


# ===========================================================================
# Test: Get hint status
# ===========================================================================


class TestGetHintStatus:
    """Verify hint status retrieval."""

    @pytest.mark.asyncio
    async def test_no_hints_unlocked(self, db):
        """Status shows no unlocked levels for a new problem."""
        user = _make_user()
        db.add(user)
        await db.flush()

        status = await HintService.get_hint_status(db, user, "1234A", 1200)

        assert status.problem_id == "1234A"
        assert status.problem_rating == 1200
        assert status.unlocked_levels == []
        assert status.next_level == 1
        assert status.next_level_price == 5  # green tier

    @pytest.mark.asyncio
    async def test_status_shows_all_prices(self, db):
        """Status shows prices for all 3 levels."""
        user = _make_user()
        db.add(user)
        await db.flush()

        status = await HintService.get_hint_status(db, user, "1234A", 1500)

        assert len(status.prices) == 3
        assert status.prices[0].level == 1
        assert status.prices[0].tokens == 8  # blue tier
        assert status.prices[1].level == 2
        assert status.prices[1].tokens == 20
        assert status.prices[2].level == 3
        assert status.prices[2].tokens == 40

    @pytest.mark.asyncio
    async def test_status_shows_elo_decay(self, db):
        """Status shows Elo decay preview for all levels."""
        user = _make_user()
        db.add(user)
        await db.flush()

        status = await HintService.get_hint_status(db, user, "1234A", 1200)

        assert len(status.elo_decay_preview) == 3
        assert status.elo_decay_preview[0].level == 1
        assert status.elo_decay_preview[0].multiplier == 0.75
        assert status.elo_decay_preview[1].level == 2
        assert status.elo_decay_preview[1].multiplier == 0.50
        assert status.elo_decay_preview[2].level == 3
        assert status.elo_decay_preview[2].multiplier == 0.25

    @pytest.mark.asyncio
    async def test_status_after_unlocking_level_1(self, db):
        """After unlocking level 1, next level is 2."""
        user = _make_user(tokens=100)
        db.add(user)
        await db.flush()

        await HintService.unlock_hint(db, user, "1234A", 1200, 1)
        await db.flush()

        status = await HintService.get_hint_status(db, user, "1234A", 1200)

        assert status.unlocked_levels == [1]
        assert status.next_level == 2
        assert status.next_level_price == 15  # green tier level 2

    @pytest.mark.asyncio
    async def test_status_all_unlocked(self, db):
        """After unlocking all levels, no next level available."""
        user = _make_user(tokens=200)
        db.add(user)
        await db.flush()

        await HintService.unlock_hint(db, user, "1234A", 1200, 1)
        await db.commit()
        await HintService.unlock_hint(db, user, "1234A", 1200, 2)
        await db.commit()
        await HintService.unlock_hint(db, user, "1234A", 1200, 3)
        await db.commit()

        status = await HintService.get_hint_status(db, user, "1234A", 1200)

        assert status.unlocked_levels == [1, 2, 3]
        assert status.next_level is None
        assert status.next_level_price is None


# ===========================================================================
# Test: Sequential unlocking
# ===========================================================================


class TestSequentialUnlock:
    """Verify hint unlocking rules."""

    @pytest.mark.asyncio
    async def test_unlock_level_1_success(self, db):
        """Can unlock level 1."""
        user = _make_user(tokens=100)
        db.add(user)
        await db.flush()

        result = await HintService.unlock_hint(db, user, "1234A", 1200, 1)

        assert result.level == 1
        assert result.tokens_spent == 5  # green tier
        assert result.tokens_remaining == 95

    @pytest.mark.asyncio
    async def test_unlock_level_2_after_1(self, db):
        """Can unlock level 2 after level 1."""
        user = _make_user(tokens=100)
        db.add(user)
        await db.flush()

        await HintService.unlock_hint(db, user, "1234A", 1200, 1)
        await db.flush()

        result = await HintService.unlock_hint(db, user, "1234A", 1200, 2)

        assert result.level == 2
        assert result.tokens_spent == 15
        assert result.tokens_remaining == 80

    @pytest.mark.asyncio
    async def test_unlock_level_3_after_2(self, db):
        """Can unlock level 3 after level 2."""
        user = _make_user(tokens=100)
        db.add(user)
        await db.flush()

        await HintService.unlock_hint(db, user, "1234A", 1200, 1)
        await db.flush()
        await HintService.unlock_hint(db, user, "1234A", 1200, 2)
        await db.flush()

        result = await HintService.unlock_hint(db, user, "1234A", 1200, 3)

        assert result.level == 3
        assert result.tokens_spent == 30
        assert result.tokens_remaining == 50

    @pytest.mark.asyncio
    async def test_cannot_skip_to_level_2(self, db):
        """Cannot unlock level 2 without first unlocking level 1."""
        user = _make_user(tokens=100)
        db.add(user)
        await db.flush()

        with pytest.raises(BadRequestException, match="Must unlock hint level 1"):
            await HintService.unlock_hint(db, user, "1234A", 1200, 2)

    @pytest.mark.asyncio
    async def test_cannot_skip_to_level_3(self, db):
        """Cannot unlock level 3 without first unlocking level 2."""
        user = _make_user(tokens=100)
        db.add(user)
        await db.flush()

        with pytest.raises(BadRequestException, match="Must unlock hint levels 1 and 2"):
            await HintService.unlock_hint(db, user, "1234A", 1200, 3)

    @pytest.mark.asyncio
    async def test_cannot_reunlock_same_level(self, db):
        """Cannot unlock the same level twice."""
        user = _make_user(tokens=100)
        db.add(user)
        await db.flush()

        await HintService.unlock_hint(db, user, "1234A", 1200, 1)
        await db.flush()

        with pytest.raises(BadRequestException, match="already unlocked"):
            await HintService.unlock_hint(db, user, "1234A", 1200, 1)

    @pytest.mark.asyncio
    async def test_reunlock_no_deduction(self, db):
        """Re-unlocking does not deduct tokens."""
        user = _make_user(tokens=100)
        db.add(user)
        await db.flush()

        await HintService.unlock_hint(db, user, "1234A", 1200, 1)
        await db.flush()

        tokens_after_first = user.tokens

        with pytest.raises(BadRequestException):
            await HintService.unlock_hint(db, user, "1234A", 1200, 1)

        # Tokens should be unchanged after failed re-unlock
        assert user.tokens == tokens_after_first

    @pytest.mark.asyncio
    async def test_invalid_level_rejected(self, db):
        """Levels outside 1-3 are rejected."""
        user = _make_user(tokens=100)
        db.add(user)
        await db.flush()

        with pytest.raises(BadRequestException, match="must be 1, 2, or 3"):
            await HintService.unlock_hint(db, user, "1234A", 1200, 0)

        with pytest.raises(BadRequestException, match="must be 1, 2, or 3"):
            await HintService.unlock_hint(db, user, "1234A", 1200, 4)


# ===========================================================================
# Test: Token deduction
# ===========================================================================


class TestTokenDeduction:
    """Verify token deduction for hint purchases."""

    @pytest.mark.asyncio
    async def test_sufficient_balance_deducted(self, db):
        """Tokens are correctly deducted."""
        user = _make_user(tokens=100)
        db.add(user)
        await db.flush()

        await HintService.unlock_hint(db, user, "1234A", 1200, 1)

        assert user.tokens == 95  # 100 - 5 (green tier level 1)

    @pytest.mark.asyncio
    async def test_insufficient_balance_rejected(self, db):
        """Unlocking is rejected when balance is insufficient."""
        user = _make_user(tokens=3)
        db.add(user)
        await db.flush()

        with pytest.raises(BadRequestException, match="Insufficient tokens"):
            await HintService.unlock_hint(db, user, "1234A", 1200, 1)

    @pytest.mark.asyncio
    async def test_insufficient_balance_no_deduction(self, db):
        """Insufficient balance does not change token count."""
        user = _make_user(tokens=3)
        db.add(user)
        await db.flush()

        with pytest.raises(BadRequestException):
            await HintService.unlock_hint(db, user, "1234A", 1200, 1)

        assert user.tokens == 3

    @pytest.mark.asyncio
    async def test_different_tiers_different_prices(self, db):
        """Different problem ratings charge different prices."""
        user1 = _make_user(tokens=200)
        user2 = _make_user(tokens=200)
        db.add_all([user1, user2])
        await db.flush()

        # Gray problem (rating 900)
        await HintService.unlock_hint(db, user1, "999A", 900, 1)
        # Green problem (rating 1200)
        await HintService.unlock_hint(db, user2, "888A", 1200, 1)

        assert user1.tokens == 197  # 200 - 3 (gray level 1)
        assert user2.tokens == 195  # 200 - 5 (green level 1)

    @pytest.mark.asyncio
    async def test_exact_balance_accepted(self, db):
        """Can unlock when balance exactly matches the cost."""
        user = _make_user(tokens=5)
        db.add(user)
        await db.flush()

        result = await HintService.unlock_hint(db, user, "1234A", 1200, 1)

        assert result.tokens_spent == 5
        assert user.tokens == 0

    @pytest.mark.asyncio
    async def test_cumulative_deduction(self, db):
        """Unlocking all 3 levels deducts the cumulative cost."""
        user = _make_user(tokens=200)
        db.add(user)
        await db.flush()

        await HintService.unlock_hint(db, user, "1234A", 1200, 1)
        await db.flush()
        await HintService.unlock_hint(db, user, "1234A", 1200, 2)
        await db.flush()
        await HintService.unlock_hint(db, user, "1234A", 1200, 3)
        await db.flush()

        # Green tier: 5 + 15 + 30 = 50
        assert user.tokens == 150


# ===========================================================================
# Test: Hint content
# ===========================================================================


class TestHintContent:
    """Verify hint content retrieval."""

    @pytest.mark.asyncio
    async def test_can_view_unlocked_hint(self, db):
        """Can view content for an unlocked level."""
        user = _make_user(tokens=100)
        db.add(user)
        await db.flush()

        await HintService.unlock_hint(db, user, "1234A", 1200, 1)
        await db.flush()

        content = await HintService.get_hint_content(
            db, user, "1234A", 1, 1200, problem_tags=["dp"]
        )

        assert content.problem_id == "1234A"
        assert content.level == 1
        assert content.unlocked is True
        assert len(content.content) > 0

    @pytest.mark.asyncio
    async def test_cannot_view_locked_hint(self, db):
        """Cannot view content for a locked level."""
        user = _make_user(tokens=100)
        db.add(user)
        await db.flush()

        with pytest.raises(BadRequestException, match="not unlocked"):
            await HintService.get_hint_content(
                db, user, "1234A", 1, 1200
            )

    @pytest.mark.asyncio
    async def test_content_varies_by_level(self, db):
        """Different levels produce different content."""
        user = _make_user(tokens=200)
        db.add(user)
        await db.flush()

        await HintService.unlock_hint(db, user, "1234A", 1500, 1)
        await db.flush()
        await HintService.unlock_hint(db, user, "1234A", 1500, 2)
        await db.flush()

        c1 = await HintService.get_hint_content(db, user, "1234A", 1, 1500, problem_tags=["dp"])
        c2 = await HintService.get_hint_content(db, user, "1234A", 2, 1500, problem_tags=["dp"])

        # Level 1 should mention direction, level 2 should be more specific
        assert c1.level == 1
        assert c2.level == 2
        assert c1.content != c2.content

    @pytest.mark.asyncio
    async def test_invalid_level_rejected(self, db):
        """Content request for invalid level is rejected."""
        user = _make_user(tokens=100)
        db.add(user)
        await db.flush()

        with pytest.raises(BadRequestException, match="must be 1, 2, or 3"):
            await HintService.get_hint_content(
                db, user, "1234A", 0, 1200
            )

        with pytest.raises(BadRequestException, match="must be 1, 2, or 3"):
            await HintService.get_hint_content(
                db, user, "1234A", 4, 1200
            )


# ===========================================================================
# Test: Hint purchase history
# ===========================================================================


class TestHintHistory:
    """Verify hint purchase history."""

    @pytest.mark.asyncio
    async def test_empty_history(self, db):
        """No purchases returns empty history."""
        user = _make_user()
        db.add(user)
        await db.flush()

        history = await HintService.get_hint_history(db, user, "1234A")

        assert history.problem_id == "1234A"
        assert history.purchases == []
        assert history.total_spent == 0

    @pytest.mark.asyncio
    async def test_history_after_one_purchase(self, db):
        """History shows one purchase after unlocking level 1."""
        user = _make_user(tokens=100)
        db.add(user)
        await db.flush()

        await HintService.unlock_hint(db, user, "1234A", 1200, 1)
        await db.flush()

        history = await HintService.get_hint_history(db, user, "1234A")

        assert len(history.purchases) == 1
        assert history.purchases[0].hint_level == 1
        assert history.purchases[0].tokens_cost == 5
        assert history.total_spent == 5

    @pytest.mark.asyncio
    async def test_history_after_all_purchases(self, db):
        """History shows all three purchases."""
        user = _make_user(tokens=200)
        db.add(user)
        await db.flush()

        await HintService.unlock_hint(db, user, "1234A", 1200, 1)
        await db.commit()
        await HintService.unlock_hint(db, user, "1234A", 1200, 2)
        await db.commit()
        await HintService.unlock_hint(db, user, "1234A", 1200, 3)
        await db.commit()

        history = await HintService.get_hint_history(db, user, "1234A")

        assert len(history.purchases) == 3
        levels = [p.hint_level for p in history.purchases]
        assert levels == [1, 2, 3]
        assert history.total_spent == 50  # 5 + 15 + 30

    @pytest.mark.asyncio
    async def test_history_isolated_per_problem(self, db):
        """History for one problem does not show purchases for another."""
        user = _make_user(tokens=200)
        db.add(user)
        await db.flush()

        await HintService.unlock_hint(db, user, "1234A", 1200, 1)
        await db.flush()
        await HintService.unlock_hint(db, user, "5678B", 1200, 1)
        await db.flush()

        history_a = await HintService.get_hint_history(db, user, "1234A")
        history_b = await HintService.get_hint_history(db, user, "5678B")

        assert len(history_a.purchases) == 1
        assert history_a.purchases[0].problem_id == "1234A"
        assert len(history_b.purchases) == 1
        assert history_b.purchases[0].problem_id == "5678B"

    @pytest.mark.asyncio
    async def test_history_isolated_per_user(self, db):
        """One user's history does not show another user's purchases."""
        user1 = _make_user(tokens=100)
        user2 = _make_user(tokens=100)
        db.add_all([user1, user2])
        await db.flush()

        await HintService.unlock_hint(db, user1, "1234A", 1200, 1)
        await db.flush()

        history = await HintService.get_hint_history(db, user2, "1234A")
        assert len(history.purchases) == 0


# ===========================================================================
# Test: Max hint level utility
# ===========================================================================


class TestMaxHintLevel:
    """Verify max hint level retrieval."""

    @pytest.mark.asyncio
    async def test_no_hints_returns_0(self, db):
        """Returns 0 when no hints have been purchased."""
        user = _make_user()
        db.add(user)
        await db.flush()

        level = await HintService.get_max_hint_level(db, user.id, "1234A")
        assert level == 0

    @pytest.mark.asyncio
    async def test_returns_max_level(self, db):
        """Returns the highest unlocked level."""
        user = _make_user(tokens=200)
        db.add(user)
        await db.flush()

        await HintService.unlock_hint(db, user, "1234A", 1200, 1)
        await db.commit()
        await HintService.unlock_hint(db, user, "1234A", 1200, 2)
        await db.commit()

        level = await HintService.get_max_hint_level(db, user.id, "1234A")
        assert level == 2

    @pytest.mark.asyncio
    async def test_all_three_levels(self, db):
        """Returns 3 when all levels are unlocked."""
        user = _make_user(tokens=200)
        db.add(user)
        await db.flush()

        await HintService.unlock_hint(db, user, "1234A", 1200, 1)
        await db.commit()
        await HintService.unlock_hint(db, user, "1234A", 1200, 2)
        await db.commit()
        await HintService.unlock_hint(db, user, "1234A", 1200, 3)
        await db.commit()

        level = await HintService.get_max_hint_level(db, user.id, "1234A")
        assert level == 3


# ===========================================================================
# Test: Pricing across all tiers (parametrized)
# ===========================================================================


class TestPricingAllTiers:
    """Verify pricing for all difficulty tiers."""

    @pytest.mark.parametrize(
        "rating,level_1,level_2,level_3",
        [
            (900, 3, 10, 20),       # gray
            (1200, 5, 15, 30),      # green
            (1500, 8, 20, 40),      # blue
            (1800, 10, 25, 50),     # purple
            (2500, 15, 30, 60),     # yellow/red
        ],
    )
    @pytest.mark.asyncio
    async def test_full_unlock_sequence(self, db, rating, level_1, level_2, level_3):
        """Complete unlock sequence with correct pricing at each tier."""
        user = _make_user(tokens=300)
        db.add(user)
        await db.flush()

        # Unlock level 1
        r1 = await HintService.unlock_hint(db, user, "TEST", rating, 1)
        assert r1.tokens_spent == level_1
        await db.flush()

        # Unlock level 2
        r2 = await HintService.unlock_hint(db, user, "TEST", rating, 2)
        assert r2.tokens_spent == level_2
        await db.flush()

        # Unlock level 3
        r3 = await HintService.unlock_hint(db, user, "TEST", rating, 3)
        assert r3.tokens_spent == level_3
        assert r3.tokens_remaining == 300 - level_1 - level_2 - level_3


# ===========================================================================
# Test: Edge cases
# ===========================================================================


class TestEdgeCases:
    """Verify edge case handling."""

    @pytest.mark.asyncio
    async def test_separate_problems_independent(self, db):
        """Hint progress for different problems is independent."""
        user = _make_user(tokens=200)
        db.add(user)
        await db.flush()

        # Problem A: unlock level 1
        await HintService.unlock_hint(db, user, "A", 1200, 1)
        await db.flush()

        # Problem B: should start from level 1, not level 2
        await HintService.unlock_hint(db, user, "B", 1200, 1)
        await db.flush()

        # Problem B: can unlock level 2
        result = await HintService.unlock_hint(db, user, "B", 1200, 2)
        assert result.level == 2

        # Problem A: can also unlock level 2
        result = await HintService.unlock_hint(db, user, "A", 1200, 2)
        assert result.level == 2

    @pytest.mark.asyncio
    async def test_problem_rating_0(self, db):
        """Rating 0 falls into gray tier."""
        prices = get_hint_prices(0)
        assert prices == [3, 10, 20]

    @pytest.mark.asyncio
    async def test_very_high_rating(self, db):
        """Very high rating falls into yellow/red tier."""
        prices = get_hint_prices(5000)
        assert prices == [15, 30, 60]

    @pytest.mark.asyncio
    async def test_unlock_creates_purchase_record(self, db):
        """Unlocking creates a HintPurchase record in the database."""
        user = _make_user(tokens=100)
        db.add(user)
        await db.flush()

        await HintService.unlock_hint(db, user, "1234A", 1200, 1)
        await db.flush()

        # Verify record exists
        from sqlalchemy import select
        stmt = select(_TestHintPurchase).where(
            _TestHintPurchase.user_id == user.id,
            _TestHintPurchase.problem_id == "1234A",
        )
        result = await db.execute(stmt)
        purchase = result.scalar_one()

        assert purchase.hint_level == 1
        assert purchase.tokens_cost == 5
        assert purchase.problem_rating == 1200
