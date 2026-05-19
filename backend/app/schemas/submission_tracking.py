"""Pydantic schemas for submission tracking API request/response validation."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class RegisterPendingRequest(BaseModel):
    """Request body for registering a pending submission."""

    session_type: str = Field(
        description="Session type: pve, pvp, training, or contest",
    )
    session_id: UUID = Field(description="Game session ID")
    problem_id: str = Field(
        max_length=50,
        description="CF problem ID, e.g. '800A'",
    )


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class TrackingStatusResponse(BaseModel):
    """Response for a tracking record status."""

    id: UUID
    session_type: str
    session_id: UUID
    problem_id: str
    status: str
    cf_submission_id: int | None = None
    cf_verdict: str | None = None
    expected_at: datetime | None = None
    matched_at: datetime | None = None
    created_at: datetime | None = None

    model_config = {"from_attributes": True}


class RegisterPendingResponse(BaseModel):
    """Response after registering a pending submission."""

    tracking_id: UUID
    status: str = "pending"
