"""Async submission tracking service.

Monitors pending Codeforces submissions by periodically polling the CF API
``user.status`` endpoint.  When a matching submission is found with a final
verdict, the corresponding game session is settled automatically.

Key guarantees:
  - Rate-limit safe: all CF API calls go through ``CFApiService`` which
    enforces a minimum 2-second interval between requests.
  - Idempotent settlement: each tracking record transitions through
    ``pending -> matched -> settled`` (or ``timeout``) exactly once.
  - Accurate stats: WA/TLE counts and time_spent are derived from actual
    CF API submission data, not hardcoded estimates.

Matching logic:
  A CF submission matches a pending record when:
    1. The CF handle belongs to the tracking record's user.
    2. The problem IDs match (contestId + index).
    3. The submission was created within the time window around
       ``expected_at``.

Final verdicts (trigger settlement):
  OK, WRONG_ANSWER, TIME_LIMIT_EXCEEDED, MEMORY_LIMIT_EXCEEDED,
  COMPILATION_ERROR, RUNTIME_ERROR, CHALLENGED, SKIPPED.

Non-final verdicts (keep polling):
  TESTING, null/empty (still running on judge).
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.submission_tracking import SubmissionTracking
from app.models.user import User
from app.services.cf_api_service import CFApiService

logger = logging.getLogger("code_arena.submission_tracker")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# How far before/after expected_at to look for matching submissions.
_MATCH_WINDOW_BEFORE = timedelta(minutes=5)
_MATCH_WINDOW_AFTER = timedelta(minutes=30)

# How long before a pending submission is considered timed out.
_TIMEOUT_AFTER = timedelta(hours=2)

# CF verdicts that represent a final, settled state.
_FINAL_VERDICTS: set[str] = {
    "OK",
    "WRONG_ANSWER",
    "TIME_LIMIT_EXCEEDED",
    "MEMORY_LIMIT_EXCEEDED",
    "COMPILATION_ERROR",
    "RUNTIME_ERROR",
    "CHALLENGED",
    "SKIPPED",
}

# CF verdicts that should be treated as "solved" for settlement purposes.
_SOLVED_VERDICTS: set[str] = {"OK"}

# Map CF verdict to a short human-readable label used in session settlement.
_VERDICT_LABEL: dict[str, str] = {
    "OK": "AC",
    "WRONG_ANSWER": "WA",
    "TIME_LIMIT_EXCEEDED": "TLE",
    "MEMORY_LIMIT_EXCEEDED": "MLE",
    "COMPILATION_ERROR": "CE",
    "RUNTIME_ERROR": "RE",
    "CHALLENGED": "CHALLENGED",
    "SKIPPED": "SKIPPED",
}

# CF verdicts that count as errors (used for error_count computation).
_ERROR_VERDICTS: set[str] = {
    "WRONG_ANSWER",
    "TIME_LIMIT_EXCEEDED",
    "MEMORY_LIMIT_EXCEEDED",
    "RUNTIME_ERROR",
    "COMPILATION_ERROR",
    "CHALLENGED",
}

# How many recent CF submissions to fetch per user per poll.
_POLL_COUNT = 50


@dataclass
class SubmissionStats:
    """Aggregated submission statistics derived from CF API data."""

    total_submissions: int
    error_count: int
    time_spent: float
    last_ac_creation_time: datetime | None


class SubmissionTracker:
    """Tracks pending CF submissions and triggers settlement on match.

    All methods are stateless -- they receive a db session and the CF API
    service as parameters, keeping the service easy to test.
    """

    # ------------------------------------------------------------------
    # 1. Register a pending submission
    # ------------------------------------------------------------------

    @staticmethod
    async def register_pending(
        db: AsyncSession,
        user_id: uuid.UUID,
        session_type: str,
        session_id: uuid.UUID,
        problem_id: str,
        expected_at: datetime,
    ) -> SubmissionTracking:
        """Create a new pending tracking record.

        Called when a user starts solving a problem in a game session.
        The ``expected_at`` timestamp marks when the user was expected to
        submit on Codeforces.

        Parameters
        ----------
        db:
            Async database session.
        user_id:
            The user solving the problem.
        session_type:
            One of ``pve``, ``pvp``, ``training``, ``contest``.
        session_id:
            ID of the game session.
        problem_id:
            CF problem ID (e.g. ``"800A"``).
        expected_at:
            The approximate time the user will submit on CF.

        Returns
        -------
        SubmissionTracking
            The newly created tracking record.
        """
        record = SubmissionTracking(
            user_id=user_id,
            session_type=session_type,
            session_id=session_id,
            problem_id=problem_id,
            status="pending",
            expected_at=expected_at,
        )
        db.add(record)
        await db.flush()

        logger.info(
            "Registered pending submission: id=%s user=%s session=%s/%s problem=%s",
            record.id, user_id, session_type, session_id, problem_id,
        )
        return record

    # ------------------------------------------------------------------
    # 2. Poll CF API for all pending submissions
    # ------------------------------------------------------------------

    @staticmethod
    async def poll_submissions(
        db: AsyncSession,
        cf_service: CFApiService,
    ) -> int:
        """Poll CF API for all users with pending tracking records.

        For each user, fetches recent submissions from CF and attempts to
        match them against pending records.

        Parameters
        ----------
        db:
            Async database session.
        cf_service:
            CF API service instance (handles rate limiting).

        Returns
        -------
        int
            Number of records that were matched and are ready for settlement.
        """
        # Find all users with pending records.
        user_stmt = (
            select(SubmissionTracking.user_id)
            .where(SubmissionTracking.status == "pending")
            .distinct()
        )
        result = await db.execute(user_stmt)
        user_ids = [row[0] for row in result.all()]

        if not user_ids:
            return 0

        matched_count = 0

        for user_id in user_ids:
            try:
                matched = await SubmissionTracker._poll_for_user(
                    db, cf_service, user_id,
                )
                matched_count += matched
            except Exception:
                logger.exception(
                    "Error polling submissions for user %s", user_id,
                )

        return matched_count

    # ------------------------------------------------------------------
    # 3. Match and update a single record
    # ------------------------------------------------------------------

    @staticmethod
    async def match_and_update(
        db: AsyncSession,
        tracking: SubmissionTracking,
        cf_submission: dict,
    ) -> bool:
        """Match a CF submission to a tracking record and update status.

        If the verdict is final, the status transitions to ``matched`` and
        ``settle_matched`` should be called afterward to trigger settlement.
        If the verdict is non-final (e.g. TESTING), the record remains
        ``pending`` and will be polled again.

        Parameters
        ----------
        db:
            Async database session.
        tracking:
            The pending tracking record.
        cf_submission:
            A single submission dict from the CF API ``user.status`` response.

        Returns
        -------
        bool
            True if the record was matched (verdict may or may not be final).
        """
        verdict = cf_submission.get("verdict")
        submission_id = cf_submission.get("id")

        tracking.cf_submission_id = submission_id
        tracking.cf_verdict = verdict

        if verdict in _FINAL_VERDICTS:
            tracking.status = "matched"
            tracking.matched_at = datetime.now(UTC)

            label = _VERDICT_LABEL.get(verdict, verdict)
            logger.info(
                "Matched submission %d for tracking %s: verdict=%s",
                submission_id, tracking.id, label,
            )
            return True

        # Non-final verdict -- record the CF submission ID but keep pending.
        logger.debug(
            "Partial match for tracking %s: cf_submission=%d verdict=%s (not final)",
            tracking.id, submission_id, verdict,
        )
        await db.flush()
        return False

    # ------------------------------------------------------------------
    # 4. Settle matched records
    # ------------------------------------------------------------------

    @staticmethod
    async def settle_matched(
        db: AsyncSession,
        cf_service: CFApiService | None = None,
    ) -> int:
        """Settle all tracking records in ``matched`` status.

        For each matched record, fetches accurate submission statistics from
        the CF API (total attempts, error count, time_spent) and calls the
        appropriate session service to apply Elo/PP/token changes.

        This method is idempotent -- it only processes records with
        ``status='matched'``.

        Parameters
        ----------
        db:
            Async database session.
        cf_service:
            CF API service instance for fetching submission stats.
            If None, falls back to default values.

        Returns
        -------
        int
            Number of records settled.
        """
        stmt = (
            select(SubmissionTracking)
            .where(SubmissionTracking.status == "matched")
        )
        result = await db.execute(stmt)
        matched_records = list(result.scalars().all())

        if not matched_records:
            return 0

        settled_count = 0
        for record in matched_records:
            try:
                await SubmissionTracker._settle_one(db, record, cf_service)
                settled_count += 1
            except Exception:
                logger.exception(
                    "Error settling tracking record %s", record.id,
                )

        return settled_count

    # ------------------------------------------------------------------
    # 5. Handle timed-out submissions
    # ------------------------------------------------------------------

    @staticmethod
    async def handle_timeout(db: AsyncSession) -> int:
        """Mark stale pending records as timed out.

        A record is considered timed out if it has been pending for longer
        than ``_TIMEOUT_AFTER`` past its ``expected_at``.

        Returns
        -------
        int
            Number of records marked as timed out.
        """
        cutoff = datetime.now(UTC) - _TIMEOUT_AFTER
        stmt = (
            update(SubmissionTracking)
            .where(
                and_(
                    SubmissionTracking.status == "pending",
                    SubmissionTracking.expected_at < cutoff,
                )
            )
            .values(status="timeout")
        )
        result = await db.execute(stmt)
        await db.flush()

        count = result.rowcount  # type: ignore[union-attr]
        if count > 0:
            logger.info("Marked %d submission tracking records as timed out", count)

        return count

    # ------------------------------------------------------------------
    # 6. Get tracking status for a session
    # ------------------------------------------------------------------

    @staticmethod
    async def get_tracking_for_session(
        db: AsyncSession,
        user_id: uuid.UUID,
        session_type: str,
        session_id: uuid.UUID,
    ) -> SubmissionTracking | None:
        """Return the most recent tracking record for a session, if any."""
        stmt = (
            select(SubmissionTracking)
            .where(
                and_(
                    SubmissionTracking.user_id == user_id,
                    SubmissionTracking.session_type == session_type,
                    SubmissionTracking.session_id == session_id,
                )
            )
            .order_by(SubmissionTracking.created_at.desc())
            .limit(1)
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    async def _get_submission_stats(
        db: AsyncSession,
        cf_service: CFApiService,
        tracking: SubmissionTracking,
    ) -> SubmissionStats:
        """Fetch all submissions for the tracked problem within the time window
        and compute accurate statistics.

        Returns a ``SubmissionStats`` with:
          - ``total_submissions``: total number of submissions for this problem
            in the window (including the final AC).
          - ``error_count``: number of submissions with non-AC final verdicts
            (WA, TLE, MLE, RE, CE, CHALLENGED).
          - ``time_spent``: seconds from ``expected_at`` to the last AC
            submission's ``creationTimeSeconds``.  Falls back to
            ``matched_at - expected_at`` if no AC found.
          - ``last_ac_creation_time``: the ``creationTimeSeconds`` of the last
            AC submission, or None.
        """
        user = await db.get(User, tracking.user_id)
        if user is None or not user.cf_handle:
            return SubmissionStats(
                total_submissions=1,
                error_count=0,
                time_spent=0.0,
                last_ac_creation_time=None,
            )

        # Ensure expected_at is timezone-aware.
        expected_at = tracking.expected_at
        if expected_at.tzinfo is None:
            expected_at = expected_at.replace(tzinfo=UTC)

        window_start = expected_at - _MATCH_WINDOW_BEFORE
        window_end = expected_at + _MATCH_WINDOW_AFTER

        try:
            cf_submissions = await cf_service.get_user_status(
                handle=user.cf_handle,
                count=_POLL_COUNT,
            )
        except Exception:
            logger.warning(
                "CF API error fetching submissions for %s during stats extraction",
                user.cf_handle,
            )
            return SubmissionStats(
                total_submissions=1,
                error_count=0,
                time_spent=0.0,
                last_ac_creation_time=None,
            )

        if not cf_submissions:
            return SubmissionStats(
                total_submissions=1,
                error_count=0,
                time_spent=0.0,
                last_ac_creation_time=None,
            )

        # Filter submissions matching the problem and within the time window.
        matching_subs: list[dict] = []
        for sub in cf_submissions:
            contest_id = sub.get("contestId", 0)
            index = sub.get("problem", {}).get("index", "")
            cf_problem_id = f"{contest_id}{index}"

            if cf_problem_id != tracking.problem_id:
                continue

            creation_time = sub.get("creationTimeSeconds")
            if creation_time is None:
                continue

            sub_time = datetime.fromtimestamp(creation_time, tz=UTC)
            if sub_time < window_start or sub_time > window_end:
                continue

            matching_subs.append(sub)

        if not matching_subs:
            return SubmissionStats(
                total_submissions=1,
                error_count=0,
                time_spent=0.0,
                last_ac_creation_time=None,
            )

        # Count errors (non-AC final verdicts).
        error_count = sum(
            1 for sub in matching_subs
            if sub.get("verdict") in _ERROR_VERDICTS
        )
        total_submissions = len(matching_subs)

        # Find the last AC submission's creation time for accurate time_spent.
        last_ac_time: datetime | None = None
        for sub in matching_subs:
            if sub.get("verdict") == "OK":
                creation_ts = sub.get("creationTimeSeconds")
                if creation_ts is not None:
                    sub_dt = datetime.fromtimestamp(creation_ts, tz=UTC)
                    if last_ac_time is None or sub_dt > last_ac_time:
                        last_ac_time = sub_dt

        # Calculate time_spent.
        if last_ac_time is not None:
            time_spent = max(0.0, (last_ac_time - expected_at).total_seconds())
        elif tracking.matched_at is not None:
            # Fallback: matched_at - expected_at.
            matched_at = tracking.matched_at
            if matched_at.tzinfo is None:
                matched_at = matched_at.replace(tzinfo=UTC)
            time_spent = max(0.0, (matched_at - expected_at).total_seconds())
        else:
            time_spent = 0.0

        return SubmissionStats(
            total_submissions=total_submissions,
            error_count=error_count,
            time_spent=time_spent,
            last_ac_creation_time=last_ac_time,
        )

    @staticmethod
    async def _poll_for_user(
        db: AsyncSession,
        cf_service: CFApiService,
        user_id: uuid.UUID,
    ) -> int:
        """Poll CF submissions for a single user and match against pending records.

        Returns the number of records that were matched with a final verdict.
        """
        # Get user's CF handle.
        user = await db.get(User, user_id)
        if user is None or not user.cf_handle:
            logger.warning("User %s has no CF handle, skipping poll", user_id)
            return 0

        # Fetch pending records for this user.
        pending_stmt = (
            select(SubmissionTracking)
            .where(
                and_(
                    SubmissionTracking.user_id == user_id,
                    SubmissionTracking.status == "pending",
                )
            )
        )
        pending_result = await db.execute(pending_stmt)
        pending_records = list(pending_result.scalars().all())

        if not pending_records:
            return 0

        # Poll CF API for recent submissions.
        try:
            cf_submissions = await cf_service.get_user_status(
                handle=user.cf_handle,
                count=_POLL_COUNT,
            )
        except Exception:
            logger.warning(
                "CF API error fetching submissions for %s", user.cf_handle,
            )
            return 0

        if not cf_submissions:
            return 0

        matched_count = 0

        for tracking in pending_records:
            cf_sub = SubmissionTracker._find_matching_submission(
                tracking, cf_submissions,
            )
            if cf_sub is not None:
                did_match = await SubmissionTracker.match_and_update(
                    db, tracking, cf_sub,
                )
                if did_match:
                    matched_count += 1

        if matched_count > 0:
            await db.flush()

        return matched_count

    @staticmethod
    def _find_matching_submission(
        tracking: SubmissionTracking,
        cf_submissions: list[dict],
    ) -> dict | None:
        """Find the best matching CF submission for a tracking record.

        Matching criteria:
          1. Problem ID matches: ``contestId + index`` equals ``problem_id``.
          2. Submission time is within the match window around ``expected_at``.
          3. Prefer the most recent submission (highest ID).

        Returns the matching submission dict, or None.
        """
        # Ensure expected_at is timezone-aware for comparison.
        if tracking.expected_at.tzinfo is None:
            tracking.expected_at = tracking.expected_at.replace(tzinfo=UTC)

        # Build CF problem ID from each submission.
        window_start = tracking.expected_at - _MATCH_WINDOW_BEFORE
        window_end = tracking.expected_at + _MATCH_WINDOW_AFTER

        best: dict | None = None
        best_id: int = -1

        for sub in cf_submissions:
            # Match problem ID.
            contest_id = sub.get("contestId", 0)
            index = sub.get("problem", {}).get("index", "")
            cf_problem_id = f"{contest_id}{index}"

            if cf_problem_id != tracking.problem_id:
                continue

            # Match time window.
            creation_time = sub.get("creationTimeSeconds")
            if creation_time is None:
                continue

            sub_time = datetime.fromtimestamp(creation_time, tz=UTC)

            if sub_time < window_start or sub_time > window_end:
                continue

            # Pick the most recent submission.
            sub_id = sub.get("id", 0)
            if sub_id > best_id:
                best = sub
                best_id = sub_id

        return best

    @staticmethod
    async def _settle_one(
        db: AsyncSession,
        tracking: SubmissionTracking,
        cf_service: CFApiService | None = None,
    ) -> None:
        """Settle a single matched tracking record.

        Fetches accurate submission statistics from CF API (if cf_service
        is provided) and dispatches to the appropriate session service.
        """
        verdict = tracking.cf_verdict or "UNKNOWN"
        is_solved = verdict in _SOLVED_VERDICTS

        # Fetch accurate stats from CF API if possible.
        stats: SubmissionStats | None = None
        if cf_service is not None:
            try:
                stats = await SubmissionTracker._get_submission_stats(
                    db, cf_service, tracking,
                )
            except Exception:
                logger.exception(
                    "Error fetching submission stats for tracking %s, using defaults",
                    tracking.id,
                )

        # Use real stats or fall back to minimal defaults.
        attempts = stats.total_submissions if stats else 1
        error_count = stats.error_count if stats else 0
        time_spent = stats.time_spent if stats else 0.0

        logger.info(
            "Settling tracking %s: session=%s/%s verdict=%s solved=%s "
            "attempts=%d error_count=%d time_spent=%.1f",
            tracking.id, tracking.session_type, tracking.session_id,
            verdict, is_solved, attempts, error_count, time_spent,
        )

        try:
            if tracking.session_type == "pve":
                await SubmissionTracker._settle_pve(
                    db, tracking, is_solved, verdict,
                    attempts=attempts, error_count=error_count, time_spent=time_spent,
                    cf_service=cf_service,
                )
            elif tracking.session_type == "training":
                await SubmissionTracker._settle_training(
                    db, tracking, is_solved, verdict,
                    attempts=attempts, time_spent=time_spent,
                    cf_service=cf_service,
                )
            elif tracking.session_type == "contest":
                await SubmissionTracker._settle_contest(
                    db, tracking, is_solved, verdict,
                    attempts=attempts, time_spent=time_spent,
                    cf_service=cf_service,
                )
            elif tracking.session_type == "pvp":
                await SubmissionTracker._settle_pvp(
                    db, tracking, is_solved, verdict,
                    attempts=attempts, time_spent=time_spent,
                    cf_service=cf_service,
                )
            else:
                logger.warning(
                    "Unknown session type %s for tracking %s",
                    tracking.session_type, tracking.id,
                )
        except Exception:
            logger.exception(
                "Settlement failed for tracking %s, leaving as matched",
                tracking.id,
            )
            raise

        # Mark as settled only if settlement succeeded.
        tracking.status = "settled"
        await db.flush()

    @staticmethod
    async def _settle_pve(
        db: AsyncSession,
        tracking: SubmissionTracking,
        is_solved: bool,
        verdict: str,
        *,
        attempts: int = 1,
        error_count: int = 0,
        time_spent: float = 0.0,
        cf_service: "CFApiService | None" = None,
    ) -> None:
        """Settle a PvE challenge session based on CF verdict.

        Calls the PvE challenge service's auto-settle endpoint with
        accurate stats derived from CF API data.
        """
        from app.services.pve_challenge_service import PvEChallengeService

        user = await db.get(User, tracking.user_id)
        if user is None:
            logger.error("User %s not found for PvE settlement", tracking.user_id)
            return

        await PvEChallengeService.submit_result(
            db=db,
            user=user,
            session_id=tracking.session_id,
            solved=is_solved,
            time_spent=time_spent,
            attempts=attempts,
            error_count=error_count,
            cf_service=cf_service,
        )

    @staticmethod
    async def _settle_training(
        db: AsyncSession,
        tracking: SubmissionTracking,
        is_solved: bool,
        verdict: str,
        *,
        attempts: int = 1,
        time_spent: float = 0.0,
        cf_service: "CFApiService | None" = None,
    ) -> None:
        """Settle a training session problem record.

        Training problem settlement is handled by the training service with
        accurate stats derived from CF API data.
        """
        from app.services.training_service import TrainingService

        user = await db.get(User, tracking.user_id)
        if user is None:
            logger.error("User %s not found for training settlement", tracking.user_id)
            return

        await TrainingService.submit_problem(
            db=db,
            user=user,
            session_id=tracking.session_id,
            problem_id=tracking.problem_id,
            solved=is_solved,
            attempts=attempts,
            time_spent=time_spent,
            cf_service=cf_service,
        )

    @staticmethod
    async def _settle_contest(
        db: AsyncSession,
        tracking: SubmissionTracking,
        is_solved: bool,
        verdict: str,
        *,
        attempts: int = 1,
        time_spent: float = 0.0,
        cf_service: "CFApiService | None" = None,  # noqa: ARG – kept for API consistency
    ) -> None:
        """Settle a contest problem record with accurate CF API stats."""
        from app.services.contest_service import ContestService

        user = await db.get(User, tracking.user_id)
        if user is None:
            logger.error("User %s not found for contest settlement", tracking.user_id)
            return

        await ContestService.submit_problem(
            db=db,
            user=user,
            contest_id=tracking.session_id,
            problem_id=tracking.problem_id,
            solved=is_solved,
            attempts=attempts,
            time_spent=time_spent,
        )

    @staticmethod
    async def _settle_pvp(
        db: AsyncSession,
        tracking: SubmissionTracking,
        is_solved: bool,
        verdict: str,
        *,
        attempts: int = 1,
        time_spent: float = 0.0,
        cf_service: "CFApiService | None" = None,
    ) -> None:
        """Settle a PvP challenge session with accurate CF API stats."""
        from app.services.challenge_service import ChallengeService

        user = await db.get(User, tracking.user_id)
        if user is None:
            logger.error("User %s not found for PvP settlement", tracking.user_id)
            return

        await ChallengeService.submit_result(
            db=db,
            user=user,
            session_id=tracking.session_id,
            solved=is_solved,
            time_spent=time_spent,
            attempts=attempts,
            cf_service=cf_service,
        )
