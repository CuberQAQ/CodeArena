"""Avatar upload and processing service.

Handles file validation, image cropping, and storage for user avatars.
Avatars are stored as JPG files in uploads/avatars/ with filename {user_id}.jpg.
"""

import logging
from io import BytesIO
from pathlib import Path
from uuid import UUID

from PIL import Image, ImageOps
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestException
from app.models.user import User
from app.models.user_settings import UserSettings

logger = logging.getLogger("code_arena")

# Avatar configuration
MAX_FILE_SIZE = 2 * 1024 * 1024  # 2 MB
ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png"}
AVATAR_SIZE = 256  # Output avatar size in pixels (square)
UPLOAD_DIR = Path("uploads/avatars")

# Ensure upload directory exists at module load
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


async def upload_avatar(
    db: AsyncSession,
    user_id: UUID,
    file_content: bytes,
    content_type: str,
) -> str:
    """Validate, crop, and save an avatar image.

    Args:
        db: AsyncSession for database access.
        user_id: The user's UUID.
        file_content: Raw bytes of the uploaded file.
        content_type: MIME type of the uploaded file.

    Returns:
        The relative path to the saved avatar (e.g. "avatars/{user_id}.jpg").

    Raises:
        BadRequestException: If file is too large, wrong format, or corrupt.
    """
    # Validate content type
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise BadRequestException(
            message="Invalid file format. Only JPG and PNG images are allowed.",
            detail=f"Received content type: {content_type}",
        )

    # Validate file size
    if len(file_content) > MAX_FILE_SIZE:
        raise BadRequestException(
            message="File is too large. Maximum size is 2 MB.",
            detail=f"Received {len(file_content)} bytes, maximum {MAX_FILE_SIZE} bytes",
        )

    if len(file_content) == 0:
        raise BadRequestException(message="Empty file uploaded.")

    # Open and process the image with Pillow
    try:
        img = Image.open(BytesIO(file_content))
        img = ImageOps.exif_transpose(img)  # Respect EXIF orientation
    except Exception as exc:
        raise BadRequestException(
            message="Invalid image file. Could not process the image.",
            detail=str(exc),
        ) from exc

    # Convert to RGB (handles PNG with alpha, palette images, etc.)
    if img.mode != "RGB":
        img = img.convert("RGB")

    # Crop to square using ImageOps.fit (center crop)
    img = ImageOps.fit(img, (AVATAR_SIZE, AVATAR_SIZE), method=Image.Resampling.LANCZOS)

    # Save as JPG
    avatar_filename = f"{user_id}.jpg"
    avatar_path = UPLOAD_DIR / avatar_filename
    img.save(avatar_path, "JPEG", quality=85)

    # Update user_settings.avatar_path in database
    relative_path = f"avatars/{avatar_filename}"
    stmt = select(UserSettings).where(UserSettings.user_id == user_id)
    result = await db.execute(stmt)
    settings = result.scalar_one_or_none()

    if settings is None:
        settings = UserSettings(
            user_id=user_id,
            display_mode="medal",
            avatar_path=relative_path,
        )
        db.add(settings)
    else:
        settings.avatar_path = relative_path

    await db.flush()

    logger.info("Avatar uploaded for user %s", user_id)
    return relative_path


def get_avatar_path(user_id: UUID) -> Path | None:
    """Return the filesystem path to a user's avatar, or None if not found.

    Checks for the expected {user_id}.jpg file.
    """
    avatar_path = UPLOAD_DIR / f"{user_id}.jpg"
    if avatar_path.is_file():
        return avatar_path
    return None


# Default avatar color palette (soft, distinct colors)
AVATAR_COLORS = [
    "#4F46E5",
    "#7C3AED",
    "#EC4899",
    "#EF4444",
    "#F97316",
    "#EAB308",
    "#22C55E",
    "#14B8A6",
    "#06B6D4",
    "#3B82F6",
    "#8B5CF6",
    "#F43F5E",
]


async def generate_default_avatar(db: AsyncSession, user_id: UUID) -> str:
    """Generate an SVG default avatar for a user who has not uploaded one.

    The avatar displays the first letter of the username in uppercase,
    on a colored circle. The color is deterministically chosen from a
    palette based on the user_id string hash so the same user always
    gets the same color.

    Args:
        db: AsyncSession for database access.
        user_id: The user's UUID.

    Returns:
        SVG string for the default avatar.
    """
    stmt = select(User.username).where(User.id == user_id)
    result = await db.execute(stmt)
    username = result.scalar_one_or_none()

    initial = username[0].upper() if username else "?"

    color_index = int(user_id) % len(AVATAR_COLORS)
    color = AVATAR_COLORS[color_index]

    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256" viewBox="0 0 256 256">'
        f'<rect width="256" height="256" rx="128" fill="{color}"/>'
        f'<text x="128" y="128" text-anchor="middle" dominant-baseline="central" '
        f'font-family="system-ui, -apple-system, sans-serif" font-size="120" font-weight="600" fill="white">'
        f"{initial}</text></svg>"
    )
    return svg
