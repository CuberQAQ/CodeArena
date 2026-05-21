"""Tests for cf_handle_service — CF account binding, verification, and unbinding.

Covers:
- bind_cf_handle: happy path, already bound, handle taken, CF API errors
- verify_cf_handle: happy path, no pending binding, handle mismatch,
  already verified, code mismatch, code not in profile, CF API errors
- get_cf_handle_info: happy path, not found, API errors
- unbind_cf_handle: happy path, nothing to unbind
- _extract_cf_info: field extraction
- _generate_verification_code: format checks
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import Boolean, Float, Integer, String, event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core.exceptions import BadRequestException, ConflictException, NotFoundException
from app.services.cf_api_service import (
    CFAPIError,
    CFNetworkError,
    CFNotFoundError,
    CFRateLimitError,
)

# ---------------------------------------------------------------------------
# Lightweight SQLite-compatible User model for testing
# ---------------------------------------------------------------------------


class _TestBase(DeclarativeBase):
    pass


class _TestUser(_TestBase):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4, nullable=False)
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    cf_handle: Mapped[str | None] = mapped_column(String(100), unique=True, nullable=True)
    cf_handle_verified: Mapped[bool] = mapped_column(Boolean, server_default="false", nullable=False)
    cf_verification_code: Mapped[str | None] = mapped_column(String(8), nullable=True)
    elo: Mapped[int] = mapped_column(Integer, server_default="1200", nullable=False)
    pp: Mapped[float] = mapped_column(Float, server_default="0", nullable=False)
    tokens: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true", nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, server_default="false", nullable=False)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def engine():
    """Create a fresh SQLite in-memory engine for each test."""
    eng = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)

    @event.listens_for(eng.sync_engine, "connect")
    def _set_sqlite_pragma(dbapi_conn, _connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return eng


@pytest.fixture
async def tables(engine):
    """Create all tables in the test database."""
    async with engine.begin() as conn:
        await conn.run_sync(_TestBase.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(_TestBase.metadata.drop_all)


@pytest.fixture
async def db_session(engine, tables):
    """Provide an async database session for tests."""
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session


def _make_user(**overrides) -> _TestUser:
    """Create a test user instance."""
    defaults = {
        "id": uuid.uuid4(),
        "username": "testuser",
        "email": "test@example.com",
        "password_hash": "hashed_password",
        "cf_handle": None,
        "cf_handle_verified": False,
        "cf_verification_code": None,
    }
    defaults.update(overrides)
    return _TestUser(**defaults)


def _cf_user_data(handle="tourist", **overrides) -> dict:
    """Return mock CF API user info response."""
    defaults = {
        "handle": handle,
        "rating": 3800,
        "maxRating": 3900,
        "avatar": "https://userpic.codeforces.org/photo.jpg",
        "rank": "legendary grandmaster",
        "maxRank": "legendary grandmaster",
        "titlePhoto": "https://userpic.codeforces.org/title.jpg",
        "organization": "",
        "firstName": "",
        "lastName": "",
    }
    defaults.update(overrides)
    return defaults


def _mock_cf_service(user_data_list=None, side_effect=None):
    """Create a mock CFApiService with configurable get_user_info."""
    svc = AsyncMock()
    if side_effect:
        svc.get_user_info = AsyncMock(side_effect=side_effect)
    elif user_data_list is not None:
        svc.get_user_info = AsyncMock(return_value=user_data_list)
    else:
        svc.get_user_info = AsyncMock(return_value=[_cf_user_data()])
    return svc


# ---------------------------------------------------------------------------
# Tests: _generate_verification_code
# ---------------------------------------------------------------------------


class TestGenerateVerificationCode:
    def test_length_default(self):
        from app.services.cf_handle_service import _generate_verification_code

        code = _generate_verification_code()
        assert len(code) == 8

    def test_length_custom(self):
        from app.services.cf_handle_service import _generate_verification_code

        code = _generate_verification_code(length=16)
        assert len(code) == 16

    def test_alphanumeric(self):
        from app.services.cf_handle_service import _generate_verification_code

        code = _generate_verification_code()
        assert code.isalnum()

    def test_uniqueness(self):
        from app.services.cf_handle_service import _generate_verification_code

        codes = {_generate_verification_code() for _ in range(50)}
        # Very unlikely to get duplicates with random 8-char codes
        assert len(codes) > 40


# ---------------------------------------------------------------------------
# Tests: _extract_cf_info
# ---------------------------------------------------------------------------


class TestExtractCfInfo:
    def test_full_data(self):
        from app.services.cf_handle_service import _extract_cf_info

        data = _cf_user_data()
        info = _extract_cf_info(data)
        assert info["handle"] == "tourist"
        assert info["rating"] == 3800
        assert info["max_rating"] == 3900
        assert info["avatar"] is not None
        assert info["rank"] == "legendary grandmaster"
        assert info["max_rank"] == "legendary grandmaster"
        assert info["title_photo"] is not None

    def test_missing_fields(self):
        from app.services.cf_handle_service import _extract_cf_info

        info = _extract_cf_info({"handle": "newbie"})
        assert info["handle"] == "newbie"
        assert info["rating"] is None
        assert info["max_rating"] is None
        assert info["avatar"] is None

    def test_empty_dict(self):
        from app.services.cf_handle_service import _extract_cf_info

        info = _extract_cf_info({})
        assert info["handle"] == ""
        assert info["rating"] is None


# ---------------------------------------------------------------------------
# Tests: bind_cf_handle
# ---------------------------------------------------------------------------


class TestBindCfHandle:
    @pytest.mark.asyncio
    async def test_happy_path(self, db_session):
        """Successful binding: CF API returns user info, no conflicts."""
        from app.services.cf_handle_service import bind_cf_handle

        user = _make_user()
        db_session.add(user)
        await db_session.commit()

        # Need to patch the User model used in bind_cf_handle's select query
        # to use our test model, since SQLite doesn't have UUID type
        cf_svc = _mock_cf_service([_cf_user_data("tourist")])

        with patch("app.services.cf_handle_service.User", _TestUser):
            result = await bind_cf_handle(db_session, user, "tourist", cf_svc)

        assert result["cf_handle"] == "tourist"
        assert result["verification_code"] is not None
        assert len(result["verification_code"]) == 8
        assert result["status"] == "pending_verification"
        assert result["cf_user_info"]["handle"] == "tourist"
        assert result["cf_user_info"]["rating"] == 3800

        # Verify DB state
        await db_session.refresh(user)
        assert user.cf_handle == "tourist"
        assert user.cf_handle_verified is False
        assert user.cf_verification_code == result["verification_code"]

    @pytest.mark.asyncio
    async def test_user_already_has_verified_handle(self, db_session):
        """Should raise BadRequestException if user already has a verified handle."""
        from app.services.cf_handle_service import bind_cf_handle

        user = _make_user(cf_handle="tourist", cf_handle_verified=True)
        db_session.add(user)
        await db_session.commit()

        cf_svc = _mock_cf_service()

        with patch("app.services.cf_handle_service.User", _TestUser):
            with pytest.raises(BadRequestException, match="already bound"):
                await bind_cf_handle(db_session, user, "new_handle", cf_svc)

    @pytest.mark.asyncio
    async def test_handle_already_bound_to_another_user(self, db_session):
        """Should raise ConflictException if handle is taken by another user."""
        from app.services.cf_handle_service import bind_cf_handle

        other_user = _make_user(
            id=uuid.uuid4(),
            username="other",
            email="other@example.com",
            cf_handle="tourist",
            cf_handle_verified=True,
        )
        current_user = _make_user(username="current", email="current@example.com")
        db_session.add_all([other_user, current_user])
        await db_session.commit()

        cf_svc = _mock_cf_service()

        with patch("app.services.cf_handle_service.User", _TestUser):
            with pytest.raises(ConflictException, match="already bound"):
                await bind_cf_handle(db_session, current_user, "tourist", cf_svc)

    @pytest.mark.asyncio
    async def test_handle_not_found_on_cf(self, db_session):
        """Should raise NotFoundException when CF says handle doesn't exist."""
        from app.services.cf_handle_service import bind_cf_handle

        user = _make_user()
        db_session.add(user)
        await db_session.commit()

        cf_svc = _mock_cf_service(side_effect=CFNotFoundError("not found"))

        with patch("app.services.cf_handle_service.User", _TestUser):
            with pytest.raises(NotFoundException, match="not found"):
                await bind_cf_handle(db_session, user, "nonexistent", cf_svc)

    @pytest.mark.asyncio
    async def test_cf_network_error(self, db_session):
        """Should raise BadRequestException on network errors."""
        from app.services.cf_handle_service import bind_cf_handle

        user = _make_user()
        db_session.add(user)
        await db_session.commit()

        cf_svc = _mock_cf_service(side_effect=CFNetworkError("timeout", detail="connection lost"))

        with patch("app.services.cf_handle_service.User", _TestUser):
            with pytest.raises(BadRequestException, match="Failed to verify"):
                await bind_cf_handle(db_session, user, "tourist", cf_svc)

    @pytest.mark.asyncio
    async def test_cf_rate_limit_error(self, db_session):
        """Should raise BadRequestException on rate limit errors."""
        from app.services.cf_handle_service import bind_cf_handle

        user = _make_user()
        db_session.add(user)
        await db_session.commit()

        cf_svc = _mock_cf_service(side_effect=CFRateLimitError("rate limited", detail="too many"))

        with patch("app.services.cf_handle_service.User", _TestUser):
            with pytest.raises(BadRequestException, match="Failed to verify"):
                await bind_cf_handle(db_session, user, "tourist", cf_svc)

    @pytest.mark.asyncio
    async def test_cf_generic_api_error(self, db_session):
        """Should raise BadRequestException on generic CF API errors."""
        from app.services.cf_handle_service import bind_cf_handle

        user = _make_user()
        db_session.add(user)
        await db_session.commit()

        cf_svc = _mock_cf_service(side_effect=CFAPIError("unknown error", detail="something"))

        with patch("app.services.cf_handle_service.User", _TestUser):
            with pytest.raises(BadRequestException, match="CF API error"):
                await bind_cf_handle(db_session, user, "tourist", cf_svc)

    @pytest.mark.asyncio
    async def test_cf_returns_empty_list(self, db_session):
        """Should raise NotFoundException when CF returns empty user list."""
        from app.services.cf_handle_service import bind_cf_handle

        user = _make_user()
        db_session.add(user)
        await db_session.commit()

        cf_svc = _mock_cf_service(user_data_list=[])

        with patch("app.services.cf_handle_service.User", _TestUser):
            with pytest.raises(NotFoundException, match="not found"):
                await bind_cf_handle(db_session, user, "ghost", cf_svc)

    @pytest.mark.asyncio
    async def test_same_user_can_rebind_same_handle(self, db_session):
        """If the same user already has the handle (unverified), re-binding should work."""
        from app.services.cf_handle_service import bind_cf_handle

        user = _make_user(cf_handle="tourist", cf_handle_verified=False, cf_verification_code="old_code")
        db_session.add(user)
        await db_session.commit()

        cf_svc = _mock_cf_service([_cf_user_data("tourist")])

        with patch("app.services.cf_handle_service.User", _TestUser):
            result = await bind_cf_handle(db_session, user, "tourist", cf_svc)

        assert result["status"] == "pending_verification"
        # New code should be generated
        await db_session.refresh(user)
        assert user.cf_verification_code != "old_code"


# ---------------------------------------------------------------------------
# Tests: verify_cf_handle
# ---------------------------------------------------------------------------


class TestVerifyCfHandle:
    @pytest.mark.asyncio
    async def test_happy_path_code_in_organization(self, db_session):
        """Verification succeeds when code is in the organization field."""
        from app.services.cf_handle_service import verify_cf_handle

        user = _make_user(
            cf_handle="tourist",
            cf_handle_verified=False,
            cf_verification_code="AbC12345",
        )
        db_session.add(user)
        await db_session.commit()

        cf_data = _cf_user_data("tourist", organization="AbC12345")
        cf_svc = _mock_cf_service([cf_data])

        result = await verify_cf_handle(db_session, user, "tourist", "AbC12345", cf_svc)

        assert result["verified"] is True
        assert result["status"] == "verified"
        assert result["cf_handle"] == "tourist"

        # DB should be updated
        await db_session.refresh(user)
        assert user.cf_handle_verified is True
        assert user.cf_verification_code is None

    @pytest.mark.asyncio
    async def test_happy_path_code_in_first_name(self, db_session):
        """Verification succeeds when code is in the firstName field."""
        from app.services.cf_handle_service import verify_cf_handle

        code = "XyZ99887"
        user = _make_user(cf_handle="tourist", cf_handle_verified=False, cf_verification_code=code)
        db_session.add(user)
        await db_session.commit()

        cf_data = _cf_user_data("tourist", firstName=code)
        cf_svc = _mock_cf_service([cf_data])

        result = await verify_cf_handle(db_session, user, "tourist", code, cf_svc)
        assert result["verified"] is True

    @pytest.mark.asyncio
    async def test_happy_path_code_in_last_name(self, db_session):
        """Verification succeeds when code is in the lastName field."""
        from app.services.cf_handle_service import verify_cf_handle

        code = "WwW12345"
        user = _make_user(cf_handle="tourist", cf_handle_verified=False, cf_verification_code=code)
        db_session.add(user)
        await db_session.commit()

        cf_data = _cf_user_data("tourist", lastName=code)
        cf_svc = _mock_cf_service([cf_data])

        result = await verify_cf_handle(db_session, user, "tourist", code, cf_svc)
        assert result["verified"] is True

    @pytest.mark.asyncio
    async def test_case_insensitive_code_match(self, db_session):
        """Verification code comparison should be case-insensitive."""
        from app.services.cf_handle_service import verify_cf_handle

        user = _make_user(cf_handle="tourist", cf_handle_verified=False, cf_verification_code="ABC12345")
        db_session.add(user)
        await db_session.commit()

        cf_data = _cf_user_data("tourist", organization="abc12345")
        cf_svc = _mock_cf_service([cf_data])

        # Code in DB is uppercase, code provided is uppercase, org has lowercase
        result = await verify_cf_handle(db_session, user, "tourist", "ABC12345", cf_svc)
        assert result["verified"] is True

    @pytest.mark.asyncio
    async def test_code_embedded_in_organization_text(self, db_session):
        """Code just needs to be a substring of the searchable text."""
        from app.services.cf_handle_service import verify_cf_handle

        code = "MyCode99"
        user = _make_user(cf_handle="tourist", cf_handle_verified=False, cf_verification_code=code)
        db_session.add(user)
        await db_session.commit()

        cf_data = _cf_user_data("tourist", organization=f"Some Org {code} Inc.")
        cf_svc = _mock_cf_service([cf_data])

        result = await verify_cf_handle(db_session, user, "tourist", code, cf_svc)
        assert result["verified"] is True

    @pytest.mark.asyncio
    async def test_no_pending_binding(self, db_session):
        """Should raise BadRequestException if user has no CF handle."""
        from app.services.cf_handle_service import verify_cf_handle

        user = _make_user(cf_handle=None)
        db_session.add(user)
        await db_session.commit()

        cf_svc = _mock_cf_service()

        with pytest.raises(BadRequestException, match="No CF Handle binding pending"):
            await verify_cf_handle(db_session, user, "tourist", "code", cf_svc)

    @pytest.mark.asyncio
    async def test_handle_mismatch(self, db_session):
        """Should raise BadRequestException if handle doesn't match."""
        from app.services.cf_handle_service import verify_cf_handle

        user = _make_user(cf_handle="tourist", cf_handle_verified=False, cf_verification_code="code1234")
        db_session.add(user)
        await db_session.commit()

        cf_svc = _mock_cf_service()

        with pytest.raises(BadRequestException, match="does not match"):
            await verify_cf_handle(db_session, user, "petr", "code1234", cf_svc)

    @pytest.mark.asyncio
    async def test_already_verified(self, db_session):
        """Should raise BadRequestException if handle is already verified."""
        from app.services.cf_handle_service import verify_cf_handle

        user = _make_user(cf_handle="tourist", cf_handle_verified=True)
        db_session.add(user)
        await db_session.commit()

        cf_svc = _mock_cf_service()

        with pytest.raises(BadRequestException, match="already verified"):
            await verify_cf_handle(db_session, user, "tourist", "code", cf_svc)

    @pytest.mark.asyncio
    async def test_no_verification_code_in_db(self, db_session):
        """Should raise BadRequestException if verification code is null in DB."""
        from app.services.cf_handle_service import verify_cf_handle

        user = _make_user(cf_handle="tourist", cf_handle_verified=False, cf_verification_code=None)
        db_session.add(user)
        await db_session.commit()

        cf_svc = _mock_cf_service()

        with pytest.raises(BadRequestException, match="No verification code found"):
            await verify_cf_handle(db_session, user, "tourist", "some_code", cf_svc)

    @pytest.mark.asyncio
    async def test_wrong_code(self, db_session):
        """Should raise BadRequestException if the code doesn't match."""
        from app.services.cf_handle_service import verify_cf_handle

        user = _make_user(cf_handle="tourist", cf_handle_verified=False, cf_verification_code="Correct1")
        db_session.add(user)
        await db_session.commit()

        cf_svc = _mock_cf_service()

        with pytest.raises(BadRequestException, match="does not match"):
            await verify_cf_handle(db_session, user, "tourist", "WrongCode", cf_svc)

    @pytest.mark.asyncio
    async def test_code_not_found_in_profile(self, db_session):
        """Should raise BadRequestException if code isn't in CF profile fields."""
        from app.services.cf_handle_service import verify_cf_handle

        code = "SearchMe"
        user = _make_user(cf_handle="tourist", cf_handle_verified=False, cf_verification_code=code)
        db_session.add(user)
        await db_session.commit()

        cf_data = _cf_user_data("tourist", organization="Some Other Text", firstName="John", lastName="Doe")
        cf_svc = _mock_cf_service([cf_data])

        with pytest.raises(BadRequestException, match="not found in CF profile"):
            await verify_cf_handle(db_session, user, "tourist", code, cf_svc)

    @pytest.mark.asyncio
    async def test_cf_api_not_found_during_verify(self, db_session):
        """Should raise NotFoundException if CF handle disappeared during verify."""
        from app.services.cf_handle_service import verify_cf_handle

        code = "AbC12345"
        user = _make_user(cf_handle="tourist", cf_handle_verified=False, cf_verification_code=code)
        db_session.add(user)
        await db_session.commit()

        cf_svc = _mock_cf_service(side_effect=CFNotFoundError("not found"))

        with pytest.raises(NotFoundException, match="not found"):
            await verify_cf_handle(db_session, user, "tourist", code, cf_svc)

    @pytest.mark.asyncio
    async def test_cf_api_network_error_during_verify(self, db_session):
        """Should raise BadRequestException on network error during verify."""
        from app.services.cf_handle_service import verify_cf_handle

        code = "AbC12345"
        user = _make_user(cf_handle="tourist", cf_handle_verified=False, cf_verification_code=code)
        db_session.add(user)
        await db_session.commit()

        cf_svc = _mock_cf_service(side_effect=CFNetworkError("timeout", detail="network"))

        with pytest.raises(BadRequestException, match="Failed to fetch"):
            await verify_cf_handle(db_session, user, "tourist", code, cf_svc)

    @pytest.mark.asyncio
    async def test_cf_api_rate_limit_during_verify(self, db_session):
        """Should raise BadRequestException on rate limit during verify."""
        from app.services.cf_handle_service import verify_cf_handle

        code = "AbC12345"
        user = _make_user(cf_handle="tourist", cf_handle_verified=False, cf_verification_code=code)
        db_session.add(user)
        await db_session.commit()

        cf_svc = _mock_cf_service(side_effect=CFRateLimitError("rate limit", detail="too many"))

        with pytest.raises(BadRequestException, match="Failed to fetch"):
            await verify_cf_handle(db_session, user, "tourist", code, cf_svc)

    @pytest.mark.asyncio
    async def test_cf_api_generic_error_during_verify(self, db_session):
        """Should raise BadRequestException on generic CF API error during verify."""
        from app.services.cf_handle_service import verify_cf_handle

        code = "AbC12345"
        user = _make_user(cf_handle="tourist", cf_handle_verified=False, cf_verification_code=code)
        db_session.add(user)
        await db_session.commit()

        cf_svc = _mock_cf_service(side_effect=CFAPIError("broken", detail="something"))

        with pytest.raises(BadRequestException, match="CF API error"):
            await verify_cf_handle(db_session, user, "tourist", code, cf_svc)

    @pytest.mark.asyncio
    async def test_cf_returns_empty_list_during_verify(self, db_session):
        """Should raise NotFoundException when CF returns empty list during verify."""
        from app.services.cf_handle_service import verify_cf_handle

        code = "AbC12345"
        user = _make_user(cf_handle="tourist", cf_handle_verified=False, cf_verification_code=code)
        db_session.add(user)
        await db_session.commit()

        cf_svc = _mock_cf_service(user_data_list=[])

        with pytest.raises(NotFoundException, match="not found"):
            await verify_cf_handle(db_session, user, "tourist", code, cf_svc)


# ---------------------------------------------------------------------------
# Tests: get_cf_handle_info
# ---------------------------------------------------------------------------


class TestGetCfHandleInfo:
    @pytest.mark.asyncio
    async def test_happy_path(self):
        """Returns CF user info for a valid handle."""
        from app.services.cf_handle_service import get_cf_handle_info

        cf_data = _cf_user_data("tourist")
        cf_svc = _mock_cf_service([cf_data])

        result = await get_cf_handle_info("tourist", cf_svc)
        assert result["handle"] == "tourist"
        assert result["rating"] == 3800

    @pytest.mark.asyncio
    async def test_not_found_error(self):
        """Raises NotFoundException when handle doesn't exist."""
        from app.services.cf_handle_service import get_cf_handle_info

        cf_svc = _mock_cf_service(side_effect=CFNotFoundError("not found"))

        with pytest.raises(NotFoundException, match="not found"):
            await get_cf_handle_info("nonexistent", cf_svc)

    @pytest.mark.asyncio
    async def test_network_error(self):
        """Raises BadRequestException on network error."""
        from app.services.cf_handle_service import get_cf_handle_info

        cf_svc = _mock_cf_service(side_effect=CFNetworkError("timeout", detail="network"))

        with pytest.raises(BadRequestException, match="Failed to fetch"):
            await get_cf_handle_info("tourist", cf_svc)

    @pytest.mark.asyncio
    async def test_rate_limit_error(self):
        """Raises BadRequestException on rate limit error."""
        from app.services.cf_handle_service import get_cf_handle_info

        cf_svc = _mock_cf_service(side_effect=CFRateLimitError("rate limit", detail="too many"))

        with pytest.raises(BadRequestException, match="Failed to fetch"):
            await get_cf_handle_info("tourist", cf_svc)

    @pytest.mark.asyncio
    async def test_generic_api_error(self):
        """Raises BadRequestException on generic CF API error."""
        from app.services.cf_handle_service import get_cf_handle_info

        cf_svc = _mock_cf_service(side_effect=CFAPIError("broken", detail="something"))

        with pytest.raises(BadRequestException, match="CF API error"):
            await get_cf_handle_info("tourist", cf_svc)

    @pytest.mark.asyncio
    async def test_cf_returns_empty_list(self):
        """Raises NotFoundException when CF returns empty list."""
        from app.services.cf_handle_service import get_cf_handle_info

        cf_svc = _mock_cf_service(user_data_list=[])

        with pytest.raises(NotFoundException, match="not found"):
            await get_cf_handle_info("tourist", cf_svc)


# ---------------------------------------------------------------------------
# Tests: unbind_cf_handle
# ---------------------------------------------------------------------------


class TestUnbindCfHandle:
    @pytest.mark.asyncio
    async def test_happy_path(self, db_session):
        """Successfully unbinds a CF handle."""
        from app.services.cf_handle_service import unbind_cf_handle

        user = _make_user(cf_handle="tourist", cf_handle_verified=True, cf_verification_code="old_code")
        db_session.add(user)
        await db_session.commit()

        result = await unbind_cf_handle(db_session, user)

        assert result["unbound"] == "tourist"
        await db_session.refresh(user)
        assert user.cf_handle is None
        assert user.cf_handle_verified is False
        assert user.cf_verification_code is None

    @pytest.mark.asyncio
    async def test_unbind_unverified_handle(self, db_session):
        """Can unbind even if handle was not yet verified."""
        from app.services.cf_handle_service import unbind_cf_handle

        user = _make_user(cf_handle="tourist", cf_handle_verified=False, cf_verification_code="pending_code")
        db_session.add(user)
        await db_session.commit()

        result = await unbind_cf_handle(db_session, user)

        assert result["unbound"] == "tourist"
        await db_session.refresh(user)
        assert user.cf_handle is None
        assert user.cf_verification_code is None

    @pytest.mark.asyncio
    async def test_no_handle_bound(self, db_session):
        """Should raise BadRequestException when no handle is bound."""
        from app.services.cf_handle_service import unbind_cf_handle

        user = _make_user(cf_handle=None)
        db_session.add(user)
        await db_session.commit()

        with pytest.raises(BadRequestException, match="No CF Handle bound"):
            await unbind_cf_handle(db_session, user)
