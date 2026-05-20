"""PvE Challenge API routes.

Mounts five endpoints under ``/api/v1/pve-challenge/``:
  POST /start          -- start a random PvE challenge (auth required)
  GET  /{id}           -- get challenge detail (auth required)
  POST /{id}/submit    -- submit result (auth required)
  POST /{id}/quit      -- quit challenge (auth required)
  GET  /history        -- get paginated history (auth required)
"""

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import success_response
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.pve_challenge import PvEQuitRequest, PvESubmitResultRequest
from app.services.cf_api_service import CFApiService
from app.services.pve_challenge_service import PvEChallengeService

router = APIRouter(prefix="/pve-challenge", tags=["PvE Challenge"])


# ---------------------------------------------------------------------------
# Service singletons
# ---------------------------------------------------------------------------

_cf_service: CFApiService | None = None


def _get_cf_service() -> CFApiService:
    global _cf_service
    if _cf_service is None:
        _cf_service = CFApiService()
    return _cf_service


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/start")
async def start_challenge(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Start a new PvE challenge with a random problem."""
    cf_service = _get_cf_service()
    result = await PvEChallengeService.start_challenge(db, current_user, cf_service)
    return success_response(
        data=result.model_dump(mode="json"),
        message="PvE challenge started",
    )


@router.get("/history")
async def get_history(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get paginated PvE challenge history."""
    result = await PvEChallengeService.get_history(db, current_user, page, page_size)
    return success_response(
        data=result.model_dump(mode="json"),
        message="History retrieved",
    )


@router.get("/{session_id}")
async def get_challenge_detail(
    session_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get detailed information about a PvE challenge session."""
    result = await PvEChallengeService.get_challenge(db, current_user, session_id)
    return success_response(
        data=result.model_dump(mode="json"),
        message="Challenge details retrieved",
    )


@router.post("/{session_id}/submit")
async def submit_result(
    session_id: UUID,
    body: PvESubmitResultRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Submit the result of a PvE challenge."""
    cf_service = _get_cf_service()
    result = await PvEChallengeService.submit_result(
        db=db,
        user=current_user,
        session_id=session_id,
        solved=body.solved,
        time_spent=body.time_spent,
        attempts=body.attempts,
        error_count=body.error_count,
        cf_service=cf_service,
    )
    return success_response(
        data=result.model_dump(mode="json"),
        message="Challenge completed",
    )


@router.post("/{session_id}/quit")
async def quit_challenge(
    session_id: UUID,
    body: PvEQuitRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Quit an active PvE challenge. Elo penalty based on submissions."""
    result = await PvEChallengeService.quit_challenge(
        db=db,
        user=current_user,
        session_id=session_id,
        submissions=body.submissions,
    )
    return success_response(
        data=result,
        message="Challenge quit",
    )
