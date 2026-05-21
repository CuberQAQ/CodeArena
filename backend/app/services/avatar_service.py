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
