"""Pydantic schemas for the token economy API."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class TokenBalance(BaseModel):
    """Current token balance and daily cap status."""

    tokens: int = Field(description="Current token balance")
    daily_tokens_earned: int = Field(description="Tokens earned today")
    daily_cap: int = Field(description="Maximum tokens earnable per day")
    daily_remaining: int = Field(description="Tokens still earnable today")


class TransactionItem(BaseModel):
    """A single token transaction."""

    id: UUID
    amount: int = Field(description="Positive for awards, negative for spending")
    type: str = Field(description="Transaction type (e.g. challenge_reward, hint_purchase)")
    reference_type: str | None = None
    reference_id: UUID | None = None
    balance_after: int
    created_at: datetime | None = None

    model_config = {"from_attributes": True}


class TransactionList(BaseModel):
    """Paginated list of token transactions."""

    items: list[TransactionItem] = []
    total: int = 0
    limit: int = 20
    offset: int = 0


class DailyStatus(BaseModel):
    """Detailed daily token earning status."""

    date: str = Field(description="Date in YYYY-MM-DD format")
    daily_tokens_earned: int = 0
    daily_cap: int = 120
    daily_remaining: int = 0
    breakdown: dict[str, int] = Field(
        default_factory=dict,
        description="Tokens earned today, grouped by transaction type",
    )
