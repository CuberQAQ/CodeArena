import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDPrimaryKeyMixin


class ContestBot(Base, UUIDPrimaryKeyMixin):
    """AI Bot participating in a virtual contest alongside the human player."""

    __tablename__ = "contest_bots"

    contest_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("contest_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    bot_name: Mapped[str] = mapped_column(String(50), nullable=False)
    bot_elo: Mapped[int] = mapped_column(Integer, nullable=False)
    problems_solved: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    solved_problem_ids: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    total_attempts: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.now,
    )

    # Relationships
    contest = relationship("ContestSession", back_populates="bots")

    def __repr__(self) -> str:
        return f"<ContestBot(id={self.id}, name={self.bot_name}, elo={self.bot_elo})>"
