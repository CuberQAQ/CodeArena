"""Token-bucket rate limiter for async contexts.

Provides an ``asyncio.Lock``-guarded token bucket that ensures at least
*min_interval* seconds elapse between consecutive acquisitions.
"""

import asyncio
import time


class TokenBucketRateLimiter:
    """Async token-bucket rate limiter.

    Parameters
    ----------
    min_interval:
        Minimum number of seconds that must elapse between two consecutive
        permit acquisitions.  The bucket refills at a rate of ``1 /
        min_interval`` tokens per second and holds at most one token.
    """

    def __init__(self, min_interval: float = 2.0) -> None:
        self._min_interval = min_interval
        self._tokens: float = 1.0  # start with one available permit
        self._last_refill: float = time.monotonic()
        self._lock = asyncio.Lock()

    def _refill(self) -> None:
        if self._min_interval <= 0:
            self._tokens = 1.0
            self._last_refill = time.monotonic()
            return
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(1.0, self._tokens + elapsed / self._min_interval)
        self._last_refill = now

    async def acquire(self) -> None:
        """Block until a permit is available.

        Uses ``asyncio.sleep`` for the wait so the event loop is not blocked.
        """
        if self._min_interval <= 0:
            return
        async with self._lock:
            self._refill()
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return

            # Calculate how long until next token is available
            deficit = 1.0 - self._tokens
            wait_time = deficit * self._min_interval
            self._tokens = 0.0

        # Sleep *outside* the lock so other waiters can queue up
        await asyncio.sleep(wait_time)

        # Re-acquire the lock and take the token
        async with self._lock:
            self._refill()
            self._tokens -= 1.0

    @property
    def min_interval(self) -> float:
        return self._min_interval
