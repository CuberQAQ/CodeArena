"""add performance factor fields to pp_records

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-05-20 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b2c3d4e5f6a7"
down_revision: str | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Add new columns with safe defaults
    op.add_column(
        "pp_records",
        sa.Column("wa_count", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "pp_records",
        sa.Column("time_spent_minutes", sa.Float(), server_default="0.0", nullable=False),
    )
    op.add_column(
        "pp_records",
        sa.Column("performance_factor", sa.Float(), server_default="1.0", nullable=False),
    )
    op.add_column(
        "pp_records",
        sa.Column("final_pp", sa.Float(), server_default="0.0", nullable=False),
    )

    # Backfill: set final_pp = base_pp for existing records
    op.execute("UPDATE pp_records SET final_pp = base_pp WHERE final_pp = 0.0")

    # Add new index on final_pp for aggregation queries
    op.create_index(
        "ix_pp_records_user_final_pp",
        "pp_records",
        ["user_id", sa.text("final_pp DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_pp_records_user_final_pp", table_name="pp_records")
    op.drop_column("pp_records", "final_pp")
    op.drop_column("pp_records", "performance_factor")
    op.drop_column("pp_records", "time_spent_minutes")
    op.drop_column("pp_records", "wa_count")
