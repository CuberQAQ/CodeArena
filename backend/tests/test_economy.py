"""Tests for the token economy service: awarding, spending, daily caps, tiers.

Uses lightweight SQLite-compatible test models following the established
patching pattern.
"""

import uuid
from datetime import UTC, date, datetime, timedelta
from unittest.mock import patch

import pytest
from sqlalchemy import Boolean, DateTime, Integer, String, event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core.exceptions import BadRequestException
from app.services import economy_service as economy_svc_module
from app.services.economy_service import (
    DAILY_TOKEN_CAP,
    attempt_tokens_for_rating,
    award_tokens,
    check_and_reset_daily,
    get_balance,
    get_daily_status,
    get_transactions,
    spend_tokens,
    time_bonus_for_rating,
    tokens_for_rating,
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
    tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    daily_tokens_earned: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    daily_tokens_reset_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


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


@pytest.fixture
async def db(async_engine):
    """Provide an async session with patched model references."""
    session_factory = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as session:
        with (
            patch.object(economy_svc_module, "User", _TestUser),
            patch.object(economy_svc_module, "TokenTransaction", _TestTokenTransaction),
        ):
            yield session


def _make_user(
    user_id: uuid.UUID | None = None,
    username: str = "testuser",
    tokens: int = 0,
    daily_tokens_earned: int = 0,
    daily_tokens_reset_at: datetime | None = None,
) -> _TestUser:
    """Create a test user instance (not yet added to session)."""
    return _TestUser(
        id=user_id or uuid.uuid4(),
        username=username,
        email=f"{username}@test.com",
        password_hash="$2b$12$fakehash",
        tokens=tokens,
        daily_tokens_earned=daily_tokens_earned,
        daily_tokens_reset_at=daily_tokens_reset_at,
    )


# ---------------------------------------------------------------------------
# 1. Token tier lookups
# ---------------------------------------------------------------------------


class TestTokensForRating:
    def test_gray_range(self):
        assert tokens_for_rating(800) == 10
        assert tokens_for_rating(900) == 10
        assert tokens_for_rating(1199) == 10

    def test_green_range(self):
        assert tokens_for_rating(1200) == 20
        assert tokens_for_rating(1300) == 20
        assert tokens_for_rating(1399) == 20

    def test_cyan_range(self):
        assert tokens_for_rating(1400) == 25
        assert tokens_for_rating(1500) == 25
        assert tokens_for_rating(1599) == 25

    def test_blue_range(self):
        assert tokens_for_rating(1600) == 35
        assert tokens_for_rating(1750) == 35
        assert tokens_for_rating(1899) == 35

    def test_purple_range(self):
        assert tokens_for_rating(1900) == 45
        assert tokens_for_rating(2000) == 45
        assert tokens_for_rating(2099) == 45

    def test_orange_range(self):
        assert tokens_for_rating(2100) == 55
        assert tokens_for_rating(2250) == 55
        assert tokens_for_rating(2399) == 55

    def test_red_range(self):
        assert tokens_for_rating(2400) == 65
        assert tokens_for_rating(2500) == 65
        assert tokens_for_rating(3500) == 65

    def test_below_range(self):
        assert tokens_for_rating(500) == 10


class TestAttemptTokensForRating:
    def test_gray_range(self):
        assert attempt_tokens_for_rating(800) == 2
        assert attempt_tokens_for_rating(1199) == 2

    def test_green_range(self):
        assert attempt_tokens_for_rating(1200) == 3
        assert attempt_tokens_for_rating(1399) == 3

    def test_cyan_range(self):
        assert attempt_tokens_for_rating(1400) == 4
        assert attempt_tokens_for_rating(1599) == 4

    def test_blue_range(self):
        assert attempt_tokens_for_rating(1600) == 5
        assert attempt_tokens_for_rating(1899) == 5

    def test_purple_range(self):
        assert attempt_tokens_for_rating(1900) == 6
        assert attempt_tokens_for_rating(2099) == 6

    def test_orange_range(self):
        assert attempt_tokens_for_rating(2100) == 7
        assert attempt_tokens_for_rating(2399) == 7

    def test_red_range(self):
        assert attempt_tokens_for_rating(2400) == 8
        assert attempt_tokens_for_rating(3000) == 8


class TestTimeBonusForRating:
    def test_gray_bonus(self):
        assert time_bonus_for_rating(800) == 5
        assert time_bonus_for_rating(1199) == 5

    def test_green_bonus(self):
        assert time_bonus_for_rating(1200) == 10
        assert time_bonus_for_rating(1399) == 10

    def test_cyan_bonus(self):
        assert time_bonus_for_rating(1400) == 12
        assert time_bonus_for_rating(1599) == 12

    def test_blue_bonus(self):
        assert time_bonus_for_rating(1600) == 18
        assert time_bonus_for_rating(1899) == 18

    def test_purple_bonus(self):
        assert time_bonus_for_rating(1900) == 22
        assert time_bonus_for_rating(2099) == 22

    def test_orange_bonus(self):
        assert time_bonus_for_rating(2100) == 28
        assert time_bonus_for_rating(2399) == 28

    def test_red_bonus(self):
        assert time_bonus_for_rating(2400) == 35
        assert time_bonus_for_rating(3000) == 35


# ---------------------------------------------------------------------------
# 2. Daily reset logic
# ---------------------------------------------------------------------------


class TestDailyReset:
    async def test_reset_when_none(self, db):
        """First-time user with no reset_at should get initialised."""
        user = _make_user()
        db.add(user)
        await db.flush()

        await check_and_reset_daily(db, user)
        assert user.daily_tokens_earned == 0
        assert user.daily_tokens_reset_at is not None

    async def test_no_reset_same_day(self, db):
        """No reset when already reset today."""
        now = datetime.now(UTC)
        user = _make_user(daily_tokens_earned=50, daily_tokens_reset_at=now)
        db.add(user)
        await db.flush()

        await check_and_reset_daily(db, user)
        assert user.daily_tokens_earned == 50

    async def test_reset_crosses_midnight(self, db):
        """Reset when the stored date is before today."""
        yesterday = datetime.now(UTC) - timedelta(days=1)
        user = _make_user(daily_tokens_earned=100, daily_tokens_reset_at=yesterday)
        db.add(user)
        await db.flush()

        await check_and_reset_daily(db, user)
        assert user.daily_tokens_earned == 0
        assert user.daily_tokens_reset_at is not None

    async def test_reset_with_naive_datetime(self, db):
        """Handle naive datetime (treated as UTC)."""
        yesterday_naive = datetime.now() - timedelta(days=1)
        user = _make_user(daily_tokens_earned=80, daily_tokens_reset_at=yesterday_naive)
        db.add(user)
        await db.flush()

        await check_and_reset_daily(db, user)
        assert user.daily_tokens_earned == 0


# ---------------------------------------------------------------------------
# 3. Award tokens
# ---------------------------------------------------------------------------


class TestAwardTokens:
    async def test_basic_award(self, db):
        user = _make_user(tokens=0)
        db.add(user)
        await db.flush()

        awarded = await award_tokens(db, user, 10, "challenge_reward")
        assert awarded == 10
        assert user.tokens == 10
        assert user.daily_tokens_earned == 10

    async def test_award_creates_transaction(self, db):
        user = _make_user(tokens=0)
        db.add(user)
        await db.flush()

        ref_id = uuid.uuid4()
        awarded = await award_tokens(
            db, user, 20, "training_reward",
            reference_type="training",
            reference_id=ref_id,
        )
        assert awarded == 20

        # Verify transaction was created
        from sqlalchemy import select
        stmt = select(_TestTokenTransaction).where(_TestTokenTransaction.user_id == user.id)
        result = await db.execute(stmt)
        tx = result.scalar_one()
        assert tx.amount == 20
        assert tx.type == "training_reward"
        assert tx.reference_type == "training"
        assert tx.reference_id == ref_id
        assert tx.balance_after == 20

    async def test_award_respects_daily_cap(self, db):
        user = _make_user(tokens=0, daily_tokens_earned=110)
        now = datetime.now(UTC)
        user.daily_tokens_reset_at = now
        db.add(user)
        await db.flush()

        # Try to award 20, only 10 should go through
        awarded = await award_tokens(db, user, 20, "challenge_reward")
        assert awarded == 10
        assert user.tokens == 10
        assert user.daily_tokens_earned == DAILY_TOKEN_CAP

    async def test_award_zero_when_cap_reached(self, db):
        user = _make_user(tokens=50, daily_tokens_earned=DAILY_TOKEN_CAP)
        now = datetime.now(UTC)
        user.daily_tokens_reset_at = now
        db.add(user)
        await db.flush()

        awarded = await award_tokens(db, user, 10, "challenge_reward")
        assert awarded == 0
        assert user.tokens == 50

    async def test_award_rejects_non_positive(self, db):
        user = _make_user(tokens=0)
        db.add(user)
        await db.flush()

        with pytest.raises(BadRequestException, match="must be positive"):
            await award_tokens(db, user, 0, "challenge_reward")

        with pytest.raises(BadRequestException, match="must be positive"):
            await award_tokens(db, user, -5, "challenge_reward")

    async def test_award_resets_daily_if_needed(self, db):
        """Awarding tokens on a new day should reset the daily counter."""
        yesterday = datetime.now(UTC) - timedelta(days=1)
        user = _make_user(tokens=0, daily_tokens_earned=100, daily_tokens_reset_at=yesterday)
        db.add(user)
        await db.flush()

        awarded = await award_tokens(db, user, 30, "challenge_reward")
        assert awarded == 30
        assert user.daily_tokens_earned == 30  # reset to 0, then +30


# ---------------------------------------------------------------------------
# 4. Spend tokens
# ---------------------------------------------------------------------------


class TestSpendTokens:
    async def test_basic_spend(self, db):
        user = _make_user(tokens=100)
        db.add(user)
        await db.flush()

        spent = await spend_tokens(db, user, 30, "hint_purchase")
        assert spent == 30
        assert user.tokens == 70

    async def test_spend_creates_negative_transaction(self, db):
        user = _make_user(tokens=50)
        db.add(user)
        await db.flush()

        ref_id = uuid.uuid4()
        await spend_tokens(
            db, user, 20, "hint_purchase",
            reference_type="hint",
            reference_id=ref_id,
        )

        from sqlalchemy import select
        stmt = select(_TestTokenTransaction).where(_TestTokenTransaction.user_id == user.id)
        result = await db.execute(stmt)
        tx = result.scalar_one()
        assert tx.amount == -20
        assert tx.type == "hint_purchase"
        assert tx.reference_type == "hint"
        assert tx.reference_id == ref_id
        assert tx.balance_after == 30

    async def test_spend_insufficient_balance(self, db):
        user = _make_user(tokens=10)
        db.add(user)
        await db.flush()

        with pytest.raises(BadRequestException, match="Insufficient tokens"):
            await spend_tokens(db, user, 50, "hint_purchase")

    async def test_spend_exact_balance(self, db):
        user = _make_user(tokens=30)
        db.add(user)
        await db.flush()

        spent = await spend_tokens(db, user, 30, "hint_purchase")
        assert spent == 30
        assert user.tokens == 0

    async def test_spend_rejects_non_positive(self, db):
        user = _make_user(tokens=100)
        db.add(user)
        await db.flush()

        with pytest.raises(BadRequestException, match="must be positive"):
            await spend_tokens(db, user, 0, "hint_purchase")

        with pytest.raises(BadRequestException, match="must be positive"):
            await spend_tokens(db, user, -10, "hint_purchase")

    async def test_spend_does_not_go_negative(self, db):
        """Balance should never be negative after spending."""
        user = _make_user(tokens=5)
        db.add(user)
        await db.flush()

        with pytest.raises(BadRequestException):
            await spend_tokens(db, user, 10, "hint_purchase")

        assert user.tokens == 5


# ---------------------------------------------------------------------------
# 5. Query helpers
# ---------------------------------------------------------------------------


class TestGetBalance:
    async def test_balance_fresh_user(self, db):
        user = _make_user(tokens=0)
        db.add(user)
        await db.flush()

        data = await get_balance(db, user)
        assert data["tokens"] == 0
        assert data["daily_tokens_earned"] == 0
        assert data["daily_cap"] == DAILY_TOKEN_CAP
        assert data["daily_remaining"] == DAILY_TOKEN_CAP

    async def test_balance_with_tokens(self, db):
        now = datetime.now(UTC)
        user = _make_user(tokens=50, daily_tokens_earned=30, daily_tokens_reset_at=now)
        db.add(user)
        await db.flush()

        data = await get_balance(db, user)
        assert data["tokens"] == 50
        assert data["daily_tokens_earned"] == 30
        assert data["daily_remaining"] == DAILY_TOKEN_CAP - 30

    async def test_balance_resets_daily(self, db):
        yesterday = datetime.now(UTC) - timedelta(days=1)
        user = _make_user(tokens=100, daily_tokens_earned=100, daily_tokens_reset_at=yesterday)
        db.add(user)
        await db.flush()

        data = await get_balance(db, user)
        assert data["daily_tokens_earned"] == 0
        assert data["daily_remaining"] == DAILY_TOKEN_CAP


class TestGetTransactions:
    async def test_empty_transactions(self, db):
        user = _make_user()
        db.add(user)
        await db.flush()

        items, total = await get_transactions(db, user.id)
        assert total == 0
        assert items == []

    async def test_transactions_with_data(self, db):
        user = _make_user(tokens=100)
        db.add(user)
        await db.flush()

        # Create some transactions
        tx1 = _TestTokenTransaction(
            user_id=user.id,
            amount=50,
            type="challenge_reward",
            reference_type="challenge_session",
            reference_id=uuid.uuid4(),
            balance_after=50,
            created_at=datetime.now(UTC) - timedelta(minutes=5),
        )
        tx2 = _TestTokenTransaction(
            user_id=user.id,
            amount=30,
            type="training_reward",
            reference_type="training",
            reference_id=uuid.uuid4(),
            balance_after=80,
            created_at=datetime.now(UTC),
        )
        db.add_all([tx1, tx2])
        await db.flush()

        items, total = await get_transactions(db, user.id)
        assert total == 2
        assert len(items) == 2
        # Should be ordered by created_at desc (newest first)
        assert items[0].type == "training_reward"
        assert items[1].type == "challenge_reward"

    async def test_transactions_pagination(self, db):
        user = _make_user(tokens=100)
        db.add(user)
        await db.flush()

        # Create 5 transactions
        for i in range(5):
            tx = _TestTokenTransaction(
                user_id=user.id,
                amount=10,
                type=f"reward_{i}",
                balance_after=(i + 1) * 10,
                created_at=datetime.now(UTC) + timedelta(minutes=i),
            )
            db.add(tx)
        await db.flush()

        # Page 1 (limit=2, offset=0)
        items, total = await get_transactions(db, user.id, limit=2, offset=0)
        assert total == 5
        assert len(items) == 2

        # Page 2 (limit=2, offset=2)
        items2, total2 = await get_transactions(db, user.id, limit=2, offset=2)
        assert total2 == 5
        assert len(items2) == 2

        # Ensure no overlap
        ids_page1 = {item.id for item in items}
        ids_page2 = {item.id for item in items2}
        assert ids_page1.isdisjoint(ids_page2)

    async def test_transactions_only_for_user(self, db):
        user_a = _make_user(username="user_a", tokens=50)
        user_b = _make_user(username="user_b", tokens=30)
        db.add_all([user_a, user_b])
        await db.flush()

        tx_a = _TestTokenTransaction(
            user_id=user_a.id,
            amount=50,
            type="reward_a",
            balance_after=50,
            created_at=datetime.now(UTC),
        )
        tx_b = _TestTokenTransaction(
            user_id=user_b.id,
            amount=30,
            type="reward_b",
            balance_after=30,
            created_at=datetime.now(UTC),
        )
        db.add_all([tx_a, tx_b])
        await db.flush()

        items_a, total_a = await get_transactions(db, user_a.id)
        assert total_a == 1
        assert items_a[0].type == "reward_a"

        items_b, total_b = await get_transactions(db, user_b.id)
        assert total_b == 1
        assert items_b[0].type == "reward_b"


class TestGetDailyStatus:
    async def test_daily_status_fresh(self, db):
        user = _make_user()
        db.add(user)
        await db.flush()

        data = await get_daily_status(db, user)
        assert data["daily_tokens_earned"] == 0
        assert data["daily_cap"] == DAILY_TOKEN_CAP
        assert data["daily_remaining"] == DAILY_TOKEN_CAP
        assert data["date"] == date.today().isoformat()

    async def test_daily_status_with_earnings(self, db):
        now = datetime.now(UTC)
        user = _make_user(tokens=50, daily_tokens_earned=50, daily_tokens_reset_at=now)
        db.add(user)
        await db.flush()

        # Add a positive transaction today
        tx = _TestTokenTransaction(
            user_id=user.id,
            amount=50,
            type="challenge_reward",
            balance_after=50,
            created_at=datetime.now(UTC),
        )
        db.add(tx)
        await db.flush()

        data = await get_daily_status(db, user)
        assert data["daily_tokens_earned"] == 50
        assert data["daily_remaining"] == DAILY_TOKEN_CAP - 50
        assert "challenge_reward" in data["breakdown"]
        assert data["breakdown"]["challenge_reward"] == 50

    async def test_daily_status_resets_old(self, db):
        yesterday = datetime.now(UTC) - timedelta(days=1)
        user = _make_user(tokens=100, daily_tokens_earned=100, daily_tokens_reset_at=yesterday)
        db.add(user)
        await db.flush()

        data = await get_daily_status(db, user)
        assert data["daily_tokens_earned"] == 0
        assert data["daily_remaining"] == DAILY_TOKEN_CAP


# ---------------------------------------------------------------------------
# 6. Integration: award + spend flow
# ---------------------------------------------------------------------------


class TestIntegrationFlow:
    async def test_award_then_spend(self, db):
        user = _make_user(tokens=0)
        db.add(user)
        await db.flush()

        # Award tokens
        awarded = await award_tokens(db, user, 50, "challenge_reward")
        assert awarded == 50
        assert user.tokens == 50

        # Spend some
        spent = await spend_tokens(db, user, 20, "hint_purchase")
        assert spent == 20
        assert user.tokens == 30

        # Check transactions
        from sqlalchemy import select
        stmt = (
            select(_TestTokenTransaction)
            .where(_TestTokenTransaction.user_id == user.id)
            .order_by(_TestTokenTransaction.created_at)
        )
        result = await db.execute(stmt)
        txs = list(result.scalars().all())
        assert len(txs) == 2
        assert txs[0].amount == 50
        assert txs[0].balance_after == 50
        assert txs[1].amount == -20
        assert txs[1].balance_after == 30

    async def test_daily_cap_across_multiple_awards(self, db):
        now = datetime.now(UTC)
        user = _make_user(tokens=0, daily_tokens_earned=0, daily_tokens_reset_at=now)
        db.add(user)
        await db.flush()

        # Award in sequence: 50 + 50 + 50, cap is 120
        a1 = await award_tokens(db, user, 50, "challenge_reward")
        assert a1 == 50
        assert user.tokens == 50

        a2 = await award_tokens(db, user, 50, "training_reward")
        assert a2 == 50
        assert user.tokens == 100

        a3 = await award_tokens(db, user, 50, "contest_reward")
        assert a3 == 20  # only 20 remaining until cap
        assert user.tokens == 120
        assert user.daily_tokens_earned == 120

    async def test_spend_does_not_affect_daily_cap(self, db):
        """Spending tokens should not reset or affect the daily earned counter."""
        now = datetime.now(UTC)
        user = _make_user(tokens=100, daily_tokens_earned=100, daily_tokens_reset_at=now)
        db.add(user)
        await db.flush()

        spent = await spend_tokens(db, user, 50, "hint_purchase")
        assert spent == 50
        assert user.tokens == 50
        assert user.daily_tokens_earned == 100  # unchanged

        # Can still only earn 20 more today
        awarded = await award_tokens(db, user, 30, "challenge_reward")
        assert awarded == 20  # 120 - 100 = 20 remaining

    async def test_new_day_resets_and_allows_full_earning(self, db):
        yesterday = datetime.now(UTC) - timedelta(days=1)
        user = _make_user(tokens=100, daily_tokens_earned=120, daily_tokens_reset_at=yesterday)
        db.add(user)
        await db.flush()

        # New day -- should be able to earn full cap again
        awarded = await award_tokens(db, user, 100, "challenge_reward")
        assert awarded == 100
        assert user.daily_tokens_earned == 100


# ---------------------------------------------------------------------------
# 7. Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    async def test_award_exactly_at_cap(self, db):
        now = datetime.now(UTC)
        user = _make_user(tokens=60, daily_tokens_earned=100, daily_tokens_reset_at=now)
        db.add(user)
        await db.flush()

        # Exactly 20 remaining
        awarded = await award_tokens(db, user, 20, "challenge_reward")
        assert awarded == 20
        assert user.daily_tokens_earned == DAILY_TOKEN_CAP

    async def test_award_large_amount_at_cap(self, db):
        now = datetime.now(UTC)
        user = _make_user(tokens=100, daily_tokens_earned=110, daily_tokens_reset_at=now)
        db.add(user)
        await db.flush()

        awarded = await award_tokens(db, user, 1000, "challenge_reward")
        assert awarded == 10
        assert user.tokens == 110

    async def test_concurrent_award_consistency(self, db):
        """Multiple sequential awards in the same session should be consistent."""
        user = _make_user(tokens=0)
        db.add(user)
        await db.flush()

        total_awarded = 0
        for _ in range(15):
            awarded = await award_tokens(db, user, 10, "challenge_reward")
            total_awarded += awarded

        assert total_awarded == DAILY_TOKEN_CAP
        assert user.tokens == DAILY_TOKEN_CAP

    async def test_spend_after_many_awards(self, db):
        """Verify balance tracking is correct through many operations."""
        user = _make_user(tokens=0)
        db.add(user)
        await db.flush()

        await award_tokens(db, user, 50, "reward_1")
        await award_tokens(db, user, 50, "reward_2")
        await spend_tokens(db, user, 30, "spend_1")
        await award_tokens(db, user, 20, "reward_3")
        await spend_tokens(db, user, 40, "spend_2")

        assert user.tokens == 50  # 50 + 50 - 30 + 20 - 40 = 50
