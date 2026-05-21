"""CF sample user model for the global ranking regression pipeline.

Caches sampled Codeforces users along with their calculated equivalent PP
and regression-estimated PP values.  Each batch of samples is identified by
a monotonically increasing ``sample_batch`` number so that prior runs can be
queried or discarded.
"""

from sqlalchemy import Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class CFSampleUser(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A Codeforces user sampled for the global ranking regression model."""

    __tablename__ = "cf_sample_users"

    cf_handle: Mapped[str] = mapped_column(String(100), nullable=False, index=True, comment="Codeforces handle")
    cf_rating: Mapped[int] = mapped_column(Integer, nullable=False, comment="CF rating at time of sampling")
    country: Mapped[str | None] = mapped_column(String(10), nullable=True, comment="Country code (ISO 3166-1 alpha-2)")
    equivalent_pp: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="PP computed from CF submission history"
    )
    estimated_pp: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="PP estimated by the regression model + noise"
    )
    sample_batch: Mapped[int] = mapped_column(
        Integer, nullable=False, index=True, comment="Batch number for this sampling run"
    )
    regression_coefficients: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="JSON-encoded polynomial coefficients used for this batch",
    )

    def __repr__(self) -> str:
        return (
            f"<CFSampleUser(id={self.id}, handle={self.cf_handle}, "
            f"cf_rating={self.cf_rating}, batch={self.sample_batch})>"
        )
