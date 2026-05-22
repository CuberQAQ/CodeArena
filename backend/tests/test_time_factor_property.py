"""Property-based tests for TimeFactor calculation invariants.

Uses hypothesis to verify mathematical properties of time factor formulas.
"""

from hypothesis import assume, given, settings
from hypothesis import strategies as st

from app.services.time_factor_service import (
    BUCKET_SIZE,
    TIME_FACTOR_MAX,
    TIME_FACTOR_MIN,
    TimeFactorService,
    _median,
    _rating_bucket,
)

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

seconds_st = st.floats(min_value=0.0, max_value=1_000_000.0, allow_nan=False, allow_infinity=False)
rating_st = st.integers(min_value=0, max_value=5000)
s_value_st = st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)
wa_count_st = st.integers(min_value=0, max_value=100)
expected_time_st = st.floats(min_value=1.0, max_value=1_000_000.0, allow_nan=False, allow_infinity=False)


# ---------------------------------------------------------------------------
# Time factor invariants
# ---------------------------------------------------------------------------


class TestTimeFactorProperties:
    """Time factor is always in [0.5, 1.5]."""

    @given(
        effective_time=seconds_st,
        expected_time=expected_time_st,
        s_value=s_value_st,
    )
    @settings(max_examples=5000)
    def test_time_factor_range(self, effective_time, expected_time, s_value):
        tf = TimeFactorService.calculate_time_factor(effective_time, expected_time, s_value)
        assert TIME_FACTOR_MIN <= tf <= TIME_FACTOR_MAX

    @given(
        expected_time=expected_time_st,
    )
    @settings(max_examples=1000)
    def test_solved_zero_time_returns_one(self, expected_time):
        tf = TimeFactorService.calculate_time_factor(0.0, expected_time, 1.0)
        assert tf == 1.0

    @given(
        expected_time=st.floats(min_value=10.0, max_value=1_000_000.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=1000)
    def test_solved_near_zero_time_max_factor(self, expected_time):
        tf = TimeFactorService.calculate_time_factor(0.001, expected_time, 1.0)
        assert tf == TIME_FACTOR_MAX

    @given(
        expected_time=expected_time_st,
        s_value=s_value_st,
    )
    @settings(max_examples=2000)
    def test_not_solved_returns_one(self, expected_time, s_value):
        assume(s_value == 0.0)
        tf = TimeFactorService.calculate_time_factor(1000.0, expected_time, 0.0)
        assert tf == 1.0

    @given(
        effective_time=seconds_st,
        expected_time=expected_time_st,
    )
    @settings(max_examples=3000)
    def test_faster_than_expected_higher_factor(self, effective_time, expected_time):
        assume(effective_time < expected_time)
        tf = TimeFactorService.calculate_time_factor(effective_time, expected_time, 1.0)
        assert tf >= 1.0

    @given(
        effective_time=seconds_st,
        expected_time=expected_time_st,
    )
    @settings(max_examples=3000)
    def test_slower_than_expected_lower_factor(self, effective_time, expected_time):
        assume(effective_time > expected_time)
        assume(effective_time > 0)
        tf = TimeFactorService.calculate_time_factor(effective_time, expected_time, 1.0)
        assert tf <= 1.0

    @given(expected_time=expected_time_st)
    @settings(max_examples=500)
    def test_null_effective_time_returns_one(self, expected_time):
        tf = TimeFactorService.calculate_time_factor(None, expected_time, 1.0)
        assert tf == 1.0

    @given(
        effective_time=seconds_st,
        expected_time=expected_time_st,
    )
    @settings(max_examples=1000)
    def test_zero_expected_returns_one(self, effective_time, expected_time):
        tf = TimeFactorService.calculate_time_factor(effective_time, 0.0, 1.0)
        assert tf == 1.0


# ---------------------------------------------------------------------------
# Effective time invariants
# ---------------------------------------------------------------------------


class TestEffectiveTimeProperties:
    """Effective time increases linearly with WA count."""

    @given(
        solve_time=seconds_st,
        wa_count=wa_count_st,
    )
    @settings(max_examples=2000)
    def test_effective_time_non_negative(self, solve_time, wa_count):
        et = TimeFactorService.compute_effective_time(solve_time, wa_count)
        assert et >= 0.0

    @given(
        solve_time=seconds_st,
    )
    @settings(max_examples=500)
    def test_zero_wa_equals_solve_time(self, solve_time):
        et = TimeFactorService.compute_effective_time(solve_time, 0)
        assert et == solve_time

    @given(
        solve_time=seconds_st,
        wa_count=wa_count_st,
    )
    @settings(max_examples=2000)
    def test_effective_time_gte_solve_time(self, solve_time, wa_count):
        et = TimeFactorService.compute_effective_time(solve_time, wa_count)
        assert et >= solve_time

    @given(
        solve_time=seconds_st,
        wa1=wa_count_st,
        wa2=wa_count_st,
    )
    @settings(max_examples=2000)
    def test_more_wa_more_effective_time(self, solve_time, wa1, wa2):
        assume(wa1 < wa2)
        et1 = TimeFactorService.compute_effective_time(solve_time, wa1)
        et2 = TimeFactorService.compute_effective_time(solve_time, wa2)
        assert et2 > et1


# ---------------------------------------------------------------------------
# Fallback expected time invariants
# ---------------------------------------------------------------------------


class TestFallbackExpectedTimeProperties:
    """Fallback expected time is positive and scales with problem difficulty."""

    @given(
        problem_rating=rating_st,
        user_rating=rating_st,
    )
    @settings(max_examples=2000)
    def test_fallback_positive(self, problem_rating, user_rating):
        et = TimeFactorService._fallback_expected_time(problem_rating, user_rating)
        assert et > 0.0

    @given(
        problem_rating=rating_st,
        user_rating=rating_st,
    )
    @settings(max_examples=2000)
    def test_fallback_at_least_60_seconds(self, problem_rating, user_rating):
        et = TimeFactorService._fallback_expected_time(problem_rating, user_rating)
        assert et >= 60.0  # at least 1 minute

    @given(
        user_rating=rating_st,
        r1=rating_st,
        r2=rating_st,
    )
    @settings(max_examples=2000)
    def test_fallback_harder_problem_more_time(self, user_rating, r1, r2):
        assume(r1 < r2)
        t1 = TimeFactorService._fallback_expected_time(r1, user_rating)
        t2 = TimeFactorService._fallback_expected_time(r2, user_rating)
        assert t1 <= t2 + 1e-10


# ---------------------------------------------------------------------------
# Rating bucket invariants
# ---------------------------------------------------------------------------


class TestRatingBucketProperties:
    """Rating bucket is always a multiple of BUCKET_SIZE."""

    @given(rating=rating_st)
    @settings(max_examples=2000)
    def test_bucket_multiple(self, rating):
        bucket = _rating_bucket(rating)
        assert bucket % BUCKET_SIZE == 0

    @given(rating=rating_st)
    @settings(max_examples=2000)
    def test_bucket_le_rating(self, rating):
        bucket = _rating_bucket(rating)
        assert bucket <= rating

    @given(rating=rating_st)
    @settings(max_examples=2000)
    def test_bucket_within_range(self, rating):
        bucket = _rating_bucket(rating)
        assert bucket <= rating < bucket + BUCKET_SIZE


# ---------------------------------------------------------------------------
# Median invariants
# ---------------------------------------------------------------------------


class TestMedianProperties:
    """Median of sorted list is bounded by min and max."""

    @given(values=st.lists(st.floats(min_value=0.0, max_value=1000.0, allow_nan=False), min_size=1, max_size=100))
    @settings(max_examples=1000)
    def test_median_within_range(self, values):
        m = _median(values)
        assert m is not None
        assert min(values) <= m <= max(values)

    def test_median_empty_is_none(self):
        assert _median([]) is None

    @given(v=st.floats(min_value=-1000.0, max_value=1000.0, allow_nan=False))
    @settings(max_examples=500)
    def test_median_single_element(self, v):
        m = _median([v])
        assert m == v
