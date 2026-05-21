"""API route tests for app/api/v1/economy.py.

Tests cover all 3 economy endpoints:
  GET /economy/balance        -- current token balance and daily cap status
  GET /economy/transactions   -- paginated transaction history
  GET /economy/daily-status   -- detailed daily earning breakdown
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
from app.core.exceptions import UnauthorizedException, register_exception_handlers
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


# ===========================================================================
# GET /economy/balance
# ===========================================================================


class TestGetBalance:
    """Tests for GET /economy/balance."""

    @patch("app.api.v1.economy.economy_service")
    def test_balance_success(self, mock_svc, app_client):
        mock_svc.get_balance = AsyncMock(
            return_value={
                "tokens": 100,
                "daily_tokens_earned": 30,
                "daily_cap": 120,
                "daily_remaining": 90,
            }
        )

        resp = app_client.get("/economy/balance")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["tokens"] == 100
        assert body["data"]["daily_tokens_earned"] == 30
        assert body["data"]["daily_cap"] == 120
        assert body["data"]["daily_remaining"] == 90
        assert body["message"] == "Balance retrieved"

    @patch("app.api.v1.economy.economy_service")
    def test_balance_zero_tokens(self, mock_svc, app_client):
        mock_svc.get_balance = AsyncMock(
            return_value={
                "tokens": 0,
                "daily_tokens_earned": 0,
                "daily_cap": 120,
                "daily_remaining": 120,
            }
        )

        resp = app_client.get("/economy/balance")
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["tokens"] == 0

    @patch("app.api.v1.economy.economy_service")
    def test_balance_daily_cap_reached(self, mock_svc, app_client):
        mock_svc.get_balance = AsyncMock(
            return_value={
                "tokens": 500,
                "daily_tokens_earned": 120,
                "daily_cap": 120,
                "daily_remaining": 0,
            }
        )

        resp = app_client.get("/economy/balance")
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["daily_remaining"] == 0

    def test_balance_unauthenticated(self):
        client = _unauth_client()
        resp = client.get("/economy/balance")
        assert resp.status_code == 401

    def test_balance_wrong_http_method(self, app_client):
        resp = app_client.post("/economy/balance")
        assert resp.status_code == 405


# ===========================================================================
# GET /economy/transactions
# ===========================================================================


class TestGetTransactions:
    """Tests for GET /economy/transactions."""

    @patch("app.api.v1.economy.economy_service")
    def test_transactions_default_params(self, mock_svc, app_client):
        mock_svc.get_transactions = AsyncMock(return_value=([], 0))

        resp = app_client.get("/economy/transactions")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["items"] == []
        assert body["data"]["total"] == 0
        assert body["data"]["limit"] == 20
        assert body["data"]["offset"] == 0
        assert body["message"] == "Transactions retrieved"

    @patch("app.api.v1.economy.economy_service")
    def test_transactions_with_items(self, mock_svc, app_client):
        items = [
            {
                "id": "00000000-0000-0000-0000-000000000001",
                "amount": 10,
                "type": "challenge_reward",
                "reference_type": "challenge",
                "reference_id": "00000000-0000-0000-0000-000000000002",
                "balance_after": 110,
                "created_at": datetime(2026, 5, 22, 10, 0, 0, tzinfo=UTC).isoformat(),
            },
        ]
        mock_svc.get_transactions = AsyncMock(return_value=(items, 1))

        resp = app_client.get("/economy/transactions")
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["total"] == 1
        assert len(body["data"]["items"]) == 1

    @patch("app.api.v1.economy.economy_service")
    def test_transactions_with_pagination(self, mock_svc, app_client):
        mock_svc.get_transactions = AsyncMock(return_value=([], 100))

        resp = app_client.get("/economy/transactions", params={"limit": 50, "offset": 50})
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["limit"] == 50
        assert body["data"]["offset"] == 50
        assert body["data"]["total"] == 100

    def test_transactions_invalid_limit_too_high(self, app_client):
        resp = app_client.get("/economy/transactions", params={"limit": 101})
        assert resp.status_code == 422

    def test_transactions_invalid_limit_zero(self, app_client):
        resp = app_client.get("/economy/transactions", params={"limit": 0})
        assert resp.status_code == 422

    def test_transactions_invalid_offset_negative(self, app_client):
        resp = app_client.get("/economy/transactions", params={"offset": -1})
        assert resp.status_code == 422

    def test_transactions_unauthenticated(self):
        client = _unauth_client()
        resp = client.get("/economy/transactions")
        assert resp.status_code == 401

    def test_transactions_wrong_http_method(self, app_client):
        resp = app_client.post("/economy/transactions")
        assert resp.status_code == 405


# ===========================================================================
# GET /economy/daily-status
# ===========================================================================


class TestGetDailyStatus:
    """Tests for GET /economy/daily-status."""

    @patch("app.api.v1.economy.economy_service")
    def test_daily_status_success(self, mock_svc, app_client):
        mock_svc.get_daily_status = AsyncMock(
            return_value={
                "date": "2026-05-22",
                "daily_tokens_earned": 50,
                "daily_cap": 120,
                "daily_remaining": 70,
                "breakdown": {"challenge_reward": 30, "checkin": 10, "training_reward": 10},
            }
        )

        resp = app_client.get("/economy/daily-status")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["date"] == "2026-05-22"
        assert body["data"]["daily_tokens_earned"] == 50
        assert body["data"]["daily_cap"] == 120
        assert body["data"]["daily_remaining"] == 70
        assert body["data"]["breakdown"]["challenge_reward"] == 30
        assert body["message"] == "Daily status retrieved"

    @patch("app.api.v1.economy.economy_service")
    def test_daily_status_empty_day(self, mock_svc, app_client):
        mock_svc.get_daily_status = AsyncMock(
            return_value={
                "date": "2026-05-22",
                "daily_tokens_earned": 0,
                "daily_cap": 120,
                "daily_remaining": 120,
                "breakdown": {},
            }
        )

        resp = app_client.get("/economy/daily-status")
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["daily_tokens_earned"] == 0
        assert body["data"]["breakdown"] == {}

    @patch("app.api.v1.economy.economy_service")
    def test_daily_status_cap_reached(self, mock_svc, app_client):
        mock_svc.get_daily_status = AsyncMock(
            return_value={
                "date": "2026-05-22",
                "daily_tokens_earned": 120,
                "daily_cap": 120,
                "daily_remaining": 0,
                "breakdown": {"challenge_reward": 120},
            }
        )

        resp = app_client.get("/economy/daily-status")
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["daily_remaining"] == 0

    def test_daily_status_unauthenticated(self):
        client = _unauth_client()
        resp = client.get("/economy/daily-status")
        assert resp.status_code == 401

    def test_daily_status_wrong_http_method(self, app_client):
        resp = app_client.post("/economy/daily-status")
        assert resp.status_code == 405


# ===========================================================================
# Cross-cutting: response envelope
# ===========================================================================


class TestResponseEnvelope:
    """Verify that all successful responses have the standard envelope."""

    @patch("app.api.v1.economy.economy_service")
    def test_balance_envelope(self, mock_svc, app_client):
        mock_svc.get_balance = AsyncMock(
            return_value={
                "tokens": 100,
                "daily_tokens_earned": 0,
                "daily_cap": 120,
                "daily_remaining": 120,
            }
        )

        resp = app_client.get("/economy/balance")
        body = resp.json()
        assert "success" in body
        assert "data" in body
        assert "message" in body
        assert body["success"] is True

    @patch("app.api.v1.economy.economy_service")
    def test_transactions_envelope(self, mock_svc, app_client):
        mock_svc.get_transactions = AsyncMock(return_value=([], 0))

        resp = app_client.get("/economy/transactions")
        body = resp.json()
        assert "success" in body
        assert "data" in body
        assert "message" in body
        assert body["success"] is True

    @patch("app.api.v1.economy.economy_service")
    def test_daily_status_envelope(self, mock_svc, app_client):
        mock_svc.get_daily_status = AsyncMock(
            return_value={
                "date": "2026-05-22",
                "daily_tokens_earned": 0,
                "daily_cap": 120,
                "daily_remaining": 120,
                "breakdown": {},
            }
        )

        resp = app_client.get("/economy/daily-status")
        body = resp.json()
        assert "success" in body
        assert "data" in body
        assert "message" in body
        assert body["success"] is True
