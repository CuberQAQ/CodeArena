import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDPrimaryKeyMixin


class ContestProblemRecord(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "contest_problem_records"

    contest_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("contest_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    problem_id: Mapped[str] = mapped_column(String(50), nullable=False)
    problem_rating: Mapped[int] = mapped_column(Integer, nullable=False)
    solved: Mapped[bool] = mapped_column(Boolean, server_default="false", nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    time_spent: Mapped[float | None] = mapped_column(Float, nullable=True)
    solved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    contest = relationship("ContestSession", back_populates="problem_records")

    def __repr__(self) -> str:
        return f"<ContestProblemRecord(id={self.id}, problem_id={self.problem_id})>"
