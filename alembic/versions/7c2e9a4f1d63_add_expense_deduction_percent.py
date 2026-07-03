"""add deduction_percent to expenses (partial tax-deductibility, e.g. vehicle/phone)

Revision ID: 7c2e9a4f1d63
Revises: c0ffee010203
Create Date: 2026-07-03 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '7c2e9a4f1d63'
down_revision: Union[str, None] = 'c0ffee010203'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('expenses', sa.Column('deduction_percent', sa.Numeric(precision=5, scale=2), nullable=True))


def downgrade() -> None:
    op.drop_column('expenses', 'deduction_percent')
