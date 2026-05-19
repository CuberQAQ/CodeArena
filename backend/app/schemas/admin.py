"""Pydantic schemas for the admin API endpoints."""

from typing import Any

from pydantic import BaseModel, Field


class ConfigUpdateRequest(BaseModel):
    """Request body for updating a configuration key."""

    value: Any = Field(description="New value for the configuration key")


class ConfigUpdateResponse(BaseModel):
    """Response for a configuration update."""

    key: str
    value: Any


class ConfigResetResponse(BaseModel):
    """Response for a configuration reset."""

    key: str
    value: Any


class UserListItem(BaseModel):
    """A single user in the admin user list."""

    id: str
    username: str
    email: str
    elo: int
    pp: float
    tokens: int
    is_active: bool
    is_admin: bool
    created_at: str | None = None
    last_login_at: str | None = None


class UserListResponse(BaseModel):
    """Paginated user list response."""

    items: list[UserListItem]
    total: int
    page: int
    page_size: int
    total_pages: int


class UserToggleResponse(BaseModel):
    """Response for a user toggle operation."""

    id: str
    username: str
    is_active: bool | None = None
    is_admin: bool | None = None


class SystemStats(BaseModel):
    """Aggregated system statistics."""

    users: dict[str, int]
    challenges: dict[str, int]
    training: dict[str, int]
    contests: dict[str, int]
