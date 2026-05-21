"""add challenger_tokens_earned to challenge_sessions

Revision ID: h8i9j0k1l2m3
Revises: g7h8i9j0k1l2
Create Date: 2026-05-21 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "h8i9j0k1l2m3"
down_revision: str | None = "g7h8i9j0k1l2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("challenge_sessions", sa.Column("challenger_tokens_earned", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("challenge_sessions", "challenger_tokens_earned")
