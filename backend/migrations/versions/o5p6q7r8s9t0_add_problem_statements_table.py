"""add problem_statements table

Revision ID: o5p6q7r8s9t0
Revises: n4o5p6q7r8s9
Create Date: 2026-05-22 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "o5p6q7r8s9t0"
down_revision: str | None = "n4o5p6q7r8s9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "problem_statements",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("uuid_generate_v4()"),
            primary_key=True,
        ),
        sa.Column("problem_id", sa.String(20), unique=True, nullable=False),
        sa.Column("contest_id", sa.Integer(), nullable=False),
        sa.Column("index", sa.String(5), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("time_limit", sa.String(100), nullable=True),
        sa.Column("memory_limit", sa.String(100), nullable=True),
        sa.Column("body_html", sa.Text(), nullable=False),
        sa.Column("input_spec_html", sa.Text(), nullable=True),
        sa.Column("output_spec_html", sa.Text(), nullable=True),
        sa.Column("samples", postgresql.JSON(), nullable=False),
        sa.Column("note_html", sa.Text(), nullable=True),
        sa.Column("full_html", sa.Text(), nullable=False),
        sa.Column(
            "scraped_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_problem_statements_contest_id_index",
        "problem_statements",
        ["contest_id", "index"],
    )


def downgrade() -> None:
    op.drop_index("ix_problem_statements_contest_id_index", table_name="problem_statements")
    op.drop_table("problem_statements")
