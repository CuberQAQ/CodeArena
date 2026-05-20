"""add submission_tracking table

Revision ID: f6g7h8i9j0k1
Revises: e5f6g7h8i9j0
Create Date: 2026-05-20 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'f6g7h8i9j0k1'
down_revision: Union[str, None] = 'd4e5f6g7h8i9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'submission_tracking',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('uuid_generate_v4()'), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('session_type', sa.String(20), nullable=False, comment='One of: pve, pvp, training, contest'),
        sa.Column('session_id', postgresql.UUID(as_uuid=True), nullable=False, comment='FK to the corresponding session table'),
        sa.Column('problem_id', sa.String(50), nullable=False, comment="CF problem ID, e.g. '800A'"),
        sa.Column('status', sa.String(20), server_default='pending', nullable=False, comment='One of: pending, matched, settled, timeout'),
        sa.Column('cf_submission_id', sa.Integer(), nullable=True, comment='CF submission ID once matched'),
        sa.Column('cf_verdict', sa.String(20), nullable=True, comment='CF verdict: OK, WRONG_ANSWER, TIME_LIMIT_EXCEEDED, etc.'),
        sa.Column('expected_at', sa.DateTime(timezone=True), nullable=False, comment='When the user was expected to submit on CF'),
        sa.Column('matched_at', sa.DateTime(timezone=True), nullable=True, comment='When the CF submission was matched'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_submission_tracking_pending', 'submission_tracking', ['status', 'user_id'])
    op.create_index('ix_submission_tracking_user_session', 'submission_tracking', ['user_id', 'session_type', 'session_id'])


def downgrade() -> None:
    op.drop_index('ix_submission_tracking_user_session', table_name='submission_tracking')
    op.drop_index('ix_submission_tracking_pending', table_name='submission_tracking')
    op.drop_table('submission_tracking')
