"""add cashflow agreements + entries persistence

Revision ID: 2c3d4e5f6a7b
Revises: 1b2c3d4e5f60
Create Date: 2026-06-22

Persists the agreement-based cash-flow service (previously in-memory).
"""
from alembic import op
import sqlalchemy as sa


revision = "2c3d4e5f6a7b"
down_revision = "1b2c3d4e5f60"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "cashflow_agreements",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("agreement_id", sa.String(length=50), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("organization_id", "agreement_id", name="uq_cashflow_agreement"),
    )
    op.create_table(
        "cashflow_entries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("entry_id", sa.String(length=50), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("organization_id", "entry_id", name="uq_cashflow_entry"),
    )


def downgrade():
    op.drop_table("cashflow_entries")
    op.drop_table("cashflow_agreements")
