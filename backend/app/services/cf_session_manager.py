"""CF session manager -- cookie-based browser session with auto-refresh.

Manages patchright Chromium browser instances for interacting with
Codeforces while bypassing Turnstile protection.  Key design decisions:

- **Browser singleton**: one Chromium process shared across all requests.
- **Per-request context**: each operation gets a fresh ``BrowserContext``
  with cookies injected, then closed after use.
- **Idle shutdown**: after 60 minutes of inactivity the browser is closed;
  it is re-launched on the next request.
- **Background refresh**: an asyncio task wakes every 20 minutes and
  re-validates cookies via a page visit (Turnstile may renew
  ``cf_clearance``).
- **No direct DB access**: cookies are passed in/out via parameters and
  callbacks so the manager stays decoupled from the persistence layer.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from patchright.async_api import Browser, BrowserContext, Playwright, async_playwright

logger = logging.getLogger("code_arena.cf_session_manager")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REFRESH_INTERVAL = 20 * 60  # 20 minutes between refresh sweeps
MAX_IDLE = 60 * 60  # 60 minutes idle -> close browser
CF_URL = "https://codeforces.com"

# Cookie name -> domain mapping used when injecting into a context.
COOKIE_MAPPING: list[tuple[str, str]] = [
    ("JSESSIONID", "codeforces.com"),
    ("39ce7", "codeforces.com"),
    ("cf_clearance", ".codeforces.com"),
    ("70a7c28f3de", ".codeforces.com"),  # pragma: allowlist secret
    ("evercookie_cache", ".codeforces.com"),
    ("evercookie_etag", ".codeforces.com"),
    ("evercookie_png", ".codeforces.com"),
    ("pow", "codeforces.com"),
]

# Callback type aliases for readability
CookieDict = dict[str, str]
CookieRefreshCallback = Callable[[str, CookieDict], Awaitable[None]]
CookieExpiredCallback = Callable[[str], Awaitable[None]]


# ---------------------------------------------------------------------------
# Cookie helpers
# ---------------------------------------------------------------------------


def _cookies_to_inject(cookies: CookieDict) -> list[dict[str, Any]]:
    """Convert a ``{name: value}`` dict to a Playwright-compatible cookie list.

    Only cookies listed in :data:`COOKIE_MAPPING` are included.
    """
    result: list[dict[str, Any]] = []
    for name, domain in COOKIE_MAPPING:
        value = cookies.get(name)
        if value:
            result.append(
                {
                    "name": name,
                    "value": value,
                    "domain": domain,
                    "path": "/",
                }
            )
    return result


async def _extract_cookies(ctx: BrowserContext) -> CookieDict:
    """Extract Codeforces cookies from a browser context."""
    result: CookieDict = {}
    for c in await ctx.cookies():
        if "codeforces" in c.get("domain", ""):
            result[c["name"]] = c["value"]
    return result


# ---------------------------------------------------------------------------
# CFSessionManager
# ---------------------------------------------------------------------------


class CFSessionManager:
    """Manages patchright browser sessions for Codeforces interactions.

    Usage::

        manager = CFSessionManager()
        await manager.start()

        # Register user cookies (caller reads from DB)
        await manager.register("tourist", {"JSESSIONID": "...", ...})

        # Create a short-lived context for a submit
        ctx = await manager.create_context("tourist", cookies)
        try:
            ...  # submit
        finally:
            await ctx.close()

        # Shutdown
        await manager.stop()
    """

    def __init__(self) -> None:
        self._pw: Playwright | None = None
        self._browser: Browser | None = None
        self._last_used: float = 0.0
        self._refresh_task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()

        # Registered handles -> cookie dicts (in-memory mirror, caller owns DB)
        self._cookies: dict[str, CookieDict] = {}

        # External callbacks
        self._on_refresh: CookieRefreshCallback | None = None
        self._on_expired: CookieExpiredCallback | None = None

    # ------------------------------------------------------------------
    # Callback registration (set by caller before start())
    # ------------------------------------------------------------------

    def set_refresh_callback(self, cb: CookieRefreshCallback) -> None:
        """Register a callback invoked with ``(handle, fresh_cookies)`` after
        a successful background refresh."""
        self._on_refresh = cb

    def set_expired_callback(self, cb: CookieExpiredCallback) -> None:
        """Register a callback invoked with ``(handle)`` when cookies are
        found to be invalid during a refresh sweep."""
        self._on_expired = cb

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the background refresh loop.  Browser is launched lazily."""
        self._refresh_task = asyncio.create_task(self._refresh_loop())
        logger.info("CFSessionManager started (browser lazy-init)")

    async def stop(self) -> None:
        """Cancel background tasks and shut down the browser."""
        if self._refresh_task is not None:
            self._refresh_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._refresh_task
            self._refresh_task = None
        await self._close_browser()
        logger.info("CFSessionManager stopped")

    # ------------------------------------------------------------------
    # Browser management
    # ------------------------------------------------------------------

    async def _ensure_browser(self) -> Browser:
        """Return the shared browser, launching (or re-launching) if needed."""
        async with self._lock:
            if self._browser is not None and self._browser.is_connected():
                self._last_used = time.monotonic()
                return self._browser
            # Close stale references
            await self._close_browser_unsafe()
            self._pw = await async_playwright().start()
            self._browser = await self._pw.chromium.launch(
                headless=False,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                ],
            )
            self._last_used = time.monotonic()
            logger.info("Launched patchright Chromium browser")
            return self._browser

    async def _close_browser(self) -> None:
        async with self._lock:
            await self._close_browser_unsafe()

    async def _close_browser_unsafe(self) -> None:
        """Close browser + playwright.  Caller must hold ``_lock``."""
        if self._browser is not None:
            with contextlib.suppress(Exception):
                await self._browser.close()
            self._browser = None
        if self._pw is not None:
            with contextlib.suppress(Exception):
                await self._pw.stop()
            self._pw = None

    async def _check_idle(self) -> None:
        """Close the browser if it has been idle for too long."""
        if self._browser is not None and self._browser.is_connected() and time.monotonic() - self._last_used > MAX_IDLE:
            logger.info("Browser idle for %d s, shutting down", MAX_IDLE)
            await self._close_browser()

    # ------------------------------------------------------------------
    # Cookie registration
    # ------------------------------------------------------------------

    async def register(
        self,
        cf_handle: str,
        cookies: CookieDict,
    ) -> dict[str, Any]:
        """Register (or replace) cookies for a CF handle and validate them.

        Returns a dict with ``{"valid": bool, "cookies": {...}}``.
        The ``cookies`` value may contain refreshed cookies extracted
        during validation.
        """
        async with self._lock:
            self._cookies[cf_handle] = dict(cookies)
        logger.info("Registered cookies for %s (%d keys)", cf_handle, len(cookies))

        # Validate by creating a short-lived context
        is_valid, fresh = await self._validate_cookies(cf_handle, cookies)
        if is_valid and fresh:
            async with self._lock:
                self._cookies[cf_handle].update(fresh)
            return {"valid": True, "cookies": self._cookies[cf_handle]}
        return {"valid": is_valid, "cookies": self._cookies[cf_handle]}

    async def unregister(self, cf_handle: str) -> None:
        """Remove cookies for a handle."""
        async with self._lock:
            self._cookies.pop(cf_handle, None)
        logger.info("Unregistered %s", cf_handle)

    def get_cookies(self, cf_handle: str) -> CookieDict | None:
        """Return in-memory cookies for a handle (no DB access)."""
        return self._cookies.get(cf_handle)

    @property
    def registered_handles(self) -> list[str]:
        """Return handles currently registered in memory."""
        return list(self._cookies.keys())

    # ------------------------------------------------------------------
    # Context creation (for callers to use)
    # ------------------------------------------------------------------

    async def create_context(
        self,
        cf_handle: str,
        cookies: CookieDict,
    ) -> BrowserContext:
        """Create a browser context with the given cookies injected.

        The caller **must** close the context when done::

            ctx = await manager.create_context(handle, cookies)
            try:
                ...
            finally:
                await ctx.close()
        """
        browser = await self._ensure_browser()
        ctx = await browser.new_context(
            locale="en-US",
            viewport={"width": 1920, "height": 1080},
        )
        to_inject = _cookies_to_inject(cookies)
        if to_inject:
            await ctx.add_cookies(to_inject)
        return ctx

    # ------------------------------------------------------------------
    # Session validation
    # ------------------------------------------------------------------

    async def check_session(
        self,
        cf_handle: str,
        cookies: CookieDict,
    ) -> tuple[bool, CookieDict]:
        """Check if cookies are still valid for ``cf_handle``.

        Returns ``(is_valid, fresh_cookies)`` where *fresh_cookies* may
        contain renewed ``cf_clearance`` values.
        """
        return await self._validate_cookies(cf_handle, cookies)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _validate_cookies(
        self,
        cf_handle: str,
        cookies: CookieDict,
    ) -> tuple[bool, CookieDict]:
        """Open a short-lived context and verify login state."""
        ctx: BrowserContext | None = None
        try:
            ctx = await self.create_context(cf_handle, cookies)
            page = await ctx.new_page()
            try:
                await page.goto(CF_URL, wait_until="domcontentloaded", timeout=60_000)
                # Give Turnstile / JS challenges time to settle
                await page.wait_for_timeout(8_000)
                logged_in = await page.evaluate(f"() => !!document.querySelector('a[href=\"/profile/{cf_handle}\"]')")
                fresh: CookieDict = {}
                if logged_in:
                    fresh = await _extract_cookies(ctx)
                    if fresh:
                        async with self._lock:
                            stored = self._cookies.get(cf_handle)
                            if stored is not None:
                                stored.update(fresh)
                return logged_in, fresh
            finally:
                await page.close()
        except Exception as exc:
            logger.warning("Session validation failed for %s: %s", cf_handle, exc)
            return False, {}
        finally:
            if ctx is not None:
                with contextlib.suppress(Exception):
                    await ctx.close()

    # ------------------------------------------------------------------
    # Background refresh loop
    # ------------------------------------------------------------------

    async def _refresh_loop(self) -> None:
        """Periodically refresh cf_clearance for all registered handles."""
        while True:
            try:
                await asyncio.sleep(REFRESH_INTERVAL)
                # Idle check -- shut browser if nobody used it
                await self._check_idle()
                # Snapshot handles (avoid dict mutation during iteration)
                handles = list(self._cookies.keys())
                if not handles:
                    continue
                for handle in handles:
                    try:
                        cookies = self._cookies.get(handle)
                        if cookies is None:
                            continue
                        valid, fresh = await self._validate_cookies(handle, cookies)
                        if valid and fresh:
                            logger.info("Refreshed cookies for %s", handle)
                            if self._on_refresh is not None:
                                try:
                                    await self._on_refresh(handle, fresh)
                                except Exception as cb_exc:
                                    logger.error(
                                        "Refresh callback error for %s: %s",
                                        handle,
                                        cb_exc,
                                    )
                        elif not valid:
                            logger.warning("Session expired for %s", handle)
                            if self._on_expired is not None:
                                try:
                                    await self._on_expired(handle)
                                except Exception as cb_exc:
                                    logger.error(
                                        "Expired callback error for %s: %s",
                                        handle,
                                        cb_exc,
                                    )
                    except Exception as exc:
                        logger.error("Refresh error for %s: %s", handle, exc)
            except asyncio.CancelledError:
                return
            except Exception as exc:
                logger.error("Refresh loop error: %s", exc)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

cf_session_manager = CFSessionManager()
