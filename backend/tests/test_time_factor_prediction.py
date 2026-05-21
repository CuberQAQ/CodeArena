"""Tests for the time factor prediction API endpoint.

Tests cover:
- Successful prediction response with expected structure
- Time factor values within [0.5, 1.5] range
- Elo change estimates follow expected trend (faster = higher)
- Expected time calculation integration
- Error handling for missing/invalid parameters
"""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.services.time_factor_service import SECONDS_PER_MINUTE, TimeFactorService

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_calculate_expected_time():
    """Mock TimeFactorService.calculate_expected_time to return a fixed value."""
    with patch.object(
        TimeFactorService,
        "calculate_expected_time",
        new_callable=AsyncMock,
        return_value=15.0 * SECONDS_PER_MINUTE,  # 15 minutes in seconds
    ) as mock:
        yield mock


@pytest.fixture
def mock_calculate_expected_time_short():
    """Mock with a short expected time (5 minutes)."""
    with patch.object(
        TimeFactorService,
        "calculate_expected_time",
        new_callable=AsyncMock,
        return_value=5.0 * SECONDS_PER_MINUTE,  # 5 minutes in seconds
    ) as mock:
        yield mock


# ---------------------------------------------------------------------------
# Helper: get an authenticated test client
# ---------------------------------------------------------------------------


def _get_auth_client():
    """Create a test client with a mocked auth dependency."""
    from unittest.mock import MagicMock

    from fastapi import FastAPI

    from app.api.v1.router import api_router
    from app.core.security import get_current_user

    app = FastAPI()
    app.include_router(api_router)

    mock_user = MagicMock()
    mock_user.id = "test-user-id"
    mock_user.elo = 1400
    mock_user.is_admin = False

    app.dependency_overrides[get_current_user] = lambda: mock_user

    client = TestClient(app)
    return client


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestTimeFactorPredictionEndpoint:
    """Tests for GET /api/v1/time-factor-prediction."""

    def test_successful_prediction(self, mock_calculate_expected_time):
        """Test that the endpoint returns a valid prediction response."""
        client = _get_auth_client()

        response = client.get(
            "/time-factor-prediction",
            params={
                "problem_id": "1920A",
                "problem_rating": 1500,
                "user_elo": 1400,
            },
        )

        assert response.status_code == 200
        data = response.json()["data"]

        # Check structure
        assert "expected_time_minutes" in data
        assert "time_points" in data
        assert isinstance(data["time_points"], list)
        assert len(data["time_points"]) == 7  # 5, 10, 15, 20, 30, 45, 60

        # Check expected_time_minutes
        assert data["expected_time_minutes"] == 15.0

        # Check each time point structure
        for point in data["time_points"]:
            assert "minutes" in point
            assert "time_factor" in point
            assert "elo_change_estimate" in point
            assert isinstance(point["time_factor"], float)
            assert isinstance(point["elo_change_estimate"], int)

    def test_time_factor_range(self, mock_calculate_expected_time):
        """Test that all time factors are within [0.5, 1.5] range."""
        client = _get_auth_client()

        response = client.get(
            "/time-factor-prediction",
            params={
                "problem_id": "1920A",
                "problem_rating": 1500,
                "user_elo": 1400,
            },
        )

        data = response.json()["data"]
        for point in data["time_points"]:
            assert 0.5 <= point["time_factor"] <= 1.5, (
                f"time_factor {point['time_factor']} at {point['minutes']}min out of range"
            )

    def test_elo_trend_faster_is_better(self, mock_calculate_expected_time):
        """Test that earlier time points have higher Elo estimates."""
        client = _get_auth_client()

        response = client.get(
            "/time-factor-prediction",
            params={
                "problem_id": "1920A",
                "problem_rating": 1500,
                "user_elo": 1400,
            },
        )

        data = response.json()["data"]
        points = data["time_points"]

        # Elo change should be non-increasing over time (faster = better)
        for i in range(len(points) - 1):
            assert points[i]["elo_change_estimate"] >= points[i + 1]["elo_change_estimate"], (
                f"Elo at {points[i]['minutes']}min ({points[i]['elo_change_estimate']}) "
                f"should be >= Elo at {points[i + 1]['minutes']}min ({points[i + 1]['elo_change_estimate']})"
            )

    def test_expected_time_call_args(self, mock_calculate_expected_time):
        """Test that calculate_expected_time is called with correct arguments."""
        client = _get_auth_client()

        client.get(
            "/time-factor-prediction",
            params={
                "problem_id": "1920A",
                "problem_rating": 1500,
                "user_elo": 1400,
            },
        )

        mock_calculate_expected_time.assert_called_once()
        call_args = mock_calculate_expected_time.call_args
        # Positional args: cf_service, problem_id, problem_rating, user_rating
        assert call_args[0][1] == "1920A"  # problem_id
        assert call_args[0][2] == 1500  # problem_rating
        assert call_args[0][3] == 1400  # user_elo

    def test_expected_time_point_has_time_factor_one(self, mock_calculate_expected_time):
        """Test that the time point matching expected time has time_factor = 1.0."""
        client = _get_auth_client()

        response = client.get(
            "/time-factor-prediction",
            params={
                "problem_id": "1920A",
                "problem_rating": 1500,
                "user_elo": 1400,
            },
        )

        data = response.json()["data"]
        # Expected time is 15 minutes, which matches the 15-minute point
        point_15 = next(p for p in data["time_points"] if p["minutes"] == 15)
        assert point_15["time_factor"] == 1.0

    def test_fast_solve_max_factor(self, mock_calculate_expected_time):
        """Test that solving faster than expected gives time_factor = 1.0 (capped at max).

        The formula is: time_factor = T_expected / max(T_effective, T_expected).
        When T_effective < T_expected, calculate_time_factor gives > 1.0, capped at 1.5.
        This is the maximum possible factor -- solving much faster earns a bonus.
        """
        client = _get_auth_client()

        response = client.get(
            "/time-factor-prediction",
            params={
                "problem_id": "1920A",
                "problem_rating": 1500,
                "user_elo": 1400,
            },
        )

        data = response.json()["data"]
        # At 5 min (much faster than 15 min expected), factor should be 1.5 (max)
        point_5 = next(p for p in data["time_points"] if p["minutes"] == 5)
        assert point_5["time_factor"] == 1.5

        # At 10 min (still faster than 15 min expected), factor > 1.0
        point_10 = next(p for p in data["time_points"] if p["minutes"] == 10)
        assert point_10["time_factor"] == 1.5

    def test_slow_solve_lower_factor(self, mock_calculate_expected_time):
        """Test that solving slower than expected gives time_factor < 1.0."""
        client = _get_auth_client()

        response = client.get(
            "/time-factor-prediction",
            params={
                "problem_id": "1920A",
                "problem_rating": 1500,
                "user_elo": 1400,
            },
        )

        data = response.json()["data"]
        # At 60 min (much slower than 15 min expected), factor should be < 1.0
        point_60 = next(p for p in data["time_points"] if p["minutes"] == 60)
        assert point_60["time_factor"] < 1.0

    def test_short_expected_time_capped(self, mock_calculate_expected_time_short):
        """Test that with very short expected time, slow solves are capped at 0.5."""
        client = _get_auth_client()

        response = client.get(
            "/time-factor-prediction",
            params={
                "problem_id": "1920A",
                "problem_rating": 1200,
                "user_elo": 1400,
            },
        )

        data = response.json()["data"]
        # Expected time is 5 min. At 60 min (12x slower), factor should be 0.5 (capped)
        point_60 = next(p for p in data["time_points"] if p["minutes"] == 60)
        assert point_60["time_factor"] == 0.5

    def test_missing_params_returns_422(self, mock_calculate_expected_time):
        """Test that missing required parameters returns 422."""
        client = _get_auth_client()

        response = client.get("/time-factor-prediction")
        assert response.status_code == 422

    def test_missing_problem_id_returns_422(self, mock_calculate_expected_time):
        """Test that missing problem_id returns 422."""
        client = _get_auth_client()

        response = client.get(
            "/time-factor-prediction",
            params={
                "problem_rating": 1500,
                "user_elo": 1400,
            },
        )
        assert response.status_code == 422

    def test_invalid_rating_range_returns_422(self, mock_calculate_expected_time):
        """Test that out-of-range rating returns 422."""
        client = _get_auth_client()

        response = client.get(
            "/time-factor-prediction",
            params={
                "problem_id": "1920A",
                "problem_rating": 500,  # below 800 minimum
                "user_elo": 1400,
            },
        )
        assert response.status_code == 422

    def test_response_success_flag(self, mock_calculate_expected_time):
        """Test that the response has success: true."""
        client = _get_auth_client()

        response = client.get(
            "/time-factor-prediction",
            params={
                "problem_id": "1920A",
                "problem_rating": 1500,
                "user_elo": 1400,
            },
        )

        assert response.json()["success"] is True

    def test_time_points_at_expected_minutes(self, mock_calculate_expected_time):
        """Test that time_points contain the 7 expected minute values."""
        client = _get_auth_client()

        response = client.get(
            "/time-factor-prediction",
            params={
                "problem_id": "1920A",
                "problem_rating": 1500,
                "user_elo": 1400,
            },
        )

        data = response.json()["data"]
        minutes = [p["minutes"] for p in data["time_points"]]
        assert minutes == [5, 10, 15, 20, 30, 45, 60]
