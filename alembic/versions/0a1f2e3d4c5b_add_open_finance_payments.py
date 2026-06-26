"""add open_finance_payments (Open Finance PIS payment tracking)

Revision ID: 0a1f2e3d4c5b
Revises: f1a2b3c4d5e6
Create Date: 2026-06-21 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0a1f2e3d4c5b'
down_revision: Union[str, None] = 'f1a2b3c4d5e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'open_finance_payments',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('organization_id', sa.Integer(), nullable=False),
        sa.Column('external_payment_id', sa.String(length=255), nullable=False),
        sa.Column('status', sa.String(length=40), nullable=True),
        sa.Column('amount', sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column('currency', sa.String(length=10), nullable=True),
        sa.Column('raw_data', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_open_finance_payments_organization_id'),
        'open_finance_payments', ['organization_id'], unique=False,
    )
    op.create_index(
        op.f('ix_open_finance_payments_external_payment_id'),
        'open_finance_payments', ['external_payment_id'], unique=False,
    )
    op.create_index(
        'ix_ofpayment_org_ext', 'open_finance_payments',
        ['organization_id', 'external_payment_id'], unique=True,
    )


def downgrade() -> None:
    op.drop_index('ix_ofpayment_org_ext', table_name='open_finance_payments')
    op.drop_index(
        op.f('ix_open_finance_payments_external_payment_id'),
        table_name='open_finance_payments',
    )
    op.drop_index(
        op.f('ix_open_finance_payments_organization_id'),
        table_name='open_finance_payments',
    )
    op.drop_table('open_finance_payments')
