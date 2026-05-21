"""add check_ins table

Revision ID: l2m3n4o5p6q7
Revises: k1l2m3n4o5p6
Create Date: 2026-05-21 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "l2m3n4o5p6q7"
down_revision: str | None = "k1l2m3n4o5p6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "check_ins",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("uuid_generate_v4()"), nullable=False),
        sa.Column(
            "user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("checkin_date", sa.Date(), nullable=False),
        sa.Column("streak_days", sa.Integer(), nullable=False),
        sa.Column("is_makeup", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("tokens_awarded", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "ix_check_ins_user_id",
        "check_ins",
        ["user_id"],
    )

    # Prevent duplicate check-ins for the same user on the same date
    op.create_unique_constraint(
        "uq_check_ins_user_date",
        "check_ins",
        ["user_id", "checkin_date"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_check_ins_user_date", "check_ins", type_="unique")
    op.drop_index("ix_check_ins_user_id", table_name="check_ins")
    op.drop_table("check_ins")
