"""Administrator service.

Provides business logic for the admin dashboard:
  - System statistics aggregation
  - User management (list, toggle active/admin)
  - Configuration management (delegates to ConfigService)
"""

import uuid
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.default_config import DEFAULT_CONFIG
from app.core.exceptions import ForbiddenException, NotFoundException
from app.models.challenge_session import ChallengeSession
from app.models.contest_session import ContestSession
from app.models.training_session import TrainingSession
from app.models.user import User
from app.services.config_service import ConfigService

# ---------------------------------------------------------------------------
# Permission helpers
# ---------------------------------------------------------------------------


def require_admin(user: User) -> None:
    """Raise ``ForbiddenException`` if *user* is not an admin."""
    if not user.is_admin:
        raise ForbiddenException(message="Admin access required")


# ---------------------------------------------------------------------------
# System statistics
# ---------------------------------------------------------------------------


async def get_system_stats(db: AsyncSession) -> dict[str, Any]:
    """Return aggregated system statistics for the admin dashboard."""

    # Total users
    total_users = await db.scalar(select(func.count(User.id)))

    # Active users
    active_users = await db.scalar(
        select(func.count(User.id)).where(User.is_active.is_(True))
    )

    # Challenge stats
    total_challenges = await db.scalar(select(func.count(ChallengeSession.id)))
    active_challenges = await db.scalar(
        select(func.count(ChallengeSession.id)).where(
            ChallengeSession.status == "active"
        )
    )

    # Training stats
    total_training_sessions = await db.scalar(select(func.count(TrainingSession.id)))
    active_training = await db.scalar(
        select(func.count(TrainingSession.id)).where(
            TrainingSession.status == "active"
        )
    )

    # Contest stats
    total_contests = await db.scalar(select(func.count(ContestSession.id)))
    active_contests = await db.scalar(
        select(func.count(ContestSession.id)).where(
            ContestSession.status == "active"
        )
    )

    return {
        "users": {
            "total": total_users or 0,
            "active": active_users or 0,
        },
        "challenges": {
            "total": total_challenges or 0,
            "active": active_challenges or 0,
        },
        "training": {
            "total_sessions": total_training_sessions or 0,
            "active_sessions": active_training or 0,
        },
        "contests": {
            "total": total_contests or 0,
            "active": active_contests or 0,
        },
    }


# ---------------------------------------------------------------------------
# User management
# ---------------------------------------------------------------------------


async def list_users(
    db: AsyncSession,
    *,
    page: int = 1,
    page_size: int = 20,
    search: str | None = None,
) -> dict[str, Any]:
    """Return a paginated, optionally filtered list of users."""

    base_query: Select = select(User).order_by(User.created_at.desc())

    # Apply search filter
    if search:
        pattern = f"%{search}%"
        base_query = base_query.where(
            (User.username.ilike(pattern)) | (User.email.ilike(pattern))
        )

    # Count total matching rows
    count_query = select(func.count()).select_from(base_query.subquery())
    total = await db.scalar(count_query) or 0

    # Paginate
    offset = (page - 1) * page_size
    rows_query = base_query.offset(offset).limit(page_size)
    result = await db.execute(rows_query)
    users = result.scalars().all()

    return {
        "items": [
            {
                "id": str(u.id),
                "username": u.username,
                "email": u.email,
                "elo": u.elo,
                "pp": u.pp,
                "tokens": u.tokens,
                "is_active": u.is_active,
                "is_admin": u.is_admin,
                "created_at": u.created_at.isoformat() if u.created_at else None,
                "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
            }
            for u in users
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": max(1, (total + page_size - 1) // page_size),
    }


async def toggle_user_active(db: AsyncSession, user_id: uuid.UUID) -> dict[str, Any]:
    """Toggle a user's ``is_active`` flag. Returns updated user info."""

    user = await db.get(User, user_id)
    if user is None:
        raise NotFoundException(message="User not found")

    user.is_active = not user.is_active
    await db.flush()

    return {
        "id": str(user.id),
        "username": user.username,
        "is_active": user.is_active,
    }


async def toggle_user_admin(db: AsyncSession, user_id: uuid.UUID) -> dict[str, Any]:
    """Toggle a user's ``is_admin`` flag. Returns updated user info."""

    user = await db.get(User, user_id)
    if user is None:
        raise NotFoundException(message="User not found")

    user.is_admin = not user.is_admin
    await db.flush()

    return {
        "id": str(user.id),
        "username": user.username,
        "is_admin": user.is_admin,
    }


# ---------------------------------------------------------------------------
# Configuration management (delegates to ConfigService)
# ---------------------------------------------------------------------------


async def get_all_config(db: AsyncSession) -> dict[str, Any]:
    """Return the full merged configuration dict."""
    return await ConfigService.get_all_config(db)


async def update_config(
    db: AsyncSession,
    key: str,
    value: Any,
    admin_id: uuid.UUID,
) -> dict[str, Any]:
    """Update a single configuration key. Returns the updated value."""
    await ConfigService.set_config(db, key, value, admin_id)
    return {"key": key, "value": value}


async def reset_config(
    db: AsyncSession,
    key: str,
    admin_id: uuid.UUID,
) -> dict[str, Any]:
    """Reset a configuration key to its default value. Returns the default."""
    default_value = await ConfigService.reset_config(db, key, admin_id)
    return {"key": key, "value": default_value}


async def get_config_metadata() -> list[dict[str, Any]]:
    """Return configuration metadata (sections and keys with descriptions).

    This is derived from ``DEFAULT_CONFIG`` to help the frontend build
    a structured configuration editor.
    """
    sections: list[dict[str, Any]] = []
    for section_key, section_value in DEFAULT_CONFIG.items():
        if not isinstance(section_value, dict):
            continue
        fields: list[dict[str, Any]] = []
        for field_key, field_value in section_value.items():
            if isinstance(field_value, dict):
                # Nested sub-section (e.g. economy.difficulty_tiers)
                for sub_key, sub_value in field_value.items():
                    if isinstance(sub_value, dict):
                        for leaf_key, leaf_value in sub_value.items():
                            fields.append({
                                "key": f"{section_key}.{field_key}.{sub_key}.{leaf_key}",
                                "label": f"{field_key}.{sub_key}.{leaf_key}",
                                "type": type(leaf_value).__name__,
                                "default": leaf_value,
                            })
                    else:
                        fields.append({
                            "key": f"{section_key}.{field_key}.{sub_key}",
                            "label": f"{field_key}.{sub_key}",
                            "type": type(sub_value).__name__,
                            "default": sub_value,
                        })
            else:
                fields.append({
                    "key": f"{section_key}.{field_key}",
                    "label": field_key,
                    "type": type(field_value).__name__,
                    "default": field_value,
                })
        sections.append({
            "key": section_key,
            "label": section_key.upper(),
            "fields": fields,
        })
    return sections
