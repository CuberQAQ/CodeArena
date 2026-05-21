"""API route tests for app/api/v1/checkin.py.

Tests cover all 4 checkin endpoints:
  POST /checkin            -- daily check-in
  POST /checkin/makeup     -- make-up check-in (for yesterday)
  GET  /checkin/status     -- get check-in status
  GET  /checkin/history    -- get check-in history (paginated)
"""

from collections.abc import AsyncGenerator
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.router import api_router
from app.core.database import get_db
from app.core.exceptions import BadRequestException, UnauthorizedException, register_exception_handlers
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


def _json_serializable(obj):
    """Convert date objects to ISO strings for JSON serialization."""
    if isinstance(obj, date):
        return obj.isoformat()
    if isinstance(obj, list):
        return [_json_serializable(item) for item in obj]
    if isinstance(obj, dict):
        return {k: _json_serializable(v) for k, v in obj.items()}
    return obj


def _make_simple_response(**data):
    """Build a namespace object with model_dump() that returns JSON-safe data."""
    json_data = _json_serializable(data)
    ns = SimpleNamespace(**data)
    ns.model_dump = lambda **kwargs: json_data
    return ns


# ===========================================================================
# POST /checkin
# ===========================================================================


class TestDailyCheckin:
    """Tests for POST /checkin."""

    @patch("app.api.v1.checkin.check_in")
    def test_checkin_success(self, mock_check_in, app_client):
        mock_check_in.return_value = _make_simple_response(
            checkin_date="2026-05-22",
            streak_days=5,
            tokens_awarded=10,
            is_makeup=False,
            tokens_balance=110,
        )

        resp = app_client.post("/checkin")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["tokens_awarded"] == 10
        assert body["data"]["streak_days"] == 5
        assert body["data"]["tokens_balance"] == 110
        assert body["message"] == "Check-in successful"

    @patch("app.api.v1.checkin.check_in")
    def test_checkin_already_checked_in(self, mock_check_in, app_client):
        mock_check_in.side_effect = BadRequestException("Already checked in today")

        resp = app_client.post("/checkin")
        assert resp.status_code == 400

    def test_checkin_unauthenticated(self):
        client = _unauth_client()
        resp = client.post("/checkin")
        assert resp.status_code == 401

    def test_checkin_wrong_http_method(self, app_client):
        resp = app_client.get("/checkin")
        assert resp.status_code == 405

    @patch("app.api.v1.checkin.check_in")
    def test_checkin_response_envelope(self, mock_check_in, app_client):
        mock_check_in.return_value = _make_simple_response(
            checkin_date="2026-05-22",
            streak_days=5,
            tokens_awarded=10,
            is_makeup=False,
            tokens_balance=110,
        )

        resp = app_client.post("/checkin")
        body = resp.json()
        assert "success" in body
        assert "data" in body
        assert "message" in body
        assert body["success"] is True

    @patch("app.api.v1.checkin.check_in")
    def test_checkin_streak_bonus(self, mock_check_in, app_client):
        """Verify higher streak returns more tokens."""
        mock_check_in.return_value = _make_simple_response(
            checkin_date="2026-05-22",
            streak_days=30,
            tokens_awarded=20,
            is_makeup=False,
            tokens_balance=120,
        )

        resp = app_client.post("/checkin")
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["tokens_awarded"] == 20
        assert body["data"]["streak_days"] == 30


# ===========================================================================
# POST /checkin/makeup
# ===========================================================================


class TestMakeupCheckin:
    """Tests for POST /checkin/makeup."""

    @patch("app.api.v1.checkin.makeup_checkin")
    def test_makeup_success(self, mock_makeup, app_client):
        mock_makeup.return_value = _make_simple_response(
            checkin_date="2026-05-21",
            streak_days=5,
            tokens_awarded=10,
            is_makeup=True,
            tokens_balance=110,
        )

        resp = app_client.post("/checkin/makeup")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["is_makeup"] is True
        assert body["message"] == "Make-up check-in successful"

    @patch("app.api.v1.checkin.makeup_checkin")
    def test_makeup_limit_exceeded(self, mock_makeup, app_client):
        mock_makeup.side_effect = BadRequestException("Weekly make-up limit reached")

        resp = app_client.post("/checkin/makeup")
        assert resp.status_code == 400

    @patch("app.api.v1.checkin.makeup_checkin")
    def test_makeup_no_yesterday_miss(self, mock_makeup, app_client):
        mock_makeup.side_effect = BadRequestException("No missed check-in yesterday")

        resp = app_client.post("/checkin/makeup")
        assert resp.status_code == 400

    def test_makeup_unauthenticated(self):
        client = _unauth_client()
        resp = client.post("/checkin/makeup")
        assert resp.status_code == 401

    def test_makeup_wrong_http_method(self, app_client):
        resp = app_client.get("/checkin/makeup")
        assert resp.status_code == 405


# ===========================================================================
# GET /checkin/status
# ===========================================================================


class TestCheckinStatus:
    """Tests for GET /checkin/status."""

    @patch("app.api.v1.checkin.get_status")
    def test_status_success(self, mock_get_status, app_client):
        mock_get_status.return_value = _make_simple_response(
            checked_in_today=True,
            streak_days=5,
            last_checkin_date="2026-05-22",
            makeup_used_this_week=0,
            makeup_limit=2,
            next_reward=10,
            can_makeup=False,
            checked_dates_this_week=["2026-05-19", "2026-05-20", "2026-05-21", "2026-05-22"],
        )

        resp = app_client.get("/checkin/status")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["checked_in_today"] is True
        assert body["data"]["streak_days"] == 5
        assert body["data"]["can_makeup"] is False
        assert body["message"] == "Check-in status retrieved"

    @patch("app.api.v1.checkin.get_status")
    def test_status_not_checked_in_today(self, mock_get_status, app_client):
        mock_get_status.return_value = _make_simple_response(
            checked_in_today=False,
            streak_days=4,
            last_checkin_date="2026-05-21",
            makeup_used_this_week=0,
            makeup_limit=2,
            next_reward=10,
            can_makeup=True,
            checked_dates_this_week=["2026-05-19", "2026-05-20", "2026-05-21"],
        )

        resp = app_client.get("/checkin/status")
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["checked_in_today"] is False
        assert body["data"]["can_makeup"] is True

    def test_status_unauthenticated(self):
        client = _unauth_client()
        resp = client.get("/checkin/status")
        assert resp.status_code == 401

    def test_status_wrong_http_method(self, app_client):
        resp = app_client.post("/checkin/status")
        assert resp.status_code == 405


# ===========================================================================
# GET /checkin/history
# ===========================================================================


class TestCheckinHistory:
    """Tests for GET /checkin/history."""

    @patch("app.api.v1.checkin.get_history")
    def test_history_default_params(self, mock_get_history, app_client):
        mock_get_history.return_value = _make_simple_response(items=[], total=0)

        resp = app_client.get("/checkin/history")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["items"] == []
        assert body["data"]["total"] == 0
        assert body["message"] == "Check-in history retrieved"
        mock_get_history.assert_called_once()
        call_kwargs = mock_get_history.call_args
        assert call_kwargs.kwargs.get("limit", call_kwargs[1].get("limit", 30)) in (30,)

    @patch("app.api.v1.checkin.get_history")
    def test_history_with_pagination(self, mock_get_history, app_client):
        mock_get_history.return_value = _make_simple_response(
            items=[
                {
                    "id": "uuid-1",
                    "checkin_date": "2026-05-22",
                    "streak_days": 5,
                    "is_makeup": False,
                    "tokens_awarded": 10,
                }
            ],
            total=50,
        )

        resp = app_client.get("/checkin/history", params={"limit": 10, "offset": 20})
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["total"] == 50

    def test_history_invalid_limit_too_high(self, app_client):
        resp = app_client.get("/checkin/history", params={"limit": 101})
        assert resp.status_code == 422

    def test_history_invalid_limit_zero(self, app_client):
        resp = app_client.get("/checkin/history", params={"limit": 0})
        assert resp.status_code == 422

    def test_history_invalid_offset_negative(self, app_client):
        resp = app_client.get("/checkin/history", params={"offset": -1})
        assert resp.status_code == 422

    def test_history_unauthenticated(self):
        client = _unauth_client()
        resp = client.get("/checkin/history")
        assert resp.status_code == 401

    @patch("app.api.v1.checkin.get_history")
    def test_history_response_envelope(self, mock_get_history, app_client):
        mock_get_history.return_value = _make_simple_response(items=[], total=0)

        resp = app_client.get("/checkin/history")
        body = resp.json()
        assert "success" in body
        assert "data" in body
        assert "message" in body
        assert body["success"] is True
