"""add onboarding_tasks (codified per-business data-mapping checklist)

Revision ID: 1b2c3d4e5f60
Revises: 0a1f2e3d4c5b
Create Date: 2026-06-22 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '1b2c3d4e5f60'
down_revision: Union[str, None] = '0a1f2e3d4c5b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'onboarding_tasks',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('organization_id', sa.Integer(), nullable=False),
        sa.Column('source', sa.String(length=50), nullable=False),
        sa.Column('step', sa.String(length=64), nullable=False),
        sa.Column('seq', sa.Integer(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=True),
        sa.Column('result', sa.JSON(), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('attempts', sa.Integer(), nullable=True),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_onboarding_org_source_step', 'onboarding_tasks',
        ['organization_id', 'source', 'step'], unique=True,
    )


def downgrade() -> None:
    op.drop_index('ix_onboarding_org_source_step', table_name='onboarding_tasks')
    op.drop_table('onboarding_tasks')
