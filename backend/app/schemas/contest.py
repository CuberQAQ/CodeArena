"""Pydantic schemas for contest API request/response validation."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class StartContestRequest(BaseModel):
    """Request body for starting a contest session."""

    tier: str = Field(description="Contest tier: beginner, advanced, or master")


class SubmitContestProblemRequest(BaseModel):
    """Request body for submitting a problem result in a contest."""

    problem_id: str = Field(description="CF problem ID (e.g. '1234A')")
    solved: bool = Field(description="Whether the user solved the problem")
    attempts: int = Field(ge=0, description="Number of submission attempts")
    time_spent: float = Field(ge=0, description="Time spent in seconds")


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class TierInfo(BaseModel):
    """Information about a contest tier."""

    tier: str
    name: str
    min_elo: int | None = None
    max_elo: int | None = None
    duration_minutes: int
    problem_count: int
    rating_range: list[int]
    eligible: bool = False


class ContestProblemInfo(BaseModel):
    """A single problem in a contest."""

    problem_id: str
    contest_id: int = 0
    index: str = ""
    name: str = ""
    rating: int = 1000
    url: str = ""
    solved: bool = False
    attempts: int = 0
    time_spent: float | None = None


class ContestSessionInfo(BaseModel):
    """Contest session state including remaining time."""

    id: UUID
    tier: str
    problems: list[ContestProblemInfo] = []
    total_problems: int = 0
    problems_solved: int = 0
    submissions: int = 0
    time_limit_minutes: int = 0
    started_at: datetime | None = None
    ended_at: datetime | None = None
    remaining_seconds: float | None = None
    status: str = "active"
    elo_change: int | None = None

    model_config = {"from_attributes": True}


class SubmitContestResponse(BaseModel):
    """Response after submitting a contest problem."""

    contest_id: UUID
    problem_id: str
    solved: bool
    tokens_earned: int = 0


class ContestResult(BaseModel):
    """Detailed result of a completed contest."""

    id: UUID
    tier: str
    total_problems: int = 0
    problems_solved: int = 0
    submissions: int = 0
    time_limit_minutes: int = 0
    started_at: datetime | None = None
    ended_at: datetime | None = None
    status: str = "completed"
    elo_change: int | None = None
    performance_rating: int | None = None
    problems: list[ContestProblemInfo] = []


class ContestHistoryItem(BaseModel):
    """Summary item for contest history listing."""

    id: UUID
    tier: str
    total_problems: int = 0
    problems_solved: int = 0
    submissions: int = 0
    time_limit_minutes: int = 0
    started_at: datetime | None = None
    ended_at: datetime | None = None
    status: str = "active"
    elo_change: int | None = None


class LeaderboardEntry(BaseModel):
    """A single entry on the contest leaderboard (human or bot)."""

    rank: int
    name: str
    elo: int
    solved: int
    is_bot: bool = False


class LeaderboardResponse(BaseModel):
    """Full leaderboard for a contest session with timing info."""

    leaderboard: list[LeaderboardEntry] = []
    time_elapsed: int = 0
    time_total: int = 0
