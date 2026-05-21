"""Pydantic schemas for Free Play API request/response validation."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class FreePlaySearchRequest(BaseModel):
    """Request body for searching problems."""

    min_rating: int = Field(ge=800, le=3500, description="Minimum problem rating")
    max_rating: int = Field(ge=800, le=3500, description="Maximum problem rating")
    tags: list[str] = Field(default_factory=list, description="CF tags to filter by")


class FreePlayRecommendRequest(BaseModel):
    """Request body for getting an adaptive recommendation."""

    pass


class FreePlayStartRequest(BaseModel):
    """Request body for starting a free play session."""

    problem_contest_id: int = Field(description="CF contest ID of the problem")
    problem_index: str = Field(description="Problem index within contest (e.g. 'A')")
    problem_rating: int = Field(ge=800, le=3500, description="Problem difficulty rating")
    problem_tags: list[str] = Field(default_factory=list, description="CF tags for the problem")
    problem_name: str = Field(default="", description="Problem name")


class FreePlaySubmitRequest(BaseModel):
    """Request body for submitting a free play result."""

    solved: bool = Field(description="Whether the user solved the problem")
    time_spent: float = Field(ge=0, description="Time spent in seconds")
    attempts: int = Field(ge=0, description="Number of submission attempts on CF")
    error_count: int = Field(ge=0, default=0, description="Number of WA/TLE/RE/MLE errors")


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class FreePlayProblemInfo(BaseModel):
    """Information about a free play problem."""

    contest_id: int
    index: str
    name: str
    rating: int | None = None
    tags: list[str] = []
    url: str


class FreePlaySearchResponse(BaseModel):
    """Response after searching problems."""

    problem: FreePlayProblemInfo | None = None
    found: bool = False
    message: str = ""


class FreePlayRecommendResponse(BaseModel):
    """Response after getting a recommendation."""

    problem: FreePlayProblemInfo | None = None
    found: bool = False
    message: str = ""
    recommended_tag: str | None = None


class FreePlayStartResponse(BaseModel):
    """Response after starting a free play session."""

    session_id: UUID
    problem: FreePlayProblemInfo
    status: str = "active"
    started_at: datetime | None = None


class AchievementEventSchema(BaseModel):
    """A single achievement event returned in settlement responses."""

    type: str
    title: str
    description: str
    icon: str


class FreePlaySubmitResponse(BaseModel):
    """Response after submitting a free play result."""

    session_id: UUID
    solved: bool
    status: str = "completed"
    elo_change: int | None = None
    pp_change: float | None = None
    s_value: float | None = None
    tokens_earned: int = 0
    overkill_multiplier: float = 1.0
    achievements: list[AchievementEventSchema] = []


class FreePlayQuitResponse(BaseModel):
    """Response after quitting a free play session."""

    session_id: UUID
    status: str = "quit"
    elo_change: int | None = None
    new_elo: int | None = None
    penalty: int | None = None
