"""Achievement event detection service.

Lightweight service that generates achievement events based on game outcomes.
Events are ephemeral (not persisted to DB) -- they are returned as part of
settlement API responses and consumed by the frontend for visual effects.

Requirement: requirements.md Section 3.5 and FR-2.3 mandate that overkill
bonus and other high-achievement events trigger achievement events for
frontend display.
"""

from dataclasses import dataclass
from enum import StrEnum

# ---------------------------------------------------------------------------
# Achievement types
# ---------------------------------------------------------------------------


class AchievementType(StrEnum):
    """Enumeration of all achievement event types."""

    OVERKILL_BONUS = "overkill_bonus"
    CONTEST_WIN = "contest_win"
    PERSONAL_BEST_PP = "personal_best_pp"


# ---------------------------------------------------------------------------
# Achievement event data
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AchievementEvent:
    """A single achievement event returned to the frontend.

    Attributes
    ----------
    type :
        The achievement category.
    title :
        Short display title (localized Chinese).
    description :
        Detailed description with context-specific numbers.
    icon :
        Lucide icon name for frontend rendering.
    """

    type: AchievementType
    title: str
    description: str
    icon: str

    def to_dict(self) -> dict:
        """Convert to a plain dict suitable for JSON serialization."""
        return {
            "type": self.type.value,
            "title": self.title,
            "description": self.description,
            "icon": self.icon,
        }


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class AchievementService:
    """Stateless service for detecting achievement events.

    Each static method checks a specific condition and returns an
    ``AchievementEvent`` if the condition is met, or ``None`` otherwise.
    """

    @staticmethod
    def check_overkill(
        user_elo: int,
        problem_rating: int,
        multiplier: float,
    ) -> AchievementEvent | None:
        """Detect an overkill bonus achievement.

        Triggered when the PP overkill multiplier is greater than 1.0,
        meaning the user solved a problem significantly above their Elo.

        Parameters
        ----------
        user_elo :
            The user's current Elo rating.
        problem_rating :
            The difficulty rating of the solved problem.
        multiplier :
            The overkill multiplier already calculated by PPService.

        Returns
        -------
        AchievementEvent | None
            An ``OVERKILL_BONUS`` event if ``multiplier > 1.0``, else ``None``.
        """
        if multiplier <= 1.0:
            return None

        # Choose description based on multiplier tier
        if multiplier >= 2.0:
            tier_label = "x2.0"
        elif multiplier >= 1.5:
            tier_label = "x1.5"
        else:
            tier_label = "x1.2"

        return AchievementEvent(
            type=AchievementType.OVERKILL_BONUS,
            title="越级挑战!",  # "越级挑战!"
            description=(
                f"你以 {user_elo} Elo 解决了 {problem_rating} 难度的题目! PP {tier_label}"  # noqa: RUF001
            ),
            icon="zap",
        )

    @staticmethod
    def check_contest_win(
        rank: int,
        total_participants: int,
    ) -> AchievementEvent | None:
        """Detect a contest win achievement.

        Triggered when the user places 1st in a contest with more than
        one participant (bots + user).

        Parameters
        ----------
        rank :
            The user's final rank (1-based).
        total_participants :
            Total number of participants (bots + user).

        Returns
        -------
        AchievementEvent | None
            A ``CONTEST_WIN`` event if ``rank == 1`` and
            ``total_participants > 1``, else ``None``.
        """
        if rank != 1 or total_participants <= 1:
            return None

        return AchievementEvent(
            type=AchievementType.CONTEST_WIN,
            title="冠军!",  # "冠军!"
            description=(f"你在 {total_participants} 名参赛者中 荣获第一名!"),
            icon="trophy",
        )

    @staticmethod
    def check_personal_best_pp(
        new_pp: float,
        old_pp: float,
    ) -> AchievementEvent | None:
        """Detect a personal best PP achievement.

        Triggered when the user's total PP exceeds their previous all-time
        high.  The ``old_pp`` must be positive to avoid triggering on the
        very first PP record (which is not a "new record" moment).

        Parameters
        ----------
        new_pp :
            The user's updated total PP.
        old_pp :
            The user's total PP before this settlement.

        Returns
        -------
        AchievementEvent | None
            A ``PERSONAL_BEST_PP`` event if ``new_pp > old_pp`` and
            ``old_pp > 0``, else ``None``.
        """
        if old_pp <= 0 or new_pp <= old_pp:
            return None

        return AchievementEvent(
            type=AchievementType.PERSONAL_BEST_PP,
            title="个人最佳!",  # "个人最佳!"
            description=(f"你的总 PP 刷新了历史纪录! {old_pp:.1f} → {new_pp:.1f}"),
            icon="star",
        )
