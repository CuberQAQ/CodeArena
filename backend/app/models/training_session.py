import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDPrimaryKeyMixin


class TrainingSession(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "training_sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    topic_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("topic_categories.id", ondelete="CASCADE"),
        nullable=False,
    )
    problems_solved: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    total_problems: Mapped[int] = mapped_column(Integer, nullable=False)
    streak_count: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    status: Mapped[str] = mapped_column(String(20), server_default="active", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    user = relationship("User", back_populates="training_sessions")
    topic = relationship("TopicCategory")
    problem_records = relationship("TrainingProblemRecord", back_populates="session", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<TrainingSession(id={self.id}, status={self.status})>"
