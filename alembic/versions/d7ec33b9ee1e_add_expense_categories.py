"""add expense_categories (org-scoped custom expense "cards")

Revision ID: d7ec33b9ee1e
Revises: 269ee41013f8
Create Date: 2026-07-06 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd7ec33b9ee1e'
down_revision: Union[str, None] = '269ee41013f8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'expense_categories',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('organization_id', sa.Integer(), sa.ForeignKey('organizations.id'), nullable=False),
        sa.Column('key', sa.String(length=100), nullable=False),
        sa.Column('name_he', sa.String(length=255), nullable=False),
        sa.Column('keywords', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
    )
    op.create_index(
        'ix_expensecat_org_key', 'expense_categories',
        ['organization_id', 'key'], unique=True,
    )
    op.create_index(
        'ix_expense_categories_organization_id', 'expense_categories', ['organization_id'],
    )


def downgrade() -> None:
    op.drop_index('ix_expense_categories_organization_id', table_name='expense_categories')
    op.drop_index('ix_expensecat_org_key', table_name='expense_categories')
    op.drop_table('expense_categories')
