"""initial schema

Revision ID: 233e80f71870
Revises:
Create Date: 2026-05-19 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '233e80f71870'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Enable uuid-ossp extension for UUID generation
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')

    # 1. users
    op.create_table(
        'users',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('uuid_generate_v4()'), primary_key=True),
        sa.Column('username', sa.String(50), unique=True, nullable=False),
        sa.Column('email', sa.String(255), unique=True, nullable=False),
        sa.Column('password_hash', sa.String(255), nullable=False),
        sa.Column('cf_handle', sa.String(100), unique=True, nullable=True),
        sa.Column('cf_handle_verified', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('elo', sa.Integer(), server_default=sa.text('1200'), nullable=False),
        sa.Column('pp', sa.Float(), server_default=sa.text('0'), nullable=False),
        sa.Column('tokens', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('daily_tokens_earned', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('daily_tokens_reset_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('is_admin', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    )

    # Indexes on users table
    op.create_index('ix_users_elo', 'users', ['elo'])
    op.create_index('ix_users_pp', 'users', ['pp'])

    # 2. elo_history
    op.create_table(
        'elo_history',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('uuid_generate_v4()'), primary_key=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('elo_before', sa.Integer(), nullable=False),
        sa.Column('elo_after', sa.Integer(), nullable=False),
        sa.Column('elo_change', sa.Integer(), nullable=False),
        sa.Column('reason', sa.String(50), nullable=False),
        sa.Column('reference_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    op.create_index('ix_elo_history_user_created', 'elo_history', ['user_id', sa.text('created_at DESC')])

    # 3. pp_records
    op.create_table(
        'pp_records',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('uuid_generate_v4()'), primary_key=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('cf_problem_id', sa.String(50), nullable=False),
        sa.Column('problem_rating', sa.Integer(), nullable=False),
        sa.Column('base_pp', sa.Float(), nullable=False),
        sa.Column('solved_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('hints_used', sa.Integer(), server_default=sa.text('0'), nullable=False),
    )
    op.create_index('ix_pp_records_user_base_pp', 'pp_records', ['user_id', sa.text('base_pp DESC')])

    # 4. challenge_sessions
    op.create_table(
        'challenge_sessions',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('uuid_generate_v4()'), primary_key=True),
        sa.Column('challenger_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('opponent_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('problem_id', sa.String(50), nullable=False),
        sa.Column('problem_rating', sa.Integer(), nullable=False),
        sa.Column('challenger_submissions', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('opponent_submissions', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('challenger_solved', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('opponent_solved', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('challenger_time', sa.Float(), nullable=True),
        sa.Column('opponent_time', sa.Float(), nullable=True),
        sa.Column('status', sa.String(20), server_default=sa.text('\'active\''), nullable=False),
        sa.Column('result', sa.String(20), nullable=True),
        sa.Column('elo_change', sa.Integer(), nullable=True),
        sa.Column('hints_used_challenger', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('hints_used_opponent', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_challenge_sessions_challenger_created', 'challenge_sessions', ['challenger_id', sa.text('created_at DESC')])
    op.create_index('ix_challenge_sessions_opponent_created', 'challenge_sessions', ['opponent_id', sa.text('created_at DESC')])

    # 5. topic_categories
    op.create_table(
        'topic_categories',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('uuid_generate_v4()'), primary_key=True),
        sa.Column('name', sa.String(100), unique=True, nullable=False),
        sa.Column('slug', sa.String(100), unique=True, nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('cf_tags', postgresql.JSONB(), nullable=True),
        sa.Column('display_order', sa.Integer(), server_default=sa.text('0'), nullable=False),
    )

    # 6. training_sessions
    op.create_table(
        'training_sessions',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('uuid_generate_v4()'), primary_key=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('topic_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('topic_categories.id', ondelete='CASCADE'), nullable=False),
        sa.Column('problems_solved', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('total_problems', sa.Integer(), nullable=False),
        sa.Column('streak_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('status', sa.String(20), server_default=sa.text('\'active\''), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    )

    # 7. training_problem_records
    op.create_table(
        'training_problem_records',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('uuid_generate_v4()'), primary_key=True),
        sa.Column('session_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('training_sessions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('topic_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('topic_categories.id', ondelete='CASCADE'), nullable=False),
        sa.Column('problem_id', sa.String(50), nullable=False),
        sa.Column('problem_rating', sa.Integer(), nullable=False),
        sa.Column('solved', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('attempts', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('time_spent', sa.Float(), nullable=True),
        sa.Column('hints_used', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('solved_at', sa.DateTime(timezone=True), nullable=True),
    )

    # 8. contest_sessions
    op.create_table(
        'contest_sessions',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('uuid_generate_v4()'), primary_key=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('contest_tier', sa.String(20), nullable=False),
        sa.Column('problems', postgresql.JSONB(), nullable=True),
        sa.Column('total_problems', sa.Integer(), nullable=False),
        sa.Column('problems_solved', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('submissions', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('time_limit', sa.Integer(), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('status', sa.String(20), server_default=sa.text('\'active\''), nullable=False),
        sa.Column('elo_change', sa.Integer(), nullable=True),
    )

    # 9. contest_problem_records
    op.create_table(
        'contest_problem_records',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('uuid_generate_v4()'), primary_key=True),
        sa.Column('contest_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('contest_sessions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('problem_id', sa.String(50), nullable=False),
        sa.Column('problem_rating', sa.Integer(), nullable=False),
        sa.Column('solved', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('attempts', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('time_spent', sa.Float(), nullable=True),
        sa.Column('solved_at', sa.DateTime(timezone=True), nullable=True),
    )

    # 10. token_transactions
    op.create_table(
        'token_transactions',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('uuid_generate_v4()'), primary_key=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('amount', sa.Integer(), nullable=False),
        sa.Column('type', sa.String(30), nullable=False),
        sa.Column('reference_type', sa.String(30), nullable=True),
        sa.Column('reference_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('balance_after', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )

    # 11. hint_purchases
    op.create_table(
        'hint_purchases',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('uuid_generate_v4()'), primary_key=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('problem_id', sa.String(50), nullable=False),
        sa.Column('problem_rating', sa.Integer(), nullable=False),
        sa.Column('hint_level', sa.Integer(), nullable=False),
        sa.Column('tokens_cost', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )

    # 12. system_config
    op.create_table(
        'system_config',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('uuid_generate_v4()'), primary_key=True),
        sa.Column('config_key', sa.String(100), unique=True, nullable=False),
        sa.Column('config_value', postgresql.JSONB(), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
    )


def downgrade() -> None:
    # Drop tables in reverse dependency order
    op.drop_table('system_config')
    op.drop_table('hint_purchases')
    op.drop_table('token_transactions')
    op.drop_table('contest_problem_records')
    op.drop_table('contest_sessions')
    op.drop_table('training_problem_records')
    op.drop_table('training_sessions')
    op.drop_table('topic_categories')
    op.drop_table('challenge_sessions')
    op.drop_table('pp_records')
    op.drop_table('elo_history')
    op.drop_table('users')

    op.execute('DROP EXTENSION IF EXISTS "uuid-ossp"')
