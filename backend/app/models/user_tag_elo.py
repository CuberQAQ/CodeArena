import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDPrimaryKeyMixin


class UserTagElo(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "user_tag_elo"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    tag: Mapped[str] = mapped_column(String(100), nullable=False)
    elo: Mapped[int] = mapped_column(Integer, server_default="1200", nullable=False)
    total_submissions: Mapped[int] = mapped_column(
        Integer, server_default="0", nullable=False
    )
    first_ac_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relationships
    user = relationship("User", back_populates="user_tag_elos")

    __table_args__ = (
        UniqueConstraint("user_id", "tag", name="uq_user_tag_elo_user_tag"),
    )

    def __repr__(self) -> str:
        return f"<UserTagElo(id={self.id}, user_id={self.user_id}, tag={self.tag}, elo={self.elo})>"
