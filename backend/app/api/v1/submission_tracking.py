"""Submission tracking API routes.

Mounts three endpoints under ``/api/v1/submission-tracking/``:
  POST /register        -- register a pending submission (auth required)
  GET  /status          -- get tracking status for a session (auth required)
  GET  /pending         -- list user's pending tracking records (auth required)
"""

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import success_response
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.submission_tracking import (
    RegisterPendingRequest,
    RegisterPendingResponse,
    TrackingStatusResponse,
)
from app.services.submission_tracker import SubmissionTracker

router = APIRouter(prefix="/submission-tracking", tags=["Submission Tracking"])


@router.post("/register")
async def register_pending(
    body: RegisterPendingRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Register a pending submission for a game session.

    Called when a user starts solving a problem and is expected to
    submit on Codeforces.  The backend will automatically poll the
    CF API and trigger settlement when a matching submission is found.
    """
    from datetime import UTC, datetime

    tracking = await SubmissionTracker.register_pending(
        db=db,
        user_id=current_user.id,
        session_type=body.session_type,
        session_id=body.session_id,
        problem_id=body.problem_id,
        expected_at=datetime.now(UTC),
    )
    response = RegisterPendingResponse(
        tracking_id=tracking.id,
        status=tracking.status,
    )
    return success_response(
        data=response.model_dump(mode="json"),
        message="Pending submission registered",
    )


@router.get("/status")
async def get_tracking_status(
    session_type: str = Query(description="Session type"),
    session_id: UUID = Query(description="Session ID"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the tracking status for a specific game session."""
    tracking = await SubmissionTracker.get_tracking_for_session(
        db=db,
        user_id=current_user.id,
        session_type=session_type,
        session_id=session_id,
    )
    if tracking is None:
        return success_response(
            data=None,
            message="No tracking record found for this session",
        )

    response = TrackingStatusResponse(
        id=tracking.id,
        session_type=tracking.session_type,
        session_id=tracking.session_id,
        problem_id=tracking.problem_id,
        status=tracking.status,
        cf_submission_id=tracking.cf_submission_id,
        cf_verdict=tracking.cf_verdict,
        expected_at=tracking.expected_at,
        matched_at=tracking.matched_at,
        created_at=tracking.created_at,
    )
    return success_response(
        data=response.model_dump(mode="json"),
        message="Tracking status retrieved",
    )


@router.get("/pending")
async def list_pending(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all pending tracking records for the current user."""
    from app.models.submission_tracking import SubmissionTracking

    stmt = (
        select(SubmissionTracking)
        .where(
            SubmissionTracking.user_id == current_user.id,
            SubmissionTracking.status.in_(["pending", "matched"]),
        )
        .order_by(SubmissionTracking.created_at.desc())
    )
    result = await db.execute(stmt)
    records = list(result.scalars().all())

    items = [
        TrackingStatusResponse(
            id=r.id,
            session_type=r.session_type,
            session_id=r.session_id,
            problem_id=r.problem_id,
            status=r.status,
            cf_submission_id=r.cf_submission_id,
            cf_verdict=r.cf_verdict,
            expected_at=r.expected_at,
            matched_at=r.matched_at,
            created_at=r.created_at,
        ).model_dump(mode="json")
        for r in records
    ]
    return success_response(
        data=items,
        message=f"Found {len(items)} pending tracking records",
    )
