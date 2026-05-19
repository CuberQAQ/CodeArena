"""Pydantic schemas for PvE challenge API request/response validation."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class PvESubmitResultRequest(BaseModel):
    """Request body for submitting PvE challenge result."""

    solved: bool = Field(description="Whether the user solved the problem")
    time_spent: float = Field(ge=0, description="Time spent in seconds")
    attempts: int = Field(ge=0, description="Number of submission attempts on CF")
    error_count: int = Field(ge=0, default=0, description="Number of WA/TLE/RE/MLE errors")


class PvEQuitRequest(BaseModel):
    """Request body for quitting a PvE challenge."""

    submissions: int = Field(ge=0, description="Number of CF submissions made before quitting")


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class PvEProblemInfo(BaseModel):
    """Information about the PvE challenge problem."""

    contest_id: int
    index: str
    name: str
    rating: int | None = None
    tags: list[str] = []
    url: str


class PvEStartResponse(BaseModel):
    """Response after starting a PvE challenge."""

    session_id: UUID
    problem: PvEProblemInfo
    status: str = "active"


class PvEDetailResponse(BaseModel):
    """Full PvE challenge session details."""

    id: UUID
    user_id: UUID
    problem_id: str
    problem_rating: int
    problem_tags: list[str] = []
    problem: PvEProblemInfo | None = None
    status: str = "active"
    error_count: int = 0
    time_spent: float | None = None
    hints_used: int = 0
    elo_change: int | None = None
    pp_change: float | None = None
    s_value: float | None = None
    created_at: datetime | None = None
    completed_at: datetime | None = None

    model_config = {"from_attributes": True}


class PvESubmitResultResponse(BaseModel):
    """Response after submitting PvE challenge result."""

    session_id: UUID
    solved: bool
    status: str = "completed"
    elo_change: int | None = None
    pp_change: float | None = None
    s_value: float | None = None
    tokens_earned: int = 0


class PvEQuitResponse(BaseModel):
    """Response after quitting a PvE challenge."""

    session_id: UUID
    status: str = "quit"
    elo_change: int | None = None
    penalty: int | None = None


class PvEHistoryItem(BaseModel):
    """A single item in the PvE challenge history."""

    id: UUID
    problem_id: str
    problem_rating: int
    problem_tags: list[str] = []
    status: str
    error_count: int = 0
    time_spent: float | None = None
    hints_used: int = 0
    elo_change: int | None = None
    pp_change: float | None = None
    s_value: float | None = None
    created_at: datetime | None = None
    completed_at: datetime | None = None

    model_config = {"from_attributes": True}


class PvEHistoryResponse(BaseModel):
    """Paginated PvE challenge history response."""

    items: list[PvEHistoryItem]
    total: int
    page: int
    page_size: int
