"""Training API routes.

Mounts thirteen endpoints under ``/api/v1/training/``:
  GET  /topics              -- list all topics
  GET  /topics/{id}         -- topic detail with problems
  GET  /topics/{id}/recommend -- adaptive problem recommendation
  GET  /topics/{id}/curated-problems -- curated problem list with pagination
  GET  /topics/{id}/active-session -- session recovery for a topic
  POST /start               -- start training session
  GET  /session/{id}        -- get session status
  POST /session/{id}/submit -- submit problem result
  POST /session/{id}/abandon -- abandon training
  GET  /progress            -- progress across all topics
  GET  /progress/{topic_id} -- progress for a single topic
  GET  /melo                -- get user's all tag M-Elo (for radar chart)
  GET  /recommended-topics  -- recommend topics based on weakest M-Elo
"""

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import success_response
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.training import (
    MEloListResponse,
    SkipProblemRequest,
    StartTrainingRequest,
    SubmitTrainingProblemRequest,
    UserTagEloInfo,
)
from app.services.cf_api_service import CFApiService
from app.services.melo_service import MEloService
from app.services.training_service import PREDEFINED_TOPICS, TrainingService

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


@router.get("/topics/{topic_id}/recommend")
async def get_recommended_problem(
    topic_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    min_rating: int | None = None,
    max_rating: int | None = None,
):
    """Get an adaptive problem recommendation based on the user's M-Elo.

    Returns a single unsolved problem within a rating range derived from
    the user's M-Elo for the topic's primary tag.  If no suitable problem
    is found (after expanding the range up to 3 rounds), returns null data.

    Optional min_rating/max_rating override the default M-Elo-based range.
    """
    cf_service = _get_cf_service()
    result = await TrainingService.get_adaptive_problem(
        db=db,
        user=current_user,
        topic_id=topic_id,
        cf_service=cf_service,
        min_rating=min_rating,
        max_rating=max_rating,
    )
    if result is None:
        return success_response(
            data=None,
            message="No suitable problem found for your current level",
        )
    return success_response(
        data=result.model_dump(mode="json"),
        message="Recommended problem found",
    )


@router.get("/topics/{topic_id}/curated-problems")
async def get_curated_problems(
    topic_id: UUID,
    limit: int = 20,
    offset: int = 0,
    min_rating: int | None = None,
    max_rating: int | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a curated list of problems for a topic with pagination.

    Returns a subset of problems segmented into 200-point rating buckets,
    with up to 5 representatives per bucket.  Supports difficulty filtering
    via min_rating/max_rating query parameters and load-more via offset/limit.
    """
    cf_service = _get_cf_service()
    result = await TrainingService.get_curated_problems(
        db=db,
        topic_id=topic_id,
        user_id=current_user.id,
        limit=limit,
        offset=offset,
        min_rating=min_rating,
        max_rating=max_rating,
        cf_service=cf_service,
    )
    return success_response(
        data=result.model_dump(mode="json"),
        message="Curated problems retrieved",
    )


@router.get("/topics/{topic_id}/active-session")
async def get_active_session_for_topic(
    topic_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the user's active training session for a topic, or null.

    Used for session recovery on page refresh.  If the user has an active
    training session for the given topic, returns its full state (including
    started_at for timer persistence).  Otherwise returns null data.
    """
    result = await TrainingService.get_active_session_for_topic(
        db=db,
        user=current_user,
        topic_id=topic_id,
    )
    if result is None:
        return success_response(data=None, message="No active session for this topic")
    return success_response(
        data=result.model_dump(mode="json"),
        message="Active session found",
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


@router.post("/session/{session_id}/skip-problem")
async def skip_problem(
    session_id: UUID,
    body: SkipProblemRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Skip a problem in an active training session.

    Within the protection period (first 300s): no penalty.
    After protection period: deducts 5 M-Elo from the topic's tag.
    """
    result = await TrainingService.skip_problem(
        db=db,
        user=current_user,
        session_id=session_id,
        problem_id=body.problem_id,
    )
    return success_response(
        data=result.model_dump(mode="json"),
        message="Problem skipped",
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


@router.get("/melo")
async def get_melo(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the user's all tag M-Elo records for radar chart visualization.

    Ensures every predefined topic has a corresponding M-Elo record so that
    unpracticed topics appear on the Skill Radar instead of being omitted.
    """
    # Collect unique primary tags from all predefined topics
    primary_tags: list[str] = []
    seen: set[str] = set()
    for topic in PREDEFINED_TOPICS:
        tag = topic["cf_tags"][0]
        if tag not in seen:
            seen.add(tag)
            primary_tags.append(tag)

    # Bulk get-or-create M-Elo records for all tags (1 query instead of 12)
    melos = await MEloService.ensure_melos_for_tags(db, current_user.id, primary_tags)

    melo_infos = [
        UserTagEloInfo(
            tag=m.tag,
            elo=m.elo,
            total_submissions=m.total_submissions,
            first_ac_at=m.first_ac_at,
            shield_active=m.first_ac_at is None,
        )
        for m in melos
    ]

    response = MEloListResponse(
        melos=melo_infos,
        global_elo=current_user.elo,
    )
    return success_response(
        data=response.model_dump(mode="json"),
        message="M-Elo retrieved",
    )


@router.get("/recommended-topics")
async def get_recommended_topics(
    limit: int = 3,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get 2-3 topics the user should prioritize based on weakest M-Elo.

    Returns topics sorted by the user's M-Elo (ascending -- weakest first)
    with reason text explaining why each topic is recommended.
    """
    results = await TrainingService.get_recommended_topics(
        db=db,
        user_id=current_user.id,
        limit=limit,
    )
    return success_response(
        data=[r.model_dump(mode="json") for r in results],
        message="Recommended topics retrieved",
    )
