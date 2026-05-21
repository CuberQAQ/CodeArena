"""Authentication API routes.

Mounts endpoints under ``/api/v1/auth/``:
  POST /register   -- create account
  POST /login      -- obtain token pair
  POST /refresh    -- rotate access token
  GET  /me         -- current user profile (auth required)
  PUT  /profile    -- update username / email (auth required)
  POST /avatar     -- upload avatar image (auth required)
  GET  /avatar/{user_id} -- serve avatar image (public)
  GET  /settings   -- get user settings (auth required)
  PUT  /settings   -- update user settings (auth required)
  GET  /pp-rank    -- get user PP ranking and percentile (auth required)
"""

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.exceptions import NotFoundException
from app.core.response import success_response
from app.core.security import get_current_user
from app.models.elo_history import EloHistory
from app.models.pp_record import PPRecord
from app.models.user import User
from app.models.user_settings import UserSettings
from app.schemas.auth import (
    LoginRequest,
    RefreshRequest,
    RefreshResponse,
    RegisterRequest,
    TokenResponse,
    UpdateProfileRequest,
    UserInfo,
)
from app.schemas.medal import UpdateSettingsRequest, UserSettingsResponse
from app.services import auth_service, avatar_service

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


@router.post("/avatar")
async def upload_avatar(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    file: UploadFile = File(...),
):
    """Upload or replace the authenticated user's avatar image.

    Accepts JPG/PNG images up to 2 MB. The image is automatically cropped
    to a square and saved as JPG.
    """
    file_content = await file.read()
    content_type = file.content_type or ""

    avatar_path = await avatar_service.upload_avatar(
        db=db,
        user_id=current_user.id,
        file_content=file_content,
        content_type=content_type,
    )

    return success_response(
        data={"avatar_path": avatar_path},
        message="Avatar uploaded successfully",
    )


@router.get("/avatar/{user_id}")
async def get_avatar(
    user_id: str,
):
    """Serve a user's avatar image.

    Returns the avatar JPG file if it exists, otherwise raises 404.
    This endpoint is public (no auth required) so avatars can be
    displayed on leaderboards and contest pages.
    """
    avatar_path = avatar_service.get_avatar_path(user_id)
    if avatar_path is None:
        raise NotFoundException(message="Avatar not found")

    return FileResponse(
        path=str(avatar_path),
        media_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@router.get("/elo-history")
async def get_elo_history(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the authenticated user's Elo rating history."""
    result = await db.execute(
        select(EloHistory).where(EloHistory.user_id == current_user.id).order_by(EloHistory.created_at.asc())
    )
    records = result.scalars().all()
    return success_response(
        data=[
            {
                "date": r.created_at.isoformat(),
                "elo": r.elo_after,
                "change": r.elo_change,
                "reason": r.reason,
            }
            for r in records
        ],
    )


@router.get("/leaderboard")
async def get_global_leaderboard(
    limit: int = 100,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the global leaderboard of all users."""
    stmt = (
        select(
            User.id,
            User.username,
            User.cf_handle,
            User.elo,
            User.pp,
            User.tokens,
            UserSettings.avatar_path,
        )
        .outerjoin(UserSettings, UserSettings.user_id == User.id)
        .where(User.is_active.is_(True))
        .order_by(User.elo.desc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    users = result.fetchall()

    leaderboard = []
    for i, user in enumerate(users, 1):
        leaderboard.append(
            {
                "id": str(user.id),
                "username": user.username,
                "cf_handle": user.cf_handle,
                "elo": user.elo,
                "pp": user.pp,
                "tokens": user.tokens,
                "rank": i,
                "avatar_path": user.avatar_path,
            }
        )

    return success_response(
        data=leaderboard,
        message="Leaderboard retrieved",
    )


@router.get("/pp-contributions")
async def get_pp_contributions(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = 20,
):
    """Return the authenticated user's top PP contributions."""
    result = await db.execute(
        select(PPRecord).where(PPRecord.user_id == current_user.id).order_by(PPRecord.base_pp.desc()).limit(limit)
    )
    records = result.scalars().all()
    return success_response(
        data=[
            {
                "problem_id": r.cf_problem_id,
                "problem_name": r.cf_problem_id,
                "rating": r.problem_rating,
                "pp": r.base_pp,
            }
            for r in records
        ],
    )


@router.get("/pp-rank")
async def get_pp_rank(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the authenticated user's PP global ranking and percentile.

    Calculates rank by counting users with higher PP, then derives percentile.
    Users with PP == 0 are considered unranked.
    """
    user_pp = current_user.pp or 0

    # Count total active users
    total_result = await db.execute(select(func.count(User.id)).where(User.is_active.is_(True)))
    total_users = total_result.scalar() or 0

    if total_users == 0 or user_pp <= 0:
        return success_response(
            data={
                "rank": None,
                "total_users": total_users,
                "top_percent": None,
            },
            message="PP rank retrieved",
        )

    # Count users with strictly higher PP (same PP broken by earlier creation)
    higher_result = await db.execute(
        select(func.count(User.id)).where(
            User.is_active.is_(True),
            ((User.pp > user_pp) | ((User.pp == user_pp) & (User.created_at < current_user.created_at))),
        )
    )
    higher_count = higher_result.scalar() or 0
    rank = higher_count + 1

    # Top percent: what percentage of the leaderboard the user occupies from the top
    top_percent = round(rank / total_users * 100, 1)

    return success_response(
        data={
            "rank": rank,
            "total_users": total_users,
            "top_percent": top_percent,
        },
        message="PP rank retrieved",
    )


@router.get("/settings")
async def get_settings(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the authenticated user's display settings.

    Creates default settings if none exist yet.
    """
    stmt = select(UserSettings).where(UserSettings.user_id == current_user.id)
    result = await db.execute(stmt)
    settings = result.scalar_one_or_none()

    if settings is None:
        # Create default settings
        settings = UserSettings(
            user_id=current_user.id,
            display_mode="medal",
        )
        db.add(settings)
        await db.flush()

    return success_response(
        data=UserSettingsResponse.model_validate(settings).model_dump(mode="json"),
        message="Settings retrieved",
    )


@router.put("/settings")
async def update_settings(
    body: UpdateSettingsRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update the authenticated user's display settings."""
    stmt = select(UserSettings).where(UserSettings.user_id == current_user.id)
    result = await db.execute(stmt)
    settings = result.scalar_one_or_none()

    if settings is None:
        # Create settings with provided values
        settings = UserSettings(
            user_id=current_user.id,
            display_mode=body.display_mode or "medal",
            avatar_path=body.avatar_path,
        )
        db.add(settings)
    else:
        # Update only provided fields
        if body.display_mode is not None:
            if body.display_mode not in ("medal", "cf_tier"):
                from app.core.exceptions import BadRequestException

                raise BadRequestException(message="display_mode must be 'medal' or 'cf_tier'")
            settings.display_mode = body.display_mode
        if body.avatar_path is not None:
            settings.avatar_path = body.avatar_path

    await db.flush()

    return success_response(
        data=UserSettingsResponse.model_validate(settings).model_dump(mode="json"),
        message="Settings updated",
    )
