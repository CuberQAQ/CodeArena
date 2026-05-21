"""add time_factor to elo_history

Revision ID: n4o5p6q7r8s9
Revises: m3n4o5p6q7r8
Create Date: 2026-05-21 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "n4o5p6q7r8s9"
down_revision: str | None = "m3n4o5p6q7r8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("elo_history", sa.Column("time_factor", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("elo_history", "time_factor")
