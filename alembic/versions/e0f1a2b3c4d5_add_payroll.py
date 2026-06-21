"""add payroll module (employees + payslips)

Revision ID: e0f1a2b3c4d5
Revises: d9e0f1a2b3c4
Create Date: 2026-06-16 10:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e0f1a2b3c4d5'
down_revision: Union[str, None] = 'd9e0f1a2b3c4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'employees',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('organization_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('tax_id', sa.String(length=20), nullable=True),
        sa.Column('email', sa.String(length=255), nullable=True),
        sa.Column('phone', sa.String(length=50), nullable=True),
        sa.Column('gross_salary', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('credit_points', sa.Numeric(precision=4, scale=2), nullable=True),
        sa.Column('pension_pct', sa.Numeric(precision=4, scale=2), nullable=True),
        sa.Column('start_date', sa.Date(), nullable=True),
        sa.Column('bank_code', sa.String(length=2), nullable=True),
        sa.Column('bank_branch', sa.String(length=3), nullable=True),
        sa.Column('bank_account_number', sa.String(length=20), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_employee_org', 'employees', ['organization_id', 'is_active'])

    op.create_table(
        'payslips',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('organization_id', sa.Integer(), nullable=False),
        sa.Column('employee_id', sa.Integer(), nullable=False),
        sa.Column('year', sa.Integer(), nullable=False),
        sa.Column('month', sa.Integer(), nullable=False),
        sa.Column('gross', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('income_tax', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('ni_employee', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('health_tax', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('pension_employee', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('net', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('employer_ni', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('employer_pension', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('employer_severance', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('employer_cost', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id']),
        sa.ForeignKeyConstraint(['employee_id'], ['employees.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_payslip_unique', 'payslips',
                    ['organization_id', 'employee_id', 'year', 'month'], unique=True)
    op.create_index('ix_payslip_period', 'payslips', ['organization_id', 'year', 'month'])


def downgrade() -> None:
    op.drop_index('ix_payslip_period', table_name='payslips')
    op.drop_index('ix_payslip_unique', table_name='payslips')
    op.drop_table('payslips')
    op.drop_index('ix_employee_org', table_name='employees')
    op.drop_table('employees')
