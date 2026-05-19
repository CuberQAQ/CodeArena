"""Token economy API routes.

Mounts three endpoints under ``/api/v1/economy/``:
  GET /balance         -- current token balance and daily cap status
  GET /transactions    -- paginated transaction history
  GET /daily-status    -- detailed daily earning breakdown
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import success_response
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.economy import DailyStatus, TokenBalance, TransactionItem, TransactionList
from app.services import economy_service

router = APIRouter(prefix="/economy", tags=["Economy"])


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/balance")
async def get_balance(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the current token balance and daily cap status."""
    data = await economy_service.get_balance(db, current_user)
    balance = TokenBalance(**data)
    return success_response(
        data=balance.model_dump(mode="json"),
        message="Balance retrieved",
    )


@router.get("/transactions")
async def get_transactions(
    limit: int = Query(default=20, ge=1, le=100, description="Items per page"),
    offset: int = Query(default=0, ge=0, description="Number of items to skip"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get paginated token transaction history."""
    items, total = await economy_service.get_transactions(
        db=db,
        user_id=current_user.id,
        limit=limit,
        offset=offset,
    )
    tx_list = TransactionList(
        items=[TransactionItem.model_validate(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )
    return success_response(
        data=tx_list.model_dump(mode="json"),
        message="Transactions retrieved",
    )


@router.get("/daily-status")
async def get_daily_status(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get detailed daily token earning status with breakdown by type."""
    data = await economy_service.get_daily_status(db, current_user)
    status = DailyStatus(**data)
    return success_response(
        data=status.model_dump(mode="json"),
        message="Daily status retrieved",
    )
