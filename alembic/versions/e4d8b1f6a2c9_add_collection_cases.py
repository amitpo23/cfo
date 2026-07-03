"""add collection_cases table (manual collection case tracking)

Revision ID: e4d8b1f6a2c9
Revises: 7c2e9a4f1d63
Create Date: 2026-07-03 21:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e4d8b1f6a2c9'
down_revision: Union[str, None] = '7c2e9a4f1d63'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'collection_cases',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('organization_id', sa.Integer(), sa.ForeignKey('organizations.id'), nullable=False),
        sa.Column('contact_id', sa.Integer(), sa.ForeignKey('contacts.id'), nullable=True),
        sa.Column('invoice_ids', sa.JSON(), nullable=True),
        sa.Column('status', sa.String(length=20), server_default='open'),
        sa.Column('attempts', sa.JSON(), nullable=True),
        sa.Column('promise_date', sa.Date(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_collcase_org_contact', 'collection_cases', ['organization_id', 'contact_id'])
    op.create_index('ix_collcase_org_status', 'collection_cases', ['organization_id', 'status'])


def downgrade() -> None:
    op.drop_index('ix_collcase_org_status', table_name='collection_cases')
    op.drop_index('ix_collcase_org_contact', table_name='collection_cases')
    op.drop_table('collection_cases')
