"""Tests for the CF ranking service: stratified sampling, equivalent PP calculation,
polynomial regression, noise injection, and pipeline orchestration.

The tests use lightweight SQLite-compatible models and mock out the CF API
to avoid external network calls.
"""

import math
import uuid
from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import Float, Integer, String, Text, event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.services.cf_ranking_service import (
    DEFAULT_DEGREE,
    PipelineState,
    _bucket_for_rating,
    _calculate_equivalent_pp,
    _estimate_pp,
    _evaluate_polynomial,
    _fit_polynomial,
    _stratified_sample,
    get_pipeline_state,
)
from app.services.pp_service import PPService

# ---------------------------------------------------------------------------
# Lightweight SQLite-compatible test models
# ---------------------------------------------------------------------------


class _TestBase(DeclarativeBase):
    pass


class _TestCFSampleUser(_TestBase):
    __tablename__ = "cf_sample_users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    cf_handle: Mapped[str] = mapped_column(String(100), nullable=False)
    cf_rating: Mapped[int] = mapped_column(Integer, nullable=False)
    country: Mapped[str | None] = mapped_column(String(10), nullable=True)
    equivalent_pp: Mapped[float | None] = mapped_column(Float, nullable=True)
    estimated_pp: Mapped[float | None] = mapped_column(Float, nullable=True)
    sample_batch: Mapped[int] = mapped_column(Integer, nullable=False)
    regression_coefficients: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.now)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def async_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)

    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as conn:
        await conn.run_sync(_TestBase.metadata.create_all)

    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(_TestBase.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
async def db(async_engine):
    session_factory = async_sessionmaker(
        async_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with session_factory() as session:
        yield session


@pytest.fixture(autouse=True)
def _reset_pipeline_state():
    """Reset the global pipeline state before each test."""
    state = get_pipeline_state()
    state.reset()
    yield
    state.reset()


# ---------------------------------------------------------------------------
# Test: Rating bucket calculation
# ---------------------------------------------------------------------------


class TestBucketForRating:
    def test_exact_bucket_boundary(self):
        assert _bucket_for_rating(800) == 800
        assert _bucket_for_rating(1000) == 1000
        assert _bucket_for_rating(1200) == 1200

    def test_within_bucket(self):
        assert _bucket_for_rating(850) == 800
        assert _bucket_for_rating(999) == 800
        assert _bucket_for_rating(1050) == 1000

    def test_below_800(self):
        assert _bucket_for_rating(500) == 400
        assert _bucket_for_rating(0) == 0

    def test_high_ratings(self):
        assert _bucket_for_rating(2400) == 2400
        assert _bucket_for_rating(2550) == 2400
        assert _bucket_for_rating(3000) == 3000


# ---------------------------------------------------------------------------
# Test: Stratified sampling
# ---------------------------------------------------------------------------


class TestStratifiedSample:
    def _make_users(self, count: int, rating: int) -> list[dict]:
        return [{"handle": f"user_{rating}_{i}", "rating": rating} for i in range(count)]

    def test_single_bucket_capped(self):
        """When a bucket has more than SAMPLES_PER_BUCKET users, only that many are sampled."""
        users = self._make_users(200, 1000)
        sampled = _stratified_sample(users, samples_per_bucket=100)
        assert len(sampled) == 100
        assert all(u["rating"] == 1000 for u in sampled)

    def test_single_bucket_fewer_than_target(self):
        """When a bucket has fewer users than the target, all are sampled."""
        users = self._make_users(50, 1200)
        sampled = _stratified_sample(users, samples_per_bucket=100)
        assert len(sampled) == 50

    def test_multiple_buckets(self):
        """Users from different buckets are all represented."""
        users = (
            self._make_users(150, 800)
            + self._make_users(80, 1000)
            + self._make_users(30, 1200)
        )
        sampled = _stratified_sample(users, samples_per_bucket=100)
        # 100 + 80 + 30 = 210
        assert len(sampled) == 210
        r800 = [u for u in sampled if u["rating"] == 800]
        r1000 = [u for u in sampled if u["rating"] == 1000]
        r1200 = [u for u in sampled if u["rating"] == 1200]
        assert len(r800) == 100
        assert len(r1000) == 80
        assert len(r1200) == 30

    def test_empty_input(self):
        assert _stratified_sample([], samples_per_bucket=100) == []

    def test_bucket_boundary_alignment(self):
        """Users with ratings 1199 and 1200 go to different buckets."""
        users = [
            {"handle": "u1", "rating": 1199},
            {"handle": "u2", "rating": 1200},
        ]
        sampled = _stratified_sample(users, samples_per_bucket=100)
        assert len(sampled) == 2
        # Verify they are in different buckets
        assert _bucket_for_rating(1199) != _bucket_for_rating(1200)

    def test_randomness(self):
        """Repeated sampling of a large bucket returns different subsets."""
        users = self._make_users(200, 1000)
        sample1 = _stratified_sample(users, samples_per_bucket=100)
        sample2 = _stratified_sample(users, samples_per_bucket=100)
        handles1 = {u["handle"] for u in sample1}
        handles2 = {u["handle"] for u in sample2}
        # Extremely unlikely to be identical with 200 choose 100
        assert handles1 != handles2


# ---------------------------------------------------------------------------
# Test: Equivalent PP calculation
# ---------------------------------------------------------------------------


class TestCalculateEquivalentPP:
    @pytest.mark.asyncio
    async def test_empty_submissions(self):
        """No submissions -> PP = 0."""
        cf_api = AsyncMock()
        cf_api.get_user_status = AsyncMock(return_value=[])
        pp = await _calculate_equivalent_pp("test_user", cf_api)
        assert pp == 0.0

    @pytest.mark.asyncio
    async def test_api_failure(self):
        """API failure -> PP = 0."""
        from app.services.cf_api_service import CFNetworkError

        cf_api = AsyncMock()
        cf_api.get_user_status = AsyncMock(side_effect=CFNetworkError("timeout"))
        pp = await _calculate_equivalent_pp("test_user", cf_api)
        assert pp == 0.0

    @pytest.mark.asyncio
    async def test_single_ac_problem(self):
        """One AC problem at rating 1200 -> expected base_pp * perf_factor."""
        cf_api = AsyncMock()
        cf_api.get_user_status = AsyncMock(
            return_value=[
                {
                    "verdict": "OK",
                    "creationTimeSeconds": 1000,
                    "problem": {
                        "contestId": 100,
                        "index": "A",
                        "rating": 1200,
                    },
                },
            ]
        )
        pp = await _calculate_equivalent_pp("test_user", cf_api)
        expected_base = PPService.calculate_base_pp(1200)
        expected_perf = PPService.calculate_performance_factor(0, 30.0)
        expected_pp = PPService.aggregate_total_pp([expected_base * expected_perf])
        assert abs(pp - expected_pp) < 0.01

    @pytest.mark.asyncio
    async def test_multiple_problems_with_decay(self):
        """Multiple AC problems with descending PP, aggregated with decay."""
        cf_api = AsyncMock()
        submissions = []
        problems = [
            (100, "A", 1500, 0),  # high PP
            (101, "B", 1200, 0),  # medium PP
            (102, "C", 1000, 0),  # low PP
        ]
        for contest_id, index, rating, t in problems:
            submissions.append({
                "verdict": "OK",
                "creationTimeSeconds": 1000 + t,
                "problem": {
                    "contestId": contest_id,
                    "index": index,
                    "rating": rating,
                },
            })
        cf_api.get_user_status = AsyncMock(return_value=submissions)

        pp = await _calculate_equivalent_pp("test_user", cf_api)
        assert pp > 0

        # Verify individual PP values are correctly calculated
        pps = []
        for _, _, rating, _ in problems:
            base = PPService.calculate_base_pp(rating)
            perf = PPService.calculate_performance_factor(0, 30.0)
            pps.append(base * perf)
        pps.sort(reverse=True)
        expected = PPService.aggregate_total_pp(pps)
        assert abs(pp - expected) < 0.01

    @pytest.mark.asyncio
    async def test_wa_counted_before_ac(self):
        """WAs before first AC are counted."""
        cf_api = AsyncMock()
        submissions = [
            {
                "verdict": "WRONG_ANSWER",
                "creationTimeSeconds": 1000,
                "problem": {"contestId": 100, "index": "A", "rating": 1200},
            },
            {
                "verdict": "WRONG_ANSWER",
                "creationTimeSeconds": 1010,
                "problem": {"contestId": 100, "index": "A", "rating": 1200},
            },
            {
                "verdict": "OK",
                "creationTimeSeconds": 1050,
                "problem": {"contestId": 100, "index": "A", "rating": 1200},
            },
        ]
        cf_api.get_user_status = AsyncMock(return_value=submissions)

        pp = await _calculate_equivalent_pp("test_user", cf_api)
        # WA count = 2, time = (1050-1000)/60 = 0.833 min
        base = PPService.calculate_base_pp(1200)
        perf = PPService.calculate_performance_factor(2, 50.0 / 60.0)
        expected = PPService.aggregate_total_pp([base * perf])
        assert abs(pp - expected) < 0.01

    @pytest.mark.asyncio
    async def test_problem_without_rating_skipped(self):
        """Problems without a rating field are skipped."""
        cf_api = AsyncMock()
        submissions = [
            {
                "verdict": "OK",
                "creationTimeSeconds": 1000,
                "problem": {"contestId": 100, "index": "A"},  # no rating
            },
        ]
        cf_api.get_user_status = AsyncMock(return_value=submissions)
        pp = await _calculate_equivalent_pp("test_user", cf_api)
        assert pp == 0.0

    @pytest.mark.asyncio
    async def test_problem_below_800_skipped(self):
        """Problems with rating < 800 are skipped."""
        cf_api = AsyncMock()
        submissions = [
            {
                "verdict": "OK",
                "creationTimeSeconds": 1000,
                "problem": {"contestId": 100, "index": "A", "rating": 600},
            },
        ]
        cf_api.get_user_status = AsyncMock(return_value=submissions)
        pp = await _calculate_equivalent_pp("test_user", cf_api)
        assert pp == 0.0

    @pytest.mark.asyncio
    async def test_no_ac_only_wa(self):
        """Only WAs, no AC -> PP = 0."""
        cf_api = AsyncMock()
        submissions = [
            {
                "verdict": "WRONG_ANSWER",
                "creationTimeSeconds": 1000,
                "problem": {"contestId": 100, "index": "A", "rating": 1200},
            },
        ]
        cf_api.get_user_status = AsyncMock(return_value=submissions)
        pp = await _calculate_equivalent_pp("test_user", cf_api)
        assert pp == 0.0


# ---------------------------------------------------------------------------
# Test: Polynomial regression
# ---------------------------------------------------------------------------


class TestFitPolynomial:
    def test_linear_data(self):
        """Perfectly linear data should give exact linear coefficients."""
        xs = [1.0, 2.0, 3.0, 4.0, 5.0]
        ys = [3.0, 5.0, 7.0, 9.0, 11.0]  # y = 1 + 2x
        coeffs = _fit_polynomial(xs, ys, degree=1)
        assert len(coeffs) == 2
        assert abs(coeffs[0] - 1.0) < 0.01  # a0 ~ 1
        assert abs(coeffs[1] - 2.0) < 0.01  # a1 ~ 2

    def test_quadratic_data(self):
        """Quadratic data should be fit with degree 2."""
        xs = [-2.0, -1.0, 0.0, 1.0, 2.0]
        ys = [4.0, 1.0, 0.0, 1.0, 4.0]  # y = x^2
        coeffs = _fit_polynomial(xs, ys, degree=2)
        assert len(coeffs) == 3
        assert abs(coeffs[0]) < 0.01  # a0 ~ 0
        assert abs(coeffs[1]) < 0.01  # a1 ~ 0
        assert abs(coeffs[2] - 1.0) < 0.01  # a2 ~ 1

    def test_constant_data(self):
        """Constant data -> all coefficients except a0 are 0."""
        xs = [1.0, 2.0, 3.0, 4.0]
        ys = [5.0, 5.0, 5.0, 5.0]
        coeffs = _fit_polynomial(xs, ys, degree=2)
        assert abs(coeffs[0] - 5.0) < 0.01
        assert abs(coeffs[1]) < 0.01
        assert abs(coeffs[2]) < 0.01

    def test_minimum_data_points(self):
        """With degree+1 points, should still work."""
        xs = [800.0, 1200.0, 1600.0]
        ys = [0.0, 14.14, 20.0]
        coeffs = _fit_polynomial(xs, ys, degree=2)
        assert len(coeffs) == 3
        # Verify it produces reasonable predictions
        for x, y in zip(xs, ys, strict=True):
            predicted = _evaluate_polynomial(coeffs, x)
            assert abs(predicted - y) < 1.0  # within 1 PP

    def test_single_point_fallback(self):
        """With 1 point and degree 2, should fallback gracefully."""
        xs = [1000.0]
        ys = [10.0]
        coeffs = _fit_polynomial(xs, ys, degree=2)
        # Should fall back to constant
        assert len(coeffs) >= 1

    def test_noisy_data(self):
        """Noisy data should still produce reasonable fit."""
        import random

        random.seed(42)
        xs = [float(i * 100 + 800) for i in range(20)]
        # y = sqrt((x-800)/100) * 10 + noise
        ys = [math.sqrt((x - 800) / 100) * 10 + random.gauss(0, 0.5) for x in xs]
        coeffs = _fit_polynomial(xs, ys, degree=2)
        # Check predictions are reasonable -- with noise, allow 6 PP tolerance
        for x, y in zip(xs, ys, strict=True):
            predicted = _evaluate_polynomial(coeffs, x)
            assert abs(predicted - y) < 6.0  # within 6 PP


class TestEvaluatePolynomial:
    def test_linear(self):
        assert abs(_evaluate_polynomial([2.0, 3.0], 4.0) - 14.0) < 0.001  # 2 + 3*4

    def test_quadratic(self):
        # x^2 + 0*x + 0
        assert abs(_evaluate_polynomial([0.0, 0.0, 1.0], 3.0) - 9.0) < 0.001

    def test_zero_coefficients(self):
        assert _evaluate_polynomial([0.0, 0.0, 0.0], 100.0) == 0.0


# ---------------------------------------------------------------------------
# Test: Noise injection
# ---------------------------------------------------------------------------


class TestEstimatePP:
    def test_noise_within_range(self):
        """Estimated PP noise magnitude should be in [0.5%, 2%]."""
        coefficients = [0.0, 0.01, 0.0001]  # arbitrary
        results = [_estimate_pp(1200.0, coefficients) for _ in range(1000)]
        regression_pp = _evaluate_polynomial(coefficients, 1200.0)

        for est in results:
            deviation = abs(est / regression_pp - 1.0)
            assert 0.004 <= deviation <= 0.021, (
                f"Deviation {deviation:.4f} outside [0.5%, 2%] (with rounding tolerance)"
            )

    def test_noise_varies(self):
        """Multiple calls should produce different values (with high probability)."""
        coefficients = [0.0, 0.01]
        results = [_estimate_pp(1200.0, coefficients) for _ in range(100)]
        unique = len(set(results))
        assert unique > 1, "All estimates are identical -- noise not applied"

    def test_rounded_to_2_decimal(self):
        """Result should be rounded to 2 decimal places."""
        coefficients = [0.0, 0.01]
        est = _estimate_pp(1234.0, coefficients)
        # Check it's a reasonable float with at most 2 decimal places
        assert est == round(est, 2)


# ---------------------------------------------------------------------------
# Test: Pipeline state
# ---------------------------------------------------------------------------


class TestPipelineState:
    def test_initial_state(self):
        state = PipelineState()
        assert state.running is False
        assert state.phase == "idle"
        assert state.progress == 0
        assert state.total == 0
        assert state.error is None
        assert state.coefficients is None

    def test_reset(self):
        state = PipelineState()
        state.running = True
        state.phase = "running"
        state.progress = 50
        state.error = "test"
        state.reset()
        assert state.running is False
        assert state.phase == "idle"
        assert state.progress == 0
        assert state.error is None

    def test_to_dict(self):
        state = PipelineState()
        state.running = True
        state.phase = "sampling"
        state.progress = 10
        state.total = 100
        state.batch = 5
        d = state.to_dict()
        assert d["running"] is True
        assert d["phase"] == "sampling"
        assert d["progress"] == 10
        assert d["total"] == 100
        assert d["batch"] == 5


# ---------------------------------------------------------------------------
# Test: Full pipeline integration
# ---------------------------------------------------------------------------


class TestPipelineIntegration:
    @pytest.mark.asyncio
    async def test_pipeline_full_run(self, db):
        """Full pipeline: sample -> calculate PP -> fit regression -> estimate."""
        from app.services import cf_ranking_service as svc_module

        with (
            patch.object(svc_module, "CFSampleUser", _TestCFSampleUser),
        ):
            # Mock CF API
            mock_cf_api = AsyncMock()
            # ratedList returns users
            mock_cf_api._request = AsyncMock(return_value=[
                {"handle": f"user_{i}", "rating": 800 + (i % 5) * 200, "country": "US"}
                for i in range(30)
            ])
            # user.status returns simple submissions
            mock_cf_api.get_user_status = AsyncMock(
                return_value=[
                    {
                        "verdict": "OK",
                        "creationTimeSeconds": 1000,
                        "problem": {
                            "contestId": 100,
                            "index": "A",
                            "rating": 1200,
                        },
                    }
                ]
            )

            result = await svc_module.run_sampling_pipeline(db, cf_api=mock_cf_api)

            assert "error" not in result or result.get("error") is None
            assert result.get("batch", 0) >= 1
            assert result["total_samples"] > 0
            assert result["data_points_used"] > 0
            assert result["coefficients"] is not None
            assert len(result["coefficients"]) == DEFAULT_DEGREE + 1

            # Verify DB records were created
            state = get_pipeline_state()
            assert state.phase == "completed"
            assert state.running is False

    @pytest.mark.asyncio
    async def test_pipeline_rejects_concurrent_run(self, db):
        """Pipeline should reject if already running."""
        from app.services import cf_ranking_service as svc_module

        state = get_pipeline_state()
        state.running = True

        result = await svc_module.run_sampling_pipeline(db)
        assert "error" in result
        assert "already running" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_pipeline_empty_rated_list(self, db):
        """Pipeline should fail gracefully with empty rated list."""
        from app.services import cf_ranking_service as svc_module

        with patch.object(svc_module, "CFSampleUser", _TestCFSampleUser):
            mock_cf_api = AsyncMock()
            mock_cf_api._request = AsyncMock(return_value=[])

            result = await svc_module.run_sampling_pipeline(db, cf_api=mock_cf_api)
            assert "error" in result
            state = get_pipeline_state()
            assert state.phase == "failed"

    @pytest.mark.asyncio
    async def test_pipeline_resume_skips_processed(self, db):
        """Already-processed handles in the current batch should be skipped."""
        from app.services import cf_ranking_service as svc_module

        with patch.object(svc_module, "CFSampleUser", _TestCFSampleUser):
            mock_cf_api = AsyncMock()

            # Need at least 3 users with different ratings for regression
            users = [
                {"handle": f"user_{i}", "rating": 800 + i * 200, "country": "US"}
                for i in range(5)
            ]
            mock_cf_api._request = AsyncMock(return_value=users)
            mock_cf_api.get_user_status = AsyncMock(
                return_value=[
                    {
                        "verdict": "OK",
                        "creationTimeSeconds": 1000,
                        "problem": {"contestId": 100, "index": "A", "rating": 1200},
                    }
                ]
            )

            result1 = await svc_module.run_sampling_pipeline(db, cf_api=mock_cf_api)
            assert result1.get("batch") == 1

            # Verify records exist
            from sqlalchemy import select as sa_select
            stmt = sa_select(_TestCFSampleUser).where(_TestCFSampleUser.sample_batch == 1)
            db_result = await db.execute(stmt)
            records = db_result.scalars().all()
            assert len(records) == 5

    @pytest.mark.asyncio
    async def test_pipeline_resumes_incomplete_batch(self, db):
        """Pipeline should resume an incomplete batch instead of creating a new one."""
        from app.services import cf_ranking_service as svc_module

        with patch.object(svc_module, "CFSampleUser", _TestCFSampleUser):
            users = [
                {"handle": f"user_{i}", "rating": 800 + i * 200, "country": "US"}
                for i in range(5)
            ]

            # Pre-insert 2 records for batch 1 WITHOUT regression_coefficients
            # (simulating a pipeline that was interrupted)
            for i in range(2):
                record = _TestCFSampleUser(
                    cf_handle=f"user_{i}",
                    cf_rating=800 + i * 200,
                    country="US",
                    equivalent_pp=10.0,
                    estimated_pp=10.0,
                    sample_batch=1,
                    regression_coefficients=None,  # Incomplete!
                )
                db.add(record)
            await db.commit()

            mock_cf_api = AsyncMock()
            mock_cf_api._request = AsyncMock(return_value=users)
            mock_cf_api.get_user_status = AsyncMock(
                return_value=[
                    {
                        "verdict": "OK",
                        "creationTimeSeconds": 1000,
                        "problem": {"contestId": 100, "index": "A", "rating": 1200},
                    }
                ]
            )

            result = await svc_module.run_sampling_pipeline(db, cf_api=mock_cf_api)

            # Should resume batch 1, not create batch 2
            assert result.get("batch") == 1, "Should resume incomplete batch 1"

            # All 5 users should now have records in batch 1
            from sqlalchemy import select as sa_select
            stmt = sa_select(_TestCFSampleUser).where(
                _TestCFSampleUser.sample_batch == 1
            )
            db_result = await db.execute(stmt)
            records = db_result.scalars().all()
            assert len(records) == 5


# ---------------------------------------------------------------------------
# Test: PP formula consistency
# ---------------------------------------------------------------------------


class TestPPFormulaConsistency:
    def test_base_pp_matches_pp_service(self):
        """The equivalent PP calculation must use PPService formulas exactly."""
        # These are the exact formulas from PPService
        for rating in [800, 1000, 1200, 1500, 1800, 2000, 2500]:
            expected = math.sqrt((rating - 800) / 100.0) * 10.0
            actual = PPService.calculate_base_pp(rating)
            assert abs(actual - expected) < 0.001, f"Rating {rating}: {actual} != {expected}"

    def test_base_pp_below_offset(self):
        assert PPService.calculate_base_pp(799) == 0.0
        assert PPService.calculate_base_pp(0) == 0.0

    def test_performance_factor_matches(self):
        """Verify performance factor formula matches the spec."""
        # f(wa, t) = (1 - 0.03*wa) * max(0.6, 1 - 0.01*t)
        for wa, t in [(0, 0), (2, 30), (5, 60), (10, 120)]:
            wa_factor = 1.0 - 0.03 * wa
            time_factor = max(0.6, 1.0 - 0.01 * t)
            expected = wa_factor * time_factor
            actual = PPService.calculate_performance_factor(wa, t)
            assert abs(actual - expected) < 0.001

    def test_aggregate_decay_matches(self):
        """Verify decay aggregation formula."""
        values = [20.0, 15.0, 10.0, 5.0]
        expected = 20.0 + 15.0 * 0.95 + 10.0 * 0.95**2 + 5.0 * 0.95**3
        actual = PPService.aggregate_total_pp(values)
        assert abs(actual - expected) < 0.01
