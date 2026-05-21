"""API route tests for app/api/v1/training.py.

Tests cover all 11 training endpoints:
  GET  /training/topics
  GET  /training/topics/{topic_id}
  GET  /training/topics/{topic_id}/recommend
  GET  /training/topics/{topic_id}/active-session
  POST /training/start
  GET  /training/session/{session_id}
  POST /training/session/{session_id}/submit
  POST /training/session/{session_id}/abandon
  GET  /training/progress
  GET  /training/progress/{topic_id}
  GET  /training/melo
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

SAMPLE_UUID = "00000000-0000-0000-0000-0000000000aa"


def _topic_info_dict(**overrides):
    d = {
        "id": SAMPLE_UUID,
        "name": "Dynamic Programming",
        "slug": "dp",
        "description": "DP problems",
        "cf_tags": ["dp"],
        "display_order": 1,
        "total_problems": 10,
        "solved_count": 3,
        "stars": 2,
        "melo": 1300.0,
        "shield_active": False,
    }
    d.update(overrides)
    return d


def _session_info_dict(**overrides):
    d = {
        "id": SAMPLE_UUID,
        "topic_id": SAMPLE_UUID,
        "topic_name": "DP",
        "problems_solved": 1,
        "total_problems": 5,
        "streak_count": 2,
        "status": "active",
        "created_at": datetime(2025, 1, 1, tzinfo=UTC).isoformat(),
        "started_at": datetime(2025, 1, 1, tzinfo=UTC).isoformat(),
        "completed_at": None,
        "last_solved_rating": 1500,
        "streak_tokens_earned": 10,
    }
    d.update(overrides)
    return d


def _topic_detail_dict(**overrides):
    d = _topic_info_dict()
    d["problems"] = []
    d.update(overrides)
    return d


def _submit_response_dict(**overrides):
    d = {
        "session_id": SAMPLE_UUID,
        "problem_id": "1234A",
        "solved": True,
        "streak_count": 2,
        "streak_tokens": 5,
        "total_streak_tokens": 10,
        "tokens_earned": 20,
        "elo_change": 5,
        "achievements": [],
    }
    d.update(overrides)
    return d


def _recommended_problem_dict(**overrides):
    d = {
        "problem_id": "1234A",
        "contest_id": 1234,
        "index": "A",
        "name": "Test Problem",
        "rating": 1500,
        "tags": ["dp"],
        "url": "https://codeforces.com/contest/1234/problem/A",
        "melo": 1300,
        "search_range": [1200, 1400],
    }
    d.update(overrides)
    return d


def _topic_progress_dict(**overrides):
    d = {
        "topic_id": SAMPLE_UUID,
        "topic_name": "DP",
        "slug": "dp",
        "total_problems": 10,
        "solved_count": 3,
        "completion_rate": 0.3,
        "stars": 2,
        "total_attempts": 5,
        "total_time_spent": 3600.0,
        "melo": 1300.0,
        "shield_active": False,
    }
    d.update(overrides)
    return d


def _progress_dict():
    return {
        "topics": [_topic_progress_dict()],
        "total_solved": 3,
        "total_problems": 10,
    }


def _abandon_response_dict(**overrides):
    d = {
        "session_id": SAMPLE_UUID,
        "status": "abandoned",
        "problems_solved": 1,
        "total_problems": 5,
        "elo_change": -3,
        "shield_active": False,
    }
    d.update(overrides)
    return d


def _make_response_model(data_dict):
    """Create a MagicMock that has .model_dump() returning the dict."""
    mock_obj = MagicMock()
    mock_obj.model_dump.return_value = data_dict
    return mock_obj


# ===========================================================================
# GET /training/topics
# ===========================================================================


class TestListTopics:
    """Tests for GET /training/topics."""

    @patch("app.api.v1.training.TrainingService")
    @patch("app.api.v1.training._get_cf_service")
    def test_list_topics_success(self, mock_cf, mock_svc, app_client):
        t1 = _make_response_model(_topic_info_dict())
        t2 = _make_response_model(_topic_info_dict(name="Greedy", slug="greedy"))
        mock_svc.list_topics = AsyncMock(return_value=[t1, t2])

        resp = app_client.get("/training/topics")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert len(body["data"]) == 2
        assert body["message"] == "Topics retrieved"

    def test_list_topics_unauthenticated(self):
        client = _unauth_client()
        resp = client.get("/training/topics")
        assert resp.status_code == 401

    def test_list_topics_wrong_method(self, app_client):
        resp = app_client.post("/training/topics")
        assert resp.status_code == 405


# ===========================================================================
# GET /training/topics/{topic_id}
# ===========================================================================


class TestGetTopicDetail:
    """Tests for GET /training/topics/{topic_id}."""

    @patch("app.api.v1.training.TrainingService")
    @patch("app.api.v1.training._get_cf_service")
    def test_topic_detail_success(self, mock_cf, mock_svc, app_client):
        detail = _make_response_model(_topic_detail_dict())
        mock_svc.get_topic_detail = AsyncMock(return_value=detail)

        resp = app_client.get(f"/training/topics/{SAMPLE_UUID}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["name"] == "Dynamic Programming"
        assert body["message"] == "Topic detail retrieved"

    @patch("app.api.v1.training.TrainingService")
    @patch("app.api.v1.training._get_cf_service")
    def test_topic_detail_not_found(self, mock_cf, mock_svc, app_client):
        mock_svc.get_topic_detail = AsyncMock(
            side_effect=NotFoundException("Topic not found"),
        )

        resp = app_client.get(f"/training/topics/{SAMPLE_UUID}")
        assert resp.status_code == 404

    def test_topic_detail_invalid_uuid(self, app_client):
        resp = app_client.get("/training/topics/not-a-uuid")
        assert resp.status_code == 422

    def test_topic_detail_unauthenticated(self):
        client = _unauth_client()
        resp = client.get(f"/training/topics/{SAMPLE_UUID}")
        assert resp.status_code == 401


# ===========================================================================
# GET /training/topics/{topic_id}/recommend
# ===========================================================================


class TestRecommendProblem:
    """Tests for GET /training/topics/{topic_id}/recommend."""

    @patch("app.api.v1.training.TrainingService")
    @patch("app.api.v1.training._get_cf_service")
    def test_recommend_found(self, mock_cf, mock_svc, app_client):
        rec = _make_response_model(_recommended_problem_dict())
        mock_svc.get_adaptive_problem = AsyncMock(return_value=rec)

        resp = app_client.get(f"/training/topics/{SAMPLE_UUID}/recommend")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["problem_id"] == "1234A"
        assert body["message"] == "Recommended problem found"

    @patch("app.api.v1.training.TrainingService")
    @patch("app.api.v1.training._get_cf_service")
    def test_recommend_no_problem_found(self, mock_cf, mock_svc, app_client):
        mock_svc.get_adaptive_problem = AsyncMock(return_value=None)

        resp = app_client.get(f"/training/topics/{SAMPLE_UUID}/recommend")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"] is None
        assert "No suitable problem" in body["message"]

    def test_recommend_invalid_uuid(self, app_client):
        resp = app_client.get("/training/topics/bad-uuid/recommend")
        assert resp.status_code == 422

    def test_recommend_unauthenticated(self):
        client = _unauth_client()
        resp = client.get(f"/training/topics/{SAMPLE_UUID}/recommend")
        assert resp.status_code == 401


# ===========================================================================
# POST /training/start
# ===========================================================================


class TestStartTraining:
    """Tests for POST /training/start."""

    @patch("app.api.v1.training.TrainingService")
    @patch("app.api.v1.training._get_cf_service")
    def test_start_success(self, mock_cf, mock_svc, app_client):
        session = _make_response_model(_session_info_dict())
        mock_svc.start_training = AsyncMock(return_value=session)

        resp = app_client.post(
            "/training/start",
            json={"topic_id": SAMPLE_UUID},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["status"] == "active"
        assert body["message"] == "Training session started"

    def test_start_missing_topic_id(self, app_client):
        resp = app_client.post("/training/start", json={})
        assert resp.status_code == 422

    def test_start_invalid_topic_id(self, app_client):
        resp = app_client.post("/training/start", json={"topic_id": "not-a-uuid"})
        assert resp.status_code == 422

    @patch("app.api.v1.training.TrainingService")
    @patch("app.api.v1.training._get_cf_service")
    def test_start_topic_not_found(self, mock_cf, mock_svc, app_client):
        mock_svc.start_training = AsyncMock(
            side_effect=NotFoundException("Topic not found"),
        )

        resp = app_client.post("/training/start", json={"topic_id": SAMPLE_UUID})
        assert resp.status_code == 404

    @patch("app.api.v1.training.TrainingService")
    @patch("app.api.v1.training._get_cf_service")
    def test_start_already_active(self, mock_cf, mock_svc, app_client):
        mock_svc.start_training = AsyncMock(
            side_effect=BadRequestException("Already have active session"),
        )

        resp = app_client.post("/training/start", json={"topic_id": SAMPLE_UUID})
        assert resp.status_code == 400

    def test_start_unauthenticated(self):
        client = _unauth_client()
        resp = client.post("/training/start", json={"topic_id": SAMPLE_UUID})
        assert resp.status_code == 401

    def test_start_wrong_http_method(self, app_client):
        resp = app_client.get("/training/start")
        assert resp.status_code == 405


# ===========================================================================
# GET /training/session/{session_id}
# ===========================================================================


class TestGetSessionStatus:
    """Tests for GET /training/session/{session_id}."""

    @patch("app.api.v1.training.TrainingService")
    def test_session_status_success(self, mock_svc, app_client):
        session = _make_response_model(_session_info_dict())
        mock_svc.get_session_status = AsyncMock(return_value=session)

        resp = app_client.get(f"/training/session/{SAMPLE_UUID}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["status"] == "active"
        assert body["message"] == "Session status retrieved"

    @patch("app.api.v1.training.TrainingService")
    def test_session_status_not_found(self, mock_svc, app_client):
        mock_svc.get_session_status = AsyncMock(
            side_effect=NotFoundException("Session not found"),
        )

        resp = app_client.get(f"/training/session/{SAMPLE_UUID}")
        assert resp.status_code == 404

    def test_session_status_invalid_uuid(self, app_client):
        resp = app_client.get("/training/session/not-a-uuid")
        assert resp.status_code == 422

    def test_session_status_unauthenticated(self):
        client = _unauth_client()
        resp = client.get(f"/training/session/{SAMPLE_UUID}")
        assert resp.status_code == 401


# ===========================================================================
# POST /training/session/{session_id}/submit
# ===========================================================================


class TestSubmitProblem:
    """Tests for POST /training/session/{session_id}/submit."""

    @patch("app.api.v1.training.TrainingService")
    @patch("app.api.v1.training._get_cf_service")
    def test_submit_success(self, mock_cf, mock_svc, app_client):
        result = _make_response_model(_submit_response_dict())
        mock_svc.submit_problem = AsyncMock(return_value=result)

        resp = app_client.post(
            f"/training/session/{SAMPLE_UUID}/submit",
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
        resp = app_client.post(f"/training/session/{SAMPLE_UUID}/submit", json={})
        assert resp.status_code == 422

    def test_submit_negative_attempts(self, app_client):
        resp = app_client.post(
            f"/training/session/{SAMPLE_UUID}/submit",
            json={"problem_id": "1234A", "solved": True, "attempts": -1, "time_spent": 60},
        )
        assert resp.status_code == 422

    def test_submit_negative_time_spent(self, app_client):
        resp = app_client.post(
            f"/training/session/{SAMPLE_UUID}/submit",
            json={"problem_id": "1234A", "solved": True, "attempts": 1, "time_spent": -10},
        )
        assert resp.status_code == 422

    @patch("app.api.v1.training.TrainingService")
    @patch("app.api.v1.training._get_cf_service")
    def test_submit_session_not_found(self, mock_cf, mock_svc, app_client):
        mock_svc.submit_problem = AsyncMock(
            side_effect=NotFoundException("Session not found"),
        )

        resp = app_client.post(
            f"/training/session/{SAMPLE_UUID}/submit",
            json={"problem_id": "1234A", "solved": True, "attempts": 1, "time_spent": 60},
        )
        assert resp.status_code == 404

    def test_submit_invalid_session_id(self, app_client):
        resp = app_client.post(
            "/training/session/bad-uuid/submit",
            json={"problem_id": "1234A", "solved": True, "attempts": 1, "time_spent": 60},
        )
        assert resp.status_code == 422

    def test_submit_unauthenticated(self):
        client = _unauth_client()
        resp = client.post(
            f"/training/session/{SAMPLE_UUID}/submit",
            json={"problem_id": "1234A", "solved": True, "attempts": 1, "time_spent": 60},
        )
        assert resp.status_code == 401


# ===========================================================================
# POST /training/session/{session_id}/abandon
# ===========================================================================


class TestAbandonTraining:
    """Tests for POST /training/session/{session_id}/abandon."""

    @patch("app.api.v1.training.TrainingService")
    def test_abandon_success(self, mock_svc, app_client):
        result = _make_response_model(_abandon_response_dict())
        mock_svc.abandon_training = AsyncMock(return_value=result)

        resp = app_client.post(f"/training/session/{SAMPLE_UUID}/abandon")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["status"] == "abandoned"
        assert body["message"] == "Training session abandoned"

    @patch("app.api.v1.training.TrainingService")
    def test_abandon_not_found(self, mock_svc, app_client):
        mock_svc.abandon_training = AsyncMock(
            side_effect=NotFoundException("Session not found"),
        )

        resp = app_client.post(f"/training/session/{SAMPLE_UUID}/abandon")
        assert resp.status_code == 404

    def test_abandon_invalid_uuid(self, app_client):
        resp = app_client.post("/training/session/bad-uuid/abandon")
        assert resp.status_code == 422

    def test_abandon_unauthenticated(self):
        client = _unauth_client()
        resp = client.post(f"/training/session/{SAMPLE_UUID}/abandon")
        assert resp.status_code == 401

    def test_abandon_wrong_method(self, app_client):
        resp = app_client.get(f"/training/session/{SAMPLE_UUID}/abandon")
        assert resp.status_code == 405


# ===========================================================================
# GET /training/progress
# ===========================================================================


class TestGetProgress:
    """Tests for GET /training/progress."""

    @patch("app.api.v1.training.TrainingService")
    @patch("app.api.v1.training._get_cf_service")
    def test_progress_success(self, mock_cf, mock_svc, app_client):
        progress = MagicMock()
        progress.model_dump.return_value = _progress_dict()
        mock_svc.get_progress = AsyncMock(return_value=progress)

        resp = app_client.get("/training/progress")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert "topics" in body["data"]
        assert body["data"]["total_solved"] == 3
        assert body["message"] == "Progress retrieved"

    def test_progress_unauthenticated(self):
        client = _unauth_client()
        resp = client.get("/training/progress")
        assert resp.status_code == 401


# ===========================================================================
# GET /training/progress/{topic_id}
# ===========================================================================


class TestGetTopicProgress:
    """Tests for GET /training/progress/{topic_id}."""

    @patch("app.api.v1.training.TrainingService")
    @patch("app.api.v1.training._get_cf_service")
    def test_topic_progress_success(self, mock_cf, mock_svc, app_client):
        tp = MagicMock()
        tp.model_dump.return_value = _topic_progress_dict()
        mock_svc.get_topic_progress = AsyncMock(return_value=tp)

        resp = app_client.get(f"/training/progress/{SAMPLE_UUID}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["topic_name"] == "DP"
        assert body["message"] == "Topic progress retrieved"

    @patch("app.api.v1.training.TrainingService")
    @patch("app.api.v1.training._get_cf_service")
    def test_topic_progress_not_found(self, mock_cf, mock_svc, app_client):
        mock_svc.get_topic_progress = AsyncMock(
            side_effect=NotFoundException("Topic not found"),
        )

        resp = app_client.get(f"/training/progress/{SAMPLE_UUID}")
        assert resp.status_code == 404

    def test_topic_progress_invalid_uuid(self, app_client):
        resp = app_client.get("/training/progress/bad-uuid")
        assert resp.status_code == 422

    def test_topic_progress_unauthenticated(self):
        client = _unauth_client()
        resp = client.get(f"/training/progress/{SAMPLE_UUID}")
        assert resp.status_code == 401


# ===========================================================================
# GET /training/melo
# ===========================================================================


class TestGetMelo:
    """Tests for GET /training/melo."""

    @patch("app.api.v1.training.MEloService")
    def test_melo_success(self, mock_melo_svc, app_client, mock_user):
        mock_melo = MagicMock()
        mock_melo.tag = "dp"
        mock_melo.elo = 1300
        mock_melo.total_submissions = 10
        mock_melo.first_ac_at = None
        mock_melo_svc.get_or_create_melo = AsyncMock(return_value=mock_melo)

        resp = app_client.get("/training/melo")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert "melos" in body["data"]
        assert body["data"]["global_elo"] == 1400
        assert body["message"] == "M-Elo retrieved"

    def test_melo_unauthenticated(self):
        client = _unauth_client()
        resp = client.get("/training/melo")
        assert resp.status_code == 401


# ===========================================================================
# Cross-cutting: response envelope
# ===========================================================================


class TestTrainingResponseEnvelope:
    """Verify all successful training responses have standard envelope."""

    @patch("app.api.v1.training.TrainingService")
    @patch("app.api.v1.training._get_cf_service")
    def test_topics_envelope(self, mock_cf, mock_svc, app_client):
        mock_svc.list_topics = AsyncMock(return_value=[])
        resp = app_client.get("/training/topics")
        body = resp.json()
        assert "success" in body
        assert "data" in body
        assert "message" in body
        assert body["success"] is True

    @patch("app.api.v1.training.TrainingService")
    @patch("app.api.v1.training._get_cf_service")
    def test_start_envelope(self, mock_cf, mock_svc, app_client):
        session = _make_response_model(_session_info_dict())
        mock_svc.start_training = AsyncMock(return_value=session)

        resp = app_client.post("/training/start", json={"topic_id": SAMPLE_UUID})
        body = resp.json()
        assert "success" in body
        assert "data" in body
        assert "message" in body


# ---------------------------------------------------------------------------
# FR-19: Timer persistence -- started_at in training responses
# ---------------------------------------------------------------------------


class TestTrainingTimerPersistence:
    """Verify started_at is present in Training API responses."""

    @patch("app.api.v1.training.TrainingService")
    @patch("app.api.v1.training._get_cf_service")
    def test_start_training_returns_started_at(self, mock_cf, mock_svc, app_client):
        """POST /training/start response includes started_at field."""
        started = datetime(2026, 5, 22, 10, 30, 0, tzinfo=UTC).isoformat()
        session = _make_response_model(_session_info_dict(started_at=started))
        mock_svc.start_training = AsyncMock(return_value=session)

        resp = app_client.post("/training/start", json={"topic_id": SAMPLE_UUID})
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["started_at"] == started

    @patch("app.api.v1.training.TrainingService")
    def test_get_session_status_returns_started_at(self, mock_svc, app_client):
        """GET /training/session/{id} response includes started_at field."""
        started = datetime(2026, 5, 22, 10, 30, 0, tzinfo=UTC).isoformat()
        session = _make_response_model(_session_info_dict(started_at=started))
        mock_svc.get_session_status = AsyncMock(return_value=session)

        resp = app_client.get(f"/training/session/{SAMPLE_UUID}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["started_at"] == started


# ===========================================================================
# GET /training/topics/{topic_id}/active-session  (session recovery)
# ===========================================================================


class TestGetActiveSessionForTopic:
    """Tests for GET /training/topics/{topic_id}/active-session."""

    @patch("app.api.v1.training.TrainingService")
    def test_active_session_found(self, mock_svc, app_client):
        """Returns active session data when one exists."""
        started = datetime(2026, 5, 22, 10, 30, 0, tzinfo=UTC).isoformat()
        session = _make_response_model(_session_info_dict(started_at=started))
        mock_svc.get_active_session_for_topic = AsyncMock(return_value=session)

        resp = app_client.get(f"/training/topics/{SAMPLE_UUID}/active-session")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["status"] == "active"
        assert body["data"]["started_at"] == started
        assert body["message"] == "Active session found"

    @patch("app.api.v1.training.TrainingService")
    def test_active_session_none(self, mock_svc, app_client):
        """Returns null data when no active session exists."""
        mock_svc.get_active_session_for_topic = AsyncMock(return_value=None)

        resp = app_client.get(f"/training/topics/{SAMPLE_UUID}/active-session")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"] is None
        assert "No active session" in body["message"]

    def test_active_session_invalid_uuid(self, app_client):
        """Returns 422 for invalid topic UUID."""
        resp = app_client.get("/training/topics/bad-uuid/active-session")
        assert resp.status_code == 422

    def test_active_session_unauthenticated(self):
        """Returns 401 for unauthenticated requests."""
        client = _unauth_client()
        resp = client.get(f"/training/topics/{SAMPLE_UUID}/active-session")
        assert resp.status_code == 401

    def test_active_session_wrong_method(self, app_client):
        """POST is not allowed on this endpoint."""
        resp = app_client.post(f"/training/topics/{SAMPLE_UUID}/active-session")
        assert resp.status_code == 405


# ===========================================================================
# GET /training/topics/{topic_id}/curated-problems
# ===========================================================================


def _curated_problems_dict(**overrides):
    d = {
        "problems": [
            {
                "problem_id": "800A",
                "contest_id": 800,
                "index": "A",
                "name": "Easy Problem",
                "rating": 800,
                "tags": ["dp"],
                "url": "https://codeforces.com/problemset/problem/800/A",
                "solved": False,
            },
            {
                "problem_id": "1200B",
                "contest_id": 1200,
                "index": "B",
                "name": "Medium Problem",
                "rating": 1200,
                "tags": ["dp"],
                "url": "https://codeforces.com/problemset/problem/1200/B",
                "solved": True,
            },
        ],
        "total": 2,
        "offset": 0,
        "limit": 20,
    }
    d.update(overrides)
    return d


class TestGetCuratedProblems:
    """Tests for GET /training/topics/{topic_id}/curated-problems."""

    @patch("app.api.v1.training.TrainingService")
    @patch("app.api.v1.training._get_cf_service")
    def test_curated_problems_success(self, mock_cf, mock_svc, app_client):
        """Returns curated problems with pagination info."""
        result = MagicMock()
        result.model_dump.return_value = _curated_problems_dict()
        mock_svc.get_curated_problems = AsyncMock(return_value=result)

        resp = app_client.get(f"/training/topics/{SAMPLE_UUID}/curated-problems")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert len(body["data"]["problems"]) == 2
        assert body["data"]["total"] == 2
        assert body["data"]["offset"] == 0
        assert body["data"]["limit"] == 20
        assert body["message"] == "Curated problems retrieved"

    @patch("app.api.v1.training.TrainingService")
    @patch("app.api.v1.training._get_cf_service")
    def test_curated_problems_with_pagination(self, mock_cf, mock_svc, app_client):
        """Supports offset and limit query parameters."""
        result = MagicMock()
        result.model_dump.return_value = _curated_problems_dict(
            problems=[],
            total=50,
            offset=20,
            limit=20,
        )
        mock_svc.get_curated_problems = AsyncMock(return_value=result)

        resp = app_client.get(
            f"/training/topics/{SAMPLE_UUID}/curated-problems?limit=20&offset=20",
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["offset"] == 20
        assert body["data"]["total"] == 50

    @patch("app.api.v1.training.TrainingService")
    @patch("app.api.v1.training._get_cf_service")
    def test_curated_problems_with_rating_filter(self, mock_cf, mock_svc, app_client):
        """Supports min_rating and max_rating query parameters."""
        result = MagicMock()
        result.model_dump.return_value = _curated_problems_dict(total=1)
        mock_svc.get_curated_problems = AsyncMock(return_value=result)

        resp = app_client.get(
            f"/training/topics/{SAMPLE_UUID}/curated-problems?min_rating=1000&max_rating=1600",
        )
        assert resp.status_code == 200

    @patch("app.api.v1.training.TrainingService")
    @patch("app.api.v1.training._get_cf_service")
    def test_curated_problems_topic_not_found(self, mock_cf, mock_svc, app_client):
        """Returns 404 for non-existent topic."""
        mock_svc.get_curated_problems = AsyncMock(
            side_effect=NotFoundException("Topic not found"),
        )

        resp = app_client.get(f"/training/topics/{SAMPLE_UUID}/curated-problems")
        assert resp.status_code == 404

    def test_curated_problems_invalid_uuid(self, app_client):
        """Returns 422 for invalid topic UUID."""
        resp = app_client.get("/training/topics/bad-uuid/curated-problems")
        assert resp.status_code == 422

    def test_curated_problems_unauthenticated(self):
        """Returns 401 for unauthenticated requests."""
        client = _unauth_client()
        resp = client.get(f"/training/topics/{SAMPLE_UUID}/curated-problems")
        assert resp.status_code == 401

    def test_curated_problems_wrong_method(self, app_client):
        """POST is not allowed on this endpoint."""
        resp = app_client.post(f"/training/topics/{SAMPLE_UUID}/curated-problems")
        assert resp.status_code == 405

    @patch("app.api.v1.training.TrainingService")
    @patch("app.api.v1.training._get_cf_service")
    def test_curated_problems_empty(self, mock_cf, mock_svc, app_client):
        """Returns empty list when no problems match filters."""
        result = MagicMock()
        result.model_dump.return_value = {
            "problems": [],
            "total": 0,
            "offset": 0,
            "limit": 20,
        }
        mock_svc.get_curated_problems = AsyncMock(return_value=result)

        resp = app_client.get(f"/training/topics/{SAMPLE_UUID}/curated-problems")
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["problems"] == []
        assert body["data"]["total"] == 0


# ===========================================================================
# GET /training/recommended-topics
# ===========================================================================


def _recommended_topics_list():
    return [
        {
            "slug": "dp",
            "name": "Dynamic Programming",
            "name_zh": "动态规划",
            "melo": 1100.0,
            "reason": "Your Dynamic Programming M-Elo is 1100, the weakest area to improve",
        },
        {
            "slug": "greedy",
            "name": "Greedy",
            "name_zh": "贪心",
            "melo": None,
            "reason": "Your Greedy M-Elo is unestablished -- start practicing!",
        },
        {
            "slug": "math",
            "name": "Math",
            "name_zh": "数学",
            "melo": 1250.0,
            "reason": "Your Math M-Elo is 1250, the weakest area to improve",
        },
    ]


class TestGetRecommendedTopics:
    """Tests for GET /training/recommended-topics."""

    @patch("app.api.v1.training.TrainingService")
    def test_recommended_topics_success(self, mock_svc, app_client):
        """Returns 2-3 recommended topics with reason text."""
        topics = [
            MagicMock(
                slug=t["slug"],
                name=t["name"],
                name_zh=t["name_zh"],
                melo=t["melo"],
                reason=t["reason"],
                model_dump=MagicMock(return_value=t),
            )
            for t in _recommended_topics_list()
        ]
        mock_svc.get_recommended_topics = AsyncMock(return_value=topics)

        resp = app_client.get("/training/recommended-topics")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert len(body["data"]) == 3
        assert body["data"][0]["slug"] == "dp"
        assert "weakest" in body["data"][0]["reason"]
        assert body["message"] == "Recommended topics retrieved"

    @patch("app.api.v1.training.TrainingService")
    def test_recommended_topics_custom_limit(self, mock_svc, app_client):
        """Respects the limit query parameter."""
        topic = _recommended_topics_list()[0]
        mock_topic = MagicMock(
            slug=topic["slug"],
            name=topic["name"],
            name_zh=topic["name_zh"],
            melo=topic["melo"],
            reason=topic["reason"],
            model_dump=MagicMock(return_value=topic),
        )
        mock_svc.get_recommended_topics = AsyncMock(return_value=[mock_topic])

        resp = app_client.get("/training/recommended-topics?limit=1")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["data"]) == 1

    def test_recommended_topics_unauthenticated(self):
        """Returns 401 for unauthenticated requests."""
        client = _unauth_client()
        resp = client.get("/training/recommended-topics")
        assert resp.status_code == 401

    def test_recommended_topics_wrong_method(self, app_client):
        """POST is not allowed on this endpoint."""
        resp = app_client.post("/training/recommended-topics")
        assert resp.status_code == 405
