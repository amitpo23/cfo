"""add vehicle_deduction_profiles and home_office_profiles (ניכוי הוצאות רכב/בית)

Revision ID: 269ee41013f8
Revises: 3a8a9532010b
Create Date: 2026-07-04 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '269ee41013f8'
down_revision: Union[str, None] = '3a8a9532010b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'vehicle_deduction_profiles',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('organization_id', sa.Integer(), sa.ForeignKey('organizations.id'), nullable=False),
        sa.Column('tax_year', sa.Integer(), nullable=False),
        sa.Column('vehicle_label', sa.String(length=100), nullable=True),
        sa.Column('running_costs_annual', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('use_value_monthly', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('odometer_start', sa.Numeric(precision=10, scale=1), nullable=True),
        sa.Column('odometer_end', sa.Numeric(precision=10, scale=1), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.UniqueConstraint('organization_id', 'tax_year', 'vehicle_label', name='uq_vehicle_deduction_profile'),
    )

    op.create_table(
        'home_office_profiles',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('organization_id', sa.Integer(), sa.ForeignKey('organizations.id'), nullable=False, unique=True),
        sa.Column('office_sqm', sa.Numeric(precision=8, scale=2), nullable=False),
        sa.Column('total_home_sqm', sa.Numeric(precision=8, scale=2), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table('home_office_profiles')
    op.drop_table('vehicle_deduction_profiles')
