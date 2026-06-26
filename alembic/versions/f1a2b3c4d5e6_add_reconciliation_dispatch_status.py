"""add reconciliation dispatch status

Revision ID: f1a2b3c4d5e6
Revises: e0f1a2b3c4d5
Create Date: 2026-06-19 18:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f1a2b3c4d5e6'
down_revision: Union[str, None] = 'e0f1a2b3c4d5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'bank_transactions',
        sa.Column('reconciliation_dispatch_status', sa.String(length=30), nullable=True),
    )
    op.add_column(
        'bank_transactions',
        sa.Column('reconciliation_dispatched_at', sa.DateTime(), nullable=True),
    )
    op.add_column(
        'bank_transactions',
        sa.Column('external_reconciliation_id', sa.String(length=255), nullable=True),
    )
    op.add_column(
        'bank_transactions',
        sa.Column('reconciliation_error', sa.Text(), nullable=True),
    )
    op.execute(
        "UPDATE bank_transactions "
        "SET reconciliation_dispatch_status = 'not_sent' "
        "WHERE reconciliation_dispatch_status IS NULL"
    )


def downgrade() -> None:
    op.drop_column('bank_transactions', 'reconciliation_error')
    op.drop_column('bank_transactions', 'external_reconciliation_id')
    op.drop_column('bank_transactions', 'reconciliation_dispatched_at')
    op.drop_column('bank_transactions', 'reconciliation_dispatch_status')
