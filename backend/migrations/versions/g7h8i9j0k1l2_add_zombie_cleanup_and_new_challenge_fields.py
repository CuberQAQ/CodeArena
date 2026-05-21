"""add zombie cleanup and new challenge session fields

Revision ID: g7h8i9j0k1l2
Revises: f6g7h8i9j0k1
Create Date: 2026-05-21 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "g7h8i9j0k1l2"
down_revision: str | None = "f6g7h8i9j0k1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Add new columns to challenge_sessions
    op.add_column("challenge_sessions", sa.Column("opponent_elo_change", sa.Integer(), nullable=True))
    op.add_column("challenge_sessions", sa.Column("opponent_tokens_earned", sa.Integer(), nullable=True))
    op.add_column("challenge_sessions", sa.Column("problem_name", sa.String(200), nullable=True))

    # 2. Zombie session cleanup: mark all pending/active sessions as cancelled/expired
    op.execute(
        "UPDATE challenge_sessions SET status = 'cancelled', result = 'expired' WHERE status IN ('pending', 'active')"
    )


def downgrade() -> None:
    op.drop_column("challenge_sessions", "problem_name")
    op.drop_column("challenge_sessions", "opponent_tokens_earned")
    op.drop_column("challenge_sessions", "opponent_elo_change")
