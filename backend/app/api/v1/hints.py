"""Hint API routes.

Mounts four endpoints under ``/api/v1/hints/``:
  GET  /{problem_id}/status         -- get hint status and pricing
  POST /{problem_id}/unlock         -- unlock a hint level
  GET  /{problem_id}/content/{level} -- get hint content for a level
  GET  /{problem_id}/history        -- get hint purchase history
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import success_response
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.hint import UnlockHintRequest
from app.services.hint_service import HintService

router = APIRouter(prefix="/hints", tags=["Hints"])


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/{problem_id}/status")
async def get_hint_status(
    problem_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    problem_rating: int = Query(default=1000, description="Problem difficulty rating"),
):
    """Get hint status for a problem: unlocked levels, prices, Elo decay preview."""
    result = await HintService.get_hint_status(
        db=db,
        user=current_user,
        problem_id=problem_id,
        problem_rating=problem_rating,
    )
    return success_response(
        data=result.model_dump(mode="json"),
        message="Hint status retrieved",
    )


@router.post("/{problem_id}/unlock")
async def unlock_hint(
    problem_id: str,
    body: UnlockHintRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    problem_rating: int = Query(default=1000, description="Problem difficulty rating"),
):
    """Unlock the next hint level for a problem."""
    result = await HintService.unlock_hint(
        db=db,
        user=current_user,
        problem_id=problem_id,
        problem_rating=problem_rating,
        level=body.level,
    )
    return success_response(
        data=result.model_dump(mode="json"),
        message=f"Hint level {body.level} unlocked",
    )


@router.get("/{problem_id}/content/{level}")
async def get_hint_content(
    problem_id: str,
    level: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    problem_rating: int = Query(default=1000, description="Problem difficulty rating"),
):
    """Get hint content for a specific level (must be unlocked)."""
    result = await HintService.get_hint_content(
        db=db,
        user=current_user,
        problem_id=problem_id,
        level=level,
        problem_rating=problem_rating,
    )
    return success_response(
        data=result.model_dump(mode="json"),
        message="Hint content retrieved",
    )


@router.get("/{problem_id}/history")
async def get_hint_history(
    problem_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the user's hint purchase history for a problem."""
    result = await HintService.get_hint_history(
        db=db,
        user=current_user,
        problem_id=problem_id,
    )
    return success_response(
        data=result.model_dump(mode="json"),
        message="Hint history retrieved",
    )
