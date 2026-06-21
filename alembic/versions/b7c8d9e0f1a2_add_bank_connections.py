"""add bank_connections (Open Finance consent journeys)

Revision ID: b7c8d9e0f1a2
Revises: f6a7b8c9d0e1
Create Date: 2026-06-16 07:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b7c8d9e0f1a2'
down_revision: Union[str, None] = 'f6a7b8c9d0e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'bank_connections',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('organization_id', sa.Integer(), nullable=False),
        sa.Column('source', sa.String(length=50), nullable=True),
        sa.Column('connection_id', sa.String(length=255), nullable=True),
        sa.Column('provider_id', sa.String(length=100), nullable=True),
        sa.Column('bank_name', sa.String(length=255), nullable=True),
        sa.Column('status', sa.String(length=40), nullable=True),
        sa.Column('connect_url', sa.Text(), nullable=True),
        sa.Column('psu_id', sa.String(length=64), nullable=True),
        sa.Column('expiry_date', sa.DateTime(), nullable=True),
        sa.Column('accounts_count', sa.Integer(), nullable=True),
        sa.Column('transactions_count', sa.Integer(), nullable=True),
        sa.Column('last_refresh_at', sa.DateTime(), nullable=True),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('raw_data', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_bankconn_org_conn', 'bank_connections',
        ['organization_id', 'connection_id'], unique=True,
    )
    op.create_index(
        'ix_bankconn_org_status', 'bank_connections',
        ['organization_id', 'status'], unique=False,
    )


def downgrade() -> None:
    op.drop_index('ix_bankconn_org_status', table_name='bank_connections')
    op.drop_index('ix_bankconn_org_conn', table_name='bank_connections')
    op.drop_table('bank_connections')
