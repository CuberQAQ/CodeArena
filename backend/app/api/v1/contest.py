"""Contest API routes.

Mounts eight endpoints under ``/api/v1/contest/``:
  GET  /tiers           -- list available tiers (auth required)
  POST /start           -- start contest session (auth required)
  GET  /active          -- get currently active contest session (auth required)
  GET  /history         -- get contest history (auth required)
  GET  /{id}            -- get contest status with remaining time (auth required)
  POST /{id}/submit     -- submit problem result (auth required)
  POST /{id}/end        -- end contest (auth required)
  GET  /{id}/result     -- get contest result detail (auth required)
"""

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import success_response
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.contest import StartContestRequest, SubmitContestProblemRequest
from app.services.cf_api_service import CFApiService
from app.services.contest_service import ContestService

router = APIRouter(prefix="/contest", tags=["Contest"])


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


@router.get("/tiers")
async def get_tiers(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get available contest tiers with eligibility info."""
    tiers = await ContestService.get_tiers(db, user=current_user)
    return success_response(
        data=[t.model_dump(mode="json") for t in tiers],
        message="Tiers retrieved",
    )


@router.post("/start")
async def start_contest(
    body: StartContestRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Start a new contest session."""
    cf_service = _get_cf_service()
    result = await ContestService.start_contest(
        db=db,
        user=current_user,
        tier=body.tier,
        cf_service=cf_service,
    )
    return success_response(
        data=result.model_dump(mode="json"),
        message="Contest started",
    )


@router.get("/history")
async def get_contest_history(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the user's contest history."""
    history = await ContestService.get_contest_history(db, user=current_user)
    return success_response(
        data=[h.model_dump(mode="json") for h in history],
        message="Contest history retrieved",
    )


@router.get("/active")
async def get_active_contest(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the user's currently active contest session, if any."""
    result = await ContestService.get_active_contest(db, user=current_user)
    return success_response(
        data=result.model_dump(mode="json") if result else None,
        message="Active contest retrieved",
    )


@router.get("/{contest_id}")
async def get_contest_status(
    contest_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the current status of a contest session."""
    result = await ContestService.get_contest_status(
        db=db,
        user=current_user,
        contest_id=contest_id,
    )
    return success_response(
        data=result.model_dump(mode="json"),
        message="Contest status retrieved",
    )


@router.post("/{contest_id}/submit")
async def submit_problem(
    contest_id: UUID,
    body: SubmitContestProblemRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Submit a problem result in a contest."""
    cf_service = _get_cf_service()
    result = await ContestService.submit_problem(
        db=db,
        user=current_user,
        contest_id=contest_id,
        problem_id=body.problem_id,
        solved=body.solved,
        attempts=body.attempts,
        time_spent=body.time_spent,
        cf_service=cf_service,
    )
    return success_response(
        data=result.model_dump(mode="json"),
        message="Problem result submitted",
    )


@router.post("/{contest_id}/end")
async def end_contest(
    contest_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """End a contest session and calculate results."""
    cf_service = _get_cf_service()
    result = await ContestService.end_contest(
        db=db,
        user=current_user,
        contest_id=contest_id,
        cf_service=cf_service,
    )
    return success_response(
        data=result.model_dump(mode="json"),
        message="Contest ended",
    )


@router.get("/{contest_id}/result")
async def get_contest_result(
    contest_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get detailed results for a contest."""
    result = await ContestService.get_contest_result(
        db=db,
        user=current_user,
        contest_id=contest_id,
    )
    return success_response(
        data=result.model_dump(mode="json"),
        message="Contest result retrieved",
    )


@router.get("/{contest_id}/leaderboard")
async def get_leaderboard(
    contest_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the combined human+bot leaderboard for an active contest."""
    result = await ContestService.get_leaderboard(
        db=db,
        user=current_user,
        contest_id=contest_id,
    )
    return success_response(
        data=result.model_dump(mode="json"),
        message="Leaderboard retrieved",
    )
