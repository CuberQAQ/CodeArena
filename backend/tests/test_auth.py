"""Tests for the authentication system (registration, login, token refresh, profile).

Uses an in-memory SQLite database with lightweight test models to avoid
PostgreSQL-specific features (UUID server_default, JSONB, etc.) that
are incompatible with SQLite.
"""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from sqlalchemy import Boolean, DateTime, Float, Integer, String, event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core.exceptions import BadRequestException, ConflictException, UnauthorizedException
from app.schemas.auth import UpdateProfileRequest
from app.services import auth_service

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
    cf_handle_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    cf_verification_code: Mapped[str | None] = mapped_column(String(8), nullable=True)
    elo: Mapped[int] = mapped_column(Integer, default=1200, nullable=False)
    pp: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    daily_tokens_earned: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    daily_tokens_reset_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


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
    """Provide an async session that uses test-compatible models.

    The auth_service functions reference the production User model via
    SQLAlchemy queries.  We patch the User model reference inside
    auth_service so queries hit our SQLite-compatible _TestUser instead.
    """
    session_factory = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as session:
        with patch.object(auth_service, "User", _TestUser):
            yield session


@pytest.fixture
def sample_password() -> str:
    """A password that passes all strength requirements."""
    return "TestPass123"


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


async def _insert_user(
    db: AsyncSession,
    username: str = "testuser",
    email: str = "test@example.com",
    password: str = "TestPass123",
    is_active: bool = True,
) -> _TestUser:
    """Insert a user directly and return the ORM instance."""
    from app.core.security import hash_password

    user = _TestUser(
        username=username,
        email=email,
        password_hash=hash_password(password),
        is_active=is_active,
    )
    db.add(user)
    await db.flush()
    return user


# ===========================================================================
# 1. Registration
# ===========================================================================


class TestRegister:
    async def test_register_success(self, db, sample_password):
        user = await auth_service.register_user(db, "newuser", "new@example.com", sample_password)
        assert user.username == "newuser"
        assert user.email == "new@example.com"
        assert user.elo == 1200
        assert user.pp == 0.0
        assert user.tokens == 0
        assert user.password_hash != sample_password

    async def test_password_is_bcrypt_hashed(self, db, sample_password):
        user = await auth_service.register_user(db, "hashcheck", "hash@example.com", sample_password)
        assert user.password_hash.startswith("$2b$")
        assert user.password_hash != sample_password

    async def test_duplicate_username_rejected(self, db, sample_password):
        await auth_service.register_user(db, "dupuser", "first@example.com", sample_password)
        with pytest.raises(ConflictException, match="Username already registered"):
            await auth_service.register_user(db, "dupuser", "second@example.com", sample_password)

    async def test_duplicate_email_rejected(self, db, sample_password):
        await auth_service.register_user(db, "user_a", "dup@example.com", sample_password)
        with pytest.raises(ConflictException, match="Email already registered"):
            await auth_service.register_user(db, "user_b", "dup@example.com", sample_password)


# ===========================================================================
# 2. Login / Authentication
# ===========================================================================


class TestAuthenticate:
    async def test_login_success(self, db, sample_password):
        await _insert_user(db, "loginuser", "login@example.com", sample_password)
        user = await auth_service.authenticate_user(db, "login@example.com", sample_password)
        assert user.username == "loginuser"

    async def test_last_login_updated(self, db, sample_password):
        await _insert_user(db, "logintime", "logintime@example.com", sample_password)
        before = datetime.now(UTC)
        user = await auth_service.authenticate_user(db, "logintime@example.com", sample_password)
        assert user.last_login_at is not None
        assert user.last_login_at >= before

    async def test_wrong_password_rejected(self, db, sample_password):
        await _insert_user(db, "wrongpw", "wrongpw@example.com", sample_password)
        with pytest.raises(UnauthorizedException, match="Invalid credentials"):
            await auth_service.authenticate_user(db, "wrongpw@example.com", "WrongPass999")

    async def test_nonexistent_email_rejected(self, db, sample_password):
        with pytest.raises(UnauthorizedException, match="Invalid credentials"):
            await auth_service.authenticate_user(db, "nobody@example.com", sample_password)

    async def test_inactive_user_rejected(self, db, sample_password):
        await _insert_user(db, "inactive", "inactive@example.com", sample_password, is_active=False)
        with pytest.raises(UnauthorizedException, match="Invalid credentials"):
            await auth_service.authenticate_user(db, "inactive@example.com", sample_password)

    async def test_error_message_does_not_reveal_existence(self, db, sample_password):
        """Both wrong-password and non-existent-email produce the same message."""
        await _insert_user(db, "reveal", "reveal@example.com", sample_password)
        with pytest.raises(UnauthorizedException) as exc_info_wrong:
            await auth_service.authenticate_user(db, "reveal@example.com", "WrongPass999")
        with pytest.raises(UnauthorizedException) as exc_info_missing:
            await auth_service.authenticate_user(db, "missing@example.com", sample_password)
        assert exc_info_wrong.value.message == exc_info_missing.value.message


# ===========================================================================
# 3. Token generation and refresh
# ===========================================================================


class TestTokenGeneration:
    def test_generate_token_pair_structure(self, sample_password):
        """generate_token_pair returns both tokens."""
        user = _TestUser(
            id=uuid.uuid4(),
            username="tokenuser",
            email="token@example.com",
            password_hash="x",
        )
        result = auth_service.generate_token_pair(user)
        assert "access_token" in result
        assert "refresh_token" in result

    def test_access_and_refresh_are_different(self, sample_password):
        user = _TestUser(
            id=uuid.uuid4(),
            username="difftoken",
            email="diff@example.com",
            password_hash="x",
        )
        result = auth_service.generate_token_pair(user)
        assert result["access_token"] != result["refresh_token"]


class TestRefreshAccessToken:
    async def test_refresh_success(self, db, sample_password):
        from app.core.security import decode_token

        user = await _insert_user(db, "refreshuser", "refresh@example.com", sample_password)
        tokens = auth_service.generate_token_pair(user)
        result = await auth_service.refresh_access_token(tokens["refresh_token"])
        assert "access_token" in result
        # The new access token must be a valid JWT with the correct subject and type
        payload = decode_token(result["access_token"])
        assert payload["sub"] == str(user.id)
        assert payload["type"] == "access"

    async def test_refresh_with_access_token_rejected(self, db, sample_password):
        user = await _insert_user(db, "wrongtype", "wrongtype@example.com", sample_password)
        tokens = auth_service.generate_token_pair(user)
        with pytest.raises(UnauthorizedException, match="Invalid token type"):
            await auth_service.refresh_access_token(tokens["access_token"])

    async def test_refresh_with_garbage_token_rejected(self):
        with pytest.raises(UnauthorizedException):
            await auth_service.refresh_access_token("not.a.real.token")

    async def test_refresh_with_expired_token_rejected(self):
        """An expired refresh token should be rejected."""
        from jose import jwt

        from app.core.config import settings

        expired_payload = {
            "sub": str(uuid.uuid4()),
            "exp": datetime.now(UTC) - timedelta(hours=1),
            "type": "refresh",
        }
        expired_token = jwt.encode(expired_payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
        with pytest.raises(UnauthorizedException):
            await auth_service.refresh_access_token(expired_token)


# ===========================================================================
# 4. Profile retrieval
# ===========================================================================


class TestGetUserProfile:
    async def test_returns_same_user(self, db, sample_password):
        user = await _insert_user(db, "profileuser", "profile@example.com", sample_password)
        result = await auth_service.get_user_profile(user)
        assert result.id == user.id


# ===========================================================================
# 5. Profile update
# ===========================================================================


class TestUpdateProfile:
    async def test_update_username(self, db, sample_password):
        user = await _insert_user(db, "oldname", "updatename@example.com", sample_password)
        data = UpdateProfileRequest(username="newname")
        updated = await auth_service.update_user_profile(db, user, data)
        assert updated.username == "newname"

    async def test_update_email(self, db, sample_password):
        user = await _insert_user(db, "updatemail", "old@example.com", sample_password)
        data = UpdateProfileRequest(email="new@example.com")
        updated = await auth_service.update_user_profile(db, user, data)
        assert updated.email == "new@example.com"

    async def test_update_both(self, db, sample_password):
        user = await _insert_user(db, "bothold", "bothold@example.com", sample_password)
        data = UpdateProfileRequest(username="bothnew", email="bothnew@example.com")
        updated = await auth_service.update_user_profile(db, user, data)
        assert updated.username == "bothnew"
        assert updated.email == "bothnew@example.com"

    async def test_no_fields_raises(self, db, sample_password):
        user = await _insert_user(db, "nofield", "nofield@example.com", sample_password)
        data = UpdateProfileRequest()
        with pytest.raises(BadRequestException, match="No fields to update"):
            await auth_service.update_user_profile(db, user, data)

    async def test_duplicate_username_rejected(self, db, sample_password):
        await _insert_user(db, "takenname", "taken@example.com", sample_password)
        user2 = await _insert_user(db, "original", "original@example.com", sample_password)
        data = UpdateProfileRequest(username="takenname")
        with pytest.raises(ConflictException, match="Username already taken"):
            await auth_service.update_user_profile(db, user2, data)

    async def test_duplicate_email_rejected(self, db, sample_password):
        await _insert_user(db, "takenuser", "taken@example.com", sample_password)
        user2 = await _insert_user(db, "seconduser", "second@example.com", sample_password)
        data = UpdateProfileRequest(email="taken@example.com")
        with pytest.raises(ConflictException, match="Email already taken"):
            await auth_service.update_user_profile(db, user2, data)

    async def test_same_username_no_conflict(self, db, sample_password):
        """Setting username to its current value should not raise."""
        user = await _insert_user(db, "sameuser", "same@example.com", sample_password)
        data = UpdateProfileRequest(username="sameuser")
        updated = await auth_service.update_user_profile(db, user, data)
        assert updated.username == "sameuser"

    async def test_same_email_no_conflict(self, db, sample_password):
        """Setting email to its current value should not raise."""
        user = await _insert_user(db, "sameemail", "sameemail@example.com", sample_password)
        data = UpdateProfileRequest(email="sameemail@example.com")
        updated = await auth_service.update_user_profile(db, user, data)
        assert updated.email == "sameemail@example.com"


# ===========================================================================
# 6. Schema validation (Pydantic)
# ===========================================================================


class TestRegisterRequestValidation:
    def test_valid_payload(self):
        from app.schemas.auth import RegisterRequest

        req = RegisterRequest(username="test_user", email="a@b.com", password="TestPass1")
        assert req.username == "test_user"

    def test_username_too_short(self):
        from pydantic import ValidationError

        from app.schemas.auth import RegisterRequest

        with pytest.raises(ValidationError):
            RegisterRequest(username="ab", email="a@b.com", password="TestPass1")

    def test_username_too_long(self):
        from pydantic import ValidationError

        from app.schemas.auth import RegisterRequest

        with pytest.raises(ValidationError):
            RegisterRequest(username="a" * 51, email="a@b.com", password="TestPass1")

    def test_username_invalid_chars(self):
        from pydantic import ValidationError

        from app.schemas.auth import RegisterRequest

        with pytest.raises(ValidationError):
            RegisterRequest(username="bad user!", email="a@b.com", password="TestPass1")

    def test_password_too_short(self):
        from pydantic import ValidationError

        from app.schemas.auth import RegisterRequest

        with pytest.raises(ValidationError):
            RegisterRequest(username="validuser", email="a@b.com", password="Sh1")

    def test_password_no_uppercase(self):
        from pydantic import ValidationError

        from app.schemas.auth import RegisterRequest

        with pytest.raises(ValidationError):
            RegisterRequest(username="validuser", email="a@b.com", password="alllowercase1")

    def test_password_no_lowercase(self):
        from pydantic import ValidationError

        from app.schemas.auth import RegisterRequest

        with pytest.raises(ValidationError):
            RegisterRequest(username="validuser", email="a@b.com", password="ALLUPPERCASE1")

    def test_password_no_digit(self):
        from pydantic import ValidationError

        from app.schemas.auth import RegisterRequest

        with pytest.raises(ValidationError):
            RegisterRequest(username="validuser", email="a@b.com", password="NoDigitsHere")

    def test_invalid_email(self):
        from pydantic import ValidationError

        from app.schemas.auth import RegisterRequest

        with pytest.raises(ValidationError):
            RegisterRequest(username="validuser", email="not-an-email", password="TestPass1")


class TestUpdateProfileRequestValidation:
    def test_username_invalid_chars(self):
        from pydantic import ValidationError

        from app.schemas.auth import UpdateProfileRequest

        with pytest.raises(ValidationError):
            UpdateProfileRequest(username="bad name!")

    def test_empty_body_is_valid(self):
        """Both fields are optional; an empty body is allowed by Pydantic."""
        from app.schemas.auth import UpdateProfileRequest

        req = UpdateProfileRequest()
        assert req.username is None
        assert req.email is None


# ===========================================================================
# 7. Integration: decode_token returns expected claims
# ===========================================================================


class TestTokenDecode:
    def test_access_token_claims(self):
        from app.core.security import create_access_token, decode_token

        user_id = uuid.uuid4()
        token = create_access_token(user_id)
        payload = decode_token(token)
        assert payload["sub"] == str(user_id)
        assert payload["type"] == "access"
        assert "exp" in payload

    def test_refresh_token_claims(self):
        from app.core.security import create_refresh_token, decode_token

        user_id = uuid.uuid4()
        token = create_refresh_token(user_id)
        payload = decode_token(token)
        assert payload["sub"] == str(user_id)
        assert payload["type"] == "refresh"
        assert "exp" in payload
