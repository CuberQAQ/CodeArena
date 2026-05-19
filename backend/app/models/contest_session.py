import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDPrimaryKeyMixin


class ContestSession(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "contest_sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    contest_tier: Mapped[str] = mapped_column(String(20), nullable=False)
    problems: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    total_problems: Mapped[int] = mapped_column(Integer, nullable=False)
    problems_solved: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    submissions: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    time_limit: Mapped[int] = mapped_column(Integer, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), server_default="active", nullable=False)
    elo_change: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Relationships
    user = relationship("User", back_populates="contest_sessions")
    problem_records = relationship(
        "ContestProblemRecord", back_populates="contest", cascade="all, delete-orphan"
    )
    bots = relationship(
        "ContestBot", back_populates="contest", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<ContestSession(id={self.id}, contest_tier={self.contest_tier})>"
