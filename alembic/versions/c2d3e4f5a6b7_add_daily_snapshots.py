"""add daily_snapshots (cron/daily-close — per-org daily metric snapshot)

Revision ID: c2d3e4f5a6b7
Revises: b1c2d3e4f5a6
Create Date: 2026-07-12 00:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c2d3e4f5a6b7'
down_revision: Union[str, None] = 'b1c2d3e4f5a6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'daily_snapshots',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('organization_id', sa.Integer(), sa.ForeignKey('organizations.id'), nullable=False),
        sa.Column('snapshot_date', sa.Date(), nullable=False),
        sa.Column('cash_balance', sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column('ar_total', sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column('ap_total', sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column('month_net_profit', sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column('undocumented_total', sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column('data_quality_issues', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.UniqueConstraint('organization_id', 'snapshot_date', name='uq_daily_snapshot_org_date'),
    )


def downgrade() -> None:
    op.drop_table('daily_snapshots')
