"""add free_play_sessions table

Revision ID: j0k1l2m3n4o5
Revises: i9j0k1l2m3n4
Create Date: 2026-05-21 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'j0k1l2m3n4o5'
down_revision: Union[str, None] = 'i9j0k1l2m3n4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'free_play_sessions',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('uuid_generate_v4()'), primary_key=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('problem_id', sa.String(50), nullable=False),
        sa.Column('problem_contest_id', sa.Integer(), nullable=False),
        sa.Column('problem_index', sa.String(10), nullable=False),
        sa.Column('problem_rating', sa.Integer(), nullable=False),
        sa.Column('problem_tags', sa.JSON(), nullable=True),
        sa.Column('status', sa.String(20), server_default='active', nullable=False),
        sa.Column('error_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('time_spent', sa.Float(), nullable=True),
        sa.Column('hints_used', sa.Integer(), server_default='0', nullable=False),
        sa.Column('elo_change', sa.Integer(), nullable=True),
        sa.Column('pp_change', sa.Float(), nullable=True),
        sa.Column('tokens_earned', sa.Integer(), server_default='0', nullable=False),
        sa.Column('s_value', sa.Float(), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        'ix_free_play_sessions_user_started',
        'free_play_sessions',
        ['user_id', sa.text('started_at DESC')],
    )


def downgrade() -> None:
    op.drop_index('ix_free_play_sessions_user_started', table_name='free_play_sessions')
    op.drop_table('free_play_sessions')
