"""API route tests for app/api/v1/cf_handle.py.

Tests cover all 4 CF Handle endpoints:
  POST   /cf-handle/bind           -- initiate CF Handle binding
  POST   /cf-handle/verify         -- verify CF Handle via bio check
  GET    /cf-handle/info/{handle}  -- look up public CF user info (public)
  DELETE /cf-handle/unbind         -- unbind CF Handle

The _get_cf_service singleton is patched at module level to avoid
instantiating a real CFApiService (no external HTTP calls).
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
    ConflictException,
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
    user.email = "test@example.com"
    user.cf_handle = None
    user.cf_handle_verified = False
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


# ===========================================================================
# POST /cf-handle/bind
# ===========================================================================


class TestBindCfHandle:
    """Tests for POST /cf-handle/bind."""

    @patch("app.api.v1.cf_handle.cf_handle_service")
    @patch("app.api.v1.cf_handle._get_cf_service")
    def test_bind_success(self, mock_cf_service_fn, mock_svc, app_client):
        mock_cf_svc = MagicMock()
        mock_cf_service_fn.return_value = mock_cf_svc
        mock_svc.bind_cf_handle = AsyncMock(
            return_value={
                "cf_handle": "tourist",
                "verification_code": "abcd1234",
                "status": "pending_verification",
            },
        )

        resp = app_client.post("/cf-handle/bind", json={"cf_handle": "tourist"})
        assert resp.status_code == 201
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["cf_handle"] == "tourist"
        assert body["data"]["verification_code"] == "abcd1234"
        assert "verification code" in body["message"].lower()

    @patch("app.api.v1.cf_handle.cf_handle_service")
    @patch("app.api.v1.cf_handle._get_cf_service")
    def test_bind_already_bound(self, mock_cf_service_fn, mock_svc, app_client):
        mock_cf_service_fn.return_value = MagicMock()
        mock_svc.bind_cf_handle = AsyncMock(
            side_effect=ConflictException("CF Handle already bound"),
        )

        resp = app_client.post("/cf-handle/bind", json={"cf_handle": "tourist"})
        assert resp.status_code == 409

    @patch("app.api.v1.cf_handle.cf_handle_service")
    @patch("app.api.v1.cf_handle._get_cf_service")
    def test_bind_handle_not_found_on_cf(self, mock_cf_service_fn, mock_svc, app_client):
        mock_cf_service_fn.return_value = MagicMock()
        mock_svc.bind_cf_handle = AsyncMock(
            side_effect=NotFoundException("CF Handle not found on Codeforces"),
        )

        resp = app_client.post("/cf-handle/bind", json={"cf_handle": "nonexistent"})
        assert resp.status_code == 404

    def test_bind_missing_body(self, app_client):
        resp = app_client.post("/cf-handle/bind")
        assert resp.status_code == 422

    def test_bind_empty_handle(self, app_client):
        resp = app_client.post("/cf-handle/bind", json={"cf_handle": ""})
        assert resp.status_code == 422

    def test_bind_handle_too_long(self, app_client):
        resp = app_client.post("/cf-handle/bind", json={"cf_handle": "a" * 101})
        assert resp.status_code == 422

    def test_bind_unauthenticated(self):
        client = _unauth_client()
        resp = client.post("/cf-handle/bind", json={"cf_handle": "tourist"})
        assert resp.status_code == 401

    def test_bind_wrong_http_method(self, app_client):
        resp = app_client.get("/cf-handle/bind")
        assert resp.status_code == 405


# ===========================================================================
# POST /cf-handle/verify
# ===========================================================================


class TestVerifyCfHandle:
    """Tests for POST /cf-handle/verify."""

    @patch("app.api.v1.cf_handle.cf_handle_service")
    @patch("app.api.v1.cf_handle._get_cf_service")
    def test_verify_success(self, mock_cf_service_fn, mock_svc, app_client):
        mock_cf_service_fn.return_value = MagicMock()
        mock_svc.verify_cf_handle = AsyncMock(
            return_value={
                "cf_handle": "tourist",
                "cf_handle_verified": True,
                "rating": 3979,
            },
        )

        resp = app_client.post(
            "/cf-handle/verify",
            json={"cf_handle": "tourist", "verification_code": "abcd1234"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["cf_handle_verified"] is True
        assert body["message"] == "CF Handle verified successfully"

    @patch("app.api.v1.cf_handle.cf_handle_service")
    @patch("app.api.v1.cf_handle._get_cf_service")
    def test_verify_wrong_code(self, mock_cf_service_fn, mock_svc, app_client):
        mock_cf_service_fn.return_value = MagicMock()
        mock_svc.verify_cf_handle = AsyncMock(
            side_effect=BadRequestException("Verification code not found in CF bio"),
        )

        resp = app_client.post(
            "/cf-handle/verify",
            json={"cf_handle": "tourist", "verification_code": "wrongcd1"},
        )
        assert resp.status_code == 400

    @patch("app.api.v1.cf_handle.cf_handle_service")
    @patch("app.api.v1.cf_handle._get_cf_service")
    def test_verify_not_bound(self, mock_cf_service_fn, mock_svc, app_client):
        mock_cf_service_fn.return_value = MagicMock()
        mock_svc.verify_cf_handle = AsyncMock(
            side_effect=NotFoundException("No pending binding for this handle"),
        )

        resp = app_client.post(
            "/cf-handle/verify",
            json={"cf_handle": "tourist", "verification_code": "abcd1234"},
        )
        assert resp.status_code == 404

    def test_verify_missing_body(self, app_client):
        resp = app_client.post("/cf-handle/verify")
        assert resp.status_code == 422

    def test_verify_missing_verification_code(self, app_client):
        resp = app_client.post(
            "/cf-handle/verify",
            json={"cf_handle": "tourist"},
        )
        assert resp.status_code == 422

    def test_verify_empty_handle(self, app_client):
        resp = app_client.post(
            "/cf-handle/verify",
            json={"cf_handle": "", "verification_code": "abcd1234"},
        )
        assert resp.status_code == 422

    def test_verify_code_wrong_length(self, app_client):
        # Code must be exactly 8 chars
        resp = app_client.post(
            "/cf-handle/verify",
            json={"cf_handle": "tourist", "verification_code": "short"},
        )
        assert resp.status_code == 422

    def test_verify_code_too_long(self, app_client):
        resp = app_client.post(
            "/cf-handle/verify",
            json={"cf_handle": "tourist", "verification_code": "toolongcode"},
        )
        assert resp.status_code == 422

    def test_verify_unauthenticated(self):
        client = _unauth_client()
        resp = client.post(
            "/cf-handle/verify",
            json={"cf_handle": "tourist", "verification_code": "abcd1234"},
        )
        assert resp.status_code == 401


# ===========================================================================
# GET /cf-handle/info/{handle}
# ===========================================================================


class TestGetCfHandleInfo:
    """Tests for GET /cf-handle/info/{handle}."""

    @patch("app.api.v1.cf_handle.cf_handle_service")
    @patch("app.api.v1.cf_handle._get_cf_service")
    def test_get_info_success(self, mock_cf_service_fn, mock_svc):
        # Public endpoint -- no auth needed
        mock_cf_service_fn.return_value = MagicMock()
        mock_svc.get_cf_handle_info = AsyncMock(
            return_value={
                "handle": "tourist",
                "rating": 3979,
                "max_rating": 3979,
                "rank": "legendary grandmaster",
                "max_rank": "legendary grandmaster",
                "avatar": "https://example.com/avatar.jpg",
            },
        )

        app = _create_app()
        # No auth override needed -- this is a public endpoint
        client = TestClient(app)
        resp = client.get("/cf-handle/info/tourist")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["handle"] == "tourist"
        assert body["data"]["rating"] == 3979
        assert body["message"] == "CF user info retrieved"

    @patch("app.api.v1.cf_handle.cf_handle_service")
    @patch("app.api.v1.cf_handle._get_cf_service")
    def test_get_info_not_found(self, mock_cf_service_fn, mock_svc):
        mock_cf_service_fn.return_value = MagicMock()
        mock_svc.get_cf_handle_info = AsyncMock(
            side_effect=NotFoundException("CF Handle not found"),
        )

        app = _create_app()
        client = TestClient(app)
        resp = client.get("/cf-handle/info/nonexistent_handle")
        assert resp.status_code == 404

    def test_get_info_missing_handle(self):
        """The handle is a path parameter; omitting it should 404 (not found route)."""
        app = _create_app()
        client = TestClient(app)
        resp = client.get("/cf-handle/info/")
        assert resp.status_code == 404

    def test_get_info_wrong_http_method(self):
        app = _create_app()
        client = TestClient(app)
        resp = client.post("/cf-handle/info/tourist")
        assert resp.status_code == 405


# ===========================================================================
# DELETE /cf-handle/unbind
# ===========================================================================


class TestUnbindCfHandle:
    """Tests for DELETE /cf-handle/unbind."""

    @patch("app.api.v1.cf_handle.cf_handle_service")
    def test_unbind_success(self, mock_svc, app_client):
        mock_svc.unbind_cf_handle = AsyncMock(
            return_value={"cf_handle": None, "cf_handle_verified": False},
        )

        resp = app_client.delete("/cf-handle/unbind")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["cf_handle"] is None
        assert body["message"] == "CF Handle unbound"

    @patch("app.api.v1.cf_handle.cf_handle_service")
    def test_unbind_no_bound_handle(self, mock_svc, app_client):
        mock_svc.unbind_cf_handle = AsyncMock(
            side_effect=NotFoundException("No CF Handle bound"),
        )

        resp = app_client.delete("/cf-handle/unbind")
        assert resp.status_code == 404

    def test_unbind_unauthenticated(self):
        client = _unauth_client()
        resp = client.delete("/cf-handle/unbind")
        assert resp.status_code == 401

    def test_unbind_wrong_http_method(self, app_client):
        resp = app_client.get("/cf-handle/unbind")
        assert resp.status_code == 405


# ===========================================================================
# Cross-cutting: response envelope
# ===========================================================================


class TestResponseEnvelope:
    """Verify that all successful responses have the standard envelope."""

    @patch("app.api.v1.cf_handle.cf_handle_service")
    @patch("app.api.v1.cf_handle._get_cf_service")
    def test_bind_envelope(self, mock_cf_service_fn, mock_svc, app_client):
        mock_cf_service_fn.return_value = MagicMock()
        mock_svc.bind_cf_handle = AsyncMock(
            return_value={"cf_handle": "test", "verification_code": "abcd1234"},
        )

        resp = app_client.post("/cf-handle/bind", json={"cf_handle": "test"})
        body = resp.json()
        assert "success" in body
        assert "data" in body
        assert "message" in body
        assert body["success"] is True

    @patch("app.api.v1.cf_handle.cf_handle_service")
    @patch("app.api.v1.cf_handle._get_cf_service")
    def test_verify_envelope(self, mock_cf_service_fn, mock_svc, app_client):
        mock_cf_service_fn.return_value = MagicMock()
        mock_svc.verify_cf_handle = AsyncMock(
            return_value={"cf_handle": "test", "cf_handle_verified": True},
        )

        resp = app_client.post(
            "/cf-handle/verify",
            json={"cf_handle": "test", "verification_code": "abcd1234"},
        )
        body = resp.json()
        assert body["success"] is True
        assert "data" in body
        assert "message" in body

    @patch("app.api.v1.cf_handle.cf_handle_service")
    @patch("app.api.v1.cf_handle._get_cf_service")
    def test_info_envelope(self, mock_cf_service_fn, mock_svc):
        mock_cf_service_fn.return_value = MagicMock()
        mock_svc.get_cf_handle_info = AsyncMock(
            return_value={"handle": "test", "rating": 1500},
        )

        app = _create_app()
        client = TestClient(app)
        resp = client.get("/cf-handle/info/test")
        body = resp.json()
        assert body["success"] is True
        assert "data" in body
        assert "message" in body

    @patch("app.api.v1.cf_handle.cf_handle_service")
    def test_unbind_envelope(self, mock_svc, app_client):
        mock_svc.unbind_cf_handle = AsyncMock(
            return_value={"cf_handle": None, "cf_handle_verified": False},
        )

        resp = app_client.delete("/cf-handle/unbind")
        body = resp.json()
        assert body["success"] is True
        assert "data" in body
        assert "message" in body
