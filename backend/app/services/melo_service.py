"""M-Elo (Multi-Elo) service.

Maintains per-user, per-tag independent Elo ratings.
Each user-tag combination has its own Elo score that starts at the user's
current Global Elo when first created.

Key concepts:
- M-Elo initial value = user's current Global Elo (not a fixed constant)
- Learning shield: first_ac_at IS NULL means shield is active
- Shield deactivation: set first_ac_at on first AC for that tag
"""

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.models.user_tag_elo import UserTagElo

logger = logging.getLogger("code_arena.melo")


class MEloService:
    """Orchestrates M-Elo (per-tag Elo) operations.

    Stateless service class -- each method receives the resources
    it needs (db session) as parameters.
    """

    @staticmethod
    async def get_or_create_melo(
        db: AsyncSession,
        user_id: uuid.UUID,
        tag: str,
    ) -> UserTagElo:
        """Get an existing M-Elo record, or create one inheriting Global Elo.

        When creating a new record, the initial Elo value is set to the
        user's current Global Elo (from the users table), not a fixed 1200.

        Args:
            db: Async database session.
            user_id: The user's UUID.
            tag: The CF tag name (e.g. "dp", "graphs").

        Returns:
            The UserTagElo record (existing or newly created).
        """
        stmt = select(UserTagElo).where(
            UserTagElo.user_id == user_id,
            UserTagElo.tag == tag,
        )
        result = await db.execute(stmt)
        existing = result.scalar_one_or_none()
        if existing is not None:
            return existing

        # Fetch user's current Global Elo for initial value
        user = await db.get(User, user_id)
        if user is None:
            raise ValueError(f"User {user_id} not found")

        melo = UserTagElo(
            user_id=user_id,
            tag=tag,
            elo=user.elo,
            total_submissions=0,
            first_ac_at=None,
        )
        db.add(melo)
        await db.flush()

        logger.info(
            "Created M-Elo for user=%s tag=%s initial_elo=%d",
            user_id, tag, user.elo,
        )
        return melo

    @staticmethod
    async def get_all_melos(
        db: AsyncSession,
        user_id: uuid.UUID,
    ) -> list[UserTagElo]:
        """Get all M-Elo records for a user.

        Args:
            db: Async database session.
            user_id: The user's UUID.

        Returns:
            List of all UserTagElo records for the user.
        """
        stmt = (
            select(UserTagElo)
            .where(UserTagElo.user_id == user_id)
            .order_by(UserTagElo.tag)
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def update_melo(
        db: AsyncSession,
        user_id: uuid.UUID,
        tag: str,
        elo_change: int,
    ) -> UserTagElo:
        """Update the M-Elo for a user-tag combination.

        Increments total_submissions and adjusts Elo by the given amount.
        Creates the record if it does not exist.

        Args:
            db: Async database session.
            user_id: The user's UUID.
            tag: The CF tag name.
            elo_change: The Elo delta (positive for gain, negative for loss).

        Returns:
            The updated UserTagElo record.
        """
        melo = await MEloService.get_or_create_melo(db, user_id, tag)
        melo.elo += elo_change
        melo.total_submissions += 1
        await db.flush()

        logger.info(
            "Updated M-Elo user=%s tag=%s change=%d new_elo=%d",
            user_id, tag, elo_change, melo.elo,
        )
        return melo

    @staticmethod
    async def is_shield_active(
        db: AsyncSession,
        user_id: uuid.UUID,
        tag: str,
    ) -> bool:
        """Check whether the learning shield is active for a user-tag combination.

        The shield is active when first_ac_at is NULL, meaning the user has
        never AC'd a problem with this tag.

        Args:
            db: Async database session.
            user_id: The user's UUID.
            tag: The CF tag name.

        Returns:
            True if shield is active (no AC yet), False otherwise.
        """
        melo = await MEloService.get_or_create_melo(db, user_id, tag)
        return melo.first_ac_at is None

    @staticmethod
    async def deactivate_shield(
        db: AsyncSession,
        user_id: uuid.UUID,
        tag: str,
    ) -> UserTagElo:
        """Deactivate the learning shield by setting first_ac_at.

        This should be called when the user achieves their first AC for
        the given tag. If the shield is already deactivated, this is a no-op.

        Args:
            db: Async database session.
            user_id: The user's UUID.
            tag: The CF tag name.

        Returns:
            The updated UserTagElo record.
        """
        melo = await MEloService.get_or_create_melo(db, user_id, tag)
        if melo.first_ac_at is None:
            melo.first_ac_at = datetime.now(UTC)
            await db.flush()
            logger.info(
                "Shield deactivated for user=%s tag=%s", user_id, tag,
            )
        return melo

    @staticmethod
    async def batch_update_melo_for_problem(
        db: AsyncSession,
        user_id: uuid.UUID,
        problem_tags: list[str],
        problem_rating: int,
        s_value: float,
        k_factor: float,
        time_factor: float | None = None,
        hint_attenuation: float | None = None,
        coefficient: float = 1.0,
        *,
        solved: bool = True,
    ) -> dict[str, int]:
        """Update M-Elo for every tag of a completed problem.

        Implements the full M-Elo update formula per tag:
            change = K * (S - P(AC_melo)) * time_factor * hint_attenuation * coefficient

        Where P(AC_melo) is the expected score based on the tag's M-Elo
        vs the problem rating (NOT the global Elo).

        Also handles Learning Shield:
        - Shield active + failure: skip Elo deduction for that tag
        - Shield active + first AC: deactivate shield for that tag

        Args:
            db: Async database session.
            user_id: The user's UUID.
            problem_tags: List of CF tags for the problem (e.g. ["dp", "greedy"]).
            problem_rating: The problem's rating.
            s_value: The S-value (performance outcome, 0.0-1.0).
            k_factor: K-factor for this user.
            time_factor: Optional time factor multiplier for positive gains.
            hint_attenuation: Optional hint attenuation multiplier for positive gains.
            coefficient: Mode-specific coefficient (1.0 for PvP/PvE/Contest,
                         training uses 2.0 via its own path).
            solved: Whether the problem was solved (for shield logic).

        Returns:
            Dict mapping tag name to the Elo change applied (0 if skipped).
        """
        if not problem_tags:
            return {}

        results: dict[str, int] = {}

        for tag in problem_tags:
            # Get or create the M-Elo record for this user-tag
            melo_record = await MEloService.get_or_create_melo(db, user_id, tag)
            shield_active = melo_record.first_ac_at is None

            # Shield protection: skip Elo deduction on failure if shield is active
            if not solved and shield_active:
                logger.info(
                    "Shield active for user=%s tag=%s -- skipping M-Elo deduction",
                    user_id, tag,
                )
                results[tag] = 0
                continue

            # Deactivate shield on first AC
            if solved and shield_active:
                await MEloService.deactivate_shield(db, user_id, tag)
                logger.info(
                    "Shield deactivated for user=%s tag=%s on first AC",
                    user_id, tag,
                )

            # Calculate expected score based on tag M-Elo vs problem rating
            melo_expected = 1.0 / (1.0 + 10.0 ** ((problem_rating - melo_record.elo) / 400.0))

            # M-Elo change: K * (S - P(AC)) * coefficient
            melo_change = round(k_factor * (s_value - melo_expected) * coefficient)

            # Apply hint attenuation to positive gains
            if melo_change > 0 and hint_attenuation is not None:
                melo_change = round(melo_change * hint_attenuation)

            # Apply time factor to positive gains
            if melo_change > 0 and time_factor is not None:
                melo_change = round(melo_change * time_factor)

            # Apply the change
            if melo_change != 0:
                await MEloService.update_melo(db, user_id, tag, melo_change)

            results[tag] = melo_change

        return results
