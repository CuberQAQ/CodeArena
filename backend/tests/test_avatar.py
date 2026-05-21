"""Tests for the avatar upload system.

Covers:
  1. Upload success (JPG, PNG <= 2MB)
  2. File too large (>2MB)
  3. Invalid format (non-image)
  4. Empty file
  5. Auto-crop: non-square images are cropped to square
  6. Avatar file is saved as JPG
  7. get_avatar_path returns path for existing, None for missing
  8. Corrupt image file handling

Uses an in-memory SQLite database with a lightweight test UserSettings model.
"""

import uuid
from io import BytesIO
from unittest.mock import patch

import pytest
from PIL import Image
from sqlalchemy import DateTime, String, event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core.exceptions import BadRequestException
from app.services import avatar_service

# ---------------------------------------------------------------------------
# Lightweight SQLite-compatible test models
# ---------------------------------------------------------------------------


class _TestBase(DeclarativeBase):
    pass


class _TestUserSettings(_TestBase):
    __tablename__ = "user_settings"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(nullable=False, unique=True)
    display_mode: Mapped[str] = mapped_column(String(20), default="medal", nullable=False)
    avatar_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    updated_at: Mapped[DateTime | None] = mapped_column(DateTime, nullable=True)


class _TestUser(_TestBase):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(String(50), nullable=False)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def async_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)

    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as conn:
        await conn.run_sync(_TestBase.metadata.create_all)

    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(_TestBase.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
async def db(async_engine):
    session_factory = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as session:
        with (
            patch.object(avatar_service, "UserSettings", _TestUserSettings),
            patch.object(avatar_service, "User", _TestUser),
        ):
            yield session


@pytest.fixture
def temp_upload_dir(tmp_path, monkeypatch):
    """Create a temporary uploads directory and monkeypatch the service."""
    upload_dir = tmp_path / "avatars"
    upload_dir.mkdir()
    monkeypatch.setattr(avatar_service, "UPLOAD_DIR", upload_dir)
    return upload_dir


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_jpg_image(width: int = 100, height: int = 100) -> bytes:
    """Create a JPG image of the given dimensions and return bytes."""
    img = Image.new("RGB", (width, height), color=(255, 0, 0))
    buf = BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def _make_png_image(width: int = 100, height: int = 100, with_alpha: bool = False) -> bytes:
    """Create a PNG image of the given dimensions and return bytes."""
    mode = "RGBA" if with_alpha else "RGB"
    img = Image.new(mode, (width, height), color=(0, 255, 0))
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ===========================================================================
# Tests
# ===========================================================================


class TestUploadAvatar:
    """Tests for avatar_service.upload_avatar."""

    async def test_upload_jpg_success(self, db, temp_upload_dir):
        """JPG upload <= 2MB should succeed."""
        user_id = uuid.uuid4()
        content = _make_jpg_image(100, 100)

        result = await avatar_service.upload_avatar(
            db=db,
            user_id=user_id,
            file_content=content,
            content_type="image/jpeg",
        )

        assert result == f"avatars/{user_id}.jpg"
        # File should exist on disk
        saved_path = temp_upload_dir / f"{user_id}.jpg"
        assert saved_path.is_file()

        # Verify the saved image is a valid square JPEG
        with Image.open(saved_path) as img:
            assert img.size == (256, 256)
            assert img.format == "JPEG"

    async def test_upload_png_success(self, db, temp_upload_dir):
        """PNG upload should succeed and be converted to JPG."""
        user_id = uuid.uuid4()
        content = _make_png_image(100, 100)

        result = await avatar_service.upload_avatar(
            db=db,
            user_id=user_id,
            file_content=content,
            content_type="image/png",
        )

        assert result == f"avatars/{user_id}.jpg"
        saved_path = temp_upload_dir / f"{user_id}.jpg"
        assert saved_path.is_file()

        # Verify saved as JPEG
        with Image.open(saved_path) as img:
            assert img.format == "JPEG"

    async def test_upload_png_with_alpha(self, db, temp_upload_dir):
        """PNG with alpha channel should be converted to RGB and saved as JPG."""
        user_id = uuid.uuid4()
        content = _make_png_image(100, 100, with_alpha=True)

        result = await avatar_service.upload_avatar(
            db=db,
            user_id=user_id,
            file_content=content,
            content_type="image/png",
        )

        assert result == f"avatars/{user_id}.jpg"
        saved_path = temp_upload_dir / f"{user_id}.jpg"
        assert saved_path.is_file()

        with Image.open(saved_path) as img:
            assert img.mode == "RGB"
            assert img.size == (256, 256)

    async def test_file_too_large(self, db, temp_upload_dir):
        """Files larger than 2MB should be rejected."""
        user_id = uuid.uuid4()
        content = b"x" * (2 * 1024 * 1024 + 1)  # 2MB + 1 byte

        with pytest.raises(BadRequestException) as exc_info:
            await avatar_service.upload_avatar(
                db=db,
                user_id=user_id,
                file_content=content,
                content_type="image/jpeg",
            )

        assert "too large" in exc_info.value.message.lower()

    async def test_invalid_format_gif(self, db, temp_upload_dir):
        """Non-JPG/PNG formats should be rejected."""
        user_id = uuid.uuid4()

        with pytest.raises(BadRequestException) as exc_info:
            await avatar_service.upload_avatar(
                db=db,
                user_id=user_id,
                file_content=b"fake gif data",
                content_type="image/gif",
            )

        assert "invalid file format" in exc_info.value.message.lower()

    async def test_invalid_format_webp(self, db, temp_upload_dir):
        """WebP format should be rejected."""
        user_id = uuid.uuid4()

        with pytest.raises(BadRequestException) as exc_info:
            await avatar_service.upload_avatar(
                db=db,
                user_id=user_id,
                file_content=b"fake webp data",
                content_type="image/webp",
            )

        assert "invalid file format" in exc_info.value.message.lower()

    async def test_empty_file(self, db, temp_upload_dir):
        """Empty file should be rejected."""
        user_id = uuid.uuid4()

        with pytest.raises(BadRequestException) as exc_info:
            await avatar_service.upload_avatar(
                db=db,
                user_id=user_id,
                file_content=b"",
                content_type="image/jpeg",
            )

        assert "empty" in exc_info.value.message.lower()

    async def test_corrupt_image(self, db, temp_upload_dir):
        """Corrupt image data should be rejected."""
        user_id = uuid.uuid4()

        with pytest.raises(BadRequestException) as exc_info:
            await avatar_service.upload_avatar(
                db=db,
                user_id=user_id,
                file_content=b"not a real image content",
                content_type="image/jpeg",
            )

        assert "invalid image" in exc_info.value.message.lower()

    async def test_auto_crop_landscape(self, db, temp_upload_dir):
        """Landscape (wide) images should be center-cropped to square."""
        user_id = uuid.uuid4()
        # 200x100 landscape image
        content = _make_jpg_image(200, 100)

        await avatar_service.upload_avatar(
            db=db,
            user_id=user_id,
            file_content=content,
            content_type="image/jpeg",
        )

        saved_path = temp_upload_dir / f"{user_id}.jpg"
        with Image.open(saved_path) as img:
            assert img.size == (256, 256)  # Should be square

    async def test_auto_crop_portrait(self, db, temp_upload_dir):
        """Portrait (tall) images should be center-cropped to square."""
        user_id = uuid.uuid4()
        # 100x200 portrait image
        content = _make_jpg_image(100, 200)

        await avatar_service.upload_avatar(
            db=db,
            user_id=user_id,
            file_content=content,
            content_type="image/jpeg",
        )

        saved_path = temp_upload_dir / f"{user_id}.jpg"
        with Image.open(saved_path) as img:
            assert img.size == (256, 256)  # Should be square

    async def test_overwrite_existing(self, db, temp_upload_dir):
        """Uploading a new avatar should overwrite the old one."""
        user_id = uuid.uuid4()

        # First upload
        content1 = _make_jpg_image(50, 50)
        await avatar_service.upload_avatar(
            db=db,
            user_id=user_id,
            file_content=content1,
            content_type="image/jpeg",
        )

        # Second upload (overwrite)
        content2 = _make_png_image(300, 200)
        result = await avatar_service.upload_avatar(
            db=db,
            user_id=user_id,
            file_content=content2,
            content_type="image/png",
        )

        assert result == f"avatars/{user_id}.jpg"
        saved_path = temp_upload_dir / f"{user_id}.jpg"
        assert saved_path.is_file()

    async def test_creates_user_settings_if_none(self, db, temp_upload_dir):
        """If user has no settings row, one should be created."""
        user_id = uuid.uuid4()
        content = _make_jpg_image(50, 50)

        await avatar_service.upload_avatar(
            db=db,
            user_id=user_id,
            file_content=content,
            content_type="image/jpeg",
        )

        # Verify settings row was created
        from sqlalchemy import select

        stmt = select(_TestUserSettings).where(_TestUserSettings.user_id == user_id)
        result = await db.execute(stmt)
        settings = result.scalar_one_or_none()
        assert settings is not None
        assert settings.avatar_path == f"avatars/{user_id}.jpg"

    async def test_updates_existing_user_settings(self, db, temp_upload_dir):
        """If user already has a settings row, it should be updated."""
        from sqlalchemy import select

        user_id = uuid.uuid4()

        # Create existing settings
        settings = _TestUserSettings(
            user_id=user_id,
            display_mode="medal",
            avatar_path=None,
        )
        db.add(settings)
        await db.flush()

        # Upload avatar
        content = _make_jpg_image(50, 50)
        await avatar_service.upload_avatar(
            db=db,
            user_id=user_id,
            file_content=content,
            content_type="image/jpeg",
        )

        # Verify settings was updated
        stmt = select(_TestUserSettings).where(_TestUserSettings.user_id == user_id)
        result = await db.execute(stmt)
        updated_settings = result.scalar_one()
        assert updated_settings.avatar_path == f"avatars/{user_id}.jpg"


class TestGetAvatarPath:
    """Tests for avatar_service.get_avatar_path."""

    def test_returns_path_for_existing_avatar(self, temp_upload_dir):
        """Should return path when avatar file exists."""
        user_id = uuid.uuid4()
        # Create a fake avatar file
        avatar_file = temp_upload_dir / f"{user_id}.jpg"
        avatar_file.write_bytes(b"fake jpg")

        result = avatar_service.get_avatar_path(user_id)

        assert result is not None
        assert result == avatar_file

    def test_returns_none_for_missing_avatar(self, temp_upload_dir):
        """Should return None when no avatar file exists."""
        user_id = uuid.uuid4()

        result = avatar_service.get_avatar_path(user_id)

        assert result is None

    def test_accepts_string_user_id(self, temp_upload_dir):
        """Should accept string user_id (from URL path parameter)."""
        user_id = uuid.uuid4()
        avatar_file = temp_upload_dir / f"{user_id}.jpg"
        avatar_file.write_bytes(b"fake jpg")

        result = avatar_service.get_avatar_path(str(user_id))

        assert result is not None


class TestGenerateDefaultAvatar:
    """Tests for avatar_service.generate_default_avatar."""

    async def test_generates_svg_with_username_initial(self, db):
        """Should return SVG containing the uppercase first letter of the username."""
        user_id = uuid.uuid4()
        user = _TestUser(id=user_id, username="alice")
        db.add(user)
        await db.flush()

        svg = await avatar_service.generate_default_avatar(db, user_id)

        assert "A" in svg
        assert svg.startswith("<svg")
        assert "</svg>" in svg

    async def test_lowercase_username_gives_uppercase_initial(self, db):
        """The initial should always be uppercase."""
        user_id = uuid.uuid4()
        user = _TestUser(id=user_id, username="bob")
        db.add(user)
        await db.flush()

        svg = await avatar_service.generate_default_avatar(db, user_id)

        assert ">B</text>" in svg

    async def test_unknown_user_gives_question_mark(self, db):
        """If user is not found, initial should be '?'."""
        user_id = uuid.uuid4()

        svg = await avatar_service.generate_default_avatar(db, user_id)

        assert ">?</text>" in svg

    async def test_consistent_color_for_same_user(self, db):
        """Same user_id should always produce the same SVG (deterministic color)."""
        user_id = uuid.uuid4()
        user = _TestUser(id=user_id, username="charlie")
        db.add(user)
        await db.flush()

        svg1 = await avatar_service.generate_default_avatar(db, user_id)
        svg2 = await avatar_service.generate_default_avatar(db, user_id)

        assert svg1 == svg2

    async def test_svg_has_correct_dimensions(self, db):
        """SVG should be 256x256 with circular viewBox."""
        user_id = uuid.uuid4()
        user = _TestUser(id=user_id, username="test")
        db.add(user)
        await db.flush()

        svg = await avatar_service.generate_default_avatar(db, user_id)

        assert 'width="256"' in svg
        assert 'height="256"' in svg
        assert 'viewBox="0 0 256 256"' in svg

    async def test_svg_has_circular_background(self, db):
        """SVG rect should have rx=128 for a circular shape."""
        user_id = uuid.uuid4()
        user = _TestUser(id=user_id, username="diana")
        db.add(user)
        await db.flush()

        svg = await avatar_service.generate_default_avatar(db, user_id)

        assert 'rx="128"' in svg

    async def test_color_is_from_palette(self, db):
        """The fill color in the SVG must be one of the AVATAR_COLORS."""
        user_id = uuid.uuid4()
        user = _TestUser(id=user_id, username="eve")
        db.add(user)
        await db.flush()

        svg = await avatar_service.generate_default_avatar(db, user_id)

        # Extract fill color from the rect element
        import re

        match = re.search(r'fill="([^"]+)"', svg)
        assert match is not None
        color = match.group(1)
        assert color in avatar_service.AVATAR_COLORS

    async def test_svg_media_type_format(self, db):
        """SVG should be a valid SVG with proper namespace."""
        user_id = uuid.uuid4()
        user = _TestUser(id=user_id, username="frank")
        db.add(user)
        await db.flush()

        svg = await avatar_service.generate_default_avatar(db, user_id)

        assert 'xmlns="http://www.w3.org/2000/svg"' in svg
