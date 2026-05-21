"""Tests for TimeFactorService -- per-problem expected time model.

Tests cover:
- Sequential solve time extraction (focused time)
- Non-sequential data exclusion
- Rating bucket correctness
- Median calculation
- Bucket expansion when data is insufficient
- Fallback expected time model
- Time factor range [0.5, 1.5]
- S=0 returns time_factor = 1.0
- contestId extraction from problem_id
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.cf_api_service import CFApiService
from app.services.time_factor_service import (
    SECONDS_PER_MINUTE,
    TimeFactorService,
    _extract_contest_id,
    _median,
    _rating_bucket,
)

# ---------------------------------------------------------------------------
# Unit tests: _extract_contest_id
# ---------------------------------------------------------------------------


class TestExtractContestId:
    """Tests for extracting contestId from problem_id strings."""

    def test_standard_problem_id(self):
        assert _extract_contest_id("1920A") == 1920

    def test_multi_digit_index(self):
        assert _extract_contest_id("1846C") == 1846

    def test_single_digit_contest(self):
        assert _extract_contest_id("1B") == 1

    def test_large_contest_id(self):
        assert _extract_contest_id("99999Z") == 99999

    def test_no_alpha_suffix(self):
        assert _extract_contest_id("12345") is None

    def test_empty_string(self):
        assert _extract_contest_id("") is None

    def test_alpha_only(self):
        assert _extract_contest_id("ABC") is None

    def test_leading_zero_contest_id(self):
        # "0A" would give contest_id=0, which is < MIN_CONTEST_ID
        assert _extract_contest_id("0A") is None


# ---------------------------------------------------------------------------
# Unit tests: _rating_bucket
# ---------------------------------------------------------------------------


class TestRatingBucket:
    """Tests for 200-point rating bucket calculation."""

    def test_exact_bucket_boundary(self):
        assert _rating_bucket(1200) == 1200

    def test_mid_bucket(self):
        assert _rating_bucket(1350) == 1200

    def test_upper_bucket_edge(self):
        assert _rating_bucket(1399) == 1200

    def test_next_bucket(self):
        assert _rating_bucket(1400) == 1400

    def test_low_rating(self):
        assert _rating_bucket(800) == 800

    def test_very_low_rating(self):
        assert _rating_bucket(50) == 0

    def test_high_rating(self):
        assert _rating_bucket(2500) == 2400

    def test_very_high_rating(self):
        assert _rating_bucket(3999) == 3800


# ---------------------------------------------------------------------------
# Unit tests: _median
# ---------------------------------------------------------------------------


class TestMedian:
    """Tests for median calculation."""

    def test_odd_count(self):
        assert _median([1.0, 2.0, 3.0]) == 2.0

    def test_even_count(self):
        assert _median([1.0, 2.0, 3.0, 4.0]) == 2.5

    def test_single_value(self):
        assert _median([5.0]) == 5.0

    def test_two_values(self):
        assert _median([10.0, 20.0]) == 15.0

    def test_empty_list(self):
        assert _median([]) is None

    def test_unsorted_input(self):
        assert _median([3.0, 1.0, 2.0]) == 2.0


# ---------------------------------------------------------------------------
# Unit tests: _calculate_focused_times
# ---------------------------------------------------------------------------


def _make_submission(handle: str, index: str, rel_time: int, verdict: str = "OK") -> dict:
    """Helper to create a CF submission dict."""
    return {
        "verdict": verdict,
        "problem": {"index": index},
        "relativeTimeSeconds": rel_time,
        "author": {
            "members": [{"handle": handle}],
        },
    }


class TestCalculateFocusedTimes:
    """Tests for the focused time calculation algorithm."""

    def test_basic_sequential_solves(self):
        """A user solves A at 300s, B at 900s, C at 1800s.
        Focused time for C = 1800 - 900 = 900s.
        """
        submissions = [
            _make_submission("alice", "A", 300),
            _make_submission("alice", "B", 900),
            _make_submission("alice", "C", 1800),
        ]
        rating_changes = {"alice": 1500}

        result = TimeFactorService._calculate_focused_times(submissions, rating_changes, "C")

        assert 1400 in result  # bucket for 1500 rating -> 1400
        assert 900.0 in result[1400]

    def test_first_problem_focused_time(self):
        """For the first problem solved, focused_time = AC_time itself."""
        submissions = [
            _make_submission("bob", "A", 600),
            _make_submission("bob", "B", 1200),
        ]
        rating_changes = {"bob": 1000}

        result = TimeFactorService._calculate_focused_times(submissions, rating_changes, "A")

        assert 1000 in result  # bucket for 1000 rating -> 1000
        assert 600.0 in result[1000]

    def test_non_sequential_data_excluded(self):
        """If a user solves problems out of alphabetical order (skip-back),
        the skip-back data is excluded.  Only sequential index-ascending
        entries are kept."""
        submissions = [
            _make_submission("charlie", "A", 300),
            _make_submission("charlie", "B", 900),
            # Re-submission for A at a later time — index "A" < last_index "B"
            # so this is excluded by the index-ascending check.
            _make_submission("charlie", "A", 1500),
            _make_submission("charlie", "C", 2000),
        ]
        rating_changes = {"charlie": 1600}

        # Sequential sequence (time-ascending AND index-ascending):
        # A@300 → B@900 → C@2000.  A@1500 is excluded because "A" < "B".
        # focused_time(C) = 2000 - 900 = 1100.

        result = TimeFactorService._calculate_focused_times(submissions, rating_changes, "C")
        assert 1600 in result
        assert 1100.0 in result[1600]

    def test_skip_back_problem_excluded(self):
        """Per task.md line 98: solver first AC C(50min) then AC B(70min)
        → B's data should NOT be included because the solver skipped back."""
        submissions = [
            _make_submission("alice", "C", 3000),  # 50min
            _make_submission("alice", "B", 4200),  # 70min — index "B" < "C"
        ]
        rating_changes = {"alice": 1400}

        # After sorting by time: C@3000, B@4200
        # Sequential check: C is first (ok). B has idx "B" < last_index "C" → excluded.
        # So B has no focused_time → not in result.
        result = TimeFactorService._calculate_focused_times(submissions, rating_changes, "B")
        assert 1400 not in result or result[1400] == []

    def test_problem_not_solved(self):
        """If the target problem was not solved by anyone, result is empty."""
        submissions = [
            _make_submission("dave", "A", 300),
            _make_submission("dave", "B", 900),
        ]
        rating_changes = {"dave": 1200}

        result = TimeFactorService._calculate_focused_times(submissions, rating_changes, "D")

        assert result == {}

    def test_multiple_users_different_buckets(self):
        """Two users in different rating buckets solving the same problem."""
        submissions = [
            _make_submission("user_low", "A", 600),
            _make_submission("user_low", "B", 1800),
            _make_submission("user_high", "A", 300),
            _make_submission("user_high", "B", 900),
        ]
        rating_changes = {"user_low": 1100, "user_high": 1700}

        result = TimeFactorService._calculate_focused_times(submissions, rating_changes, "B")

        # user_low (1100) -> bucket 1000, focused B = 1800 - 600 = 1200
        assert 1000 in result
        assert 1200.0 in result[1000]

        # user_high (1700) -> bucket 1600, focused B = 900 - 300 = 600
        assert 1600 in result
        assert 600.0 in result[1600]

    def test_non_ac_submissions_ignored(self):
        """Submissions with verdict != 'OK' are filtered out."""
        submissions = [
            _make_submission("eve", "A", 300, verdict="WA"),
            _make_submission("eve", "A", 400),
            _make_submission("eve", "B", 1200),
        ]
        rating_changes = {"eve": 1300}

        result = TimeFactorService._calculate_focused_times(submissions, rating_changes, "B")

        # Only AC submissions count: A@400, B@1200
        # focused B = 1200 - 400 = 800
        assert 1200 in result
        assert 800.0 in result[1200]

    def test_user_not_in_rating_changes_excluded(self):
        """Users not present in rating_changes are excluded."""
        submissions = [
            _make_submission("unknown_user", "A", 300),
            _make_submission("unknown_user", "B", 900),
        ]
        rating_changes = {}  # no rating data

        result = TimeFactorService._calculate_focused_times(submissions, rating_changes, "B")
        assert result == {}

    def test_zero_or_negative_focused_time_excluded(self):
        """Focused times <= 0 are excluded."""
        submissions = [
            _make_submission("frank", "A", 0),  # AC at time 0
        ]
        rating_changes = {"frank": 1200}

        # focused time for A = 0 (first problem, AC at time 0) -> excluded since <= 0
        result = TimeFactorService._calculate_focused_times(submissions, rating_changes, "A")
        assert result == {}

    def test_skip_problem_data(self):
        """User solves A, skips B, solves C.
        The focused time for C should reflect the gap including the skipped problem."""
        submissions = [
            _make_submission("grace", "A", 300),
            _make_submission("grace", "C", 1800),  # skipped B
        ]
        rating_changes = {"grace": 1400}

        # Sequential: A@300, C@1800
        # focused C = 1800 - 300 = 1500
        result = TimeFactorService._calculate_focused_times(submissions, rating_changes, "C")
        assert 1400 in result
        assert 1500.0 in result[1400]


# ---------------------------------------------------------------------------
# Unit tests: _get_bucket_median with expansion
# ---------------------------------------------------------------------------


class TestGetBucketMedian:
    """Tests for bucket median calculation with expansion."""

    def test_exact_bucket_enough_data(self):
        data = {1200: [100.0, 200.0, 300.0, 400.0, 500.0]}
        result = TimeFactorService._get_bucket_median(data, 1200)
        assert result == 300.0  # median of 5 values

    def test_exact_bucket_insufficient_expands(self):
        data = {
            1000: [50.0, 60.0, 70.0],
            1200: [100.0, 200.0],  # only 2 data points, needs expansion
            1400: [150.0, 250.0, 350.0],
        }
        result = TimeFactorService._get_bucket_median(data, 1200)
        # Merges 1200 (2) + 1400 (3) = 5 points -> [100, 150, 200, 250, 350]
        assert result == 200.0

    def test_expansion_prefers_higher_bucket_first(self):
        data = {
            1200: [100.0, 200.0],  # 2 points
            1400: [300.0, 400.0, 500.0],  # 3 points
        }
        result = TimeFactorService._get_bucket_median(data, 1200)
        # Merge: [100, 200, 300, 400, 500] -> median = 300
        assert result == 300.0

    def test_no_data_returns_none(self):
        result = TimeFactorService._get_bucket_median({}, 1200)
        assert result is None

    def test_target_bucket_missing(self):
        data = {1000: [100.0] * 5}
        result = TimeFactorService._get_bucket_median(data, 1200)
        # Should expand to 1000 and use that data
        assert result == 100.0

    def test_all_buckets_empty_after_expansion(self):
        data = {1200: []}
        result = TimeFactorService._get_bucket_median(data, 1200)
        assert result is None

    def test_large_expansion(self):
        """Target bucket has no data, needs to expand multiple steps."""
        data = {
            800: [10.0] * 6,
            1200: [],  # target, empty
        }
        result = TimeFactorService._get_bucket_median(data, 1200)
        # Expands to 800 eventually
        assert result == 10.0


# ---------------------------------------------------------------------------
# Unit tests: _fallback_expected_time
# ---------------------------------------------------------------------------


class TestFallbackExpectedTime:
    """Tests for the fallback expected time formula."""

    def test_basic_calculation(self):
        # problem_rating=1300, user_rating=1300
        # base_minutes = 10 + (1300-800)/50 = 10 + 10 = 20
        # rating_diff = 0, adjustment = 0, multiplier = 1.0
        # expected = 20 * 60 = 1200 seconds
        result = TimeFactorService._fallback_expected_time(1300, 1300)
        assert result == 20.0 * SECONDS_PER_MINUTE

    def test_stronger_user_solves_faster(self):
        # Higher user rating -> lower expected time
        weak = TimeFactorService._fallback_expected_time(1500, 1000)
        strong = TimeFactorService._fallback_expected_time(1500, 2000)
        assert strong < weak

    def test_harder_problem_takes_longer(self):
        easy = TimeFactorService._fallback_expected_time(1000, 1500)
        hard = TimeFactorService._fallback_expected_time(2000, 1500)
        assert hard > easy

    def test_minimum_1_minute(self):
        # Even at very low rating, minimum is 1 minute
        result = TimeFactorService._fallback_expected_time(800, 5000)
        assert result >= 1.0 * SECONDS_PER_MINUTE

    def test_returns_seconds(self):
        result = TimeFactorService._fallback_expected_time(1000, 1000)
        # Should be in seconds (large number), not minutes
        assert result > 60  # more than 1 minute in seconds

    def test_rating_adjustment_bounds(self):
        """Multiplier is clamped to [0.5, 2.0]."""
        # Extreme rating difference should still produce reasonable times
        very_weak = TimeFactorService._fallback_expected_time(3000, 500)
        very_strong = TimeFactorService._fallback_expected_time(500, 3000)
        # Both should be positive
        assert very_weak > 0
        assert very_strong > 0


# ---------------------------------------------------------------------------
# Unit tests: calculate_time_factor
# ---------------------------------------------------------------------------


class TestCalculateTimeFactor:
    """Tests for the time factor calculation."""

    def test_solved_in_expected_time(self):
        # T_eff == T_expected -> factor = 1.0
        result = TimeFactorService.calculate_time_factor(600.0, 600.0, 1.0)
        assert result == 1.0

    def test_solved_faster_than_expected(self):
        # T_eff < T_expected -> factor > 1.0
        # raw = 600 / 300 = 2.0, clamped to 1.5
        result = TimeFactorService.calculate_time_factor(300.0, 600.0, 1.0)
        assert result == 1.5

    def test_solved_slower_than_expected(self):
        # T_eff > T_expected -> factor < 1.0
        result = TimeFactorService.calculate_time_factor(1200.0, 600.0, 1.0)
        assert result == pytest.approx(0.5)

    def test_not_solved_returns_1(self):
        # S=0 -> factor = 1.0 regardless of time
        result = TimeFactorService.calculate_time_factor(300.0, 600.0, 0.0)
        assert result == 1.0

    def test_no_effective_time(self):
        # effective_time=None -> treated as equal to expected -> 1.0
        result = TimeFactorService.calculate_time_factor(None, 600.0, 1.0)
        assert result == 1.0

    def test_range_lower_bound(self):
        # Very slow solve -> factor clamped to 0.5
        result = TimeFactorService.calculate_time_factor(100000.0, 600.0, 0.7)
        assert result == 0.5

    def test_range_upper_bound(self):
        # Very fast solve -> factor clamped to 1.5
        result = TimeFactorService.calculate_time_factor(1.0, 600.0, 1.0)
        assert result == 1.5

    def test_zero_expected_time(self):
        # Edge case: expected_time <= 0 -> returns 1.0
        result = TimeFactorService.calculate_time_factor(300.0, 0.0, 1.0)
        assert result == 1.0

    def test_negative_expected_time(self):
        result = TimeFactorService.calculate_time_factor(300.0, -100.0, 1.0)
        assert result == 1.0

    def test_partial_s_value(self):
        # S=0.85 (solved with errors)
        result = TimeFactorService.calculate_time_factor(600.0, 600.0, 0.85)
        assert result == 1.0  # equal times -> factor = 1.0

    def test_twice_as_fast(self):
        # T_eff = T_expected / 2 -> raw = 2.0, clamped to 1.5
        result = TimeFactorService.calculate_time_factor(300.0, 600.0, 0.9)
        assert result == 1.5

    def test_twice_as_slow(self):
        # T_eff = 2 * T_expected -> factor = 0.5
        result = TimeFactorService.calculate_time_factor(1200.0, 600.0, 0.8)
        assert result == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# Integration tests: calculate_expected_time
# ---------------------------------------------------------------------------


class TestCalculateExpectedTime:
    """Tests for the full calculate_expected_time flow with mocked CF API."""

    @pytest.fixture
    def cf_service(self):
        """Create a mock CFApiService."""
        service = MagicMock(spec=CFApiService)
        service.get_contest_status = AsyncMock()
        service.get_contest_rating_changes = AsyncMock()
        return service

    @pytest.mark.asyncio
    async def test_fallback_when_no_contest_id(self, cf_service):
        """Problem ID without valid contestId uses fallback."""
        result = await TimeFactorService.calculate_expected_time(
            cf_service,
            "INVALID",
            1300,
            1500,
        )
        # Should be the fallback value
        expected = TimeFactorService._fallback_expected_time(1300, 1500)
        assert result == expected
        # CF API should not be called
        cf_service.get_contest_status.assert_not_called()

    @pytest.mark.asyncio
    async def test_fallback_on_api_error(self, cf_service):
        """CF API error falls back to formula."""
        cf_service.get_contest_status.side_effect = Exception("API error")

        result = await TimeFactorService.calculate_expected_time(
            cf_service,
            "1920A",
            1300,
            1500,
        )
        expected = TimeFactorService._fallback_expected_time(1300, 1500)
        assert result == expected

    @pytest.mark.asyncio
    async def test_fallback_on_empty_submissions(self, cf_service):
        """Empty submissions data falls back to formula."""
        cf_service.get_contest_status.return_value = []
        cf_service.get_contest_rating_changes.return_value = [
            {"handle": "user1", "oldRating": 1500},
        ]

        result = await TimeFactorService.calculate_expected_time(
            cf_service,
            "1920A",
            1300,
            1500,
        )
        expected = TimeFactorService._fallback_expected_time(1300, 1500)
        assert result == expected

    @pytest.mark.asyncio
    async def test_fallback_on_empty_rating_changes(self, cf_service):
        """Empty rating changes falls back to formula."""
        cf_service.get_contest_status.return_value = [
            _make_submission("user1", "A", 300),
        ]
        cf_service.get_contest_rating_changes.return_value = []

        result = await TimeFactorService.calculate_expected_time(
            cf_service,
            "1920A",
            1300,
            1500,
        )
        expected = TimeFactorService._fallback_expected_time(1300, 1500)
        assert result == expected

    @pytest.mark.asyncio
    async def test_full_flow_with_data(self, cf_service):
        """Full flow: contest data available, returns bucket median."""
        submissions = []
        rating_changes_list = []

        # Create 10 users in the 1400-1599 bucket, all solving A then B
        for i in range(10):
            handle = f"user_{i}"
            # All solve A at ~300s, B at ~900s
            a_time = 300 + i * 10
            b_time = 900 + i * 20
            submissions.append(_make_submission(handle, "A", a_time))
            submissions.append(_make_submission(handle, "B", b_time))
            rating = 1500 + i * 5  # all in 1400 bucket
            rating_changes_list.append({"handle": handle, "oldRating": rating})

        cf_service.get_contest_status.return_value = submissions
        cf_service.get_contest_rating_changes.return_value = rating_changes_list

        result = await TimeFactorService.calculate_expected_time(
            cf_service,
            "1920B",
            1300,
            1500,
        )

        # Should be a reasonable number of seconds (600 +/- some variation)
        assert 500 < result < 700
        # Should NOT be the fallback
        fallback = TimeFactorService._fallback_expected_time(1300, 1500)
        assert result != fallback

    @pytest.mark.asyncio
    async def test_bucket_expansion_flow(self, cf_service):
        """User in a bucket with few data points triggers expansion."""
        submissions = []
        rating_changes_list = []

        # Only 1 user in the 1200 bucket
        handle = "lonely_user"
        submissions.append(_make_submission(handle, "A", 300))
        submissions.append(_make_submission(handle, "A", 600))  # re-AC doesn't add
        submissions.append(_make_submission(handle, "B", 1200))
        rating_changes_list.append({"handle": handle, "oldRating": 1300})

        # 5 users in the 1400 bucket
        for i in range(5):
            h = f"neighbor_{i}"
            a_time = 250 + i * 10
            b_time = 850 + i * 15
            submissions.append(_make_submission(h, "A", a_time))
            submissions.append(_make_submission(h, "B", b_time))
            rating_changes_list.append({"handle": h, "oldRating": 1450 + i * 5})

        cf_service.get_contest_status.return_value = submissions
        cf_service.get_contest_rating_changes.return_value = rating_changes_list

        # User rating 1300 -> bucket 1200, only 1 data point, should expand to 1400
        result = await TimeFactorService.calculate_expected_time(
            cf_service,
            "1920B",
            1300,
            1300,
        )

        # Should return a value (not fallback) thanks to expansion
        fallback = TimeFactorService._fallback_expected_time(1300, 1300)
        assert result != fallback
        assert result > 0

    @pytest.mark.asyncio
    async def test_rating_changes_api_error_falls_back(self, cf_service):
        """If rating changes API fails but submissions succeed, use fallback."""
        cf_service.get_contest_status.return_value = [
            _make_submission("user1", "A", 300),
        ]
        cf_service.get_contest_rating_changes.side_effect = Exception("API error")

        result = await TimeFactorService.calculate_expected_time(
            cf_service,
            "1920A",
            1300,
            1500,
        )
        # The outer try/except should catch and use fallback
        expected = TimeFactorService._fallback_expected_time(1300, 1500)
        assert result == expected


# ---------------------------------------------------------------------------
# Edge case tests
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Edge case tests for the time factor service."""

    def test_time_factor_with_very_large_effective_time(self):
        """Very large effective time still clamps to 0.5."""
        result = TimeFactorService.calculate_time_factor(1e9, 600.0, 1.0)
        assert result == 0.5

    def test_time_factor_with_very_small_effective_time(self):
        """Very small effective time clamps to 1.5."""
        result = TimeFactorService.calculate_time_factor(0.001, 600.0, 1.0)
        assert result == 1.5

    def test_fallback_very_low_problem_rating(self):
        """Problem rating below 800 still works."""
        result = TimeFactorService._fallback_expected_time(500, 1200)
        assert result > 0

    def test_calculate_focused_times_empty_submissions(self):
        result = TimeFactorService._calculate_focused_times([], {}, "A")
        assert result == {}

    def test_calculate_focused_times_submission_without_members(self):
        submissions = [
            {
                "verdict": "OK",
                "problem": {"index": "A"},
                "relativeTimeSeconds": 300,
                "author": {"members": []},  # empty members
            },
        ]
        result = TimeFactorService._calculate_focused_times(submissions, {"user": 1200}, "A")
        assert result == {}

    def test_calculate_focused_times_submission_without_relative_time(self):
        submissions = [
            {
                "verdict": "OK",
                "problem": {"index": "A"},
                "relativeTimeSeconds": None,
                "author": {"members": [{"handle": "user"}]},
            },
        ]
        result = TimeFactorService._calculate_focused_times(submissions, {"user": 1200}, "A")
        assert result == {}

    def test_time_factor_s_value_zero_with_none_time(self):
        result = TimeFactorService.calculate_time_factor(None, 600.0, 0.0)
        assert result == 1.0

    def test_bucket_median_single_value(self):
        data = {1200: [500.0]}
        result = TimeFactorService._get_bucket_median(data, 1200)
        # Only 1 value but MIN_BUCKET_SIZE=5, so expansion needed, but no adjacent buckets
        # Will return median of the 1 value
        assert result == 500.0

    def test_extract_contest_id_with_multi_letter_index(self):
        """Some problems have multi-letter indices like 'G1', 'H2'."""
        # Our regex only matches the first alpha after digits
        assert _extract_contest_id("1920G1") == 1920

    def test_multiple_reac_same_problem(self):
        """User re-ACs the same problem. Only the first sequential AC counts."""
        submissions = [
            _make_submission("user", "A", 300),
            _make_submission("user", "A", 500),  # re-AC
            _make_submission("user", "B", 1000),
        ]
        rating_changes = {"user": 1200}

        # Sorted by time: A@300, A@500, B@1000
        # Sequential (strictly increasing): A@300, A@500, B@1000
        # But when computing focused time for A, we use index 0 (first A@300)
        # focused A = 300 (first problem)
        result = TimeFactorService._calculate_focused_times(submissions, rating_changes, "A")
        assert 1200 in result
        assert 300.0 in result[1200]
