"""API route tests for app/api/v1/medal.py.

Tests cover all 4 medal endpoints:
  GET  /medal/overall
  GET  /medal/skills
  GET  /medal/stats
  GET  /medal/user/{user_id}
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

SAMPLE_UUID = "00000000-0000-0000-0000-000000000001"
OTHER_UUID = "00000000-0000-0000-0000-000000000002"


def _make_mock_user(**overrides):
    user = MagicMock()
    user.id = SAMPLE_UUID
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


# ===========================================================================
# GET /medal/overall
# ===========================================================================


class TestGetOverallMedal:
    """Tests for GET /medal/overall."""

    @patch("app.api.v1.medal.MedalService")
    def test_overall_medal_success(self, mock_svc, app_client, mock_user):
        mock_svc.calculate_overall_medal.return_value = {
            "level": "silver",
            "name": "Silver",
            "icon": "silver_icon",
        }

        resp = app_client.get("/medal/overall")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["elo"] == 1400
        assert body["data"]["medal"]["level"] == "silver"
        assert body["message"] == "Overall medal retrieved"

    @patch("app.api.v1.medal.MedalService")
    def test_overall_medal_gold(self, mock_svc, app_client):
        mock_svc.calculate_overall_medal.return_value = {
            "level": "gold",
            "name": "Gold",
            "icon": "gold_icon",
        }

        resp = app_client.get("/medal/overall")
        assert resp.status_code == 200
        assert resp.json()["data"]["medal"]["level"] == "gold"

    @patch("app.api.v1.medal.MedalService")
    def test_overall_medal_bronze(self, mock_svc, app_client):
        mock_svc.calculate_overall_medal.return_value = {
            "level": "bronze",
            "name": "Bronze",
            "icon": "bronze_icon",
        }

        resp = app_client.get("/medal/overall")
        assert resp.status_code == 200
        assert resp.json()["data"]["medal"]["level"] == "bronze"

    def test_overall_medal_unauthenticated(self):
        client = _unauth_client()
        resp = client.get("/medal/overall")
        assert resp.status_code == 401

    def test_overall_medal_wrong_method(self, app_client):
        resp = app_client.post("/medal/overall")
        assert resp.status_code == 405

    @patch("app.api.v1.medal.MedalService")
    def test_overall_medal_uses_current_user_elo(self, mock_svc, app_client, mock_user):
        """Verify the endpoint passes the current user's elo to the service."""
        mock_svc.calculate_overall_medal.return_value = {"level": "silver", "name": "Silver"}

        app_client.get("/medal/overall")
        mock_svc.calculate_overall_medal.assert_called_once_with(mock_user.elo)


# ===========================================================================
# GET /medal/skills
# ===========================================================================


class TestGetSkillMedals:
    """Tests for GET /medal/skills."""

    @patch("app.api.v1.medal.MedalService")
    def test_skills_success(self, mock_svc, app_client):
        mock_svc.get_all_skill_medals = AsyncMock(
            return_value={
                "dp": {"level": "gold", "name": "Gold", "elo": 1500},
                "greedy": {"level": "silver", "name": "Silver", "elo": 1300},
            }
        )

        resp = app_client.get("/medal/skills")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert len(body["data"]["skills"]) == 2
        assert body["message"] == "Skill medals retrieved"

    @patch("app.api.v1.medal.MedalService")
    def test_skills_empty(self, mock_svc, app_client):
        mock_svc.get_all_skill_medals = AsyncMock(return_value={})

        resp = app_client.get("/medal/skills")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["skills"] == []

    @patch("app.api.v1.medal.MedalService")
    def test_skills_contains_tag_in_response(self, mock_svc, app_client):
        mock_svc.get_all_skill_medals = AsyncMock(
            return_value={
                "dp": {"level": "gold", "name": "Gold", "elo": 1500},
            }
        )

        resp = app_client.get("/medal/skills")
        body = resp.json()
        skill = body["data"]["skills"][0]
        assert skill["tag"] == "dp"
        assert "level" in skill
        assert "elo" in skill

    def test_skills_unauthenticated(self):
        client = _unauth_client()
        resp = client.get("/medal/skills")
        assert resp.status_code == 401

    def test_skills_wrong_method(self, app_client):
        resp = app_client.post("/medal/skills")
        assert resp.status_code == 405


# ===========================================================================
# GET /medal/stats
# ===========================================================================


class TestGetMedalStats:
    """Tests for GET /medal/stats."""

    @patch("app.api.v1.medal.MedalService")
    def test_stats_success(self, mock_svc, app_client):
        mock_svc.get_user_medal_stats = AsyncMock(
            return_value={
                "overall": {"gold": 2, "silver": 1},
                "skill": {"gold": 5, "silver": 3},
            }
        )

        resp = app_client.get("/medal/stats")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["stats"]["overall"]["gold"] == 2
        assert body["data"]["total_medals"] == 11  # 2+1+5+3
        assert body["message"] == "Medal stats retrieved"

    @patch("app.api.v1.medal.MedalService")
    def test_stats_empty(self, mock_svc, app_client):
        mock_svc.get_user_medal_stats = AsyncMock(return_value={})

        resp = app_client.get("/medal/stats")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["stats"] == {}
        assert body["data"]["total_medals"] == 0

    def test_stats_unauthenticated(self):
        client = _unauth_client()
        resp = client.get("/medal/stats")
        assert resp.status_code == 401

    def test_stats_wrong_method(self, app_client):
        resp = app_client.post("/medal/stats")
        assert resp.status_code == 405


# ===========================================================================
# GET /medal/user/{user_id}
# ===========================================================================


class TestGetPublicUserMedal:
    """Tests for GET /medal/user/{user_id}."""

    def _make_target_user(self, **overrides):
        user = MagicMock()
        user.id = OTHER_UUID
        user.username = "targetuser"
        user.elo = 1600
        for k, v in overrides.items():
            setattr(user, k, v)
        return user

    @patch("app.api.v1.medal.MedalService")
    def test_public_medal_success(self, mock_svc, app_client):
        # Mock the DB query to return a target user
        target_user = self._make_target_user()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = target_user

        # We need to patch the db.execute to return our mock
        mock_svc.calculate_overall_medal.return_value = {
            "level": "gold",
            "name": "Gold",
            "icon": "gold_icon",
        }
        mock_svc.get_user_medal_stats = AsyncMock(
            return_value={
                "overall": {"gold": 3},
            }
        )

        # Need to override the db to return the target user
        target_user = self._make_target_user()
        mock_session = MagicMock(spec=AsyncSession)
        mock_scalar = MagicMock()
        mock_scalar.scalar_one_or_none.return_value = target_user
        mock_session.execute = AsyncMock(return_value=mock_scalar)

        async def _mock_db_with_target():
            yield mock_session

        app = _create_app()
        app.dependency_overrides[get_db] = _mock_db_with_target
        app.dependency_overrides[get_current_user] = lambda: _make_mock_user()
        client = TestClient(app)

        resp = client.get(f"/medal/user/{OTHER_UUID}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["user_id"] == OTHER_UUID
        assert body["data"]["username"] == "targetuser"
        assert body["data"]["overall_medal"]["level"] == "gold"
        assert body["data"]["total_medals"] == 3
        assert body["message"] == "User medal info retrieved"

    def test_public_medal_invalid_user_id(self, app_client):
        resp = app_client.get("/medal/user/not-a-uuid")
        assert resp.status_code == 404

    @patch("app.api.v1.medal.MedalService")
    def test_public_medal_user_not_found(self, mock_svc, app_client):
        mock_session = MagicMock(spec=AsyncSession)
        mock_scalar = MagicMock()
        mock_scalar.scalar_one_or_none.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_scalar)

        async def _mock_db_with_no_user():
            yield mock_session

        app = _create_app()
        app.dependency_overrides[get_db] = _mock_db_with_no_user
        app.dependency_overrides[get_current_user] = lambda: _make_mock_user()
        client = TestClient(app)

        resp = client.get(f"/medal/user/{OTHER_UUID}")
        assert resp.status_code == 404

    def test_public_medal_unauthenticated(self):
        client = _unauth_client()
        resp = client.get(f"/medal/user/{OTHER_UUID}")
        assert resp.status_code == 401


# ===========================================================================
# Cross-cutting: response envelope
# ===========================================================================


class TestMedalResponseEnvelope:
    """Verify all successful medal responses have standard envelope."""

    @patch("app.api.v1.medal.MedalService")
    def test_overall_envelope(self, mock_svc, app_client):
        mock_svc.calculate_overall_medal.return_value = {"level": "silver"}

        resp = app_client.get("/medal/overall")
        body = resp.json()
        assert "success" in body
        assert "data" in body
        assert "message" in body
        assert body["success"] is True

    @patch("app.api.v1.medal.MedalService")
    def test_skills_envelope(self, mock_svc, app_client):
        mock_svc.get_all_skill_medals = AsyncMock(return_value={})

        resp = app_client.get("/medal/skills")
        body = resp.json()
        assert "success" in body
        assert "data" in body
        assert "message" in body
        assert body["success"] is True

    @patch("app.api.v1.medal.MedalService")
    def test_stats_envelope(self, mock_svc, app_client):
        mock_svc.get_user_medal_stats = AsyncMock(return_value={})

        resp = app_client.get("/medal/stats")
        body = resp.json()
        assert "success" in body
        assert "data" in body
        assert "message" in body
        assert body["success"] is True
