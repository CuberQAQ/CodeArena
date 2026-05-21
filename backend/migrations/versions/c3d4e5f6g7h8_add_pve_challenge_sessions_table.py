"""add pve_challenge_sessions table

Revision ID: c3d4e5f6g7h8
Revises: b2c3d4e5f6g7
Create Date: 2026-05-20 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "c3d4e5f6g7h8"
down_revision: str | None = "b2c3d4e5f6g7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "pve_challenge_sessions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("uuid_generate_v4()"),
            primary_key=True,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("problem_id", sa.String(50), nullable=False),
        sa.Column("problem_rating", sa.Integer(), nullable=False),
        sa.Column("problem_tags", postgresql.JSON(), nullable=True),
        sa.Column("status", sa.String(20), server_default="active", nullable=False),
        sa.Column("error_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("time_spent", sa.Float(), nullable=True),
        sa.Column("hints_used", sa.Integer(), server_default="0", nullable=False),
        sa.Column("elo_change", sa.Integer(), nullable=True),
        sa.Column("pp_change", sa.Float(), nullable=True),
        sa.Column("s_value", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_pve_sessions_user_created",
        "pve_challenge_sessions",
        ["user_id", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_pve_sessions_user_created", table_name="pve_challenge_sessions")
    op.drop_table("pve_challenge_sessions")
