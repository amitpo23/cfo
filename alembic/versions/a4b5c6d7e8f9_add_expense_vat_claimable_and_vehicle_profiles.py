"""add expense vat_claimable/doc_kind + vehicle_profiles (Israeli tax rules engine)

Revision ID: a4b5c6d7e8f9
Revises: e4f5a6b7c8d9
Create Date: 2026-07-20 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a4b5c6d7e8f9'
down_revision: Union[str, None] = 'e4f5a6b7c8d9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('expenses', sa.Column('vat_claimable', sa.Numeric(precision=12, scale=2), nullable=True))
    op.add_column('expenses', sa.Column('doc_kind', sa.String(length=20), nullable=True))
    op.create_table(
        'vehicle_profiles',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('organization_id', sa.Integer(), sa.ForeignKey('organizations.id'), nullable=False),
        sa.Column('label', sa.String(length=120), nullable=False),
        sa.Column('vehicle_kind', sa.String(length=20), nullable=False, server_default='private'),
        sa.Column('primarily_business', sa.Boolean(), nullable=True),
        sa.Column('attached_to_employee_with_use_value', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
    )
    op.create_index('ix_vehicle_profiles_organization_id', 'vehicle_profiles', ['organization_id'])


def downgrade() -> None:
    op.drop_index('ix_vehicle_profiles_organization_id', table_name='vehicle_profiles')
    op.drop_table('vehicle_profiles')
    op.drop_column('expenses', 'doc_kind')
    op.drop_column('expenses', 'vat_claimable')
