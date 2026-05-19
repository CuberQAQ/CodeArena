"""Authentication API routes.

Mounts five endpoints under ``/api/v1/auth/``:
  POST /register   -- create account
  POST /login      -- obtain token pair
  POST /refresh    -- rotate access token
  GET  /me         -- current user profile (auth required)
  PUT  /profile    -- update username / email (auth required)
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import success_response
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.auth import (
    LoginRequest,
    RefreshRequest,
    RefreshResponse,
    RegisterRequest,
    TokenResponse,
    UpdateProfileRequest,
    UserInfo,
)
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/register")
async def register(
    body: RegisterRequest,
    db: AsyncSession = Depends(get_db),
):
    """Register a new user account and return user info + JWT tokens."""
    user = await auth_service.register_user(
        db=db,
        username=body.username,
        email=body.email,
        password=body.password,
    )
    tokens = auth_service.generate_token_pair(user)
    return success_response(
        data={
            "user": UserInfo.model_validate(user).model_dump(mode="json"),
            "tokens": TokenResponse(**tokens).model_dump(),
        },
        message="Registration successful",
        status_code=201,
    )


@router.post("/login")
async def login(
    body: LoginRequest,
    db: AsyncSession = Depends(get_db),
):
    """Authenticate with email and password, return JWT token pair."""
    user = await auth_service.authenticate_user(
        db=db,
        email=body.email,
        password=body.password,
    )
    tokens = auth_service.generate_token_pair(user)
    return success_response(
        data=TokenResponse(**tokens).model_dump(),
        message="Login successful",
    )


@router.post("/refresh")
async def refresh_token(
    body: RefreshRequest,
):
    """Exchange a valid refresh token for a new access token."""
    result = await auth_service.refresh_access_token(body.refresh_token)
    return success_response(
        data=RefreshResponse(**result).model_dump(),
        message="Token refreshed",
    )


@router.get("/me")
async def get_me(
    current_user: User = Depends(get_current_user),
):
    """Return the authenticated user's full profile."""
    return success_response(
        data=UserInfo.model_validate(current_user).model_dump(mode="json"),
        message="User profile retrieved",
    )


@router.put("/profile")
async def update_profile(
    body: UpdateProfileRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update the authenticated user's username and/or email."""
    user = await auth_service.update_user_profile(
        db=db,
        user=current_user,
        data=body,
    )
    return success_response(
        data=UserInfo.model_validate(user).model_dump(mode="json"),
        message="Profile updated",
    )
