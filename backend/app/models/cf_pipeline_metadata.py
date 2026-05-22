"""CF pipeline metadata model for global ranking estimation.

Stores metadata from each pipeline run: total rated users count,
rating histogram for CDF construction, and regression coefficients.
Used by the ranking API to estimate global percentiles based on the
full CF user base rather than the sampled subset.
"""

from sqlalchemy import DateTime, Integer, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class CFPipelineMetadata(Base):
    """Metadata from a CF sampling pipeline run for CDF-based ranking estimation."""

    __tablename__ = "cf_pipeline_metadata"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sample_batch: Mapped[int] = mapped_column(Integer, nullable=False, comment="Batch number this metadata belongs to")
    total_rated_users: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="Total CF rated users from ratedList API"
    )
    rating_histogram: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        comment="JSON: {bucket_midpoint: count} histogram of CF ratings",
    )
    regression_coefficients: Mapped[list | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="JSON: [a0, a1, a2] polynomial coefficients for PP estimation",
    )
    created_at = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"<CFPipelineMetadata(id={self.id}, batch={self.sample_batch}, total_rated={self.total_rated_users})>"
