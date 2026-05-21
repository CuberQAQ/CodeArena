"""add cf_verification_code to users

Revision ID: a1b2c3d4e5f6
Revises: 233e80f71870
Create Date: 2026-05-19 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: str | None = "233e80f71870"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("cf_verification_code", sa.String(8), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "cf_verification_code")
