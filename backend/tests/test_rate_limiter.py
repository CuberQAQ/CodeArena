"""Tests for the TokenBucketRateLimiter.

Covers:
- Immediate acquisition when bucket has a token
- Waiting when bucket is empty
- Token refill after min_interval elapses
- Zero/negative min_interval (no limiting)
- Concurrent acquisition queuing
- Property access
"""

from __future__ import annotations

import asyncio
import contextlib
import time

import pytest

from app.utils.rate_limiter import TokenBucketRateLimiter


class TestTokenBucketRateLimiterBasic:
    def test_default_min_interval(self):
        limiter = TokenBucketRateLimiter()
        assert limiter.min_interval == 2.0

    def test_custom_min_interval(self):
        limiter = TokenBucketRateLimiter(min_interval=0.5)
        assert limiter.min_interval == 0.5

    @pytest.mark.asyncio
    async def test_first_acquire_immediate(self):
        """First acquire should succeed immediately (bucket starts with 1 token)."""
        limiter = TokenBucketRateLimiter(min_interval=1.0)
        start = time.monotonic()
        await limiter.acquire()
        elapsed = time.monotonic() - start
        assert elapsed < 0.1  # Should be near-instant

    @pytest.mark.asyncio
    async def test_second_acquire_waits(self):
        """Second acquire should wait approximately min_interval."""
        limiter = TokenBucketRateLimiter(min_interval=0.2)
        await limiter.acquire()
        start = time.monotonic()
        await limiter.acquire()
        elapsed = time.monotonic() - start
        # Should wait at least ~0.2s, but allow some timing slack
        assert elapsed >= 0.1

    @pytest.mark.asyncio
    async def test_refill_after_interval(self):
        """Token should refill after min_interval seconds pass."""
        limiter = TokenBucketRateLimiter(min_interval=0.1)
        # Consume the initial token
        await limiter.acquire()
        # Wait long enough for refill
        await asyncio.sleep(0.15)
        # This should succeed immediately (token refilled)
        start = time.monotonic()
        await limiter.acquire()
        elapsed = time.monotonic() - start
        assert elapsed < 0.05

    @pytest.mark.asyncio
    async def test_zero_min_interval(self):
        """With min_interval=0, all acquires should be instant."""
        limiter = TokenBucketRateLimiter(min_interval=0)
        for _ in range(10):
            start = time.monotonic()
            await limiter.acquire()
            elapsed = time.monotonic() - start
            assert elapsed < 0.05

    @pytest.mark.asyncio
    async def test_negative_min_interval(self):
        """Negative min_interval should behave like zero (no limiting)."""
        limiter = TokenBucketRateLimiter(min_interval=-1.0)
        for _ in range(5):
            start = time.monotonic()
            await limiter.acquire()
            elapsed = time.monotonic() - start
            assert elapsed < 0.05

    @pytest.mark.asyncio
    async def test_multiple_rapid_acquires(self):
        """Multiple rapid acquires should each wait the appropriate time."""
        limiter = TokenBucketRateLimiter(min_interval=0.1)
        times = []
        for _ in range(3):
            await limiter.acquire()
            times.append(time.monotonic())

        # First acquire is instant, subsequent ones wait
        # The gap between each should be at least ~min_interval
        gap1 = times[1] - times[0]
        gap2 = times[2] - times[1]
        assert gap1 >= 0.05  # Allow timing slack
        assert gap2 >= 0.05


class TestTokenBucketRateLimiterConcurrency:
    @pytest.mark.asyncio
    async def test_concurrent_acquires(self):
        """Concurrent acquires should be serialized, not drop requests."""
        limiter = TokenBucketRateLimiter(min_interval=0.1)
        count = 0
        done = asyncio.Event()

        async def worker():
            nonlocal count
            await limiter.acquire()
            count += 1
            if count == 5:
                done.set()

        # Launch 5 concurrent workers
        tasks = [asyncio.create_task(worker()) for _ in range(5)]
        await asyncio.wait_for(done.wait(), timeout=5.0)
        # Cancel any remaining tasks
        for t in tasks:
            t.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await t

        assert count == 5  # All acquires should succeed (just serialized)

    @pytest.mark.asyncio
    async def test_no_token_loss_under_contention(self):
        """Under contention, every acquire should eventually succeed."""
        limiter = TokenBucketRateLimiter(min_interval=0.05)
        results = []

        async def acquire_and_record(i):
            await limiter.acquire()
            results.append(i)

        tasks = [asyncio.create_task(acquire_and_record(i)) for i in range(4)]
        await asyncio.gather(*tasks)

        # All 4 acquires should complete
        assert len(results) == 4
        assert set(results) == {0, 1, 2, 3}


class TestTokenBucketRefillMechanics:
    @pytest.mark.asyncio
    async def test_partial_refill(self):
        """Token partially refills: if only half the interval elapsed, need to wait."""
        limiter = TokenBucketRateLimiter(min_interval=0.2)
        # Use the initial token
        await limiter.acquire()
        # Wait only half the interval - token is partially refilled
        await asyncio.sleep(0.1)
        # Next acquire should wait for the remaining refill time
        start = time.monotonic()
        await limiter.acquire()
        elapsed = time.monotonic() - start
        # Should have waited approximately the remaining half (~0.1s)
        assert elapsed >= 0.05
