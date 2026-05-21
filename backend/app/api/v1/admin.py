"""Administrator API routes.

All endpoints require admin privileges (``user.is_admin == True``).

Endpoints:
  GET  /admin/config          -- retrieve all configuration
  PUT  /admin/config/{key}    -- update a single config key
  POST /admin/config/{key}/reset -- reset key to default
  GET  /admin/config/metadata -- get config structure metadata
  GET  /admin/users           -- paginated user list with search
  PUT  /admin/users/{id}/toggle-active  -- enable/disable user
  PUT  /admin/users/{id}/toggle-admin   -- grant/revoke admin
  GET  /admin/stats           -- system statistics
"""

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import success_response
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.admin import ConfigUpdateRequest
from app.services import admin_service

router = APIRouter(prefix="/admin", tags=["Administration"])

# ---------------------------------------------------------------------------
# Dependency: ensure the caller is an admin
# ---------------------------------------------------------------------------


async def _require_admin(user: User = Depends(get_current_user)) -> User:
    admin_service.require_admin(user)
    return user


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@router.get("/config")
async def get_all_config(
    _admin: User = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Retrieve the full system configuration (merged defaults + overrides)."""
    config = await admin_service.get_all_config(db)
    return success_response(data=config, message="Configuration retrieved")


@router.get("/config/metadata")
async def get_config_metadata(
    _admin: User = Depends(_require_admin),
):
    """Return configuration metadata (sections, fields, types, defaults)."""
    metadata = await admin_service.get_config_metadata()
    return success_response(data=metadata, message="Config metadata retrieved")


@router.put("/config/{key:path}")
async def update_config(
    key: str,
    body: ConfigUpdateRequest,
    _admin: User = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Update a single configuration key."""
    result = await admin_service.update_config(db, key, body.value, _admin.id)
    return success_response(data=result, message="Configuration updated")


@router.post("/config/{key:path}/reset")
async def reset_config(
    key: str,
    _admin: User = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Reset a configuration key to its default value."""
    result = await admin_service.reset_config(db, key, _admin.id)
    return success_response(data=result, message="Configuration reset to default")


# ---------------------------------------------------------------------------
# User management
# ---------------------------------------------------------------------------


@router.get("/users")
async def list_users(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    search: str | None = Query(None, max_length=100, description="Search by username or email"),
    _admin: User = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Retrieve a paginated, searchable user list."""
    result = await admin_service.list_users(db, page=page, page_size=page_size, search=search)
    return success_response(data=result, message="User list retrieved")


@router.put("/users/{user_id}/toggle-active")
async def toggle_user_active(
    user_id: UUID,
    _admin: User = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Toggle a user's active status."""
    result = await admin_service.toggle_user_active(db, user_id)
    return success_response(data=result, message="User active status toggled")


@router.put("/users/{user_id}/toggle-admin")
async def toggle_user_admin(
    user_id: UUID,
    _admin: User = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Toggle a user's admin status."""
    result = await admin_service.toggle_user_admin(db, user_id)
    return success_response(data=result, message="User admin status toggled")


# ---------------------------------------------------------------------------
# System statistics
# ---------------------------------------------------------------------------


@router.get("/stats")
async def get_system_stats(
    _admin: User = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Retrieve aggregated system statistics."""
    stats = await admin_service.get_system_stats(db)
    return success_response(data=stats, message="System statistics retrieved")
