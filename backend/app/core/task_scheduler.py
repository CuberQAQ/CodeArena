"""Background task scheduler for submission tracking.

Manages a long-running ``asyncio.Task`` that periodically polls pending
CF submissions and triggers settlement.  The scheduler integrates with
the FastAPI lifespan so that it starts on app startup and shuts down
gracefully on app shutdown.

Usage in ``main.py``::

    from app.core.task_scheduler import scheduler

    @asynccontextmanager
    async def lifespan(app):
        # ... startup ...
        scheduler.start(app)
        yield
        await scheduler.stop()
"""

import asyncio
import contextlib
import logging

from fastapi import FastAPI

from app.core.database import async_session_factory
from app.services.cf_api_service import CFApiService
from app.services.submission_tracker import SubmissionTracker

logger = logging.getLogger("code_arena.task_scheduler")

# Default interval between polling cycles (seconds).
DEFAULT_POLL_INTERVAL = 30


class TaskScheduler:
    """Background task scheduler for submission tracking.

    Starts a single ``asyncio.Task`` that runs a polling loop.  Each
    iteration:
      1. Polls CF API for pending submissions (via ``SubmissionTracker``).
      2. Settles any matched records.
      3. Handles timed-out records.
      4. Sleeps until the next cycle.

    The scheduler is designed to be instantiated once and controlled
    via ``start()`` / ``stop()``.
    """

    def __init__(self, poll_interval: float = DEFAULT_POLL_INTERVAL) -> None:
        self._poll_interval = poll_interval
        self._task: asyncio.Task | None = None
        self._cf_service: CFApiService | None = None
        self._running = False

    @property
    def running(self) -> bool:
        return self._running

    def start(self, app: FastAPI) -> None:
        """Start the background polling task.

        Safe to call multiple times -- subsequent calls are no-ops if the
        task is already running.
        """
        if self._running and self._task is not None:
            logger.warning("Task scheduler is already running")
            return

        self._cf_service = CFApiService()
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info(
            "Submission tracking scheduler started (interval=%ds)",
            self._poll_interval,
        )

    async def stop(self) -> None:
        """Stop the background polling task and clean up.

        Waits for the current iteration to complete before returning.
        """
        if not self._running:
            return

        self._running = False

        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

        if self._cf_service is not None:
            await self._cf_service.close()
            self._cf_service = None

        logger.info("Submission tracking scheduler stopped")

    async def _run_loop(self) -> None:
        """Main polling loop.  Runs until cancelled."""
        while self._running:
            try:
                await self._poll_cycle()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Error in submission tracking poll cycle")

            try:
                await asyncio.sleep(self._poll_interval)
            except asyncio.CancelledError:
                break

    async def _poll_cycle(self) -> None:
        """Execute one polling cycle: poll -> settle -> timeout."""
        async with async_session_factory() as db:
            try:
                # 1. Poll CF API and match pending records.
                matched_count = await SubmissionTracker.poll_submissions(
                    db,
                    self._cf_service,
                )

                # 2. Settle matched records.
                settled_count = 0
                if matched_count > 0:
                    settled_count = await SubmissionTracker.settle_matched(db)

                # 3. Handle timed-out records.
                timeout_count = await SubmissionTracker.handle_timeout(db)

                await db.commit()

                if matched_count or settled_count or timeout_count:
                    logger.info(
                        "Poll cycle complete: matched=%d settled=%d timeout=%d",
                        matched_count,
                        settled_count,
                        timeout_count,
                    )
            except Exception:
                await db.rollback()
                raise


# Module-level singleton.
scheduler = TaskScheduler()
