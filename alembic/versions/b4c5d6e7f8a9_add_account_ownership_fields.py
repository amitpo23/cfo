"""add account ownership matching fields (Package H)

Revision ID: b4c5d6e7f8a9
Revises: a5b6c7d8e9f0
Create Date: 2026-07-27 12:00:00.000000

Package H (2026-07-27b moshko-memory-and-whatsapp plan) — accurate ownership
matching. Open Finance returns ``ownerInfo: {nationalId, fullName}`` on every
Account (docs/OPEN_FINANCE_KNOWLEDGE_BASE.md:248), but
``open_finance_connector._normalize_account`` previously discarded it and
``accounts`` had nowhere to store it. Additive and idempotent, matching the
convention set by e6f7a8b9c0d1_add_bank_transaction_provisional.py: every
column is added only if missing, so a database that already carries a column
via the ORM's create_all (pre-Alembic drift) is left alone.

Columns are populated by the next regular daily sync — no dedicated API call
is made for this (API-call cost discipline).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b4c5d6e7f8a9"
down_revision: Union[str, None] = "a5b6c7d8e9f0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _columns(table_name: str) -> set[str]:
    return {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns(table_name)
    }


def _indexes(table_name: str) -> set[str]:
    return {
        index["name"]
        for index in sa.inspect(op.get_bind()).get_indexes(table_name)
    }


def upgrade() -> None:
    account_columns = _columns("accounts")
    if "owner_national_id" not in account_columns:
        op.add_column(
            "accounts",
            sa.Column("owner_national_id", sa.String(length=20), nullable=True),
        )
    if "owner_national_id" in _columns("accounts") and (
        "ix_accounts_owner_national_id" not in _indexes("accounts")
    ):
        op.create_index(
            "ix_accounts_owner_national_id",
            "accounts",
            ["owner_national_id"],
            unique=False,
        )
    if "owner_name" not in account_columns:
        op.add_column(
            "accounts",
            sa.Column("owner_name", sa.String(length=255), nullable=True),
        )
    if "is_primary_business_account" not in account_columns:
        op.add_column(
            "accounts",
            sa.Column("is_primary_business_account", sa.Boolean(), nullable=True),
        )

    org_columns = _columns("organizations")
    if "ownership_reviewed_at" not in org_columns:
        op.add_column(
            "organizations",
            sa.Column("ownership_reviewed_at", sa.DateTime(), nullable=True),
        )


def downgrade() -> None:
    account_columns = _columns("accounts")
    if "ix_accounts_owner_national_id" in _indexes("accounts"):
        op.drop_index("ix_accounts_owner_national_id", table_name="accounts")
    if "owner_national_id" in account_columns:
        op.drop_column("accounts", "owner_national_id")
    if "owner_name" in account_columns:
        op.drop_column("accounts", "owner_name")
    if "is_primary_business_account" in account_columns:
        op.drop_column("accounts", "is_primary_business_account")

    org_columns = _columns("organizations")
    if "ownership_reviewed_at" in org_columns:
        op.drop_column("organizations", "ownership_reviewed_at")
