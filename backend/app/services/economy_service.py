"""Token economy service.

Provides the centralised logic for token awarding, spending, daily caps,
and transaction recording.  The existing challenge/training/contest services
can call these helpers instead of manipulating User.tokens and
TokenTransaction directly.

Key responsibilities:
  - award_tokens: check daily cap, create transaction, update balance
  - spend_tokens: check sufficient balance, create transaction, update balance
  - check_and_reset_daily: roll over daily_tokens_earned at UTC midnight
  - token tier lookups (AC reward, attempt reward, time bonus)
"""

import logging
import uuid
from datetime import UTC, date, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestException
from app.models.token_transaction import TokenTransaction
from app.models.user import User

logger = logging.getLogger("code_arena.economy")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DAILY_TOKEN_CAP: int = 120

# Token reward tiers by problem rating threshold
_TOKEN_TIERS: list[tuple[int, int]] = [
    (1100, 10),   # gray (800-1099)
    (1400, 20),   # green (1100-1399)
    (1700, 30),   # blue (1400-1699)
    (2000, 40),   # purple (1700-1999)
    (9999, 50),   # yellow/red (2000+)
]

_ATTEMPT_TOKEN_TIERS: list[tuple[int, int]] = [
    (1100, 2),   # gray
    (1400, 3),   # green
    (1700, 4),   # blue
    (2000, 5),   # purple
    (9999, 6),   # yellow/red
]

_TIME_BONUS_TIERS: list[tuple[int, int]] = [
    (1100, 5),   # gray
    (1400, 10),  # green
    (1700, 15),  # blue
    (2000, 20),  # purple
    (9999, 25),  # yellow/red
]

TIME_BONUS_THRESHOLD_SECONDS: float = 20 * 60  # 20 minutes


# ---------------------------------------------------------------------------
# Public tier helpers
# ---------------------------------------------------------------------------


def tokens_for_rating(rating: int) -> int:
    """Return the AC token reward for a problem at *rating*."""
    for threshold, reward in _TOKEN_TIERS:
        if rating < threshold:
            return reward
    return 50


def attempt_tokens_for_rating(rating: int) -> int:
    """Return the attempt token reward for a problem at *rating*."""
    for threshold, reward in _ATTEMPT_TOKEN_TIERS:
        if rating < threshold:
            return reward
    return 6


def time_bonus_for_rating(rating: int) -> int:
    """Return the time-bonus token reward for a problem at *rating*."""
    for threshold, reward in _TIME_BONUS_TIERS:
        if rating < threshold:
            return reward
    return 25


# ---------------------------------------------------------------------------
# Daily reset
# ---------------------------------------------------------------------------


def _needs_daily_reset(user: User) -> bool:
    """Return True if the user's daily counter should be reset.

    Reset is needed when ``daily_tokens_reset_at`` is ``None`` or when the
    stored date is on a different UTC calendar day than *now*.
    """
    if user.daily_tokens_reset_at is None:
        return True

    stored = user.daily_tokens_reset_at
    if stored.tzinfo is None:
        # Treat naive datetimes as UTC
        stored = stored.replace(tzinfo=UTC)

    now = datetime.now(UTC)
    return stored.date() < now.date()


async def check_and_reset_daily(db: AsyncSession, user: User) -> None:
    """Reset ``daily_tokens_earned`` if a new UTC day has started."""
    if _needs_daily_reset(user):
        user.daily_tokens_earned = 0
        user.daily_tokens_reset_at = datetime.now(UTC)
        await db.flush()


# ---------------------------------------------------------------------------
# Core operations
# ---------------------------------------------------------------------------


async def award_tokens(
    db: AsyncSession,
    user: User,
    amount: int,
    tx_type: str,
    reference_type: str | None = None,
    reference_id: uuid.UUID | None = None,
) -> int:
    """Award *amount* tokens to *user*, respecting the daily cap.

    Returns the number of tokens actually awarded (may be less than
    *amount* if the cap is hit).

    Raises:
        BadRequestException: if *amount* is not positive.
    """
    if amount <= 0:
        raise BadRequestException(message="Token award amount must be positive")

    await check_and_reset_daily(db, user)

    remaining_capacity = DAILY_TOKEN_CAP - user.daily_tokens_earned
    actual = min(amount, remaining_capacity)

    if actual <= 0:
        logger.info("Daily cap reached for user %s, no tokens awarded", user.id)
        return 0

    user.tokens += actual
    user.daily_tokens_earned += actual

    tx = TokenTransaction(
        user_id=user.id,
        amount=actual,
        type=tx_type,
        reference_type=reference_type,
        reference_id=reference_id,
        balance_after=user.tokens,
    )
    db.add(tx)
    await db.flush()

    logger.info(
        "Awarded %d tokens to user %s (type=%s, balance=%d, daily=%d/%d)",
        actual,
        user.id,
        tx_type,
        user.tokens,
        user.daily_tokens_earned,
        DAILY_TOKEN_CAP,
    )
    return actual


async def spend_tokens(
    db: AsyncSession,
    user: User,
    amount: int,
    tx_type: str,
    reference_type: str | None = None,
    reference_id: uuid.UUID | None = None,
) -> int:
    """Spend *amount* tokens from *user*'s balance.

    Returns the number of tokens actually spent (equals *amount* on success).

    Raises:
        BadRequestException: if *amount* is not positive or insufficient balance.
    """
    if amount <= 0:
        raise BadRequestException(message="Token spend amount must be positive")

    if user.tokens < amount:
        raise BadRequestException(
            message=f"Insufficient tokens: have {user.tokens}, need {amount}"
        )

    user.tokens -= amount

    tx = TokenTransaction(
        user_id=user.id,
        amount=-amount,
        type=tx_type,
        reference_type=reference_type,
        reference_id=reference_id,
        balance_after=user.tokens,
    )
    db.add(tx)
    await db.flush()

    logger.info(
        "Spent %d tokens from user %s (type=%s, balance=%d)",
        amount,
        user.id,
        tx_type,
        user.tokens,
    )
    return amount


# ---------------------------------------------------------------------------
# Query helpers (used by API routes)
# ---------------------------------------------------------------------------


async def get_balance(db: AsyncSession, user: User) -> dict:
    """Return the user's current token balance and daily status."""
    await check_and_reset_daily(db, user)
    return {
        "tokens": user.tokens,
        "daily_tokens_earned": user.daily_tokens_earned,
        "daily_cap": DAILY_TOKEN_CAP,
        "daily_remaining": max(0, DAILY_TOKEN_CAP - user.daily_tokens_earned),
    }


async def get_transactions(
    db: AsyncSession,
    user_id: uuid.UUID,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[TokenTransaction], int]:
    """Return paginated transactions for *user_id*.

    Returns ``(items, total_count)``.
    """
    # Total count
    count_stmt = (
        select(func.count(TokenTransaction.id))
        .where(TokenTransaction.user_id == user_id)
    )
    count_result = await db.execute(count_stmt)
    total = count_result.scalar_one()

    # Items
    stmt = (
        select(TokenTransaction)
        .where(TokenTransaction.user_id == user_id)
        .order_by(TokenTransaction.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    result = await db.execute(stmt)
    items = list(result.scalars().all())

    return items, total


async def get_daily_status(db: AsyncSession, user: User) -> dict:
    """Return detailed daily earning status."""
    await check_and_reset_daily(db, user)

    # Summarise today's transactions by type
    today = date.today()
    today_start = datetime(today.year, today.month, today.day, tzinfo=UTC)

    stmt = (
        select(TokenTransaction.type, func.sum(TokenTransaction.amount))
        .where(
            TokenTransaction.user_id == user.id,
            TokenTransaction.amount > 0,
            TokenTransaction.created_at >= today_start,
        )
        .group_by(TokenTransaction.type)
    )
    result = await db.execute(stmt)
    breakdown = {row[0]: row[1] for row in result.all()}

    return {
        "date": today.isoformat(),
        "daily_tokens_earned": user.daily_tokens_earned,
        "daily_cap": DAILY_TOKEN_CAP,
        "daily_remaining": max(0, DAILY_TOKEN_CAP - user.daily_tokens_earned),
        "breakdown": breakdown,
    }
