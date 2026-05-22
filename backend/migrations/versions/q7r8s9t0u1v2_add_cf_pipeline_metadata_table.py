"""add cf_pipeline_metadata table

Revision ID: q7r8s9t0u1v2
Revises: p6q7r8s9t0u1
Create Date: 2026-05-22 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "q7r8s9t0u1v2"
down_revision: str | None = "p6q7r8s9t0u1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "cf_pipeline_metadata",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "sample_batch",
            sa.Integer(),
            nullable=False,
            comment="Batch number this metadata belongs to",
        ),
        sa.Column(
            "total_rated_users",
            sa.Integer(),
            nullable=False,
            comment="Total CF rated users from ratedList API",
        ),
        sa.Column(
            "rating_histogram",
            postgresql.JSONB(),
            nullable=False,
            comment="JSON: {bucket_midpoint: count} histogram of CF ratings",
        ),
        sa.Column(
            "regression_coefficients",
            postgresql.JSONB(),
            nullable=True,
            comment="JSON: [a0, a1, a2] polynomial coefficients for PP estimation",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("cf_pipeline_metadata")
