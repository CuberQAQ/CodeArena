"""Redis connection management.

Provides a shared async Redis client via a connection pool.
Includes graceful degradation: if Redis is unavailable, operations
raise RedisUnavailableError which callers should handle as 503.
"""

import logging
from typing import Any

import redis.asyncio as aioredis

from app.core.config import settings

logger = logging.getLogger("code_arena.redis")

# Module-level pool and client -- initialized in lifespan, closed on shutdown.
_pool: aioredis.Redis | None = None


async def init_redis_pool() -> aioredis.Redis:
    """Create the Redis connection pool. Called once at startup."""
    global _pool
    _pool = aioredis.from_url(
        settings.REDIS_URL,
        decode_responses=True,
        max_connections=20,
        socket_connect_timeout=5,
        socket_timeout=5,
        retry_on_timeout=True,
    )
    # Verify connectivity
    try:
        await _pool.ping()
        logger.info("Redis connection pool initialized")
    except Exception as e:
        logger.error("Redis ping failed on init: %s", e)
        # Keep pool alive -- operations will degrade gracefully
    return _pool


async def close_redis_pool() -> None:
    """Close the Redis connection pool. Called once at shutdown."""
    global _pool
    if _pool is not None:
        await _pool.aclose()
        _pool = None
        logger.info("Redis connection pool closed")


def get_redis() -> aioredis.Redis:
    """Return the module-level Redis client.

    Raises RuntimeError if the pool has not been initialized.
    """
    if _pool is None:
        raise RuntimeError("Redis pool not initialized -- call init_redis_pool() first")
    return _pool


class RedisUnavailableError(Exception):
    """Raised when a Redis operation fails due to connectivity issues."""


async def safe_redis_call(coro: Any) -> Any:
    """Execute a Redis coroutine with error handling.

    Catches redis exceptions and raises RedisUnavailableError instead,
    so callers can degrade gracefully without importing redis exceptions.
    """
    try:
        return await coro
    except (aioredis.ConnectionError, aioredis.TimeoutError, aioredis.RedisError) as e:
        logger.warning("Redis operation failed: %s", e)
        raise RedisUnavailableError(str(e)) from e
