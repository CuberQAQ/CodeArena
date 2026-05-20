"""Per-problem expected time model based on CF contest data.

Calculates the expected time for a user to solve a problem, derived from
historical contest submissions and rating changes on Codeforces.

Key concepts:
- **Focused time**: For each solver, the time spent on a single problem,
  computed by subtracting the AC time of the previous sequential solve from
  the current one.  Only sequential solves (AC times in ascending order) are
  kept; "skip" data (non-sequential) is discarded.
- **Rating buckets**: Solvers are grouped into 200-point rating bands
  (e.g. 1200-1399, 1400-1599).  The median focused time of the user's
  bucket is used as T_expected.
- **Bucket expansion**: If a bucket has fewer than 5 data points, adjacent
  buckets are merged until the threshold is met.
- **Fallback**: When no contest data is available, a simple formula based on
  problem rating and user rating is used.
- **Time factor**: ``T_expected / max(T_effective, T_expected)``, clamped to
  [0.5, 1.5].  Returns 1.0 when the S-value is 0 (not solved).
"""

import logging
import re
from typing import Any

from app.services.cf_api_service import CFApiService

logger = logging.getLogger("code_arena.time_factor")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BUCKET_SIZE: int = 200          # rating bucket width in points
MIN_BUCKET_SIZE: int = 5        # minimum data points per bucket before expansion
MIN_CONTEST_ID: int = 1         # minimum valid contest ID
TIME_FACTOR_MIN: float = 0.5
TIME_FACTOR_MAX: float = 1.5
SECONDS_PER_MINUTE: float = 60.0


# ---------------------------------------------------------------------------
# Helper: extract contestId from problem_id
# ---------------------------------------------------------------------------

def _extract_contest_id(problem_id: str) -> int | None:
    """Extract the numeric contestId from a problem_id string.

    CF problem IDs are stored as ``"contestIdindex"`` (e.g. ``"1920A"``,
    ``"1846C"``, ``"1B"``).

    Returns ``None`` if the problem_id cannot be parsed.
    """
    match = re.match(r"^(\d+)[A-Za-z]", problem_id)
    if match:
        contest_id = int(match.group(1))
        return contest_id if contest_id >= MIN_CONTEST_ID else None
    return None


# ---------------------------------------------------------------------------
# Helper: determine the bucket key for a given rating
# ---------------------------------------------------------------------------

def _rating_bucket(rating: int) -> int:
    """Return the lower bound of the 200-point bucket for *rating*.

    Examples: 800 -> 800, 999 -> 800, 1200 -> 1200, 1399 -> 1200.
    """
    return (rating // BUCKET_SIZE) * BUCKET_SIZE


# ---------------------------------------------------------------------------
# Helper: compute median of a sorted list
# ---------------------------------------------------------------------------

def _median(values: list[float]) -> float | None:
    """Return the median of a list of floats.  Returns ``None`` if empty."""
    if not values:
        return None
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    mid = n // 2
    if n % 2 == 1:
        return sorted_vals[mid]
    return (sorted_vals[mid - 1] + sorted_vals[mid]) / 2.0


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class TimeFactorService:
    """Stateless service for computing per-problem expected time and time factor.

    All public methods are static; state (CF API client) is passed in or
    created on demand.
    """

    # ------------------------------------------------------------------
    # 1. Main entry point: calculate_expected_time
    # ------------------------------------------------------------------

    @staticmethod
    async def calculate_expected_time(
        cf_service: CFApiService,
        problem_id: str,
        problem_rating: int,
        user_rating: int,
    ) -> float:
        """Calculate the expected solve time (in seconds) for a problem.

        Fetches contest submission and rating-change data from Codeforces,
        computes focused times per rating bucket, and returns the median
        focused time for the user's bucket.

        Falls back to a simple formula when contest data is unavailable.

        Parameters
        ----------
        cf_service:
            The CF API service instance (for rate limiting and caching).
        problem_id:
            The problem identifier (e.g. ``"1920A"``).
        problem_rating:
            The problem's difficulty rating.
        user_rating:
            The user's current Elo rating.

        Returns
        -------
        float
            Expected solve time in **seconds**.
        """
        contest_id = _extract_contest_id(problem_id)
        if contest_id is None:
            logger.debug("Cannot extract contestId from problem_id=%s, using fallback", problem_id)
            return TimeFactorService._fallback_expected_time(problem_rating, user_rating)

        try:
            submissions = await TimeFactorService._fetch_contest_submissions(cf_service, contest_id)
            rating_changes = await TimeFactorService._fetch_rating_changes(cf_service, contest_id)
        except Exception:
            logger.warning(
                "CF API error for contest %d, using fallback expected time",
                contest_id,
                exc_info=True,
            )
            return TimeFactorService._fallback_expected_time(problem_rating, user_rating)

        if not submissions or not rating_changes:
            logger.debug("No contest data for contest %d, using fallback", contest_id)
            return TimeFactorService._fallback_expected_time(problem_rating, user_rating)

        # Parse the problem index from problem_id (the letter suffix)
        index = problem_id[re.match(r"\d+", problem_id).end():] if re.match(r"\d+", problem_id) else ""

        bucket_data = TimeFactorService._calculate_focused_times(
            submissions, rating_changes, index,
        )

        if not bucket_data:
            logger.debug("No focused time data for contest %d problem %s", contest_id, index)
            return TimeFactorService._fallback_expected_time(problem_rating, user_rating)

        # Find the user's bucket and get the median
        user_bucket = _rating_bucket(user_rating)
        expected = TimeFactorService._get_bucket_median(bucket_data, user_bucket)

        if expected is not None:
            return expected

        # Fallback if no data in the user's bucket even after expansion
        return TimeFactorService._fallback_expected_time(problem_rating, user_rating)

    # ------------------------------------------------------------------
    # 2. CF API data fetchers
    # ------------------------------------------------------------------

    @staticmethod
    async def _fetch_contest_submissions(
        cf_service: CFApiService,
        contest_id: int,
    ) -> list[dict[str, Any]]:
        """Fetch all submissions for a contest via CF API ``contest.status``.

        Returns a list of submission dicts as returned by the CF API.
        """
        return await cf_service.get_contest_status(contest_id)

    @staticmethod
    async def _fetch_rating_changes(
        cf_service: CFApiService,
        contest_id: int,
    ) -> dict[str, int]:
        """Fetch rating changes for a contest and return a handle-to-rating map.

        Calls CF API ``contest.ratingChanges`` and returns
        ``{handle: old_rating}``.

        Returns an empty dict if the API call fails or returns no data.
        """
        try:
            changes = await cf_service.get_contest_rating_changes(contest_id)
        except Exception:
            logger.warning("Failed to fetch rating changes for contest %d", contest_id, exc_info=True)
            return {}

        if not changes:
            return {}

        return {entry.get("handle", ""): entry.get("oldRating", 0) for entry in changes if entry.get("handle")}

    # ------------------------------------------------------------------
    # 3. Focused time calculation
    # ------------------------------------------------------------------

    @staticmethod
    def _calculate_focused_times(
        submissions: list[dict[str, Any]],
        rating_changes: dict[str, int],
        problem_index: str,
    ) -> dict[int, list[float]]:
        """Calculate focused times per rating bucket for a specific problem.

        **Algorithm**:

        1. Filter submissions to only accepted (AC) ones.
        2. Group AC submissions by author handle.
        3. For each author, sort their AC submissions by ``relativeTimeSeconds``.
        4. Walk the sorted list and only keep sequential solves (AC times
           strictly increasing).  Compute focused time for each problem:
           ``focused_time(C) = AC_time(C) - AC_time(prev)``, with the first
           problem's focused time being ``AC_time(first)``.
        5. Look up each author's rating from *rating_changes* and place their
           focused time into the corresponding 200-point bucket.

        Parameters
        ----------
        submissions:
            List of CF submission dicts.  Each must have at least:
            ``author.members[0].handle``, ``problem.index``,
            ``relativeTimeSeconds``, and ``verdict``.
        rating_changes:
            Mapping of ``{handle: old_rating}``.
        problem_index:
            The problem index to compute focused times for (e.g. ``"C"``).

        Returns
        -------
        dict[int, list[float]]
            ``{bucket_lower_bound: [focused_times_in_seconds]}``
        """
        # Group AC submissions by author
        author_acs: dict[str, list[tuple[str, int]]] = {}  # handle -> [(index, relTime)]

        for sub in submissions:
            if sub.get("verdict") != "OK":
                continue
            problem = sub.get("problem", {})
            idx = problem.get("index", "")
            rel_time = sub.get("relativeTimeSeconds")
            if rel_time is None:
                continue

            # Extract author handle
            author = sub.get("author", {})
            members = author.get("members", [])
            if not members:
                continue
            handle = members[0].get("handle", "")
            if not handle:
                continue

            author_acs.setdefault(handle, []).append((idx, rel_time))

        # Compute focused times for the target problem index
        bucket_data: dict[int, list[float]] = {}

        for handle, acs in author_acs.items():
            # Sort by relative time
            acs.sort(key=lambda x: x[1])

            # Build sequential-only sequence (time-ascending AND index-ascending)
            # Skip data where a later-indexed problem was solved before an
            # earlier-indexed one (e.g. solved C then B — B is "jump-back").
            sequential: list[tuple[str, int]] = []
            last_time = -1
            last_index = ""
            for idx, rel_time in acs:
                if rel_time > last_time and idx >= last_index:
                    sequential.append((idx, rel_time))
                    last_time = rel_time
                    last_index = idx

            # Find the focused time for the target problem index
            focused_time: float | None = None
            for i, (idx, rel_time) in enumerate(sequential):
                if idx == problem_index:
                    focused_time = float(rel_time) if i == 0 else float(rel_time - sequential[i - 1][1])
                    break

            if focused_time is None or focused_time <= 0:
                continue

            # Look up author's rating
            rating = rating_changes.get(handle)
            if rating is None or rating <= 0:
                continue

            bucket = _rating_bucket(rating)
            bucket_data.setdefault(bucket, []).append(focused_time)

        return bucket_data

    # ------------------------------------------------------------------
    # 4. Bucket median with expansion
    # ------------------------------------------------------------------

    @staticmethod
    def _get_bucket_median(
        bucket_data: dict[int, list[float]],
        target_bucket: int,
    ) -> float | None:
        """Get the median focused time for a bucket, with expansion if needed.

        If the target bucket has fewer than ``MIN_BUCKET_SIZE`` data points,
        adjacent buckets are merged (alternating left/right) until the
        threshold is met or no more buckets are available.

        Parameters
        ----------
        bucket_data:
            ``{bucket_lower_bound: [focused_times]}``
        target_bucket:
            The lower bound of the user's rating bucket.

        Returns
        -------
        float | None
            Median focused time in seconds, or ``None`` if no data at all.
        """
        if not bucket_data:
            return None

        # Try the exact bucket first
        times = bucket_data.get(target_bucket, [])
        if len(times) >= MIN_BUCKET_SIZE:
            return _median(times)

        # Expand to adjacent buckets
        all_sorted_buckets = sorted(bucket_data.keys())
        merged: list[float] = list(times)

        # Alternating expansion: +1, -1, +2, -2, ...
        offset = 1
        available = set(all_sorted_buckets) - {target_bucket}

        while len(merged) < MIN_BUCKET_SIZE and available:
            for sign in (1, -1):
                candidate = target_bucket + sign * offset * BUCKET_SIZE
                if candidate in available:
                    merged.extend(bucket_data[candidate])
                    available.discard(candidate)
                if len(merged) >= MIN_BUCKET_SIZE:
                    break
            offset += 1

        if not merged:
            return None

        return _median(merged)

    # ------------------------------------------------------------------
    # 5. Fallback expected time
    # ------------------------------------------------------------------

    @staticmethod
    def _fallback_expected_time(problem_rating: int, user_rating: int) -> float:
        """Compute a simple fallback expected time when no contest data exists.

        Formula::

            T_expected = 10 + (problem_rating - 800) / 50   (minutes)

        Adjusted by rating difference::

            adjustment = (user_rating - problem_rating) / 200
            T_expected *= max(0.5, min(2.0, 1.0 - adjustment * 0.1))

        Returns the value in **seconds**.
        """
        base_minutes = 10.0 + (problem_rating - 800) / 50.0
        base_minutes = max(1.0, base_minutes)  # at least 1 minute

        # Adjust based on rating gap: stronger users solve faster
        rating_diff = user_rating - problem_rating
        adjustment = rating_diff / 200.0
        multiplier = max(0.5, min(2.0, 1.0 - adjustment * 0.1))
        expected_minutes = base_minutes * multiplier
        expected_minutes = max(1.0, expected_minutes)

        return expected_minutes * SECONDS_PER_MINUTE

    # ------------------------------------------------------------------
    # 6. Time factor calculation
    # ------------------------------------------------------------------

    @staticmethod
    def compute_effective_time(
        solve_time_seconds: float,
        wa_count: int,
    ) -> float:
        """Compute effective time including WA penalty.

        penalty is 20 minutes per WA/TLE/RE/MLE (requirement 3.6.2).
        """
        return solve_time_seconds + wa_count * 20 * 60

    @staticmethod
    def calculate_time_factor(
        effective_time: float | None,
        expected_time: float,
        s_value: float,
    ) -> float:
        """Calculate the time factor for PP/Elo weighting.

        ``time_factor = T_expected / max(T_effective, T_expected)``

        The result is clamped to ``[0.5, 1.5]``.

        When ``s_value == 0`` (not solved), returns ``1.0`` (neutral factor).

        Parameters
        ----------
        effective_time:
            The user's actual time spent on the problem in **seconds**.
            ``None`` means no time data is available; treated as equal to
            expected_time (factor = 1.0).
        expected_time:
            The expected time for this problem/user in **seconds**.
        s_value:
            The S-value (0.0 = not solved, >0 = solved with quality measure).

        Returns
        -------
        float
            Time factor in ``[0.5, 1.5]``.
        """
        if s_value == 0.0:
            return 1.0

        if expected_time <= 0:
            return 1.0

        t_eff = effective_time if effective_time is not None else expected_time

        if t_eff <= 0:
            return 1.0

        raw_factor = expected_time / t_eff

        return max(TIME_FACTOR_MIN, min(TIME_FACTOR_MAX, raw_factor))
