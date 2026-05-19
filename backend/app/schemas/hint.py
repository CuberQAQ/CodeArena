"""Pydantic schemas for hint API request/response validation."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class UnlockHintRequest(BaseModel):
    """Request body for unlocking a hint level."""

    level: int = Field(ge=1, le=3, description="Hint level to unlock (1, 2, or 3)")


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class HintPriceInfo(BaseModel):
    """Price for a single hint level."""

    level: int
    tokens: int


class EloDecayPreview(BaseModel):
    """Elo decay multiplier for a hint level."""

    level: int
    multiplier: float


class HintStatusResponse(BaseModel):
    """Response for GET /hints/{problem_id}/status."""

    problem_id: str
    problem_rating: int
    unlocked_levels: list[int] = []
    prices: list[HintPriceInfo] = []
    elo_decay_preview: list[EloDecayPreview] = []
    next_level: int | None = None
    next_level_price: int | None = None


class UnlockHintResponse(BaseModel):
    """Response for POST /hints/{problem_id}/unlock."""

    problem_id: str
    level: int
    tokens_spent: int
    tokens_remaining: int


class HintContentResponse(BaseModel):
    """Response for GET /hints/{problem_id}/content/{level}."""

    problem_id: str
    level: int
    content: str
    unlocked: bool = True


class HintHistoryItem(BaseModel):
    """A single hint purchase record."""

    id: UUID
    problem_id: str
    hint_level: int
    tokens_cost: int
    created_at: datetime | None = None

    model_config = {"from_attributes": True}


class HintHistoryResponse(BaseModel):
    """Response for GET /hints/{problem_id}/history."""

    problem_id: str
    purchases: list[HintHistoryItem] = []
    total_spent: int = 0
