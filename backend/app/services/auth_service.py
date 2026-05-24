"""Authentication business logic.

Provides registration, login, token refresh, profile retrieval, and profile
update.  All functions receive an ``AsyncSession`` and are pure-logic helpers
that the route layer can call directly.
"""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestException, ConflictException, UnauthorizedException
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.models.user import User
from app.schemas.auth import UpdateProfileRequest


async def register_user(
    db: AsyncSession,
    username: str,
    email: str,
    password: str,
) -> User:
    """Create a new user account.

    Raises:
        ConflictException: If the username or email is already taken.
    """
    # Check uniqueness of username
    existing = await db.execute(select(User).where(User.username == username))
    if existing.scalar_one_or_none() is not None:
        raise ConflictException(message="Username already registered", detail="username")

    # Check uniqueness of email
    existing = await db.execute(select(User).where(User.email == email))
    if existing.scalar_one_or_none() is not None:
        raise ConflictException(message="Email already registered", detail="email")

    user = User(
        username=username,
        email=email,
        password_hash=hash_password(password),
        elo=1200,
        pp=0,
        tokens=0,
    )
    db.add(user)
    await db.flush()
    return user


async def authenticate_user(
    db: AsyncSession,
    email: str,
    password: str,
) -> User:
    """Verify credentials and return the user.

    Raises:
        UnauthorizedException: Always with "Invalid credentials" regardless of
            whether the email does not exist or the password is wrong.
    """
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if user is None or not verify_password(password, user.password_hash):
        raise UnauthorizedException(message="Invalid credentials")

    if not user.is_active:
        raise UnauthorizedException(message="Invalid credentials")

    # Record last login
    user.last_login_at = datetime.now(UTC)
    await db.flush()
    return user


def build_login_response(user: User, tokens: dict) -> dict:
    """Build the full login response dict including tokens and login_time.

    Args:
        user: The authenticated user.
        tokens: Dict from generate_token_pair with access_token and refresh_token.

    Returns:
        Dict suitable for API response data.
    """
    return {
        "access_token": tokens["access_token"],
        "refresh_token": tokens["refresh_token"],
        "token_type": "bearer",
        "login_time": datetime.now(UTC).isoformat(),
    }


def generate_token_pair(user: User) -> dict:
    """Return a dict with access_token and refresh_token for the given user."""
    return {
        "access_token": create_access_token(user.id),
        "refresh_token": create_refresh_token(user.id),
    }


async def refresh_access_token(refresh_token: str) -> dict:
    """Decode a refresh token and issue a new access token.

    Raises:
        UnauthorizedException: If the token is invalid, expired, or not a
            refresh-type token.
    """
    payload = decode_token(refresh_token)

    if payload.get("type") != "refresh":
        raise UnauthorizedException(message="Invalid token type", detail="Expected refresh token")

    user_id = payload.get("sub")
    if user_id is None:
        raise UnauthorizedException(message="Invalid token payload")

    return {
        "access_token": create_access_token(user_id),
    }


async def get_user_profile(user: User) -> User:
    """Return the current user.  Trivial helper kept for symmetry."""
    return user


async def update_user_profile(
    db: AsyncSession,
    user: User,
    data: UpdateProfileRequest,
) -> User:
    """Update the username and/or email of the given user.

    Raises:
        BadRequestException: If no fields are provided.
        ConflictException: If the new username or email is already taken.
    """
    if data.username is None and data.email is None:
        raise BadRequestException(message="No fields to update")

    if data.username is not None and data.username != user.username:
        existing = await db.execute(select(User).where(User.username == data.username))
        if existing.scalar_one_or_none() is not None:
            raise ConflictException(message="Username already taken", detail="username")
        user.username = data.username

    if data.email is not None and data.email != user.email:
        existing = await db.execute(select(User).where(User.email == data.email))
        if existing.scalar_one_or_none() is not None:
            raise ConflictException(message="Email already taken", detail="email")
        user.email = data.email

    await db.flush()
    await db.refresh(user)
    return user
