import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDPrimaryKeyMixin


class ContestMedal(Base, UUIDPrimaryKeyMixin):
    """Permanent record of a medal awarded in a contest session.

    Each user can receive at most one medal per contest session.
    The medal level/type is determined by the user's Performance Rating (PR)
    at the time of contest settlement, mapped against the XCPC tier thresholds.
    """

    __tablename__ = "contest_medals"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    contest_session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("contest_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    medal_level: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        comment="XCPC tier level: world_finals, ec_final, regional, provincial",
    )
    medal_type: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        comment="Medal type: gold, silver, bronze",
    )
    pr_value: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="Performance Rating at the time of awarding",
    )
    awarded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    # Relationships
    user = relationship("User", back_populates="contest_medals")
    contest_session = relationship("ContestSession", back_populates="medals")

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "contest_session_id",
            name="uq_contest_medals_user_session",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<ContestMedal(id={self.id}, "
            f"user_id={self.user_id}, "
            f"level={self.medal_level}, "
            f"type={self.medal_type})>"
        )
