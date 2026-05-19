"""Tests for the M-Elo (Multi-Elo) service.

Uses lightweight SQLite-compatible test models and mocks for external services.
The key technique is patching the production model references in melo_service
with test-compatible models so SQLAlchemy queries target the SQLite tables.
"""

import uuid
from datetime import datetime
from unittest.mock import patch

import pytest
from sqlalchemy import DateTime, Integer, String, UniqueConstraint, event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.services import melo_service as melo_svc_module
from app.services.melo_service import MEloService

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
    tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class _TestUserTagElo(_TestBase):
    __tablename__ = "user_tag_elo"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    tag: Mapped[str] = mapped_column(String(100), nullable=False)
    elo: Mapped[int] = mapped_column(Integer, default=1200, nullable=False)
    total_submissions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    first_ac_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        UniqueConstraint("user_id", "tag", name="uq_user_tag_elo_user_tag"),
    )


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
    session_factory = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as session:
        with (
            patch.object(melo_svc_module, "UserTagElo", _TestUserTagElo),
            patch.object(melo_svc_module, "User", _TestUser),
        ):
            yield session


def _make_user(**kwargs) -> _TestUser:
    """Create a test user with sensible defaults."""
    defaults = {
        "username": f"user_{uuid.uuid4().hex[:8]}",
        "email": f"{uuid.uuid4().hex[:8]}@test.com",
        "password_hash": "hash",
        "elo": 1200,
        "tokens": 100,
    }
    defaults.update(kwargs)
    return _TestUser(**defaults)


# ===========================================================================
# Test: get_or_create_melo
# ===========================================================================


class TestGetOrCreateMElo:
    """Verify M-Elo creation and retrieval."""

    @pytest.mark.asyncio
    async def test_create_new_melo_inherits_global_elo(self, db):
        """New M-Elo record inherits the user's current Global Elo."""
        user = _make_user(elo=1500)
        db.add(user)
        await db.flush()

        melo = await MEloService.get_or_create_melo(db, user.id, "dp")

        assert melo.elo == 1500
        assert melo.tag == "dp"
        assert melo.total_submissions == 0
        assert melo.first_ac_at is None

    @pytest.mark.asyncio
    async def test_create_new_melo_with_default_elo(self, db):
        """New user with default Elo (1200) creates M-Elo at 1200."""
        user = _make_user()
        db.add(user)
        await db.flush()

        melo = await MEloService.get_or_create_melo(db, user.id, "graphs")

        assert melo.elo == 1200

    @pytest.mark.asyncio
    async def test_get_existing_melo(self, db):
        """Getting an existing M-Elo returns the same record."""
        user = _make_user(elo=1400)
        db.add(user)
        await db.flush()

        melo1 = await MEloService.get_or_create_melo(db, user.id, "dp")
        melo1.elo = 1600
        await db.flush()

        melo2 = await MEloService.get_or_create_melo(db, user.id, "dp")

        assert melo2.elo == 1600
        assert melo2.id == melo1.id

    @pytest.mark.asyncio
    async def test_different_tags_create_separate_records(self, db):
        """Different tags create separate M-Elo records."""
        user = _make_user(elo=1300)
        db.add(user)
        await db.flush()

        melo_dp = await MEloService.get_or_create_melo(db, user.id, "dp")
        melo_graph = await MEloService.get_or_create_melo(db, user.id, "graphs")

        assert melo_dp.id != melo_graph.id
        assert melo_dp.tag == "dp"
        assert melo_graph.tag == "graphs"
        assert melo_dp.elo == 1300
        assert melo_graph.elo == 1300

    @pytest.mark.asyncio
    async def test_nonexistent_user_raises(self, db):
        """Creating M-Elo for a nonexistent user raises ValueError."""
        fake_id = uuid.uuid4()

        with pytest.raises(ValueError, match="not found"):
            await MEloService.get_or_create_melo(db, fake_id, "dp")


# ===========================================================================
# Test: unique constraint
# ===========================================================================


class TestUniqueConstraint:
    """Verify that user_id + tag is unique."""

    @pytest.mark.asyncio
    async def test_duplicate_user_tag_rejected(self, db):
        """Cannot create two records for the same user-tag combination."""
        user = _make_user()
        db.add(user)
        await db.flush()

        # Manually insert a duplicate to test constraint
        melo1 = _TestUserTagElo(user_id=user.id, tag="dp", elo=1200)
        db.add(melo1)
        await db.flush()

        melo2 = _TestUserTagElo(user_id=user.id, tag="dp", elo=1300)
        db.add(melo2)

        with pytest.raises(IntegrityError):
            # Should raise IntegrityError due to unique constraint
            await db.flush()

    @pytest.mark.asyncio
    async def test_same_tag_different_users_ok(self, db):
        """Different users can have the same tag."""
        user1 = _make_user()
        user2 = _make_user()
        db.add_all([user1, user2])
        await db.flush()

        melo1 = await MEloService.get_or_create_melo(db, user1.id, "dp")
        melo2 = await MEloService.get_or_create_melo(db, user2.id, "dp")

        assert melo1.id != melo2.id
        assert melo1.user_id != melo2.user_id


# ===========================================================================
# Test: get_all_melos
# ===========================================================================


class TestGetAllMElos:
    """Verify retrieving all M-Elo records for a user."""

    @pytest.mark.asyncio
    async def test_empty_when_no_records(self, db):
        """Returns empty list when user has no M-Elo records."""
        user = _make_user()
        db.add(user)
        await db.flush()

        melos = await MEloService.get_all_melos(db, user.id)

        assert melos == []

    @pytest.mark.asyncio
    async def test_returns_all_records(self, db):
        """Returns all M-Elo records for a user."""
        user = _make_user(elo=1500)
        db.add(user)
        await db.flush()

        await MEloService.get_or_create_melo(db, user.id, "dp")
        await MEloService.get_or_create_melo(db, user.id, "graphs")
        await MEloService.get_or_create_melo(db, user.id, "math")

        melos = await MEloService.get_all_melos(db, user.id)

        assert len(melos) == 3
        tags = {m.tag for m in melos}
        assert tags == {"dp", "graphs", "math"}

    @pytest.mark.asyncio
    async def test_does_not_return_other_users(self, db):
        """Does not return records belonging to other users."""
        user1 = _make_user()
        user2 = _make_user()
        db.add_all([user1, user2])
        await db.flush()

        await MEloService.get_or_create_melo(db, user1.id, "dp")
        await MEloService.get_or_create_melo(db, user2.id, "dp")
        await MEloService.get_or_create_melo(db, user2.id, "graphs")

        melos1 = await MEloService.get_all_melos(db, user1.id)
        melos2 = await MEloService.get_all_melos(db, user2.id)

        assert len(melos1) == 1
        assert len(melos2) == 2


# ===========================================================================
# Test: update_melo
# ===========================================================================


class TestUpdateMElo:
    """Verify M-Elo update operations."""

    @pytest.mark.asyncio
    async def test_positive_elo_change(self, db):
        """Positive elo_change increases the M-Elo."""
        user = _make_user(elo=1200)
        db.add(user)
        await db.flush()

        melo = await MEloService.update_melo(db, user.id, "dp", 20)

        assert melo.elo == 1220
        assert melo.total_submissions == 1

    @pytest.mark.asyncio
    async def test_negative_elo_change(self, db):
        """Negative elo_change decreases the M-Elo."""
        user = _make_user(elo=1200)
        db.add(user)
        await db.flush()

        melo = await MEloService.update_melo(db, user.id, "dp", -15)

        assert melo.elo == 1185
        assert melo.total_submissions == 1

    @pytest.mark.asyncio
    async def test_multiple_updates_accumulate(self, db):
        """Multiple updates accumulate correctly."""
        user = _make_user(elo=1200)
        db.add(user)
        await db.flush()

        await MEloService.update_melo(db, user.id, "dp", 30)
        await MEloService.update_melo(db, user.id, "dp", -10)
        melo = await MEloService.update_melo(db, user.id, "dp", 5)

        assert melo.elo == 1225  # 1200 + 30 - 10 + 5
        assert melo.total_submissions == 3

    @pytest.mark.asyncio
    async def test_update_creates_record_if_missing(self, db):
        """Update creates the M-Elo record if it does not exist."""
        user = _make_user(elo=1500)
        db.add(user)
        await db.flush()

        melo = await MEloService.update_melo(db, user.id, "dp", 10)

        assert melo.elo == 1510  # Started at 1500 (global elo) + 10
        assert melo.total_submissions == 1


# ===========================================================================
# Test: shield status
# ===========================================================================


class TestShieldStatus:
    """Verify learning shield status checks."""

    @pytest.mark.asyncio
    async def test_shield_active_by_default(self, db):
        """Shield is active when first_ac_at is NULL (new record)."""
        user = _make_user()
        db.add(user)
        await db.flush()

        await MEloService.get_or_create_melo(db, user.id, "dp")
        active = await MEloService.is_shield_active(db, user.id, "dp")

        assert active is True

    @pytest.mark.asyncio
    async def test_shield_active_creates_record(self, db):
        """is_shield_active creates the record if it does not exist."""
        user = _make_user()
        db.add(user)
        await db.flush()

        active = await MEloService.is_shield_active(db, user.id, "dp")

        assert active is True


# ===========================================================================
# Test: deactivate_shield
# ===========================================================================


class TestDeactivateShield:
    """Verify shield deactivation."""

    @pytest.mark.asyncio
    async def test_deactivate_sets_first_ac_at(self, db):
        """Deactivating shield sets first_ac_at to current time."""
        user = _make_user()
        db.add(user)
        await db.flush()

        melo = await MEloService.deactivate_shield(db, user.id, "dp")

        assert melo.first_ac_at is not None
        # Should be a recent datetime
        assert isinstance(melo.first_ac_at, datetime)

    @pytest.mark.asyncio
    async def test_shield_inactive_after_deactivate(self, db):
        """is_shield_active returns False after deactivation."""
        user = _make_user()
        db.add(user)
        await db.flush()

        await MEloService.deactivate_shield(db, user.id, "dp")
        active = await MEloService.is_shield_active(db, user.id, "dp")

        assert active is False

    @pytest.mark.asyncio
    async def test_deactivate_idempotent(self, db):
        """Calling deactivate_shield twice does not change first_ac_at."""
        user = _make_user()
        db.add(user)
        await db.flush()

        melo1 = await MEloService.deactivate_shield(db, user.id, "dp")
        first_ac = melo1.first_ac_at

        melo2 = await MEloService.deactivate_shield(db, user.id, "dp")

        assert melo2.first_ac_at == first_ac

    @pytest.mark.asyncio
    async def test_deactivate_creates_record_if_missing(self, db):
        """Deactivate creates the M-Elo record if it does not exist."""
        user = _make_user(elo=1350)
        db.add(user)
        await db.flush()

        melo = await MEloService.deactivate_shield(db, user.id, "dp")

        assert melo.elo == 1350  # Inherited global elo
        assert melo.first_ac_at is not None

    @pytest.mark.asyncio
    async def test_shield_per_tag_independent(self, db):
        """Shield status is independent per tag."""
        user = _make_user()
        db.add(user)
        await db.flush()

        await MEloService.deactivate_shield(db, user.id, "dp")
        await db.flush()

        # dp shield is off, graphs shield is still on
        dp_active = await MEloService.is_shield_active(db, user.id, "dp")
        graphs_active = await MEloService.is_shield_active(db, user.id, "graphs")

        assert dp_active is False
        assert graphs_active is True


# ===========================================================================
# Test: full lifecycle
# ===========================================================================


class TestFullLifecycle:
    """Verify complete M-Elo lifecycle scenarios."""

    @pytest.mark.asyncio
    async def test_new_tag_to_first_ac(self, db):
        """Simulate: new tag -> shield active -> first AC -> shield off -> elo update."""
        user = _make_user(elo=1000)
        db.add(user)
        await db.flush()

        # 1. First encounter with tag: shield is active
        active = await MEloService.is_shield_active(db, user.id, "dp")
        assert active is True

        # 2. Shield protects from Elo loss
        melo = await MEloService.get_or_create_melo(db, user.id, "dp")
        assert melo.elo == 1000

        # 3. First AC: deactivate shield
        await MEloService.deactivate_shield(db, user.id, "dp")
        active = await MEloService.is_shield_active(db, user.id, "dp")
        assert active is False

        # 4. Update Elo after AC
        melo = await MEloService.update_melo(db, user.id, "dp", 25)
        assert melo.elo == 1025
        assert melo.total_submissions == 1

    @pytest.mark.asyncio
    async def test_multiple_users_same_tag(self, db):
        """Multiple users can independently track the same tag."""
        user1 = _make_user(elo=1000)
        user2 = _make_user(elo=1800)
        db.add_all([user1, user2])
        await db.flush()

        melo1 = await MEloService.get_or_create_melo(db, user1.id, "dp")
        melo2 = await MEloService.get_or_create_melo(db, user2.id, "dp")

        assert melo1.elo == 1000
        assert melo2.elo == 1800

        await MEloService.update_melo(db, user1.id, "dp", 50)
        await MEloService.update_melo(db, user2.id, "dp", -30)

        melo1 = await MEloService.get_or_create_melo(db, user1.id, "dp")
        melo2 = await MEloService.get_or_create_melo(db, user2.id, "dp")

        assert melo1.elo == 1050
        assert melo2.elo == 1770
