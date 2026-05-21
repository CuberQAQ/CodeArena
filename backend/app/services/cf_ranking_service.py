"""CF global ranking regression pipeline.

Provides:
- Stratified sampling of CF users by rating bucket
- Equivalent PP calculation using the project PP formula
- Polynomial regression (pure-Python) from CF rating to PP
- Noise injection for estimated PP values
- Interrupt-resumable batch processing

The pipeline is designed to run as a long-lived background task managed
by an admin API endpoint.  Progress is tracked in-memory so that callers
can poll for status.
"""

import json
import logging
import random
from collections import defaultdict
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cf_sample_user import CFSampleUser
from app.services.cf_api_service import CFApiService, CFNetworkError, CFNotFoundError
from app.services.pp_service import PPService

logger = logging.getLogger("code_arena.cf_ranking")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BUCKET_SIZE = 200        # rating bucket width
SAMPLES_PER_BUCKET = 100  # target samples per bucket
DEFAULT_DEGREE = 2        # polynomial regression degree
NOISE_MAG_MIN = 0.005      # 0.5 % minimum noise magnitude
NOISE_MAG_MAX = 0.02       # 2 % maximum noise magnitude
DEFAULT_TIME_MINUTES = 30.0  # default time approximation for CF submissions


# ---------------------------------------------------------------------------
# In-memory pipeline state (module-level singleton)
# ---------------------------------------------------------------------------

class PipelineState:
    """Tracks the running state of the sampling pipeline."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.running: bool = False
        self.phase: str = "idle"
        self.progress: int = 0
        self.total: int = 0
        self.batch: int = 0
        self.error: str | None = None
        self.coefficients: list[float] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "running": self.running,
            "phase": self.phase,
            "progress": self.progress,
            "total": self.total,
            "batch": self.batch,
            "error": self.error,
            "coefficients": self.coefficients,
        }


_pipeline_state = PipelineState()


def get_pipeline_state() -> PipelineState:
    """Return the global pipeline state singleton."""
    return _pipeline_state


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _bucket_for_rating(rating: int) -> int:
    """Return the lower bound of the 200-wide rating bucket."""
    return (rating // BUCKET_SIZE) * BUCKET_SIZE


def _stratified_sample(rated_list: list[dict], samples_per_bucket: int = SAMPLES_PER_BUCKET) -> list[dict]:
    """Select ~*samples_per_bucket* users from each 200-rating bucket.

    Parameters
    ----------
    rated_list :
        List of dicts, each having at least ``handle`` and ``rating``.
    samples_per_bucket :
        Target number of samples per bucket.

    Returns
    -------
    list[dict]
        Stratified sample.
    """
    buckets: dict[int, list[dict]] = defaultdict(list)
    for user in rated_list:
        bucket = _bucket_for_rating(user["rating"])
        buckets[bucket].append(user)

    sampled: list[dict] = []
    for bucket_key in sorted(buckets.keys()):
        users_in_bucket = buckets[bucket_key]
        # Cap at samples_per_bucket; if fewer, take all
        count = min(samples_per_bucket, len(users_in_bucket))
        sampled.extend(random.sample(users_in_bucket, count))

    return sampled


# ---------------------------------------------------------------------------
# Equivalent PP calculation
# ---------------------------------------------------------------------------


async def _calculate_equivalent_pp(
    handle: str,
    cf_api: CFApiService,
) -> float:
    """Calculate equivalent PP for a CF user by replaying their submissions.

    Pulls the user's submission history, filters for accepted (AC) verdicts,
    computes base_pp x performance_factor per problem, then aggregates with
    0.95 decay.

    Approximations (CF does not provide full session data):
    - WA count = number of non-OK verdicts on the same problem before first AC.
    - Time spent = fixed 30 minutes per problem (CF has no per-problem timer).
    """
    try:
        submissions = await cf_api.get_user_status(handle, count=1000)
    except (CFNetworkError, CFNotFoundError) as exc:
        logger.warning("Failed to fetch submissions for %s: %s", handle, exc)
        return 0.0

    if not submissions:
        return 0.0

    # Group submissions by problem (contestId + index)
    problem_submissions: dict[str, list[dict]] = defaultdict(list)
    for sub in submissions:
        problem = sub.get("problem", {})
        contest_id = problem.get("contestId")
        index = problem.get("index")
        if contest_id is None or index is None:
            continue
        problem_key = f"{contest_id}{index}"
        problem_submissions[problem_key].append(sub)

    # Per-problem PP calculation
    problem_pps: list[float] = []
    for _problem_key, subs in problem_submissions.items():
        # Find first AC and count WAs before it
        first_ac: dict | None = None
        wa_count = 0
        first_submission_time = None
        first_ac_time = None

        # Sort by submission time (creationTimeSeconds)
        sorted_subs = sorted(subs, key=lambda s: s.get("creationTimeSeconds", 0))

        for sub in sorted_subs:
            verdict = sub.get("verdict")
            if first_submission_time is None:
                first_submission_time = sub.get("creationTimeSeconds")

            if verdict == "OK":
                first_ac = sub
                first_ac_time = sub.get("creationTimeSeconds")
                break
            elif verdict is not None:
                # Count non-OK verdicts as WAs (WA, TLE, RE, MLE, etc.)
                wa_count += 1

        if first_ac is None:
            continue

        problem = first_ac.get("problem", {})
        problem_rating = problem.get("rating")
        if problem_rating is None or problem_rating < 800:
            continue

        # Time approximation: if we have timestamps, use the difference;
        # otherwise default to DEFAULT_TIME_MINUTES
        time_spent = DEFAULT_TIME_MINUTES
        if first_submission_time and first_ac_time:
            time_diff_minutes = (first_ac_time - first_submission_time) / 60.0
            if time_diff_minutes > 0:
                time_spent = time_diff_minutes

        base_pp = PPService.calculate_base_pp(problem_rating)
        perf_factor = PPService.calculate_performance_factor(wa_count, time_spent)
        problem_pps.append(base_pp * perf_factor)

    # Sort descending and aggregate
    problem_pps.sort(reverse=True)
    return PPService.aggregate_total_pp(problem_pps)


# ---------------------------------------------------------------------------
# Polynomial regression (pure Python)
# ---------------------------------------------------------------------------


def _fit_polynomial(xs: list[float], ys: list[float], degree: int = DEFAULT_DEGREE) -> list[float]:
    """Fit a polynomial of *degree* to (x, y) data using least-squares.

    Solves the normal equations via Gaussian elimination.  Returns the
    coefficients [a0, a1, ..., ad] where p(x) = a0 + a1*x + ... + ad*x^d.

    No external dependencies (numpy/scipy) required.
    """
    n = degree + 1  # number of coefficients

    # Build Vandermonde-like moment matrix X^T X and vector X^T y
    # X_ij = sum_k x_k^(i+j)
    # Right-hand side: sum_k x_k^i * y_k
    mat = [[0.0] * n for _ in range(n)]
    rhs = [0.0] * n

    for x, y in zip(xs, ys, strict=True):
        powers = [x ** p for p in range(2 * n - 1)]  # x^0 .. x^(2n-2)
        y_powers = [y * (x ** p) for p in range(n)]
        for i in range(n):
            for j in range(n):
                mat[i][j] += powers[i + j]
            rhs[i] += y_powers[i]

    # Gaussian elimination with partial pivoting
    for col in range(n):
        # Find pivot
        max_row = col
        max_val = abs(mat[col][col])
        for row in range(col + 1, n):
            if abs(mat[row][col]) > max_val:
                max_val = abs(mat[row][col])
                max_row = row
        mat[col], mat[max_row] = mat[max_row], mat[col]
        rhs[col], rhs[max_row] = rhs[max_row], rhs[col]

        pivot = mat[col][col]
        if abs(pivot) < 1e-12:
            # Singular matrix -- fall back to linear fit
            if degree > 1:
                return _fit_polynomial(xs, ys, degree=1)
            return [sum(ys) / len(ys) if ys else 0.0]

        for row in range(col + 1, n):
            factor = mat[row][col] / pivot
            for j in range(col, n):
                mat[row][j] -= factor * mat[col][j]
            rhs[row] -= factor * rhs[col]

    # Back-substitution
    coeffs = [0.0] * n
    for i in range(n - 1, -1, -1):
        s = rhs[i]
        for j in range(i + 1, n):
            s -= mat[i][j] * coeffs[j]
        coeffs[i] = s / mat[i][i]

    return coeffs


def _evaluate_polynomial(coeffs: list[float], x: float) -> float:
    """Evaluate polynomial with Horner's method."""
    result = 0.0
    for c in reversed(coeffs):
        result = result * x + c
    return result


def _estimate_pp(cf_rating: float, coefficients: list[float]) -> float:
    """Return estimated PP from regression + noise.

    Adds random noise with magnitude in [0.5%, 2%], sign random.
    """
    regression_pp = _evaluate_polynomial(coefficients, cf_rating)
    magnitude = random.uniform(NOISE_MAG_MIN, NOISE_MAG_MAX)
    sign = random.choice([-1, 1])
    return round(regression_pp * (1.0 + sign * magnitude), 2)


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------


async def run_sampling_pipeline(
    db: AsyncSession,
    cf_api: CFApiService | None = None,
) -> dict[str, Any]:
    """Execute the full CF sampling and regression pipeline.

    Steps:
    1. Fetch all rated CF users
    2. Stratified sample by rating bucket
    3. Calculate equivalent PP for each sample (resumable)
    4. Fit polynomial regression model
    5. Apply regression + noise to estimate PP for all samples

    Supports interrupt-resume: already-processed handles in the current
    batch are skipped on re-run.

    Returns a summary dict.
    """
    state = _pipeline_state
    if state.running:
        return {"error": "Pipeline already running", "state": state.to_dict()}

    if cf_api is None:
        cf_api = CFApiService()

    state.reset()
    state.running = True
    state.phase = "fetching_rated_list"

    try:
        # --- Step 1: Fetch rated list ---
        logger.info("Fetching CF rated user list...")
        rated_list = await _fetch_rated_list(cf_api)
        if not rated_list:
            state.running = False
            state.phase = "failed"
            state.error = "No rated users returned from CF API"
            return {"error": state.error, "state": state.to_dict()}

        # --- Step 2: Determine batch number (resume incomplete batch or start new) ---
        max_batch_result = await db.execute(
            select(func.coalesce(func.max(CFSampleUser.sample_batch), 0))
        )
        max_batch = max_batch_result.scalar_one()

        # Check for incomplete batch: has records but no regression coefficients
        incomplete_result = await db.execute(
            select(CFSampleUser.sample_batch)
            .where(CFSampleUser.sample_batch == max_batch)
            .where(CFSampleUser.regression_coefficients.is_(None))
            .limit(1)
        )
        incomplete_row = incomplete_result.first()
        if max_batch > 0 and incomplete_row is not None:
            current_batch = max_batch  # Resume incomplete batch
            logger.info("Resuming incomplete batch %d", current_batch)
        else:
            current_batch = max_batch + 1  # Start new batch
        state.batch = current_batch

        # --- Step 3: Stratified sample ---
        state.phase = "stratified_sampling"
        sampled_users = _stratified_sample(rated_list)
        state.total = len(sampled_users)
        num_buckets = len(set(_bucket_for_rating(u["rating"]) for u in sampled_users))
        logger.info("Sampled %d users across %d buckets", state.total, num_buckets)

        # --- Step 4: Check for already-processed handles in this batch (resume support) ---
        existing_result = await db.execute(
            select(CFSampleUser.cf_handle).where(
                CFSampleUser.sample_batch == current_batch
            )
        )
        processed_handles = {row[0] for row in existing_result.all()}

        # --- Step 5: Calculate equivalent PP for each sample ---
        state.phase = "calculating_pp"
        for i, user_info in enumerate(sampled_users):
            handle = user_info["handle"]
            cf_rating = user_info["rating"]
            country = user_info.get("country")

            if handle in processed_handles:
                state.progress = i + 1
                continue

            equivalent_pp = await _calculate_equivalent_pp(handle, cf_api)

            sample_record = CFSampleUser(
                cf_handle=handle,
                cf_rating=cf_rating,
                country=country,
                equivalent_pp=equivalent_pp,
                sample_batch=current_batch,
            )
            db.add(sample_record)
            state.progress = i + 1

            # Commit every 50 users to support resume
            if (i + 1) % 50 == 0:
                await db.flush()
                await db.commit()
                logger.info("Processed %d/%d users", i + 1, state.total)

        # Final flush for remaining records
        await db.flush()
        await db.commit()

        # --- Step 6: Fit regression model ---
        state.phase = "fitting_regression"
        samples_result = await db.execute(
            select(CFSampleUser.cf_rating, CFSampleUser.equivalent_pp).where(
                CFSampleUser.sample_batch == current_batch,
                CFSampleUser.equivalent_pp.isnot(None),
                CFSampleUser.equivalent_pp > 0,
            )
        )
        data_points = [(r, pp) for r, pp in samples_result.all()]

        if len(data_points) < 3:
            state.running = False
            state.phase = "failed"
            state.error = f"Not enough data points for regression ({len(data_points)})"
            return {"error": state.error, "state": state.to_dict()}

        xs = [float(r) for r, _pp in data_points]
        ys = [float(pp) for _r, pp in data_points]
        coefficients = _fit_polynomial(xs, ys, degree=DEFAULT_DEGREE)
        state.coefficients = coefficients

        coeffs_json = json.dumps(coefficients)

        # --- Step 7: Apply regression + noise to all samples ---
        state.phase = "estimating_pp"
        all_samples_result = await db.execute(
            select(CFSampleUser).where(
                CFSampleUser.sample_batch == current_batch,
            )
        )
        all_samples = all_samples_result.scalars().all()

        for sample in all_samples:
            est_pp = _estimate_pp(float(sample.cf_rating), coefficients)
            sample.estimated_pp = est_pp
            sample.regression_coefficients = coeffs_json

        await db.flush()
        await db.commit()

        # --- Done ---
        state.phase = "completed"
        state.running = False
        logger.info(
            "Pipeline completed. Batch %d, %d samples, coefficients=%s",
            current_batch,
            len(all_samples),
            coefficients,
        )

        return {
            "batch": current_batch,
            "total_samples": len(all_samples),
            "data_points_used": len(data_points),
            "coefficients": coefficients,
            "state": state.to_dict(),
        }

    except Exception as exc:
        state.running = False
        state.phase = "failed"
        state.error = str(exc)
        logger.exception("Pipeline failed: %s", exc)
        return {"error": str(exc), "state": state.to_dict()}


async def _fetch_rated_list(cf_api: CFApiService) -> list[dict]:
    """Fetch the list of all rated CF users.

    Uses the CF API ``user.ratedList`` endpoint which returns users who
    have participated in at least one rated contest.
    """
    try:
        result = await cf_api._request(
            "/user.ratedList",
            params={"active": "true"},
            ttl=3600,  # cache for 1 hour -- this is a heavy request
        )
        if not result:
            return []
        return result
    except Exception as exc:
        logger.error("Failed to fetch rated list: %s", exc)
        raise


async def get_regression_model(db: AsyncSession) -> dict[str, Any] | None:
    """Return the latest regression model coefficients.

    Looks up the most recent batch that has regression coefficients stored.
    """
    # Get max batch first
    max_batch = await db.scalar(
        select(func.max(CFSampleUser.sample_batch))
    )
    if max_batch is None:
        return None

    result = await db.execute(
        select(CFSampleUser.regression_coefficients)
        .where(
            CFSampleUser.sample_batch == max_batch,
            CFSampleUser.regression_coefficients.isnot(None),
        )
        .limit(1)
    )
    row = result.scalar_one_or_none()
    if row is None:
        return None
    return {"coefficients": json.loads(row)}


async def estimate_pp_for_rating(db: AsyncSession, cf_rating: int) -> float | None:
    """Estimate PP for a given CF rating using the latest regression model."""
    model = await get_regression_model(db)
    if model is None:
        return None
    coefficients = model["coefficients"]
    return _estimate_pp(float(cf_rating), coefficients)
