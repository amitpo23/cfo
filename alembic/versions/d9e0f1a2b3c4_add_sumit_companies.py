"""add sumit_companies (multi-company office model)

Revision ID: d9e0f1a2b3c4
Revises: c8d9e0f1a2b3
Create Date: 2026-06-16 07:55:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd9e0f1a2b3c4'
down_revision: Union[str, None] = 'c8d9e0f1a2b3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'sumit_companies',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('office_organization_id', sa.Integer(), nullable=False),
        sa.Column('company_id', sa.String(length=50), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=True),
        sa.Column('target_organization_id', sa.Integer(), nullable=True),
        sa.Column('last_synced_at', sa.DateTime(), nullable=True),
        sa.Column('raw_data', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['office_organization_id'], ['organizations.id']),
        sa.ForeignKeyConstraint(['target_organization_id'], ['organizations.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_sumitco_office_company', 'sumit_companies',
        ['office_organization_id', 'company_id'], unique=True,
    )


def downgrade() -> None:
    op.drop_index('ix_sumitco_office_company', table_name='sumit_companies')
    op.drop_table('sumit_companies')
