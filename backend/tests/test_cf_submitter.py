"""Tests for the CF submitter service.

Covers:
  1. SubmitResult dataclass defaults
  2. CF_LANGUAGES mapping
  3. VERDICT_LABELS mapping
  4. submit_to_cf: successful submission flow
  5. submit_to_cf: not logged in error
  6. submit_to_cf: page error after submit
  7. submit_to_cf: polling timeout
  8. submit_to_cf: Turnstile not solved (submits anyway)
  9. submit_to_cf: on_status_change callback
  10. submit_to_cf: navigation exception
  11. submit_to_cf: rate-limited during polling
"""

import time
from unittest.mock import AsyncMock, MagicMock, patch

from app.services import cf_submitter as submitter_module
from app.services.cf_submitter import (
    CF_LANGUAGES,
    FINAL_VERDICTS,
    VERDICT_LABELS,
    SubmitResult,
    submit_to_cf,
)

# ---------------------------------------------------------------------------
# 1. Dataclass / constant tests
# ---------------------------------------------------------------------------


class TestSubmitResult:
    def test_defaults(self):
        """SubmitResult should have sensible defaults."""
        result = SubmitResult()
        assert result.submission_id is None
        assert result.verdict is None
        assert result.verdict_label is None
        assert result.time_ms is None
        assert result.memory_bytes is None
        assert result.passed_test_count is None
        assert result.error is None
        assert result.success is False

    def test_with_values(self):
        """SubmitResult should store all fields."""
        result = SubmitResult(
            submission_id=12345,
            verdict="OK",
            verdict_label="Accepted",
            time_ms=100,
            memory_bytes=1024,
            passed_test_count=10,
            success=True,
        )
        assert result.submission_id == 12345
        assert result.verdict == "OK"
        assert result.success is True


class TestConstants:
    def test_cf_languages_has_expected_entries(self):
        """CF_LANGUAGES should contain expected language mappings."""
        assert CF_LANGUAGES["python3"] == 31
        assert CF_LANGUAGES["gnu_cpp17"] == 54
        assert CF_LANGUAGES["gnu_c11"] == 43
        assert CF_LANGUAGES["pypy3"] == 70
        assert CF_LANGUAGES["java21"] == 87
        assert CF_LANGUAGES["rust_2021"] == 75
        assert CF_LANGUAGES["go"] == 32
        assert CF_LANGUAGES["javascript"] == 34
        assert CF_LANGUAGES["gnu_cpp20"] == 89

    def test_verdict_labels_coverage(self):
        """VERDICT_LABELS should cover all final verdicts."""
        for v in FINAL_VERDICTS:
            assert v in VERDICT_LABELS, f"Missing label for verdict {v}"

    def test_final_verdicts_contains_expected(self):
        """FINAL_VERDICTS should contain the standard set."""
        expected = {
            "OK",
            "WRONG_ANSWER",
            "TIME_LIMIT_EXCEEDED",
            "MEMORY_LIMIT_EXCEEDED",
            "COMPILATION_ERROR",
            "RUNTIME_ERROR",
            "CHALLENGED",
            "SKIPPED",
        }
        assert expected == FINAL_VERDICTS


# ---------------------------------------------------------------------------
# Helper to build mock page
# ---------------------------------------------------------------------------


def _make_mock_page(
    *,
    logged_in: bool = True,
    turnstile_token: str = "token_abc",
    submit_error: str | None = None,
    final_url: str = "https://codeforces.com/contest/1/my",
    nav_exception: Exception | None = None,
):
    """Build a mock Playwright page."""
    page = AsyncMock()

    if nav_exception:
        page.goto.side_effect = nav_exception
    else:
        page.goto = AsyncMock()
        page.url = final_url

    # evaluate calls: logged_in check, turnstile, fill code, select lang, submit, error check
    call_index = [0]

    def _evaluate_side_effect(script, *args, **kwargs):
        ci = call_index[0]
        call_index[0] += 1
        # The first evaluate after goto is the logged-in check
        if ci == 0:
            return logged_in
        # Turnstile token check
        if ci == 1:
            return turnstile_token
        # Fill code (returns None)
        if ci == 2:
            return None
        # Select language (returns None)
        if ci == 3:
            return None
        # Click submit (returns None)
        if ci == 4:
            return None
        # Error check after submit
        if ci == 5:
            return submit_error
        return None

    page.evaluate.side_effect = _evaluate_side_effect
    page.wait_for_timeout = AsyncMock()
    page.wait_for_load_state = AsyncMock()
    page.close = AsyncMock()

    return page


def _make_mock_context(page):
    """Build a mock browser context that returns the given page."""
    ctx = AsyncMock()
    ctx.new_page = AsyncMock(return_value=page)
    ctx.close = AsyncMock()
    return ctx


def _make_cf_api_response(
    submissions: list[dict] | None = None,
    status: str = "OK",
    http_status: int = 200,
):
    """Build a mock httpx response for CF API."""
    resp = MagicMock()
    resp.status_code = http_status
    resp.json.return_value = {
        "status": status,
        "result": submissions or [],
    }
    return resp


# ---------------------------------------------------------------------------
# 2. submit_to_cf tests
# ---------------------------------------------------------------------------


class TestSubmitToCf:
    async def test_successful_ac_submission(self):
        """Full happy path: submit, poll, get OK verdict."""
        mock_page = _make_mock_page(final_url="https://codeforces.com/contest/1/my")
        mock_ctx = _make_mock_context(mock_page)

        # Build CF API responses
        # Pre-submit poll (empty) + post-submit poll (with AC)
        ac_submission = {
            "id": 99999,
            "contestId": 1,
            "problem": {"index": "A"},
            "verdict": "OK",
            "creationTimeSeconds": int(time.time()),
            "timeConsumedMillis": 100,
            "memoryConsumedBytes": 1024,
            "passedTestCount": 10,
        }
        pre_resp = _make_cf_api_response([])
        post_resp = _make_cf_api_response([ac_submission])

        call_count = [0]

        async def _mock_get(url, **kwargs):
            call_count[0] += 1
            if call_count[0] <= 1:
                return pre_resp
            return post_resp

        mock_http_client = AsyncMock()
        mock_http_client.get = _mock_get
        mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
        mock_http_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch.object(submitter_module, "cf_session_manager") as mock_mgr,
            patch.object(submitter_module, "httpx") as mock_httpx,
        ):
            mock_mgr.create_context = AsyncMock(return_value=mock_ctx)
            mock_httpx.AsyncClient.return_value = mock_http_client

            result = await submit_to_cf(
                contest_id=1,
                problem_index="A",
                source_code="print('hello')",
                language_id=31,
                cf_handle="testuser",
                cookies={"JSESSIONID": "abc"},
                poll_timeout=5,
                poll_interval=0.1,
            )

        assert result.success is True
        assert result.verdict == "OK"
        assert result.verdict_label == "Accepted"
        assert result.submission_id == 99999
        assert result.time_ms == 100
        assert result.memory_bytes == 1024
        assert result.passed_test_count == 10
        assert result.error is None

        # Verify context was closed
        mock_ctx.close.assert_awaited()

    async def test_not_logged_in_returns_error(self):
        """Should return error when not logged in."""
        mock_page = _make_mock_page(logged_in=False)
        mock_ctx = _make_mock_context(mock_page)

        mock_http_client = AsyncMock()
        mock_http_client.get = AsyncMock(return_value=_make_cf_api_response([]))
        mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
        mock_http_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch.object(submitter_module, "cf_session_manager") as mock_mgr,
            patch.object(submitter_module, "httpx") as mock_httpx,
        ):
            mock_mgr.create_context = AsyncMock(return_value=mock_ctx)
            mock_httpx.AsyncClient.return_value = mock_http_client

            result = await submit_to_cf(
                contest_id=1,
                problem_index="A",
                source_code="x",
                language_id=31,
                cf_handle="testuser",
                cookies={"JSESSIONID": "abc"},
            )

        assert result.success is False
        assert "Not logged in" in result.error

    async def test_submit_error_on_page(self):
        """Should return error when CF shows an error after submit."""
        mock_page = _make_mock_page(
            submit_error="You have submitted exactly the same code before",
        )
        mock_ctx = _make_mock_context(mock_page)

        mock_http_client = AsyncMock()
        mock_http_client.get = AsyncMock(return_value=_make_cf_api_response([]))
        mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
        mock_http_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch.object(submitter_module, "cf_session_manager") as mock_mgr,
            patch.object(submitter_module, "httpx") as mock_httpx,
        ):
            mock_mgr.create_context = AsyncMock(return_value=mock_ctx)
            mock_httpx.AsyncClient.return_value = mock_http_client

            result = await submit_to_cf(
                contest_id=1,
                problem_index="A",
                source_code="x",
                language_id=31,
                cf_handle="testuser",
                cookies={"JSESSIONID": "abc"},
            )

        assert result.success is False
        assert "same code" in result.error

    async def test_polling_timeout(self):
        """Should return timeout error when polling exceeds timeout."""
        mock_page = _make_mock_page(final_url="https://codeforces.com/contest/1/my")
        mock_ctx = _make_mock_context(mock_page)

        # CF API always returns empty
        empty_resp = _make_cf_api_response([])

        mock_http_client = AsyncMock()
        mock_http_client.get = AsyncMock(return_value=empty_resp)
        mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
        mock_http_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch.object(submitter_module, "cf_session_manager") as mock_mgr,
            patch.object(submitter_module, "httpx") as mock_httpx,
        ):
            mock_mgr.create_context = AsyncMock(return_value=mock_ctx)
            mock_httpx.AsyncClient.return_value = mock_http_client

            result = await submit_to_cf(
                contest_id=1,
                problem_index="A",
                source_code="x",
                language_id=31,
                cf_handle="testuser",
                cookies={"JSESSIONID": "abc"},
                poll_timeout=1,
                poll_interval=0.1,
            )

        assert result.success is False
        assert "timed out" in result.error

    async def test_navigation_exception(self):
        """Should return error when page navigation fails."""
        mock_page = _make_mock_page(
            nav_exception=Exception("Network error"),
        )
        mock_ctx = _make_mock_context(mock_page)

        mock_http_client = AsyncMock()
        mock_http_client.get = AsyncMock(return_value=_make_cf_api_response([]))
        mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
        mock_http_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch.object(submitter_module, "cf_session_manager") as mock_mgr,
            patch.object(submitter_module, "httpx") as mock_httpx,
        ):
            mock_mgr.create_context = AsyncMock(return_value=mock_ctx)
            mock_httpx.AsyncClient.return_value = mock_http_client

            result = await submit_to_cf(
                contest_id=1,
                problem_index="A",
                source_code="x",
                language_id=31,
                cf_handle="testuser",
                cookies={"JSESSIONID": "abc"},
            )

        assert result.success is False
        assert "Network error" in result.error

    async def test_status_change_callback(self):
        """Should call on_status_change with appropriate statuses."""
        mock_page = _make_mock_page(final_url="https://codeforces.com/contest/1/my")
        mock_ctx = _make_mock_context(mock_page)

        ac_submission = {
            "id": 42,
            "contestId": 1,
            "problem": {"index": "A"},
            "verdict": "OK",
            "creationTimeSeconds": int(time.time()),
            "timeConsumedMillis": 50,
            "memoryConsumedBytes": 512,
            "passedTestCount": 5,
        }
        pre_resp = _make_cf_api_response([])
        post_resp = _make_cf_api_response([ac_submission])

        call_count = [0]

        async def _mock_get(url, **kwargs):
            call_count[0] += 1
            if call_count[0] <= 1:
                return pre_resp
            return post_resp

        mock_http_client = AsyncMock()
        mock_http_client.get = _mock_get
        mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
        mock_http_client.__aexit__ = AsyncMock(return_value=False)

        statuses_received: list[tuple[str, dict]] = []

        async def on_status(status: str, data: dict):
            statuses_received.append((status, data))

        with (
            patch.object(submitter_module, "cf_session_manager") as mock_mgr,
            patch.object(submitter_module, "httpx") as mock_httpx,
        ):
            mock_mgr.create_context = AsyncMock(return_value=mock_ctx)
            mock_httpx.AsyncClient.return_value = mock_http_client

            result = await submit_to_cf(
                contest_id=1,
                problem_index="A",
                source_code="x",
                language_id=31,
                cf_handle="testuser",
                cookies={"JSESSIONID": "abc"},
                on_status_change=on_status,
                poll_timeout=5,
                poll_interval=0.1,
            )

        assert result.success is True

        status_names = [s for s, _ in statuses_received]
        assert "submitting" in status_names
        assert "waiting_turnstile" in status_names
        assert "done" in status_names

        # Check "done" data
        done_data = [d for s, d in statuses_received if s == "done"][0]
        assert done_data["verdict"] == "OK"
        assert done_data["submission_id"] == 42

    async def test_status_change_callback_error_does_not_crash(self):
        """If on_status_change raises, it should be caught."""
        mock_page = _make_mock_page(final_url="https://codeforces.com/contest/1/my")
        mock_ctx = _make_mock_context(mock_page)

        ac_submission = {
            "id": 42,
            "contestId": 1,
            "problem": {"index": "A"},
            "verdict": "OK",
            "creationTimeSeconds": int(time.time()),
        }
        pre_resp = _make_cf_api_response([])
        post_resp = _make_cf_api_response([ac_submission])

        call_count = [0]

        async def _mock_get(url, **kwargs):
            call_count[0] += 1
            if call_count[0] <= 1:
                return pre_resp
            return post_resp

        mock_http_client = AsyncMock()
        mock_http_client.get = _mock_get
        mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
        mock_http_client.__aexit__ = AsyncMock(return_value=False)

        async def bad_callback(status: str, data: dict):
            raise RuntimeError("Callback error")

        with (
            patch.object(submitter_module, "cf_session_manager") as mock_mgr,
            patch.object(submitter_module, "httpx") as mock_httpx,
        ):
            mock_mgr.create_context = AsyncMock(return_value=mock_ctx)
            mock_httpx.AsyncClient.return_value = mock_http_client

            result = await submit_to_cf(
                contest_id=1,
                problem_index="A",
                source_code="x",
                language_id=31,
                cf_handle="testuser",
                cookies={"JSESSIONID": "abc"},
                on_status_change=bad_callback,
                poll_timeout=5,
                poll_interval=0.1,
            )

        # Should still succeed despite callback errors
        assert result.success is True

    async def test_known_ids_filtering(self):
        """Should not match old submissions that were already known."""
        mock_page = _make_mock_page(final_url="https://codeforces.com/contest/1/my")
        mock_ctx = _make_mock_context(mock_page)

        now = int(time.time())
        # Old submission that exists before we submit
        old_sub = {
            "id": 100,
            "contestId": 1,
            "problem": {"index": "A"},
            "verdict": "OK",
            "creationTimeSeconds": now - 60,
        }
        # New submission (the one we just made)
        new_sub = {
            "id": 200,
            "contestId": 1,
            "problem": {"index": "A"},
            "verdict": "WRONG_ANSWER",
            "creationTimeSeconds": now,
            "timeConsumedMillis": 50,
            "passedTestCount": 2,
        }

        call_count = [0]

        async def _mock_get(url, **kwargs):
            call_count[0] += 1
            if call_count[0] <= 1:
                # Pre-submit: returns old sub
                return _make_cf_api_response([old_sub])
            # Post-submit: returns both old and new
            return _make_cf_api_response([old_sub, new_sub])

        mock_http_client = AsyncMock()
        mock_http_client.get = _mock_get
        mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
        mock_http_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch.object(submitter_module, "cf_session_manager") as mock_mgr,
            patch.object(submitter_module, "httpx") as mock_httpx,
        ):
            mock_mgr.create_context = AsyncMock(return_value=mock_ctx)
            mock_httpx.AsyncClient.return_value = mock_http_client

            result = await submit_to_cf(
                contest_id=1,
                problem_index="A",
                source_code="x",
                language_id=31,
                cf_handle="testuser",
                cookies={"JSESSIONID": "abc"},
                poll_timeout=5,
                poll_interval=0.1,
            )

        # Should match the new submission (id=200), not the old one (id=100)
        assert result.submission_id == 200
        assert result.verdict == "WRONG_ANSWER"
        assert result.success is False

    async def test_pre_poll_api_failure_continues(self):
        """If the pre-submit snapshot fails, submission should still proceed."""
        mock_page = _make_mock_page(final_url="https://codeforces.com/contest/1/my")
        mock_ctx = _make_mock_context(mock_page)

        now = int(time.time())
        new_sub = {
            "id": 300,
            "contestId": 1,
            "problem": {"index": "A"},
            "verdict": "OK",
            "creationTimeSeconds": now,
        }

        call_count = [0]

        async def _mock_get(url, **kwargs):
            call_count[0] += 1
            if call_count[0] <= 1:
                # Pre-submit: API error
                resp = MagicMock()
                resp.status_code = 500
                return resp
            return _make_cf_api_response([new_sub])

        mock_http_client = AsyncMock()
        mock_http_client.get = _mock_get
        mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
        mock_http_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch.object(submitter_module, "cf_session_manager") as mock_mgr,
            patch.object(submitter_module, "httpx") as mock_httpx,
        ):
            mock_mgr.create_context = AsyncMock(return_value=mock_ctx)
            mock_httpx.AsyncClient.return_value = mock_http_client

            result = await submit_to_cf(
                contest_id=1,
                problem_index="A",
                source_code="x",
                language_id=31,
                cf_handle="testuser",
                cookies={"JSESSIONID": "abc"},
                poll_timeout=5,
                poll_interval=0.1,
            )

        assert result.success is True
        assert result.submission_id == 300

    async def test_no_turnstile_token_submits_anyway(self):
        """Should submit even when Turnstile does not auto-solve."""
        mock_page = _make_mock_page(
            turnstile_token="",
            final_url="https://codeforces.com/contest/1/my",
        )
        mock_ctx = _make_mock_context(mock_page)

        now = int(time.time())
        new_sub = {
            "id": 400,
            "contestId": 1,
            "problem": {"index": "A"},
            "verdict": "OK",
            "creationTimeSeconds": now,
        }

        call_count = [0]

        async def _mock_get(url, **kwargs):
            call_count[0] += 1
            if call_count[0] <= 1:
                return _make_cf_api_response([])
            return _make_cf_api_response([new_sub])

        mock_http_client = AsyncMock()
        mock_http_client.get = _mock_get
        mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
        mock_http_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch.object(submitter_module, "cf_session_manager") as mock_mgr,
            patch.object(submitter_module, "httpx") as mock_httpx,
        ):
            mock_mgr.create_context = AsyncMock(return_value=mock_ctx)
            mock_httpx.AsyncClient.return_value = mock_http_client

            result = await submit_to_cf(
                contest_id=1,
                problem_index="A",
                source_code="x",
                language_id=31,
                cf_handle="testuser",
                cookies={"JSESSIONID": "abc"},
                poll_timeout=5,
                poll_interval=0.1,
            )

        assert result.success is True
