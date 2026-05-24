"""add training indexes

Revision ID: q7r8s9t0u1v2
Revises: p6q7r8s9t0u1
Create Date: 2026-05-24 00:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "q7r8s9t0u1v2"
down_revision: str | None = "p6q7r8s9t0u1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # list_topics: solved-count query per topic
    op.create_index(
        "ix_training_problem_records_user_topic_solved",
        "training_problem_records",
        ["user_id", "topic_id", "solved"],
    )
    # submit_problem: dedup check
    op.create_index(
        "ix_training_problem_records_session_problem",
        "training_problem_records",
        ["session_id", "problem_id"],
    )
    # session recovery: find active session
    op.create_index(
        "ix_training_sessions_user_topic_status",
        "training_sessions",
        ["user_id", "topic_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_training_sessions_user_topic_status", table_name="training_sessions")
    op.drop_index("ix_training_problem_records_session_problem", table_name="training_problem_records")
    op.drop_index("ix_training_problem_records_user_topic_solved", table_name="training_problem_records")
