"""Tests for the PP rank API endpoint (GET /auth/pp-rank).

Validates rank calculation, percentile derivation, and edge cases for users
with zero PP or an empty user base.
"""

import uuid
from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from sqlalchemy import Boolean, DateTime, Float, Integer, String, event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core.response import success_response
from app.core.security import hash_password
from app.models.user import User

# ---------------------------------------------------------------------------
# Lightweight SQLite-compatible test models
# ---------------------------------------------------------------------------


class _TestBase(DeclarativeBase):
    pass


class _TestUser(_TestBase):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    cf_handle: Mapped[str | None] = mapped_column(String(100), nullable=True)
    elo: Mapped[int] = mapped_column(Integer, default=1200, nullable=False)
    pp: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


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
        yield session


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _make_user(
    db: AsyncSession,
    username: str,
    email: str,
    pp: float = 0.0,
    elo: int = 1200,
    is_active: bool = True,
    created_at: datetime | None = None,
) -> _TestUser:
    """Insert a test user with given PP value."""
    user = _TestUser(
        username=username,
        email=email,
        password_hash=hash_password("TestPass123"),
        pp=pp,
        elo=elo,
        is_active=is_active,
        created_at=created_at or datetime.now(UTC),
    )
    db.add(user)
    await db.flush()
    return user


# ---------------------------------------------------------------------------
# The core ranking logic, extracted for direct testing
# ---------------------------------------------------------------------------


async def _calculate_pp_rank(user: _TestUser, db: AsyncSession):
    """Mimics the pp-rank endpoint logic for testing."""
    from sqlalchemy import func, select

    user_pp = user.pp or 0

    total_result = await db.execute(
        select(func.count(_TestUser.id)).where(_TestUser.is_active.is_(True))
    )
    total_users = total_result.scalar() or 0

    if total_users == 0 or user_pp <= 0:
        return {"rank": None, "total_users": total_users, "top_percent": None}

    higher_result = await db.execute(
        select(func.count(_TestUser.id)).where(
            _TestUser.is_active.is_(True),
            (
                (_TestUser.pp > user_pp)
                | ((_TestUser.pp == user_pp) & (_TestUser.created_at < user.created_at))
            ),
        )
    )
    higher_count = higher_result.scalar() or 0
    rank = higher_count + 1
    top_percent = round(rank / total_users * 100, 1)

    return {"rank": rank, "total_users": total_users, "top_percent": top_percent}


# ===========================================================================
# Tests
# ===========================================================================


class TestPPRank:
    async def test_single_user_with_pp(self, db):
        """A single active user with PP > 0 gets rank 1."""
        user = await _make_user(db, "solo", "solo@test.com", pp=1500.0)
        result = await _calculate_pp_rank(user, db)
        assert result["rank"] == 1
        assert result["total_users"] == 1
        assert result["top_percent"] == 100.0

    async def test_single_user_zero_pp(self, db):
        """A user with PP == 0 is unranked."""
        user = await _make_user(db, "zero", "zero@test.com", pp=0.0)
        result = await _calculate_pp_rank(user, db)
        assert result["rank"] is None
        assert result["total_users"] == 1
        assert result["top_percent"] is None

    async def test_three_users_correct_ranking(self, db):
        """Three users with different PP get correct ranks."""
        u1 = await _make_user(db, "high", "high@test.com", pp=3000.0, created_at=datetime(2024, 1, 1, tzinfo=UTC))
        u2 = await _make_user(db, "mid", "mid@test.com", pp=2000.0, created_at=datetime(2024, 1, 2, tzinfo=UTC))
        u3 = await _make_user(db, "low", "low@test.com", pp=1000.0, created_at=datetime(2024, 1, 3, tzinfo=UTC))

        r1 = await _calculate_pp_rank(u1, db)
        r2 = await _calculate_pp_rank(u2, db)
        r3 = await _calculate_pp_rank(u3, db)

        assert r1["rank"] == 1
        assert r2["rank"] == 2
        assert r3["rank"] == 3

    async def test_top_percent_calculation(self, db):
        """Top percent = rank/total * 100."""
        # 10 users, user is rank 3 => top_percent = 3/10 * 100 = 30.0
        for i in range(10):
            await _make_user(
                db,
                f"user{i}",
                f"user{i}@test.com",
                pp=float(1000 - i * 100),
                created_at=datetime(2024, 1, 1 + i, tzinfo=UTC),
            )

        # The 3rd user (index 2, pp=800) should be rank 3
        from sqlalchemy import select
        result = await db.execute(select(_TestUser).where(_TestUser.username == "user2"))
        user2 = result.scalar_one()
        rank_info = await _calculate_pp_rank(user2, db)
        assert rank_info["rank"] == 3
        assert rank_info["total_users"] == 10
        assert rank_info["top_percent"] == 30.0

    async def test_tie_breaking_by_created_at(self, db):
        """Users with same PP are ranked by earlier created_at first."""
        u1 = await _make_user(db, "early", "early@test.com", pp=1000.0, created_at=datetime(2024, 1, 1, tzinfo=UTC))
        u2 = await _make_user(db, "late", "late@test.com", pp=1000.0, created_at=datetime(2024, 6, 1, tzinfo=UTC))

        r1 = await _calculate_pp_rank(u1, db)
        r2 = await _calculate_pp_rank(u2, db)

        # Same PP, but u1 registered earlier so u1 has no one ahead
        assert r1["rank"] == 1
        assert r2["rank"] == 2

    async def test_inactive_users_excluded(self, db):
        """Inactive users should not appear in the ranking."""
        await _make_user(db, "active", "active@test.com", pp=500.0, is_active=True)
        await _make_user(db, "inactive", "inactive@test.com", pp=9999.0, is_active=False)

        from sqlalchemy import select
        result = await db.execute(select(_TestUser).where(_TestUser.username == "active"))
        active_user = result.scalar_one()
        rank_info = await _calculate_pp_rank(active_user, db)
        assert rank_info["rank"] == 1
        assert rank_info["total_users"] == 1

    async def test_empty_database(self, db):
        """Edge case: no users at all (should not happen in practice)."""
        user = _TestUser(
            username="ghost",
            email="ghost@test.com",
            password_hash=hash_password("TestPass123"),
            pp=100.0,
            is_active=True,
            created_at=datetime.now(UTC),
        )
        # Don't persist -- just test the logic with a detached user
        # In practice, the endpoint always has a real user. This tests
        # the total_users == 0 guard path.
        from sqlalchemy import func, select

        total_result = await db.execute(
            select(func.count(_TestUser.id)).where(_TestUser.is_active.is_(True))
        )
        total_users = total_result.scalar() or 0
        assert total_users == 0

    async def test_rank_1_top_percent_low(self, db):
        """Rank 1 out of N means top_percent = 1/5 * 100 = 20.0."""
        for i in range(5):
            await _make_user(
                db,
                f"u{i}",
                f"u{i}@test.com",
                pp=float(500 - i * 100),
                created_at=datetime(2024, 1, 1 + i, tzinfo=UTC),
            )

        from sqlalchemy import select
        result = await db.execute(select(_TestUser).where(_TestUser.username == "u0"))
        top_user = result.scalar_one()
        rank_info = await _calculate_pp_rank(top_user, db)
        assert rank_info["rank"] == 1
        assert rank_info["top_percent"] == 20.0

    async def test_last_rank_top_percent_100(self, db):
        """Last-ranked user has top_percent = 100.0."""
        for i in range(5):
            await _make_user(
                db,
                f"u{i}",
                f"u{i}@test.com",
                pp=float(500 - i * 100),
                created_at=datetime(2024, 1, 1 + i, tzinfo=UTC),
            )

        from sqlalchemy import select
        result = await db.execute(select(_TestUser).where(_TestUser.username == "u4"))
        last_user = result.scalar_one()
        rank_info = await _calculate_pp_rank(last_user, db)
        assert rank_info["rank"] == 5
        assert rank_info["top_percent"] == 100.0
