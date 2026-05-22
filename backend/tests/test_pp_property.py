"""Property-based tests for PP calculation invariants.

Uses hypothesis to verify mathematical properties of PP formulas.
"""

import math

from hypothesis import assume, given, settings
from hypothesis import strategies as st

from app.services.pp_service import PPService

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

rating_st = st.integers(min_value=0, max_value=5000)
wa_count_st = st.integers(min_value=0, max_value=100)
time_minutes_st = st.floats(min_value=0.0, max_value=1000.0, allow_nan=False, allow_infinity=False)
elo_st = st.integers(min_value=0, max_value=5000)
positive_float_st = st.floats(min_value=0.01, max_value=1000.0, allow_nan=False, allow_infinity=False)
pp_list_st = st.lists(
    st.floats(min_value=0.0, max_value=100.0, allow_nan=False, allow_infinity=False), min_size=0, max_size=200
)


# ---------------------------------------------------------------------------
# Base PP invariants
# ---------------------------------------------------------------------------


class TestBasePPProperties:
    """Base PP is non-negative and monotonically non-decreasing with rating."""

    @given(rating=rating_st)
    @settings(max_examples=2000)
    def test_base_pp_non_negative(self, rating):
        pp = PPService.calculate_base_pp(rating)
        assert pp >= 0.0

    @given(rating=st.integers(min_value=0, max_value=799))
    @settings(max_examples=500)
    def test_base_pp_zero_below_offset(self, rating):
        pp = PPService.calculate_base_pp(rating)
        assert pp == 0.0

    @given(
        r1=st.integers(min_value=800, max_value=5000),
        r2=st.integers(min_value=800, max_value=5000),
    )
    @settings(max_examples=2000)
    def test_base_pp_monotonic(self, r1, r2):
        assume(r1 <= r2)
        pp1 = PPService.calculate_base_pp(r1)
        pp2 = PPService.calculate_base_pp(r2)
        assert pp1 <= pp2 + 1e-10

    @given(rating=st.integers(min_value=800, max_value=5000))
    @settings(max_examples=1000)
    def test_base_pp_formula(self, rating):
        """Verify sqrt((rating - 800) / 100) * 10 matches."""
        pp = PPService.calculate_base_pp(rating)
        expected = math.sqrt((rating - 800) / 100.0) * 10.0
        assert abs(pp - expected) < 1e-10


# ---------------------------------------------------------------------------
# Performance factor invariants
# ---------------------------------------------------------------------------


class TestPerformanceFactorProperties:
    """Performance factor decreases with more WA and more time."""

    @given(wa_count=wa_count_st, time_spent=time_minutes_st)
    @settings(max_examples=3000)
    def test_performance_factor_can_go_negative_with_extreme_wa(self, wa_count, time_spent):
        pf = PPService.calculate_performance_factor(wa_count, time_spent)
        # wa_factor = 1 - 0.03 * wa_count, can go negative for wa > 33
        # time_factor >= 0.6, so overall can be negative
        assert pf <= 1.0 + 1e-10

    @given(
        wa1=wa_count_st,
        wa2=wa_count_st,
        time_spent=time_minutes_st,
    )
    @settings(max_examples=3000)
    def test_more_wa_lower_factor(self, wa1, wa2, time_spent):
        assume(wa1 < wa2)
        pf1 = PPService.calculate_performance_factor(wa1, time_spent)
        pf2 = PPService.calculate_performance_factor(wa2, time_spent)
        assert pf1 >= pf2 - 1e-10

    @given(
        wa_count=st.integers(min_value=0, max_value=33),  # Keep wa_factor non-negative
        t1=time_minutes_st,
        t2=time_minutes_st,
    )
    @settings(max_examples=3000)
    def test_more_time_lower_factor(self, wa_count, t1, t2):
        assume(t1 < t2)
        pf1 = PPService.calculate_performance_factor(wa_count, t1)
        pf2 = PPService.calculate_performance_factor(wa_count, t2)
        assert pf1 >= pf2 - 1e-10

    @given(wa_count=wa_count_st, time_spent=time_minutes_st)
    @settings(max_examples=2000)
    def test_zero_wa_zero_time_is_one(self, wa_count, time_spent):
        pf = PPService.calculate_performance_factor(0, 0.0)
        assert abs(pf - 1.0) < 1e-10

    @given(wa_count=wa_count_st, time_spent=time_minutes_st)
    @settings(max_examples=3000)
    def test_performance_factor_bounded(self, wa_count, time_spent):
        pf = PPService.calculate_performance_factor(wa_count, time_spent)
        assert pf <= 1.0 + 1e-10  # at most 1.0


# ---------------------------------------------------------------------------
# Overkill multiplier invariants
# ---------------------------------------------------------------------------


class TestOverkillMultiplierProperties:
    """Overkill multiplier is >= 1.0 and increases with gap."""

    @given(user_elo=elo_st, problem_rating=rating_st)
    @settings(max_examples=2000)
    def test_multiplier_at_least_one(self, user_elo, problem_rating):
        m = PPService.calculate_overkill_multiplier(user_elo, problem_rating)
        assert m >= 1.0

    @given(
        user_elo=elo_st,
        problem_rating=rating_st,
    )
    @settings(max_examples=2000)
    def test_no_overkill_when_gap_small(self, user_elo, problem_rating):
        assume(problem_rating - user_elo <= 150)
        m = PPService.calculate_overkill_multiplier(user_elo, problem_rating)
        assert m == 1.0

    @given(user_elo=elo_st)
    @settings(max_examples=500)
    def test_multiplier_at_most_two(self, user_elo):
        m = PPService.calculate_overkill_multiplier(user_elo, 5000)
        assert m <= 2.0


# ---------------------------------------------------------------------------
# Total PP aggregation invariants
# ---------------------------------------------------------------------------


class TestAggregationProperties:
    """Total PP is non-negative and monotonically increases with more entries."""

    @given(values=pp_list_st)
    @settings(max_examples=1000)
    def test_total_pp_non_negative(self, values):
        total = PPService.aggregate_total_pp(values)
        assert total >= 0.0

    @given(values=pp_list_st)
    @settings(max_examples=1000)
    def test_empty_list_zero(self, values):
        total = PPService.aggregate_total_pp([])
        assert total == 0.0

    @given(
        v=st.floats(min_value=0.01, max_value=50.0, allow_nan=False),
    )
    @settings(max_examples=500)
    def test_single_entry_no_decay(self, v):
        total = PPService.aggregate_total_pp([v])
        assert abs(total - round(v, 2)) < 1e-10

    @given(
        n=st.integers(min_value=1, max_value=50),
        v=st.floats(min_value=1.0, max_value=10.0, allow_nan=False),
    )
    @settings(max_examples=500)
    def test_more_entries_more_pp(self, n, v):
        t1 = PPService.aggregate_total_pp([v] * n)
        t2 = PPService.aggregate_total_pp([v] * (n + 1))
        assert t2 >= t1 - 1e-10
