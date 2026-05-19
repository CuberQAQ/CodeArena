"""Pydantic schemas for authentication request/response validation."""

import re
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, field_validator

# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class RegisterRequest(BaseModel):
    """Request body for user registration."""

    username: str = Field(
        min_length=3,
        max_length=50,
        description="Username, 3-50 characters, alphanumeric and underscores only",
    )
    email: EmailStr = Field(description="Valid email address")
    password: str = Field(
        min_length=8,
        description="Password, at least 8 characters with uppercase, lowercase, and digit",
    )

    @field_validator("username")
    @classmethod
    def username_format(cls, v: str) -> str:
        if not re.match(r"^[a-zA-Z0-9_]+$", v):
            raise ValueError("Username must contain only letters, digits, and underscores")
        return v

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if not re.search(r"[A-Z]", v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not re.search(r"[a-z]", v):
            raise ValueError("Password must contain at least one lowercase letter")
        if not re.search(r"\d", v):
            raise ValueError("Password must contain at least one digit")
        return v


class LoginRequest(BaseModel):
    """Request body for user login."""

    email: EmailStr = Field(description="Registered email address")
    password: str = Field(description="Account password")


class RefreshRequest(BaseModel):
    """Request body for token refresh."""

    refresh_token: str = Field(description="A valid JWT refresh token")


class UpdateProfileRequest(BaseModel):
    """Request body for profile update. All fields are optional."""

    username: str | None = Field(
        default=None,
        min_length=3,
        max_length=50,
        description="New username, 3-50 characters",
    )
    email: EmailStr | None = Field(default=None, description="New email address")

    @field_validator("username")
    @classmethod
    def username_format(cls, v: str | None) -> str | None:
        if v is not None and not re.match(r"^[a-zA-Z0-9_]+$", v):
            raise ValueError("Username must contain only letters, digits, and underscores")
        return v


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class UserInfo(BaseModel):
    """Public user information returned in API responses."""

    id: UUID
    username: str
    email: str
    cf_handle: str | None = None
    cf_handle_verified: bool = False
    elo: int = 1200
    pp: float = 0.0
    tokens: int = 0
    is_active: bool = True
    is_admin: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None
    last_login_at: datetime | None = None

    model_config = {"from_attributes": True}


class TokenResponse(BaseModel):
    """JWT token pair."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshResponse(BaseModel):
    """Response for token refresh (only a new access token)."""

    access_token: str
    token_type: str = "bearer"
