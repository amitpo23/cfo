"""add Hashavshevet chart provenance to accounts

Revision ID: c5d6e7f8a9b0
Revises: b4c5d6e7f8a9
Create Date: 2026-07-30 12:00:00.000000

The existing ``accounts`` table is the connector chart-of-accounts data plane.
This additive migration gives it lossless source fields and adds an immutable
change-audit table.  It performs no source import and no external calls.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c5d6e7f8a9b0"
down_revision: Union[str, None] = "b4c5d6e7f8a9"
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


def _unique_constraints(table_name: str) -> set[str]:
    return {
        constraint["name"]
        for constraint in sa.inspect(op.get_bind()).get_unique_constraints(table_name)
        if constraint["name"]
    }


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        # PostgreSQL stores AccountType as a native enum.  Removing an enum
        # value is destructive, so downgrade intentionally leaves OTHER.
        op.execute("ALTER TYPE accounttype ADD VALUE IF NOT EXISTS 'OTHER'")

    existing = _columns("accounts")
    additions = [
        sa.Column("source_account_code", sa.String(length=100), nullable=True),
        sa.Column("source_name", sa.String(length=255), nullable=True),
        sa.Column("source_classification", sa.String(length=50), nullable=True),
        sa.Column("sort_code", sa.String(length=50), nullable=True),
        sa.Column("vat_key", sa.String(length=50), nullable=True),
        sa.Column("tax_id", sa.String(length=20), nullable=True),
        sa.Column("withholding_rate", sa.Numeric(7, 4), nullable=True),
        sa.Column("withholding_valid_until", sa.Date(), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "is_historical",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("source_status_code", sa.String(length=10), nullable=True),
        sa.Column("row_hash", sa.String(length=64), nullable=True),
        sa.Column("source_file_hash", sa.String(length=64), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sumit_account_code", sa.String(length=100), nullable=True),
    ]
    for column in additions:
        if column.name not in existing:
            op.add_column("accounts", column)

    constraint_name = "uq_account_org_source_account_code"
    if constraint_name not in _indexes("accounts") | _unique_constraints("accounts"):
        # A unique index enforces the same pair-wise invariant on both SQLite
        # and PostgreSQL without rebuilding an already-populated SQLite table.
        op.create_index(
            constraint_name,
            "accounts",
            ["organization_id", "source_account_code"],
            unique=True,
        )

    if "account_import_changes" not in sa.inspect(bind).get_table_names():
        op.create_table(
            "account_import_changes",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("organization_id", sa.Integer(), nullable=False),
            sa.Column("account_id", sa.Integer(), nullable=False),
            sa.Column("source_account_code", sa.String(length=100), nullable=False),
            sa.Column("source_file_hash", sa.String(length=64), nullable=False),
            sa.Column("old_row_hash", sa.String(length=64), nullable=True),
            sa.Column("new_row_hash", sa.String(length=64), nullable=False),
            sa.Column("changes", sa.JSON(), nullable=False),
            sa.Column(
                "changed_at", sa.DateTime(timezone=True), nullable=False
            ),
            sa.ForeignKeyConstraint(["account_id"], ["accounts.id"]),
            sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_account_import_changes_account_id",
            "account_import_changes",
            ["account_id"],
            unique=False,
        )
        op.create_index(
            "ix_account_import_changes_organization_id",
            "account_import_changes",
            ["organization_id"],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    if "account_import_changes" in sa.inspect(bind).get_table_names():
        op.drop_index(
            "ix_account_import_changes_organization_id",
            table_name="account_import_changes",
        )
        op.drop_index(
            "ix_account_import_changes_account_id",
            table_name="account_import_changes",
        )
        op.drop_table("account_import_changes")

    constraint_name = "uq_account_org_source_account_code"
    if constraint_name in _indexes("accounts"):
        op.drop_index(constraint_name, table_name="accounts")

    existing = _columns("accounts")
    for column_name in [
        "sumit_account_code",
        "synced_at",
        "observed_at",
        "source_file_hash",
        "row_hash",
        "source_status_code",
        "is_historical",
        "is_active",
        "withholding_valid_until",
        "withholding_rate",
        "tax_id",
        "vat_key",
        "sort_code",
        "source_classification",
        "source_name",
        "source_account_code",
    ]:
        if column_name in existing:
            op.drop_column("accounts", column_name)

