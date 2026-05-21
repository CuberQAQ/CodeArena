"""add cf_sample_users table

Revision ID: m3n4o5p6q7r8
Revises: l2m3n4o5p6q7
Create Date: 2026-05-21 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'm3n4o5p6q7r8'
down_revision: Union[str, None] = 'l2m3n4o5p6q7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'cf_sample_users',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('uuid_generate_v4()'), nullable=False),
        sa.Column('cf_handle', sa.String(100), nullable=False, comment='Codeforces handle'),
        sa.Column('cf_rating', sa.Integer(), nullable=False, comment='CF rating at time of sampling'),
        sa.Column('country', sa.String(10), nullable=True, comment='Country code (ISO 3166-1 alpha-2)'),
        sa.Column('equivalent_pp', sa.Float(), nullable=True, comment='PP computed from CF submission history'),
        sa.Column('estimated_pp', sa.Float(), nullable=True, comment='PP estimated by the regression model + noise'),
        sa.Column('sample_batch', sa.Integer(), nullable=False, comment='Batch number for this sampling run'),
        sa.Column('regression_coefficients', sa.Text(), nullable=True, comment='JSON-encoded polynomial coefficients used for this batch'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_index('ix_cf_sample_users_cf_handle', 'cf_sample_users', ['cf_handle'])
    op.create_index('ix_cf_sample_users_sample_batch', 'cf_sample_users', ['sample_batch'])


def downgrade() -> None:
    op.drop_index('ix_cf_sample_users_sample_batch', table_name='cf_sample_users')
    op.drop_index('ix_cf_sample_users_cf_handle', table_name='cf_sample_users')
    op.drop_table('cf_sample_users')
