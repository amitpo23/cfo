"""Date indexes for /d/ window filters.

Not applied to production. Gate 0 still requires an owner-approved repair.

``/d/`` reads filter these columns and the matching index was missing:

- ``bank_transactions (account_id, transaction_date)`` — liquidity balances.
  ``ix_banktx_date`` already covers ``(organization_id, transaction_date)``
  (``window_rows``). This migration does not rebuild it.
- ``invoices (organization_id, issue_date)`` — cash-basis books and freshness.
  ``ix_invoice_due`` is ``due_date``.
- ``bills (organization_id, issue_date)`` — same. ``ix_bill_due`` is ``due_date``.
- ``expenses (organization_id, expense_date)`` — document months and freshness.

``journal_entries (organization_id, entry_date)`` is already ``ix_je_org_entry_date``.

PostgreSQL builds each index with ``CREATE INDEX CONCURRENTLY`` so writes are
not blocked. ``lock_timeout`` is 5s: if the ShareUpdateExclusiveLock is not
available, the statement aborts instead of queueing. ``statement_timeout`` is
cleared for the build. A concurrent index is allowed to run long; it does not
hold an access-exclusive lock. Both settings are reset before the migration
returns.

A failed concurrent build leaves an invalid index. ``CREATE INDEX CONCURRENTLY
IF NOT EXISTS`` then does nothing, because the name exists. Upgrade drops an
invalid index of the same name and creates it again.

Reviewed, not edited: no revision in this tree sets ``lock_timeout`` or
``statement_timeout``. Alembic will not re-run an applied file, so adding the
guards there would not change a database that already ran them. The revisions
that alter the large tables without those guards are ``e03f5b21c7d4`` and
``e6f7a8b9c0d1`` and ``f1a2b3c4d5e6`` (``bank_transactions``; the last one also
``UPDATE``s every row), ``7f6e5d4c3b2a`` (invoice/bill column rewrite and
non-concurrent indexes), ``f6a7b8c9d0e1`` (``invoices.allocation_number``),
``b0c1d2e3f4a5`` (``expenses.account_id`` plus a non-concurrent index), and the
other ``expenses`` column adds ``d4e5f6a7b8c9``, ``5f6a7b8c9d0e``,
``e5f6a7b8c9d0``, ``7c2e9a4f1d63``, ``a4b5c6d7e8f9``.

Revision ID: j38f2b18d6a7
Revises: g15b7d43e9f0
"""
from alembic import op
import sqlalchemy as sa


revision = "j38f2b18d6a7"
down_revision = "g15b7d43e9f0"
branch_labels = None
depends_on = None

LOCK_TIMEOUT = "5s"
# 0 disables statement_timeout. The concurrent build is the long part.
STATEMENT_TIMEOUT = "0"

DASHBOARD_DATE_INDEXES = (
    ("ix_banktx_account_date", "bank_transactions", ("account_id", "transaction_date")),
    ("ix_invoice_org_issue_date", "invoices", ("organization_id", "issue_date")),
    ("ix_bill_org_issue_date", "bills", ("organization_id", "issue_date")),
    ("ix_expense_org_date", "expenses", ("organization_id", "expense_date")),
)


def _set_timeouts() -> None:
    op.execute(f"SET lock_timeout = '{LOCK_TIMEOUT}'")
    op.execute(f"SET statement_timeout = {STATEMENT_TIMEOUT}")


def _reset_timeouts() -> None:
    op.execute("RESET lock_timeout")
    op.execute("RESET statement_timeout")


def _invalid_index(name: str) -> bool:
    # Called inside autocommit_block. Do not commit the connection: Alembic
    # holds a logical transaction over the AUTOCOMMIT isolation level, and
    # closing it makes the block's exit fail. Each statement still commits
    # at the server, so the following CREATE INDEX CONCURRENTLY is not inside
    # a transaction block.
    invalid = op.get_bind().execute(sa.text("""
        SELECT NOT i.indisvalid
        FROM pg_class c
        JOIN pg_index i ON i.indexrelid = c.oid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = current_schema()
          AND c.relname = :name
    """), {"name": name}).scalar()
    return invalid is True


def _upgrade_postgresql() -> None:
    with op.get_context().autocommit_block():
        _set_timeouts()
        for name, table, columns in DASHBOARD_DATE_INDEXES:
            if _invalid_index(name):
                op.execute(f'DROP INDEX CONCURRENTLY IF EXISTS "{name}"')
            column_sql = ", ".join(columns)
            op.execute(
                f'CREATE INDEX CONCURRENTLY IF NOT EXISTS "{name}" '
                f'ON "{table}" ({column_sql})'
            )
        _reset_timeouts()


def _downgrade_postgresql() -> None:
    with op.get_context().autocommit_block():
        _set_timeouts()
        for name, _table, _columns in DASHBOARD_DATE_INDEXES:
            op.execute(f'DROP INDEX CONCURRENTLY IF EXISTS "{name}"')
        _reset_timeouts()


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        _upgrade_postgresql()
        return
    for name, table, columns in DASHBOARD_DATE_INDEXES:
        op.create_index(name, table, list(columns))


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        _downgrade_postgresql()
        return
    for name, table, _columns in DASHBOARD_DATE_INDEXES:
        op.drop_index(name, table_name=table)
