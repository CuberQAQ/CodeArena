import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDPrimaryKeyMixin


class PvEChallengeSession(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "pve_challenge_sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    problem_id: Mapped[str] = mapped_column(String(50), nullable=False)
    problem_rating: Mapped[int] = mapped_column(Integer, nullable=False)
    problem_tags: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(20), server_default="active", nullable=False)
    error_count: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    time_spent: Mapped[float | None] = mapped_column(Float, nullable=True)
    hints_used: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    elo_change: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pp_change: Mapped[float | None] = mapped_column(Float, nullable=True)
    s_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    user = relationship("User", back_populates="pve_challenge_sessions", foreign_keys=[user_id])

    __table_args__ = (
        Index("ix_pve_sessions_user_created", "user_id", created_at.desc()),
    )

    def __repr__(self) -> str:
        return f"<PvEChallengeSession(id={self.id}, status={self.status})>"
