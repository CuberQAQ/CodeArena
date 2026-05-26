"""Codeforces remote submission service.

Submits code to Codeforces on behalf of a user through a headless browser,
then polls the CF API for the final verdict.

Architecture:
- Uses :class:`CFSessionManager` to obtain a per-request browser context
  with the user's cookies already injected.
- Each submission creates a **new** context and closes it when done (no reuse).
- Turnstile auto-solves under patchright (anti-detection Playwright fork).
- Verdict is obtained by polling ``user.status`` with known-ID + time-window
  double matching to avoid picking up stale submissions.

Status change callback:
  Callers may pass an ``on_status_change(status, data)`` coroutine to receive
  real-time updates suitable for WebSocket push.

Usage::

    from app.services.cf_submitter import submit_to_cf, CF_LANGUAGES

    result = await submit_to_cf(
        contest_id=1,
        problem_index="A",
        source_code="print('hello')",
        language_id=31,
        cf_handle="tourist",
        cookies={"JSESSIONID": "...", ...},
        on_status_change=my_ws_callback,
    )
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import httpx

from app.services.cf_session_manager import cf_session_manager

logger = logging.getLogger("code_arena.cf_submitter")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CF_LANGUAGES: dict[str, int] = {
    "gnu_c11": 43,
    "gnu_cpp17": 54,
    "gnu_cpp20": 89,
    "python3": 31,
    "pypy3": 70,
    "java21": 87,
    "rust_2021": 75,
    "go": 32,
    "javascript": 34,
}

FINAL_VERDICTS: set[str] = {
    "OK",
    "WRONG_ANSWER",
    "TIME_LIMIT_EXCEEDED",
    "MEMORY_LIMIT_EXCEEDED",
    "COMPILATION_ERROR",
    "RUNTIME_ERROR",
    "CHALLENGED",
    "SKIPPED",
}

VERDICT_LABELS: dict[str, str] = {
    "OK": "Accepted",
    "WRONG_ANSWER": "Wrong Answer",
    "TIME_LIMIT_EXCEEDED": "Time Limit Exceeded",
    "MEMORY_LIMIT_EXCEEDED": "Memory Limit Exceeded",
    "COMPILATION_ERROR": "Compilation Error",
    "RUNTIME_ERROR": "Runtime Error",
    "CHALLENGED": "Challenged",
    "SKIPPED": "Skipped",
}

# Callback type: async (status: str, data: dict) -> None
StatusCallback = Callable[[str, dict[str, Any]], Awaitable[None]]


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class SubmitResult:
    """Result of a CF submission."""

    submission_id: int | None = None
    verdict: str | None = None
    verdict_label: str | None = None
    time_ms: int | None = None
    memory_bytes: int | None = None
    passed_test_count: int | None = None
    error: str | None = None
    success: bool = False


# ---------------------------------------------------------------------------
# Core submission logic
# ---------------------------------------------------------------------------


async def submit_to_cf(
    contest_id: int,
    problem_index: str,
    source_code: str,
    language_id: int,
    cf_handle: str,
    cookies: dict[str, str],
    on_status_change: StatusCallback | None = None,
    poll_timeout: int = 120,
    poll_interval: int = 3,
) -> SubmitResult:
    """Submit code to Codeforces and poll for verdict.

    Uses a fresh browser context from :data:`cf_session_manager` for each
    call.  The context is closed when the function returns (or on error).

    Parameters
    ----------
    contest_id:
        CF contest ID.
    problem_index:
        Problem letter (e.g. ``"A"``, ``"B1"``).
    source_code:
        Source code text.
    language_id:
        CF language ID (see :data:`CF_LANGUAGES`).
    cf_handle:
        CF handle of the user.
    cookies:
        Cookie dict (``{name: value}``) obtained from
        :meth:`CFSessionManager.get_cookies` or DB.
    on_status_change:
        Optional async callback ``f(status, data)`` for real-time updates.
    poll_timeout:
        Max seconds to wait for a final verdict (default 120).
    poll_interval:
        Seconds between polls (default 3).

    Returns
    -------
    SubmitResult
        Submission outcome.  ``success`` is ``True`` only on AC.
    """

    async def _notify(status: str, data: dict[str, Any]) -> None:
        if on_status_change is not None:
            try:
                await on_status_change(status, data)
            except Exception:
                logger.warning("Status callback error for %s", status, exc_info=True)

    await _notify("submitting", {})

    # -- Snapshot known submission IDs before submitting --------------------
    known_ids: set[int] = set()
    submit_epoch = int(time.time())
    try:
        async with httpx.AsyncClient(timeout=10) as pre_client:
            pre_resp = await pre_client.get(
                "https://codeforces.com/api/user.status",
                params={"handle": cf_handle, "count": 5},
            )
            if pre_resp.status_code == 200:
                for sub in pre_resp.json().get("result", []):
                    if sub.get("contestId") == contest_id and sub.get("problem", {}).get("index") == problem_index:
                        known_ids.add(sub.get("id", 0))
    except Exception:
        pass

    # -- Create a fresh browser context ------------------------------------
    ctx = await cf_session_manager.create_context(cf_handle, cookies)
    page = await ctx.new_page()

    try:
        # Step 1: Navigate to submit page
        submit_url = f"https://codeforces.com/contest/{contest_id}/submit/{problem_index}"
        logger.info("Navigating to submit page: %s", submit_url)
        await page.goto(submit_url, wait_until="domcontentloaded", timeout=60_000)
        await page.wait_for_timeout(5_000)

        # Check if logged in
        logged_in = await page.evaluate(f"() => !!document.querySelector('a[href=\"/profile/{cf_handle}\"]')")
        if not logged_in:
            logger.error("Not logged in as %s", cf_handle)
            return SubmitResult(
                error="Not logged in -- cookies expired. User needs to re-provide cookies.",
            )

        # Step 2: Wait for Turnstile to auto-solve
        await _notify("waiting_turnstile", {})
        logger.info("Waiting for Turnstile token...")
        turnstile_token = ""
        for _ in range(30):
            turnstile_token = await page.evaluate(
                "() => document.querySelector('input[name=\"turnstileToken\"]')?.value || ''"
            )
            if turnstile_token:
                logger.info("Turnstile solved (token: %s...)", turnstile_token[:15])
                break
            await page.wait_for_timeout(2_000)

        if not turnstile_token:
            logger.warning("Turnstile did not auto-solve, submitting anyway...")

        # Step 3: Fill code via ACE editor + hidden textarea
        await page.evaluate(
            """
            (code) => {
                const aceEl = document.querySelector('.ace_editor');
                if (aceEl && typeof ace !== 'undefined') {
                    const editor = ace.edit(aceEl);
                    editor.setValue(code);
                    editor.clearSelection();
                }
                const ta = document.querySelector('textarea[name="source"]');
                if (ta) ta.value = code;
            }
            """,
            source_code,
        )
        logger.info("Code set (%d chars)", len(source_code))

        # Step 4: Select language
        await page.evaluate(
            f"() => {{"
            f"  const s = document.querySelector('select[name=\"programTypeId\"]');"
            f"  if (s) s.value = '{language_id}';"
            f"}}"
        )

        # Step 5: Submit
        logger.info("Clicking submit button...")
        await page.evaluate("() => document.querySelector('input[value=\"Submit\"]')?.click()")

        await page.wait_for_load_state("domcontentloaded", timeout=30_000)
        await page.wait_for_timeout(3_000)

        # Check for errors on result page
        error = await page.evaluate("() => document.querySelector('.error')?.textContent?.trim()")
        if error:
            logger.error("Submit error: %s", error)
            return SubmitResult(error=error)

        # Verify redirect
        final_url = page.url
        logger.info("After submit: %s", final_url)

        if f"/contest/{contest_id}/my" in final_url or "/submissions" in final_url:
            logger.info("Submit accepted -- redirected to submissions page")
    except Exception as e:
        logger.error("Submit exception: %s", e)
        return SubmitResult(error=str(e))
    finally:
        await page.close()
        await ctx.close()

    # -- Poll CF API for verdict -------------------------------------------
    logger.info("Polling for verdict (timeout=%ds)...", poll_timeout)

    async with httpx.AsyncClient(timeout=15) as client:
        start = time.time()
        current_status = ""
        while time.time() - start < poll_timeout:
            try:
                resp = await client.get(
                    "https://codeforces.com/api/user.status",
                    params={"handle": cf_handle, "count": 10},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("status") == "OK":
                        for sub in data.get("result", []):
                            cid = sub.get("contestId")
                            idx = sub.get("problem", {}).get("index", "")
                            sub_id = sub.get("id", 0)
                            ct = sub.get("creationTimeSeconds", 0)

                            if (
                                cid == contest_id
                                and idx == problem_index
                                and sub_id not in known_ids
                                and ct >= submit_epoch - 5
                            ):
                                verdict = sub.get("verdict")
                                if verdict and verdict in FINAL_VERDICTS:
                                    result = SubmitResult(
                                        submission_id=sub_id,
                                        verdict=verdict,
                                        verdict_label=VERDICT_LABELS.get(verdict, verdict),
                                        time_ms=sub.get("timeConsumedMillis"),
                                        memory_bytes=sub.get("memoryConsumedBytes"),
                                        passed_test_count=sub.get("passedTestCount"),
                                        success=(verdict == "OK"),
                                    )
                                    await _notify(
                                        "done",
                                        {
                                            "submission_id": result.submission_id,
                                            "verdict": result.verdict,
                                            "verdict_label": result.verdict_label,
                                            "time_ms": result.time_ms,
                                            "memory_bytes": result.memory_bytes,
                                            "passed_test_count": result.passed_test_count,
                                        },
                                    )
                                    logger.info(
                                        "Verdict: %s (id=%s, time=%sms, passed=%s)",
                                        result.verdict_label,
                                        result.submission_id,
                                        result.time_ms,
                                        result.passed_test_count,
                                    )
                                    return result
                                elif verdict == "TESTING":
                                    if current_status != "testing":
                                        current_status = "testing"
                                        await _notify("testing", {})
                                elif verdict is None or verdict == "":
                                    if current_status != "in_queue":
                                        current_status = "in_queue"
                                        await _notify("in_queue", {})
                elif resp.status_code == 429:
                    logger.warning("Rate limited, backing off...")
            except Exception as e:
                logger.warning("Poll error: %s", e)

            await asyncio.sleep(poll_interval)

    return SubmitResult(error=f"Polling timed out after {poll_timeout}s")
