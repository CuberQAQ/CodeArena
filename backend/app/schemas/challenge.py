"""Pydantic schemas for challenge API request/response validation."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class SubmitResultRequest(BaseModel):
    """Request body for submitting challenge result."""

    solved: bool = Field(description="Whether the user solved the problem")
    time_spent: float = Field(ge=0, description="Time spent in seconds")
    attempts: int = Field(ge=0, description="Number of submission attempts on CF")


class QuitChallengeRequest(BaseModel):
    """Request body for quitting a challenge."""

    submissions: int = Field(ge=0, description="Number of CF submissions made before quitting")


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class OpponentInfo(BaseModel):
    """Public opponent information returned in match results."""

    id: UUID
    username: str
    elo: int
    cf_handle: str | None = None

    model_config = {"from_attributes": True}


class MatchResult(BaseModel):
    """Returned when a match is found."""

    session_id: UUID
    opponent: OpponentInfo
    status: str = "matched"


class QueueStatus(BaseModel):
    """Current queue/match status for the user."""

    in_queue: bool
    matched: bool
    session_id: UUID | None = None
    opponent: OpponentInfo | None = None
    both_ready: bool = False


class ProblemInfo(BaseModel):
    """Information about the challenge problem."""

    contest_id: int
    index: str
    name: str
    rating: int | None = None
    tags: list[str] = []
    url: str


class ChallengeDetail(BaseModel):
    """Full challenge session details."""

    id: UUID
    challenger_id: UUID
    opponent_id: UUID
    problem_id: str
    problem_rating: int
    problem: ProblemInfo | None = None
    challenger_solved: bool = False
    opponent_solved: bool = False
    challenger_submissions: int = 0
    opponent_submissions: int = 0
    challenger_time: float | None = None
    opponent_time: float | None = None
    status: str = "active"
    result: str | None = None
    is_challenger: bool = False
    elo_change: int | None = None
    opponent_elo_change: int | None = None
    tokens_earned: int | None = None
    opponent_tokens_earned: int | None = None
    created_at: datetime | None = None
    completed_at: datetime | None = None

    model_config = {"from_attributes": True}


class StartChallengeResponse(BaseModel):
    """Response after confirming start -- reveals the problem."""

    session_id: UUID
    problem: ProblemInfo
    status: str = "problem_revealed"


class SubmitResultResponse(BaseModel):
    """Response after submitting challenge result."""

    session_id: UUID
    solved: bool
    status: str = "result_submitted"
    settled: bool = False
    result: str | None = None
    elo_change: int | None = None
    tokens_earned: int | None = None
    achievements: list[dict] = []


class QuitChallengeResponse(BaseModel):
    """Response after quitting a challenge."""

    session_id: UUID
    status: str = "quit"
    elo_change: int | None = None
    penalty: int | None = None


class ActiveChallengeInfo(BaseModel):
    """Summary of an active challenge session for resume purposes."""

    id: UUID
    problem_id: str
    problem_name: str | None = None
    problem_rating: int
    created_at: datetime | None = None
    is_challenger: bool
    opponent_username: str | None = None
    opponent_elo: int | None = None
    status: str = "active"

    model_config = {"from_attributes": True}
