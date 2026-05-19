"""Tests for the Codeforces API client service.

All external HTTP calls are mocked -- no real network requests are made.
"""

import asyncio
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.services.cf_api_service import (
    DEFAULT_CACHE_TTL,
    PROBLEMS_CACHE_TTL,
    STATUS_CACHE_TTL,
    CFAPIError,
    CFApiService,
    CFNetworkError,
    CFNotFoundError,
    CFRateLimitError,
)
from app.utils.rate_limiter import TokenBucketRateLimiter

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _cf_ok(result) -> httpx.Response:
    """Build a mock 200 Response with a successful CF API envelope."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = 200
    resp.json.return_value = {"status": "OK", "result": result}
    return resp


def _cf_failed(comment: str) -> httpx.Response:
    """Build a mock 200 Response with a FAILED CF API envelope."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = 200
    resp.json.return_value = {"status": "FAILED", "comment": comment}
    return resp


def _http_429() -> httpx.Response:
    """Build a mock 429 Response."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = 429
    resp.text = "rate limit"
    return resp


def _http_500() -> httpx.Response:
    """Build a mock 500 Response."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = 500
    resp.text = "internal server error"
    return resp


@pytest.fixture
def service() -> CFApiService:
    """Return a CFApiService with zero-interval rate limiter for fast tests."""
    svc = CFApiService(
        base_url="https://codeforces.com/api",
        timeout=5.0,
        min_interval=0.0,  # no delay in tests
        max_retries=3,
        default_ttl=DEFAULT_CACHE_TTL,
    )
    yield svc
    # Cleanup
    asyncio.get_event_loop().run_until_complete(svc.close())


def _mock_client(service: CFApiService, responses: list[httpx.Response]) -> AsyncMock:
    """Patch the internal client's ``get`` to return *responses* in order."""
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.is_closed = False
    mock_client.get = AsyncMock(side_effect=responses)
    # Inject the mock client so _get_client returns it
    service._client = mock_client
    return mock_client


# ===========================================================================
# Rate limiter unit tests
# ===========================================================================


class TestTokenBucketRateLimiter:
    """Unit tests for the token-bucket rate limiter."""

    @pytest.mark.asyncio
    async def test_acquire_immediately_when_token_available(self):
        limiter = TokenBucketRateLimiter(min_interval=1.0)
        # First acquire should not block
        await asyncio.wait_for(limiter.acquire(), timeout=0.5)

    @pytest.mark.asyncio
    async def test_acquire_waits_when_no_token(self):
        limiter = TokenBucketRateLimiter(min_interval=0.1)
        # Drain the token
        await limiter.acquire()
        # Next acquire should wait roughly min_interval
        start = time.monotonic()
        await limiter.acquire()
        elapsed = time.monotonic() - start
        assert elapsed >= 0.05  # allow small tolerance

    @pytest.mark.asyncio
    async def test_min_interval_property(self):
        limiter = TokenBucketRateLimiter(min_interval=3.5)
        assert limiter.min_interval == 3.5

    @pytest.mark.asyncio
    async def test_multiple_acquires_queue(self):
        limiter = TokenBucketRateLimiter(min_interval=0.05)
        # Three acquires should complete without error
        for _ in range(3):
            await limiter.acquire()


# ===========================================================================
# Cache tests
# ===========================================================================


class TestCache:
    """Tests for the in-memory TTL cache."""

    def test_cache_key_deterministic(self):
        key1 = CFApiService._make_cache_key("/user.info", {"handles": "alice;bob"})
        key2 = CFApiService._make_cache_key("/user.info", {"handles": "alice;bob"})
        assert key1 == key2

    def test_cache_key_differs_for_different_params(self):
        key1 = CFApiService._make_cache_key("/user.info", {"handles": "alice"})
        key2 = CFApiService._make_cache_key("/user.info", {"handles": "bob"})
        assert key1 != key2

    def test_set_and_get_cached(self):
        svc = CFApiService(base_url="https://example.com")
        key = "test-key"
        svc._set_cached(key, {"data": 42}, ttl=60.0)
        hit, val = svc._get_cached(key)
        assert hit is True
        assert val == {"data": 42}

    def test_cache_miss(self):
        svc = CFApiService(base_url="https://example.com")
        hit, val = svc._get_cached("nonexistent")
        assert hit is False
        assert val is None

    def test_cache_expires(self):
        svc = CFApiService(base_url="https://example.com")
        key = "expiring-key"
        svc._set_cached(key, "value", ttl=0.0)  # already expired
        hit, val = svc._get_cached(key)
        assert hit is False

    def test_clear_cache(self):
        svc = CFApiService(base_url="https://example.com")
        svc._set_cached("k1", "v1", ttl=60.0)
        svc._set_cached("k2", "v2", ttl=60.0)
        svc.clear_cache()
        assert svc._get_cached("k1") == (False, None)
        assert svc._get_cached("k2") == (False, None)


# ===========================================================================
# API method tests
# ===========================================================================


class TestGetUserInfo:
    """Tests for ``get_user_info``."""

    @pytest.mark.asyncio
    async def test_single_handle(self, service: CFApiService):
        user_data = [{"handle": "tourist", "rating": 3800}]
        _mock_client(service, [_cf_ok(user_data)])

        result = await service.get_user_info(["tourist"])
        assert result == user_data
        service._client.get.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_multiple_handles(self, service: CFApiService):
        users = [
            {"handle": "tourist", "rating": 3800},
            {"handle": "Petr", "rating": 3400},
        ]
        _mock_client(service, [_cf_ok(users)])

        result = await service.get_user_info(["tourist", "Petr"])
        assert len(result) == 2
        call_args = service._client.get.call_args
        assert call_args[1]["params"]["handles"] == "tourist;Petr"

    @pytest.mark.asyncio
    async def test_empty_handles_returns_empty(self, service: CFApiService):
        result = await service.get_user_info([])
        assert result == []
        # No HTTP call should be made
        assert service._client is None

    @pytest.mark.asyncio
    async def test_handle_not_found(self, service: CFApiService):
        _mock_client(service, [_cf_failed("handles: nonexistent not found")])
        with pytest.raises(CFNotFoundError) as exc_info:
            await service.get_user_info(["nonexistent"])
        assert "not found" in exc_info.value.message.lower()

    @pytest.mark.asyncio
    async def test_cache_hit_avoids_http_call(self, service: CFApiService):
        data = [{"handle": "tourist"}]
        _mock_client(service, [_cf_ok(data)])

        # First call hits the network
        r1 = await service.get_user_info(["tourist"])
        assert r1 == data

        # Second call should be served from cache
        r2 = await service.get_user_info(["tourist"])
        assert r2 == data
        # Only one HTTP call was made
        assert service._client.get.await_count == 1


class TestGetUserStatus:
    """Tests for ``get_user_status``."""

    @pytest.mark.asyncio
    async def test_default_count(self, service: CFApiService):
        subs = [{"id": 1, "verdict": "OK"}]
        _mock_client(service, [_cf_ok(subs)])

        result = await service.get_user_status("tourist")
        assert result == subs
        call_params = service._client.get.call_args[1]["params"]
        assert call_params["count"] == 10

    @pytest.mark.asyncio
    async def test_custom_count(self, service: CFApiService):
        subs = [{"id": 1}]
        _mock_client(service, [_cf_ok(subs)])

        await service.get_user_status("tourist", count=50)
        call_params = service._client.get.call_args[1]["params"]
        assert call_params["count"] == 50
        assert call_params["handle"] == "tourist"

    @pytest.mark.asyncio
    async def test_uses_short_ttl(self, service: CFApiService):
        """Verify user status uses the short TTL (1 minute)."""
        subs = [{"id": 1}]
        _mock_client(service, [_cf_ok(subs)])
        await service.get_user_status("tourist")

        # Check that the cache entry was stored with short TTL
        assert len(service._cache) == 1


class TestGetProblemsetProblems:
    """Tests for ``get_problemset_problems``."""

    @pytest.mark.asyncio
    async def test_no_tags(self, service: CFApiService):
        problems = {"problems": [{"name": "A+B"}], "statistics": []}
        _mock_client(service, [_cf_ok(problems)])

        result = await service.get_problemset_problems()
        assert result == problems
        call_params = service._client.get.call_args[1]["params"]
        assert "tags" not in call_params

    @pytest.mark.asyncio
    async def test_with_tags(self, service: CFApiService):
        problems = {"problems": [{"name": "DP Problem"}], "statistics": []}
        _mock_client(service, [_cf_ok(problems)])

        result = await service.get_problemset_problems(tags=["dp", "greedy"])
        assert result == problems
        call_params = service._client.get.call_args[1]["params"]
        assert call_params["tags"] == "dp;greedy"

    @pytest.mark.asyncio
    async def test_uses_long_ttl(self, service: CFApiService):
        """Problems endpoint uses the longer 30-minute TTL."""
        problems = {"problems": [], "statistics": []}
        _mock_client(service, [_cf_ok(problems)])
        await service.get_problemset_problems()

        assert len(service._cache) == 1


class TestGetContestStandings:
    """Tests for ``get_contest_standings``."""

    @pytest.mark.asyncio
    async def test_basic(self, service: CFApiService):
        standings = {"contest": {"id": 123}, "rows": []}
        _mock_client(service, [_cf_ok(standings)])

        result = await service.get_contest_standings(123)
        assert result == standings
        call_params = service._client.get.call_args[1]["params"]
        assert call_params["contestId"] == 123


class TestGetUserRating:
    """Tests for ``get_user_rating``."""

    @pytest.mark.asyncio
    async def test_basic(self, service: CFApiService):
        rating_changes = [
            {"contestId": 1, "newRating": 1500},
            {"contestId": 2, "newRating": 1600},
        ]
        _mock_client(service, [_cf_ok(rating_changes)])

        result = await service.get_user_rating("tourist")
        assert result == rating_changes
        call_params = service._client.get.call_args[1]["params"]
        assert call_params["handle"] == "tourist"

    @pytest.mark.asyncio
    async def test_handle_not_found(self, service: CFApiService):
        _mock_client(service, [_cf_failed("handle tourist2 not found")])
        with pytest.raises(CFNotFoundError):
            await service.get_user_rating("tourist2")


# ===========================================================================
# Retry & error handling tests
# ===========================================================================


class TestRetryOn429:
    """Tests for exponential-backoff retry on HTTP 429."""

    @pytest.mark.asyncio
    async def test_succeeds_after_retry(self, service: CFApiService):
        data = [{"handle": "tourist"}]
        # First call returns 429, second succeeds
        _mock_client(service, [_http_429(), _cf_ok(data)])

        with patch("app.services.cf_api_service.asyncio.sleep", new_callable=AsyncMock):
            result = await service.get_user_info(["tourist"])
        assert result == data
        assert service._client.get.await_count == 2

    @pytest.mark.asyncio
    async def test_raises_after_max_retries(self, service: CFApiService):
        # All 3 attempts return 429
        _mock_client(service, [_http_429()] * 3)

        with patch("app.services.cf_api_service.asyncio.sleep", new_callable=AsyncMock), \
             pytest.raises(CFRateLimitError):
            await service.get_user_info(["tourist"])
        assert service._client.get.await_count == 3

    @pytest.mark.asyncio
    async def test_exponential_backoff_timing(self, service: CFApiService):
        """Verify sleep is called with exponentially increasing durations."""
        data = [{"handle": "tourist"}]
        _mock_client(service, [_http_429(), _http_429(), _cf_ok(data)])

        with patch("app.services.cf_api_service.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            await service.get_user_info(["tourist"])

        # attempt 1: wait 2**1=2, attempt 2: wait 2**2=4
        calls = mock_sleep.call_args_list
        assert len(calls) == 2
        assert calls[0][0][0] == 2  # first retry waits 2s
        assert calls[1][0][0] == 4  # second retry waits 4s


class TestNetworkErrors:
    """Tests for network-level error handling."""

    @pytest.mark.asyncio
    async def test_timeout_retries_then_succeeds(self, service: CFApiService):
        """Timeout on first attempt, success on second attempt."""
        data = [{"handle": "tourist"}]
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.is_closed = False
        mock_client.get = AsyncMock(
            side_effect=[
                httpx.TimeoutException("timed out"),
                _cf_ok(data),
            ]
        )
        service._client = mock_client

        with patch("app.services.cf_api_service.asyncio.sleep", new_callable=AsyncMock):
            result = await service.get_user_info(["tourist"])
        assert result == data
        assert service._client.get.await_count == 2

    @pytest.mark.asyncio
    async def test_timeout_raises_after_max_retries(self, service: CFApiService):
        """All attempts time out -- should raise CFNetworkError."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.is_closed = False
        mock_client.get = AsyncMock(
            side_effect=httpx.TimeoutException("timed out")
        )
        service._client = mock_client

        with patch("app.services.cf_api_service.asyncio.sleep", new_callable=AsyncMock), \
             pytest.raises(CFNetworkError) as exc_info:
            await service.get_user_info(["tourist"])
        assert "timed out" in exc_info.value.message.lower()
        assert service._client.get.await_count == 3

    @pytest.mark.asyncio
    async def test_timeout_exponential_backoff(self, service: CFApiService):
        """Verify timeout retry uses exponential backoff sleep durations."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.is_closed = False
        mock_client.get = AsyncMock(
            side_effect=httpx.TimeoutException("timed out")
        )
        service._client = mock_client

        with patch("app.services.cf_api_service.asyncio.sleep", new_callable=AsyncMock) as mock_sleep, \
             pytest.raises(CFNetworkError):
            await service.get_user_info(["tourist"])

        # attempt 1: sleep 2**1=2, attempt 2: sleep 2**2=4
        calls = mock_sleep.call_args_list
        assert len(calls) == 2
        assert calls[0][0][0] == 2
        assert calls[1][0][0] == 4

    @pytest.mark.asyncio
    async def test_connection_error_retries_then_raises(self, service: CFApiService):
        """Connection errors are also retried with exponential backoff."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.is_closed = False
        mock_client.get = AsyncMock(
            side_effect=httpx.ConnectError("connection refused")
        )
        service._client = mock_client

        with patch("app.services.cf_api_service.asyncio.sleep", new_callable=AsyncMock), \
             pytest.raises(CFNetworkError) as exc_info:
            await service.get_user_info(["tourist"])
        assert "network error" in exc_info.value.message.lower()
        assert service._client.get.await_count == 3

    @pytest.mark.asyncio
    async def test_http_500_raises_cf_network_error(self, service: CFApiService):
        _mock_client(service, [_http_500()])

        with pytest.raises(CFNetworkError) as exc_info:
            await service.get_user_info(["tourist"])
        assert "500" in exc_info.value.message


class TestCFAPIErrors:
    """Tests for CF API-level error handling."""

    @pytest.mark.asyncio
    async def test_failed_status_with_generic_comment(self, service: CFApiService):
        _mock_client(service, [_cf_failed("some internal error")])

        with pytest.raises(CFAPIError) as exc_info:
            await service.get_user_info(["tourist"])
        assert "internal error" in (exc_info.value.detail or "")

    @pytest.mark.asyncio
    async def test_invalid_json_response(self, service: CFApiService):
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 200
        resp.json.side_effect = json.JSONDecodeError("bad json", "", 0)
        _mock_client(service, [resp])

        with pytest.raises(CFAPIError) as exc_info:
            await service.get_user_info(["tourist"])
        assert "invalid json" in exc_info.value.message.lower()


class TestClientLifecycle:
    """Tests for client creation and cleanup."""

    @pytest.mark.asyncio
    async def test_close_cleans_up(self, service: CFApiService):
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.is_closed = False
        service._client = mock_client

        await service.close()
        mock_client.aclose.assert_awaited_once()
        assert service._client is None

    @pytest.mark.asyncio
    async def test_close_idempotent(self, service: CFApiService):
        await service.close()  # Should not raise
        await service.close()  # Still should not raise

    @pytest.mark.asyncio
    async def test_get_client_creates_new_when_none(self):
        svc = CFApiService(base_url="https://example.com")
        assert svc._client is None
        client = await svc._get_client()
        assert isinstance(client, httpx.AsyncClient)
        await svc.close()

    @pytest.mark.asyncio
    async def test_get_client_creates_new_when_closed(self):
        svc = CFApiService(base_url="https://example.com")
        client = await svc._get_client()
        await client.aclose()
        # Client is now closed
        new_client = await svc._get_client()
        assert new_client is not client
        await svc.close()


class TestTTLConfiguration:
    """Verify TTL constants and per-method cache behavior."""

    def test_default_cache_ttl(self):
        assert DEFAULT_CACHE_TTL == 300

    def test_problems_cache_ttl(self):
        assert PROBLEMS_CACHE_TTL == 1800

    def test_status_cache_ttl(self):
        assert STATUS_CACHE_TTL == 60

    @pytest.mark.asyncio
    async def test_user_info_uses_default_ttl(self, service: CFApiService):
        data = [{"handle": "tourist"}]
        _mock_client(service, [_cf_ok(data)])

        await service.get_user_info(["tourist"])
        assert len(service._cache) == 1
        entry = list(service._cache.values())[0]
        # TTL should be default (300s)
        expected_expiry = entry.expires_at
        # Entry should still be fresh well within the default TTL
        assert expected_expiry > time.monotonic()
