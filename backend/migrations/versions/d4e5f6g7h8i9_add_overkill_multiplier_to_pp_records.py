"""add overkill_multiplier to pp_records

Revision ID: d4e5f6g7h8i9
Revises: c3d4e5f6g7h8
Create Date: 2026-05-20 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'd4e5f6g7h8i9'
down_revision: Union[str, None] = ('c3d4e5f6g7h8', 'e5f6g7h8i9j0')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'pp_records',
        sa.Column('overkill_multiplier', sa.Float(), server_default='1.0', nullable=False),
    )


def downgrade() -> None:
    op.drop_column('pp_records', 'overkill_multiplier')
