"""Medal service -- XCPC-style medal tier mapping and awarding.

Handles:
- Medal tier mapping (FR-10.1): XCPC four-level tier thresholds
- Overall medal calculation (FR-10.2): Global Elo -> real-time medal
- Skill medal calculation (FR-10.3): Per-tag M-Elo -> real-time medal
- Contest medal awarding (FR-10.4): PR -> medal based on tier thresholds
- Medal statistics (FR-10.5): Permanent record aggregation
"""

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contest_medal import ContestMedal
from app.models.user_tag_elo import UserTagElo

logger = logging.getLogger("code_arena.medal")

# ---------------------------------------------------------------------------
# Medal tier thresholds (FR-10.1)
# Flat, non-overlapping medal mapping (threshold, level, medal_type).
# Iterated from highest threshold to lowest; the first match wins.
# NOTE: ec_final tier has overlapping thresholds with world_finals and regional
# (MEDAL_TIERS defines ec_final gold=2600/silver=2400/bronze=2200, but these
# overlap with world_finals silver=2600/bronze=2400 and regional gold=2200).
# The flat map currently uses world_finals and regional mappings for the
# overlapping ranges. ec_full is only used for display/config purposes.
# See human_todo.md for the design decision needed on threshold overlap.
# ---------------------------------------------------------------------------

_FLAT_MEDAL_MAP: list[tuple[int, str, str]] = [
    (2800, "world_finals", "gold"),
    (2600, "world_finals", "silver"),
    (2400, "world_finals", "bronze"),
    (2200, "regional", "gold"),
    (2000, "regional", "silver"),
    (1800, "regional", "bronze"),
    (1600, "provincial", "gold"),
    (1400, "provincial", "silver"),
    (1200, "provincial", "bronze"),
]

MEDAL_TIERS: list[dict] = [
    {
        "level": "world_finals",
        "gold": 2800,
        "silver": 2600,
        "bronze": 2400,
    },
    {
        "level": "ec_final",
        "gold": 2600,
        "silver": 2400,
        "bronze": 2200,
    },
    {
        "level": "regional",
        "gold": 2200,
        "silver": 2000,
        "bronze": 1800,
    },
    {
        "level": "provincial",
        "gold": 1600,
        "silver": 1400,
        "bronze": 1200,
    },
]

# Minimum rating for any medal (provincial bronze)
_MIN_MEDAL_RATING = 1200


class MedalService:
    """Stateless service for medal calculations and awards.

    All methods are static and receive the resources they need as parameters.
    """

    # ------------------------------------------------------------------
    # Medal calculation (pure functions)
    # ------------------------------------------------------------------

    @staticmethod
    def calculate_overall_medal(elo: int) -> dict:
        """Calculate the overall medal based on Global Elo.

        Traverses MEDAL_TIERS from highest to lowest, returning the first
        tier where the rating meets a medal threshold.

        Parameters
        ----------
        elo : int
            The user's current Global Elo rating.

        Returns
        -------
        dict
            ``{"level": "regional", "type": "gold"}`` or ``{"level": "unranked"}``.
        """
        return MedalService._rating_to_medal(elo)

    @staticmethod
    def calculate_skill_medal(melo: int) -> dict:
        """Calculate the skill-specific medal based on tag M-Elo.

        Uses the same tier mapping as overall medals.

        Parameters
        ----------
        melo : int
            The user's M-Elo rating for a specific tag.

        Returns
        -------
        dict
            ``{"level": "regional", "type": "gold"}`` or ``{"level": "unranked"}``.
        """
        return MedalService._rating_to_medal(melo)

    @staticmethod
    def _rating_to_medal(rating: int) -> dict:
        """Map a numeric rating to a medal tier + type.

        Uses a flat, non-overlapping threshold list.  Iterates from
        highest threshold to lowest; the first match wins.

        Examples:
          2200 -> regional gold, 2100 -> regional silver, 1800 -> regional bronze
          2800 -> world_finals gold, 2600 -> world_finals silver
        """
        for threshold, level, medal_type in _FLAT_MEDAL_MAP:
            if rating >= threshold:
                return {"level": level, "type": medal_type}
        return {"level": "unranked"}

    # ------------------------------------------------------------------
    # Contest medal awarding (FR-10.4)
    # ------------------------------------------------------------------

    @staticmethod
    async def award_contest_medal(
        db: AsyncSession,
        user_id: uuid.UUID,
        contest_session_id: uuid.UUID,
        pr: int,
    ) -> ContestMedal | None:
        """Award a contest medal based on Performance Rating.

        Calculates the medal corresponding to the PR value and, if the user
        earned a medal (i.e. PR >= 1200), creates a permanent record.
        Duplicate awards for the same contest are prevented by a unique
        constraint on (user_id, contest_session_id).

        Parameters
        ----------
        db : AsyncSession
            Database session.
        user_id : UUID
            The user who participated.
        contest_session_id : UUID
            The contest session ID.
        pr : int
            Performance Rating from the contest.

        Returns
        -------
        ContestMedal | None
            The created medal record, or ``None`` if no medal was earned.
        """
        medal_info = MedalService._rating_to_medal(pr)

        if medal_info["level"] == "unranked":
            return None

        # Check for existing medal to avoid duplicates
        existing_stmt = select(ContestMedal).where(
            ContestMedal.user_id == user_id,
            ContestMedal.contest_session_id == contest_session_id,
        )
        existing_result = await db.execute(existing_stmt)
        existing = existing_result.scalar_one_or_none()
        if existing is not None:
            return None

        # Create permanent medal record
        medal = ContestMedal(
            user_id=user_id,
            contest_session_id=contest_session_id,
            medal_level=medal_info["level"],
            medal_type=medal_info["type"],
            pr_value=pr,
            awarded_at=datetime.now(UTC),
        )
        db.add(medal)
        await db.flush()

        logger.info(
            "Awarded %s %s medal to user %s for contest %s (PR=%d)",
            medal_info["level"],
            medal_info["type"],
            user_id,
            contest_session_id,
            pr,
        )

        return medal

    # ------------------------------------------------------------------
    # Medal statistics (FR-10.5)
    # ------------------------------------------------------------------

    @staticmethod
    async def get_user_medal_stats(db: AsyncSession, user_id: uuid.UUID) -> dict:
        """Get aggregated medal statistics for a user's trophy cabinet.

        Groups medals by level and type, counting each.

        Parameters
        ----------
        db : AsyncSession
            Database session.
        user_id : UUID
            The user whose stats to retrieve.

        Returns
        -------
        dict
            e.g. ``{"regional": {"gold": 3, "silver": 1}, "provincial": {"gold": 2}}``
        """
        stmt = (
            select(
                ContestMedal.medal_level,
                ContestMedal.medal_type,
                func.count(ContestMedal.id).label("count"),
            )
            .where(ContestMedal.user_id == user_id)
            .group_by(ContestMedal.medal_level, ContestMedal.medal_type)
            .order_by(ContestMedal.medal_level, ContestMedal.medal_type)
        )
        result = await db.execute(stmt)
        rows = result.all()

        stats: dict[str, dict[str, int]] = {}
        for row in rows:
            level = row.medal_level
            medal_type = row.medal_type
            count = row.count
            if level not in stats:
                stats[level] = {}
            stats[level][medal_type] = count

        return stats

    # ------------------------------------------------------------------
    # Skill medals for all tags (FR-10.3)
    # ------------------------------------------------------------------

    @staticmethod
    async def get_all_skill_medals(db: AsyncSession, user_id: uuid.UUID) -> dict:
        """Get medal mapping for all user skill tags.

        Parameters
        ----------
        db : AsyncSession
            Database session.
        user_id : UUID
            The user whose skill medals to retrieve.

        Returns
        -------
        dict
            e.g. ``{"dp": {"level": "regional", "type": "bronze", "melo": 1800}, ...}``
        """
        stmt = select(UserTagElo).where(UserTagElo.user_id == user_id)
        result = await db.execute(stmt)
        tag_elos = result.scalars().all()

        skill_medals: dict = {}
        for tag_elo in tag_elos:
            medal = MedalService.calculate_skill_medal(tag_elo.elo)
            skill_medals[tag_elo.tag] = {
                **medal,
                "melo": tag_elo.elo,
            }

        return skill_medals
