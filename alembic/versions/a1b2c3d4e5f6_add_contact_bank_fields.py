"""add bank account fields to contacts for Masav payments

Revision ID: a1b2c3d4e5f6
Revises: d741d91ce99c
Create Date: 2026-06-13 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = 'd741d91ce99c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('contacts', sa.Column('bank_code', sa.String(length=2), nullable=True))
    op.add_column('contacts', sa.Column('bank_branch', sa.String(length=3), nullable=True))
    op.add_column('contacts', sa.Column('bank_account_number', sa.String(length=20), nullable=True))
    op.add_column('contacts', sa.Column('bank_account_holder', sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column('contacts', 'bank_account_holder')
    op.drop_column('contacts', 'bank_account_number')
    op.drop_column('contacts', 'bank_branch')
    op.drop_column('contacts', 'bank_code')
