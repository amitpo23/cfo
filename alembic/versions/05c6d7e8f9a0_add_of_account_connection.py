"""Persist the Open Finance consent connection on each account.

Revision ID: 05c6d7e8f9a0
Revises: 04b5c6d7e8f9
Create Date: 2026-08-13

The column is deliberately nullable: legacy accounts cannot be assigned to a
bank consent safely without source evidence.  The next normal Open Finance
account sync fills it from the provider's ``connectionId`` field.
"""
from alembic import op
import sqlalchemy as sa


revision = "05c6d7e8f9a0"
down_revision = "04b5c6d7e8f9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "accounts",
        sa.Column("open_finance_connection_id", sa.String(length=255), nullable=True),
    )
    op.create_index(
        "ix_account_org_of_connection",
        "accounts",
        ["organization_id", "open_finance_connection_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_account_org_of_connection", table_name="accounts")
    op.drop_column("accounts", "open_finance_connection_id")
