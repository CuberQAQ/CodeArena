"""Daily check-in service.

Handles:
  - Daily check-in with streak tracking and token rewards
  - Make-up (retroactive) check-in with weekly limit
  - Check-in status queries

Reward tiers by streak:
  - 1-6 days: 10 tokens
  - 7-29 days: 15 tokens
  - 30+ days: 20 tokens

Make-up check-ins always award base 10 tokens (no streak bonus).
All token awards respect the daily cap (120 tokens).
"""

import logging
import uuid
from datetime import date, timedelta

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestException
from app.models.check_in import CheckIn
from app.models.user import User
from app.schemas.checkin import (
    CheckInHistoryItem,
    CheckInHistoryResponse,
    CheckInResponse,
    CheckInStatusResponse,
)
from app.services import economy_service

logger = logging.getLogger("code_arena.checkin")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BASE_REWARD: int = 10
STREAK_7_REWARD: int = 15
STREAK_30_REWARD: int = 20

MAKEUP_WEEKLY_LIMIT: int = 2


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _reward_for_streak(streak_days: int) -> int:
    """Return token reward based on streak length."""
    if streak_days >= 30:
        return STREAK_30_REWARD
    if streak_days >= 7:
        return STREAK_7_REWARD
    return BASE_REWARD


def _week_start(d: date | None = None) -> date:
    """Return the Monday of the ISO week containing *d* (default: today)."""
    if d is None:
        d = date.today()
    return d - timedelta(days=d.weekday())  # Monday=0


async def _latest_checkin(db: AsyncSession, user_id: uuid.UUID) -> CheckIn | None:
    """Return the most recent CheckIn record for *user_id*."""
    stmt = select(CheckIn).where(CheckIn.user_id == user_id).order_by(CheckIn.checkin_date.desc()).limit(1)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def _makeup_count_this_week(db: AsyncSession, user_id: uuid.UUID) -> int:
    """Return the number of make-up check-ins in the current ISO week."""
    week_monday = _week_start()
    stmt = select(func.count(CheckIn.id)).where(
        and_(
            CheckIn.user_id == user_id,
            CheckIn.is_makeup.is_(True),
            CheckIn.checkin_date >= week_monday,
        )
    )
    result = await db.execute(stmt)
    return result.scalar_one()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def check_in(db: AsyncSession, user: User) -> CheckInResponse:
    """Perform a daily check-in for *user*.

    Returns a CheckInResponse with the results.

    Raises:
        BadRequestException: if already checked in today.
    """
    today = date.today()
    user_id = user.id

    # Check if already checked in today
    latest = await _latest_checkin(db, user_id)
    if latest is not None and latest.checkin_date == today:
        raise BadRequestException(message="Already checked in today")

    # Calculate streak
    if latest is not None and latest.checkin_date == today - timedelta(days=1):
        streak_days = latest.streak_days + 1
    else:
        streak_days = 1

    # Determine reward
    reward = _reward_for_streak(streak_days)

    # Award tokens (respects daily cap)
    actual_awarded = await economy_service.award_tokens(
        db,
        user,
        reward,
        tx_type="daily_checkin",
        reference_type="checkin",
    )

    # Create check-in record
    record = CheckIn(
        user_id=user_id,
        checkin_date=today,
        streak_days=streak_days,
        is_makeup=False,
        tokens_awarded=actual_awarded,
    )
    db.add(record)
    await db.flush()

    logger.info(
        "User %s checked in (streak=%d, reward=%d, actual=%d)",
        user_id,
        streak_days,
        reward,
        actual_awarded,
    )

    return CheckInResponse(
        checkin_date=today,
        streak_days=streak_days,
        tokens_awarded=actual_awarded,
        is_makeup=False,
        tokens_balance=user.tokens,
    )


async def makeup_checkin(db: AsyncSession, user: User) -> CheckInResponse:
    """Perform a make-up check-in for yesterday.

    Make-up check-ins:
      - Fill in yesterday's date
      - Award base 10 tokens (no streak bonus)
      - Count toward the weekly limit of 2
      - Restore streak: if the user's last check-in was 2 days ago,
        streak resumes from where it was + 1; otherwise resets to 1.

    Raises:
        BadRequestException: if weekly make-up limit reached or no date to make up.
    """
    today = date.today()
    yesterday = today - timedelta(days=1)
    user_id = user.id

    # Check weekly limit
    makeup_count = await _makeup_count_this_week(db, user_id)
    if makeup_count >= MAKEUP_WEEKLY_LIMIT:
        raise BadRequestException(message=f"Weekly make-up limit ({MAKEUP_WEEKLY_LIMIT}) reached")

    # Check that yesterday hasn't already been filled
    stmt = select(CheckIn).where(
        and_(
            CheckIn.user_id == user_id,
            CheckIn.checkin_date == yesterday,
        )
    )
    result = await db.execute(stmt)
    existing = result.scalar_one_or_none()
    if existing is not None:
        raise BadRequestException(message="Yesterday is already checked in")

    # Check today isn't already checked in (must check in today first via normal)
    # Actually, make-up should be for yesterday regardless of today's state.
    # The spec says "补签日期填充为昨天", so just fill yesterday.

    # Calculate streak for the make-up date
    # Look at the record before yesterday
    day_before = yesterday - timedelta(days=1)
    stmt_before = (
        select(CheckIn)
        .where(
            and_(
                CheckIn.user_id == user_id,
                CheckIn.checkin_date == day_before,
            )
        )
        .limit(1)
    )
    result_before = await db.execute(stmt_before)
    record_before = result_before.scalar_one_or_none()

    streak_days = record_before.streak_days + 1 if record_before is not None else 1

    # Make-up always awards base reward
    actual_awarded = await economy_service.award_tokens(
        db,
        user,
        BASE_REWARD,
        tx_type="makeup_checkin",
        reference_type="checkin",
    )

    record = CheckIn(
        user_id=user_id,
        checkin_date=yesterday,
        streak_days=streak_days,
        is_makeup=True,
        tokens_awarded=actual_awarded,
    )
    db.add(record)
    await db.flush()

    logger.info(
        "User %s make-up checked in for %s (streak=%d, reward=%d)",
        user_id,
        yesterday,
        streak_days,
        actual_awarded,
    )

    return CheckInResponse(
        checkin_date=yesterday,
        streak_days=streak_days,
        tokens_awarded=actual_awarded,
        is_makeup=True,
        tokens_balance=user.tokens,
    )


async def get_status(db: AsyncSession, user: User) -> CheckInStatusResponse:
    """Return the user's current check-in status."""
    today = date.today()
    user_id = user.id

    latest = await _latest_checkin(db, user_id)
    makeup_count = await _makeup_count_this_week(db, user_id)

    checked_in_today = latest is not None and latest.checkin_date == today

    if latest is not None:
        # Compute current effective streak
        if latest.checkin_date == today:
            streak_days = latest.streak_days
        elif latest.checkin_date == today - timedelta(days=1):
            streak_days = latest.streak_days  # Will increment on next check-in
        else:
            streak_days = 0  # Streak broken
        last_date = latest.checkin_date
    else:
        streak_days = 0
        last_date = None

    # Next reward preview
    if checked_in_today:
        next_reward = 0  # Can't check in again today
    else:
        # What would streak be on next check-in?
        if latest is not None and latest.checkin_date == today - timedelta(days=1):
            next_streak = latest.streak_days + 1
        else:
            next_streak = 1
        next_reward = _reward_for_streak(next_streak)

    # Can user make up yesterday?
    yesterday = today - timedelta(days=1)
    yesterday_checkin = await db.execute(
        select(CheckIn).where(
            CheckIn.user_id == user_id,
            CheckIn.checkin_date == yesterday,
        )
    )
    yesterday_exists = yesterday_checkin.scalar_one_or_none() is not None
    can_makeup = not yesterday_exists and makeup_count < MAKEUP_WEEKLY_LIMIT

    # Get actual checked dates this week
    iso_cal = today.isocalendar()
    week_start = today - timedelta(days=iso_cal[2] - 1)  # Monday
    week_end = week_start + timedelta(days=6)  # Sunday
    week_stmt = (
        select(CheckIn.checkin_date)
        .where(
            CheckIn.user_id == user_id,
            CheckIn.checkin_date >= week_start,
            CheckIn.checkin_date <= week_end,
        )
        .order_by(CheckIn.checkin_date)
    )
    week_result = await db.execute(week_stmt)
    checked_dates = [row[0] for row in week_result.all()]

    return CheckInStatusResponse(
        checked_in_today=checked_in_today,
        streak_days=streak_days,
        last_checkin_date=last_date,
        makeup_used_this_week=makeup_count,
        makeup_limit=MAKEUP_WEEKLY_LIMIT,
        next_reward=next_reward,
        can_makeup=can_makeup,
        checked_dates_this_week=checked_dates,
    )


async def get_history(
    db: AsyncSession,
    user: User,
    limit: int = 30,
    offset: int = 0,
) -> CheckInHistoryResponse:
    """Return paginated check-in history for *user*."""
    user_id = user.id

    # Total count
    count_stmt = select(func.count(CheckIn.id)).where(CheckIn.user_id == user_id)
    count_result = await db.execute(count_stmt)
    total = count_result.scalar_one()

    # Items
    stmt = (
        select(CheckIn)
        .where(CheckIn.user_id == user_id)
        .order_by(CheckIn.checkin_date.desc())
        .limit(limit)
        .offset(offset)
    )
    result = await db.execute(stmt)
    items = [
        CheckInHistoryItem(
            id=record.id,
            checkin_date=record.checkin_date,
            streak_days=record.streak_days,
            is_makeup=record.is_makeup,
            tokens_awarded=record.tokens_awarded,
        )
        for record in result.scalars().all()
    ]

    return CheckInHistoryResponse(items=items, total=total)
