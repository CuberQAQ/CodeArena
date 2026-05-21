"""Tests for the problem scraper service and API endpoints.

Tests cover:
- Problem ID parsing and URL building
- HTML parsing (sync, in executor)
- get_or_scrape: cache hit, cache miss + persist, scrape failure
- check_cached: batch cache check
- API endpoints: GET /{problem_id}/statement, GET /statements/check
- Error handling: invalid problem ID, scrape failure -> 503, empty problem_ids
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import DateTime, Integer, String, Text, event, func
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.schemas.problem import CacheCheckResponse, ProblemStatementResponse, SampleTest
from app.services.problem_scraper_service import (
    ProblemScraperService,
    build_cf_url,
    parse_problem_id,
)

# ---------------------------------------------------------------------------
# Lightweight SQLite-compatible test models
# ---------------------------------------------------------------------------


class _TestBase(DeclarativeBase):
    pass


class _TestProblemStatement(_TestBase):
    __tablename__ = "problem_statements"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4, nullable=False)
    problem_id: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    contest_id: Mapped[int] = mapped_column(Integer, nullable=False)
    index: Mapped[str] = mapped_column(String(5), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    time_limit: Mapped[str | None] = mapped_column(String(100), nullable=True)
    memory_limit: Mapped[str | None] = mapped_column(String(100), nullable=True)
    body_html: Mapped[str] = mapped_column(Text, nullable=False)
    input_spec_html: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_spec_html: Mapped[str | None] = mapped_column(Text, nullable=True)
    samples: Mapped[dict] = mapped_column(JSON, nullable=False)
    note_html: Mapped[str | None] = mapped_column(Text, nullable=True)
    full_html: Mapped[str] = mapped_column(Text, nullable=False)
    scraped_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def engine():
    """Create a fresh SQLite in-memory engine for each test."""
    eng = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)

    # Enable WAL mode and foreign keys for SQLite
    @event.listens_for(eng.sync_engine, "connect")
    def _set_sqlite_pragma(dbapi_conn, _connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return eng


@pytest.fixture
async def tables(engine):
    """Create all tables in the test database."""
    async with engine.begin() as conn:
        await conn.run_sync(_TestBase.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(_TestBase.metadata.drop_all)


@pytest.fixture
async def db_session(engine, tables):
    """Provide an async database session for tests."""
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session
        await session.rollback()


# ---------------------------------------------------------------------------
# Helper to create a test row
# ---------------------------------------------------------------------------


def _make_row(**overrides) -> _TestProblemStatement:
    defaults = {
        "problem_id": "1A",
        "contest_id": 1,
        "index": "A",
        "title": "Theatre Square",
        "time_limit": "1 second",
        "memory_limit": "256 megabytes",
        "body_html": "<div>The problem body</div>",
        "input_spec_html": "<div>Input spec</div>",
        "output_spec_html": "<div>Output spec</div>",
        "samples": [{"input": "3\n", "output": "4\n"}],
        "note_html": "<div>Note</div>",
        "full_html": "<div class='problem-statement'>full</div>",
        "scraped_at": datetime.now(UTC),
    }
    defaults.update(overrides)
    return _TestProblemStatement(**defaults)


# ---------------------------------------------------------------------------
# Tests: parse_problem_id
# ---------------------------------------------------------------------------


class TestParseProblemId:
    def test_simple(self):
        assert parse_problem_id("1A") == (1, "A")

    def test_multi_digit_contest(self):
        assert parse_problem_id("2100F2") == (2100, "F2")

    def test_leading_zeros(self):
        assert parse_problem_id("001A") == (1, "A")

    def test_invalid_no_letters(self):
        with pytest.raises(ValueError, match="Invalid"):
            parse_problem_id("123")

    def test_invalid_empty(self):
        with pytest.raises(ValueError, match="Invalid"):
            parse_problem_id("")

    def test_invalid_lowercase(self):
        with pytest.raises(ValueError, match="Invalid"):
            parse_problem_id("1a")

    def test_invalid_special_chars(self):
        with pytest.raises(ValueError, match="Invalid"):
            parse_problem_id("1A!")


class TestBuildCfUrl:
    def test_basic(self):
        assert build_cf_url(1, "A") == "https://codeforces.com/problemset/problem/1/A"

    def test_complex(self):
        assert build_cf_url(2100, "F2") == "https://codeforces.com/problemset/problem/2100/F2"


# ---------------------------------------------------------------------------
# Tests: _parse_problem_html (sync, tested directly)
# ---------------------------------------------------------------------------

SAMPLE_HTML = """
<html>
<body>
<div class="problem-statement">
    <div class="header">
        <div class="title">A. Theatre Square</div>
        <div class="time-limit">1 second</div>
        <div class="memory-limit">256 megabytes</div>
    </div>
    <div class="section-body">
        <p>The problem body text.</p>
    </div>
    <div class="input-specification">
        <p>Input description.</p>
    </div>
    <div class="output-specification">
        <p>Output description.</p>
    </div>
    <div class="sample-tests">
        <div class="section-title">Sample Input</div>
        <div class="sample-test">
            <div class="input">
                <div class="section-title">Input</div>
                <pre>
                    <div class="test-example-line">3</div>
                    <div class="test-example-line">1 2 3</div>
                </pre>
            </div>
            <div class="output">
                <div class="section-title">Output</div>
                <pre>
                    <div class="test-example-line">6</div>
                </pre>
            </div>
        </div>
    </div>
    <div class="note">
        <p>Note text.</p>
    </div>
</div>
</body>
</html>
"""


class TestParseProblemHtml:
    def test_full_parse(self):
        from app.services.problem_scraper_service import _parse_problem_html

        result = _parse_problem_html(SAMPLE_HTML)
        assert result["title"] == "A. Theatre Square"
        assert result["time_limit"] == "1 second"
        assert result["memory_limit"] == "256 megabytes"
        assert "section-body" in result["body_html"]
        assert "input-specification" in result["input_spec_html"]
        assert "output-specification" in result["output_spec_html"]
        assert len(result["samples"]) == 1
        assert result["samples"][0]["input"] == "3\n1 2 3"
        assert result["samples"][0]["output"] == "6"
        assert "note" in result["note_html"]
        assert "problem-statement" in result["full_html"]

    def test_missing_problem_statement_element(self):
        from app.services.problem_scraper_service import _parse_problem_html

        with pytest.raises(ValueError, match="No .problem-statement"):
            _parse_problem_html("<html><body>No problem here</body></html>")

    def test_minimal_html(self):
        from app.services.problem_scraper_service import _parse_problem_html

        html = (
            '<html><body><div class="problem-statement">'
            '<div class="header"><div class="title">B. Test</div>'
            "</div></div></body></html>"
        )
        result = _parse_problem_html(html)
        assert result["title"] == "B. Test"
        assert result["body_html"] == ""
        assert result["samples"] == []
        assert result["note_html"] is None
        assert result["input_spec_html"] is None
        assert result["output_spec_html"] is None


# ---------------------------------------------------------------------------
# Tests: ProblemScraperService.get_or_scrape
# ---------------------------------------------------------------------------


class TestGetOrScrape:
    @pytest.mark.asyncio
    async def test_cache_hit(self, db_session):
        """When a row exists in DB, it should be returned without scraping."""
        row = _make_row()
        db_session.add(row)
        await db_session.commit()

        service = ProblemScraperService()
        with patch.object(service, "scrape_problem") as mock_scrape:
            result = await service.get_or_scrape(db_session, "1A")
            mock_scrape.assert_not_called()

        assert result.problem_id == "1A"
        assert result.title == "Theatre Square"

    @pytest.mark.asyncio
    async def test_cache_miss_scrapes_and_persists(self, db_session):
        """When no row exists, scrape and persist."""
        scraped_data = {
            "title": "New Problem",
            "time_limit": "2 seconds",
            "memory_limit": "512 megabytes",
            "body_html": "<div>body</div>",
            "input_spec_html": "<div>input</div>",
            "output_spec_html": "<div>output</div>",
            "samples": [{"input": "1\n", "output": "2\n"}],
            "note_html": "<div>note</div>",
            "full_html": "<div class='problem-statement'>full</div>",
        }

        service = ProblemScraperService()
        # Patch ProblemStatement to use UUID default that works with SQLite
        with (
            patch.object(service, "scrape_problem", new_callable=AsyncMock, return_value=scraped_data),
            patch("app.services.problem_scraper_service.ProblemStatement", _TestProblemStatement),
        ):
            result = await service.get_or_scrape(db_session, "100A")

        assert result.problem_id == "100A"
        assert result.contest_id == 100
        assert result.index == "A"
        assert result.title == "New Problem"
        assert result.samples == [{"input": "1\n", "output": "2\n"}]
        assert result.id is not None

    @pytest.mark.asyncio
    async def test_scrape_failure_raises(self, db_session):
        """Scrape failure should propagate as RuntimeError."""
        service = ProblemScraperService()
        with patch.object(service, "scrape_problem", new_callable=AsyncMock, side_effect=RuntimeError("CF blocked")):
            with pytest.raises(RuntimeError, match="CF blocked"):
                await service.get_or_scrape(db_session, "999Z")


# ---------------------------------------------------------------------------
# Tests: check_cached
# ---------------------------------------------------------------------------


class TestCheckCached:
    @pytest.mark.asyncio
    async def test_mixed_cached(self, db_session):
        row1 = _make_row(problem_id="1A", contest_id=1, index="A")
        row2 = _make_row(problem_id="1B", contest_id=1, index="B", title="Other")
        db_session.add_all([row1, row2])
        await db_session.commit()

        service = ProblemScraperService()
        result = await service.check_cached(db_session, ["1A", "1B", "1C"])

        assert "1A" in result["cached"]
        assert "1B" in result["cached"]
        assert "1C" in result["not_cached"]
        assert "1A" not in result["not_cached"]

    @pytest.mark.asyncio
    async def test_all_cached(self, db_session):
        row = _make_row(problem_id="1A")
        db_session.add(row)
        await db_session.commit()

        service = ProblemScraperService()
        result = await service.check_cached(db_session, ["1A"])
        assert result["cached"] == ["1A"]
        assert result["not_cached"] == []

    @pytest.mark.asyncio
    async def test_none_cached(self, db_session):
        service = ProblemScraperService()
        result = await service.check_cached(db_session, ["2A", "2B"])
        assert result["cached"] == []
        assert "2A" in result["not_cached"]
        assert "2B" in result["not_cached"]

    @pytest.mark.asyncio
    async def test_empty_list(self, db_session):
        service = ProblemScraperService()
        result = await service.check_cached(db_session, [])
        assert result["cached"] == []
        assert result["not_cached"] == []


# ---------------------------------------------------------------------------
# Tests: API endpoints (via TestClient with mocked service)
# ---------------------------------------------------------------------------


@pytest.fixture
def client(db_session):
    """Create a TestClient that overrides the DB dependency."""
    from app.core.database import get_db
    from app.main import app

    async def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


class TestGetStatementEndpoint:
    def test_invalid_problem_id(self, client):
        resp = client.get("/api/v1/problem/INVALID/statement")
        assert resp.status_code == 400
        data = resp.json()
        assert data["success"] is False

    def test_scrape_failure_returns_503(self, client, db_session):
        with patch("app.api.v1.problem.scraper_service") as mock_svc:
            mock_svc.get_or_scrape = AsyncMock(side_effect=RuntimeError("CF blocked"))
            resp = client.get("/api/v1/problem/1A/statement")
            assert resp.status_code == 503
            data = resp.json()
            assert data["success"] is False
            assert "SERVICE_UNAVAILABLE" in data["error"]["code"]

    def test_success_returns_statement(self, client, db_session):
        mock_row = SimpleNamespace(
            problem_id="1A",
            contest_id=1,
            index="A",
            title="Theatre Square",
            time_limit="1 second",
            memory_limit="256 megabytes",
            body_html="<div>body</div>",
            input_spec_html="<div>input</div>",
            output_spec_html="<div>output</div>",
            samples=[{"input": "3\n", "output": "4\n"}],
            note_html="<div>note</div>",
            full_html="<div class='problem-statement'>full</div>",
            scraped_at=datetime.now(UTC),
        )
        with patch("app.api.v1.problem.scraper_service") as mock_svc:
            mock_svc.get_or_scrape = AsyncMock(return_value=mock_row)
            resp = client.get("/api/v1/problem/1A/statement")

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        stmt = data["data"]
        assert stmt["problem_id"] == "1A"
        assert stmt["title"] == "Theatre Square"
        assert stmt["fallback_url"] == "https://codeforces.com/problemset/problem/1/A"
        assert stmt["cached"] is True
        assert len(stmt["samples"]) == 1
        assert stmt["samples"][0]["input"] == "3\n"


class TestCheckCachedEndpoint:
    def test_success(self, client, db_session):
        with patch("app.api.v1.problem.scraper_service") as mock_svc:
            mock_svc.check_cached = AsyncMock(return_value={"cached": ["1A"], "not_cached": ["2B"]})
            resp = client.get("/api/v1/problem/statements/check?problem_ids=1A,2B")

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["data"]["cached"] == ["1A"]
        assert data["data"]["not_cached"] == ["2B"]

    def test_empty_problem_ids(self, client, db_session):
        resp = client.get("/api/v1/problem/statements/check?problem_ids=")
        assert resp.status_code == 400

    def test_whitespace_handling(self, client, db_session):
        with patch("app.api.v1.problem.scraper_service") as mock_svc:
            mock_svc.check_cached = AsyncMock(return_value={"cached": ["1A"], "not_cached": []})
            resp = client.get("/api/v1/problem/statements/check?problem_ids=1A%2C+%0A")

        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Tests: _extract_pre_text (sync helper)
# ---------------------------------------------------------------------------


class TestExtractPreText:
    def test_with_test_example_lines(self):
        from bs4 import BeautifulSoup

        from app.services.problem_scraper_service import _extract_pre_text

        html = "<pre><div class='test-example-line'>3</div><div class='test-example-line'>1 2 3</div></pre>"
        soup = BeautifulSoup(html, "lxml")
        pre = soup.find("pre")
        result = _extract_pre_text(pre)
        assert result == "3\n1 2 3"

    def test_without_test_example_lines(self):
        from bs4 import BeautifulSoup

        from app.services.problem_scraper_service import _extract_pre_text

        html = "<pre>plain text content</pre>"
        soup = BeautifulSoup(html, "lxml")
        pre = soup.find("pre")
        result = _extract_pre_text(pre)
        assert result == "plain text content"


# ---------------------------------------------------------------------------
# Tests: _fetch_page_html (via mock — tests retry logic and error handling)
# ---------------------------------------------------------------------------


class TestFetchPageHtml:
    def test_successful_fetch(self):
        """_fetch_page_html returns HTML on success."""
        from app.services.problem_scraper_service import _fetch_page_html

        mock_page = MagicMock()
        mock_page.content.return_value = '<html><div class="problem-statement">problem</div></html>'
        mock_page.goto = MagicMock()
        mock_page.wait_for_selector = MagicMock()

        mock_context = MagicMock()
        mock_context.new_page.return_value = mock_page
        mock_context.close = MagicMock()

        with patch("app.services.problem_scraper_service._new_context", return_value=mock_context):
            html = _fetch_page_html("https://codeforces.com/problemset/problem/1/A")

        assert "problem-statement" in html
        mock_context.close.assert_called_once()

    def test_retry_on_failure_then_success(self):
        """_fetch_page_html retries on failure and succeeds on second attempt."""
        from app.services.problem_scraper_service import _fetch_page_html

        mock_page = MagicMock()
        mock_page.goto.side_effect = [
            Exception("Network error"),
            None,  # second attempt succeeds
        ]
        mock_page.wait_for_selector = MagicMock()
        mock_page.content.return_value = '<html><div class="problem-statement">ok</div></html>'
        mock_page.wait_for_timeout = MagicMock()

        mock_context = MagicMock()
        mock_context.new_page.return_value = mock_page
        mock_context.close = MagicMock()

        with patch("app.services.problem_scraper_service._new_context", return_value=mock_context):
            html = _fetch_page_html("https://codeforces.com/problemset/problem/1/A", retries=3)

        assert "problem-statement" in html
        assert mock_page.goto.call_count == 2
        mock_page.wait_for_timeout.assert_called_once()

    def test_all_retries_exhausted(self):
        """_fetch_page_html raises RuntimeError when all retries fail."""
        from app.services.problem_scraper_service import _fetch_page_html

        mock_page = MagicMock()
        mock_page.goto.side_effect = Exception("Network error")
        mock_page.wait_for_timeout = MagicMock()

        mock_context = MagicMock()
        mock_context.new_page.return_value = mock_page
        mock_context.close = MagicMock()

        with patch("app.services.problem_scraper_service._new_context", return_value=mock_context):
            with pytest.raises(RuntimeError, match="Failed to scrape"):
                _fetch_page_html("https://codeforces.com/problemset/problem/1/A", retries=2)

        mock_context.close.assert_called_once()

    def test_page_without_problem_statement_raises(self):
        """If fetched HTML lacks .problem-statement, it should retry."""
        from app.services.problem_scraper_service import _fetch_page_html

        mock_page = MagicMock()
        # First call returns HTML without problem-statement, second succeeds
        mock_page.content.side_effect = [
            "<html><body>no problem here</body></html>",
            '<html><div class="problem-statement">found</div></html>',
        ]
        mock_page.goto = MagicMock()
        mock_page.wait_for_selector = MagicMock()
        mock_page.wait_for_timeout = MagicMock()

        mock_context = MagicMock()
        mock_context.new_page.return_value = mock_page
        mock_context.close = MagicMock()

        with patch("app.services.problem_scraper_service._new_context", return_value=mock_context):
            html = _fetch_page_html("https://codeforces.com/problemset/problem/1/A", retries=3)

        assert "problem-statement" in html


# ---------------------------------------------------------------------------
# Tests: _ensure_browser and _new_context
# ---------------------------------------------------------------------------


class TestBrowserManagement:
    def test_ensure_browser_creates_instance(self):
        """_ensure_browser should create a browser if none exists."""
        mock_pw = MagicMock()
        mock_browser = MagicMock()
        mock_pw.chromium.launch.return_value = mock_browser
        mock_pw.start.return_value = mock_pw

        with (
            patch("app.services.problem_scraper_service._browser_instance", None),
            patch("app.services.problem_scraper_service._playwright_instance", None),
            patch("app.services.problem_scraper_service.sync_playwright", return_value=mock_pw),
        ):
            from app.services.problem_scraper_service import _ensure_browser

            browser = _ensure_browser()
            assert browser is mock_browser

    @pytest.mark.asyncio
    async def test_shutdown_closes_browser(self):
        """shutdown() should close browser and playwright instances."""
        svc = ProblemScraperService()

        mock_browser = MagicMock()
        mock_pw = MagicMock()

        with (
            patch("app.services.problem_scraper_service._browser_instance", mock_browser),
            patch("app.services.problem_scraper_service._playwright_instance", mock_pw),
        ):
            await svc.shutdown()

        mock_browser.close.assert_called_once()
        mock_pw.stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_shutdown_no_browser(self):
        """shutdown() should be safe when no browser exists."""
        svc = ProblemScraperService()

        with (
            patch("app.services.problem_scraper_service._browser_instance", None),
            patch("app.services.problem_scraper_service._playwright_instance", None),
        ):
            # Should not raise
            await svc.shutdown()

    def test_ensure_browser_reuses_connected(self):
        """_ensure_browser should return existing browser if still connected."""
        mock_browser = MagicMock()
        mock_browser.is_connected.return_value = True

        with (
            patch("app.services.problem_scraper_service._browser_instance", mock_browser),
        ):
            from app.services.problem_scraper_service import _ensure_browser

            browser = _ensure_browser()
            assert browser is mock_browser

    def test_ensure_browser_recreates_when_disconnected(self):
        """_ensure_browser should recreate browser if existing one is disconnected."""
        old_browser = MagicMock()
        old_browser.is_connected.return_value = False

        old_pw = MagicMock()
        new_browser = MagicMock()
        new_pw = MagicMock()
        new_pw.chromium.launch.return_value = new_browser
        new_pw.start.return_value = new_pw

        with (
            patch("app.services.problem_scraper_service._browser_instance", old_browser),
            patch("app.services.problem_scraper_service._playwright_instance", old_pw),
            patch("app.services.problem_scraper_service.sync_playwright", return_value=new_pw),
        ):
            from app.services.problem_scraper_service import _ensure_browser

            browser = _ensure_browser()
            assert browser is new_browser
            old_pw.stop.assert_called_once()

    def test_new_context_creates_context(self):
        """_new_context should create a browser context with anti-detection."""
        mock_browser = MagicMock()
        mock_context = MagicMock()
        mock_browser.new_context.return_value = mock_context

        with patch("app.services.problem_scraper_service._ensure_browser", return_value=mock_browser):
            from app.services.problem_scraper_service import _new_context

            ctx = _new_context()
            assert ctx is mock_context
            mock_browser.new_context.assert_called_once()
            mock_context.add_init_script.assert_called_once()


# ---------------------------------------------------------------------------
# Tests: scrape_problem (async wrapper)
# ---------------------------------------------------------------------------


class TestScrapeProblem:
    @pytest.mark.asyncio
    async def test_scrape_problem_calls_run_sync(self):
        """scrape_problem should call _run_sync for fetch and parse."""
        svc = ProblemScraperService()

        mock_html = '<html><div class="problem-statement">test</div></html>'
        mock_parsed = {
            "title": "Test",
            "body_html": "<div>body</div>",
            "samples": [],
            "full_html": '<div class="problem-statement">test</div>',
        }

        call_log = []

        async def fake_run_sync(func, *args):
            call_log.append((func, args))
            if func.__name__ == "_fetch_page_html":
                return mock_html
            if func.__name__ == "_parse_problem_html":
                return mock_parsed
            return None

        with patch.object(svc, "_run_sync", side_effect=fake_run_sync):
            result = await svc.scrape_problem(1, "A")

        assert result["title"] == "Test"
        assert len(call_log) == 2

    @pytest.mark.asyncio
    async def test_scrape_problem_builds_correct_url(self):
        """scrape_problem should use the correct CF URL."""
        svc = ProblemScraperService()

        captured_url = []

        async def fake_run_sync(func, *args):
            if func.__name__ == "_fetch_page_html":
                captured_url.append(args[0])
                return '<div class="problem-statement">ok</div>'
            return {"title": "T", "body_html": "", "samples": [], "full_html": ""}

        with patch.object(svc, "_run_sync", side_effect=fake_run_sync):
            await svc.scrape_problem(2100, "F2")

        assert captured_url[0] == "https://codeforces.com/problemset/problem/2100/F2"


# ---------------------------------------------------------------------------
# Tests: _parse_problem_html edge cases
# ---------------------------------------------------------------------------


class TestParseProblemHtmlEdgeCases:
    def test_no_time_limit_element(self):
        from app.services.problem_scraper_service import _parse_problem_html

        html = (
            '<html><body><div class="problem-statement">'
            '<div class="header"><div class="title">A. Test</div>'
            '<div class="memory-limit">256 MB</div>'
            "</div></div></body></html>"
        )
        result = _parse_problem_html(html)
        assert result["title"] == "A. Test"
        assert result["time_limit"] is None
        assert result["memory_limit"] == "256 MB"

    def test_no_header_element(self):
        from app.services.problem_scraper_service import _parse_problem_html

        html = '<html><body><div class="problem-statement"></div></body></html>'
        result = _parse_problem_html(html)
        assert result["body_html"] == ""

    def test_multiple_samples(self):
        from app.services.problem_scraper_service import _parse_problem_html

        html = (
            '<html><body><div class="problem-statement">'
            '<div class="header"><div class="title">A. Multi</div></div>'
            '<div class="sample-test">'
            '<div class="input"><pre>1</pre></div>'
            '<div class="output"><pre>2</pre></div>'
            '<div class="input"><pre>3</pre></div>'
            '<div class="output"><pre>4</pre></div>'
            "</div></div></body></html>"
        )
        result = _parse_problem_html(html)
        assert len(result["samples"]) == 2
        assert result["samples"][0] == {"input": "1", "output": "2"}
        assert result["samples"][1] == {"input": "3", "output": "4"}


# ---------------------------------------------------------------------------
# Tests: Schema validation
# ---------------------------------------------------------------------------


class TestSchemas:
    def test_problem_statement_response(self):
        resp = ProblemStatementResponse(
            problem_id="1A",
            contest_id=1,
            index="A",
            title="Test",
            body_html="<p>body</p>",
            samples=[SampleTest(input="1", output="2")],
            full_html="<div>full</div>",
            scraped_at=datetime.now(UTC),
            fallback_url="https://codeforces.com/problemset/problem/1/A",
        )
        d = resp.model_dump(mode="json")
        assert d["problem_id"] == "1A"
        assert d["cached"] is True
        assert len(d["samples"]) == 1

    def test_cache_check_response(self):
        resp = CacheCheckResponse(cached=["1A"], not_cached=["2B"])
        d = resp.model_dump()
        assert d["cached"] == ["1A"]
        assert d["not_cached"] == ["2B"]
