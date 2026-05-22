"""Property-based tests for Elo calculation invariants.

Uses hypothesis to verify mathematical properties hold for all possible inputs.
"""

from hypothesis import assume, given, settings
from hypothesis import strategies as st

from app.services.elo_service import EloService

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

rating_st = st.integers(min_value=0, max_value=5000)
k_factor_st = st.floats(min_value=1.0, max_value=100.0, allow_nan=False, allow_infinity=False)
s_value_st = st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)
expected_st = st.floats(min_value=0.01, max_value=0.99, allow_nan=False, allow_infinity=False)
submission_count_st = st.integers(min_value=0, max_value=500)
hint_level_st = st.integers(min_value=0, max_value=3)
error_count_st = st.integers(min_value=0, max_value=100)
positive_float_st = st.floats(min_value=0.0, max_value=10000.0, allow_nan=False, allow_infinity=False)


# ---------------------------------------------------------------------------
# S-value invariants
# ---------------------------------------------------------------------------


class TestSValueProperties:
    """S-value is always in [0.0, 1.0]."""

    @given(
        is_solved=st.booleans(),
        is_first_ac=st.booleans(),
        error_count=error_count_st,
    )
    @settings(max_examples=2000)
    def test_s_value_range(self, is_solved, is_first_ac, error_count):
        s = EloService.calculate_s_value(is_solved, is_first_ac, error_count)
        assert 0.0 <= s <= 1.0

    @given(error_count=error_count_st)
    @settings(max_examples=500)
    def test_solved_first_ac_is_one(self, error_count):
        s = EloService.calculate_s_value(True, True, error_count)
        assert s == 1.0

    @given(error_count=error_count_st)
    @settings(max_examples=500)
    def test_not_solved_is_zero(self, error_count):
        s = EloService.calculate_s_value(False, True, error_count)
        assert s == 0.0

    @given(error_count=error_count_st)
    @settings(max_examples=1000)
    def test_solved_not_first_ac_bounded(self, error_count):
        s = EloService.calculate_s_value(True, False, error_count)
        assert 0.7 <= s <= 1.0


# ---------------------------------------------------------------------------
# Expected score invariants
# ---------------------------------------------------------------------------


class TestExpectedScoreProperties:
    """E_A + E_B = 1.0 (conservation of expected scores)."""

    @given(rating_a=rating_st, rating_b=rating_st)
    @settings(max_examples=2000)
    def test_expected_scores_sum_to_one(self, rating_a, rating_b):
        e_a = EloService.calculate_expected_score(rating_a, rating_b)
        e_b = EloService.calculate_expected_score(rating_b, rating_a)
        assert abs(e_a + e_b - 1.0) < 1e-10

    @given(rating_a=rating_st, rating_b=rating_st)
    @settings(max_examples=2000)
    def test_expected_score_range(self, rating_a, rating_b):
        e = EloService.calculate_expected_score(rating_a, rating_b)
        assert 0.0 < e < 1.0

    @given(rating_a=rating_st)
    @settings(max_examples=1000)
    def test_equal_ratings_expected_half(self, rating_a):
        e = EloService.calculate_expected_score(rating_a, rating_a)
        assert abs(e - 0.5) < 1e-10

    @given(rating_a=rating_st, rating_b=rating_st)
    @settings(max_examples=2000)
    def test_higher_rating_higher_expected(self, rating_a, rating_b):
        assume(rating_a > rating_b)
        e_a = EloService.calculate_expected_score(rating_a, rating_b)
        assert e_a > 0.5


# ---------------------------------------------------------------------------
# New rating invariants
# ---------------------------------------------------------------------------


class TestNewRatingProperties:
    """Elo change is bounded by K factor."""

    @given(
        current_rating=rating_st,
        expected_score=expected_st,
        actual_score=s_value_st,
        k_factor=k_factor_st,
    )
    @settings(max_examples=5000)
    def test_elo_change_bounded_by_k(self, current_rating, expected_score, actual_score, k_factor):
        new_rating = EloService.calculate_new_rating(current_rating, expected_score, actual_score, k_factor)
        change = new_rating - current_rating
        assert abs(change) <= k_factor + 1  # +1 for rounding

    @given(
        current_rating=rating_st,
        k_factor=k_factor_st,
    )
    @settings(max_examples=1000)
    def test_win_increases_when_expected_below_one(self, current_rating, k_factor):
        expected = 0.5
        new_rating = EloService.calculate_new_rating(current_rating, expected, 1.0, k_factor)
        assert new_rating >= current_rating

    @given(
        current_rating=rating_st,
        k_factor=k_factor_st,
    )
    @settings(max_examples=1000)
    def test_loss_decreases_when_expected_above_zero(self, current_rating, k_factor):
        expected = 0.5
        new_rating = EloService.calculate_new_rating(current_rating, expected, 0.0, k_factor)
        assert new_rating <= current_rating


# ---------------------------------------------------------------------------
# K-factor invariants
# ---------------------------------------------------------------------------


class TestKFactorProperties:
    """K-factor is monotonically non-increasing with submission count."""

    @given(n=submission_count_st)
    @settings(max_examples=2000)
    def test_k_factor_range(self, n):
        k = EloService.calculate_k_factor(n)
        assert 20.0 <= k <= 40.0

    @given(n=st.integers(min_value=0, max_value=20))
    @settings(max_examples=500)
    def test_newbie_gets_max_k(self, n):
        k = EloService.calculate_k_factor(n)
        assert k == 40.0

    @given(n=st.integers(min_value=100, max_value=500))
    @settings(max_examples=500)
    def test_veteran_gets_min_k(self, n):
        k = EloService.calculate_k_factor(n)
        assert k == 20.0

    @given(
        n1=st.integers(min_value=20, max_value=99),
        n2=st.integers(min_value=20, max_value=99),
    )
    @settings(max_examples=2000)
    def test_k_factor_monotonic(self, n1, n2):
        assume(n1 <= n2)
        k1 = EloService.calculate_k_factor(n1)
        k2 = EloService.calculate_k_factor(n2)
        assert k1 >= k2


# ---------------------------------------------------------------------------
# Hint attenuation invariants
# ---------------------------------------------------------------------------


class TestHintAttenuationProperties:
    """Hint attenuation only reduces positive changes, never increases them."""

    @given(
        elo_change=st.floats(min_value=-1000.0, max_value=1000.0, allow_nan=False),
        hint_level=hint_level_st,
    )
    @settings(max_examples=3000)
    def test_attenuation_never_increases(self, elo_change, hint_level):
        result = EloService.apply_hint_attenuation(elo_change, hint_level)
        assert result <= elo_change or elo_change <= 0

    @given(hint_level=hint_level_st)
    @settings(max_examples=500)
    def test_attenuation_always_le_one(self, hint_level):
        result = EloService.apply_hint_attenuation(100.0, hint_level)
        assert result <= 100.0

    @given(
        elo_change=st.floats(min_value=-1000.0, max_value=-0.01, allow_nan=False),
        hint_level=hint_level_st,
    )
    @settings(max_examples=1000)
    def test_negative_change_unchanged(self, elo_change, hint_level):
        result = EloService.apply_hint_attenuation(elo_change, hint_level)
        assert result == elo_change

    @given(hint_level=hint_level_st)
    @settings(max_examples=100)
    def test_zero_hint_no_attenuation(self, hint_level):
        result = EloService.apply_hint_attenuation(100.0, 0)
        assert result == 100.0


# ---------------------------------------------------------------------------
# Challenge Elo invariants
# ---------------------------------------------------------------------------


class TestChallengeEloProperties:
    """Rating conservation in challenge mode."""

    @given(
        rating_a=rating_st,
        rating_b=rating_st,
        actual_score=s_value_st,
        k_factor=k_factor_st,
    )
    @settings(max_examples=3000)
    def test_total_rating_preserved_no_hint(self, rating_a, rating_b, actual_score, k_factor):
        new_a, new_b, _ = EloService.calculate_challenge_elo(rating_a, rating_b, actual_score, k_factor, hint_level=0)
        # Total may not be exactly preserved due to rounding, but should be close
        diff_before = rating_a + rating_b
        diff_after = new_a + new_b
        assert abs(diff_after - diff_before) <= 2  # rounding tolerance

    @given(
        rating_a=rating_st,
        rating_b=rating_st,
    )
    @settings(max_examples=1000)
    def test_symmetric_draw_no_change(self, rating_a, rating_b):
        """When players have equal rating and draw, no change expected."""
        _, _, change = EloService.calculate_challenge_elo(rating_a, rating_a, 0.5, 32.0, 0)
        assert change == 0


# ---------------------------------------------------------------------------
# Contest score invariants
# ---------------------------------------------------------------------------


class TestContestScoreProperties:
    """Contest score is bounded."""

    @given(
        solved=st.integers(min_value=0, max_value=20),
        total=st.integers(min_value=1, max_value=20),
        time_used=st.floats(min_value=0.0, max_value=100000.0, allow_nan=False),
        time_limit=st.floats(min_value=1.0, max_value=100000.0, allow_nan=False),
    )
    @settings(max_examples=2000)
    def test_contest_score_non_negative(self, solved, total, time_used, time_limit):
        score = EloService.calculate_contest_score(solved, total, time_used, time_limit)
        assert score >= 0.0

    @given(
        solved=st.integers(min_value=0, max_value=10),
        total=st.integers(min_value=1, max_value=10),
        time_used=st.floats(min_value=0.0, max_value=100000.0, allow_nan=False),
        time_limit=st.floats(min_value=1.0, max_value=100000.0, allow_nan=False),
    )
    @settings(max_examples=2000)
    def test_contest_score_bounded(self, solved, total, time_used, time_limit):
        assume(solved <= total)
        score = EloService.calculate_contest_score(solved, total, time_used, time_limit)
        assert score <= solved / total + 0.3  # max bonus is 0.2

    def test_zero_total_problems_returns_zero(self):
        score = EloService.calculate_contest_score(5, 0, 100, 200)
        assert score == 0.0
