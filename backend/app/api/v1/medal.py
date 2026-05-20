"""Medal API routes.

Mounts four endpoints under ``/api/v1/medal/``:
  GET  /overall     -- current user's overall medal
  GET  /skills      -- current user's per-tag skill medals
  GET  /stats       -- current user's trophy cabinet stats
  GET  /user/{uid}  -- public medal info for any user
"""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import success_response
from app.core.security import get_current_user
from app.models.user import User
from app.services.medal_service import MedalService

router = APIRouter(prefix="/medal", tags=["Medal"])


@router.get("/overall")
async def get_overall_medal(
    current_user: User = Depends(get_current_user),
):
    """Get the current user's overall medal based on Global Elo."""
    medal = MedalService.calculate_overall_medal(current_user.elo)
    return success_response(
        data={
            "elo": current_user.elo,
            "medal": medal,
        },
        message="Overall medal retrieved",
    )


@router.get("/skills")
async def get_skill_medals(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the current user's per-tag skill medals based on M-Elo."""
    skill_medals = await MedalService.get_all_skill_medals(db, current_user.id)

    # Convert dict to list format for cleaner API response
    skills_list = [
        {
            "tag": tag,
            **info,
        }
        for tag, info in skill_medals.items()
    ]

    return success_response(
        data={"skills": skills_list},
        message="Skill medals retrieved",
    )


@router.get("/stats")
async def get_medal_stats(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the current user's trophy cabinet -- medal counts by level/type."""
    stats = await MedalService.get_user_medal_stats(db, current_user.id)

    # Calculate total medals
    total = sum(
        count
        for level_stats in stats.values()
        for count in level_stats.values()
    )

    return success_response(
        data={
            "stats": stats,
            "total_medals": total,
        },
        message="Medal stats retrieved",
    )


@router.get("/user/{user_id}")
async def get_public_user_medal(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get public medal info for a specific user (requires authentication)."""
    from uuid import UUID

    from app.core.exceptions import NotFoundException

    try:
        uid = UUID(user_id)
    except ValueError as err:
        raise NotFoundException(message="Invalid user ID format") from err

    # Fetch user
    result = await db.execute(select(User).where(User.id == uid))
    target_user = result.scalar_one_or_none()
    if target_user is None:
        raise NotFoundException(message="User not found")

    # Calculate medals
    overall = MedalService.calculate_overall_medal(target_user.elo)
    stats = await MedalService.get_user_medal_stats(db, uid)

    total = sum(
        count
        for level_stats in stats.values()
        for count in level_stats.values()
    )

    return success_response(
        data={
            "user_id": str(uid),
            "username": target_user.username,
            "overall_medal": overall,
            "medal_stats": stats,
            "total_medals": total,
        },
        message="User medal info retrieved",
    )
