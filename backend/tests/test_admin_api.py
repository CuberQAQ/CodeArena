"""API route tests for app/api/v1/admin.py.

Tests cover all 10 admin endpoints:
  GET  /admin/config                -- retrieve all configuration
  GET  /admin/config/metadata       -- get config structure metadata
  PUT  /admin/config/{key}          -- update a single config key
  POST /admin/config/{key}/reset    -- reset key to default
  GET  /admin/users                 -- paginated user list with search
  PUT  /admin/users/{id}/toggle-active  -- enable/disable user
  PUT  /admin/users/{id}/toggle-admin   -- grant/revoke admin
  GET  /admin/stats                 -- system statistics
  POST /admin/cf-ranking/pipeline   -- trigger CF sampling pipeline
  GET  /admin/cf-ranking/status     -- query pipeline status

All endpoints require admin privileges (is_admin=True).
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
    NotFoundException,
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


def _make_mock_admin(**overrides):
    """Create a mock admin User object."""
    user = MagicMock()
    user.id = "00000000-0000-0000-0000-000000000001"
    user.username = "admin"
    user.email = "admin@example.com"
    user.elo = 2000
    user.tokens = 500
    user.is_active = True
    user.is_admin = True
    for k, v in overrides.items():
        setattr(user, k, v)
    return user


def _make_mock_non_admin(**overrides):
    """Create a mock non-admin User object."""
    user = MagicMock()
    user.id = "00000000-0000-0000-0000-000000000002"
    user.username = "normaluser"
    user.email = "user@example.com"
    user.elo = 1400
    user.tokens = 100
    user.is_active = True
    user.is_admin = False
    for k, v in overrides.items():
        setattr(user, k, v)
    return user


@pytest.fixture()
def admin_user():
    return _make_mock_admin()


@pytest.fixture()
def admin_client(admin_user):
    """Create a TestClient with admin auth and DB dependencies overridden."""
    app = _create_app()
    app.dependency_overrides[get_current_user] = lambda: admin_user
    return TestClient(app)


@pytest.fixture()
def non_admin_user():
    return _make_mock_non_admin()


@pytest.fixture()
def non_admin_client(non_admin_user):
    """Create a TestClient with non-admin auth."""
    app = _create_app()
    app.dependency_overrides[get_current_user] = lambda: non_admin_user
    return TestClient(app)


# ===========================================================================
# GET /admin/config
# ===========================================================================


class TestGetAllConfig:
    """Tests for GET /admin/config."""

    @patch("app.api.v1.admin.admin_service")
    def test_get_all_config_success(self, mock_svc, admin_client):
        mock_svc.get_all_config = AsyncMock(
            return_value={"challenge": {"elo_k_factor": 32}},
        )
        mock_svc.require_admin = MagicMock()

        resp = admin_client.get("/admin/config")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"] == {"challenge": {"elo_k_factor": 32}}
        assert body["message"] == "Configuration retrieved"

    def test_get_all_config_non_admin_forbidden(self, non_admin_client):
        resp = non_admin_client.get("/admin/config")
        assert resp.status_code == 403

    def test_get_all_config_wrong_method(self, admin_client):
        resp = admin_client.post("/admin/config")
        assert resp.status_code == 405


# ===========================================================================
# GET /admin/config/metadata
# ===========================================================================


class TestGetConfigMetadata:
    """Tests for GET /admin/config/metadata."""

    @patch("app.api.v1.admin.admin_service")
    def test_get_config_metadata_success(self, mock_svc, admin_client):
        mock_svc.get_config_metadata = AsyncMock(
            return_value={"sections": [{"name": "challenge"}]},
        )
        mock_svc.require_admin = MagicMock()

        resp = admin_client.get("/admin/config/metadata")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert "sections" in body["data"]
        assert body["message"] == "Config metadata retrieved"

    def test_get_config_metadata_non_admin_forbidden(self, non_admin_client):
        resp = non_admin_client.get("/admin/config/metadata")
        assert resp.status_code == 403


# ===========================================================================
# PUT /admin/config/{key}
# ===========================================================================


class TestUpdateConfig:
    """Tests for PUT /admin/config/{key}."""

    @patch("app.api.v1.admin.admin_service")
    def test_update_config_success(self, mock_svc, admin_client):
        mock_svc.require_admin = MagicMock()
        mock_svc.update_config = AsyncMock(
            return_value={"key": "challenge.elo_k_factor", "value": 40},
        )

        resp = admin_client.put(
            "/admin/config/challenge.elo_k_factor",
            json={"value": 40},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["key"] == "challenge.elo_k_factor"
        assert body["data"]["value"] == 40
        assert body["message"] == "Configuration updated"

    def test_update_config_missing_body(self, admin_client):
        resp = admin_client.put("/admin/config/some.key")
        assert resp.status_code == 422

    def test_update_config_non_admin_forbidden(self, non_admin_client):
        resp = non_admin_client.put(
            "/admin/config/some.key",
            json={"value": 1},
        )
        assert resp.status_code == 403

    @patch("app.api.v1.admin.admin_service")
    def test_update_config_not_found(self, mock_svc, admin_client):
        mock_svc.require_admin = MagicMock()
        mock_svc.update_config = AsyncMock(
            side_effect=NotFoundException("Config key not found"),
        )

        resp = admin_client.put(
            "/admin/config/nonexistent.key",
            json={"value": 1},
        )
        assert resp.status_code == 404


# ===========================================================================
# POST /admin/config/{key}/reset
# ===========================================================================


class TestResetConfig:
    """Tests for POST /admin/config/{key}/reset."""

    @patch("app.api.v1.admin.admin_service")
    def test_reset_config_success(self, mock_svc, admin_client):
        mock_svc.require_admin = MagicMock()
        mock_svc.reset_config = AsyncMock(
            return_value={"key": "challenge.elo_k_factor", "value": 32},
        )

        resp = admin_client.post("/admin/config/challenge.elo_k_factor/reset")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["key"] == "challenge.elo_k_factor"
        assert body["data"]["value"] == 32
        assert body["message"] == "Configuration reset to default"

    def test_reset_config_non_admin_forbidden(self, non_admin_client):
        resp = non_admin_client.post("/admin/config/some.key/reset")
        assert resp.status_code == 403

    @patch("app.api.v1.admin.admin_service")
    def test_reset_config_not_found(self, mock_svc, admin_client):
        mock_svc.require_admin = MagicMock()
        mock_svc.reset_config = AsyncMock(
            side_effect=NotFoundException("Config key not found"),
        )

        resp = admin_client.post("/admin/config/nonexistent.key/reset")
        assert resp.status_code == 404


# ===========================================================================
# GET /admin/users
# ===========================================================================


class TestListUsers:
    """Tests for GET /admin/users."""

    @patch("app.api.v1.admin.admin_service")
    def test_list_users_default_params(self, mock_svc, admin_client):
        mock_svc.require_admin = MagicMock()
        mock_svc.list_users = AsyncMock(
            return_value={
                "items": [],
                "total": 0,
                "page": 1,
                "page_size": 20,
                "total_pages": 0,
            },
        )

        resp = admin_client.get("/admin/users")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["items"] == []
        assert body["data"]["total"] == 0
        assert body["data"]["page"] == 1
        assert body["message"] == "User list retrieved"

    @patch("app.api.v1.admin.admin_service")
    def test_list_users_with_pagination(self, mock_svc, admin_client):
        mock_svc.require_admin = MagicMock()
        mock_svc.list_users = AsyncMock(
            return_value={
                "items": [{"id": "u1", "username": "alice"}],
                "total": 50,
                "page": 2,
                "page_size": 10,
                "total_pages": 5,
            },
        )

        resp = admin_client.get("/admin/users", params={"page": 2, "page_size": 10})
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["page"] == 2
        assert body["data"]["total"] == 50
        assert len(body["data"]["items"]) == 1

    @patch("app.api.v1.admin.admin_service")
    def test_list_users_with_search(self, mock_svc, admin_client):
        mock_svc.require_admin = MagicMock()
        mock_svc.list_users = AsyncMock(
            return_value={
                "items": [{"id": "u1", "username": "alice"}],
                "total": 1,
                "page": 1,
                "page_size": 20,
                "total_pages": 1,
            },
        )

        resp = admin_client.get("/admin/users", params={"search": "alice"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["total"] == 1

    def test_list_users_page_zero_invalid(self, admin_client):
        resp = admin_client.get("/admin/users", params={"page": 0})
        assert resp.status_code == 422

    def test_list_users_page_size_over_100(self, admin_client):
        resp = admin_client.get("/admin/users", params={"page_size": 101})
        assert resp.status_code == 422

    def test_list_users_page_size_zero_invalid(self, admin_client):
        resp = admin_client.get("/admin/users", params={"page_size": 0})
        assert resp.status_code == 422

    def test_list_users_non_admin_forbidden(self, non_admin_client):
        resp = non_admin_client.get("/admin/users")
        assert resp.status_code == 403


# ===========================================================================
# PUT /admin/users/{user_id}/toggle-active
# ===========================================================================


class TestToggleUserActive:
    """Tests for PUT /admin/users/{user_id}/toggle-active."""

    @patch("app.api.v1.admin.admin_service")
    def test_toggle_active_success(self, mock_svc, admin_client):
        mock_svc.require_admin = MagicMock()
        mock_svc.toggle_user_active = AsyncMock(
            return_value={"id": "u2", "username": "bob", "is_active": False},
        )

        resp = admin_client.put(
            "/admin/users/00000000-0000-0000-0000-000000000002/toggle-active",
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["is_active"] is False
        assert body["message"] == "User active status toggled"

    def test_toggle_active_invalid_uuid(self, admin_client):
        resp = admin_client.put("/admin/users/not-a-uuid/toggle-active")
        assert resp.status_code == 422

    def test_toggle_active_non_admin_forbidden(self, non_admin_client):
        resp = non_admin_client.put(
            "/admin/users/00000000-0000-0000-0000-000000000002/toggle-active",
        )
        assert resp.status_code == 403

    @patch("app.api.v1.admin.admin_service")
    def test_toggle_active_user_not_found(self, mock_svc, admin_client):
        mock_svc.require_admin = MagicMock()
        mock_svc.toggle_user_active = AsyncMock(
            side_effect=NotFoundException("User not found"),
        )

        resp = admin_client.put(
            "/admin/users/00000000-0000-0000-0000-000000009999/toggle-active",
        )
        assert resp.status_code == 404


# ===========================================================================
# PUT /admin/users/{user_id}/toggle-admin
# ===========================================================================


class TestToggleUserAdmin:
    """Tests for PUT /admin/users/{user_id}/toggle-admin."""

    @patch("app.api.v1.admin.admin_service")
    def test_toggle_admin_success(self, mock_svc, admin_client):
        mock_svc.require_admin = MagicMock()
        mock_svc.toggle_user_admin = AsyncMock(
            return_value={"id": "u2", "username": "bob", "is_admin": True},
        )

        resp = admin_client.put(
            "/admin/users/00000000-0000-0000-0000-000000000002/toggle-admin",
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["is_admin"] is True
        assert body["message"] == "User admin status toggled"

    def test_toggle_admin_invalid_uuid(self, admin_client):
        resp = admin_client.put("/admin/users/not-a-uuid/toggle-admin")
        assert resp.status_code == 422

    def test_toggle_admin_non_admin_forbidden(self, non_admin_client):
        resp = non_admin_client.put(
            "/admin/users/00000000-0000-0000-0000-000000000002/toggle-admin",
        )
        assert resp.status_code == 403


# ===========================================================================
# GET /admin/stats
# ===========================================================================


class TestGetSystemStats:
    """Tests for GET /admin/stats."""

    @patch("app.api.v1.admin.admin_service")
    def test_get_stats_success(self, mock_svc, admin_client):
        mock_svc.require_admin = MagicMock()
        mock_svc.get_system_stats = AsyncMock(
            return_value={
                "users": {"total": 100, "active": 80},
                "challenges": {"total": 500},
                "training": {"total": 200},
                "contests": {"total": 50},
            },
        )

        resp = admin_client.get("/admin/stats")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["users"]["total"] == 100
        assert body["data"]["challenges"]["total"] == 500
        assert body["message"] == "System statistics retrieved"

    def test_get_stats_non_admin_forbidden(self, non_admin_client):
        resp = non_admin_client.get("/admin/stats")
        assert resp.status_code == 403


# ===========================================================================
# POST /admin/cf-ranking/pipeline
# ===========================================================================


class TestTriggerCfRankingPipeline:
    """Tests for POST /admin/cf-ranking/pipeline."""

    @patch("app.api.v1.admin.admin_service")
    @patch("app.services.cf_ranking_service.run_sampling_pipeline", new_callable=AsyncMock)
    def test_trigger_pipeline_success(self, mock_pipeline, mock_svc, admin_client):
        mock_svc.require_admin = MagicMock()
        mock_pipeline.return_value = {"sampled": 50, "regression_r2": 0.95}

        resp = admin_client.post("/admin/cf-ranking/pipeline")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["sampled"] == 50
        assert body["message"] == "Pipeline completed"

    @patch("app.api.v1.admin.admin_service")
    @patch("app.services.cf_ranking_service.run_sampling_pipeline", new_callable=AsyncMock)
    def test_trigger_pipeline_failure(self, mock_pipeline, mock_svc, admin_client):
        mock_svc.require_admin = MagicMock()
        mock_pipeline.return_value = {"error": "CF API rate limited"}

        resp = admin_client.post("/admin/cf-ranking/pipeline")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert "error" in body["data"]
        assert body["message"] == "Pipeline failed"

    def test_trigger_pipeline_non_admin_forbidden(self, non_admin_client):
        resp = non_admin_client.post("/admin/cf-ranking/pipeline")
        assert resp.status_code == 403


# ===========================================================================
# GET /admin/cf-ranking/status
# ===========================================================================


class TestGetCfRankingStatus:
    """Tests for GET /admin/cf-ranking/status."""

    @patch("app.api.v1.admin.admin_service")
    @patch("app.services.cf_ranking_service.get_pipeline_state")
    def test_get_status_idle(self, mock_state_fn, mock_svc, admin_client):
        mock_svc.require_admin = MagicMock()
        mock_state = MagicMock()
        mock_state.to_dict.return_value = {
            "running": False,
            "phase": "idle",
            "progress": 0,
            "total": 0,
            "batch": 0,
            "error": None,
            "coefficients": None,
        }
        mock_state_fn.return_value = mock_state

        resp = admin_client.get("/admin/cf-ranking/status")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["running"] is False
        assert body["data"]["phase"] == "idle"
        assert body["message"] == "Pipeline status retrieved"

    @patch("app.api.v1.admin.admin_service")
    @patch("app.services.cf_ranking_service.get_pipeline_state")
    def test_get_status_running(self, mock_state_fn, mock_svc, admin_client):
        mock_svc.require_admin = MagicMock()
        mock_state = MagicMock()
        mock_state.to_dict.return_value = {
            "running": True,
            "phase": "sampling",
            "progress": 25,
            "total": 100,
            "batch": 1,
            "error": None,
            "coefficients": None,
        }
        mock_state_fn.return_value = mock_state

        resp = admin_client.get("/admin/cf-ranking/status")
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["running"] is True
        assert body["data"]["progress"] == 25

    def test_get_status_non_admin_forbidden(self, non_admin_client):
        resp = non_admin_client.get("/admin/cf-ranking/status")
        assert resp.status_code == 403


# ===========================================================================
# Cross-cutting: response envelope
# ===========================================================================


class TestResponseEnvelope:
    """Verify that all successful admin responses have the standard envelope."""

    @patch("app.api.v1.admin.admin_service")
    def test_config_envelope(self, mock_svc, admin_client):
        mock_svc.require_admin = MagicMock()
        mock_svc.get_all_config = AsyncMock(return_value={})

        resp = admin_client.get("/admin/config")
        body = resp.json()
        assert "success" in body
        assert "data" in body
        assert "message" in body
        assert body["success"] is True

    @patch("app.api.v1.admin.admin_service")
    def test_stats_envelope(self, mock_svc, admin_client):
        mock_svc.require_admin = MagicMock()
        mock_svc.get_system_stats = AsyncMock(
            return_value={"users": {}, "challenges": {}, "training": {}, "contests": {}},
        )

        resp = admin_client.get("/admin/stats")
        body = resp.json()
        assert body["success"] is True
        assert "data" in body
        assert "message" in body

    @patch("app.api.v1.admin.admin_service")
    def test_users_envelope(self, mock_svc, admin_client):
        mock_svc.require_admin = MagicMock()
        mock_svc.list_users = AsyncMock(
            return_value={"items": [], "total": 0, "page": 1, "page_size": 20, "total_pages": 0},
        )

        resp = admin_client.get("/admin/users")
        body = resp.json()
        assert body["success"] is True
        assert "data" in body
        assert "message" in body
