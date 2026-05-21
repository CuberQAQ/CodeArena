"""Tests for the daily check-in service: check-in, make-up, streak, token caps.

Uses lightweight SQLite-compatible test models following the established
patching pattern. All 8 test points from the task spec are covered.
"""

import uuid
from datetime import UTC, date, datetime, timedelta
from unittest.mock import patch

import pytest
from sqlalchemy import Boolean, Date, DateTime, Integer, String, event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core.exceptions import BadRequestException
from app.services import checkin_service as checkin_svc_module
from app.services.checkin_service import (
    BASE_REWARD,
    MAKEUP_WEEKLY_LIMIT,
    STREAK_7_REWARD,
    STREAK_30_REWARD,
    _reward_for_streak,
    check_in,
    get_history,
    get_status,
    makeup_checkin,
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


class _TestCheckIn(_TestBase):
    __tablename__ = "check_ins"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    checkin_date: Mapped[date] = mapped_column(Date, nullable=False)
    streak_days: Mapped[int] = mapped_column(Integer, nullable=False)
    is_makeup: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    tokens_awarded: Mapped[int] = mapped_column(Integer, nullable=False)
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


@pytest.fixture
async def db(async_engine):
    """Provide an async session with patched model references."""
    session_factory = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as session:
        with (
            patch.object(checkin_svc_module, "CheckIn", _TestCheckIn),
            patch.object(checkin_svc_module.economy_service, "User", _TestUser),
            patch.object(checkin_svc_module.economy_service, "TokenTransaction", _TestTokenTransaction),
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


def _make_checkin(
    user_id: uuid.UUID,
    checkin_date: date,
    streak_days: int,
    is_makeup: bool = False,
    tokens_awarded: int = 10,
) -> _TestCheckIn:
    """Create a test check-in record (not yet added to session)."""
    return _TestCheckIn(
        user_id=user_id,
        checkin_date=checkin_date,
        streak_days=streak_days,
        is_makeup=is_makeup,
        tokens_awarded=tokens_awarded,
    )


# ---------------------------------------------------------------------------
# 1. Reward tier helper
# ---------------------------------------------------------------------------


class TestRewardForStreak:
    def test_base_reward_days_1_to_6(self):
        for d in range(1, 7):
            assert _reward_for_streak(d) == BASE_REWARD

    def test_streak_7_reward(self):
        assert _reward_for_streak(7) == STREAK_7_REWARD

    def test_streak_29_reward(self):
        assert _reward_for_streak(29) == STREAK_7_REWARD

    def test_streak_30_reward(self):
        assert _reward_for_streak(30) == STREAK_30_REWARD

    def test_streak_beyond_30(self):
        assert _reward_for_streak(100) == STREAK_30_REWARD


# ---------------------------------------------------------------------------
# 2. First check-in (Test Point 1)
# ---------------------------------------------------------------------------


class TestFirstCheckIn:
    """Test Point 1: First check-in => streak=1, 10 tokens."""

    async def test_first_checkin(self, db):
        user = _make_user()
        db.add(user)
        await db.flush()

        result = await check_in(db, user)

        assert result.streak_days == 1
        assert result.tokens_awarded == 10
        assert result.is_makeup is False
        assert result.checkin_date == date.today()
        assert user.tokens == 10


# ---------------------------------------------------------------------------
# 3. Streak 7 days (Test Point 2)
# ---------------------------------------------------------------------------


class TestStreak7Days:
    """Test Point 2: 7-day streak => 15 tokens."""

    async def test_streak_7_reward(self, db):
        user = _make_user()
        db.add(user)
        await db.flush()

        # Create 6 previous check-ins (streak=6 at yesterday)
        today = date.today()
        for i in range(6):
            ci = _make_checkin(
                user_id=user.id,
                checkin_date=today - timedelta(days=6 - i),
                streak_days=i + 1,
                tokens_awarded=BASE_REWARD,
            )
            db.add(ci)
        await db.flush()

        result = await check_in(db, user)

        assert result.streak_days == 7
        assert result.tokens_awarded == STREAK_7_REWARD


# ---------------------------------------------------------------------------
# 4. Streak 30 days (Test Point 3)
# ---------------------------------------------------------------------------


class TestStreak30Days:
    """Test Point 3: 30-day streak => 20 tokens."""

    async def test_streak_30_reward(self, db):
        user = _make_user()
        db.add(user)
        await db.flush()

        # Create 29 previous check-ins
        today = date.today()
        for i in range(29):
            ci = _make_checkin(
                user_id=user.id,
                checkin_date=today - timedelta(days=29 - i),
                streak_days=i + 1,
                tokens_awarded=BASE_REWARD,
            )
            db.add(ci)
        await db.flush()

        result = await check_in(db, user)

        assert result.streak_days == 30
        assert result.tokens_awarded == STREAK_30_REWARD


# ---------------------------------------------------------------------------
# 5. Duplicate check-in (Test Point 4)
# ---------------------------------------------------------------------------


class TestDuplicateCheckIn:
    """Test Point 4: Cannot check in twice on the same day."""

    async def test_reject_duplicate_checkin(self, db):
        user = _make_user()
        db.add(user)
        await db.flush()

        # First check-in
        await check_in(db, user)

        # Second check-in should fail
        with pytest.raises(BadRequestException, match="Already checked in"):
            await check_in(db, user)


# ---------------------------------------------------------------------------
# 6. Streak reset after missing day (Test Point 5)
# ---------------------------------------------------------------------------


class TestStreakReset:
    """Test Point 5: Missing a day resets streak to 1."""

    async def test_streak_resets_after_gap(self, db):
        user = _make_user()
        db.add(user)
        await db.flush()

        today = date.today()
        # Check-in 3 days ago (streak was 5 at that point)
        old_ci = _make_checkin(
            user_id=user.id,
            checkin_date=today - timedelta(days=3),
            streak_days=5,
        )
        db.add(old_ci)
        await db.flush()

        result = await check_in(db, user)
        assert result.streak_days == 1
        assert result.tokens_awarded == BASE_REWARD


# ---------------------------------------------------------------------------
# 7. Make-up check-in (Test Point 6)
# ---------------------------------------------------------------------------


class TestMakeupCheckIn:
    """Test Point 6: Make-up gives base 10 tokens and restores streak."""

    async def test_makeup_basic(self, db):
        user = _make_user()
        db.add(user)
        await db.flush()

        today = date.today()
        yesterday = today - timedelta(days=1)

        # User checked in 2 days ago with streak=3
        old_ci = _make_checkin(
            user_id=user.id,
            checkin_date=today - timedelta(days=2),
            streak_days=3,
        )
        db.add(old_ci)
        await db.flush()

        result = await makeup_checkin(db, user)

        assert result.checkin_date == yesterday
        assert result.tokens_awarded == BASE_REWARD  # Always base 10
        assert result.is_makeup is True
        assert result.streak_days == 4  # 3 + 1

    async def test_makeup_first_time_no_prior(self, db):
        """Make-up with no prior check-in gives streak=1."""
        user = _make_user()
        db.add(user)
        await db.flush()

        result = await makeup_checkin(db, user)

        assert result.streak_days == 1
        assert result.tokens_awarded == BASE_REWARD


# ---------------------------------------------------------------------------
# 8. Make-up weekly limit (Test Point 7)
# ---------------------------------------------------------------------------


class TestMakeupLimit:
    """Test Point 7: Max 2 make-ups per week."""

    async def test_makeup_limit_enforced(self, db):
        user = _make_user()
        db.add(user)
        await db.flush()

        today = date.today()
        week_monday = today - timedelta(days=today.weekday())

        # Add 2 make-up records this week
        for i in range(2):
            ci = _make_checkin(
                user_id=user.id,
                checkin_date=week_monday + timedelta(days=i),
                streak_days=1,
                is_makeup=True,
            )
            db.add(ci)
        await db.flush()

        with pytest.raises(BadRequestException, match="Weekly make-up limit"):
            await makeup_checkin(db, user)


# ---------------------------------------------------------------------------
# 9. Token daily cap (Test Point 8)
# ---------------------------------------------------------------------------


class TestTokenDailyCap:
    """Test Point 8: Check-in tokens respect daily 120 cap."""

    async def test_checkin_respects_daily_cap(self, db):
        now = datetime.now(UTC)
        user = _make_user(tokens=110, daily_tokens_earned=110, daily_tokens_reset_at=now)
        db.add(user)
        await db.flush()

        result = await check_in(db, user)

        # 120 cap - 110 already earned = 10 remaining
        assert result.tokens_awarded == 10
        assert user.tokens == 120

    async def test_checkin_zero_when_cap_reached(self, db):
        now = datetime.now(UTC)
        user = _make_user(tokens=120, daily_tokens_earned=120, daily_tokens_reset_at=now)
        db.add(user)
        await db.flush()

        result = await check_in(db, user)
        assert result.tokens_awarded == 0


# ---------------------------------------------------------------------------
# 10. Get status
# ---------------------------------------------------------------------------


class TestGetStatus:
    async def test_status_fresh_user(self, db):
        user = _make_user()
        db.add(user)
        await db.flush()

        status = await get_status(db, user)

        assert status.checked_in_today is False
        assert status.streak_days == 0
        assert status.last_checkin_date is None
        assert status.makeup_used_this_week == 0
        assert status.makeup_limit == MAKEUP_WEEKLY_LIMIT
        assert status.next_reward == BASE_REWARD

    async def test_status_after_checkin(self, db):
        user = _make_user()
        db.add(user)
        await db.flush()

        await check_in(db, user)
        status = await get_status(db, user)

        assert status.checked_in_today is True
        assert status.streak_days == 1
        assert status.last_checkin_date == date.today()
        assert status.next_reward == 0  # Can't check in again

    async def test_status_streak_broken(self, db):
        user = _make_user()
        db.add(user)
        await db.flush()

        today = date.today()
        old_ci = _make_checkin(
            user_id=user.id,
            checkin_date=today - timedelta(days=5),
            streak_days=10,
        )
        db.add(old_ci)
        await db.flush()

        status = await get_status(db, user)

        assert status.checked_in_today is False
        assert status.streak_days == 0  # Broken
        assert status.next_reward == BASE_REWARD

    async def test_status_yesterday_streak_active(self, db):
        user = _make_user()
        db.add(user)
        await db.flush()

        today = date.today()
        yesterday_ci = _make_checkin(
            user_id=user.id,
            checkin_date=today - timedelta(days=1),
            streak_days=6,
        )
        db.add(yesterday_ci)
        await db.flush()

        status = await get_status(db, user)

        assert status.checked_in_today is False
        assert status.streak_days == 6  # Will become 7 on next check-in
        assert status.next_reward == STREAK_7_REWARD  # 7-day bonus


# ---------------------------------------------------------------------------
# 11. Get history
# ---------------------------------------------------------------------------


class TestGetHistory:
    async def test_empty_history(self, db):
        user = _make_user()
        db.add(user)
        await db.flush()

        result = await get_history(db, user)
        assert result.total == 0
        assert result.items == []

    async def test_history_with_data(self, db):
        user = _make_user()
        db.add(user)
        await db.flush()

        today = date.today()
        for i in range(5):
            ci = _make_checkin(
                user_id=user.id,
                checkin_date=today - timedelta(days=i),
                streak_days=5 - i,
            )
            db.add(ci)
        await db.flush()

        result = await get_history(db, user)
        assert result.total == 5
        assert len(result.items) == 5
        # Should be ordered by date desc
        assert result.items[0].checkin_date == today

    async def test_history_pagination(self, db):
        user = _make_user()
        db.add(user)
        await db.flush()

        today = date.today()
        for i in range(10):
            ci = _make_checkin(
                user_id=user.id,
                checkin_date=today - timedelta(days=i),
                streak_days=10 - i,
            )
            db.add(ci)
        await db.flush()

        page1 = await get_history(db, user, limit=5, offset=0)
        assert page1.total == 10
        assert len(page1.items) == 5

        page2 = await get_history(db, user, limit=5, offset=5)
        assert page2.total == 10
        assert len(page2.items) == 5

        # Ensure no overlap
        ids1 = {item.id for item in page1.items}
        ids2 = {item.id for item in page2.items}
        assert ids1.isdisjoint(ids2)


# ---------------------------------------------------------------------------
# 12. Make-up edge cases
# ---------------------------------------------------------------------------


class TestMakeupEdgeCases:
    async def test_makeup_yesterday_already_filled(self, db):
        """Cannot make-up if yesterday already has a check-in."""
        user = _make_user()
        db.add(user)
        await db.flush()

        today = date.today()
        yesterday = today - timedelta(days=1)

        ci = _make_checkin(
            user_id=user.id,
            checkin_date=yesterday,
            streak_days=1,
        )
        db.add(ci)
        await db.flush()

        with pytest.raises(BadRequestException, match="already checked in"):
            await makeup_checkin(db, user)

    async def test_makeup_count_scoped_to_week(self, db):
        """Make-ups from a previous week don't count toward current week."""
        user = _make_user()
        db.add(user)
        await db.flush()

        today = date.today()
        # Add 2 make-ups from last week
        last_week_monday = today - timedelta(days=today.weekday() + 7)
        for i in range(2):
            ci = _make_checkin(
                user_id=user.id,
                checkin_date=last_week_monday + timedelta(days=i),
                streak_days=1,
                is_makeup=True,
            )
            db.add(ci)
        await db.flush()

        # Should still be able to make-up this week
        result = await makeup_checkin(db, user)
        assert result.is_makeup is True


# ---------------------------------------------------------------------------
# 13. Integration: continuous streak flow
# ---------------------------------------------------------------------------


class TestStreakFlow:
    async def test_continuous_streak_day_by_day(self, db):
        """Simulate checking in 10 days in a row."""
        user = _make_user()
        db.add(user)
        await db.flush()

        # Manually build up a streak to simulate 10 consecutive days
        today = date.today()
        for i in range(10):
            ci = _make_checkin(
                user_id=user.id,
                checkin_date=today - timedelta(days=10 - i),
                streak_days=i + 1,
                tokens_awarded=STREAK_7_REWARD if i + 1 >= 7 else BASE_REWARD,
            )
            db.add(ci)
        await db.flush()

        # Check status
        status = await get_status(db, user)
        assert status.streak_days == 10

        # Next check-in should give streak_7 reward (since streak will be 11)
        assert status.next_reward == STREAK_7_REWARD
