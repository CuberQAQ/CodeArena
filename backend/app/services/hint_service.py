"""Hint system business logic service.

Handles hint purchase lifecycle:
- Checking hint status and pricing for a problem
- Unlocking hints with sequential level validation
- Retrieving hint content (only for unlocked levels)
- Recording and retrieving hint purchase history
- Elo decay preview and calculation
"""

import logging
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestException
from app.models.hint_purchase import HintPurchase
from app.models.user import User
from app.schemas.hint import (
    EloDecayPreview,
    HintContentResponse,
    HintHistoryItem,
    HintHistoryResponse,
    HintPriceInfo,
    HintStatusResponse,
    UnlockHintResponse,
)
from app.services import economy_service as economy_svc
from app.services.hint_content_service import HintContentService

logger = logging.getLogger("code_arena.hints")

# ---------------------------------------------------------------------------
# Hint pricing tiers by problem rating
# ---------------------------------------------------------------------------

_HINT_PRICE_TIERS: list[tuple[int, list[int]]] = [
    # (rating_threshold, [level_1, level_2, level_3])
    (1200, [3, 10, 20]),     # gray (800-1199)
    (1400, [5, 15, 30]),     # green (1200-1399)
    (1600, [6, 18, 35]),     # cyan (1400-1599)
    (1900, [8, 20, 40]),     # blue (1600-1899)
    (2100, [10, 25, 50]),    # purple (1900-2099)
    (2400, [12, 28, 55]),    # orange (2100-2399)
    (9999, [15, 30, 60]),    # red (2400+)
]

# Elo decay multipliers per hint level
_ELO_DECAY_MULTIPLIERS: dict[int, float] = {
    1: 0.75,
    2: 0.50,
    3: 0.25,
}


def get_hint_prices(rating: int) -> list[int]:
    """Return [level_1_price, level_2_price, level_3_price] for a given rating."""
    for threshold, prices in _HINT_PRICE_TIERS:
        if rating < threshold:
            return prices
    return _HINT_PRICE_TIERS[-1][1]


def get_elo_decay_multiplier(hint_level: int) -> float:
    """Return the Elo decay multiplier for a given hint level (1-3).

    Returns 1.0 (no decay) for level 0.
    """
    if hint_level <= 0:
        return 1.0
    return _ELO_DECAY_MULTIPLIERS.get(hint_level, 1.0)


# ---------------------------------------------------------------------------
# Hint Service
# ---------------------------------------------------------------------------


class HintService:
    """Orchestrates hint purchases and content delivery.

    Stateless service class -- each method receives the resources
    it needs (db session, external services) as parameters.
    """

    # ------------------------------------------------------------------
    # 1. Get hint status for a problem
    # ------------------------------------------------------------------

    @staticmethod
    async def get_hint_status(
        db: AsyncSession,
        user: User,
        problem_id: str,
        problem_rating: int,
    ) -> HintStatusResponse:
        """Get the hint status for a specific problem.

        Returns unlocked levels, prices for all levels, and Elo decay preview.
        """
        # Fetch user's existing purchases for this problem
        stmt = select(HintPurchase.hint_level).where(
            HintPurchase.user_id == user.id,
            HintPurchase.problem_id == problem_id,
        )
        result = await db.execute(stmt)
        unlocked_levels = sorted(row[0] for row in result.all())

        # Calculate prices for all levels
        prices_list = get_hint_prices(problem_rating)
        prices = [
            HintPriceInfo(level=i + 1, tokens=prices_list[i])
            for i in range(3)
        ]

        # Elo decay preview
        elo_decay_preview = [
            EloDecayPreview(level=i, multiplier=_ELO_DECAY_MULTIPLIERS[i])
            for i in range(1, 4)
        ]

        # Determine next unlockable level
        next_level = None
        next_level_price = None
        if not unlocked_levels:
            next_level = 1
            next_level_price = prices_list[0]
        elif unlocked_levels[-1] < 3:
            next_level = unlocked_levels[-1] + 1
            next_level_price = prices_list[next_level - 1]

        return HintStatusResponse(
            problem_id=problem_id,
            problem_rating=problem_rating,
            unlocked_levels=unlocked_levels,
            prices=prices,
            elo_decay_preview=elo_decay_preview,
            next_level=next_level,
            next_level_price=next_level_price,
        )

    # ------------------------------------------------------------------
    # 2. Unlock a hint level
    # ------------------------------------------------------------------

    @staticmethod
    async def unlock_hint(
        db: AsyncSession,
        user: User,
        problem_id: str,
        problem_rating: int,
        level: int,
        problem_tags: list[str] | None = None,
    ) -> UnlockHintResponse:
        """Unlock a hint level for a problem.

        Validates:
        - Level must be 1, 2, or 3
        - Cannot skip levels (must unlock 1 -> 2 -> 3)
        - Cannot re-unlock the same level
        - User must have sufficient tokens

        On success, deducts tokens and creates a HintPurchase record.
        """
        if level < 1 or level > 3:
            raise BadRequestException(message="Hint level must be 1, 2, or 3")

        # Check existing purchases
        stmt = select(HintPurchase.hint_level).where(
            HintPurchase.user_id == user.id,
            HintPurchase.problem_id == problem_id,
        )
        result = await db.execute(stmt)
        existing_levels = sorted(row[0] for row in result.all())

        # Validate: cannot re-unlock
        if level in existing_levels:
            raise BadRequestException(
                message=f"Hint level {level} is already unlocked for this problem"
            )

        # Validate: must unlock in order (1 -> 2 -> 3)
        if level == 1:
            # Level 1 can always be unlocked if not already done
            pass
        elif level == 2:
            if 1 not in existing_levels:
                raise BadRequestException(
                    message="Must unlock hint level 1 before level 2"
                )
        elif level == 3 and 2 not in existing_levels:
            raise BadRequestException(
                message="Must unlock hint levels 1 and 2 before level 3"
            )

        # Calculate price
        prices = get_hint_prices(problem_rating)
        cost = prices[level - 1]

        # Check balance
        if user.tokens < cost:
            raise BadRequestException(
                message=f"Insufficient tokens: have {user.tokens}, need {cost}"
            )

        # Spend tokens via economy service
        await economy_svc.spend_tokens(
            db=db,
            user=user,
            amount=cost,
            tx_type="hint_purchase",
            reference_type="hint",
        )

        # Create purchase record
        purchase = HintPurchase(
            user_id=user.id,
            problem_id=problem_id,
            problem_rating=problem_rating,
            hint_level=level,
            tokens_cost=cost,
        )
        db.add(purchase)
        await db.flush()

        logger.info(
            "User %s unlocked hint level %d for problem %s (cost=%d)",
            user.id,
            level,
            problem_id,
            cost,
        )

        return UnlockHintResponse(
            problem_id=problem_id,
            level=level,
            tokens_spent=cost,
            tokens_remaining=user.tokens,
        )

    # ------------------------------------------------------------------
    # 3. Get hint content
    # ------------------------------------------------------------------

    @staticmethod
    async def get_hint_content(
        db: AsyncSession,
        user: User,
        problem_id: str,
        level: int,
        problem_rating: int,
        problem_tags: list[str] | None = None,
    ) -> HintContentResponse:
        """Get hint content for a specific level.

        Only returns content for already-unlocked levels.
        """
        if level < 1 or level > 3:
            raise BadRequestException(message="Hint level must be 1, 2, or 3")

        # Check if this level is unlocked
        stmt = select(HintPurchase).where(
            HintPurchase.user_id == user.id,
            HintPurchase.problem_id == problem_id,
            HintPurchase.hint_level == level,
        )
        result = await db.execute(stmt)
        purchase = result.scalar_one_or_none()

        if purchase is None:
            raise BadRequestException(
                message=f"Hint level {level} is not unlocked for this problem"
            )

        # Generate hint content
        tags = problem_tags or []
        content = HintContentService.generate_hint(
            problem_id=problem_id,
            problem_rating=problem_rating,
            tags=tags,
            level=level,
        )

        return HintContentResponse(
            problem_id=problem_id,
            level=level,
            content=content,
            unlocked=True,
        )

    # ------------------------------------------------------------------
    # 4. Get hint purchase history for a problem
    # ------------------------------------------------------------------

    @staticmethod
    async def get_hint_history(
        db: AsyncSession,
        user: User,
        problem_id: str,
    ) -> HintHistoryResponse:
        """Get the user's hint purchase history for a specific problem."""
        stmt = (
            select(HintPurchase)
            .where(
                HintPurchase.user_id == user.id,
                HintPurchase.problem_id == problem_id,
            )
            .order_by(HintPurchase.hint_level.asc())
        )
        result = await db.execute(stmt)
        purchases = list(result.scalars().all())

        total_spent = sum(p.tokens_cost for p in purchases)

        items = [
            HintHistoryItem(
                id=p.id,
                problem_id=p.problem_id,
                hint_level=p.hint_level,
                tokens_cost=p.tokens_cost,
                created_at=p.created_at,
            )
            for p in purchases
        ]

        return HintHistoryResponse(
            problem_id=problem_id,
            purchases=items,
            total_spent=total_spent,
        )

    # ------------------------------------------------------------------
    # 5. Get max hint level unlocked for a user/problem (utility)
    # ------------------------------------------------------------------

    @staticmethod
    async def get_max_hint_level(
        db: AsyncSession,
        user_id: uuid.UUID,
        problem_id: str,
    ) -> int:
        """Return the maximum hint level unlocked by a user for a problem.

        Returns 0 if no hints have been unlocked.
        """
        stmt = select(func.max(HintPurchase.hint_level)).where(
            HintPurchase.user_id == user_id,
            HintPurchase.problem_id == problem_id,
        )
        result = await db.execute(stmt)
        max_level = result.scalar_one_or_none()
        return max_level if max_level is not None else 0
