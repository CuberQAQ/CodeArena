"""Free Play API routes.

Mounts five endpoints under ``/api/v1/free-play/``:
  POST /search                -- search problems by rating range and tags (auth required)
  POST /recommend             -- get adaptive problem recommendation (auth required)
  POST /start                 -- start a free play session (auth required)
  POST /{session_id}/submit   -- submit result (auth required)
  POST /{session_id}/quit     -- quit session (auth required)
"""

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import success_response
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.free_play import (
    FreePlaySearchRequest,
    FreePlayStartRequest,
    FreePlaySubmitRequest,
)
from app.services.cf_api_service import CFApiService
from app.services.free_play_service import FreePlayService

router = APIRouter(prefix="/free-play", tags=["Free Play"])


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


@router.post("/search")
async def search_problems(
    body: FreePlaySearchRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Search for problems by rating range and optional tags."""
    cf_service = _get_cf_service()
    result = await FreePlayService.search_problems(
        db=db,
        user=current_user,
        min_rating=body.min_rating,
        max_rating=body.max_rating,
        tags=body.tags,
        cf_service=cf_service,
    )
    return success_response(
        data=result.model_dump(mode="json"),
        message="Search completed",
    )


@router.post("/recommend")
async def recommend_problem(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get an adaptive problem recommendation based on M-Elo."""
    cf_service = _get_cf_service()
    result = await FreePlayService.recommend_problem(
        db=db,
        user=current_user,
        cf_service=cf_service,
    )
    return success_response(
        data=result.model_dump(mode="json"),
        message="Recommendation completed",
    )


@router.get("/active")
async def get_active_session(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the user's current active Free Play session, if any."""
    result = await FreePlayService.get_active_session(db=db, user=current_user)
    if result is None:
        return success_response(data=None, message="No active session")
    return success_response(
        data=result.model_dump(mode="json"),
        message="Active session found",
    )


@router.post("/start")
async def start_session(
    body: FreePlayStartRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Start a new Free Play session with a user-selected problem."""
    result = await FreePlayService.start_session(
        db=db,
        user=current_user,
        problem_contest_id=body.problem_contest_id,
        problem_index=body.problem_index,
        problem_rating=body.problem_rating,
        problem_tags=body.problem_tags,
        problem_name=body.problem_name,
    )
    return success_response(
        data=result.model_dump(mode="json"),
        message="Free Play session started",
    )


@router.post("/{session_id}/submit")
async def submit_result(
    session_id: UUID,
    body: FreePlaySubmitRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Submit the result of a Free Play session."""
    cf_service = _get_cf_service()
    result = await FreePlayService.submit_result(
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
        message="Free Play session completed",
    )


@router.post("/{session_id}/quit")
async def quit_session(
    session_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Quit an active Free Play session."""
    result = await FreePlayService.quit_session(
        db=db,
        user=current_user,
        session_id=session_id,
    )
    return success_response(
        data=result.model_dump(mode="json"),
        message="Free Play session quit",
    )
