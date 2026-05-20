import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDPrimaryKeyMixin


class UserSettings(Base, UUIDPrimaryKeyMixin):
    """User display preferences and settings.

    Supports multi-device sync by persisting settings server-side.
    """

    __tablename__ = "user_settings"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    display_mode: Mapped[str] = mapped_column(
        String(20),
        server_default="medal",
        nullable=False,
        comment="Display mode: 'medal' (XCPC medal icons) or 'cf_tier' (CF-style tier colors)",
    )
    avatar_path: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships
    user = relationship("User", back_populates="settings")

    def __repr__(self) -> str:
        return f"<UserSettings(id={self.id}, user_id={self.user_id}, display_mode={self.display_mode})>"
