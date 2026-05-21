"""Matchmaking service for random challenge mode.

Manages a match queue backed by Redis (Sorted Set + Hash) so that state is
shared across multiple Gunicorn workers.  Implements probability-weighted
opponent selection based on Elo gap.

All Redis operations are wrapped via ``safe_redis_call()`` so that connectivity
errors are translated to ``RedisUnavailableError`` (which the FastAPI app
maps to HTTP 503).  Queue mutations (join / leave / match) use optimistic
locking (WATCH/MULTI/EXEC) to prevent check-then-act races.
"""

import json
import logging
import random
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

import redis.asyncio as aioredis

from app.core.redis import get_redis, safe_redis_call

logger = logging.getLogger("code_arena.match")

# Redis key constants
QUEUE_SCORES_KEY = "match_queue:scores"  # Sorted Set: score=elo, member=user_id
QUEUE_ENTRIES_KEY = "match_queue:entries"  # Hash: field=user_id, value=JSON entry

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


def _entry_to_json(entry: QueueEntry) -> str:
    """Serialize a QueueEntry to JSON for Redis storage."""
    return json.dumps(
        {
            "user_id": str(entry.user_id),
            "elo": entry.elo,
            "username": entry.username,
            "cf_handle": entry.cf_handle,
            "joined_at": entry.joined_at.isoformat(),
        }
    )


def _entry_from_json(user_id_str: str, data: str) -> QueueEntry:
    """Deserialize a QueueEntry from Redis JSON."""
    obj = json.loads(data)
    return QueueEntry(
        user_id=uuid.UUID(obj["user_id"]),
        elo=obj["elo"],
        username=obj["username"],
        cf_handle=obj.get("cf_handle"),
        joined_at=datetime.fromisoformat(obj["joined_at"]),
    )


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
# Match Service (Redis-backed)
# ---------------------------------------------------------------------------


class MatchService:
    """Redis-backed matchmaking service.

    Queue state lives in Redis so it is shared across all workers.
    Uses a Sorted Set (scored by Elo) for range queries and a Hash
    for full entry data.  Atomic match removal uses optimistic locking
    (WATCH/MULTI/EXEC) which is compatible with both real Redis and
    fakeredis.
    """

    def __init__(self, weight_config: MatchWeightConfig | None = None) -> None:
        self._weight_config = weight_config or _DEFAULT_WEIGHT_CONFIG

    # ------------------------------------------------------------------
    # Queue management
    # ------------------------------------------------------------------

    async def join_queue(self, user_id: uuid.UUID, elo: int, username: str, cf_handle: str | None = None) -> bool:
        """Add a user to the match queue.

        Returns True if the user was added, False if already in queue.
        Raises RedisUnavailableError if Redis is unreachable.
        """
        redis = get_redis()
        uid_str = str(user_id)
        entry = QueueEntry(user_id=user_id, elo=elo, username=username, cf_handle=cf_handle)

        # Retry loop for optimistic locking (WATCH/MULTI/EXEC)
        for _ in range(3):
            try:
                async with redis.pipeline(transaction=True) as pipe:
                    await pipe.watch(QUEUE_ENTRIES_KEY)

                    # Check existence inside the watched context
                    exists = await pipe.hexists(QUEUE_ENTRIES_KEY, uid_str)
                    if exists:
                        await pipe.unwatch()
                        return False

                    pipe.multi()
                    pipe.zadd(QUEUE_SCORES_KEY, {uid_str: elo})
                    pipe.hset(QUEUE_ENTRIES_KEY, uid_str, _entry_to_json(entry))
                    await safe_redis_call(pipe.execute())
                    # Success -- added atomically
                    break
            except aioredis.WatchError:
                # Another worker modified the entries hash -- retry
                continue
        else:
            # All retries exhausted due to contention
            return False

        logger.info("User %s (elo=%d) joined match queue", username, elo)
        return True

    async def leave_queue(self, user_id: uuid.UUID) -> bool:
        """Remove a user from the match queue.

        Returns True if the user was removed, False if not in queue.
        Raises RedisUnavailableError if Redis is unreachable.
        """
        redis = get_redis()
        uid_str = str(user_id)

        # Retry loop for optimistic locking (WATCH/MULTI/EXEC)
        for _ in range(3):
            try:
                async with redis.pipeline(transaction=True) as pipe:
                    await pipe.watch(QUEUE_ENTRIES_KEY)

                    # Check existence inside the watched context
                    exists = await pipe.hexists(QUEUE_ENTRIES_KEY, uid_str)
                    if not exists:
                        await pipe.unwatch()
                        return False

                    pipe.multi()
                    pipe.zrem(QUEUE_SCORES_KEY, uid_str)
                    pipe.hdel(QUEUE_ENTRIES_KEY, uid_str)
                    await safe_redis_call(pipe.execute())
                    # Success -- removed atomically
                    break
            except aioredis.WatchError:
                # Another worker modified the entries hash -- retry
                continue
        else:
            # All retries exhausted due to contention
            return False

        logger.info("User %s left match queue", uid_str)
        return True

    async def is_in_queue(self, user_id: uuid.UUID) -> bool:
        """Check whether a user is currently in the queue."""
        redis = get_redis()
        return await safe_redis_call(redis.hexists(QUEUE_ENTRIES_KEY, str(user_id)))

    async def get_queue_size(self) -> int:
        """Return the current number of players in the queue."""
        redis = get_redis()
        return await safe_redis_call(redis.zcard(QUEUE_SCORES_KEY))

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
            if elo_gap > 0:
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
            return random.choice(candidates)

        r = random.uniform(0, total_weight)
        cumulative = 0.0
        for candidate, w in zip(candidates, weights, strict=False):
            cumulative += w
            if r <= cumulative:
                return candidate

        return candidates[-1]

    async def try_match(self, user_id: uuid.UUID) -> MatchResult | None:
        """Attempt to find a match for a specific user.

        If a suitable opponent is found, both players are removed from the
        queue atomically using optimistic locking (WATCH/MULTI/EXEC) and a
        MatchResult is returned.  Returns None if no match found.
        """
        redis = get_redis()
        uid_str = str(user_id)
        opp_str: str | None = None

        # Retry loop for optimistic locking
        for _ in range(3):
            # Get player entry
            player_data = await safe_redis_call(redis.hget(QUEUE_ENTRIES_KEY, uid_str))
            if player_data is None:
                return None

            player = _entry_from_json(uid_str, player_data)

            # Get all other entries
            all_entries = await safe_redis_call(redis.hgetall(QUEUE_ENTRIES_KEY))
            candidates: list[QueueEntry] = []
            for other_uid, other_data in all_entries.items():
                if other_uid != uid_str:
                    candidates.append(_entry_from_json(other_uid, other_data))

            if not candidates:
                return None

            opponent = self._select_opponent(player, candidates)
            if opponent is None:
                return None

            opp_str = str(opponent.user_id)

            # Optimistic locking: WATCH the entries hash, then verify both still exist
            # and remove them in a MULTI/EXEC transaction.
            try:
                async with redis.pipeline(transaction=True) as pipe:
                    await pipe.watch(QUEUE_ENTRIES_KEY)

                    # Re-check both entries still exist after WATCH
                    a_exists = await pipe.hexists(QUEUE_ENTRIES_KEY, uid_str)
                    b_exists = await pipe.hexists(QUEUE_ENTRIES_KEY, opp_str)
                    if not a_exists or not b_exists:
                        await pipe.unwatch()
                        return None  # One was already matched by another worker

                    pipe.multi()
                    pipe.zrem(QUEUE_SCORES_KEY, uid_str)
                    pipe.zrem(QUEUE_SCORES_KEY, opp_str)
                    pipe.hdel(QUEUE_ENTRIES_KEY, uid_str)
                    pipe.hdel(QUEUE_ENTRIES_KEY, opp_str)
                    await safe_redis_call(pipe.execute())
                    # Success -- both removed atomically
                    break
            except aioredis.WatchError:
                # Another worker modified the entries hash -- retry
                continue
        else:
            # All retries exhausted due to contention
            return None

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

        Returns a list of MatchResult for all pairs matched.
        """
        redis = get_redis()
        results: list[MatchResult] = []

        # Get all user IDs in the queue
        user_ids = await safe_redis_call(redis.zrange(QUEUE_SCORES_KEY, 0, -1))

        for uid_str in user_ids:
            # try_match handles the "already removed" case
            try:
                uid = uuid.UUID(uid_str)
            except (ValueError, AttributeError):
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
