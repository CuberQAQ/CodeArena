"""Submission tracking model for async CF submission polling.

Stores pending submissions that need to be tracked against the Codeforces
API.  The background task scheduler periodically polls CF ``user.status``
for each user with pending submissions, matches results, and triggers
settlement when a final verdict (AC/WA/TLE/RE/MLE) is reached.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDPrimaryKeyMixin


class SubmissionTracking(Base, UUIDPrimaryKeyMixin):
    """Tracks a user's CF submission against a game session.

    Lifecycle:
        pending -> matched -> settled
        pending -> timeout
    """

    __tablename__ = "submission_tracking"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    session_type: Mapped[str] = mapped_column(
        String(20), nullable=False,
        comment="One of: pve, pvp, training, contest",
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False,
        comment="FK to the corresponding session table",
    )
    problem_id: Mapped[str] = mapped_column(
        String(50), nullable=False,
        comment="CF problem ID, e.g. '800A'",
    )
    status: Mapped[str] = mapped_column(
        String(20), server_default="pending", nullable=False,
        comment="One of: pending, matched, settled, timeout",
    )
    cf_submission_id: Mapped[int | None] = mapped_column(
        Integer, nullable=True,
        comment="CF submission ID once matched",
    )
    cf_verdict: Mapped[str | None] = mapped_column(
        String(20), nullable=True,
        comment="CF verdict: OK, WRONG_ANSWER, TIME_LIMIT_EXCEEDED, etc.",
    )
    expected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        comment="When the user was expected to submit on CF",
    )
    matched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
        comment="When the CF submission was matched",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )

    # Relationships
    user = relationship("User", foreign_keys=[user_id])

    __table_args__ = (
        Index(
            "ix_submission_tracking_pending",
            "status",
            "user_id",
        ),
        Index(
            "ix_submission_tracking_user_session",
            "user_id",
            "session_type",
            "session_id",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<SubmissionTracking(id={self.id}, status={self.status}, "
            f"session_type={self.session_type})>"
        )
