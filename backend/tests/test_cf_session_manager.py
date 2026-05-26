"""Tests for the CF session manager service.

Covers:
  1. CFSessionManager lifecycle (start/stop)
  2. Browser singleton management (_ensure_browser, _close_browser)
  3. Idle timeout (60 min auto-shutdown)
  4. Cookie registration (register/unregister/get_cookies)
  5. Cookie injection into browser context (_cookies_to_inject)
  6. Cookie extraction from browser context (_extract_cookies)
  7. Session validation (check_session / _validate_cookies)
  8. Background refresh loop (20 min interval)
  9. Refresh and expired callbacks
  10. create_context with cookie injection
  11. Module-level singleton (cf_session_manager)
"""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

from app.services import cf_session_manager as mgr_module
from app.services.cf_session_manager import (
    COOKIE_MAPPING,
    MAX_IDLE,
    REFRESH_INTERVAL,
    CFSessionManager,
    _cookies_to_inject,
    _extract_cookies,
    cf_session_manager,
)

# ---------------------------------------------------------------------------
# Helper: build mock Playwright objects
# ---------------------------------------------------------------------------


def _make_mock_page(
    *,
    logged_in: bool = True,
    cookies: list[dict] | None = None,
    nav_ok: bool = True,
):
    """Build a mock Playwright page."""
    page = AsyncMock()

    if not nav_ok:
        page.goto.side_effect = Exception("Navigation failed")
    else:
        page.goto = AsyncMock()

    # evaluate: first call checks logged-in, later calls return None
    eval_call_index = [0]

    def _evaluate_side_effect(script, *args, **kwargs):
        eval_call_index[0] += 1
        # Check if it is the logged-in check (contains "profile/")
        if isinstance(script, str) and "profile/" in script:
            return logged_in
        return None

    page.evaluate.side_effect = _evaluate_side_effect
    page.wait_for_timeout = AsyncMock()
    page.close = AsyncMock()

    # cookies returned by the context
    if cookies is None:
        cookies = [
            {"name": "JSESSIONID", "value": "abc123", "domain": "codeforces.com"},
            {"name": "cf_clearance", "value": "clear456", "domain": ".codeforces.com"},
        ]

    return page


def _make_mock_context(page=None, cookies=None):
    """Build a mock BrowserContext."""
    if page is None:
        page = _make_mock_page()
    ctx = AsyncMock()
    ctx.new_page = AsyncMock(return_value=page)
    ctx.close = AsyncMock()
    ctx.add_cookies = AsyncMock()

    if cookies is None:
        cookies = [
            {"name": "JSESSIONID", "value": "abc123", "domain": "codeforces.com"},
            {"name": "cf_clearance", "value": "clear456", "domain": ".codeforces.com"},
        ]
    ctx.cookies = AsyncMock(return_value=cookies)

    return ctx


def _make_mock_browser(context=None):
    """Build a mock Browser."""
    if context is None:
        context = _make_mock_context()
    browser = MagicMock()
    browser.new_context = AsyncMock(return_value=context)
    browser.close = AsyncMock()
    browser.is_connected.return_value = True
    return browser


def _make_mock_playwright(browser=None):
    """Build a mock Playwright instance."""
    if browser is None:
        browser = _make_mock_browser()
    pw = MagicMock()
    pw.chromium.launch = AsyncMock(return_value=browser)
    pw.stop = AsyncMock()

    class _PlaywrightMock:
        pass

    pw_obj = MagicMock()
    pw_obj.chromium = pw.chromium
    pw_obj.stop = pw.stop

    # async_playwright().start() returns the pw object
    mock_pw_start = AsyncMock(return_value=pw_obj)

    return browser, pw_obj, mock_pw_start


# ---------------------------------------------------------------------------
# 1. Cookie helper tests
# ---------------------------------------------------------------------------


class TestCookiesToInject:
    def test_filters_known_cookies(self):
        """Only cookies in COOKIE_MAPPING should be included."""
        cookies = {
            "JSESSIONID": "val1",
            "cf_clearance": "val2",
            "unknown_cookie": "val3",
        }
        result = _cookies_to_inject(cookies)
        names = {c["name"] for c in result}
        assert "JSESSIONID" in names
        assert "cf_clearance" in names
        assert "unknown_cookie" not in names

    def test_sets_domain_from_mapping(self):
        """Domain should come from COOKIE_MAPPING."""
        cookies = {"cf_clearance": "val"}
        result = _cookies_to_inject(cookies)
        assert len(result) == 1
        assert result[0]["domain"] == ".codeforces.com"

    def test_empty_cookies_returns_empty(self):
        """Empty dict returns empty list."""
        assert _cookies_to_inject({}) == []

    def test_missing_optional_cookies_skipped(self):
        """Cookies not in the input dict should not appear."""
        cookies = {"JSESSIONID": "val"}
        result = _cookies_to_inject(cookies)
        assert len(result) == 1
        assert result[0]["name"] == "JSESSIONID"

    def test_path_is_root(self):
        """All injected cookies should have path '/'."""
        cookies = {"JSESSIONID": "val"}
        result = _cookies_to_inject(cookies)
        assert result[0]["path"] == "/"

    def test_none_value_cookies_skipped(self):
        """Cookies with None value should not be included."""
        cookies = {"JSESSIONID": None, "cf_clearance": "val"}
        result = _cookies_to_inject(cookies)
        assert len(result) == 1
        assert result[0]["name"] == "cf_clearance"


class TestExtractCookies:
    async def test_extracts_codeforces_cookies(self):
        """Should extract cookies whose domain contains 'codeforces'."""
        ctx = _make_mock_context(
            cookies=[
                {"name": "JSESSIONID", "value": "j1", "domain": "codeforces.com"},
                {"name": "other", "value": "o1", "domain": "example.com"},
                {"name": "cf_clearance", "value": "c1", "domain": ".codeforces.com"},
            ]
        )
        result = await _extract_cookies(ctx)
        assert result == {"JSESSIONID": "j1", "cf_clearance": "c1"}

    async def test_empty_cookies(self):
        """Should return empty dict for no cookies."""
        ctx = _make_mock_context(cookies=[])
        result = await _extract_cookies(ctx)
        assert result == {}


# ---------------------------------------------------------------------------
# 2. Lifecycle tests
# ---------------------------------------------------------------------------


class TestLifecycle:
    async def test_start_creates_refresh_task(self):
        """start() should create a background refresh task."""
        mgr = CFSessionManager()
        await mgr.start()
        assert mgr._refresh_task is not None
        assert not mgr._refresh_task.done()
        await mgr.stop()

    async def test_stop_cancels_refresh_task(self):
        """stop() should cancel the refresh task."""
        mgr = CFSessionManager()
        await mgr.start()
        task = mgr._refresh_task
        await mgr.stop()
        assert mgr._refresh_task is None
        assert task.cancelled() or task.done()

    async def test_stop_closes_browser(self):
        """stop() should close the browser if running."""
        mgr = CFSessionManager()
        mock_browser = _make_mock_browser()
        mgr._browser = mock_browser
        mgr._pw = MagicMock()
        mgr._pw.stop = AsyncMock()

        await mgr.stop()

        mock_browser.close.assert_awaited()
        assert mgr._browser is None
        assert mgr._pw is None

    async def test_start_stop_idempotent(self):
        """Calling start/stop multiple times should be safe."""
        mgr = CFSessionManager()
        await mgr.start()
        await mgr.start()  # second call should be safe
        await mgr.stop()
        await mgr.stop()  # second call should be safe
        assert mgr._refresh_task is None


# ---------------------------------------------------------------------------
# 3. Browser management tests
# ---------------------------------------------------------------------------


class TestBrowserManagement:
    async def test_ensure_browser_launches_on_first_call(self):
        """_ensure_browser should launch Chromium lazily."""
        mgr = CFSessionManager()
        mock_browser, mock_pw, _ = _make_mock_playwright()

        with patch.object(mgr_module, "async_playwright") as mock_ap:
            mock_ap.return_value.start = AsyncMock(return_value=mock_pw)
            browser = await mgr._ensure_browser()

        assert browser is mock_browser
        assert mgr._browser is mock_browser
        assert mgr._last_used > 0
        # Cleanup
        mgr._browser = None
        mgr._pw = None

    async def test_ensure_browser_reuses_existing(self):
        """_ensure_browser should return existing connected browser."""
        mgr = CFSessionManager()
        mock_browser = _make_mock_browser()
        mgr._browser = mock_browser
        mgr._pw = MagicMock()

        browser = await mgr._ensure_browser()
        assert browser is mock_browser
        # Should NOT launch a new one
        mock_browser.new_context.assert_not_called()
        # Cleanup
        mgr._browser = None
        mgr._pw = None

    async def test_ensure_browser_relanches_disconnected(self):
        """_ensure_browser should relaunch if browser is disconnected."""
        mgr = CFSessionManager()
        disconnected_browser = MagicMock()
        disconnected_browser.is_connected.return_value = False
        disconnected_browser.close = AsyncMock()
        mgr._browser = disconnected_browser
        mgr._pw = MagicMock()
        mgr._pw.stop = AsyncMock()

        mock_browser, mock_pw, _ = _make_mock_playwright()

        with patch.object(mgr_module, "async_playwright") as mock_ap:
            mock_ap.return_value.start = AsyncMock(return_value=mock_pw)
            browser = await mgr._ensure_browser()

        assert browser is mock_browser
        # Cleanup
        mgr._browser = None
        mgr._pw = None

    async def test_browser_launches_headless_false(self):
        """Browser should be launched with headless=False (per FR-33.6)."""
        mgr = CFSessionManager()
        mock_browser, mock_pw, _ = _make_mock_playwright()

        with patch.object(mgr_module, "async_playwright") as mock_ap:
            mock_ap.return_value.start = AsyncMock(return_value=mock_pw)
            await mgr._ensure_browser()

        mock_pw.chromium.launch.assert_called_once()
        call_kwargs = mock_pw.chromium.launch.call_args
        assert call_kwargs.kwargs.get("headless") is False
        # Cleanup
        mgr._browser = None
        mgr._pw = None


# ---------------------------------------------------------------------------
# 4. Idle timeout tests
# ---------------------------------------------------------------------------


class TestIdleTimeout:
    async def test_idle_browser_is_closed(self):
        """Browser idle > MAX_IDLE should be closed."""
        mgr = CFSessionManager()
        mock_browser = _make_mock_browser()
        mgr._browser = mock_browser
        mgr._pw = MagicMock()
        mgr._pw.stop = AsyncMock()
        # Set last_used to be older than MAX_IDLE
        mgr._last_used = time.monotonic() - MAX_IDLE - 1

        await mgr._check_idle()

        mock_browser.close.assert_awaited()
        assert mgr._browser is None

    async def test_active_browser_not_closed(self):
        """Browser used recently should NOT be closed."""
        mgr = CFSessionManager()
        mock_browser = _make_mock_browser()
        mgr._browser = mock_browser
        mgr._pw = MagicMock()
        mgr._last_used = time.monotonic()

        await mgr._check_idle()

        mock_browser.close.assert_not_awaited()
        assert mgr._browser is mock_browser
        # Cleanup
        mgr._browser = None
        mgr._pw = None

    async def test_no_browser_is_noop(self):
        """_check_idle with no browser should be safe."""
        mgr = CFSessionManager()
        await mgr._check_idle()
        assert mgr._browser is None


# ---------------------------------------------------------------------------
# 5. Cookie registration tests
# ---------------------------------------------------------------------------


class TestCookieRegistration:
    async def test_register_stores_cookies(self):
        """register() should store cookies in memory."""
        mgr = CFSessionManager()
        mock_ctx = _make_mock_context()

        with patch.object(mgr, "_validate_cookies", new_callable=AsyncMock) as mock_validate:
            mock_validate.return_value = (True, {})
            with patch.object(mgr, "create_context", new_callable=AsyncMock, return_value=mock_ctx):
                result = await mgr.register("tourist", {"JSESSIONID": "abc"})

        assert result["valid"] is True
        assert mgr._cookies["tourist"]["JSESSIONID"] == "abc"
        # Cleanup
        mgr._cookies.clear()

    async def test_register_updates_fresh_cookies(self):
        """register() should update stored cookies with fresh ones."""
        mgr = CFSessionManager()

        with patch.object(mgr, "_validate_cookies", new_callable=AsyncMock) as mock_validate:
            mock_validate.return_value = (True, {"cf_clearance": "new_val"})
            with patch.object(mgr, "create_context", new_callable=AsyncMock):
                result = await mgr.register("tourist", {"JSESSIONID": "abc"})

        assert result["valid"] is True
        assert mgr._cookies["tourist"]["cf_clearance"] == "new_val"
        # Cleanup
        mgr._cookies.clear()

    async def test_register_invalid_cookies(self):
        """register() should return valid=False for invalid cookies."""
        mgr = CFSessionManager()

        with patch.object(mgr, "_validate_cookies", new_callable=AsyncMock) as mock_validate:
            mock_validate.return_value = (False, {})
            with patch.object(mgr, "create_context", new_callable=AsyncMock):
                result = await mgr.register("tourist", {"JSESSIONID": "expired"})

        assert result["valid"] is False
        # Cleanup
        mgr._cookies.clear()

    async def test_unregister_removes_cookies(self):
        """unregister() should remove cookies for a handle."""
        mgr = CFSessionManager()
        mgr._cookies["tourist"] = {"JSESSIONID": "abc"}

        await mgr.unregister("tourist")
        assert "tourist" not in mgr._cookies

    async def test_unregister_nonexistent_is_noop(self):
        """unregister() for nonexistent handle should be safe."""
        mgr = CFSessionManager()
        await mgr.unregister("nonexistent")  # Should not raise

    def test_get_cookies_returns_stored(self):
        """get_cookies() should return stored cookies."""
        mgr = CFSessionManager()
        mgr._cookies["tourist"] = {"JSESSIONID": "abc"}
        assert mgr.get_cookies("tourist") == {"JSESSIONID": "abc"}

    def test_get_cookies_returns_none_for_unknown(self):
        """get_cookies() should return None for unknown handle."""
        mgr = CFSessionManager()
        assert mgr.get_cookies("unknown") is None

    def test_registered_handles_property(self):
        """registered_handles should list all registered handles."""
        mgr = CFSessionManager()
        mgr._cookies = {"tourist": {}, "petr": {}}
        assert set(mgr.registered_handles) == {"tourist", "petr"}


# ---------------------------------------------------------------------------
# 6. Context creation tests
# ---------------------------------------------------------------------------


class TestCreateContext:
    async def test_creates_context_with_cookies(self):
        """create_context() should create a context and inject cookies."""
        mgr = CFSessionManager()
        mock_ctx = _make_mock_context()
        mock_browser = _make_mock_browser(mock_ctx)

        with patch.object(mgr, "_ensure_browser", new_callable=AsyncMock, return_value=mock_browser):
            ctx = await mgr.create_context("tourist", {"JSESSIONID": "abc"})

        assert ctx is mock_ctx
        mock_ctx.add_cookies.assert_awaited_once()
        # Cleanup
        mgr._browser = None
        mgr._pw = None

    async def test_creates_context_with_empty_cookies(self):
        """create_context() with empty cookies should not call add_cookies."""
        mgr = CFSessionManager()
        mock_ctx = _make_mock_context()
        mock_browser = _make_mock_browser(mock_ctx)

        with patch.object(mgr, "_ensure_browser", new_callable=AsyncMock, return_value=mock_browser):
            ctx = await mgr.create_context("tourist", {})

        assert ctx is mock_ctx
        mock_ctx.add_cookies.assert_not_awaited()
        # Cleanup
        mgr._browser = None
        mgr._pw = None


# ---------------------------------------------------------------------------
# 7. Session validation tests
# ---------------------------------------------------------------------------


class TestSessionValidation:
    async def test_check_session_valid(self):
        """check_session() should return (True, fresh_cookies) for valid session."""
        mgr = CFSessionManager()
        mock_ctx = _make_mock_context()
        mock_page = _make_mock_page(logged_in=True)
        mock_ctx.new_page = AsyncMock(return_value=mock_page)

        with patch.object(mgr, "create_context", new_callable=AsyncMock, return_value=mock_ctx):
            is_valid, fresh = await mgr.check_session("tourist", {"JSESSIONID": "abc"})

        assert is_valid is True
        assert "JSESSIONID" in fresh

    async def test_check_session_invalid(self):
        """check_session() should return (False, {}) for invalid session."""
        mgr = CFSessionManager()
        mock_ctx = _make_mock_context()
        mock_page = _make_mock_page(logged_in=False)
        mock_ctx.new_page = AsyncMock(return_value=mock_page)

        with patch.object(mgr, "create_context", new_callable=AsyncMock, return_value=mock_ctx):
            is_valid, fresh = await mgr.check_session("tourist", {"JSESSIONID": "expired"})

        assert is_valid is False
        assert fresh == {}

    async def test_check_session_navigation_error(self):
        """check_session() should return (False, {}) on navigation error."""
        mgr = CFSessionManager()
        mock_ctx = _make_mock_context()
        mock_page = _make_mock_page(nav_ok=False)
        mock_ctx.new_page = AsyncMock(return_value=mock_page)

        with patch.object(mgr, "create_context", new_callable=AsyncMock, return_value=mock_ctx):
            is_valid, fresh = await mgr.check_session("tourist", {"JSESSIONID": "abc"})

        assert is_valid is False

    async def test_check_session_closes_context(self):
        """check_session() should close the context after validation."""
        mgr = CFSessionManager()
        mock_ctx = _make_mock_context()
        mock_page = _make_mock_page(logged_in=True)
        mock_ctx.new_page = AsyncMock(return_value=mock_page)

        with patch.object(mgr, "create_context", new_callable=AsyncMock, return_value=mock_ctx):
            await mgr.check_session("tourist", {"JSESSIONID": "abc"})

        mock_ctx.close.assert_awaited()


# ---------------------------------------------------------------------------
# 8. Background refresh loop tests
# ---------------------------------------------------------------------------


class TestRefreshLoop:
    async def test_refresh_loop_validates_cookies(self):
        """Refresh loop should validate cookies for all registered handles."""
        mgr = CFSessionManager()
        mgr._cookies["tourist"] = {"JSESSIONID": "abc"}

        call_count = 0

        async def _mock_validate(handle, cookies):
            nonlocal call_count
            call_count += 1
            return (True, {})

        with (
            patch.object(mgr, "_validate_cookies", side_effect=_mock_validate),
            patch.object(mgr, "_check_idle", new_callable=AsyncMock),
            patch.object(mgr_module, "REFRESH_INTERVAL", 0.1),
        ):
            await mgr.start()
            await asyncio.sleep(0.3)
            await mgr.stop()

        assert call_count >= 1

    async def test_refresh_loop_calls_refresh_callback(self):
        """Refresh loop should call _on_refresh for valid cookies."""
        mgr = CFSessionManager()
        mgr._cookies["tourist"] = {"JSESSIONID": "abc"}

        refresh_called = asyncio.Event()

        async def _on_refresh(handle, fresh):
            refresh_called.set()

        mgr._on_refresh = _on_refresh

        with (
            patch.object(
                mgr,
                "_validate_cookies",
                new_callable=AsyncMock,
                return_value=(True, {"cf_clearance": "new"}),
            ),
            patch.object(mgr, "_check_idle", new_callable=AsyncMock),
            patch.object(mgr_module, "REFRESH_INTERVAL", 0.1),
        ):
            await mgr.start()
            await asyncio.wait_for(refresh_called.wait(), timeout=1.0)
            await mgr.stop()

    async def test_refresh_loop_calls_expired_callback(self):
        """Refresh loop should call _on_expired for invalid cookies."""
        mgr = CFSessionManager()
        mgr._cookies["tourist"] = {"JSESSIONID": "abc"}

        expired_called = asyncio.Event()

        async def _on_expired(handle):
            expired_called.set()

        mgr._on_expired = _on_expired

        with (
            patch.object(mgr, "_validate_cookies", new_callable=AsyncMock, return_value=(False, {})),
            patch.object(mgr, "_check_idle", new_callable=AsyncMock),
            patch.object(mgr_module, "REFRESH_INTERVAL", 0.1),
        ):
            await mgr.start()
            await asyncio.wait_for(expired_called.wait(), timeout=1.0)
            await mgr.stop()

    async def test_refresh_loop_callback_error_does_not_crash(self):
        """Errors in callbacks should be caught and not crash the loop."""
        mgr = CFSessionManager()
        mgr._cookies["tourist"] = {"JSESSIONID": "abc"}

        call_count = 0

        async def _bad_refresh(handle, fresh):
            nonlocal call_count
            call_count += 1
            raise RuntimeError("callback error")

        mgr._on_refresh = _bad_refresh

        with (
            patch.object(
                mgr,
                "_validate_cookies",
                new_callable=AsyncMock,
                return_value=(True, {"cf_clearance": "new"}),
            ),
            patch.object(mgr, "_check_idle", new_callable=AsyncMock),
            patch.object(mgr_module, "REFRESH_INTERVAL", 0.1),
        ):
            await mgr.start()
            await asyncio.sleep(0.3)
            await mgr.stop()

        # Loop should have survived the callback error
        assert call_count >= 1

    async def test_refresh_loop_skips_no_handles(self):
        """Refresh loop should do nothing when no handles are registered."""
        mgr = CFSessionManager()

        with (
            patch.object(mgr, "_validate_cookies", new_callable=AsyncMock) as mock_validate,
            patch.object(mgr, "_check_idle", new_callable=AsyncMock),
            patch.object(mgr_module, "REFRESH_INTERVAL", 0.1),
        ):
            await mgr.start()
            await asyncio.sleep(0.3)
            await mgr.stop()

        mock_validate.assert_not_called()


# ---------------------------------------------------------------------------
# 9. Module-level singleton test
# ---------------------------------------------------------------------------


class TestModuleSingleton:
    def test_cf_session_manager_exists(self):
        """Module-level cf_session_manager should be a CFSessionManager instance."""
        assert isinstance(cf_session_manager, CFSessionManager)


# ---------------------------------------------------------------------------
# 10. Constants validation
# ---------------------------------------------------------------------------


class TestConstants:
    def test_refresh_interval(self):
        """REFRESH_INTERVAL should be 20 minutes."""
        assert REFRESH_INTERVAL == 20 * 60

    def test_max_idle(self):
        """MAX_IDLE should be 60 minutes."""
        assert MAX_IDLE == 60 * 60

    def test_cookie_mapping_has_required_entries(self):
        """COOKIE_MAPPING should contain key CF cookies."""
        names = {name for name, _ in COOKIE_MAPPING}
        assert "JSESSIONID" in names
        assert "cf_clearance" in names

    def test_cookie_mapping_domains(self):
        """All domains should contain 'codeforces'."""
        for name, domain in COOKIE_MAPPING:
            assert "codeforces" in domain


# ---------------------------------------------------------------------------
# 11. set_refresh_callback / set_expired_callback tests
# ---------------------------------------------------------------------------


class TestCallbackRegistration:
    def test_set_refresh_callback(self):
        """set_refresh_callback should store the callback."""
        mgr = CFSessionManager()
        cb = AsyncMock()
        mgr.set_refresh_callback(cb)
        assert mgr._on_refresh is cb

    def test_set_expired_callback(self):
        """set_expired_callback should store the callback."""
        mgr = CFSessionManager()
        cb = AsyncMock()
        mgr.set_expired_callback(cb)
        assert mgr._on_expired is cb
