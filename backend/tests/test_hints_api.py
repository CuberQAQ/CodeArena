"""API route tests for app/api/v1/hints.py.

Tests cover all 4 hint endpoints:
  GET  /hints/{problem_id}/status           -- get hint status and pricing
  POST /hints/{problem_id}/unlock           -- unlock a hint level
  GET  /hints/{problem_id}/content/{level}  -- get hint content for a level
  GET  /hints/{problem_id}/history          -- get hint purchase history
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
    ForbiddenException,
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


def _make_simple_response(**data):
    """Build a namespace object that has model_dump() returning the data dict."""
    ns = SimpleNamespace(**data)
    ns.model_dump = lambda **kwargs: data
    return ns


# ===========================================================================
# GET /hints/{problem_id}/status
# ===========================================================================


class TestGetHintStatus:
    """Tests for GET /hints/{problem_id}/status."""

    @patch("app.api.v1.hints.HintService")
    def test_status_success(self, mock_hint_svc, app_client):
        mock_hint_svc.get_hint_status = AsyncMock(
            return_value=_make_simple_response(
                problem_id="123A",
                problem_rating=1500,
                unlocked_levels=[1],
                prices=[{"level": 1, "tokens": 5}, {"level": 2, "tokens": 10}],
                elo_decay_preview=[{"level": 1, "multiplier": 0.95}, {"level": 2, "multiplier": 0.85}],
                next_level=2,
                next_level_price=10,
            )
        )

        resp = app_client.get("/hints/123A/status")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["problem_id"] == "123A"
        assert body["data"]["problem_rating"] == 1500
        assert body["data"]["unlocked_levels"] == [1]
        assert body["data"]["next_level"] == 2
        assert body["message"] == "Hint status retrieved"

    @patch("app.api.v1.hints.HintService")
    def test_status_with_custom_rating(self, mock_hint_svc, app_client):
        mock_hint_svc.get_hint_status = AsyncMock(
            return_value=_make_simple_response(
                problem_id="456B",
                problem_rating=2000,
                unlocked_levels=[],
                prices=[],
                elo_decay_preview=[],
                next_level=1,
                next_level_price=5,
            )
        )

        resp = app_client.get("/hints/456B/status", params={"problem_rating": 2000})
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["problem_rating"] == 2000
        # Verify the service was called with the custom rating
        call_kwargs = mock_hint_svc.get_hint_status.call_args.kwargs
        assert call_kwargs["problem_rating"] == 2000

    @patch("app.api.v1.hints.HintService")
    def test_status_no_unlocked_hints(self, mock_hint_svc, app_client):
        mock_hint_svc.get_hint_status = AsyncMock(
            return_value=_make_simple_response(
                problem_id="789C",
                problem_rating=1000,
                unlocked_levels=[],
                prices=[{"level": 1, "tokens": 5}],
                elo_decay_preview=[{"level": 1, "multiplier": 0.95}],
                next_level=1,
                next_level_price=5,
            )
        )

        resp = app_client.get("/hints/789C/status")
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["unlocked_levels"] == []

    def test_status_unauthenticated(self):
        client = _unauth_client()
        resp = client.get("/hints/123A/status")
        assert resp.status_code == 401

    def test_status_wrong_http_method(self, app_client):
        resp = app_client.post("/hints/123A/status")
        assert resp.status_code == 405


# ===========================================================================
# POST /hints/{problem_id}/unlock
# ===========================================================================


class TestUnlockHint:
    """Tests for POST /hints/{problem_id}/unlock."""

    @patch("app.api.v1.hints.HintService")
    def test_unlock_success(self, mock_hint_svc, app_client):
        mock_hint_svc.unlock_hint = AsyncMock(
            return_value=_make_simple_response(
                problem_id="123A",
                level=1,
                tokens_spent=5,
                tokens_remaining=95,
            )
        )

        resp = app_client.post("/hints/123A/unlock", json={"level": 1})
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["level"] == 1
        assert body["data"]["tokens_spent"] == 5
        assert body["data"]["tokens_remaining"] == 95
        assert body["message"] == "Hint level 1 unlocked"

    @patch("app.api.v1.hints.HintService")
    def test_unlock_level_2(self, mock_hint_svc, app_client):
        mock_hint_svc.unlock_hint = AsyncMock(
            return_value=_make_simple_response(
                problem_id="123A",
                level=2,
                tokens_spent=10,
                tokens_remaining=85,
            )
        )

        resp = app_client.post("/hints/123A/unlock", json={"level": 2})
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["level"] == 2
        assert body["message"] == "Hint level 2 unlocked"

    @patch("app.api.v1.hints.HintService")
    def test_unlock_insufficient_tokens(self, mock_hint_svc, app_client):
        mock_hint_svc.unlock_hint = AsyncMock(
            side_effect=BadRequestException("Insufficient tokens"),
        )

        resp = app_client.post("/hints/123A/unlock", json={"level": 2})
        assert resp.status_code == 400

    @patch("app.api.v1.hints.HintService")
    def test_unlock_already_unlocked(self, mock_hint_svc, app_client):
        mock_hint_svc.unlock_hint = AsyncMock(
            side_effect=BadRequestException("Hint level already unlocked"),
        )

        resp = app_client.post("/hints/123A/unlock", json={"level": 1})
        assert resp.status_code == 400

    def test_unlock_invalid_level_zero(self, app_client):
        resp = app_client.post("/hints/123A/unlock", json={"level": 0})
        assert resp.status_code == 422

    def test_unlock_invalid_level_four(self, app_client):
        resp = app_client.post("/hints/123A/unlock", json={"level": 4})
        assert resp.status_code == 422

    def test_unlock_missing_body(self, app_client):
        resp = app_client.post("/hints/123A/unlock")
        assert resp.status_code == 422

    @patch("app.api.v1.hints.HintService")
    def test_unlock_with_custom_rating(self, mock_hint_svc, app_client):
        mock_hint_svc.unlock_hint = AsyncMock(
            return_value=_make_simple_response(
                problem_id="123A",
                level=1,
                tokens_spent=5,
                tokens_remaining=95,
            )
        )

        resp = app_client.post(
            "/hints/123A/unlock",
            json={"level": 1},
            params={"problem_rating": 2000},
        )
        assert resp.status_code == 200
        call_kwargs = mock_hint_svc.unlock_hint.call_args.kwargs
        assert call_kwargs["problem_rating"] == 2000

    def test_unlock_unauthenticated(self):
        client = _unauth_client()
        resp = client.post("/hints/123A/unlock", json={"level": 1})
        assert resp.status_code == 401


# ===========================================================================
# GET /hints/{problem_id}/content/{level}
# ===========================================================================


class TestGetHintContent:
    """Tests for GET /hints/{problem_id}/content/{level}."""

    @patch("app.api.v1.hints.HintService")
    def test_content_success(self, mock_hint_svc, app_client):
        mock_hint_svc.get_hint_content = AsyncMock(
            return_value=_make_simple_response(
                problem_id="123A",
                level=1,
                content="Think about using a hash map",
                unlocked=True,
            )
        )

        resp = app_client.get("/hints/123A/content/1")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["content"] == "Think about using a hash map"
        assert body["data"]["unlocked"] is True
        assert body["data"]["level"] == 1
        assert body["message"] == "Hint content retrieved"

    @patch("app.api.v1.hints.HintService")
    def test_content_not_unlocked(self, mock_hint_svc, app_client):
        mock_hint_svc.get_hint_content = AsyncMock(
            side_effect=ForbiddenException("Hint not unlocked"),
        )

        resp = app_client.get("/hints/123A/content/2")
        assert resp.status_code == 403

    @patch("app.api.v1.hints.HintService")
    def test_content_with_custom_rating(self, mock_hint_svc, app_client):
        mock_hint_svc.get_hint_content = AsyncMock(
            return_value=_make_simple_response(
                problem_id="123A",
                level=1,
                content="Some hint",
                unlocked=True,
            )
        )

        resp = app_client.get("/hints/123A/content/1", params={"problem_rating": 1800})
        assert resp.status_code == 200
        call_kwargs = mock_hint_svc.get_hint_content.call_args.kwargs
        assert call_kwargs["problem_rating"] == 1800

    def test_content_unauthenticated(self):
        client = _unauth_client()
        resp = client.get("/hints/123A/content/1")
        assert resp.status_code == 401

    def test_content_wrong_http_method(self, app_client):
        resp = app_client.post("/hints/123A/content/1")
        assert resp.status_code == 405


# ===========================================================================
# GET /hints/{problem_id}/history
# ===========================================================================


class TestGetHintHistory:
    """Tests for GET /hints/{problem_id}/history."""

    @patch("app.api.v1.hints.HintService")
    def test_history_success_empty(self, mock_hint_svc, app_client):
        mock_hint_svc.get_hint_history = AsyncMock(
            return_value=_make_simple_response(
                problem_id="123A",
                purchases=[],
                total_spent=0,
            )
        )

        resp = app_client.get("/hints/123A/history")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["purchases"] == []
        assert body["data"]["total_spent"] == 0
        assert body["message"] == "Hint history retrieved"

    @patch("app.api.v1.hints.HintService")
    def test_history_with_purchases(self, mock_hint_svc, app_client):
        purchases = [
            {
                "id": "00000000-0000-0000-0000-000000000001",
                "problem_id": "123A",
                "hint_level": 1,
                "tokens_cost": 5,
                "created_at": "2026-05-22T10:00:00Z",
            },
            {
                "id": "00000000-0000-0000-0000-000000000002",
                "problem_id": "123A",
                "hint_level": 2,
                "tokens_cost": 10,
                "created_at": "2026-05-22T10:05:00Z",
            },
        ]
        mock_hint_svc.get_hint_history = AsyncMock(
            return_value=_make_simple_response(
                problem_id="123A",
                purchases=purchases,
                total_spent=15,
            )
        )

        resp = app_client.get("/hints/123A/history")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["data"]["purchases"]) == 2
        assert body["data"]["total_spent"] == 15

    def test_history_unauthenticated(self):
        client = _unauth_client()
        resp = client.get("/hints/123A/history")
        assert resp.status_code == 401

    def test_history_wrong_http_method(self, app_client):
        resp = app_client.post("/hints/123A/history")
        assert resp.status_code == 405


# ===========================================================================
# Cross-cutting: response envelope
# ===========================================================================


class TestResponseEnvelope:
    """Verify that all successful responses have the standard envelope."""

    @patch("app.api.v1.hints.HintService")
    def test_status_envelope(self, mock_hint_svc, app_client):
        mock_hint_svc.get_hint_status = AsyncMock(
            return_value=_make_simple_response(
                problem_id="123A",
                problem_rating=1000,
                unlocked_levels=[],
                prices=[],
                elo_decay_preview=[],
                next_level=None,
                next_level_price=None,
            )
        )

        resp = app_client.get("/hints/123A/status")
        body = resp.json()
        assert "success" in body
        assert "data" in body
        assert "message" in body
        assert body["success"] is True

    @patch("app.api.v1.hints.HintService")
    def test_unlock_envelope(self, mock_hint_svc, app_client):
        mock_hint_svc.unlock_hint = AsyncMock(
            return_value=_make_simple_response(
                problem_id="123A",
                level=1,
                tokens_spent=5,
                tokens_remaining=95,
            )
        )

        resp = app_client.post("/hints/123A/unlock", json={"level": 1})
        body = resp.json()
        assert "success" in body
        assert "data" in body
        assert "message" in body
        assert body["success"] is True
