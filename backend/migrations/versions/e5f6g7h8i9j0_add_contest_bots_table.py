"""add contest_bots table

Revision ID: e5f6g7h8i9j0
Revises: b2c3d4e5f6a7
Create Date: 2026-05-20 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'e5f6g7h8i9j0'
down_revision: Union[str, None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'contest_bots',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('uuid_generate_v4()'), nullable=False),
        sa.Column('contest_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('bot_name', sa.String(50), nullable=False),
        sa.Column('bot_elo', sa.Integer(), nullable=False),
        sa.Column('problems_solved', sa.Integer(), server_default='0', nullable=False),
        sa.Column('solved_problem_ids', postgresql.JSON(), nullable=True),
        sa.Column('total_attempts', sa.Integer(), server_default='0', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['contest_id'], ['contest_sessions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    op.drop_table('contest_bots')
