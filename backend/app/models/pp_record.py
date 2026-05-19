import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDPrimaryKeyMixin


class PPRecord(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "pp_records"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    cf_problem_id: Mapped[str] = mapped_column(String(50), nullable=False)
    problem_rating: Mapped[int] = mapped_column(Integer, nullable=False)
    base_pp: Mapped[float] = mapped_column(Float, nullable=False)
    solved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    hints_used: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    wa_count: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    time_spent_minutes: Mapped[float] = mapped_column(Float, server_default="0.0", nullable=False)
    performance_factor: Mapped[float] = mapped_column(Float, server_default="1.0", nullable=False)
    final_pp: Mapped[float] = mapped_column(Float, server_default="0.0", nullable=False)
    overkill_multiplier: Mapped[float] = mapped_column(Float, server_default="1.0", nullable=False)

    # Relationships
    user = relationship("User", back_populates="pp_records")

    __table_args__ = (
        Index("ix_pp_records_user_base_pp", "user_id", base_pp.desc()),
        Index("ix_pp_records_user_final_pp", "user_id", final_pp.desc()),
    )

    def __repr__(self) -> str:
        return f"<PPRecord(id={self.id}, user_id={self.user_id}, cf_problem_id={self.cf_problem_id})>"
