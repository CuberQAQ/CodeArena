"""API route tests for app/api/v1/contest.py.

Tests cover all 9 contest endpoints:
  GET  /contest/tiers
  POST /contest/start
  GET  /contest/history
  GET  /contest/active
  GET  /contest/{contest_id}
  POST /contest/{contest_id}/submit
  POST /contest/{contest_id}/end
  GET  /contest/{contest_id}/result
  GET  /contest/{contest_id}/leaderboard
"""

from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.router import api_router
from app.core.database import get_db
from app.core.exceptions import (
    BadRequestException,
    ForbiddenException,
    NotFoundException,
    UnauthorizedException,
    register_exception_handlers,
)
from app.core.security import get_current_user

# ---------------------------------------------------------------------------
# App factory & mock DB
# ---------------------------------------------------------------------------


async def _mock_get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield a mock async session; never touches real DB."""
    session = MagicMock(spec=AsyncSession)
    session.execute = AsyncMock(return_value=MagicMock())
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.close = AsyncMock()
    session.flush = AsyncMock()
    session.add = MagicMock()
    yield session


def _create_app() -> FastAPI:
    """Create a FastAPI app with routers and exception handlers registered."""
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(api_router)
    app.state.settings = SimpleNamespace(DEBUG=False)
    app.dependency_overrides[get_db] = _mock_get_db
    return app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_UUID = "00000000-0000-0000-0000-0000000000cc"


def _make_mock_user(**overrides):
    user = MagicMock()
    user.id = "00000000-0000-0000-0000-000000000001"
    user.username = "testuser"
    user.email = "test@example.com"
    user.elo = 1400
    user.pp = 50.0
    user.tokens = 100
    user.is_active = True
    user.is_admin = False
    for k, v in overrides.items():
        setattr(user, k, v)
    return user


@pytest.fixture()
def mock_user():
    return _make_mock_user()


@pytest.fixture()
def app_client(mock_user):
    app = _create_app()
    app.dependency_overrides[get_current_user] = lambda: mock_user
    return TestClient(app)


def _unauth_client():
    app = _create_app()

    def _raise_unauth():
        raise UnauthorizedException(message="Not authenticated")

    app.dependency_overrides[get_current_user] = _raise_unauth
    return TestClient(app)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_response_model(data_dict):
    """Create a MagicMock that has .model_dump() returning the dict."""
    mock_obj = MagicMock()
    mock_obj.model_dump.return_value = data_dict
    return mock_obj


def _tier_info_dict(**overrides):
    d = {
        "tier": "beginner",
        "name": "Beginner Contest",
        "div": 4,
        "min_elo": None,
        "max_elo": 1399,
        "duration_minutes": 120,
        "problem_count": 7,
        "rating_range": [800, 1400],
        "eligible": True,
        "is_rated": True,
    }
    d.update(overrides)
    return d


def _contest_session_dict(**overrides):
    d = {
        "id": SAMPLE_UUID,
        "tier": "beginner",
        "problems": [],
        "total_problems": 7,
        "problems_solved": 0,
        "submissions": 0,
        "time_limit_minutes": 120,
        "started_at": datetime(2025, 1, 1, tzinfo=UTC).isoformat(),
        "ended_at": None,
        "remaining_seconds": 7200.0,
        "end_time": datetime(2025, 1, 1, 2, 0, tzinfo=UTC).isoformat(),
        "status": "active",
        "elo_change": None,
    }
    d.update(overrides)
    return d


def _submit_response_dict(**overrides):
    d = {
        "contest_id": SAMPLE_UUID,
        "problem_id": "1234A",
        "solved": True,
        "tokens_earned": 20,
    }
    d.update(overrides)
    return d


def _contest_result_dict(**overrides):
    d = {
        "id": SAMPLE_UUID,
        "tier": "beginner",
        "total_problems": 7,
        "problems_solved": 2,
        "submissions": 5,
        "time_limit_minutes": 120,
        "started_at": datetime(2025, 1, 1, tzinfo=UTC).isoformat(),
        "ended_at": datetime(2025, 1, 1, 2, 0, tzinfo=UTC).isoformat(),
        "status": "completed",
        "elo_change": 12,
        "performance_rating": 1450,
        "medal": {"level": "gold", "type": "overall"},
        "problems": [],
        "achievements": [],
    }
    d.update(overrides)
    return d


def _history_item_dict(**overrides):
    d = {
        "id": SAMPLE_UUID,
        "tier": "beginner",
        "total_problems": 7,
        "problems_solved": 2,
        "submissions": 5,
        "time_limit_minutes": 120,
        "started_at": datetime(2025, 1, 1, tzinfo=UTC).isoformat(),
        "ended_at": datetime(2025, 1, 1, 2, 0, tzinfo=UTC).isoformat(),
        "status": "completed",
        "elo_change": 12,
    }
    d.update(overrides)
    return d


def _leaderboard_dict(**overrides):
    d = {
        "leaderboard": [
            {"rank": 1, "name": "testuser", "elo": 1400, "solved": 2, "is_bot": False},
            {"rank": 2, "name": "Bot-1500", "elo": 1500, "solved": 1, "is_bot": True},
        ],
        "time_elapsed": 1200,
        "time_total": 5400,
    }
    d.update(overrides)
    return d


# ===========================================================================
# GET /contest/tiers
# ===========================================================================


class TestGetTiers:
    """Tests for GET /contest/tiers."""

    @patch("app.api.v1.contest.ContestService")
    def test_get_tiers_success(self, mock_svc, app_client):
        t1 = _make_response_model(_tier_info_dict())
        t2 = _make_response_model(_tier_info_dict(tier="advanced", name="Advanced"))
        mock_svc.get_tiers = AsyncMock(return_value=[t1, t2])

        resp = app_client.get("/contest/tiers")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert len(body["data"]) == 2
        assert body["message"] == "Tiers retrieved"

    @patch("app.api.v1.contest.ContestService")
    def test_get_tiers_eligibility(self, mock_svc, app_client):
        tier = _make_response_model(_tier_info_dict(eligible=True))
        mock_svc.get_tiers = AsyncMock(return_value=[tier])

        resp = app_client.get("/contest/tiers")
        assert resp.status_code == 200
        assert resp.json()["data"][0]["eligible"] is True

    def test_get_tiers_unauthenticated(self):
        client = _unauth_client()
        resp = client.get("/contest/tiers")
        assert resp.status_code == 401

    def test_get_tiers_wrong_method(self, app_client):
        resp = app_client.post("/contest/tiers")
        assert resp.status_code == 405


# ===========================================================================
# POST /contest/start
# ===========================================================================


class TestStartContest:
    """Tests for POST /contest/start."""

    @patch("app.api.v1.contest._get_cf_service")
    @patch("app.api.v1.contest.ContestService")
    def test_start_success(self, mock_svc, mock_cf, app_client):
        session = _make_response_model(_contest_session_dict())
        mock_svc.start_contest = AsyncMock(return_value=session)

        resp = app_client.post("/contest/start", json={"tier": "beginner"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["status"] == "active"
        assert body["message"] == "Contest started"

    def test_start_missing_tier(self, app_client):
        resp = app_client.post("/contest/start", json={})
        assert resp.status_code == 422

    @patch("app.api.v1.contest._get_cf_service")
    @patch("app.api.v1.contest.ContestService")
    def test_start_not_eligible(self, mock_svc, mock_cf, app_client):
        mock_svc.start_contest = AsyncMock(
            side_effect=ForbiddenException("Not eligible for this tier"),
        )

        resp = app_client.post("/contest/start", json={"tier": "master"})
        assert resp.status_code == 403

    @patch("app.api.v1.contest._get_cf_service")
    @patch("app.api.v1.contest.ContestService")
    def test_start_already_active(self, mock_svc, mock_cf, app_client):
        mock_svc.start_contest = AsyncMock(
            side_effect=BadRequestException("Already have an active contest"),
        )

        resp = app_client.post("/contest/start", json={"tier": "beginner"})
        assert resp.status_code == 400

    def test_start_unauthenticated(self):
        client = _unauth_client()
        resp = client.post("/contest/start", json={"tier": "beginner"})
        assert resp.status_code == 401

    def test_start_wrong_method(self, app_client):
        # GET /contest/start matches /{contest_id} with contest_id="start",
        # so it returns 422 (invalid UUID). Use PUT to test 405.
        resp = app_client.put("/contest/start", json={"tier": "beginner"})
        assert resp.status_code == 405


# ===========================================================================
# GET /contest/history
# ===========================================================================


class TestGetContestHistory:
    """Tests for GET /contest/history."""

    @patch("app.api.v1.contest.ContestService")
    def test_history_success(self, mock_svc, app_client):
        h1 = _make_response_model(_history_item_dict())
        mock_svc.get_contest_history = AsyncMock(return_value=[h1])

        resp = app_client.get("/contest/history")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert len(body["data"]) == 1
        assert body["data"][0]["status"] == "completed"
        assert body["message"] == "Contest history retrieved"

    @patch("app.api.v1.contest.ContestService")
    def test_history_empty(self, mock_svc, app_client):
        mock_svc.get_contest_history = AsyncMock(return_value=[])

        resp = app_client.get("/contest/history")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"] == []

    def test_history_unauthenticated(self):
        client = _unauth_client()
        resp = client.get("/contest/history")
        assert resp.status_code == 401


# ===========================================================================
# GET /contest/active
# ===========================================================================


class TestGetActiveContest:
    """Tests for GET /contest/active."""

    @patch("app.api.v1.contest.ContestService")
    def test_active_contest_found(self, mock_svc, app_client):
        session = _make_response_model(_contest_session_dict())
        mock_svc.get_active_contest = AsyncMock(return_value=session)

        resp = app_client.get("/contest/active")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["status"] == "active"
        assert body["message"] == "Active contest retrieved"

    @patch("app.api.v1.contest.ContestService")
    def test_active_contest_none(self, mock_svc, app_client):
        mock_svc.get_active_contest = AsyncMock(return_value=None)

        resp = app_client.get("/contest/active")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"] is None
        assert body["message"] == "Active contest retrieved"

    def test_active_contest_unauthenticated(self):
        client = _unauth_client()
        resp = client.get("/contest/active")
        assert resp.status_code == 401

    def test_active_contest_wrong_method(self, app_client):
        resp = app_client.post("/contest/active")
        assert resp.status_code == 405


# ===========================================================================
# GET /contest/{contest_id}
# ===========================================================================


class TestGetContestStatus:
    """Tests for GET /contest/{contest_id}."""

    @patch("app.api.v1.contest.ContestService")
    def test_status_success(self, mock_svc, app_client):
        session = _make_response_model(_contest_session_dict())
        mock_svc.get_contest_status = AsyncMock(return_value=session)

        resp = app_client.get(f"/contest/{SAMPLE_UUID}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["id"] == SAMPLE_UUID
        assert body["message"] == "Contest status retrieved"

    @patch("app.api.v1.contest.ContestService")
    def test_status_not_found(self, mock_svc, app_client):
        mock_svc.get_contest_status = AsyncMock(
            side_effect=NotFoundException("Contest not found"),
        )

        resp = app_client.get(f"/contest/{SAMPLE_UUID}")
        assert resp.status_code == 404

    def test_status_invalid_uuid(self, app_client):
        resp = app_client.get("/contest/not-a-uuid")
        assert resp.status_code == 422

    def test_status_unauthenticated(self):
        client = _unauth_client()
        resp = client.get(f"/contest/{SAMPLE_UUID}")
        assert resp.status_code == 401


# ===========================================================================
# POST /contest/{contest_id}/submit
# ===========================================================================


class TestSubmitContestProblem:
    """Tests for POST /contest/{contest_id}/submit."""

    @patch("app.api.v1.contest._get_cf_service")
    @patch("app.api.v1.contest.ContestService")
    def test_submit_success(self, mock_svc, mock_cf, app_client):
        result = _make_response_model(_submit_response_dict())
        mock_svc.submit_problem = AsyncMock(return_value=result)

        resp = app_client.post(
            f"/contest/{SAMPLE_UUID}/submit",
            json={
                "problem_id": "1234A",
                "solved": True,
                "attempts": 1,
                "time_spent": 120.5,
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["solved"] is True
        assert body["message"] == "Problem result submitted"

    def test_submit_missing_fields(self, app_client):
        resp = app_client.post(f"/contest/{SAMPLE_UUID}/submit", json={})
        assert resp.status_code == 422

    def test_submit_negative_attempts(self, app_client):
        resp = app_client.post(
            f"/contest/{SAMPLE_UUID}/submit",
            json={"problem_id": "1234A", "solved": True, "attempts": -1, "time_spent": 60},
        )
        assert resp.status_code == 422

    def test_submit_negative_time_spent(self, app_client):
        resp = app_client.post(
            f"/contest/{SAMPLE_UUID}/submit",
            json={"problem_id": "1234A", "solved": True, "attempts": 1, "time_spent": -10},
        )
        assert resp.status_code == 422

    @patch("app.api.v1.contest._get_cf_service")
    @patch("app.api.v1.contest.ContestService")
    def test_submit_contest_not_found(self, mock_svc, mock_cf, app_client):
        mock_svc.submit_problem = AsyncMock(
            side_effect=NotFoundException("Contest not found"),
        )

        resp = app_client.post(
            f"/contest/{SAMPLE_UUID}/submit",
            json={"problem_id": "1234A", "solved": True, "attempts": 1, "time_spent": 60},
        )
        assert resp.status_code == 404

    @patch("app.api.v1.contest._get_cf_service")
    @patch("app.api.v1.contest.ContestService")
    def test_submit_already_submitted(self, mock_svc, mock_cf, app_client):
        mock_svc.submit_problem = AsyncMock(
            side_effect=BadRequestException("Problem already submitted"),
        )

        resp = app_client.post(
            f"/contest/{SAMPLE_UUID}/submit",
            json={"problem_id": "1234A", "solved": True, "attempts": 1, "time_spent": 60},
        )
        assert resp.status_code == 400

    def test_submit_invalid_contest_id(self, app_client):
        resp = app_client.post(
            "/contest/bad-uuid/submit",
            json={"problem_id": "1234A", "solved": True, "attempts": 1, "time_spent": 60},
        )
        assert resp.status_code == 422

    def test_submit_unauthenticated(self):
        client = _unauth_client()
        resp = client.post(
            f"/contest/{SAMPLE_UUID}/submit",
            json={"problem_id": "1234A", "solved": True, "attempts": 1, "time_spent": 60},
        )
        assert resp.status_code == 401


# ===========================================================================
# POST /contest/{contest_id}/end
# ===========================================================================


class TestEndContest:
    """Tests for POST /contest/{contest_id}/end."""

    @patch("app.api.v1.contest._get_cf_service")
    @patch("app.api.v1.contest.ContestService")
    def test_end_success(self, mock_svc, mock_cf, app_client):
        result = _make_response_model(_contest_result_dict())
        mock_svc.end_contest = AsyncMock(return_value=result)

        resp = app_client.post(f"/contest/{SAMPLE_UUID}/end")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["status"] == "completed"
        assert body["message"] == "Contest ended"

    @patch("app.api.v1.contest._get_cf_service")
    @patch("app.api.v1.contest.ContestService")
    def test_end_not_found(self, mock_svc, mock_cf, app_client):
        mock_svc.end_contest = AsyncMock(
            side_effect=NotFoundException("Contest not found"),
        )

        resp = app_client.post(f"/contest/{SAMPLE_UUID}/end")
        assert resp.status_code == 404

    @patch("app.api.v1.contest._get_cf_service")
    @patch("app.api.v1.contest.ContestService")
    def test_end_already_ended(self, mock_svc, mock_cf, app_client):
        mock_svc.end_contest = AsyncMock(
            side_effect=BadRequestException("Contest already ended"),
        )

        resp = app_client.post(f"/contest/{SAMPLE_UUID}/end")
        assert resp.status_code == 400

    def test_end_invalid_contest_id(self, app_client):
        resp = app_client.post("/contest/bad-uuid/end")
        assert resp.status_code == 422

    def test_end_unauthenticated(self):
        client = _unauth_client()
        resp = client.post(f"/contest/{SAMPLE_UUID}/end")
        assert resp.status_code == 401

    def test_end_wrong_method(self, app_client):
        resp = app_client.get(f"/contest/{SAMPLE_UUID}/end")
        assert resp.status_code == 405


# ===========================================================================
# GET /contest/{contest_id}/result
# ===========================================================================


class TestGetContestResult:
    """Tests for GET /contest/{contest_id}/result."""

    @patch("app.api.v1.contest.ContestService")
    def test_result_success(self, mock_svc, app_client):
        result = _make_response_model(_contest_result_dict())
        mock_svc.get_contest_result = AsyncMock(return_value=result)

        resp = app_client.get(f"/contest/{SAMPLE_UUID}/result")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["status"] == "completed"
        assert body["data"]["elo_change"] == 12
        assert body["message"] == "Contest result retrieved"

    @patch("app.api.v1.contest.ContestService")
    def test_result_not_found(self, mock_svc, app_client):
        mock_svc.get_contest_result = AsyncMock(
            side_effect=NotFoundException("Contest not found"),
        )

        resp = app_client.get(f"/contest/{SAMPLE_UUID}/result")
        assert resp.status_code == 404

    def test_result_invalid_uuid(self, app_client):
        resp = app_client.get("/contest/bad-uuid/result")
        assert resp.status_code == 422

    def test_result_unauthenticated(self):
        client = _unauth_client()
        resp = client.get(f"/contest/{SAMPLE_UUID}/result")
        assert resp.status_code == 401


# ===========================================================================
# GET /contest/{contest_id}/leaderboard
# ===========================================================================


class TestGetLeaderboard:
    """Tests for GET /contest/{contest_id}/leaderboard."""

    @patch("app.api.v1.contest.ContestService")
    def test_leaderboard_success(self, mock_svc, app_client):
        lb = _make_response_model(_leaderboard_dict())
        mock_svc.get_leaderboard = AsyncMock(return_value=lb)

        resp = app_client.get(f"/contest/{SAMPLE_UUID}/leaderboard")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert len(body["data"]["leaderboard"]) == 2
        assert body["data"]["time_elapsed"] == 1200
        assert body["message"] == "Leaderboard retrieved"

    @patch("app.api.v1.contest.ContestService")
    def test_leaderboard_not_found(self, mock_svc, app_client):
        mock_svc.get_leaderboard = AsyncMock(
            side_effect=NotFoundException("Contest not found"),
        )

        resp = app_client.get(f"/contest/{SAMPLE_UUID}/leaderboard")
        assert resp.status_code == 404

    def test_leaderboard_invalid_uuid(self, app_client):
        resp = app_client.get("/contest/bad-uuid/leaderboard")
        assert resp.status_code == 422

    def test_leaderboard_unauthenticated(self):
        client = _unauth_client()
        resp = client.get(f"/contest/{SAMPLE_UUID}/leaderboard")
        assert resp.status_code == 401


# ===========================================================================
# Cross-cutting: response envelope
# ===========================================================================


class TestContestResponseEnvelope:
    """Verify all successful contest responses have standard envelope."""

    @patch("app.api.v1.contest.ContestService")
    def test_tiers_envelope(self, mock_svc, app_client):
        mock_svc.get_tiers = AsyncMock(return_value=[])

        resp = app_client.get("/contest/tiers")
        body = resp.json()
        assert "success" in body
        assert "data" in body
        assert "message" in body
        assert body["success"] is True

    @patch("app.api.v1.contest._get_cf_service")
    @patch("app.api.v1.contest.ContestService")
    def test_start_envelope(self, mock_svc, mock_cf, app_client):
        session = _make_response_model(_contest_session_dict())
        mock_svc.start_contest = AsyncMock(return_value=session)

        resp = app_client.post("/contest/start", json={"tier": "beginner"})
        body = resp.json()
        assert "success" in body
        assert "data" in body
        assert "message" in body
        assert body["success"] is True

    @patch("app.api.v1.contest._get_cf_service")
    @patch("app.api.v1.contest.ContestService")
    def test_end_envelope(self, mock_svc, mock_cf, app_client):
        result = _make_response_model(_contest_result_dict())
        mock_svc.end_contest = AsyncMock(return_value=result)

        resp = app_client.post(f"/contest/{SAMPLE_UUID}/end")
        body = resp.json()
        assert "success" in body
        assert "data" in body
        assert "message" in body
        assert body["success"] is True
