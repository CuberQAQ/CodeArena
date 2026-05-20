"""Challenge API routes.

Mounts eight endpoints under ``/api/v1/challenge/``:
  POST /queue           -- join match queue (auth required)
  DELETE /queue         -- leave match queue (auth required)
  GET  /status          -- query match status (auth required)
  GET  /active          -- get active challenge for resume (auth required)
  POST /start           -- confirm start / reveal problem (auth required)
  GET  /{id}            -- get challenge detail (auth required)
  POST /{id}/submit     -- submit result (auth required)
  POST /{id}/quit       -- quit challenge (auth required)
"""

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import success_response
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.challenge import QuitChallengeRequest, SubmitResultRequest
from app.services.cf_api_service import CFApiService
from app.services.challenge_service import ChallengeService
from app.services.match_service import get_match_service

router = APIRouter(prefix="/challenge", tags=["Challenge"])


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


@router.post("/queue")
async def join_queue(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Join the match queue. Attempts immediate matching."""
    match_service = get_match_service()
    result = await ChallengeService.join_queue(db, current_user, match_service)
    return success_response(
        data=result,
        message="Match found" if result.get("matched") else "Added to queue",
    )


@router.delete("/queue")
async def leave_queue(
    current_user: User = Depends(get_current_user),
):
    """Leave the match queue."""
    match_service = get_match_service()
    removed = await ChallengeService.leave_queue(current_user, match_service)
    if not removed:
        return success_response(
            data={"removed": False},
            message="Not in queue",
        )
    return success_response(
        data={"removed": True},
        message="Removed from queue",
    )


@router.get("/status")
async def get_status(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Query current match/queue status."""
    match_service = get_match_service()
    result = await ChallengeService.get_queue_status(db, current_user, match_service)
    return success_response(
        data=result,
        message="Status retrieved",
    )


@router.get("/active")
async def get_active_challenge(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the user's currently active challenge session, if any."""
    result = await ChallengeService.get_active_challenge(db, user=current_user)
    return success_response(
        data=result.model_dump(mode="json") if result else None,
        message="Active challenge retrieved",
    )


@router.post("/start")
async def start_challenge(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Confirm start and reveal the challenge problem.

    If the opponent hasn't confirmed yet, returns a waiting status.
    When both confirm, the problem is selected and revealed.
    """
    # Get the user's active pending session
    match_service = get_match_service()
    status = await ChallengeService.get_queue_status(db, current_user, match_service)

    session_id = status.get("session_id")
    if not session_id:
        return success_response(
            data={"status": "no_match"},
            message="No active match to start",
        )

    cf_service = _get_cf_service()
    result = await ChallengeService.start_challenge(
        db=db,
        user=current_user,
        session_id=UUID(session_id),
        cf_service=cf_service,
    )
    return success_response(
        data=result.model_dump(mode="json"),
        message="Challenge started",
    )


@router.get("/{session_id}")
async def get_challenge_detail(
    session_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get detailed information about a challenge session."""
    result = await ChallengeService.get_challenge_detail(db, current_user, session_id)
    return success_response(
        data=result.model_dump(mode="json"),
        message="Challenge details retrieved",
    )


@router.post("/{session_id}/submit")
async def submit_result(
    session_id: UUID,
    body: SubmitResultRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Submit your challenge result (solved, time_spent, attempts)."""
    cf_service = _get_cf_service()
    result = await ChallengeService.submit_result(
        db=db,
        user=current_user,
        session_id=session_id,
        solved=body.solved,
        time_spent=body.time_spent,
        attempts=body.attempts,
        cf_service=cf_service,
    )
    return success_response(
        data=result.model_dump(mode="json"),
        message="Result submitted" if not result.settled else "Challenge settled",
    )


@router.post("/{session_id}/quit")
async def quit_challenge(
    session_id: UUID,
    body: QuitChallengeRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Quit an active challenge. Elo penalty based on submissions."""
    result = await ChallengeService.quit_challenge(
        db=db,
        user=current_user,
        session_id=session_id,
        submissions=body.submissions,
    )
    return success_response(
        data=result,
        message="Challenge quit",
    )
