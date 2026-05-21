"""add overkill_multiplier to pp_records

Revision ID: d4e5f6g7h8i9
Revises: c3d4e5f6g7h8
Create Date: 2026-05-20 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d4e5f6g7h8i9"
down_revision: str | None = ("c3d4e5f6g7h8", "e5f6g7h8i9j0")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "pp_records",
        sa.Column("overkill_multiplier", sa.Float(), server_default="1.0", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("pp_records", "overkill_multiplier")
