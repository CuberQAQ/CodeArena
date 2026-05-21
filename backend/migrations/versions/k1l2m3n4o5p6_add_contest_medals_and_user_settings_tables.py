"""add contest_medals and user_settings tables

Revision ID: k1l2m3n4o5p6
Revises: j0k1l2m3n4o5
Create Date: 2026-05-21 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "k1l2m3n4o5p6"
down_revision: str | None = "j0k1l2m3n4o5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- contest_medals table ---
    op.create_table(
        "contest_medals",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("uuid_generate_v4()"), nullable=False),
        sa.Column(
            "user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "contest_session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("contest_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "medal_level",
            sa.String(30),
            nullable=False,
            comment="XCPC tier level: world_finals, ec_final, regional, provincial",
        ),
        sa.Column("medal_type", sa.String(10), nullable=False, comment="Medal type: gold, silver, bronze"),
        sa.Column("pr_value", sa.Integer(), nullable=False, comment="Performance Rating at the time of awarding"),
        sa.Column("awarded_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "contest_session_id", name="uq_contest_medals_user_session"),
    )

    op.create_index(
        "ix_contest_medals_user_id",
        "contest_medals",
        ["user_id"],
    )

    # --- user_settings table ---
    op.create_table(
        "user_settings",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("uuid_generate_v4()"), nullable=False),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            unique=True,
            nullable=False,
        ),
        sa.Column("display_mode", sa.String(20), server_default="medal", nullable=False),
        sa.Column("avatar_path", sa.String(500), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("user_settings")
    op.drop_index("ix_contest_medals_user_id", table_name="contest_medals")
    op.drop_table("contest_medals")
