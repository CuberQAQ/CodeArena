"""CF Handle binding and verification API routes.

Mounts four endpoints under ``/api/v1/cf-handle/``:
  POST /bind              -- initiate CF Handle binding (auth required)
  POST /verify            -- verify CF Handle via bio check (auth required)
  GET  /info/{handle}     -- look up public CF user info (public)
  DELETE /unbind          -- unbind CF Handle (auth required)
"""

import functools

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import success_response
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.cf_handle import BindCFHandleRequest, VerifyCFHandleRequest
from app.services import cf_handle_service
from app.services.cf_api_service import CFApiService

router = APIRouter(prefix="/cf-handle", tags=["CF Handle"])


# ---------------------------------------------------------------------------
# Service singleton (thread-safe via lru_cache)
# ---------------------------------------------------------------------------


@functools.lru_cache(maxsize=1)
def _get_cf_service() -> CFApiService:
    return CFApiService()


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/bind")
async def bind_cf_handle(
    body: BindCFHandleRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Initiate CF Handle binding. Returns a verification code to place in CF bio."""
    cf_service = _get_cf_service()
    result = await cf_handle_service.bind_cf_handle(
        db=db,
        user=current_user,
        cf_handle=body.cf_handle,
        cf_service=cf_service,
    )
    return success_response(
        data=result,
        message="CF Handle binding initiated. Add the verification code to your CF profile.",
        status_code=201,
    )


@router.post("/verify")
async def verify_cf_handle(
    body: VerifyCFHandleRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Verify CF Handle by checking the verification code in the user's CF bio."""
    cf_service = _get_cf_service()
    result = await cf_handle_service.verify_cf_handle(
        db=db,
        user=current_user,
        cf_handle=body.cf_handle,
        verification_code=body.verification_code,
        cf_service=cf_service,
    )
    return success_response(
        data=result,
        message="CF Handle verified successfully",
    )


@router.get("/info/{handle}")
async def get_cf_handle_info(
    handle: str,
):
    """Look up public CF user information by handle. No authentication required."""
    cf_service = _get_cf_service()
    result = await cf_handle_service.get_cf_handle_info(
        cf_handle=handle,
        cf_service=cf_service,
    )
    return success_response(
        data=result,
        message="CF user info retrieved",
    )


@router.delete("/unbind")
async def unbind_cf_handle(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Unbind the current user's CF Handle."""
    result = await cf_handle_service.unbind_cf_handle(
        db=db,
        user=current_user,
    )
    return success_response(
        data=result,
        message="CF Handle unbound",
    )
