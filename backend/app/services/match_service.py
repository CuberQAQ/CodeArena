"""Matchmaking service for random challenge mode.

Manages an in-memory match queue using a dict + asyncio.Lock.
Implements probability-weighted opponent selection based on Elo gap.
"""

import asyncio
import logging
import random
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

logger = logging.getLogger("code_arena.match")


# ---------------------------------------------------------------------------
# Queue entry
# ---------------------------------------------------------------------------


@dataclass
class QueueEntry:
    """Represents a player waiting in the match queue."""

    user_id: uuid.UUID
    elo: int
    username: str
    cf_handle: str | None = None
    joined_at: datetime = field(default_factory=lambda: datetime.now(UTC))


# ---------------------------------------------------------------------------
# Weight configuration for Elo-gap tiers
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MatchWeightConfig:
    """Probability weights for opponent selection by Elo gap.

    The four tiers sum to 1.0:
    - close (gap <= 100): high chance of matching
    - challenge (gap 100-300, higher-rated opponent): moderate
    - consolidate (gap 100-300, lower-rated opponent): lower
    - far (gap > 300): minimal
    """

    close: float = 0.50
    challenge: float = 0.25
    consolidate: float = 0.15
    far: float = 0.10


_DEFAULT_WEIGHT_CONFIG = MatchWeightConfig()


# ---------------------------------------------------------------------------
# Match result
# ---------------------------------------------------------------------------


@dataclass
class MatchResult:
    """Result of a successful match."""

    session_id: uuid.UUID
    player_a: QueueEntry
    player_b: QueueEntry
    avg_elo: float


# ---------------------------------------------------------------------------
# Match Service (singleton state)
# ---------------------------------------------------------------------------


class MatchService:
    """In-memory matchmaking service.

    All state lives in process memory -- no database persistence.
    The queue is keyed by user_id to prevent duplicate entries.
    """

    def __init__(self, weight_config: MatchWeightConfig | None = None) -> None:
        self._queue: dict[uuid.UUID, QueueEntry] = {}
        self._lock = asyncio.Lock()
        self._weight_config = weight_config or _DEFAULT_WEIGHT_CONFIG

    # ------------------------------------------------------------------
    # Queue management
    # ------------------------------------------------------------------

    async def join_queue(self, user_id: uuid.UUID, elo: int, username: str, cf_handle: str | None = None) -> bool:
        """Add a user to the match queue.

        Returns True if the user was added, False if already in queue.
        """
        async with self._lock:
            if user_id in self._queue:
                return False
            self._queue[user_id] = QueueEntry(
                user_id=user_id,
                elo=elo,
                username=username,
                cf_handle=cf_handle,
            )
            logger.info("User %s (elo=%d) joined match queue", username, elo)
            return True

    async def leave_queue(self, user_id: uuid.UUID) -> bool:
        """Remove a user from the match queue.

        Returns True if the user was removed, False if not in queue.
        """
        async with self._lock:
            entry = self._queue.pop(user_id, None)
            if entry is not None:
                logger.info("User %s left match queue", entry.username)
                return True
            return False

    async def is_in_queue(self, user_id: uuid.UUID) -> bool:
        """Check whether a user is currently in the queue."""
        async with self._lock:
            return user_id in self._queue

    async def get_queue_size(self) -> int:
        """Return the current number of players in the queue."""
        async with self._lock:
            return len(self._queue)

    # ------------------------------------------------------------------
    # Matching
    # ------------------------------------------------------------------

    def _calculate_weight(self, elo_gap: int) -> float:
        """Return the probability weight for a given absolute Elo gap."""
        gap = abs(elo_gap)
        cfg = self._weight_config
        if gap <= 100:
            return cfg.close
        if gap <= 300:
            # Challenge zone if opponent is stronger, consolidate if weaker
            # Both fall in the 100-300 band; split the weight proportionally
            if elo_gap > 0:
                # Opponent is stronger (higher elo) -> challenge
                return cfg.challenge
            return cfg.consolidate
        return cfg.far

    def _select_opponent(self, player: QueueEntry, candidates: list[QueueEntry]) -> QueueEntry | None:
        """Select an opponent using probability-weighted random choice.

        Parameters
        ----------
        player :
            The player looking for a match.
        candidates :
            Other players in the queue.

        Returns
        -------
        QueueEntry or None
            Selected opponent, or None if no candidates.
        """
        if not candidates:
            return None

        weights = [self._calculate_weight(c.elo - player.elo) for c in candidates]
        total_weight = sum(weights)
        if total_weight <= 0:
            # Fallback: uniform random
            return random.choice(candidates)

        # Normalise and pick
        r = random.uniform(0, total_weight)
        cumulative = 0.0
        for candidate, w in zip(candidates, weights, strict=True):
            cumulative += w
            if r <= cumulative:
                return candidate

        # Edge case: floating point imprecision -> return last
        return candidates[-1]

    async def try_match(self, user_id: uuid.UUID) -> MatchResult | None:
        """Attempt to find a match for a specific user.

        If a suitable opponent is found, both players are removed from the
        queue and a MatchResult is returned.  Returns None if no match found.

        This should be called after a user joins the queue.
        """
        async with self._lock:
            player = self._queue.get(user_id)
            if player is None:
                return None

            # Collect candidates (everyone except the player)
            candidates = [e for uid, e in self._queue.items() if uid != user_id]
            if not candidates:
                return None

            opponent = self._select_opponent(player, candidates)
            if opponent is None:
                return None

            # Remove both from queue
            del self._queue[player.user_id]
            del self._queue[opponent.user_id]

            avg_elo = (player.elo + opponent.elo) / 2.0
            session_id = uuid.uuid4()

            logger.info(
                "Match found: %s (elo=%d) vs %s (elo=%d), avg_elo=%.0f, session=%s",
                player.username,
                player.elo,
                opponent.username,
                opponent.elo,
                avg_elo,
                session_id,
            )

            return MatchResult(
                session_id=session_id,
                player_a=player,
                player_b=opponent,
                avg_elo=avg_elo,
            )

    async def try_match_any(self) -> list[MatchResult]:
        """Attempt to match all possible pairs in the queue.

        Returns a list of MatchResult for all pairs matched. Used by
        background polling if needed.
        """
        results: list[MatchResult] = []
        async with self._lock:
            user_ids = list(self._queue.keys())

        for uid in user_ids:
            # try_match will handle lock internally; skip if already matched
            if uid not in self._queue:
                continue
            result = await self.try_match(uid)
            if result is not None:
                results.append(result)

        return results


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_match_service: MatchService | None = None


def get_match_service() -> MatchService:
    """Return the module-level MatchService singleton."""
    global _match_service
    if _match_service is None:
        _match_service = MatchService()
    return _match_service
