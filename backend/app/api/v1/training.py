"""Training API routes.

Mounts eight endpoints under ``/api/v1/training/``:
  GET  /topics              -- list all topics
  GET  /topics/{id}         -- topic detail with problems
  POST /start               -- start training session
  GET  /session/{id}        -- get session status
  POST /session/{id}/submit -- submit problem result
  POST /session/{id}/abandon -- abandon training
  GET  /progress            -- progress across all topics
  GET  /progress/{topic_id} -- progress for a single topic
"""

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import success_response
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.training import StartTrainingRequest, SubmitTrainingProblemRequest
from app.services.cf_api_service import CFApiService
from app.services.training_service import TrainingService

router = APIRouter(prefix="/training", tags=["Training"])


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


@router.get("/topics")
async def list_topics(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get all topic categories."""
    cf_service = _get_cf_service()
    topics = await TrainingService.list_topics(db, user_id=current_user.id, cf_service=cf_service)
    return success_response(
        data=[t.model_dump(mode="json") for t in topics],
        message="Topics retrieved",
    )


@router.get("/topics/{topic_id}")
async def get_topic_detail(
    topic_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get topic detail with problem list."""
    cf_service = _get_cf_service()
    detail = await TrainingService.get_topic_detail(
        db=db,
        topic_id=topic_id,
        user_id=current_user.id,
        cf_service=cf_service,
    )
    return success_response(
        data=detail.model_dump(mode="json"),
        message="Topic detail retrieved",
    )


@router.post("/start")
async def start_training(
    body: StartTrainingRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Start a new training session for a topic."""
    cf_service = _get_cf_service()
    result = await TrainingService.start_training(
        db=db,
        user=current_user,
        topic_id=body.topic_id,
        cf_service=cf_service,
    )
    return success_response(
        data=result.model_dump(mode="json"),
        message="Training session started",
    )


@router.get("/session/{session_id}")
async def get_session_status(
    session_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the current status of a training session."""
    result = await TrainingService.get_session_status(
        db=db,
        user=current_user,
        session_id=session_id,
    )
    return success_response(
        data=result.model_dump(mode="json"),
        message="Session status retrieved",
    )


@router.post("/session/{session_id}/submit")
async def submit_problem(
    session_id: UUID,
    body: SubmitTrainingProblemRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Submit a problem result in a training session."""
    cf_service = _get_cf_service()
    result = await TrainingService.submit_problem(
        db=db,
        user=current_user,
        session_id=session_id,
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


@router.post("/session/{session_id}/abandon")
async def abandon_training(
    session_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Abandon an active training session."""
    result = await TrainingService.abandon_training(
        db=db,
        user=current_user,
        session_id=session_id,
    )
    return success_response(
        data=result.model_dump(mode="json"),
        message="Training session abandoned",
    )


@router.get("/progress")
async def get_progress(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the user's progress across all topics."""
    cf_service = _get_cf_service()
    progress = await TrainingService.get_progress(
        db=db,
        user_id=current_user.id,
        cf_service=cf_service,
    )
    return success_response(
        data=progress.model_dump(mode="json"),
        message="Progress retrieved",
    )


@router.get("/progress/{topic_id}")
async def get_topic_progress(
    topic_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the user's detailed progress for a specific topic."""
    cf_service = _get_cf_service()
    progress = await TrainingService.get_topic_progress(
        db=db,
        user_id=current_user.id,
        topic_id=topic_id,
        cf_service=cf_service,
    )
    return success_response(
        data=progress.model_dump(mode="json"),
        message="Topic progress retrieved",
    )
