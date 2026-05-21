"""Pydantic schemas for check-in API request/response validation."""

from datetime import date
from uuid import UUID

from pydantic import BaseModel


class CheckInResponse(BaseModel):
    """Response for POST /checkin and POST /checkin/makeup."""

    checkin_date: date
    streak_days: int
    tokens_awarded: int
    is_makeup: bool = False
    tokens_balance: int


class CheckInStatusResponse(BaseModel):
    """Response for GET /checkin/status."""

    checked_in_today: bool
    streak_days: int
    last_checkin_date: date | None = None
    makeup_used_this_week: int
    makeup_limit: int
    next_reward: int  # tokens they'd get on next check-in
    can_makeup: bool  # whether user can make up yesterday's missed check-in
    checked_dates_this_week: list[date] = []  # actual dates checked in this week


class CheckInHistoryItem(BaseModel):
    """A single check-in record."""

    id: UUID
    checkin_date: date
    streak_days: int
    is_makeup: bool
    tokens_awarded: int

    model_config = {"from_attributes": True}


class CheckInHistoryResponse(BaseModel):
    """Response for GET /checkin/history."""

    items: list[CheckInHistoryItem] = []
    total: int
