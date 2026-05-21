"""Codeforces problem statement scraper service.

Uses Playwright (sync API) via ``run_in_executor`` to scrape CF problem pages,
parse structured data, and cache results in the database.

Key design decisions:
- Browser instance is a **process-level singleton** to avoid cold-start cost.
- Each scrape creates a **new browser context** (fresh cookies / storage).
- Sync Playwright calls are wrapped with ``loop.run_in_executor(None, ...)``
  so FastAPI async handlers are never blocked directly.
- Parsed data is persisted as ``ProblemStatement`` rows (permanent cache).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
from typing import Any

from bs4 import BeautifulSoup, Tag
from playwright.sync_api import Browser, BrowserContext, sync_playwright
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.problem_statement import ProblemStatement

logger = logging.getLogger("code_arena.problem_scraper")

# ---------------------------------------------------------------------------
# Problem-ID parsing helpers
# ---------------------------------------------------------------------------

# Matches CF problem IDs like "1A", "1234B1", "2100F2"
_PROBLEM_ID_RE = re.compile(r"^(\d+)([A-Z]\d?)$")


def parse_problem_id(problem_id: str) -> tuple[int, str]:
    """Split a CF problem ID into ``(contest_id, index)``.

    Examples::

        >>> parse_problem_id("1A")
        (1, "A")
        >>> parse_problem_id("2100F2")
        (2100, "F2")

    Raises ``ValueError`` for malformed IDs.
    """
    m = _PROBLEM_ID_RE.match(problem_id.strip())
    if not m:
        raise ValueError(f"Invalid CF problem ID: {problem_id!r}")
    return int(m.group(1)), m.group(2)


def build_cf_url(contest_id: int, index: str) -> str:
    """Build the CF problemset URL."""
    return f"https://codeforces.com/problemset/problem/{contest_id}/{index}"


# ---------------------------------------------------------------------------
# Browser singleton
# ---------------------------------------------------------------------------

_playwright_instance = None
_browser_instance: Browser | None = None


def _ensure_browser() -> Browser:
    """Return the shared Chromium browser instance (lazy init)."""
    global _browser_instance, _playwright_instance
    if _browser_instance is None or not _browser_instance.is_connected():
        # Clean up old playwright if browser died
        if _playwright_instance is not None:
            with contextlib.suppress(Exception):
                _playwright_instance.stop()
        _playwright_instance = sync_playwright().start()
        _browser_instance = _playwright_instance.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )
    return _browser_instance


def _new_context() -> BrowserContext:
    """Create a new browser context with anti-detection measures."""
    browser = _ensure_browser()
    context = browser.new_context(
        user_agent=(
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36"
        ),
        locale="en-US",
        viewport={"width": 1920, "height": 1080},
    )
    context.add_init_script("Object.defineProperty(navigator, 'webdriver', { get: () => undefined });")
    return context


# ---------------------------------------------------------------------------
# Sync scraping functions (run in executor)
# ---------------------------------------------------------------------------

_DEFAULT_RETRIES = 3
_RETRY_DELAY = 3  # seconds


def _fetch_page_html(url: str, retries: int = _DEFAULT_RETRIES) -> str:
    """Fetch full page HTML via Playwright.  *Blocking* -- call via executor."""
    context = _new_context()
    page = context.new_page()
    try:
        for attempt in range(1, retries + 1):
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=30_000)
                page.wait_for_selector(".problem-statement", timeout=20_000)
                # Wait for MathJax rendering to settle
                page.wait_for_timeout(1500)
                html = page.content()
                if "problem-statement" not in html:
                    raise RuntimeError("Page does not contain .problem-statement")
                return html
            except Exception as exc:
                logger.warning(
                    "Scrape attempt %d/%d failed for %s: %s",
                    attempt,
                    retries,
                    url,
                    exc,
                )
                if attempt < retries:
                    page.wait_for_timeout(_RETRY_DELAY * 1000)
                else:
                    raise RuntimeError(f"Failed to scrape {url} after {retries} attempts") from exc
    finally:
        context.close()

    # Unreachable, but keeps type checkers happy
    raise RuntimeError("Unreachable")  # pragma: no cover


def _extract_pre_text(pre: Tag) -> str:
    """Extract text from a ``<pre>`` element, preserving line-breaks."""
    lines = pre.select(".test-example-line")
    if lines:
        return "\n".join(line.get_text() for line in lines)
    return pre.get_text()


def _parse_problem_html(html: str) -> dict[str, Any]:
    """Parse structured problem data from raw HTML.

    Returns a dict with keys matching ``ProblemStatement`` columns.
    """
    soup = BeautifulSoup(html, "lxml")
    ps = soup.select_one(".problem-statement")
    if ps is None:
        raise ValueError("No .problem-statement element found in HTML")

    result: dict[str, Any] = {}

    # Title
    title_el = ps.select_one(".header .title")
    result["title"] = title_el.get_text(strip=True) if title_el else "Unknown"

    # Time / memory limits
    tl = ps.select_one(".header .time-limit")
    result["time_limit"] = tl.get_text(strip=True) if tl else None
    ml = ps.select_one(".header .memory-limit")
    result["memory_limit"] = ml.get_text(strip=True) if ml else None

    # Body HTML (everything after header except input/output specs, samples, notes)
    header = ps.select_one(".header")
    skip_classes = {"input-specification", "output-specification", "sample-tests", "note"}
    if header:
        body_parts = []
        for sibling in header.next_siblings:
            if isinstance(sibling, Tag) and sibling.name == "div":
                classes = sibling.get("class", [])
                if not any(c in skip_classes for c in classes):
                    body_parts.append(str(sibling))
        result["body_html"] = "\n".join(body_parts)
    else:
        result["body_html"] = ""

    # Input / output specifications
    inp = ps.select_one(".input-specification")
    result["input_spec_html"] = str(inp) if inp else None
    out = ps.select_one(".output-specification")
    result["output_spec_html"] = str(out) if out else None

    # Samples
    samples: list[dict[str, str]] = []
    for st in ps.select(".sample-test"):
        inputs = st.select(".input pre")
        outputs = st.select(".output pre")
        for inp_el, out_el in zip(inputs, outputs, strict=False):
            samples.append(
                {
                    "input": _extract_pre_text(inp_el),
                    "output": _extract_pre_text(out_el),
                }
            )
    result["samples"] = samples

    # Note
    note = ps.select_one(".note")
    result["note_html"] = str(note) if note else None

    # Full problem-statement HTML
    result["full_html"] = str(ps)

    return result


# ---------------------------------------------------------------------------
# Async service class
# ---------------------------------------------------------------------------


class ProblemScraperService:
    """High-level async service for scraping and caching CF problem statements."""

    @staticmethod
    async def _run_sync(func: Any, *args: Any) -> Any:
        """Run a blocking function in the default thread executor."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, func, *args)

    # ---- public API -------------------------------------------------------

    async def scrape_problem(self, contest_id: int, index: str) -> dict[str, Any]:
        """Scrape and parse a single problem page.

        Returns the parsed dict (not yet persisted).
        """
        url = build_cf_url(contest_id, index)
        logger.info("Scraping problem: %s", url)
        html = await self._run_sync(_fetch_page_html, url)
        data = await self._run_sync(_parse_problem_html, html)
        return data

    async def get_or_scrape(
        self,
        db: AsyncSession,
        problem_id: str,
    ) -> ProblemStatement:
        """Return a cached ``ProblemStatement`` or scrape, persist, and return.

        Raises ``RuntimeError`` on scrape failure (caller decides fallback).
        """
        # 1. Check cache
        stmt = select(ProblemStatement).where(ProblemStatement.problem_id == problem_id)
        result = await db.execute(stmt)
        cached = result.scalar_one_or_none()
        if cached is not None:
            logger.debug("Cache hit for problem %s", problem_id)
            return cached

        # 2. Parse ID, scrape, persist
        contest_id, index = parse_problem_id(problem_id)
        data = await self.scrape_problem(contest_id, index)

        row = ProblemStatement(
            problem_id=problem_id,
            contest_id=contest_id,
            index=index,
            title=data["title"],
            time_limit=data.get("time_limit"),
            memory_limit=data.get("memory_limit"),
            body_html=data["body_html"],
            input_spec_html=data.get("input_spec_html"),
            output_spec_html=data.get("output_spec_html"),
            samples=data["samples"],
            note_html=data.get("note_html"),
            full_html=data["full_html"],
        )
        db.add(row)
        await db.flush()
        logger.info("Persisted problem statement for %s", problem_id)
        return row

    async def check_cached(
        self,
        db: AsyncSession,
        problem_ids: list[str],
    ) -> dict[str, list[str]]:
        """Return ``{"cached": [...], "not_cached": [...]}`` for the given IDs."""
        stmt = select(ProblemStatement.problem_id).where(ProblemStatement.problem_id.in_(problem_ids))
        result = await db.execute(stmt)
        cached_set = {row[0] for row in result.all()}
        return {
            "cached": sorted(pid for pid in problem_ids if pid in cached_set),
            "not_cached": sorted(pid for pid in problem_ids if pid not in cached_set),
        }

    async def shutdown(self) -> None:
        """Close the shared browser instance.  Call on app shutdown."""
        global _browser_instance, _playwright_instance
        if _browser_instance is not None:
            with contextlib.suppress(Exception):
                _browser_instance.close()
            _browser_instance = None
        if _playwright_instance is not None:
            with contextlib.suppress(Exception):
                _playwright_instance.stop()
            _playwright_instance = None


# Module-level singleton (lazy-init browser shared across requests)
scraper_service = ProblemScraperService()
