"""Pydantic schemas for medal API request/response validation."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class MedalInfo(BaseModel):
    """A single medal determination result."""

    level: str = Field(description="XCPC tier level: world_finals, ec_final, regional, provincial, or unranked")
    type: str | None = Field(default=None, description="Medal type: gold, silver, bronze (null for unranked)")

    model_config = {"from_attributes": True}


class SkillMedalInfo(BaseModel):
    """Medal info for a specific skill tag."""

    tag: str = Field(description="Skill tag name (e.g. 'dp', 'greedy')")
    level: str = Field(description="XCPC tier level")
    type: str | None = Field(default=None, description="Medal type (null for unranked)")
    melo: int = Field(description="Current M-Elo for this tag")

    model_config = {"from_attributes": True}


class ContestMedalRecord(BaseModel):
    """A permanent contest medal record."""

    id: UUID
    contest_session_id: UUID
    medal_level: str
    medal_type: str
    pr_value: int
    awarded_at: datetime | None = None

    model_config = {"from_attributes": True}


class OverallMedalResponse(BaseModel):
    """Response for GET /medal/overall."""

    elo: int = Field(description="Current global Elo")
    medal: MedalInfo = Field(description="Current overall medal")


class SkillMedalsResponse(BaseModel):
    """Response for GET /medal/skills."""

    skills: list[SkillMedalInfo] = Field(description="Per-tag medal breakdown")


class UserMedalStatsResponse(BaseModel):
    """Response for GET /medal/stats -- trophy cabinet summary."""

    stats: dict[str, dict[str, int]] = Field(
        description="Medal counts grouped by level and type",
        examples=[{
            "regional": {"gold": 3, "silver": 1},
            "provincial": {"gold": 2},
        }],
    )
    total_medals: int = Field(description="Total number of medals earned")


class PublicUserMedalResponse(BaseModel):
    """Response for GET /medal/user/{user_id} -- public medal info."""

    user_id: UUID
    username: str
    overall_medal: MedalInfo | None = None
    medal_stats: dict[str, dict[str, int]] = {}
    total_medals: int = 0


# ---------------------------------------------------------------------------
# Settings schemas
# ---------------------------------------------------------------------------


class UserSettingsResponse(BaseModel):
    """Response for GET /settings."""

    display_mode: str = Field(description="Display mode: medal or cf_tier")
    avatar_path: str | None = Field(default=None, description="Custom avatar path")

    model_config = {"from_attributes": True}


class UpdateSettingsRequest(BaseModel):
    """Request body for PUT /settings. All fields are optional."""

    display_mode: str | None = Field(
        default=None,
        description="Display mode: medal or cf_tier",
    )
    avatar_path: str | None = Field(
        default=None,
        description="Custom avatar path",
    )
