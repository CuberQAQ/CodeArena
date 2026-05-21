"""Daily check-in record model.

Tracks user daily check-ins, streaks, and make-up (retroactive) check-ins.
"""

import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDPrimaryKeyMixin


class CheckIn(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "check_ins"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    checkin_date: Mapped[date] = mapped_column(Date, nullable=False)
    streak_days: Mapped[int] = mapped_column(Integer, nullable=False)
    is_makeup: Mapped[bool] = mapped_column(
        Boolean, server_default="false", nullable=False
    )
    tokens_awarded: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    user = relationship("User", back_populates="check_ins")

    def __repr__(self) -> str:
        return (
            f"<CheckIn(id={self.id}, user_id={self.user_id}, "
            f"date={self.checkin_date}, streak={self.streak_days})>"
        )
