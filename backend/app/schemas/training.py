"""Pydantic schemas for training API request/response validation."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class StartTrainingRequest(BaseModel):
    """Request body for starting a training session."""

    topic_id: UUID = Field(description="ID of the topic category to train on")


class SubmitTrainingProblemRequest(BaseModel):
    """Request body for submitting a problem result in training."""

    problem_id: str = Field(description="CF problem ID (e.g. '1234A')")
    solved: bool = Field(description="Whether the user solved the problem")
    attempts: int = Field(ge=0, description="Number of submission attempts")
    time_spent: float = Field(ge=0, description="Time spent in seconds")


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class TopicProblemInfo(BaseModel):
    """A single problem within a topic."""

    problem_id: str
    contest_id: int
    index: str
    name: str
    rating: int | None = None
    tags: list[str] = []
    url: str
    solved: bool = False
    attempts: int = 0
    time_spent: float | None = None


class TopicInfo(BaseModel):
    """Basic info about a topic category."""

    id: UUID
    name: str
    slug: str
    description: str | None = None
    cf_tags: list[str] = []
    display_order: int = 0
    total_problems: int = 0
    solved_count: int = 0
    stars: int = 0
    melo: float | None = None
    shield_active: bool = False

    model_config = {"from_attributes": True}


class TopicDetail(TopicInfo):
    """Detailed topic info including problem list."""

    problems: list[TopicProblemInfo] = []


class TrainingSessionInfo(BaseModel):
    """Training session state."""

    id: UUID
    topic_id: UUID
    topic_name: str = ""
    problems_solved: int = 0
    total_problems: int = 0
    streak_count: int = 0
    status: str = "active"
    created_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    last_solved_rating: int | None = None
    streak_tokens_earned: int = 0

    model_config = {"from_attributes": True}


class SubmitTrainingResponse(BaseModel):
    """Response after submitting a training problem."""

    session_id: UUID
    problem_id: str
    solved: bool
    streak_count: int = 0
    streak_tokens: int = 0
    total_streak_tokens: int = 0
    tokens_earned: int = 0
    elo_change: int | None = None
    achievements: list[dict] = []


class TopicProgress(BaseModel):
    """User progress on a single topic."""

    topic_id: UUID
    topic_name: str
    slug: str
    total_problems: int = 0
    solved_count: int = 0
    completion_rate: float = 0.0
    stars: int = 0
    total_attempts: int = 0
    total_time_spent: float = 0.0
    melo: float | None = None
    shield_active: bool = False


class TrainingProgress(BaseModel):
    """User progress across all topics."""

    topics: list[TopicProgress] = []
    total_solved: int = 0
    total_problems: int = 0


class AbandonTrainingResponse(BaseModel):
    """Response after abandoning a training session."""

    session_id: UUID
    status: str = "abandoned"
    problems_solved: int = 0
    total_problems: int = 0
    elo_change: int | None = None
    shield_active: bool = False


class UserTagEloInfo(BaseModel):
    """M-Elo (per-tag Elo) record for a user."""

    tag: str
    elo: int
    total_submissions: int = 0
    first_ac_at: datetime | None = None
    shield_active: bool = True

    model_config = {"from_attributes": True}


class MEloListResponse(BaseModel):
    """Response for the user's all tag M-Elo list."""

    melos: list[UserTagEloInfo] = []
    global_elo: int = 1200


class RecommendedProblemResponse(BaseModel):
    """Adaptively recommended problem based on M-Elo."""

    problem_id: str
    contest_id: int
    index: str
    name: str
    rating: int | None = None
    tags: list[str] = []
    url: str
    melo: int = Field(description="User's M-Elo used for selection")
    search_range: list[int] = Field(
        description="The [low, high] rating range used to find this problem",
    )
