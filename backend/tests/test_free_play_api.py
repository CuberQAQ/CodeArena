"""API route tests for app/api/v1/free_play.py.

Tests cover all 6 free play endpoints:
  POST /free-play/search
  POST /free-play/recommend
  GET  /free-play/active
  POST /free-play/start
  POST /free-play/{session_id}/submit
  POST /free-play/{session_id}/quit
"""

from collections.abc import AsyncGenerator
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

SAMPLE_UUID = "00000000-0000-0000-0000-0000000000dd"


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


def _search_response_dict(**overrides):
    d = {
        "problem": {
            "contest_id": 1234,
            "index": "A",
            "name": "Test Problem",
            "rating": 1500,
            "tags": ["dp"],
            "url": "https://codeforces.com/contest/1234/problem/A",
        },
        "found": True,
        "message": "Problem found",
    }
    d.update(overrides)
    return d


def _recommend_response_dict(**overrides):
    d = {
        "problem": {
            "contest_id": 1234,
            "index": "B",
            "name": "Recommended Problem",
            "rating": 1400,
            "tags": ["greedy"],
            "url": "https://codeforces.com/contest/1234/problem/B",
        },
        "found": True,
        "message": "Recommended",
        "recommended_tag": "greedy",
    }
    d.update(overrides)
    return d


def _start_response_dict(**overrides):
    d = {
        "session_id": SAMPLE_UUID,
        "problem": {
            "contest_id": 1234,
            "index": "A",
            "name": "Test Problem",
            "rating": 1500,
            "tags": ["dp"],
            "url": "https://codeforces.com/contest/1234/problem/A",
        },
        "status": "active",
    }
    d.update(overrides)
    return d


def _submit_response_dict(**overrides):
    d = {
        "session_id": SAMPLE_UUID,
        "solved": True,
        "status": "completed",
        "elo_change": 5,
        "pp_change": 1.5,
        "s_value": 0.8,
        "tokens_earned": 20,
        "overkill_multiplier": 1.0,
        "achievements": [],
    }
    d.update(overrides)
    return d


def _quit_response_dict(**overrides):
    d = {
        "session_id": SAMPLE_UUID,
        "status": "quit",
        "elo_change": -5,
        "new_elo": 1395,
        "penalty": 5,
    }
    d.update(overrides)
    return d


# ===========================================================================
# POST /free-play/search
# ===========================================================================


class TestSearchProblems:
    """Tests for POST /free-play/search."""

    @patch("app.api.v1.free_play._get_cf_service")
    @patch("app.api.v1.free_play.FreePlayService")
    def test_search_found(self, mock_svc, mock_cf, app_client):
        result = _make_response_model(_search_response_dict())
        mock_svc.search_problems = AsyncMock(return_value=result)

        resp = app_client.post(
            "/free-play/search",
            json={"min_rating": 1200, "max_rating": 1600, "tags": ["dp"]},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["found"] is True
        assert body["message"] == "Search completed"

    @patch("app.api.v1.free_play._get_cf_service")
    @patch("app.api.v1.free_play.FreePlayService")
    def test_search_not_found(self, mock_svc, mock_cf, app_client):
        result = _make_response_model(
            _search_response_dict(problem=None, found=False, message="No problems found"),
        )
        mock_svc.search_problems = AsyncMock(return_value=result)

        resp = app_client.post(
            "/free-play/search",
            json={"min_rating": 1200, "max_rating": 1600},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["found"] is False

    def test_search_missing_min_rating(self, app_client):
        resp = app_client.post(
            "/free-play/search",
            json={"max_rating": 1600},
        )
        assert resp.status_code == 422

    def test_search_missing_max_rating(self, app_client):
        resp = app_client.post(
            "/free-play/search",
            json={"min_rating": 1200},
        )
        assert resp.status_code == 422

    def test_search_invalid_rating_below_range(self, app_client):
        resp = app_client.post(
            "/free-play/search",
            json={"min_rating": 500, "max_rating": 1600},
        )
        assert resp.status_code == 422

    def test_search_invalid_rating_above_range(self, app_client):
        resp = app_client.post(
            "/free-play/search",
            json={"min_rating": 1200, "max_rating": 4000},
        )
        assert resp.status_code == 422

    def test_search_empty_body(self, app_client):
        resp = app_client.post("/free-play/search", json={})
        assert resp.status_code == 422

    def test_search_unauthenticated(self):
        client = _unauth_client()
        resp = client.post(
            "/free-play/search",
            json={"min_rating": 1200, "max_rating": 1600},
        )
        assert resp.status_code == 401


# ===========================================================================
# POST /free-play/recommend
# ===========================================================================


class TestRecommendProblem:
    """Tests for POST /free-play/recommend."""

    @patch("app.api.v1.free_play._get_cf_service")
    @patch("app.api.v1.free_play.FreePlayService")
    def test_recommend_found(self, mock_svc, mock_cf, app_client):
        result = _make_response_model(_recommend_response_dict())
        mock_svc.recommend_problem = AsyncMock(return_value=result)

        resp = app_client.post("/free-play/recommend")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["found"] is True
        assert body["message"] == "Recommendation completed"

    @patch("app.api.v1.free_play._get_cf_service")
    @patch("app.api.v1.free_play.FreePlayService")
    def test_recommend_not_found(self, mock_svc, mock_cf, app_client):
        result = _make_response_model(
            _recommend_response_dict(problem=None, found=False, message="No suitable problem"),
        )
        mock_svc.recommend_problem = AsyncMock(return_value=result)

        resp = app_client.post("/free-play/recommend")
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["found"] is False

    def test_recommend_unauthenticated(self):
        client = _unauth_client()
        resp = client.post("/free-play/recommend")
        assert resp.status_code == 401

    def test_recommend_wrong_method(self, app_client):
        resp = app_client.get("/free-play/recommend")
        assert resp.status_code == 405


# ===========================================================================
# GET /free-play/active
# ===========================================================================


class TestGetActiveSession:
    """Tests for GET /free-play/active."""

    @patch("app.api.v1.free_play.FreePlayService")
    def test_active_session_found(self, mock_svc, app_client):
        result = _make_response_model(_start_response_dict())
        mock_svc.get_active_session = AsyncMock(return_value=result)

        resp = app_client.get("/free-play/active")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["message"] == "Active session found"

    @patch("app.api.v1.free_play.FreePlayService")
    def test_active_session_none(self, mock_svc, app_client):
        mock_svc.get_active_session = AsyncMock(return_value=None)

        resp = app_client.get("/free-play/active")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"] is None
        assert body["message"] == "No active session"

    def test_active_session_unauthenticated(self):
        client = _unauth_client()
        resp = client.get("/free-play/active")
        assert resp.status_code == 401

    def test_active_session_wrong_method(self, app_client):
        resp = app_client.post("/free-play/active")
        assert resp.status_code == 405


# ===========================================================================
# POST /free-play/start
# ===========================================================================


class TestStartSession:
    """Tests for POST /free-play/start."""

    @patch("app.api.v1.free_play.FreePlayService")
    def test_start_success(self, mock_svc, app_client):
        result = _make_response_model(_start_response_dict())
        mock_svc.start_session = AsyncMock(return_value=result)

        resp = app_client.post(
            "/free-play/start",
            json={
                "problem_contest_id": 1234,
                "problem_index": "A",
                "problem_rating": 1500,
                "problem_tags": ["dp"],
                "problem_name": "Test Problem",
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["status"] == "active"
        assert body["message"] == "Free Play session started"

    @patch("app.api.v1.free_play.FreePlayService")
    def test_start_minimal_fields(self, mock_svc, app_client):
        """Test start with only required fields (tags and name are optional)."""
        result = _make_response_model(_start_response_dict())
        mock_svc.start_session = AsyncMock(return_value=result)

        resp = app_client.post(
            "/free-play/start",
            json={
                "problem_contest_id": 1234,
                "problem_index": "A",
                "problem_rating": 1500,
            },
        )
        assert resp.status_code == 200

    def test_start_missing_contest_id(self, app_client):
        resp = app_client.post(
            "/free-play/start",
            json={"problem_index": "A", "problem_rating": 1500},
        )
        assert resp.status_code == 422

    def test_start_missing_index(self, app_client):
        resp = app_client.post(
            "/free-play/start",
            json={"problem_contest_id": 1234, "problem_rating": 1500},
        )
        assert resp.status_code == 422

    def test_start_missing_rating(self, app_client):
        resp = app_client.post(
            "/free-play/start",
            json={"problem_contest_id": 1234, "problem_index": "A"},
        )
        assert resp.status_code == 422

    def test_start_invalid_rating_below_range(self, app_client):
        resp = app_client.post(
            "/free-play/start",
            json={
                "problem_contest_id": 1234,
                "problem_index": "A",
                "problem_rating": 500,
            },
        )
        assert resp.status_code == 422

    def test_start_invalid_rating_above_range(self, app_client):
        resp = app_client.post(
            "/free-play/start",
            json={
                "problem_contest_id": 1234,
                "problem_index": "A",
                "problem_rating": 4000,
            },
        )
        assert resp.status_code == 422

    @patch("app.api.v1.free_play.FreePlayService")
    def test_start_already_active(self, mock_svc, app_client):
        mock_svc.start_session = AsyncMock(
            side_effect=BadRequestException("Already have an active session"),
        )

        resp = app_client.post(
            "/free-play/start",
            json={
                "problem_contest_id": 1234,
                "problem_index": "A",
                "problem_rating": 1500,
            },
        )
        assert resp.status_code == 400

    def test_start_unauthenticated(self):
        client = _unauth_client()
        resp = client.post(
            "/free-play/start",
            json={
                "problem_contest_id": 1234,
                "problem_index": "A",
                "problem_rating": 1500,
            },
        )
        assert resp.status_code == 401

    def test_start_wrong_method(self, app_client):
        resp = app_client.get("/free-play/start")
        assert resp.status_code == 405


# ===========================================================================
# POST /free-play/{session_id}/submit
# ===========================================================================


class TestSubmitResult:
    """Tests for POST /free-play/{session_id}/submit."""

    @patch("app.api.v1.free_play._get_cf_service")
    @patch("app.api.v1.free_play.FreePlayService")
    def test_submit_success(self, mock_svc, mock_cf, app_client):
        result = _make_response_model(_submit_response_dict())
        mock_svc.submit_result = AsyncMock(return_value=result)

        resp = app_client.post(
            f"/free-play/{SAMPLE_UUID}/submit",
            json={
                "solved": True,
                "time_spent": 120.5,
                "attempts": 1,
                "error_count": 0,
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["solved"] is True
        assert body["message"] == "Free Play session completed"

    @patch("app.api.v1.free_play._get_cf_service")
    @patch("app.api.v1.free_play.FreePlayService")
    def test_submit_not_solved(self, mock_svc, mock_cf, app_client):
        result = _make_response_model(
            _submit_response_dict(solved=False, elo_change=-3, tokens_earned=0),
        )
        mock_svc.submit_result = AsyncMock(return_value=result)

        resp = app_client.post(
            f"/free-play/{SAMPLE_UUID}/submit",
            json={"solved": False, "time_spent": 300, "attempts": 3, "error_count": 3},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["solved"] is False

    def test_submit_missing_solved(self, app_client):
        resp = app_client.post(
            f"/free-play/{SAMPLE_UUID}/submit",
            json={"time_spent": 60, "attempts": 1},
        )
        assert resp.status_code == 422

    def test_submit_missing_time_spent(self, app_client):
        resp = app_client.post(
            f"/free-play/{SAMPLE_UUID}/submit",
            json={"solved": True, "attempts": 1},
        )
        assert resp.status_code == 422

    def test_submit_missing_attempts(self, app_client):
        resp = app_client.post(
            f"/free-play/{SAMPLE_UUID}/submit",
            json={"solved": True, "time_spent": 60},
        )
        assert resp.status_code == 422

    def test_submit_negative_time_spent(self, app_client):
        resp = app_client.post(
            f"/free-play/{SAMPLE_UUID}/submit",
            json={"solved": True, "time_spent": -10, "attempts": 1},
        )
        assert resp.status_code == 422

    def test_submit_negative_attempts(self, app_client):
        resp = app_client.post(
            f"/free-play/{SAMPLE_UUID}/submit",
            json={"solved": True, "time_spent": 60, "attempts": -1},
        )
        assert resp.status_code == 422

    def test_submit_negative_error_count(self, app_client):
        resp = app_client.post(
            f"/free-play/{SAMPLE_UUID}/submit",
            json={"solved": True, "time_spent": 60, "attempts": 1, "error_count": -1},
        )
        assert resp.status_code == 422

    @patch("app.api.v1.free_play._get_cf_service")
    @patch("app.api.v1.free_play.FreePlayService")
    def test_submit_session_not_found(self, mock_svc, mock_cf, app_client):
        mock_svc.submit_result = AsyncMock(
            side_effect=NotFoundException("Session not found"),
        )

        resp = app_client.post(
            f"/free-play/{SAMPLE_UUID}/submit",
            json={"solved": True, "time_spent": 60, "attempts": 1},
        )
        assert resp.status_code == 404

    @patch("app.api.v1.free_play._get_cf_service")
    @patch("app.api.v1.free_play.FreePlayService")
    def test_submit_already_completed(self, mock_svc, mock_cf, app_client):
        mock_svc.submit_result = AsyncMock(
            side_effect=BadRequestException("Session already completed"),
        )

        resp = app_client.post(
            f"/free-play/{SAMPLE_UUID}/submit",
            json={"solved": True, "time_spent": 60, "attempts": 1},
        )
        assert resp.status_code == 400

    def test_submit_invalid_session_id(self, app_client):
        resp = app_client.post(
            "/free-play/bad-uuid/submit",
            json={"solved": True, "time_spent": 60, "attempts": 1},
        )
        assert resp.status_code == 422

    def test_submit_unauthenticated(self):
        client = _unauth_client()
        resp = client.post(
            f"/free-play/{SAMPLE_UUID}/submit",
            json={"solved": True, "time_spent": 60, "attempts": 1},
        )
        assert resp.status_code == 401


# ===========================================================================
# POST /free-play/{session_id}/quit
# ===========================================================================


class TestQuitSession:
    """Tests for POST /free-play/{session_id}/quit."""

    @patch("app.api.v1.free_play.FreePlayService")
    def test_quit_success(self, mock_svc, app_client):
        result = _make_response_model(_quit_response_dict())
        mock_svc.quit_session = AsyncMock(return_value=result)

        resp = app_client.post(f"/free-play/{SAMPLE_UUID}/quit")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["status"] == "quit"
        assert body["data"]["elo_change"] == -5
        assert body["message"] == "Free Play session quit"

    @patch("app.api.v1.free_play.FreePlayService")
    def test_quit_not_found(self, mock_svc, app_client):
        mock_svc.quit_session = AsyncMock(
            side_effect=NotFoundException("Session not found"),
        )

        resp = app_client.post(f"/free-play/{SAMPLE_UUID}/quit")
        assert resp.status_code == 404

    @patch("app.api.v1.free_play.FreePlayService")
    def test_quit_already_completed(self, mock_svc, app_client):
        mock_svc.quit_session = AsyncMock(
            side_effect=BadRequestException("Session already completed"),
        )

        resp = app_client.post(f"/free-play/{SAMPLE_UUID}/quit")
        assert resp.status_code == 400

    def test_quit_invalid_session_id(self, app_client):
        resp = app_client.post("/free-play/bad-uuid/quit")
        assert resp.status_code == 422

    def test_quit_unauthenticated(self):
        client = _unauth_client()
        resp = client.post(f"/free-play/{SAMPLE_UUID}/quit")
        assert resp.status_code == 401

    def test_quit_wrong_method(self, app_client):
        resp = app_client.get(f"/free-play/{SAMPLE_UUID}/quit")
        assert resp.status_code == 405


# ===========================================================================
# Cross-cutting: response envelope
# ===========================================================================


class TestFreePlayResponseEnvelope:
    """Verify all successful free play responses have standard envelope."""

    @patch("app.api.v1.free_play._get_cf_service")
    @patch("app.api.v1.free_play.FreePlayService")
    def test_search_envelope(self, mock_svc, mock_cf, app_client):
        result = _make_response_model(_search_response_dict())
        mock_svc.search_problems = AsyncMock(return_value=result)

        resp = app_client.post(
            "/free-play/search",
            json={"min_rating": 1200, "max_rating": 1600},
        )
        body = resp.json()
        assert "success" in body
        assert "data" in body
        assert "message" in body
        assert body["success"] is True

    @patch("app.api.v1.free_play.FreePlayService")
    def test_start_envelope(self, mock_svc, app_client):
        result = _make_response_model(_start_response_dict())
        mock_svc.start_session = AsyncMock(return_value=result)

        resp = app_client.post(
            "/free-play/start",
            json={
                "problem_contest_id": 1234,
                "problem_index": "A",
                "problem_rating": 1500,
            },
        )
        body = resp.json()
        assert "success" in body
        assert "data" in body
        assert "message" in body
        assert body["success"] is True
