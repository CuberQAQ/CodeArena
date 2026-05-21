"""API route tests for app/api/v1/auth.py.

Tests cover all 12 auth endpoints:
  POST /auth/register
  POST /auth/login
  POST /auth/refresh
  GET  /auth/me
  PUT  /auth/profile
  POST /auth/avatar
  GET  /auth/avatar/{user_id}
  GET  /auth/elo-history
  GET  /auth/leaderboard
  GET  /auth/pp-contributions
  GET  /auth/pp-rank
  GET  /auth/settings
  PUT  /auth/settings
"""

import io
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
    ConflictException,
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
    user.created_at = datetime(2025, 1, 1, tzinfo=UTC)
    user.updated_at = datetime(2025, 6, 1, tzinfo=UTC)
    user.last_login_at = None
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
# POST /auth/register
# ===========================================================================


class TestRegister:
    """Tests for POST /auth/register."""

    @patch("app.api.v1.auth.auth_service")
    def test_register_success(self, mock_auth_svc, app_client):
        mock_user = _make_mock_user()
        mock_auth_svc.register_user = AsyncMock(return_value=mock_user)
        mock_auth_svc.generate_token_pair.return_value = {
            "access_token": "at",
            "refresh_token": "rt",
        }

        resp = app_client.post(
            "/auth/register",
            json={"username": "newuser", "email": "new@example.com", "password": "StrongPass1"},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["success"] is True
        assert "user" in body["data"]
        assert "tokens" in body["data"]
        assert body["data"]["tokens"]["access_token"] == "at"
        assert body["message"] == "Registration successful"

    def test_register_missing_fields(self, app_client):
        resp = app_client.post("/auth/register", json={})
        assert resp.status_code == 422

    def test_register_short_username(self, app_client):
        resp = app_client.post(
            "/auth/register",
            json={"username": "ab", "email": "x@x.com", "password": "StrongPass1"},
        )
        assert resp.status_code == 422

    def test_register_invalid_username_chars(self, app_client):
        resp = app_client.post(
            "/auth/register",
            json={"username": "bad user!", "email": "x@x.com", "password": "StrongPass1"},
        )
        assert resp.status_code == 422

    def test_register_password_no_uppercase(self, app_client):
        resp = app_client.post(
            "/auth/register",
            json={"username": "gooduser", "email": "x@x.com", "password": "lowercase1"},
        )
        assert resp.status_code == 422

    def test_register_password_no_lowercase(self, app_client):
        resp = app_client.post(
            "/auth/register",
            json={"username": "gooduser", "email": "x@x.com", "password": "UPPERCASE1"},
        )
        assert resp.status_code == 422

    def test_register_password_no_digit(self, app_client):
        resp = app_client.post(
            "/auth/register",
            json={"username": "gooduser", "email": "x@x.com", "password": "NoDigitPass"},
        )
        assert resp.status_code == 422

    def test_register_short_password(self, app_client):
        resp = app_client.post(
            "/auth/register",
            json={"username": "gooduser", "email": "x@x.com", "password": "Sh1"},
        )
        assert resp.status_code == 422

    def test_register_invalid_email(self, app_client):
        resp = app_client.post(
            "/auth/register",
            json={"username": "gooduser", "email": "not-an-email", "password": "StrongPass1"},
        )
        assert resp.status_code == 422

    @patch("app.api.v1.auth.auth_service")
    def test_register_duplicate_email(self, mock_auth_svc, app_client):
        mock_auth_svc.register_user = AsyncMock(
            side_effect=ConflictException("Email already registered"),
        )

        resp = app_client.post(
            "/auth/register",
            json={"username": "dup", "email": "dup@example.com", "password": "StrongPass1"},
        )
        assert resp.status_code == 409

    @patch("app.api.v1.auth.auth_service")
    def test_register_duplicate_username(self, mock_auth_svc, app_client):
        mock_auth_svc.register_user = AsyncMock(
            side_effect=ConflictException("Username already taken"),
        )

        resp = app_client.post(
            "/auth/register",
            json={"username": "dup", "email": "dup@example.com", "password": "StrongPass1"},
        )
        assert resp.status_code == 409


# ===========================================================================
# POST /auth/login
# ===========================================================================


class TestLogin:
    """Tests for POST /auth/login."""

    @patch("app.api.v1.auth.auth_service")
    def test_login_success(self, mock_auth_svc, app_client):
        mock_user = _make_mock_user()
        mock_auth_svc.authenticate_user = AsyncMock(return_value=mock_user)
        mock_auth_svc.generate_token_pair.return_value = {
            "access_token": "at",
            "refresh_token": "rt",
        }

        resp = app_client.post(
            "/auth/login",
            json={"email": "test@example.com", "password": "StrongPass1"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["access_token"] == "at"
        assert body["data"]["refresh_token"] == "rt"
        assert body["data"]["token_type"] == "bearer"
        assert body["message"] == "Login successful"

    def test_login_missing_fields(self, app_client):
        resp = app_client.post("/auth/login", json={})
        assert resp.status_code == 422

    def test_login_invalid_email_format(self, app_client):
        resp = app_client.post(
            "/auth/login",
            json={"email": "not-email", "password": "pass"},
        )
        assert resp.status_code == 422

    @patch("app.api.v1.auth.auth_service")
    def test_login_wrong_password(self, mock_auth_svc, app_client):
        mock_auth_svc.authenticate_user = AsyncMock(
            side_effect=UnauthorizedException("Invalid credentials"),
        )

        resp = app_client.post(
            "/auth/login",
            json={"email": "test@example.com", "password": "wrong"},
        )
        assert resp.status_code == 401

    def test_login_wrong_http_method(self, app_client):
        resp = app_client.get("/auth/login")
        assert resp.status_code == 405


# ===========================================================================
# POST /auth/refresh
# ===========================================================================


class TestRefresh:
    """Tests for POST /auth/refresh."""

    @patch("app.api.v1.auth.auth_service")
    def test_refresh_success(self, mock_auth_svc, app_client):
        mock_auth_svc.refresh_access_token = AsyncMock(
            return_value={"access_token": "new_at"},
        )

        resp = app_client.post(
            "/auth/refresh",
            json={"refresh_token": "valid-refresh-token"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["access_token"] == "new_at"
        assert body["data"]["token_type"] == "bearer"
        assert body["message"] == "Token refreshed"

    def test_refresh_missing_token(self, app_client):
        resp = app_client.post("/auth/refresh", json={})
        assert resp.status_code == 422

    @patch("app.api.v1.auth.auth_service")
    def test_refresh_invalid_token(self, mock_auth_svc, app_client):
        mock_auth_svc.refresh_access_token = AsyncMock(
            side_effect=UnauthorizedException("Invalid refresh token"),
        )

        resp = app_client.post(
            "/auth/refresh",
            json={"refresh_token": "bad-token"},
        )
        assert resp.status_code == 401


# ===========================================================================
# GET /auth/me
# ===========================================================================


class TestGetMe:
    """Tests for GET /auth/me."""

    def test_get_me_success(self, app_client):
        resp = app_client.get("/auth/me")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["username"] == "testuser"
        assert body["data"]["email"] == "test@example.com"
        assert body["data"]["elo"] == 1400
        assert body["message"] == "User profile retrieved"

    def test_get_me_unauthenticated(self):
        client = _unauth_client()
        resp = client.get("/auth/me")
        assert resp.status_code == 401

    def test_get_me_wrong_method(self, app_client):
        resp = app_client.post("/auth/me")
        assert resp.status_code == 405


# ===========================================================================
# PUT /auth/profile
# ===========================================================================


class TestUpdateProfile:
    """Tests for PUT /auth/profile."""

    @patch("app.api.v1.auth.auth_service")
    def test_update_profile_username(self, mock_auth_svc, app_client):
        updated = _make_mock_user(username="newname")
        mock_auth_svc.update_user_profile = AsyncMock(return_value=updated)

        resp = app_client.put("/auth/profile", json={"username": "newname"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["username"] == "newname"
        assert body["message"] == "Profile updated"

    @patch("app.api.v1.auth.auth_service")
    def test_update_profile_email(self, mock_auth_svc, app_client):
        updated = _make_mock_user(email="new@example.com")
        mock_auth_svc.update_user_profile = AsyncMock(return_value=updated)

        resp = app_client.put("/auth/profile", json={"email": "new@example.com"})
        assert resp.status_code == 200
        assert resp.json()["data"]["email"] == "new@example.com"

    def test_update_profile_invalid_username(self, app_client):
        resp = app_client.put("/auth/profile", json={"username": "bad name!"})
        assert resp.status_code == 422

    def test_update_profile_short_username(self, app_client):
        resp = app_client.put("/auth/profile", json={"username": "ab"})
        assert resp.status_code == 422

    def test_update_profile_invalid_email(self, app_client):
        resp = app_client.put("/auth/profile", json={"email": "not-email"})
        assert resp.status_code == 422

    @patch("app.api.v1.auth.auth_service")
    def test_update_profile_conflict_username(self, mock_auth_svc, app_client):
        mock_auth_svc.update_user_profile = AsyncMock(
            side_effect=ConflictException("Username already taken"),
        )

        resp = app_client.put("/auth/profile", json={"username": "taken"})
        assert resp.status_code == 409

    def test_update_profile_unauthenticated(self):
        client = _unauth_client()
        resp = client.put("/auth/profile", json={"username": "x"})
        assert resp.status_code == 401


# ===========================================================================
# POST /auth/avatar
# ===========================================================================


class TestUploadAvatar:
    """Tests for POST /auth/avatar."""

    @patch("app.api.v1.auth.avatar_service")
    def test_upload_avatar_success(self, mock_avatar_svc, app_client):
        mock_avatar_svc.upload_avatar = AsyncMock(return_value="/avatars/123.jpg")

        img_data = b"\xff\xd8\xff\xe0" + b"\x00" * 100
        resp = app_client.post(
            "/auth/avatar",
            files={"file": ("avatar.jpg", io.BytesIO(img_data), "image/jpeg")},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["avatar_path"] == "/avatars/123.jpg"
        assert body["message"] == "Avatar uploaded successfully"

    def test_upload_avatar_unauthenticated(self):
        client = _unauth_client()
        img_data = b"\x00" * 10
        resp = client.post(
            "/auth/avatar",
            files={"file": ("a.jpg", io.BytesIO(img_data), "image/jpeg")},
        )
        assert resp.status_code == 401


# ===========================================================================
# GET /auth/avatar/{user_id}
# ===========================================================================


class TestGetAvatar:
    """Tests for GET /auth/avatar/{user_id}."""

    @patch("app.api.v1.auth.avatar_service")
    def test_get_avatar_file_exists(self, mock_avatar_svc, app_client):
        import os
        import tempfile
        from pathlib import Path

        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            f.write(b"\xff\xd8\xff\xe0" + b"\x00" * 10)
            tmp_path = f.name

        mock_avatar_svc.get_avatar_path.return_value = Path(tmp_path)

        resp = app_client.get("/auth/avatar/00000000-0000-0000-0000-000000000001")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/jpeg"
        os.unlink(tmp_path)

    @patch("app.api.v1.auth.avatar_service")
    def test_get_avatar_default_svg(self, mock_avatar_svc, app_client):
        mock_avatar_svc.get_avatar_path.return_value = None
        mock_avatar_svc.generate_default_avatar = AsyncMock(
            return_value='<svg xmlns="http://www.w3.org/2000/svg"><circle r="40"/></svg>',
        )

        resp = app_client.get("/auth/avatar/00000000-0000-0000-0000-000000000001")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/svg+xml"
        assert "svg" in resp.text

    def test_get_avatar_invalid_user_id(self, app_client):
        resp = app_client.get("/auth/avatar/not-a-uuid")
        assert resp.status_code == 422


# ===========================================================================
# GET /auth/elo-history
# ===========================================================================


class TestEloHistory:
    """Tests for GET /auth/elo-history."""

    def test_elo_history_returns_list(self, app_client):
        # Mock DB returns empty result set by default
        resp = app_client.get("/auth/elo-history")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert isinstance(body["data"], list)

    def test_elo_history_unauthenticated(self):
        client = _unauth_client()
        resp = client.get("/auth/elo-history")
        assert resp.status_code == 401


# ===========================================================================
# GET /auth/leaderboard
# ===========================================================================


class TestLeaderboard:
    """Tests for GET /auth/leaderboard."""

    def test_leaderboard_returns_list(self, app_client, mock_user):
        # The mock DB execute returns a result whose fetchall() returns empty list
        # (default MagicMock behavior for unknown methods)
        resp = app_client.get("/auth/leaderboard")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert isinstance(body["data"], list)
        assert body["message"] == "Leaderboard retrieved"

    def test_leaderboard_unauthenticated(self):
        client = _unauth_client()
        resp = client.get("/auth/leaderboard")
        assert resp.status_code == 401


# ===========================================================================
# GET /auth/pp-contributions
# ===========================================================================


class TestPpContributions:
    """Tests for GET /auth/pp-contributions."""

    def test_pp_contributions_returns_list(self, app_client, mock_user):
        # Configure mock to handle result.scalars().all() chain
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        mock_result.scalars.return_value = mock_scalars

        # Override get_db to provide configured session
        app = _create_app()
        app.dependency_overrides[get_current_user] = lambda: mock_user

        async def _configured_db():
            session = MagicMock(spec=AsyncSession)
            session.execute = AsyncMock(return_value=mock_result)
            session.commit = AsyncMock()
            session.rollback = AsyncMock()
            session.close = AsyncMock()
            session.flush = AsyncMock()
            yield session

        app.dependency_overrides[get_db] = _configured_db

        client = TestClient(app)
        resp = client.get("/auth/pp-contributions")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert isinstance(body["data"], list)

    def test_pp_contributions_unauthenticated(self):
        client = _unauth_client()
        resp = client.get("/auth/pp-contributions")
        assert resp.status_code == 401


# ===========================================================================
# GET /auth/pp-rank
# ===========================================================================


class TestPpRank:
    """Tests for GET /auth/pp-rank."""

    def test_pp_rank_unranked_zero_pp(self, mock_user):
        mock_user.pp = 0

        # Configure mock to handle scalar() for total count
        mock_result = MagicMock()
        mock_result.scalar.return_value = 5  # total_users

        app = _create_app()
        app.dependency_overrides[get_current_user] = lambda: mock_user

        async def _configured_db():
            session = MagicMock(spec=AsyncSession)
            session.execute = AsyncMock(return_value=mock_result)
            session.commit = AsyncMock()
            session.rollback = AsyncMock()
            session.close = AsyncMock()
            session.flush = AsyncMock()
            yield session

        app.dependency_overrides[get_db] = _configured_db

        client = TestClient(app)
        resp = client.get("/auth/pp-rank")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["rank"] is None
        assert body["data"]["top_percent"] is None
        assert body["data"]["total_users"] == 5

    def test_pp_rank_with_pp(self, mock_user):
        mock_user.pp = 100
        mock_user.created_at = datetime(2025, 1, 1, tzinfo=UTC)

        # Configure mock results
        total_result = MagicMock()
        total_result.scalar.return_value = 10  # total_users

        higher_result = MagicMock()
        higher_result.scalar.return_value = 3  # higher_count

        call_count = 0

        async def _execute_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return total_result
            return higher_result

        app = _create_app()
        app.dependency_overrides[get_current_user] = lambda: mock_user

        async def _configured_db():
            session = MagicMock(spec=AsyncSession)
            session.execute = AsyncMock(side_effect=_execute_side_effect)
            session.commit = AsyncMock()
            session.rollback = AsyncMock()
            session.close = AsyncMock()
            session.flush = AsyncMock()
            yield session

        app.dependency_overrides[get_db] = _configured_db

        client = TestClient(app)
        resp = client.get("/auth/pp-rank")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["rank"] == 4
        assert body["data"]["total_users"] == 10
        assert body["data"]["top_percent"] == 40.0

    def test_pp_rank_unauthenticated(self):
        client = _unauth_client()
        resp = client.get("/auth/pp-rank")
        assert resp.status_code == 401


# ===========================================================================
# GET /auth/settings
# ===========================================================================


class TestGetSettings:
    """Tests for GET /auth/settings."""

    def test_settings_existing(self, mock_user):
        # Configure mock to return existing settings
        mock_result = MagicMock()
        mock_settings = MagicMock()
        mock_settings.display_mode = "medal"
        mock_settings.avatar_path = None
        mock_result.scalar_one_or_none.return_value = mock_settings

        app = _create_app()
        app.dependency_overrides[get_current_user] = lambda: mock_user

        async def _configured_db():
            session = MagicMock(spec=AsyncSession)
            session.execute = AsyncMock(return_value=mock_result)
            session.commit = AsyncMock()
            session.rollback = AsyncMock()
            session.close = AsyncMock()
            session.flush = AsyncMock()
            yield session

        app.dependency_overrides[get_db] = _configured_db

        client = TestClient(app)
        resp = client.get("/auth/settings")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["display_mode"] == "medal"
        assert body["message"] == "Settings retrieved"

    def test_settings_creates_default_when_none(self, mock_user):
        # Configure mock to return None (no existing settings)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        app = _create_app()
        app.dependency_overrides[get_current_user] = lambda: mock_user

        async def _configured_db():
            session = MagicMock(spec=AsyncSession)
            session.execute = AsyncMock(return_value=mock_result)
            session.commit = AsyncMock()
            session.rollback = AsyncMock()
            session.close = AsyncMock()
            session.flush = AsyncMock()
            session.add = MagicMock()
            yield session

        app.dependency_overrides[get_db] = _configured_db

        client = TestClient(app)
        resp = client.get("/auth/settings")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["display_mode"] == "medal"

    def test_settings_unauthenticated(self):
        client = _unauth_client()
        resp = client.get("/auth/settings")
        assert resp.status_code == 401


# ===========================================================================
# PUT /auth/settings
# ===========================================================================


class TestUpdateSettings:
    """Tests for PUT /auth/settings."""

    def test_update_settings_existing(self, mock_user):
        # Configure mock to return existing settings
        mock_result = MagicMock()
        mock_settings = MagicMock()
        mock_settings.display_mode = "medal"
        mock_settings.avatar_path = None
        mock_result.scalar_one_or_none.return_value = mock_settings

        app = _create_app()
        app.dependency_overrides[get_current_user] = lambda: mock_user

        async def _configured_db():
            session = MagicMock(spec=AsyncSession)
            session.execute = AsyncMock(return_value=mock_result)
            session.commit = AsyncMock()
            session.rollback = AsyncMock()
            session.close = AsyncMock()
            session.flush = AsyncMock()
            yield session

        app.dependency_overrides[get_db] = _configured_db

        client = TestClient(app)
        resp = client.put("/auth/settings", json={"display_mode": "cf_tier"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["message"] == "Settings updated"

    def test_update_settings_creates_when_none(self, mock_user):
        # Configure mock to return None (no existing settings)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        app = _create_app()
        app.dependency_overrides[get_current_user] = lambda: mock_user

        async def _configured_db():
            session = MagicMock(spec=AsyncSession)
            session.execute = AsyncMock(return_value=mock_result)
            session.commit = AsyncMock()
            session.rollback = AsyncMock()
            session.close = AsyncMock()
            session.flush = AsyncMock()
            session.add = MagicMock()
            yield session

        app.dependency_overrides[get_db] = _configured_db

        client = TestClient(app)
        resp = client.put("/auth/settings", json={"display_mode": "medal"})
        assert resp.status_code == 200

    def test_update_settings_invalid_display_mode(self, mock_user):
        # Configure mock to return existing settings
        mock_result = MagicMock()
        mock_settings = MagicMock()
        mock_settings.display_mode = "medal"
        mock_settings.avatar_path = None
        mock_result.scalar_one_or_none.return_value = mock_settings

        app = _create_app()
        app.dependency_overrides[get_current_user] = lambda: mock_user

        async def _configured_db():
            session = MagicMock(spec=AsyncSession)
            session.execute = AsyncMock(return_value=mock_result)
            session.commit = AsyncMock()
            session.rollback = AsyncMock()
            session.close = AsyncMock()
            session.flush = AsyncMock()
            yield session

        app.dependency_overrides[get_db] = _configured_db

        client = TestClient(app)
        resp = client.put("/auth/settings", json={"display_mode": "invalid_mode"})
        assert resp.status_code == 400

    def test_settings_unauthenticated(self):
        client = _unauth_client()
        resp = client.put("/auth/settings", json={"display_mode": "medal"})
        assert resp.status_code == 401


# ===========================================================================
# Cross-cutting: response structure
# ===========================================================================


class TestResponseStructure:
    """Verify that all successful responses have the standard envelope."""

    @patch("app.api.v1.auth.auth_service")
    def test_register_envelope(self, mock_auth_svc, app_client):
        mock_user = _make_mock_user()
        mock_auth_svc.register_user = AsyncMock(return_value=mock_user)
        mock_auth_svc.generate_token_pair.return_value = {
            "access_token": "at",
            "refresh_token": "rt",
        }

        resp = app_client.post(
            "/auth/register",
            json={"username": "testuser2", "email": "t2@example.com", "password": "StrongPass1"},
        )
        body = resp.json()
        assert "success" in body
        assert "data" in body
        assert "message" in body
        assert body["success"] is True

    @patch("app.api.v1.auth.auth_service")
    def test_login_envelope(self, mock_auth_svc, app_client):
        mock_user = _make_mock_user()
        mock_auth_svc.authenticate_user = AsyncMock(return_value=mock_user)
        mock_auth_svc.generate_token_pair.return_value = {
            "access_token": "at",
            "refresh_token": "rt",
        }

        resp = app_client.post(
            "/auth/login",
            json={"email": "test@example.com", "password": "StrongPass1"},
        )
        body = resp.json()
        assert body["success"] is True
        assert "data" in body
        assert "message" in body

    def test_me_envelope(self, app_client):
        resp = app_client.get("/auth/me")
        body = resp.json()
        assert body["success"] is True
        assert "data" in body
        assert "message" in body


# ===========================================================================
# Cross-cutting: validation error format
# ===========================================================================


class TestValidationErrorFormat:
    """Verify validation errors have the expected error envelope."""

    def test_register_validation_returns_422(self, app_client):
        resp = app_client.post("/auth/register", json={})
        assert resp.status_code == 422
        body = resp.json()
        assert body["success"] is False
        assert "error" in body

    def test_login_validation_returns_422(self, app_client):
        resp = app_client.post("/auth/login", json={})
        assert resp.status_code == 422
        body = resp.json()
        assert body["success"] is False

    def test_refresh_validation_returns_422(self, app_client):
        resp = app_client.post("/auth/refresh", json={})
        assert resp.status_code == 422
