"""API route tests for app/api/v1/submission_tracking.py.

Tests cover all 3 submission tracking endpoints:
  POST /submission-tracking/register
  GET  /submission-tracking/status
  GET  /submission-tracking/pending
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
    UnauthorizedException,
    register_exception_handlers,
)
from app.core.security import get_current_user

# ---------------------------------------------------------------------------
# App factory & mock DB
# ---------------------------------------------------------------------------


def _make_mock_db_session():
    """Create a mock async session."""
    session = MagicMock(spec=AsyncSession)
    session.execute = AsyncMock(return_value=MagicMock())
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.close = AsyncMock()
    session.flush = AsyncMock()
    session.add = MagicMock()
    return session


async def _mock_get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield a mock async session; never touches real DB."""
    yield _make_mock_db_session()


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

SAMPLE_UUID = "00000000-0000-0000-0000-0000000000ee"


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


def _make_tracking_mock(**overrides):
    """Create a mock tracking record."""
    tracking = MagicMock()
    tracking.id = overrides.get("id", SAMPLE_UUID)
    tracking.session_type = overrides.get("session_type", "pvp")
    tracking.session_id = overrides.get("session_id", SAMPLE_UUID)
    tracking.problem_id = overrides.get("problem_id", "1234A")
    tracking.status = overrides.get("status", "pending")
    tracking.cf_submission_id = overrides.get("cf_submission_id")
    tracking.cf_verdict = overrides.get("cf_verdict")
    tracking.expected_at = overrides.get("expected_at", datetime(2025, 1, 1, tzinfo=UTC))
    tracking.matched_at = overrides.get("matched_at")
    tracking.created_at = overrides.get("created_at", datetime(2025, 1, 1, tzinfo=UTC))
    return tracking


def _db_with_pending_records(records):
    """Create a mock DB that returns the given records for the pending list query."""
    session = _make_mock_db_session()

    mock_scalars = MagicMock()
    mock_scalars.all.return_value = records
    mock_result = MagicMock()
    mock_result.scalars.return_value = mock_scalars
    session.execute = AsyncMock(return_value=mock_result)

    return session


# ===========================================================================
# POST /submission-tracking/register
# ===========================================================================


class TestRegisterPending:
    """Tests for POST /submission-tracking/register."""

    @patch("app.api.v1.submission_tracking.SubmissionTracker")
    def test_register_success(self, mock_tracker, app_client):
        tracking = _make_tracking_mock(status="pending")
        mock_tracker.register_pending = AsyncMock(return_value=tracking)

        resp = app_client.post(
            "/submission-tracking/register",
            json={
                "session_type": "pvp",
                "session_id": SAMPLE_UUID,
                "problem_id": "1234A",
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["tracking_id"] == SAMPLE_UUID
        assert body["data"]["status"] == "pending"
        assert body["message"] == "Pending submission registered"

    @patch("app.api.v1.submission_tracking.SubmissionTracker")
    def test_register_contest_session(self, mock_tracker, app_client):
        tracking = _make_tracking_mock(session_type="contest")
        mock_tracker.register_pending = AsyncMock(return_value=tracking)

        resp = app_client.post(
            "/submission-tracking/register",
            json={
                "session_type": "contest",
                "session_id": SAMPLE_UUID,
                "problem_id": "1234A",
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["tracking_id"] == SAMPLE_UUID

    @patch("app.api.v1.submission_tracking.SubmissionTracker")
    def test_register_training_session(self, mock_tracker, app_client):
        tracking = _make_tracking_mock(session_type="training")
        mock_tracker.register_pending = AsyncMock(return_value=tracking)

        resp = app_client.post(
            "/submission-tracking/register",
            json={
                "session_type": "training",
                "session_id": SAMPLE_UUID,
                "problem_id": "1234A",
            },
        )
        assert resp.status_code == 200

    def test_register_missing_session_type(self, app_client):
        resp = app_client.post(
            "/submission-tracking/register",
            json={"session_id": SAMPLE_UUID, "problem_id": "1234A"},
        )
        assert resp.status_code == 422

    def test_register_missing_session_id(self, app_client):
        resp = app_client.post(
            "/submission-tracking/register",
            json={"session_type": "pvp", "problem_id": "1234A"},
        )
        assert resp.status_code == 422

    def test_register_missing_problem_id(self, app_client):
        resp = app_client.post(
            "/submission-tracking/register",
            json={"session_type": "pvp", "session_id": SAMPLE_UUID},
        )
        assert resp.status_code == 422

    def test_register_invalid_session_id(self, app_client):
        resp = app_client.post(
            "/submission-tracking/register",
            json={"session_type": "pvp", "session_id": "not-a-uuid", "problem_id": "1234A"},
        )
        assert resp.status_code == 422

    def test_register_empty_body(self, app_client):
        resp = app_client.post("/submission-tracking/register", json={})
        assert resp.status_code == 422

    @patch("app.api.v1.submission_tracking.SubmissionTracker")
    def test_register_duplicate(self, mock_tracker, app_client):
        mock_tracker.register_pending = AsyncMock(
            side_effect=BadRequestException("Already tracking for this session"),
        )

        resp = app_client.post(
            "/submission-tracking/register",
            json={
                "session_type": "pvp",
                "session_id": SAMPLE_UUID,
                "problem_id": "1234A",
            },
        )
        assert resp.status_code == 400

    def test_register_unauthenticated(self):
        client = _unauth_client()
        resp = client.post(
            "/submission-tracking/register",
            json={
                "session_type": "pvp",
                "session_id": SAMPLE_UUID,
                "problem_id": "1234A",
            },
        )
        assert resp.status_code == 401


# ===========================================================================
# GET /submission-tracking/status
# ===========================================================================


class TestGetTrackingStatus:
    """Tests for GET /submission-tracking/status."""

    @patch("app.api.v1.submission_tracking.SubmissionTracker")
    def test_status_pending(self, mock_tracker, app_client):
        tracking = _make_tracking_mock(status="pending")
        mock_tracker.get_tracking_for_session = AsyncMock(return_value=tracking)

        resp = app_client.get(
            "/submission-tracking/status",
            params={"session_type": "pvp", "session_id": SAMPLE_UUID},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["status"] == "pending"
        assert body["data"]["problem_id"] == "1234A"
        assert body["message"] == "Tracking status retrieved"

    @patch("app.api.v1.submission_tracking.SubmissionTracker")
    def test_status_matched(self, mock_tracker, app_client):
        tracking = _make_tracking_mock(
            status="matched",
            cf_submission_id=12345678,
            cf_verdict="OK",
            matched_at=datetime(2025, 1, 1, 12, 0, tzinfo=UTC),
        )
        mock_tracker.get_tracking_for_session = AsyncMock(return_value=tracking)

        resp = app_client.get(
            "/submission-tracking/status",
            params={"session_type": "pvp", "session_id": SAMPLE_UUID},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["status"] == "matched"
        assert body["data"]["cf_submission_id"] == 12345678
        assert body["data"]["cf_verdict"] == "OK"

    @patch("app.api.v1.submission_tracking.SubmissionTracker")
    def test_status_not_found(self, mock_tracker, app_client):
        mock_tracker.get_tracking_for_session = AsyncMock(return_value=None)

        resp = app_client.get(
            "/submission-tracking/status",
            params={"session_type": "pvp", "session_id": SAMPLE_UUID},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"] is None
        assert "No tracking record" in body["message"]

    def test_status_missing_session_type(self, app_client):
        resp = app_client.get(
            "/submission-tracking/status",
            params={"session_id": SAMPLE_UUID},
        )
        assert resp.status_code == 422

    def test_status_missing_session_id(self, app_client):
        resp = app_client.get(
            "/submission-tracking/status",
            params={"session_type": "pvp"},
        )
        assert resp.status_code == 422

    def test_status_invalid_session_id(self, app_client):
        resp = app_client.get(
            "/submission-tracking/status",
            params={"session_type": "pvp", "session_id": "not-a-uuid"},
        )
        assert resp.status_code == 422

    def test_status_unauthenticated(self):
        client = _unauth_client()
        resp = client.get(
            "/submission-tracking/status",
            params={"session_type": "pvp", "session_id": SAMPLE_UUID},
        )
        assert resp.status_code == 401


# ===========================================================================
# GET /submission-tracking/pending
# ===========================================================================


class TestListPending:
    """Tests for GET /submission-tracking/pending."""

    def test_pending_with_records(self, app_client):
        r1 = _make_tracking_mock(
            id="00000000-0000-0000-0000-000000000001",
            session_type="pvp",
            problem_id="1234A",
            status="pending",
        )
        r2 = _make_tracking_mock(
            id="00000000-0000-0000-0000-000000000002",
            session_type="training",
            problem_id="5678B",
            status="matched",
            cf_submission_id=99999,
        )

        mock_db = _db_with_pending_records([r1, r2])

        async def _mock_db():
            yield mock_db

        app = _create_app()
        app.dependency_overrides[get_db] = _mock_db
        app.dependency_overrides[get_current_user] = lambda: _make_mock_user()
        client = TestClient(app)

        resp = client.get("/submission-tracking/pending")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert len(body["data"]) == 2
        assert body["data"][0]["status"] == "pending"
        assert body["data"][1]["status"] == "matched"
        assert "2 pending" in body["message"]

    def test_pending_empty(self, app_client):
        mock_db = _db_with_pending_records([])

        async def _mock_db():
            yield mock_db

        app = _create_app()
        app.dependency_overrides[get_db] = _mock_db
        app.dependency_overrides[get_current_user] = lambda: _make_mock_user()
        client = TestClient(app)

        resp = client.get("/submission-tracking/pending")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"] == []
        assert "0 pending" in body["message"]

    def test_pending_unauthenticated(self):
        client = _unauth_client()
        resp = client.get("/submission-tracking/pending")
        assert resp.status_code == 401

    def test_pending_wrong_method(self, app_client):
        resp = app_client.post("/submission-tracking/pending")
        assert resp.status_code == 405


# ===========================================================================
# Cross-cutting: response envelope
# ===========================================================================


class TestSubmissionTrackingResponseEnvelope:
    """Verify all successful submission tracking responses have standard envelope."""

    @patch("app.api.v1.submission_tracking.SubmissionTracker")
    def test_register_envelope(self, mock_tracker, app_client):
        tracking = _make_tracking_mock(status="pending")
        mock_tracker.register_pending = AsyncMock(return_value=tracking)

        resp = app_client.post(
            "/submission-tracking/register",
            json={
                "session_type": "pvp",
                "session_id": SAMPLE_UUID,
                "problem_id": "1234A",
            },
        )
        body = resp.json()
        assert "success" in body
        assert "data" in body
        assert "message" in body
        assert body["success"] is True

    @patch("app.api.v1.submission_tracking.SubmissionTracker")
    def test_status_envelope(self, mock_tracker, app_client):
        tracking = _make_tracking_mock()
        mock_tracker.get_tracking_for_session = AsyncMock(return_value=tracking)

        resp = app_client.get(
            "/submission-tracking/status",
            params={"session_type": "pvp", "session_id": SAMPLE_UUID},
        )
        body = resp.json()
        assert "success" in body
        assert "data" in body
        assert "message" in body
        assert body["success"] is True
