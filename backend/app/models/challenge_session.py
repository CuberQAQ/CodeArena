import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDPrimaryKeyMixin


class ChallengeSession(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "challenge_sessions"

    challenger_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    opponent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    problem_id: Mapped[str] = mapped_column(String(50), nullable=False)
    problem_rating: Mapped[int] = mapped_column(Integer, nullable=False)
    challenger_submissions: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    opponent_submissions: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    challenger_solved: Mapped[bool] = mapped_column(Boolean, server_default="false", nullable=False)
    opponent_solved: Mapped[bool] = mapped_column(Boolean, server_default="false", nullable=False)
    challenger_time: Mapped[float | None] = mapped_column(Float, nullable=True)
    opponent_time: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(20), server_default="active", nullable=False)
    result: Mapped[str | None] = mapped_column(String(20), nullable=True)
    elo_change: Mapped[int | None] = mapped_column(Integer, nullable=True)
    opponent_elo_change: Mapped[int | None] = mapped_column(Integer, nullable=True)
    opponent_tokens_earned: Mapped[int | None] = mapped_column(Integer, nullable=True)
    challenger_tokens_earned: Mapped[int | None] = mapped_column(Integer, nullable=True)
    problem_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    hints_used_challenger: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    hints_used_opponent: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    challenger = relationship(
        "User",
        back_populates="challenge_sessions_as_challenger",
        foreign_keys=[challenger_id],
    )
    opponent = relationship(
        "User",
        back_populates="challenge_sessions_as_opponent",
        foreign_keys=[opponent_id],
    )

    __table_args__ = (
        Index("ix_challenge_sessions_challenger_created", "challenger_id", created_at.desc()),
        Index("ix_challenge_sessions_opponent_created", "opponent_id", created_at.desc()),
    )

    def __repr__(self) -> str:
        return f"<ChallengeSession(id={self.id}, status={self.status})>"
