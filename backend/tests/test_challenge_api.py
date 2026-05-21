"""API route tests for app/api/v1/challenge.py.

Tests cover all 8 challenge endpoints:
  POST   /challenge/queue
  DELETE /challenge/queue
  GET    /challenge/status
  GET    /challenge/active
  POST   /challenge/start
  GET    /challenge/{session_id}
  POST   /challenge/{session_id}/submit
  POST   /challenge/{session_id}/quit
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

SAMPLE_UUID = "00000000-0000-0000-0000-0000000000bb"


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


def _match_result_dict(**overrides):
    d = {
        "session_id": SAMPLE_UUID,
        "matched": True,
        "opponent": {
            "id": "00000000-0000-0000-0000-000000000002",
            "username": "opponent",
            "elo": 1500,
            "cf_handle": "opp_cf",
        },
        "status": "matched",
    }
    d.update(overrides)
    return d


def _queue_status_dict(**overrides):
    d = {
        "in_queue": False,
        "matched": False,
        "session_id": None,
        "opponent": None,
        "both_ready": False,
    }
    d.update(overrides)
    return d


def _challenge_detail_dict(**overrides):
    d = {
        "id": SAMPLE_UUID,
        "challenger_id": "00000000-0000-0000-0000-000000000001",
        "opponent_id": "00000000-0000-0000-0000-000000000002",
        "problem_id": "1234A",
        "problem_rating": 1500,
        "problem": {
            "contest_id": 1234,
            "index": "A",
            "name": "Test Problem",
            "rating": 1500,
            "tags": ["dp"],
            "url": "https://codeforces.com/contest/1234/problem/A",
        },
        "challenger_solved": False,
        "opponent_solved": False,
        "challenger_submissions": 0,
        "opponent_submissions": 0,
        "challenger_time": None,
        "opponent_time": None,
        "status": "active",
        "result": None,
        "is_challenger": True,
        "elo_change": None,
        "opponent_elo_change": None,
        "tokens_earned": None,
        "opponent_tokens_earned": None,
        "created_at": datetime(2025, 1, 1, tzinfo=UTC).isoformat(),
        "completed_at": None,
    }
    d.update(overrides)
    return d


def _submit_result_dict(**overrides):
    d = {
        "session_id": SAMPLE_UUID,
        "solved": True,
        "status": "result_submitted",
        "settled": False,
        "result": None,
        "elo_change": None,
        "tokens_earned": None,
        "achievements": [],
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
        "status": "problem_revealed",
    }
    d.update(overrides)
    return d


def _active_challenge_dict(**overrides):
    d = {
        "id": SAMPLE_UUID,
        "problem_id": "1234A",
        "problem_name": "Test Problem",
        "problem_rating": 1500,
        "created_at": datetime(2025, 1, 1, tzinfo=UTC).isoformat(),
        "is_challenger": True,
        "opponent_username": "opponent",
        "opponent_elo": 1500,
        "status": "active",
    }
    d.update(overrides)
    return d


# ===========================================================================
# POST /challenge/queue
# ===========================================================================


class TestJoinQueue:
    """Tests for POST /challenge/queue."""

    @patch("app.api.v1.challenge.get_match_service")
    @patch("app.api.v1.challenge.ChallengeService")
    def test_join_queue_matched(self, mock_svc, mock_match, app_client):
        mock_svc.join_queue = AsyncMock(return_value=_match_result_dict())

        resp = app_client.post("/challenge/queue")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["matched"] is True
        assert body["message"] == "Match found"

    @patch("app.api.v1.challenge.get_match_service")
    @patch("app.api.v1.challenge.ChallengeService")
    def test_join_queue_waiting(self, mock_svc, mock_match, app_client):
        mock_svc.join_queue = AsyncMock(
            return_value={"matched": False, "in_queue": True},
        )

        resp = app_client.post("/challenge/queue")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["matched"] is False
        assert body["message"] == "Added to queue"

    @patch("app.api.v1.challenge.get_match_service")
    @patch("app.api.v1.challenge.ChallengeService")
    def test_join_queue_already_in_queue(self, mock_svc, mock_match, app_client):
        mock_svc.join_queue = AsyncMock(
            side_effect=BadRequestException("Already in queue"),
        )

        resp = app_client.post("/challenge/queue")
        assert resp.status_code == 400

    def test_join_queue_unauthenticated(self):
        client = _unauth_client()
        resp = client.post("/challenge/queue")
        assert resp.status_code == 401

    def test_join_queue_wrong_method(self, app_client):
        # Note: GET /challenge/queue matches /{session_id} with session_id="queue",
        # so it returns 422 (invalid UUID) rather than 405. Use PUT to test 405.
        resp = app_client.put("/challenge/queue")
        assert resp.status_code == 405


# ===========================================================================
# DELETE /challenge/queue
# ===========================================================================


class TestLeaveQueue:
    """Tests for DELETE /challenge/queue."""

    @patch("app.api.v1.challenge.get_match_service")
    @patch("app.api.v1.challenge.ChallengeService")
    def test_leave_queue_success(self, mock_svc, mock_match, app_client):
        mock_svc.leave_queue = AsyncMock(return_value=True)

        resp = app_client.delete("/challenge/queue")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["removed"] is True
        assert body["message"] == "Removed from queue"

    @patch("app.api.v1.challenge.get_match_service")
    @patch("app.api.v1.challenge.ChallengeService")
    def test_leave_queue_not_in_queue(self, mock_svc, mock_match, app_client):
        mock_svc.leave_queue = AsyncMock(return_value=False)

        resp = app_client.delete("/challenge/queue")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["removed"] is False
        assert body["message"] == "Not in queue"

    def test_leave_queue_unauthenticated(self):
        client = _unauth_client()
        resp = client.delete("/challenge/queue")
        assert resp.status_code == 401


# ===========================================================================
# GET /challenge/status
# ===========================================================================


class TestGetStatus:
    """Tests for GET /challenge/status."""

    @patch("app.api.v1.challenge.get_match_service")
    @patch("app.api.v1.challenge.ChallengeService")
    def test_status_idle(self, mock_svc, mock_match, app_client):
        mock_svc.get_queue_status = AsyncMock(
            return_value=_queue_status_dict(),
        )

        resp = app_client.get("/challenge/status")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["in_queue"] is False
        assert body["data"]["matched"] is False

    @patch("app.api.v1.challenge.get_match_service")
    @patch("app.api.v1.challenge.ChallengeService")
    def test_status_matched(self, mock_svc, mock_match, app_client):
        mock_svc.get_queue_status = AsyncMock(
            return_value=_queue_status_dict(
                matched=True,
                session_id=SAMPLE_UUID,
            ),
        )

        resp = app_client.get("/challenge/status")
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["matched"] is True
        assert body["data"]["session_id"] == SAMPLE_UUID

    def test_status_unauthenticated(self):
        client = _unauth_client()
        resp = client.get("/challenge/status")
        assert resp.status_code == 401


# ===========================================================================
# GET /challenge/active
# ===========================================================================


class TestGetActiveChallenge:
    """Tests for GET /challenge/active."""

    @patch("app.api.v1.challenge.ChallengeService")
    def test_active_challenge_found(self, mock_svc, app_client):
        active = MagicMock()
        active.model_dump.return_value = _active_challenge_dict()
        mock_svc.get_active_challenge = AsyncMock(return_value=active)

        resp = app_client.get("/challenge/active")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["id"] == SAMPLE_UUID
        assert body["data"]["status"] == "active"
        assert body["message"] == "Active challenge retrieved"

    @patch("app.api.v1.challenge.ChallengeService")
    def test_active_challenge_none(self, mock_svc, app_client):
        mock_svc.get_active_challenge = AsyncMock(return_value=None)

        resp = app_client.get("/challenge/active")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"] is None
        assert body["message"] == "Active challenge retrieved"

    def test_active_challenge_unauthenticated(self):
        client = _unauth_client()
        resp = client.get("/challenge/active")
        assert resp.status_code == 401

    def test_active_challenge_wrong_method(self, app_client):
        resp = app_client.post("/challenge/active")
        assert resp.status_code == 405


# ===========================================================================
# POST /challenge/start
# ===========================================================================


class TestStartChallenge:
    """Tests for POST /challenge/start."""

    @patch("app.api.v1.challenge._get_cf_service")
    @patch("app.api.v1.challenge.get_match_service")
    @patch("app.api.v1.challenge.ChallengeService")
    def test_start_success(self, mock_svc, mock_match, mock_cf, app_client):
        mock_svc.get_queue_status = AsyncMock(
            return_value={"session_id": SAMPLE_UUID},
        )
        start_resp = MagicMock()
        start_resp.model_dump.return_value = _start_response_dict()
        mock_svc.start_challenge = AsyncMock(return_value=start_resp)

        resp = app_client.post("/challenge/start")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["status"] == "problem_revealed"
        assert body["message"] == "Challenge started"

    @patch("app.api.v1.challenge.get_match_service")
    @patch("app.api.v1.challenge.ChallengeService")
    def test_start_no_match(self, mock_svc, mock_match, app_client):
        mock_svc.get_queue_status = AsyncMock(
            return_value={"session_id": None},
        )

        resp = app_client.post("/challenge/start")
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["status"] == "no_match"
        assert body["message"] == "No active match to start"

    @patch("app.api.v1.challenge._get_cf_service")
    @patch("app.api.v1.challenge.get_match_service")
    @patch("app.api.v1.challenge.ChallengeService")
    def test_start_already_started(self, mock_svc, mock_match, mock_cf, app_client):
        mock_svc.get_queue_status = AsyncMock(
            return_value={"session_id": SAMPLE_UUID},
        )
        mock_svc.start_challenge = AsyncMock(
            side_effect=BadRequestException("Challenge already started"),
        )

        resp = app_client.post("/challenge/start")
        assert resp.status_code == 400

    def test_start_unauthenticated(self):
        client = _unauth_client()
        resp = client.post("/challenge/start")
        assert resp.status_code == 401


# ===========================================================================
# GET /challenge/{session_id}
# ===========================================================================


class TestGetChallengeDetail:
    """Tests for GET /challenge/{session_id}."""

    @patch("app.api.v1.challenge.ChallengeService")
    def test_detail_success(self, mock_svc, app_client):
        detail = MagicMock()
        detail.model_dump.return_value = _challenge_detail_dict()
        mock_svc.get_challenge_detail = AsyncMock(return_value=detail)

        resp = app_client.get(f"/challenge/{SAMPLE_UUID}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["id"] == SAMPLE_UUID
        assert body["data"]["status"] == "active"
        assert body["message"] == "Challenge details retrieved"

    @patch("app.api.v1.challenge.ChallengeService")
    def test_detail_not_found(self, mock_svc, app_client):
        mock_svc.get_challenge_detail = AsyncMock(
            side_effect=NotFoundException("Challenge not found"),
        )

        resp = app_client.get(f"/challenge/{SAMPLE_UUID}")
        assert resp.status_code == 404

    def test_detail_invalid_uuid(self, app_client):
        resp = app_client.get("/challenge/not-a-uuid")
        assert resp.status_code == 422

    def test_detail_unauthenticated(self):
        client = _unauth_client()
        resp = client.get(f"/challenge/{SAMPLE_UUID}")
        assert resp.status_code == 401


# ===========================================================================
# POST /challenge/{session_id}/submit
# ===========================================================================


class TestSubmitResult:
    """Tests for POST /challenge/{session_id}/submit."""

    @patch("app.api.v1.challenge._get_cf_service")
    @patch("app.api.v1.challenge.ChallengeService")
    def test_submit_success_unsettled(self, mock_svc, mock_cf, app_client):
        result = MagicMock()
        result.model_dump.return_value = _submit_result_dict()
        result.settled = False
        mock_svc.submit_result = AsyncMock(return_value=result)

        resp = app_client.post(
            f"/challenge/{SAMPLE_UUID}/submit",
            json={"solved": True, "time_spent": 120.5, "attempts": 1},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["solved"] is True
        assert body["message"] == "Result submitted"

    @patch("app.api.v1.challenge._get_cf_service")
    @patch("app.api.v1.challenge.ChallengeService")
    def test_submit_success_settled(self, mock_svc, mock_cf, app_client):
        result_dict = _submit_result_dict(
            settled=True,
            result="win",
            elo_change=15,
            tokens_earned=30,
        )
        result = MagicMock()
        result.model_dump.return_value = result_dict
        result.settled = True
        mock_svc.submit_result = AsyncMock(return_value=result)

        resp = app_client.post(
            f"/challenge/{SAMPLE_UUID}/submit",
            json={"solved": True, "time_spent": 60.0, "attempts": 2},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["message"] == "Challenge settled"
        assert body["data"]["settled"] is True
        assert body["data"]["elo_change"] == 15

    def test_submit_missing_fields(self, app_client):
        resp = app_client.post(f"/challenge/{SAMPLE_UUID}/submit", json={})
        assert resp.status_code == 422

    def test_submit_negative_time_spent(self, app_client):
        resp = app_client.post(
            f"/challenge/{SAMPLE_UUID}/submit",
            json={"solved": True, "time_spent": -10, "attempts": 1},
        )
        assert resp.status_code == 422

    def test_submit_negative_attempts(self, app_client):
        resp = app_client.post(
            f"/challenge/{SAMPLE_UUID}/submit",
            json={"solved": True, "time_spent": 60, "attempts": -1},
        )
        assert resp.status_code == 422

    @patch("app.api.v1.challenge._get_cf_service")
    @patch("app.api.v1.challenge.ChallengeService")
    def test_submit_not_found(self, mock_svc, mock_cf, app_client):
        mock_svc.submit_result = AsyncMock(
            side_effect=NotFoundException("Challenge not found"),
        )

        resp = app_client.post(
            f"/challenge/{SAMPLE_UUID}/submit",
            json={"solved": True, "time_spent": 60, "attempts": 1},
        )
        assert resp.status_code == 404

    @patch("app.api.v1.challenge._get_cf_service")
    @patch("app.api.v1.challenge.ChallengeService")
    def test_submit_already_submitted(self, mock_svc, mock_cf, app_client):
        mock_svc.submit_result = AsyncMock(
            side_effect=BadRequestException("Already submitted"),
        )

        resp = app_client.post(
            f"/challenge/{SAMPLE_UUID}/submit",
            json={"solved": True, "time_spent": 60, "attempts": 1},
        )
        assert resp.status_code == 400

    def test_submit_invalid_session_id(self, app_client):
        resp = app_client.post(
            "/challenge/bad-uuid/submit",
            json={"solved": True, "time_spent": 60, "attempts": 1},
        )
        assert resp.status_code == 422

    def test_submit_unauthenticated(self):
        client = _unauth_client()
        resp = client.post(
            f"/challenge/{SAMPLE_UUID}/submit",
            json={"solved": True, "time_spent": 60, "attempts": 1},
        )
        assert resp.status_code == 401


# ===========================================================================
# POST /challenge/{session_id}/quit
# ===========================================================================


class TestQuitChallenge:
    """Tests for POST /challenge/{session_id}/quit."""

    @patch("app.api.v1.challenge.ChallengeService")
    def test_quit_success(self, mock_svc, app_client):
        mock_svc.quit_challenge = AsyncMock(
            return_value={
                "session_id": SAMPLE_UUID,
                "status": "quit",
                "elo_change": -10,
                "penalty": 10,
            },
        )

        resp = app_client.post(
            f"/challenge/{SAMPLE_UUID}/quit",
            json={"submissions": 2},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["status"] == "quit"
        assert body["data"]["elo_change"] == -10
        assert body["message"] == "Challenge quit"

    @patch("app.api.v1.challenge.ChallengeService")
    def test_quit_not_found(self, mock_svc, app_client):
        mock_svc.quit_challenge = AsyncMock(
            side_effect=NotFoundException("Challenge not found"),
        )

        resp = app_client.post(
            f"/challenge/{SAMPLE_UUID}/quit",
            json={"submissions": 0},
        )
        assert resp.status_code == 404

    def test_quit_missing_submissions(self, app_client):
        resp = app_client.post(f"/challenge/{SAMPLE_UUID}/quit", json={})
        assert resp.status_code == 422

    def test_quit_negative_submissions(self, app_client):
        resp = app_client.post(
            f"/challenge/{SAMPLE_UUID}/quit",
            json={"submissions": -1},
        )
        assert resp.status_code == 422

    def test_quit_invalid_session_id(self, app_client):
        resp = app_client.post(
            "/challenge/bad-uuid/quit",
            json={"submissions": 0},
        )
        assert resp.status_code == 422

    def test_quit_unauthenticated(self):
        client = _unauth_client()
        resp = client.post(
            f"/challenge/{SAMPLE_UUID}/quit",
            json={"submissions": 0},
        )
        assert resp.status_code == 401

    def test_quit_wrong_method(self, app_client):
        resp = app_client.get(f"/challenge/{SAMPLE_UUID}/quit")
        assert resp.status_code == 405


# ===========================================================================
# Cross-cutting: response envelope
# ===========================================================================


class TestChallengeResponseEnvelope:
    """Verify all successful challenge responses have standard envelope."""

    @patch("app.api.v1.challenge.get_match_service")
    @patch("app.api.v1.challenge.ChallengeService")
    def test_queue_envelope(self, mock_svc, mock_match, app_client):
        mock_svc.join_queue = AsyncMock(return_value={"matched": True, "session_id": SAMPLE_UUID})

        resp = app_client.post("/challenge/queue")
        body = resp.json()
        assert "success" in body
        assert "data" in body
        assert "message" in body
        assert body["success"] is True

    @patch("app.api.v1.challenge.get_match_service")
    @patch("app.api.v1.challenge.ChallengeService")
    def test_leave_envelope(self, mock_svc, mock_match, app_client):
        mock_svc.leave_queue = AsyncMock(return_value=True)

        resp = app_client.delete("/challenge/queue")
        body = resp.json()
        assert "success" in body
        assert "data" in body
        assert "message" in body
