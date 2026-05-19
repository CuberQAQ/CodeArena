"""Integration test: registration -> login -> get profile -> update profile -> token refresh.

Tests the complete authentication lifecycle through the API layer.
"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from .conftest import _TestUser, create_test_user, get_auth_headers


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def client(db_engine, db_session):
    """Provide an httpx AsyncClient wired to the test database."""
    from app.core.database import get_db
    from app.main import app
    from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

    session_factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)

    async def _override_get_db():
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            finally:
                await session.close()

    app.dependency_overrides[get_db] = _override_get_db

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as ac:
        yield ac

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


async def _register(client, username="newuser", email="new@example.com", password="TestPass123"):
    """Call POST /api/v1/auth/register."""
    return await client.post(
        "/api/v1/auth/register",
        json={"username": username, "email": email, "password": password},
    )


async def _login(client, email="new@example.com", password="TestPass123"):
    """Call POST /api/v1/auth/login."""
    return await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestRegisterLoginFlow:
    """Register -> login -> get profile -> update profile -> refresh."""

    async def test_register_returns_user_and_tokens(self, client, db_session):
        """Registration creates a user and returns JWT tokens."""
        resp = await _register(client)
        assert resp.status_code == 201

        body = resp.json()
        assert body["success"] is True

        data = body["data"]
        assert "user" in data
        assert "tokens" in data

        user_data = data["user"]
        assert user_data["username"] == "newuser"
        assert user_data["email"] == "new@example.com"
        assert user_data["elo"] == 1200
        assert user_data["pp"] == 0.0
        assert user_data["tokens"] == 0
        assert user_data["is_active"] is True
        assert user_data["is_admin"] is False

        tokens = data["tokens"]
        assert "access_token" in tokens
        assert "refresh_token" in tokens
        assert tokens["token_type"] == "bearer"

    async def test_register_duplicate_username_fails(self, client, db_session):
        """Registration with duplicate username returns 409."""
        await _register(client, username="dup_user")
        resp = await _register(client, username="dup_user", email="other@example.com")
        assert resp.status_code == 409

    async def test_register_duplicate_email_fails(self, client, db_session):
        """Registration with duplicate email returns 409."""
        await _register(client, email="dup@example.com")
        resp = await _register(client, username="other_user", email="dup@example.com")
        assert resp.status_code == 409

    async def test_register_weak_password_fails(self, client, db_session):
        """Registration with weak password returns 422."""
        resp = await _register(client, password="weak")
        assert resp.status_code == 422

    async def test_login_with_valid_credentials(self, client, db_session):
        """Login with correct credentials returns tokens."""
        await _register(client)
        resp = await _login(client)
        assert resp.status_code == 200

        body = resp.json()
        assert body["success"] is True

        tokens = body["data"]
        assert "access_token" in tokens
        assert "refresh_token" in tokens

    async def test_login_with_wrong_password_fails(self, client, db_session):
        """Login with wrong password returns 401."""
        await _register(client)
        resp = await _login(client, password="WrongPass1")
        assert resp.status_code == 401

    async def test_login_with_nonexistent_email_fails(self, client, db_session):
        """Login with non-existent email returns 401."""
        resp = await _login(client, email="nobody@example.com")
        assert resp.status_code == 401

    async def test_get_me_with_valid_token(self, client, db_session):
        """GET /auth/me returns user profile with valid token."""
        reg_resp = await _register(client)
        token = reg_resp.json()["data"]["tokens"]["access_token"]

        resp = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200

        user_data = resp.json()["data"]
        assert user_data["username"] == "newuser"
        assert user_data["email"] == "new@example.com"
        assert user_data["elo"] == 1200

    async def test_get_me_without_token_fails(self, client, db_session):
        """GET /auth/me without token returns 401."""
        resp = await client.get("/api/v1/auth/me")
        assert resp.status_code == 401

    async def test_update_profile_username(self, client, db_session):
        """PUT /auth/profile updates username."""
        reg_resp = await _register(client)
        token = reg_resp.json()["data"]["tokens"]["access_token"]

        resp = await client.put(
            "/api/v1/auth/profile",
            headers={"Authorization": f"Bearer {token}"},
            json={"username": "updated_user"},
        )
        assert resp.status_code == 200

        user_data = resp.json()["data"]
        assert user_data["username"] == "updated_user"

    async def test_update_profile_email(self, client, db_session):
        """PUT /auth/profile updates email."""
        reg_resp = await _register(client)
        token = reg_resp.json()["data"]["tokens"]["access_token"]

        resp = await client.put(
            "/api/v1/auth/profile",
            headers={"Authorization": f"Bearer {token}"},
            json={"email": "updated@example.com"},
        )
        assert resp.status_code == 200

        user_data = resp.json()["data"]
        assert user_data["email"] == "updated@example.com"

    async def test_refresh_token_returns_new_access_token(self, client, db_session):
        """POST /auth/refresh with valid refresh token returns new access token."""
        reg_resp = await _register(client)
        tokens = reg_resp.json()["data"]["tokens"]
        refresh_token = tokens["refresh_token"]

        resp = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": refresh_token},
        )
        assert resp.status_code == 200

        body = resp.json()
        assert "access_token" in body["data"]
        assert body["data"]["token_type"] == "bearer"

    async def test_refresh_with_access_token_fails(self, client, db_session):
        """POST /auth/refresh with access token (not refresh) returns 401."""
        reg_resp = await _register(client)
        access_token = reg_resp.json()["data"]["tokens"]["access_token"]

        resp = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": access_token},
        )
        assert resp.status_code == 401

    async def test_full_auth_lifecycle(self, client, db_session):
        """End-to-end: register -> login -> get profile -> update -> refresh."""
        # 1. Register
        reg_resp = await _register(client, username="lifecycle_user", email="lc@example.com")
        assert reg_resp.status_code == 201
        reg_tokens = reg_resp.json()["data"]["tokens"]

        # 2. Login (separate step)
        login_resp = await _login(client, email="lc@example.com")
        assert login_resp.status_code == 200
        login_tokens = login_resp.json()["data"]

        # 3. Get profile with access token
        me_resp = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {login_tokens['access_token']}"},
        )
        assert me_resp.status_code == 200
        assert me_resp.json()["data"]["username"] == "lifecycle_user"

        # 4. Update profile
        update_resp = await client.put(
            "/api/v1/auth/profile",
            headers={"Authorization": f"Bearer {login_tokens['access_token']}"},
            json={"username": "lifecycle_updated"},
        )
        assert update_resp.status_code == 200
        assert update_resp.json()["data"]["username"] == "lifecycle_updated"

        # 5. Refresh token
        refresh_resp = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": login_tokens["refresh_token"]},
        )
        assert refresh_resp.status_code == 200
        new_access = refresh_resp.json()["data"]["access_token"]

        # 6. Use new access token
        me_resp2 = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {new_access}"},
        )
        assert me_resp2.status_code == 200
        assert me_resp2.json()["data"]["username"] == "lifecycle_updated"

    async def test_update_profile_no_changes_fails(self, client, db_session):
        """PUT /auth/profile with no fields returns 400."""
        reg_resp = await _register(client)
        token = reg_resp.json()["data"]["tokens"]["access_token"]

        resp = await client.put(
            "/api/v1/auth/profile",
            headers={"Authorization": f"Bearer {token}"},
            json={},
        )
        assert resp.status_code == 400
