"""add morning-cycle columns to daily_snapshots (PR4 of bookkeeper daily-cycle plan)

Revision ID: b3c4d5e6f7a8
Revises: f8a9b0c1d2e3
Create Date: 2026-07-20 00:00:00.000001

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b3c4d5e6f7a8'
down_revision: Union[str, None] = 'f8a9b0c1d2e3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('daily_snapshots', sa.Column('unreconciled_count', sa.Integer(), nullable=True))
    op.add_column('daily_snapshots', sa.Column('open_expense_drafts', sa.Integer(), nullable=True))
    op.add_column('daily_snapshots', sa.Column('exceptions_over_48h', sa.Integer(), nullable=True))
    op.add_column('daily_snapshots', sa.Column('parity_status', sa.String(length=20), nullable=True))
    op.add_column('daily_snapshots', sa.Column('credit_headroom', sa.Numeric(precision=14, scale=2), nullable=True))
    op.add_column('daily_snapshots', sa.Column('credit_breach_date', sa.Date(), nullable=True))
    op.add_column('daily_snapshots', sa.Column('cycle_status', sa.String(length=10), nullable=True))
    op.add_column('daily_snapshots', sa.Column('days_to_next_deadline', sa.Integer(), nullable=True))
    op.add_column('daily_snapshots', sa.Column('open_items', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('daily_snapshots', 'open_items')
    op.drop_column('daily_snapshots', 'days_to_next_deadline')
    op.drop_column('daily_snapshots', 'cycle_status')
    op.drop_column('daily_snapshots', 'credit_breach_date')
    op.drop_column('daily_snapshots', 'credit_headroom')
    op.drop_column('daily_snapshots', 'parity_status')
    op.drop_column('daily_snapshots', 'exceptions_over_48h')
    op.drop_column('daily_snapshots', 'open_expense_drafts')
    op.drop_column('daily_snapshots', 'unreconciled_count')
