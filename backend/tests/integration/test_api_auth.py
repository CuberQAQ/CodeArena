"""Integration tests: HTTP-level API authentication endpoints.

Tests the auth API through the full FastAPI stack with real PostgreSQL.
"""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def client(db_engine, db_session):
    """Provide an httpx AsyncClient wired to the test database."""
    from app.core.database import get_db
    from app.main import app

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
# Tests
# ---------------------------------------------------------------------------


class TestAuthRegister:
    """POST /api/v1/auth/register endpoint tests."""

    async def test_register_success_returns_user_and_tokens(self, client, db_session):
        """Registration with valid data returns 201 + user + tokens."""
        resp = await client.post(
            "/api/v1/auth/register",
            json={
                "username": "newuser",
                "email": "new@example.com",
                "password": "TestPass123",
            },
        )
        assert resp.status_code == 201

        body = resp.json()
        assert body["success"] is True
        data = body["data"]

        # User info
        assert data["user"]["username"] == "newuser"
        assert data["user"]["email"] == "new@example.com"
        assert data["user"]["elo"] == 1200
        assert data["user"]["is_active"] is True

        # Tokens
        assert "access_token" in data["tokens"]
        assert "refresh_token" in data["tokens"]
        assert data["tokens"]["token_type"] == "bearer"

    async def test_register_duplicate_email_returns_error(self, client, db_session):
        """Registration with duplicate email returns an error status."""
        payload = {
            "username": "first_user",
            "email": "dup@example.com",
            "password": "TestPass123",
        }
        # First registration succeeds
        resp1 = await client.post("/api/v1/auth/register", json=payload)
        assert resp1.status_code == 201

        # Second with same email but different username
        resp2 = await client.post(
            "/api/v1/auth/register",
            json={
                "username": "second_user",
                "email": "dup@example.com",
                "password": "TestPass123",
            },
        )
        assert resp2.status_code == 409


class TestAuthLogin:
    """POST /api/v1/auth/login endpoint tests."""

    async def test_login_success(self, client, db_session):
        """Login with correct credentials returns 200 + tokens."""
        # Register first
        await client.post(
            "/api/v1/auth/register",
            json={
                "username": "loginuser",
                "email": "login@example.com",
                "password": "TestPass123",
            },
        )

        # Login
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": "login@example.com", "password": "TestPass123"},
        )
        assert resp.status_code == 200

        body = resp.json()
        assert body["success"] is True
        assert "access_token" in body["data"]
        assert "refresh_token" in body["data"]

    async def test_login_wrong_password_returns_401(self, client, db_session):
        """Login with wrong password returns 401."""
        # Register first
        await client.post(
            "/api/v1/auth/register",
            json={
                "username": "wrongpwuser",
                "email": "wrongpw@example.com",
                "password": "TestPass123",
            },
        )

        # Login with wrong password
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": "wrongpw@example.com", "password": "WrongPass999"},
        )
        assert resp.status_code == 401


class TestAuthMe:
    """GET /api/v1/auth/me endpoint tests."""

    async def test_me_with_token_returns_profile(self, client, db_session):
        """GET /auth/me with valid token returns user profile."""
        # Register and get token
        reg_resp = await client.post(
            "/api/v1/auth/register",
            json={
                "username": "meuser",
                "email": "me@example.com",
                "password": "TestPass123",
            },
        )
        token = reg_resp.json()["data"]["tokens"]["access_token"]

        resp = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200

        body = resp.json()
        assert body["success"] is True
        assert body["data"]["username"] == "meuser"
        assert body["data"]["email"] == "me@example.com"

    async def test_me_without_token_returns_401(self, client, db_session):
        """GET /auth/me without token returns 401."""
        resp = await client.get("/api/v1/auth/me")
        assert resp.status_code == 401
