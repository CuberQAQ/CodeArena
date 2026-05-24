"""Codeforces API client with rate limiting, caching, and retry.

Wraps the public Codeforces API endpoints with:
- Token-bucket rate limiting (default 2 s between requests)
- In-memory TTL cache with per-method configurable TTLs
- Exponential-backoff retry on HTTP 429 (rate-limited) responses
- Structured error handling for network failures, CF errors, and missing handles
"""

import asyncio
import hashlib
import json
import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import settings
from app.utils.rate_limiter import TokenBucketRateLimiter

logger = logging.getLogger("code_arena.cf_api")

# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------


class CFAPIError(Exception):
    """Base exception for Codeforces API errors."""

    def __init__(self, message: str, detail: str | None = None) -> None:
        self.message = message
        self.detail = detail
        super().__init__(message)


class CFNetworkError(CFAPIError):
    """Network-level failure (timeout, connection error, etc.)."""


class CFNotFoundError(CFAPIError):
    """Requested resource (e.g. handle) does not exist."""


class CFRateLimitError(CFAPIError):
    """Rate-limited by CF even after retries."""


# ---------------------------------------------------------------------------
# Cache entry
# ---------------------------------------------------------------------------


@dataclass
class _CacheEntry:
    value: Any
    expires_at: float


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

# Default TTLs (seconds)
DEFAULT_CACHE_TTL = 300  # 5 minutes
PROBLEMS_CACHE_TTL = 1800  # 30 minutes
STATUS_CACHE_TTL = 60  # 1 minute


class CFApiService:
    """Async Codeforces API client.

    Parameters
    ----------
    base_url:
        CF API base URL.  Defaults to ``settings.CF_API_BASE_URL``.
    timeout:
        HTTP request timeout in seconds.
    min_interval:
        Minimum seconds between consecutive API requests.
    max_retries:
        Maximum retry attempts on 429 responses.
    default_ttl:
        Default cache TTL in seconds.
    """

    def __init__(
        self,
        base_url: str | None = None,
        timeout: float = 10.0,
        min_interval: float = 2.0,
        max_retries: int = 1,
        default_ttl: float = DEFAULT_CACHE_TTL,
    ) -> None:
        self._base_url = (base_url or settings.CF_API_BASE_URL).rstrip("/")
        self._timeout = timeout
        self._max_retries = max_retries
        self._default_ttl = default_ttl

        self._rate_limiter = TokenBucketRateLimiter(min_interval=min_interval)
        self._cache: dict[str, _CacheEntry] = {}
        self._client: httpx.AsyncClient | None = None

    # ------------------------------------------------------------------
    # Client lifecycle
    # ------------------------------------------------------------------

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=httpx.Timeout(self._timeout),
            )
        return self._client

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    # ------------------------------------------------------------------
    # Cache helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _make_cache_key(endpoint: str, params: dict[str, Any]) -> str:
        raw = f"{endpoint}:{json.dumps(params, sort_keys=True, default=str)}"
        return hashlib.sha256(raw.encode()).hexdigest()

    def _get_cached(self, key: str) -> tuple[bool, Any]:
        entry = self._cache.get(key)
        if entry is None:
            return False, None
        if time.monotonic() > entry.expires_at:
            del self._cache[key]
            return False, None
        return True, entry.value

    def _set_cached(self, key: str, value: Any, ttl: float) -> None:
        self._cache[key] = _CacheEntry(value=value, expires_at=time.monotonic() + ttl)

    def clear_cache(self) -> None:
        """Drop all cached entries."""
        self._cache.clear()

    # ------------------------------------------------------------------
    # Core request with retry
    # ------------------------------------------------------------------

    async def _request(
        self,
        endpoint: str,
        params: dict[str, Any] | None = None,
        *,
        ttl: float | None = None,
    ) -> Any:
        """Execute an API request with caching, rate limiting, and retry.

        Returns the parsed ``result`` field from the CF API JSON response.
        """
        params = params or {}
        effective_ttl = ttl if ttl is not None else self._default_ttl

        # 1. Check cache
        cache_key = self._make_cache_key(endpoint, params)
        hit, cached = self._get_cached(cache_key)
        if hit:
            logger.debug("Cache hit for %s", endpoint)
            return cached

        # 2. Rate limit
        await self._rate_limiter.acquire()

        # 3. Request with exponential-backoff retry on 429
        client = await self._get_client()
        last_exception: Exception | None = None

        for attempt in range(1, self._max_retries + 1):
            try:
                response = await client.get(endpoint, params=params)
            except httpx.TimeoutException as exc:
                last_exception = exc
                logger.warning(
                    "CF API timeout on %s (attempt %d/%d)",
                    endpoint,
                    attempt,
                    self._max_retries,
                )
                if attempt == self._max_retries:
                    raise CFNetworkError(
                        "Request to Codeforces API timed out",
                        detail=str(exc),
                    ) from exc
                await asyncio.sleep(2**attempt)
                continue
            except httpx.RequestError as exc:
                last_exception = exc
                logger.warning(
                    "CF API network error on %s (attempt %d/%d)",
                    endpoint,
                    attempt,
                    self._max_retries,
                )
                if attempt == self._max_retries:
                    raise CFNetworkError(
                        "Network error communicating with Codeforces API",
                        detail=str(exc),
                    ) from exc
                await asyncio.sleep(2**attempt)
                continue

            if response.status_code == 429:
                wait = 2**attempt  # 2, 4, 8 seconds
                logger.warning(
                    "CF API rate-limited on %s (attempt %d/%d), waiting %ds",
                    endpoint,
                    attempt,
                    self._max_retries,
                    wait,
                )
                if attempt == self._max_retries:
                    raise CFRateLimitError(
                        "Rate-limited by Codeforces API after maximum retries",
                        detail=f"endpoint={endpoint}, attempts={self._max_retries}",
                    )
                await asyncio.sleep(wait)
                continue

            # Non-2xx that is not 429
            if response.status_code != 200:
                raise CFNetworkError(
                    f"Unexpected HTTP {response.status_code} from Codeforces API",
                    detail=response.text[:500],
                )

            # Parse CF API JSON envelope
            try:
                data = response.json()
            except json.JSONDecodeError as exc:
                raise CFAPIError(
                    "Invalid JSON response from Codeforces API",
                    detail=str(exc),
                ) from exc

            status = data.get("status")
            if status == "FAILED":
                comment = data.get("comment", "")
                # Detect handle-not-found errors
                if "not found" in comment.lower() or "handles: " in comment.lower():
                    raise CFNotFoundError(
                        "Codeforces handle not found",
                        detail=comment,
                    )
                raise CFAPIError(
                    "Codeforces API returned an error",
                    detail=comment,
                )

            result = data.get("result")

            # 4. Store in cache
            self._set_cached(cache_key, result, effective_ttl)
            return result

        # Should not reach here, but just in case
        if last_exception:
            raise last_exception
        raise CFAPIError("Unexpected state in request retry loop")

    # ------------------------------------------------------------------
    # Public API methods
    # ------------------------------------------------------------------

    async def get_user_info(self, handles: list[str]) -> list[dict[str, Any]]:
        """Batch-fetch user information.

        CF API endpoint: ``/user.info`` with ``handles`` as semicolon-separated.
        """
        if not handles:
            return []
        params = {"handles": ";".join(handles)}
        result = await self._request("/user.info", params)
        return result

    async def get_user_status(
        self,
        handle: str,
        count: int = 10,
    ) -> list[dict[str, Any]]:
        """Fetch recent submissions for a user.

        CF API endpoint: ``/user.status`` with ``handle`` and ``count``.
        """
        params: dict[str, Any] = {"handle": handle, "count": count}
        result = await self._request(
            "/user.status",
            params,
            ttl=STATUS_CACHE_TTL,
        )
        return result

    async def get_problemset_problems(
        self,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """Fetch problems, optionally filtered by tags.

        CF API endpoint: ``/problemset.problems`` with optional ``tags`` param.
        """
        params: dict[str, Any] = {}
        if tags:
            params["tags"] = ";".join(tags)
        result = await self._request(
            "/problemset.problems",
            params,
            ttl=PROBLEMS_CACHE_TTL,
        )
        return result

    async def get_contest_standings(
        self,
        contest_id: int,
    ) -> dict[str, Any]:
        """Fetch contest standings.

        CF API endpoint: ``/contest.standings`` with ``contestId``.
        """
        params: dict[str, Any] = {"contestId": contest_id}
        result = await self._request("/contest.standings", params)
        return result

    async def get_user_rating(self, handle: str) -> list[dict[str, Any]]:
        """Fetch rating change history for a user.

        CF API endpoint: ``/user.rating`` with ``handle``.
        """
        params: dict[str, Any] = {"handle": handle}
        result = await self._request("/user.rating", params)
        return result

    async def get_contest_status(
        self,
        contest_id: int,
    ) -> list[dict[str, Any]]:
        """Fetch all submissions for a contest.

        CF API endpoint: ``/contest.status`` with ``contestId``.
        Returns the list of submission objects.
        """
        params: dict[str, Any] = {"contestId": contest_id}
        result = await self._request(
            "/contest.status",
            params,
            ttl=STATUS_CACHE_TTL,
        )
        return result

    async def get_contest_rating_changes(
        self,
        contest_id: int,
    ) -> list[dict[str, Any]]:
        """Fetch rating changes for a contest.

        CF API endpoint: ``/contest.ratingChanges`` with ``contestId``.
        Returns the list of rating change objects, each containing
        ``handle`` and ``oldRating`` among other fields.
        """
        params: dict[str, Any] = {"contestId": contest_id}
        result = await self._request(
            "/contest.ratingChanges",
            params,
            ttl=DEFAULT_CACHE_TTL,
        )
        return result
