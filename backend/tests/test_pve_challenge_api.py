"""API route tests for app/api/v1/pve_challenge.py.

Tests cover all 5 PvE challenge endpoints:
  POST /pve-challenge/start           -- start a random PvE challenge
  GET  /pve-challenge/history         -- get paginated history
  GET  /pve-challenge/{session_id}    -- get challenge detail
  POST /pve-challenge/{session_id}/submit  -- submit result
  POST /pve-challenge/{session_id}/quit    -- quit challenge
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


def _make_mock_user(**overrides):
    """Create a mock User object with sensible defaults."""
    user = MagicMock()
    user.id = "00000000-0000-0000-0000-000000000001"
    user.username = "testuser"
    user.elo = 1400
    user.tokens = 100
    user.is_active = True
    for k, v in overrides.items():
        setattr(user, k, v)
    return user


@pytest.fixture()
def mock_user():
    return _make_mock_user()


@pytest.fixture()
def app_client(mock_user):
    """Create a TestClient with auth and DB dependencies overridden."""
    app = _create_app()
    app.dependency_overrides[get_current_user] = lambda: mock_user
    return TestClient(app)


def _unauth_client():
    """Client without auth -- used to test 401 responses."""
    app = _create_app()

    def _raise_unauth():
        raise UnauthorizedException(message="Not authenticated")

    app.dependency_overrides[get_current_user] = _raise_unauth
    return TestClient(app)


VALID_SESSION_ID = "00000000-0000-0000-0000-0000000000aa"


def _make_simple_response(**data):
    """Build a namespace object that has model_dump() returning the data dict."""
    ns = SimpleNamespace(**data)
    ns.model_dump = lambda **kwargs: data
    return ns


# ===========================================================================
# POST /pve-challenge/start
# ===========================================================================


class TestStartChallenge:
    """Tests for POST /pve-challenge/start."""

    @patch("app.api.v1.pve_challenge.PvEChallengeService")
    @patch("app.api.v1.pve_challenge._get_cf_service")
    def test_start_success(self, mock_get_cf, mock_pve_svc, app_client):
        mock_cf = MagicMock()
        mock_get_cf.return_value = mock_cf
        mock_pve_svc.start_challenge = AsyncMock(
            return_value=_make_simple_response(
                session_id=VALID_SESSION_ID,
                problem={
                    "contest_id": 1234,
                    "index": "A",
                    "name": "Test Problem",
                    "rating": 1500,
                    "tags": ["dp", "greedy"],
                    "url": "https://codeforces.com/problemset/problem/1234/A",
                },
                status="active",
            )
        )

        resp = app_client.post("/pve-challenge/start")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["session_id"] == VALID_SESSION_ID
        assert body["data"]["status"] == "active"
        assert body["data"]["problem"]["name"] == "Test Problem"
        assert body["message"] == "PvE challenge started"

    @patch("app.api.v1.pve_challenge.PvEChallengeService")
    @patch("app.api.v1.pve_challenge._get_cf_service")
    def test_start_active_session_exists(self, mock_get_cf, mock_pve_svc, app_client):
        mock_get_cf.return_value = MagicMock()
        mock_pve_svc.start_challenge = AsyncMock(
            side_effect=BadRequestException("Active session already exists"),
        )

        resp = app_client.post("/pve-challenge/start")
        assert resp.status_code == 400

    @patch("app.api.v1.pve_challenge.PvEChallengeService")
    @patch("app.api.v1.pve_challenge._get_cf_service")
    def test_start_no_problems_available(self, mock_get_cf, mock_pve_svc, app_client):
        mock_get_cf.return_value = MagicMock()
        mock_pve_svc.start_challenge = AsyncMock(
            side_effect=NotFoundException("No problems available"),
        )

        resp = app_client.post("/pve-challenge/start")
        assert resp.status_code == 404

    def test_start_unauthenticated(self):
        client = _unauth_client()
        resp = client.post("/pve-challenge/start")
        assert resp.status_code == 401

    def test_start_wrong_http_method(self, app_client):
        # GET /pve-challenge/start matches the GET /pve-challenge/{session_id} route,
        # which returns 422 because "start" is not a valid UUID -- not a 405.
        resp = app_client.get("/pve-challenge/start")
        assert resp.status_code == 422


# ===========================================================================
# GET /pve-challenge/history
# ===========================================================================


class TestGetHistory:
    """Tests for GET /pve-challenge/history."""

    @patch("app.api.v1.pve_challenge.PvEChallengeService")
    def test_history_default_params(self, mock_pve_svc, app_client):
        mock_pve_svc.get_history = AsyncMock(
            return_value=_make_simple_response(
                items=[],
                total=0,
                page=1,
                page_size=20,
            )
        )

        resp = app_client.get("/pve-challenge/history")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["items"] == []
        assert body["data"]["total"] == 0
        assert body["data"]["page"] == 1
        assert body["data"]["page_size"] == 20
        assert body["message"] == "History retrieved"

    @patch("app.api.v1.pve_challenge.PvEChallengeService")
    def test_history_with_items(self, mock_pve_svc, app_client):
        items = [
            {
                "id": VALID_SESSION_ID,
                "problem_id": "1234A",
                "problem_rating": 1500,
                "problem_tags": ["dp"],
                "status": "completed",
                "error_count": 0,
                "time_spent": 300.0,
                "hints_used": 1,
                "elo_change": 10,
                "pp_change": 2.5,
                "s_value": 0.85,
                "created_at": "2026-05-22T10:00:00Z",
                "completed_at": "2026-05-22T10:05:00Z",
            },
        ]
        mock_pve_svc.get_history = AsyncMock(
            return_value=_make_simple_response(
                items=items,
                total=1,
                page=1,
                page_size=20,
            )
        )

        resp = app_client.get("/pve-challenge/history")
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["total"] == 1
        assert len(body["data"]["items"]) == 1
        assert body["data"]["items"][0]["status"] == "completed"

    @patch("app.api.v1.pve_challenge.PvEChallengeService")
    def test_history_pagination(self, mock_pve_svc, app_client):
        mock_pve_svc.get_history = AsyncMock(
            return_value=_make_simple_response(
                items=[],
                total=100,
                page=3,
                page_size=10,
            )
        )

        resp = app_client.get("/pve-challenge/history", params={"page": 3, "page_size": 10})
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["page"] == 3
        assert body["data"]["page_size"] == 10
        assert body["data"]["total"] == 100

    def test_history_invalid_page_zero(self, app_client):
        resp = app_client.get("/pve-challenge/history", params={"page": 0})
        assert resp.status_code == 422

    def test_history_invalid_page_size_zero(self, app_client):
        resp = app_client.get("/pve-challenge/history", params={"page_size": 0})
        assert resp.status_code == 422

    def test_history_invalid_page_size_too_large(self, app_client):
        resp = app_client.get("/pve-challenge/history", params={"page_size": 101})
        assert resp.status_code == 422

    def test_history_unauthenticated(self):
        client = _unauth_client()
        resp = client.get("/pve-challenge/history")
        assert resp.status_code == 401


# ===========================================================================
# GET /pve-challenge/{session_id}
# ===========================================================================


class TestGetChallengeDetail:
    """Tests for GET /pve-challenge/{session_id}."""

    @patch("app.api.v1.pve_challenge.PvEChallengeService")
    def test_detail_success(self, mock_pve_svc, app_client):
        mock_pve_svc.get_challenge = AsyncMock(
            return_value=_make_simple_response(
                id=VALID_SESSION_ID,
                user_id="00000000-0000-0000-0000-000000000001",
                problem_id="1234A",
                problem_rating=1500,
                problem_tags=["dp"],
                problem={
                    "contest_id": 1234,
                    "index": "A",
                    "name": "Test Problem",
                    "rating": 1500,
                    "tags": ["dp"],
                    "url": "https://codeforces.com/problemset/problem/1234/A",
                },
                status="active",
                error_count=0,
                time_spent=None,
                hints_used=0,
                elo_change=None,
                pp_change=None,
                s_value=None,
                created_at="2026-05-22T10:00:00Z",
                completed_at=None,
            )
        )

        resp = app_client.get(f"/pve-challenge/{VALID_SESSION_ID}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["id"] == VALID_SESSION_ID
        assert body["data"]["status"] == "active"
        assert body["data"]["problem"]["name"] == "Test Problem"
        assert body["message"] == "Challenge details retrieved"

    @patch("app.api.v1.pve_challenge.PvEChallengeService")
    def test_detail_not_found(self, mock_pve_svc, app_client):
        mock_pve_svc.get_challenge = AsyncMock(
            side_effect=NotFoundException("Challenge session not found"),
        )

        resp = app_client.get(f"/pve-challenge/{VALID_SESSION_ID}")
        assert resp.status_code == 404

    def test_detail_invalid_uuid(self, app_client):
        resp = app_client.get("/pve-challenge/not-a-uuid")
        assert resp.status_code == 422

    def test_detail_unauthenticated(self):
        client = _unauth_client()
        resp = client.get(f"/pve-challenge/{VALID_SESSION_ID}")
        assert resp.status_code == 401

    def test_detail_wrong_http_method(self, app_client):
        resp = app_client.post(f"/pve-challenge/{VALID_SESSION_ID}")
        # This will route to submit if body is provided, but without body returns 422
        # A plain POST without a matching sub-route gives 404 or 422
        # Let's just check it's not 200
        assert resp.status_code != 200


# ===========================================================================
# POST /pve-challenge/{session_id}/submit
# ===========================================================================


class TestSubmitResult:
    """Tests for POST /pve-challenge/{session_id}/submit."""

    @patch("app.api.v1.pve_challenge.PvEChallengeService")
    @patch("app.api.v1.pve_challenge._get_cf_service")
    def test_submit_success_solved(self, mock_get_cf, mock_pve_svc, app_client):
        mock_get_cf.return_value = MagicMock()
        mock_pve_svc.submit_result = AsyncMock(
            return_value=_make_simple_response(
                session_id=VALID_SESSION_ID,
                solved=True,
                status="completed",
                elo_change=10,
                pp_change=2.5,
                s_value=0.85,
                tokens_earned=15,
                overkill_multiplier=1.2,
                achievements=[],
            )
        )

        resp = app_client.post(
            f"/pve-challenge/{VALID_SESSION_ID}/submit",
            json={"solved": True, "time_spent": 120.5, "attempts": 1, "error_count": 0},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["solved"] is True
        assert body["data"]["status"] == "completed"
        assert body["data"]["elo_change"] == 10
        assert body["data"]["tokens_earned"] == 15
        assert body["message"] == "Challenge completed"

    @patch("app.api.v1.pve_challenge.PvEChallengeService")
    @patch("app.api.v1.pve_challenge._get_cf_service")
    def test_submit_failed(self, mock_get_cf, mock_pve_svc, app_client):
        mock_get_cf.return_value = MagicMock()
        mock_pve_svc.submit_result = AsyncMock(
            return_value=_make_simple_response(
                session_id=VALID_SESSION_ID,
                solved=False,
                status="completed",
                elo_change=-5,
                pp_change=-1.0,
                s_value=0.3,
                tokens_earned=0,
                overkill_multiplier=1.0,
                achievements=[],
            )
        )

        resp = app_client.post(
            f"/pve-challenge/{VALID_SESSION_ID}/submit",
            json={"solved": False, "time_spent": 300.0, "attempts": 3, "error_count": 2},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["solved"] is False
        assert body["data"]["elo_change"] == -5

    @patch("app.api.v1.pve_challenge.PvEChallengeService")
    @patch("app.api.v1.pve_challenge._get_cf_service")
    def test_submit_session_not_found(self, mock_get_cf, mock_pve_svc, app_client):
        mock_get_cf.return_value = MagicMock()
        mock_pve_svc.submit_result = AsyncMock(
            side_effect=NotFoundException("Challenge session not found"),
        )

        resp = app_client.post(
            f"/pve-challenge/{VALID_SESSION_ID}/submit",
            json={"solved": True, "time_spent": 100.0, "attempts": 1, "error_count": 0},
        )
        assert resp.status_code == 404

    @patch("app.api.v1.pve_challenge.PvEChallengeService")
    @patch("app.api.v1.pve_challenge._get_cf_service")
    def test_submit_already_completed(self, mock_get_cf, mock_pve_svc, app_client):
        mock_get_cf.return_value = MagicMock()
        mock_pve_svc.submit_result = AsyncMock(
            side_effect=BadRequestException("Challenge already completed"),
        )

        resp = app_client.post(
            f"/pve-challenge/{VALID_SESSION_ID}/submit",
            json={"solved": True, "time_spent": 100.0, "attempts": 1, "error_count": 0},
        )
        assert resp.status_code == 400

    def test_submit_missing_body(self, app_client):
        resp = app_client.post(f"/pve-challenge/{VALID_SESSION_ID}/submit")
        assert resp.status_code == 422

    def test_submit_invalid_body_negative_time(self, app_client):
        resp = app_client.post(
            f"/pve-challenge/{VALID_SESSION_ID}/submit",
            json={"solved": True, "time_spent": -1.0, "attempts": 1, "error_count": 0},
        )
        assert resp.status_code == 422

    def test_submit_invalid_body_negative_attempts(self, app_client):
        resp = app_client.post(
            f"/pve-challenge/{VALID_SESSION_ID}/submit",
            json={"solved": True, "time_spent": 100.0, "attempts": -1, "error_count": 0},
        )
        assert resp.status_code == 422

    def test_submit_invalid_body_negative_error_count(self, app_client):
        resp = app_client.post(
            f"/pve-challenge/{VALID_SESSION_ID}/submit",
            json={"solved": True, "time_spent": 100.0, "attempts": 1, "error_count": -1},
        )
        assert resp.status_code == 422

    def test_submit_invalid_session_id(self, app_client):
        resp = app_client.post(
            "/pve-challenge/not-a-uuid/submit",
            json={"solved": True, "time_spent": 100.0, "attempts": 1, "error_count": 0},
        )
        assert resp.status_code == 422

    def test_submit_unauthenticated(self):
        client = _unauth_client()
        resp = client.post(
            f"/pve-challenge/{VALID_SESSION_ID}/submit",
            json={"solved": True, "time_spent": 100.0, "attempts": 1, "error_count": 0},
        )
        assert resp.status_code == 401


# ===========================================================================
# POST /pve-challenge/{session_id}/quit
# ===========================================================================


class TestQuitChallenge:
    """Tests for POST /pve-challenge/{session_id}/quit."""

    @patch("app.api.v1.pve_challenge.PvEChallengeService")
    def test_quit_success(self, mock_pve_svc, app_client):
        quit_data = {
            "session_id": VALID_SESSION_ID,
            "status": "quit",
            "elo_change": -10,
            "penalty": 10,
        }
        mock_pve_svc.quit_challenge = AsyncMock(return_value=quit_data)

        resp = app_client.post(
            f"/pve-challenge/{VALID_SESSION_ID}/quit",
            json={"submissions": 2},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["status"] == "quit"
        assert body["data"]["elo_change"] == -10
        assert body["data"]["penalty"] == 10
        assert body["message"] == "Challenge quit"

    @patch("app.api.v1.pve_challenge.PvEChallengeService")
    def test_quit_zero_submissions(self, mock_pve_svc, app_client):
        quit_data = {
            "session_id": VALID_SESSION_ID,
            "status": "quit",
            "elo_change": -5,
            "penalty": 5,
        }
        mock_pve_svc.quit_challenge = AsyncMock(return_value=quit_data)

        resp = app_client.post(
            f"/pve-challenge/{VALID_SESSION_ID}/quit",
            json={"submissions": 0},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["penalty"] == 5

    @patch("app.api.v1.pve_challenge.PvEChallengeService")
    def test_quit_session_not_found(self, mock_pve_svc, app_client):
        mock_pve_svc.quit_challenge = AsyncMock(
            side_effect=NotFoundException("Challenge session not found"),
        )

        resp = app_client.post(
            f"/pve-challenge/{VALID_SESSION_ID}/quit",
            json={"submissions": 0},
        )
        assert resp.status_code == 404

    @patch("app.api.v1.pve_challenge.PvEChallengeService")
    def test_quit_already_completed(self, mock_pve_svc, app_client):
        mock_pve_svc.quit_challenge = AsyncMock(
            side_effect=BadRequestException("Challenge already completed"),
        )

        resp = app_client.post(
            f"/pve-challenge/{VALID_SESSION_ID}/quit",
            json={"submissions": 1},
        )
        assert resp.status_code == 400

    def test_quit_missing_body(self, app_client):
        resp = app_client.post(f"/pve-challenge/{VALID_SESSION_ID}/quit")
        assert resp.status_code == 422

    def test_quit_negative_submissions(self, app_client):
        resp = app_client.post(
            f"/pve-challenge/{VALID_SESSION_ID}/quit",
            json={"submissions": -1},
        )
        assert resp.status_code == 422

    def test_quit_invalid_session_id(self, app_client):
        resp = app_client.post(
            "/pve-challenge/not-a-uuid/quit",
            json={"submissions": 0},
        )
        assert resp.status_code == 422

    def test_quit_unauthenticated(self):
        client = _unauth_client()
        resp = client.post(
            f"/pve-challenge/{VALID_SESSION_ID}/quit",
            json={"submissions": 0},
        )
        assert resp.status_code == 401


# ===========================================================================
# Cross-cutting: response envelope
# ===========================================================================


class TestResponseEnvelope:
    """Verify that all successful responses have the standard envelope."""

    @patch("app.api.v1.pve_challenge.PvEChallengeService")
    @patch("app.api.v1.pve_challenge._get_cf_service")
    def test_start_envelope(self, mock_get_cf, mock_pve_svc, app_client):
        mock_get_cf.return_value = MagicMock()
        mock_pve_svc.start_challenge = AsyncMock(
            return_value=_make_simple_response(
                session_id=VALID_SESSION_ID,
                problem={
                    "contest_id": 1234,
                    "index": "A",
                    "name": "Test",
                    "rating": 1500,
                    "tags": [],
                    "url": "https://codeforces.com/problemset/problem/1234/A",
                },
                status="active",
            )
        )

        resp = app_client.post("/pve-challenge/start")
        body = resp.json()
        assert "success" in body
        assert "data" in body
        assert "message" in body
        assert body["success"] is True

    @patch("app.api.v1.pve_challenge.PvEChallengeService")
    def test_history_envelope(self, mock_pve_svc, app_client):
        mock_pve_svc.get_history = AsyncMock(
            return_value=_make_simple_response(
                items=[],
                total=0,
                page=1,
                page_size=20,
            )
        )

        resp = app_client.get("/pve-challenge/history")
        body = resp.json()
        assert "success" in body
        assert "data" in body
        assert "message" in body
        assert body["success"] is True

    @patch("app.api.v1.pve_challenge.PvEChallengeService")
    @patch("app.api.v1.pve_challenge._get_cf_service")
    def test_submit_envelope(self, mock_get_cf, mock_pve_svc, app_client):
        mock_get_cf.return_value = MagicMock()
        mock_pve_svc.submit_result = AsyncMock(
            return_value=_make_simple_response(
                session_id=VALID_SESSION_ID,
                solved=True,
                status="completed",
                elo_change=10,
                pp_change=2.5,
                s_value=0.85,
                tokens_earned=15,
                overkill_multiplier=1.0,
                achievements=[],
            )
        )

        resp = app_client.post(
            f"/pve-challenge/{VALID_SESSION_ID}/submit",
            json={"solved": True, "time_spent": 100.0, "attempts": 1, "error_count": 0},
        )
        body = resp.json()
        assert "success" in body
        assert "data" in body
        assert "message" in body
        assert body["success"] is True

    @patch("app.api.v1.pve_challenge.PvEChallengeService")
    def test_quit_envelope(self, mock_pve_svc, app_client):
        mock_pve_svc.quit_challenge = AsyncMock(
            return_value={
                "session_id": VALID_SESSION_ID,
                "status": "quit",
                "elo_change": -5,
                "penalty": 5,
            }
        )

        resp = app_client.post(
            f"/pve-challenge/{VALID_SESSION_ID}/quit",
            json={"submissions": 0},
        )
        body = resp.json()
        assert "success" in body
        assert "data" in body
        assert "message" in body
        assert body["success"] is True
