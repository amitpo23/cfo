"""add balance_as_of + raw_account_type to accounts (Open Finance freshness + loan/card split)

Revision ID: b1c2d3e4f5a6
Revises: a3b4c5d6e7f8
Create Date: 2026-07-12 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b1c2d3e4f5a6'
down_revision: Union[str, None] = 'a3b4c5d6e7f8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('accounts', sa.Column('balance_as_of', sa.DateTime(), nullable=True))
    op.add_column('accounts', sa.Column('raw_account_type', sa.String(length=20), nullable=True))


def downgrade() -> None:
    op.drop_column('accounts', 'raw_account_type')
    op.drop_column('accounts', 'balance_as_of')
