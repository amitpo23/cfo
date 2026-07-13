"""add filing_crosschecks (recorded three-way VAT crosscheck vs SUMIT books)

Revision ID: d3e4f5a6b7c8
Revises: c2d3e4f5a6b7
Create Date: 2026-07-13 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd3e4f5a6b7c8'
down_revision: Union[str, None] = 'c2d3e4f5a6b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'filing_crosschecks',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('organization_id', sa.Integer(), nullable=False),
        sa.Column('period', sa.String(length=20), nullable=False),
        sa.Column('basis', sa.String(length=20), nullable=False),
        sa.Column('books_input_vat', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('books_output_vat', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('source', sa.String(length=50), nullable=True),
        sa.Column('noted_by', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('organization_id', 'period', 'basis',
                             name='uq_filing_crosscheck_period_basis'),
    )


def downgrade() -> None:
    op.drop_table('filing_crosschecks')
