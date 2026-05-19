"""Tests for the admin service and API routes.

Validates:
  - Permission enforcement (non-admin blocked)
  - System statistics aggregation
  - User list with pagination and search
  - User active/admin toggle
  - Configuration CRUD (get all, update, reset)
  - Configuration metadata retrieval

Uses lightweight SQLite-compatible test models following the established
patching pattern.
"""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import Boolean, DateTime, Float, Integer, String, event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core.exceptions import ForbiddenException, NotFoundException
from app.services import admin_service as admin_svc_module
from app.services.admin_service import (
    get_config_metadata,
    get_system_stats,
    list_users,
    require_admin,
    reset_config,
    toggle_user_active,
    toggle_user_admin,
    update_config,
)

# ---------------------------------------------------------------------------
# Lightweight SQLite-compatible test models
# ---------------------------------------------------------------------------


class _TestBase(DeclarativeBase):
    pass


class _TestUser(_TestBase):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(String(50), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    elo: Mapped[int] = mapped_column(Integer, default=1200, nullable=False)
    pp: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class _TestChallengeSession(_TestBase):
    __tablename__ = "challenge_sessions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)


class _TestTrainingSession(_TestBase):
    __tablename__ = "training_sessions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)


class _TestContestSession(_TestBase):
    __tablename__ = "contest_sessions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def async_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)

    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as conn:
        await conn.run_sync(_TestBase.metadata.create_all)

    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(_TestBase.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
async def db(async_engine):
    """Provide an async session with patched model references."""
    session_factory = async_sessionmaker(
        async_engine, class_=AsyncSession, expire_on_commit=False
    )

    async with session_factory() as session:
        with (
            patch.object(admin_svc_module, "User", _TestUser),
            patch.object(admin_svc_module, "ChallengeSession", _TestChallengeSession),
            patch.object(admin_svc_module, "TrainingSession", _TestTrainingSession),
            patch.object(admin_svc_module, "ContestSession", _TestContestSession),
        ):
            yield session


def _make_user(
    user_id: uuid.UUID | None = None,
    username: str = "testuser",
    email: str | None = None,
    is_active: bool = True,
    is_admin: bool = False,
    elo: int = 1200,
    pp: float = 0.0,
    tokens: int = 0,
) -> _TestUser:
    """Create a test user instance (not yet added to session)."""
    return _TestUser(
        id=user_id or uuid.uuid4(),
        username=username,
        email=email or f"{username}@test.com",
        password_hash="$2b$12$fakehash",
        is_active=is_active,
        is_admin=is_admin,
        elo=elo,
        pp=pp,
        tokens=tokens,
        created_at=datetime.now(UTC),
    )


# ---------------------------------------------------------------------------
# 1. Permission checks
# ---------------------------------------------------------------------------


class TestRequireAdmin:
    def test_admin_user_passes(self):
        user = _make_user(is_admin=True)
        require_admin(user)  # should not raise

    def test_non_admin_raises_forbidden(self):
        user = _make_user(is_admin=False)
        with pytest.raises(ForbiddenException, match="Admin access required"):
            require_admin(user)

    def test_default_user_is_not_admin(self):
        user = _make_user()
        assert user.is_admin is False
        with pytest.raises(ForbiddenException):
            require_admin(user)


# ---------------------------------------------------------------------------
# 2. System statistics
# ---------------------------------------------------------------------------


class TestGetSystemStats:
    @pytest.mark.asyncio
    async def test_empty_database(self, db):
        stats = await get_system_stats(db)
        assert stats["users"]["total"] == 0
        assert stats["users"]["active"] == 0
        assert stats["challenges"]["total"] == 0
        assert stats["training"]["total_sessions"] == 0
        assert stats["contests"]["total"] == 0

    @pytest.mark.asyncio
    async def test_with_users(self, db):
        db.add(_make_user(username="u1", is_active=True))
        db.add(_make_user(username="u2", is_active=True))
        db.add(_make_user(username="u3", is_active=False))
        await db.commit()

        stats = await get_system_stats(db)
        assert stats["users"]["total"] == 3
        assert stats["users"]["active"] == 2

    @pytest.mark.asyncio
    async def test_with_challenge_sessions(self, db):
        db.add(_TestChallengeSession(status="active"))
        db.add(_TestChallengeSession(status="completed"))
        await db.commit()

        stats = await get_system_stats(db)
        assert stats["challenges"]["total"] == 2
        assert stats["challenges"]["active"] == 1

    @pytest.mark.asyncio
    async def test_with_training_sessions(self, db):
        db.add(_TestTrainingSession(status="active"))
        db.add(_TestTrainingSession(status="completed"))
        db.add(_TestTrainingSession(status="abandoned"))
        await db.commit()

        stats = await get_system_stats(db)
        assert stats["training"]["total_sessions"] == 3
        assert stats["training"]["active_sessions"] == 1

    @pytest.mark.asyncio
    async def test_with_contest_sessions(self, db):
        db.add(_TestContestSession(status="active"))
        db.add(_TestContestSession(status="completed"))
        await db.commit()

        stats = await get_system_stats(db)
        assert stats["contests"]["total"] == 2
        assert stats["contests"]["active"] == 1


# ---------------------------------------------------------------------------
# 3. User list with pagination and search
# ---------------------------------------------------------------------------


class TestListUsers:
    @pytest.mark.asyncio
    async def test_empty_list(self, db):
        result = await list_users(db)
        assert result["items"] == []
        assert result["total"] == 0
        assert result["total_pages"] == 1  # min 1

    @pytest.mark.asyncio
    async def test_basic_pagination(self, db):
        for i in range(25):
            db.add(_make_user(username=f"user_{i:03d}"))
        await db.commit()

        # Page 1
        result = await list_users(db, page=1, page_size=10)
        assert len(result["items"]) == 10
        assert result["total"] == 25
        assert result["total_pages"] == 3
        assert result["page"] == 1

        # Page 3
        result = await list_users(db, page=3, page_size=10)
        assert len(result["items"]) == 5
        assert result["page"] == 3

    @pytest.mark.asyncio
    async def test_search_by_username(self, db):
        db.add(_make_user(username="alice"))
        db.add(_make_user(username="bob"))
        db.add(_make_user(username="charlie"))
        await db.commit()

        result = await list_users(db, search="ali")
        assert result["total"] == 1
        assert result["items"][0]["username"] == "alice"

    @pytest.mark.asyncio
    async def test_search_by_email(self, db):
        db.add(_make_user(username="alice", email="alice@example.com"))
        db.add(_make_user(username="bob", email="bob@test.com"))
        await db.commit()

        result = await list_users(db, search="example")
        assert result["total"] == 1
        assert result["items"][0]["username"] == "alice"

    @pytest.mark.asyncio
    async def test_search_case_insensitive(self, db):
        db.add(_make_user(username="Alice"))
        db.add(_make_user(username="alice_smith"))
        await db.commit()

        result = await list_users(db, search="ALICE")
        assert result["total"] == 2

    @pytest.mark.asyncio
    async def test_search_no_match(self, db):
        db.add(_make_user(username="alice"))
        await db.commit()

        result = await list_users(db, search="xyz")
        assert result["total"] == 0
        assert result["items"] == []

    @pytest.mark.asyncio
    async def test_user_item_fields(self, db):
        user_id = uuid.uuid4()
        db.add(
            _make_user(
                user_id=user_id,
                username="alice",
                email="alice@test.com",
                elo=1500,
                pp=42.5,
                tokens=100,
                is_active=True,
                is_admin=False,
            )
        )
        await db.commit()

        result = await list_users(db)
        item = result["items"][0]
        assert item["id"] == str(user_id)
        assert item["username"] == "alice"
        assert item["email"] == "alice@test.com"
        assert item["elo"] == 1500
        assert item["pp"] == 42.5
        assert item["tokens"] == 100
        assert item["is_active"] is True
        assert item["is_admin"] is False


# ---------------------------------------------------------------------------
# 4. Toggle user active
# ---------------------------------------------------------------------------


class TestToggleUserActive:
    @pytest.mark.asyncio
    async def test_toggle_active_to_inactive(self, db):
        user = _make_user(username="alice", is_active=True)
        db.add(user)
        await db.commit()

        result = await toggle_user_active(db, user.id)
        assert result["is_active"] is False
        assert result["username"] == "alice"

    @pytest.mark.asyncio
    async def test_toggle_inactive_to_active(self, db):
        user = _make_user(username="bob", is_active=False)
        db.add(user)
        await db.commit()

        result = await toggle_user_active(db, user.id)
        assert result["is_active"] is True

    @pytest.mark.asyncio
    async def test_toggle_nonexistent_user_raises(self, db):
        with pytest.raises(NotFoundException, match="User not found"):
            await toggle_user_active(db, uuid.uuid4())


# ---------------------------------------------------------------------------
# 5. Toggle user admin
# ---------------------------------------------------------------------------


class TestToggleUserAdmin:
    @pytest.mark.asyncio
    async def test_grant_admin(self, db):
        user = _make_user(username="alice", is_admin=False)
        db.add(user)
        await db.commit()

        result = await toggle_user_admin(db, user.id)
        assert result["is_admin"] is True

    @pytest.mark.asyncio
    async def test_revoke_admin(self, db):
        user = _make_user(username="bob", is_admin=True)
        db.add(user)
        await db.commit()

        result = await toggle_user_admin(db, user.id)
        assert result["is_admin"] is False

    @pytest.mark.asyncio
    async def test_toggle_admin_nonexistent_raises(self, db):
        with pytest.raises(NotFoundException, match="User not found"):
            await toggle_user_admin(db, uuid.uuid4())


# ---------------------------------------------------------------------------
# 6. Configuration management (delegates to ConfigService)
# ---------------------------------------------------------------------------


class TestConfigManagement:
    @pytest.mark.asyncio
    async def test_update_config_delegates(self, db):
        """Verify update_config calls ConfigService.set_config."""
        admin_id = uuid.uuid4()
        with patch.object(
            admin_svc_module.ConfigService,
            "set_config",
            new_callable=AsyncMock,
        ) as mock_set:
            result = await update_config(db, "elo.k_factor", 40, admin_id)
            mock_set.assert_awaited_once_with(db, "elo.k_factor", 40, admin_id)
            assert result["key"] == "elo.k_factor"
            assert result["value"] == 40

    @pytest.mark.asyncio
    async def test_reset_config_delegates(self, db):
        """Verify reset_config calls ConfigService.reset_config."""
        admin_id = uuid.uuid4()
        with patch.object(
            admin_svc_module.ConfigService,
            "reset_config",
            new_callable=AsyncMock,
            return_value=32,
        ) as mock_reset:
            result = await reset_config(db, "elo.k_factor", admin_id)
            mock_reset.assert_awaited_once_with(db, "elo.k_factor", admin_id)
            assert result["key"] == "elo.k_factor"
            assert result["value"] == 32

    @pytest.mark.asyncio
    async def test_get_all_config_delegates(self, db):
        """Verify get_all_config calls ConfigService.get_all_config."""
        expected = {"elo": {"initial_elo": 1200}}
        with patch.object(
            admin_svc_module.ConfigService,
            "get_all_config",
            new_callable=AsyncMock,
            return_value=expected,
        ) as mock_get:
            result = await admin_svc_module.get_all_config(db)
            mock_get.assert_awaited_once_with(db)
            assert result == expected


# ---------------------------------------------------------------------------
# 7. Config metadata
# ---------------------------------------------------------------------------


class TestConfigMetadata:
    @pytest.mark.asyncio
    async def test_metadata_structure(self):
        metadata = await get_config_metadata()
        assert isinstance(metadata, list)
        assert len(metadata) > 0

        # Each section should have key, label, fields
        for section in metadata:
            assert "key" in section
            assert "label" in section
            assert "fields" in section
            assert isinstance(section["fields"], list)

            for field in section["fields"]:
                assert "key" in field
                assert "label" in field
                assert "type" in field
                assert "default" in field

    @pytest.mark.asyncio
    async def test_metadata_contains_elo_section(self):
        metadata = await get_config_metadata()
        elo_section = next((s for s in metadata if s["key"] == "elo"), None)
        assert elo_section is not None
        assert elo_section["label"] == "ELO"

        field_keys = [f["key"] for f in elo_section["fields"]]
        assert "elo.initial_elo" in field_keys
        assert "elo.k_factor" in field_keys

    @pytest.mark.asyncio
    async def test_metadata_contains_economy_section(self):
        metadata = await get_config_metadata()
        economy_section = next((s for s in metadata if s["key"] == "economy"), None)
        assert economy_section is not None

        field_keys = [f["key"] for f in economy_section["fields"]]
        assert "economy.daily_token_cap" in field_keys

    @pytest.mark.asyncio
    async def test_metadata_field_types(self):
        metadata = await get_config_metadata()
        elo_section = next(s for s in metadata if s["key"] == "elo")

        initial_elo_field = next(
            f for f in elo_section["fields"] if f["key"] == "elo.initial_elo"
        )
        assert initial_elo_field["type"] == "int"
        assert initial_elo_field["default"] == 1200


# ---------------------------------------------------------------------------
# 8. Pagination edge cases
# ---------------------------------------------------------------------------


class TestPaginationEdgeCases:
    @pytest.mark.asyncio
    async def test_page_beyond_results(self, db):
        db.add(_make_user(username="u1"))
        await db.commit()

        result = await list_users(db, page=10, page_size=10)
        assert result["items"] == []
        assert result["total"] == 1
        assert result["total_pages"] == 1

    @pytest.mark.asyncio
    async def test_single_page(self, db):
        db.add(_make_user(username="u1"))
        db.add(_make_user(username="u2"))
        await db.commit()

        result = await list_users(db, page=1, page_size=100)
        assert len(result["items"]) == 2
        assert result["total_pages"] == 1

    @pytest.mark.asyncio
    async def test_exact_page_boundary(self, db):
        for i in range(20):
            db.add(_make_user(username=f"user_{i:03d}"))
        await db.commit()

        result = await list_users(db, page=1, page_size=20)
        assert len(result["items"]) == 20
        assert result["total_pages"] == 1

        result2 = await list_users(db, page=2, page_size=20)
        assert len(result2["items"]) == 0
