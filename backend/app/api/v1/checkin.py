"""Check-in API routes.

Mounts four endpoints under ``/api/v1/checkin/``:
  POST /            -- daily check-in
  POST /makeup      -- make-up check-in (for yesterday)
  GET  /status      -- get check-in status
  GET  /history     -- get check-in history (paginated)
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import success_response
from app.core.security import get_current_user
from app.models.user import User
from app.services.checkin_service import (
    check_in,
    get_history,
    get_status,
    makeup_checkin,
)

router = APIRouter(prefix="/checkin", tags=["Check-in"])


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("")
async def daily_checkin(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Perform a daily check-in. Awards tokens based on streak length."""
    result = await check_in(db=db, user=current_user)
    return success_response(
        data=result.model_dump(mode="json"),
        message="Check-in successful",
    )


@router.post("/makeup")
async def makeup_checkin_endpoint(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Perform a make-up check-in for yesterday (weekly limit: 2)."""
    result = await makeup_checkin(db=db, user=current_user)
    return success_response(
        data=result.model_dump(mode="json"),
        message="Make-up check-in successful",
    )


@router.get("/status")
async def checkin_status(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get current check-in status: streak, today's status, make-up quota."""
    result = await get_status(db=db, user=current_user)
    return success_response(
        data=result.model_dump(mode="json"),
        message="Check-in status retrieved",
    )


@router.get("/history")
async def checkin_history(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=30, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    """Get paginated check-in history."""
    result = await get_history(db=db, user=current_user, limit=limit, offset=offset)
    return success_response(
        data=result.model_dump(mode="json"),
        message="Check-in history retrieved",
    )
