"""add ledger opening balances

Revision ID: 3d4e5f6a7b8c
Revises: 2c3d4e5f6a7b
Create Date: 2026-06-22

Opening balances per account for the derived ledger (carry-forward).
"""
from alembic import op
import sqlalchemy as sa


revision = "3d4e5f6a7b8c"
down_revision = "2c3d4e5f6a7b"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "ledger_opening_balances",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("account_code", sa.String(length=10), nullable=False),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("debit", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("credit", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("organization_id", "account_code", name="uq_opening_balance"),
    )


def downgrade():
    op.drop_table("ledger_opening_balances")
