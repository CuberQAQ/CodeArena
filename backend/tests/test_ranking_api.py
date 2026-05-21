"""Tests for the global ranking API.

Uses lightweight SQLite-compatible test models and patching strategy.
Tests cover:
- Mixed global ranking (CA + CF users)
- Arena-only ranking (CA users)
- Country filtering
- Pagination
- Verified flag correctness
- Tie-breaking (CA users first on equal PP)
- Empty data handling
- PP=0 users excluded
- is_active=False users excluded
"""

import uuid
from unittest.mock import patch

import pytest
from sqlalchemy import Boolean, Float, Integer, String, event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# ---------------------------------------------------------------------------
# Lightweight SQLite-compatible test models
# ---------------------------------------------------------------------------


class _TestBase(DeclarativeBase):
    pass


class _TestUser(_TestBase):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(String(50), nullable=False)
    pp: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    elo: Mapped[int] = mapped_column(Integer, default=1200, nullable=False)
    cf_handle: Mapped[str | None] = mapped_column(String(100), nullable=True)
    cf_handle_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class _TestCFSampleUser(_TestBase):
    __tablename__ = "cf_sample_users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    cf_handle: Mapped[str] = mapped_column(String(100), nullable=False)
    cf_rating: Mapped[int] = mapped_column(Integer, nullable=False)
    country: Mapped[str | None] = mapped_column(String(10), nullable=True)
    estimated_pp: Mapped[float | None] = mapped_column(Float, nullable=True)
    sample_batch: Mapped[int] = mapped_column(Integer, nullable=False)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_SQLITE_PATH = "sqlite+aiosqlite:///:memory:"


@pytest.fixture
async def async_engine():
    engine = create_async_engine(_SQLITE_PATH, echo=False)

    # Enable WAL for async SQLite
    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragma(dbapi_conn, _connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()

    async with engine.begin() as conn:
        await conn.run_sync(_TestBase.metadata.create_all)

    yield engine

    async with engine.begin() as conn:
        await conn.run_sync(_TestBase.metadata.drop_all)

    await engine.dispose()


@pytest.fixture
async def db_session(async_engine):
    session_factory = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(
    username: str,
    pp: float = 100.0,
    elo: int = 1500,
    cf_handle: str | None = None,
    cf_handle_verified: bool = False,
    is_active: bool = True,
) -> _TestUser:
    return _TestUser(
        id=uuid.uuid4(),
        username=username,
        pp=pp,
        elo=elo,
        cf_handle=cf_handle,
        cf_handle_verified=cf_handle_verified,
        is_active=is_active,
    )


def _make_cf_user(
    handle: str,
    cf_rating: int = 2000,
    estimated_pp: float = 150.0,
    country: str | None = None,
    batch: int = 1,
) -> _TestCFSampleUser:
    return _TestCFSampleUser(
        id=uuid.uuid4(),
        cf_handle=handle,
        cf_rating=cf_rating,
        estimated_pp=estimated_pp,
        country=country,
        sample_batch=batch,
    )


# ---------------------------------------------------------------------------
# Unit tests for the ranking logic (using mock DB results)
# ---------------------------------------------------------------------------


class TestGlobalRankingLogic:
    """Test the core logic of the global ranking endpoint."""

    @pytest.mark.asyncio
    async def test_mixed_ranking_ca_and_cf(self, db_session: AsyncSession):
        """CA and CF users are correctly merged and sorted by PP."""
        ca_user = _make_user("alice", pp=200.0)
        cf_user = _make_cf_user("tourist", cf_rating=3000, estimated_pp=300.0, batch=1)

        db_session.add_all([ca_user, cf_user])
        await db_session.commit()

        # Patch the models in the ranking module
        import app.api.v1.ranking as ranking_mod

        with (
            patch.object(ranking_mod, "User", _TestUser),
            patch.object(ranking_mod, "CFSampleUser", _TestCFSampleUser),
        ):
            from app.api.v1.ranking import get_global_ranking

            response = await get_global_ranking(
                country=None,
                page=1,
                page_size=50,
                db=db_session,
            )

        data = response.body
        import json

        result = json.loads(data)
        assert result["success"] is True
        items = result["data"]["items"]
        total = result["data"]["total"]
        assert total == 2
        assert len(items) == 2
        # CF user (tourist, pp=300) should be first
        assert items[0]["name"] == "tourist"
        assert items[0]["pp"] == 300.0
        assert items[0]["verified"] is False
        assert items[0]["cf_rating"] == 3000
        # CA user (alice, pp=200) second
        assert items[1]["name"] == "alice"
        assert items[1]["pp"] == 200.0
        assert items[1]["verified"] is True

    @pytest.mark.asyncio
    async def test_ca_user_priority_on_tie(self, db_session: AsyncSession):
        """When PP is equal, CA users rank above CF users."""
        ca_user = _make_user("alice", pp=200.0)
        cf_user = _make_cf_user("bob_cf", cf_rating=2000, estimated_pp=200.0, batch=1)

        db_session.add_all([ca_user, cf_user])
        await db_session.commit()

        import app.api.v1.ranking as ranking_mod

        with (
            patch.object(ranking_mod, "User", _TestUser),
            patch.object(ranking_mod, "CFSampleUser", _TestCFSampleUser),
        ):
            from app.api.v1.ranking import get_global_ranking

            response = await get_global_ranking(country=None, page=1, page_size=50, db=db_session)

        import json

        result = json.loads(response.body)
        items = result["data"]["items"]
        assert items[0]["name"] == "alice"
        assert items[0]["verified"] is True
        assert items[1]["name"] == "bob_cf"
        assert items[1]["verified"] is False

    @pytest.mark.asyncio
    async def test_country_filter(self, db_session: AsyncSession):
        """Country filter correctly excludes non-matching users."""
        ca_user = _make_user("alice", pp=200.0, cf_handle="alice_cf", cf_handle_verified=True)
        cf_user_cn = _make_cf_user("bob_cn", estimated_pp=150.0, country="CN", batch=1)
        # Add a second CF row for the CA user's country lookup
        cf_alice = _make_cf_user("alice_cf", estimated_pp=180.0, country="US", batch=1)

        db_session.add_all([ca_user, cf_user_cn, cf_alice])
        await db_session.commit()

        import app.api.v1.ranking as ranking_mod

        with (
            patch.object(ranking_mod, "User", _TestUser),
            patch.object(ranking_mod, "CFSampleUser", _TestCFSampleUser),
        ):
            from app.api.v1.ranking import get_global_ranking

            response = await get_global_ranking(country="CN", page=1, page_size=50, db=db_session)

        import json

        result = json.loads(response.body)
        items = result["data"]["items"]
        assert len(items) == 1
        assert items[0]["name"] == "bob_cn"
        assert items[0]["country"] == "CN"

    @pytest.mark.asyncio
    async def test_pagination(self, db_session: AsyncSession):
        """Pagination returns correct page slice."""
        for i in range(5):
            db_session.add(_make_user(f"user_{i}", pp=100.0 - i))
        await db_session.commit()

        import app.api.v1.ranking as ranking_mod

        with (
            patch.object(ranking_mod, "User", _TestUser),
            patch.object(ranking_mod, "CFSampleUser", _TestCFSampleUser),
        ):
            from app.api.v1.ranking import get_global_ranking

            response = await get_global_ranking(country=None, page=2, page_size=2, db=db_session)

        import json

        result = json.loads(response.body)
        assert result["data"]["total"] == 5
        assert result["data"]["page"] == 2
        assert result["data"]["page_size"] == 2
        assert len(result["data"]["items"]) == 2

    @pytest.mark.asyncio
    async def test_empty_data(self, db_session: AsyncSession):
        """Empty database returns empty results without error."""
        import app.api.v1.ranking as ranking_mod

        with (
            patch.object(ranking_mod, "User", _TestUser),
            patch.object(ranking_mod, "CFSampleUser", _TestCFSampleUser),
        ):
            from app.api.v1.ranking import get_global_ranking

            response = await get_global_ranking(country=None, page=1, page_size=50, db=db_session)

        import json

        result = json.loads(response.body)
        assert result["data"]["total"] == 0
        assert result["data"]["items"] == []

    @pytest.mark.asyncio
    async def test_inactive_users_excluded(self, db_session: AsyncSession):
        """is_active=False users are not included in rankings."""
        active = _make_user("active_user", pp=100.0, is_active=True)
        inactive = _make_user("inactive_user", pp=200.0, is_active=False)

        db_session.add_all([active, inactive])
        await db_session.commit()

        import app.api.v1.ranking as ranking_mod

        with (
            patch.object(ranking_mod, "User", _TestUser),
            patch.object(ranking_mod, "CFSampleUser", _TestCFSampleUser),
        ):
            from app.api.v1.ranking import get_global_ranking

            response = await get_global_ranking(country=None, page=1, page_size=50, db=db_session)

        import json

        result = json.loads(response.body)
        assert result["data"]["total"] == 1
        assert result["data"]["items"][0]["name"] == "active_user"

    @pytest.mark.asyncio
    async def test_zero_pp_users_excluded(self, db_session: AsyncSession):
        """PP=0 users are not included in rankings."""
        user_with_pp = _make_user("has_pp", pp=50.0)
        user_zero_pp = _make_user("zero_pp", pp=0.0)

        db_session.add_all([user_with_pp, user_zero_pp])
        await db_session.commit()

        import app.api.v1.ranking as ranking_mod

        with (
            patch.object(ranking_mod, "User", _TestUser),
            patch.object(ranking_mod, "CFSampleUser", _TestCFSampleUser),
        ):
            from app.api.v1.ranking import get_global_ranking

            response = await get_global_ranking(country=None, page=1, page_size=50, db=db_session)

        import json

        result = json.loads(response.body)
        assert result["data"]["total"] == 1
        assert result["data"]["items"][0]["name"] == "has_pp"

    @pytest.mark.asyncio
    async def test_duplicate_cf_handle_dedup(self, db_session: AsyncSession):
        """CA user with verified CF handle deduplicates the CF entry."""
        ca_user = _make_user("alice", pp=200.0, cf_handle="alice_cf", cf_handle_verified=True)
        cf_dup = _make_cf_user("alice_cf", estimated_pp=180.0, country="US", batch=1)
        cf_other = _make_cf_user("bob", estimated_pp=100.0, country="CN", batch=1)

        db_session.add_all([ca_user, cf_dup, cf_other])
        await db_session.commit()

        import app.api.v1.ranking as ranking_mod

        with (
            patch.object(ranking_mod, "User", _TestUser),
            patch.object(ranking_mod, "CFSampleUser", _TestCFSampleUser),
        ):
            from app.api.v1.ranking import get_global_ranking

            response = await get_global_ranking(country=None, page=1, page_size=50, db=db_session)

        import json

        result = json.loads(response.body)
        items = result["data"]["items"]
        # alice_cf should appear only once (as CA user)
        names = [item["name"] for item in items]
        assert names.count("alice") == 1
        assert "alice_cf" not in names  # CF entry for same handle should be excluded
        assert "bob" in names
        # Total should be 2 (alice + bob), not 3
        assert result["data"]["total"] == 2

    @pytest.mark.asyncio
    async def test_ca_user_country_from_cf_handle(self, db_session: AsyncSession):
        """CA user with verified CF handle gets country from CF sample data."""
        ca_user = _make_user("alice", pp=200.0, cf_handle="alice_cf", cf_handle_verified=True)
        cf_row = _make_cf_user("alice_cf", estimated_pp=180.0, country="JP", batch=1)

        db_session.add_all([ca_user, cf_row])
        await db_session.commit()

        import app.api.v1.ranking as ranking_mod

        with (
            patch.object(ranking_mod, "User", _TestUser),
            patch.object(ranking_mod, "CFSampleUser", _TestCFSampleUser),
        ):
            from app.api.v1.ranking import get_global_ranking

            response = await get_global_ranking(country=None, page=1, page_size=50, db=db_session)

        import json

        result = json.loads(response.body)
        alice_item = next(i for i in result["data"]["items"] if i["name"] == "alice")
        assert alice_item["country"] == "JP"

    @pytest.mark.asyncio
    async def test_latest_batch_only(self, db_session: AsyncSession):
        """Only the latest batch of CF samples is used."""
        ca_user = _make_user("alice", pp=200.0)
        cf_old = _make_cf_user("old_user", estimated_pp=50.0, batch=1)
        cf_new = _make_cf_user("new_user", estimated_pp=80.0, batch=2)

        db_session.add_all([ca_user, cf_old, cf_new])
        await db_session.commit()

        import app.api.v1.ranking as ranking_mod

        with (
            patch.object(ranking_mod, "User", _TestUser),
            patch.object(ranking_mod, "CFSampleUser", _TestCFSampleUser),
        ):
            from app.api.v1.ranking import get_global_ranking

            response = await get_global_ranking(country=None, page=1, page_size=50, db=db_session)

        import json

        result = json.loads(response.body)
        names = [i["name"] for i in result["data"]["items"]]
        assert "new_user" in names
        assert "old_user" not in names

    @pytest.mark.asyncio
    async def test_cf_only_no_ca_users(self, db_session: AsyncSession):
        """Global ranking works with only CF users (no CA users)."""
        cf_user1 = _make_cf_user("tourist", cf_rating=3800, estimated_pp=350.0, country="BY", batch=1)
        cf_user2 = _make_cf_user("petr", cf_rating=3200, estimated_pp=280.0, country="RU", batch=1)

        db_session.add_all([cf_user1, cf_user2])
        await db_session.commit()

        import app.api.v1.ranking as ranking_mod

        with (
            patch.object(ranking_mod, "User", _TestUser),
            patch.object(ranking_mod, "CFSampleUser", _TestCFSampleUser),
        ):
            from app.api.v1.ranking import get_global_ranking

            response = await get_global_ranking(country=None, page=1, page_size=50, db=db_session)

        import json

        result = json.loads(response.body)
        items = result["data"]["items"]
        assert result["data"]["total"] == 2
        assert len(items) == 2
        # Sorted by PP descending
        assert items[0]["name"] == "tourist"
        assert items[0]["pp"] == 350.0
        assert items[0]["verified"] is False
        assert items[0]["cf_rating"] == 3800
        assert items[1]["name"] == "petr"
        assert items[1]["verified"] is False

    @pytest.mark.asyncio
    async def test_cf_user_with_null_estimated_pp_excluded(self, db_session: AsyncSession):
        """CF users with estimated_pp=None are excluded from global ranking."""
        ca_user = _make_user("alice", pp=100.0)
        cf_valid = _make_cf_user("valid_cf", cf_rating=2000, estimated_pp=150.0, batch=1)
        # Manually create a CF user with null estimated_pp
        cf_null = _TestCFSampleUser(
            id=uuid.uuid4(),
            cf_handle="null_pp_cf",
            cf_rating=1800,
            estimated_pp=None,
            country="US",
            sample_batch=1,
        )

        db_session.add_all([ca_user, cf_valid, cf_null])
        await db_session.commit()

        import app.api.v1.ranking as ranking_mod

        with (
            patch.object(ranking_mod, "User", _TestUser),
            patch.object(ranking_mod, "CFSampleUser", _TestCFSampleUser),
        ):
            from app.api.v1.ranking import get_global_ranking

            response = await get_global_ranking(country=None, page=1, page_size=50, db=db_session)

        import json

        result = json.loads(response.body)
        names = [i["name"] for i in result["data"]["items"]]
        assert "valid_cf" in names
        assert "null_pp_cf" not in names

    @pytest.mark.asyncio
    async def test_cf_user_with_zero_estimated_pp_excluded(self, db_session: AsyncSession):
        """CF users with estimated_pp=0 are excluded from global ranking."""
        ca_user = _make_user("alice", pp=100.0)
        cf_zero = _TestCFSampleUser(
            id=uuid.uuid4(),
            cf_handle="zero_pp_cf",
            cf_rating=1200,
            estimated_pp=0.0,
            country="US",
            sample_batch=1,
        )

        db_session.add_all([ca_user, cf_zero])
        await db_session.commit()

        import app.api.v1.ranking as ranking_mod

        with (
            patch.object(ranking_mod, "User", _TestUser),
            patch.object(ranking_mod, "CFSampleUser", _TestCFSampleUser),
        ):
            from app.api.v1.ranking import get_global_ranking

            response = await get_global_ranking(country=None, page=1, page_size=50, db=db_session)

        import json

        result = json.loads(response.body)
        names = [i["name"] for i in result["data"]["items"]]
        assert "zero_pp_cf" not in names

    @pytest.mark.asyncio
    async def test_cf_user_country_filter(self, db_session: AsyncSession):
        """Country filter works for CF users in global ranking."""
        cf_cn = _make_cf_user("cn_user", estimated_pp=100.0, country="CN", batch=1)
        cf_us = _make_cf_user("us_user", estimated_pp=200.0, country="US", batch=1)

        db_session.add_all([cf_cn, cf_us])
        await db_session.commit()

        import app.api.v1.ranking as ranking_mod

        with (
            patch.object(ranking_mod, "User", _TestUser),
            patch.object(ranking_mod, "CFSampleUser", _TestCFSampleUser),
        ):
            from app.api.v1.ranking import get_global_ranking

            response = await get_global_ranking(country="CN", page=1, page_size=50, db=db_session)

        import json

        result = json.loads(response.body)
        items = result["data"]["items"]
        assert len(items) == 1
        assert items[0]["name"] == "cn_user"
        assert items[0]["country"] == "CN"

    @pytest.mark.asyncio
    async def test_cf_user_cf_rating_returned(self, db_session: AsyncSession):
        """CF users have cf_rating in the API response."""
        cf_user = _make_cf_user("tourist", cf_rating=3800, estimated_pp=350.0, batch=1)

        db_session.add(cf_user)
        await db_session.commit()

        import app.api.v1.ranking as ranking_mod

        with (
            patch.object(ranking_mod, "User", _TestUser),
            patch.object(ranking_mod, "CFSampleUser", _TestCFSampleUser),
        ):
            from app.api.v1.ranking import get_global_ranking

            response = await get_global_ranking(country=None, page=1, page_size=50, db=db_session)

        import json

        result = json.loads(response.body)
        item = result["data"]["items"][0]
        assert item["cf_rating"] == 3800
        assert item["verified"] is False

    @pytest.mark.asyncio
    async def test_ca_user_no_cf_rating_in_response(self, db_session: AsyncSession):
        """CA users do not have cf_rating in the API response."""
        ca_user = _make_user("alice", pp=100.0, cf_handle="alice_cf", cf_handle_verified=True)

        db_session.add(ca_user)
        await db_session.commit()

        import app.api.v1.ranking as ranking_mod

        with (
            patch.object(ranking_mod, "User", _TestUser),
            patch.object(ranking_mod, "CFSampleUser", _TestCFSampleUser),
        ):
            from app.api.v1.ranking import get_global_ranking

            response = await get_global_ranking(country=None, page=1, page_size=50, db=db_session)

        import json

        result = json.loads(response.body)
        item = result["data"]["items"][0]
        assert "cf_rating" not in item
        assert item["verified"] is True

    @pytest.mark.asyncio
    async def test_large_mixed_ranking_sort_order(self, db_session: AsyncSession):
        """Large mixed ranking is correctly sorted: PP desc, CA priority on tie."""
        # Create multiple CA and CF users with overlapping PP values
        for i in range(5):
            db_session.add(_make_user(f"ca_{i}", pp=200.0 - i * 10))

        for i in range(5):
            db_session.add(_make_cf_user(f"cf_{i}", cf_rating=2000 + i * 100, estimated_pp=195.0 - i * 10, batch=1))

        await db_session.commit()

        import app.api.v1.ranking as ranking_mod

        with (
            patch.object(ranking_mod, "User", _TestUser),
            patch.object(ranking_mod, "CFSampleUser", _TestCFSampleUser),
        ):
            from app.api.v1.ranking import get_global_ranking

            response = await get_global_ranking(country=None, page=1, page_size=50, db=db_session)

        import json

        result = json.loads(response.body)
        items = result["data"]["items"]
        assert result["data"]["total"] == 10

        # Verify sorting: PP descending
        pps = [item["pp"] for item in items]
        assert pps == sorted(pps, reverse=True)

        # Find tied users at PP=200.0 and verify CA user comes first
        ca_0_item = next(i for i in items if i["name"] == "ca_0")
        cf_0_item = next(i for i in items if i["name"] == "cf_0")
        # ca_0 has pp=200.0 and cf_0 has pp=195.0, so ca_0 should be before cf_0
        assert items.index(ca_0_item) < items.index(cf_0_item)


class TestArenaRankingLogic:
    """Test the arena-only ranking endpoint."""

    @pytest.mark.asyncio
    async def test_arena_only_shows_ca_users(self, db_session: AsyncSession):
        """Arena ranking only includes CA users."""
        ca_user = _make_user("alice", pp=200.0, elo=1600)

        db_session.add(ca_user)
        await db_session.commit()

        import app.api.v1.ranking as ranking_mod

        with (
            patch.object(ranking_mod, "User", _TestUser),
            patch.object(ranking_mod, "CFSampleUser", _TestCFSampleUser),
        ):
            from app.api.v1.ranking import get_arena_ranking

            response = await get_arena_ranking(country=None, page=1, page_size=50, db=db_session)

        import json

        result = json.loads(response.body)
        items = result["data"]["items"]
        assert len(items) == 1
        assert items[0]["name"] == "alice"
        assert items[0]["pp"] == 200.0
        assert items[0]["elo"] == 1600
        assert items[0]["verified"] is True

    @pytest.mark.asyncio
    async def test_arena_sort_by_elo(self, db_session: AsyncSession):
        """Arena ranking supports sort_by=elo."""
        user1 = _make_user("low_elo", pp=100.0, elo=1200)
        user2 = _make_user("high_elo", pp=50.0, elo=2000)

        db_session.add_all([user1, user2])
        await db_session.commit()

        import app.api.v1.ranking as ranking_mod

        with (
            patch.object(ranking_mod, "User", _TestUser),
            patch.object(ranking_mod, "CFSampleUser", _TestCFSampleUser),
        ):
            from app.api.v1.ranking import get_arena_ranking

            response = await get_arena_ranking(sort_by="elo", country=None, page=1, page_size=50, db=db_session)

        import json

        result = json.loads(response.body)
        items = result["data"]["items"]
        assert items[0]["name"] == "high_elo"
        assert items[0]["elo"] == 2000
        assert items[1]["name"] == "low_elo"
        assert items[1]["elo"] == 1200

    @pytest.mark.asyncio
    async def test_arena_sort_by_pp(self, db_session: AsyncSession):
        """Arena ranking default sort is by PP descending."""
        user1 = _make_user("low_pp", pp=50.0, elo=2000)
        user2 = _make_user("high_pp", pp=300.0, elo=1200)

        db_session.add_all([user1, user2])
        await db_session.commit()

        import app.api.v1.ranking as ranking_mod

        with (
            patch.object(ranking_mod, "User", _TestUser),
            patch.object(ranking_mod, "CFSampleUser", _TestCFSampleUser),
        ):
            from app.api.v1.ranking import get_arena_ranking

            response = await get_arena_ranking(country=None, page=1, page_size=50, db=db_session)

        import json

        result = json.loads(response.body)
        items = result["data"]["items"]
        assert items[0]["name"] == "high_pp"
        assert items[0]["pp"] == 300.0

    @pytest.mark.asyncio
    async def test_arena_country_filter(self, db_session: AsyncSession):
        """Country filter works on arena ranking."""
        user_us = _make_user("us_user", pp=100.0, cf_handle="us_cf", cf_handle_verified=True)
        user_cn = _make_user("cn_user", pp=200.0, cf_handle="cn_cf", cf_handle_verified=True)
        cf_us = _make_cf_user("us_cf", estimated_pp=80.0, country="US", batch=1)
        cf_cn = _make_cf_user("cn_cf", estimated_pp=90.0, country="CN", batch=1)

        db_session.add_all([user_us, user_cn, cf_us, cf_cn])
        await db_session.commit()

        import app.api.v1.ranking as ranking_mod

        with (
            patch.object(ranking_mod, "User", _TestUser),
            patch.object(ranking_mod, "CFSampleUser", _TestCFSampleUser),
        ):
            from app.api.v1.ranking import get_arena_ranking

            response = await get_arena_ranking(country="US", page=1, page_size=50, db=db_session)

        import json

        result = json.loads(response.body)
        items = result["data"]["items"]
        assert len(items) == 1
        assert items[0]["name"] == "us_user"
        assert items[0]["country"] == "US"

    @pytest.mark.asyncio
    async def test_arena_empty_data(self, db_session: AsyncSession):
        """Empty database returns empty arena results."""
        import app.api.v1.ranking as ranking_mod

        with (
            patch.object(ranking_mod, "User", _TestUser),
            patch.object(ranking_mod, "CFSampleUser", _TestCFSampleUser),
        ):
            from app.api.v1.ranking import get_arena_ranking

            response = await get_arena_ranking(country=None, page=1, page_size=50, db=db_session)

        import json

        result = json.loads(response.body)
        assert result["data"]["total"] == 0
        assert result["data"]["items"] == []

    @pytest.mark.asyncio
    async def test_arena_pagination(self, db_session: AsyncSession):
        """Pagination works correctly for arena ranking."""
        for i in range(10):
            db_session.add(_make_user(f"user_{i}", pp=100.0 - i, elo=1500 + i))
        await db_session.commit()

        import app.api.v1.ranking as ranking_mod

        with (
            patch.object(ranking_mod, "User", _TestUser),
            patch.object(ranking_mod, "CFSampleUser", _TestCFSampleUser),
        ):
            from app.api.v1.ranking import get_arena_ranking

            response = await get_arena_ranking(country=None, page=3, page_size=3, db=db_session)

        import json

        result = json.loads(response.body)
        assert result["data"]["total"] == 10
        assert result["data"]["page"] == 3
        assert result["data"]["page_size"] == 3
        assert len(result["data"]["items"]) == 3


class TestPaginationHelper:
    """Test the _paginate helper function."""

    def test_first_page(self):
        from app.api.v1.ranking import _paginate

        items = [{"name": f"u{i}"} for i in range(10)]
        result = _paginate(items, page=1, page_size=3)
        assert result["total"] == 10
        assert result["page"] == 1
        assert result["page_size"] == 3
        assert len(result["items"]) == 3
        assert result["items"][0]["name"] == "u0"

    def test_last_page_partial(self):
        from app.api.v1.ranking import _paginate

        items = [{"name": f"u{i}"} for i in range(10)]
        result = _paginate(items, page=4, page_size=3)
        assert result["total"] == 10
        assert len(result["items"]) == 1  # 10 items, page 4 with size 3 -> last 1

    def test_page_beyond_data(self):
        from app.api.v1.ranking import _paginate

        items = [{"name": f"u{i}"} for i in range(5)]
        result = _paginate(items, page=10, page_size=3)
        assert result["total"] == 5
        assert result["items"] == []

    def test_empty_list(self):
        from app.api.v1.ranking import _paginate

        result = _paginate([], page=1, page_size=50)
        assert result["total"] == 0
        assert result["items"] == []
