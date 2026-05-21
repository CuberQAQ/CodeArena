from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPrimaryKeyMixin


class ProblemStatement(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "problem_statements"

    problem_id: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    contest_id: Mapped[int] = mapped_column(Integer, nullable=False)
    index: Mapped[str] = mapped_column(String(5), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    time_limit: Mapped[str | None] = mapped_column(String(100), nullable=True)
    memory_limit: Mapped[str | None] = mapped_column(String(100), nullable=True)
    body_html: Mapped[str] = mapped_column(Text, nullable=False)
    input_spec_html: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_spec_html: Mapped[str | None] = mapped_column(Text, nullable=True)
    samples: Mapped[dict] = mapped_column(JSON, nullable=False)
    note_html: Mapped[str | None] = mapped_column(Text, nullable=True)
    full_html: Mapped[str] = mapped_column(Text, nullable=False)
    scraped_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (Index("ix_problem_statements_contest_id_index", "contest_id", "index"),)

    def __repr__(self) -> str:
        return f"<ProblemStatement(id={self.id}, problem_id={self.problem_id})>"
