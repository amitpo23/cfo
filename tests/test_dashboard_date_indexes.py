"""Dashboard date indexes: the ORM contract and the SQLite migration path.

PostgreSQL uses CREATE INDEX CONCURRENTLY. That path is not run here.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from cfo.models import BankTransaction, Bill, Expense, Invoice


REPO = Path(__file__).resolve().parents[1]
MIGRATION = REPO / "alembic" / "versions" / "j38f2b18d6a7_dashboard_date_indexes.py"


def _migration():
    spec = importlib.util.spec_from_file_location("dashboard_date_indexes", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_model_indexes_match_the_migration():
    migration = _migration()
    tables = {
        "bank_transactions": BankTransaction,
        "invoices": Invoice,
        "bills": Bill,
        "expenses": Expense,
    }
    declared = {
        (name, table, tuple(columns))
        for name, table, columns in migration.DASHBOARD_DATE_INDEXES
    }
    from_models = set()
    for table_name, model in tables.items():
        for index in model.__table__.indexes:
            if index.name in {row[0] for row in declared}:
                from_models.add((index.name, table_name, tuple(column.name for column in index.columns)))
    assert from_models == declared
    assert migration.LOCK_TIMEOUT == "5s"
    assert migration.STATEMENT_TIMEOUT == "0"
    source = MIGRATION.read_text()
    assert "CREATE INDEX CONCURRENTLY IF NOT EXISTS" in source
    assert "DROP INDEX CONCURRENTLY IF EXISTS" in source
    assert "SET lock_timeout" in source
    assert "SET statement_timeout" in source


def _sqlite_tables(engine):
    with engine.begin() as conn:
        conn.execute(sa.text(
            "CREATE TABLE bank_transactions ("
            "id INTEGER PRIMARY KEY, account_id INTEGER, transaction_date DATE)"
        ))
        conn.execute(sa.text(
            "CREATE TABLE invoices ("
            "id INTEGER PRIMARY KEY, organization_id INTEGER, issue_date DATE)"
        ))
        conn.execute(sa.text(
            "CREATE TABLE bills ("
            "id INTEGER PRIMARY KEY, organization_id INTEGER, issue_date DATE)"
        ))
        conn.execute(sa.text(
            "CREATE TABLE expenses ("
            "id INTEGER PRIMARY KEY, organization_id INTEGER, expense_date DATE)"
        ))


def _run(engine, fn):
    with engine.begin() as conn:
        context = MigrationContext.configure(conn)
        with Operations.context(context):
            fn()


def test_sqlite_upgrade_and_downgrade_round_trip():
    migration = _migration()
    engine = sa.create_engine("sqlite://")
    _sqlite_tables(engine)
    _run(engine, migration.upgrade)
    inspector = sa.inspect(engine)
    for name, table, columns in migration.DASHBOARD_DATE_INDEXES:
        found = {idx["name"]: tuple(idx["column_names"]) for idx in inspector.get_indexes(table)}
        assert found[name] == columns
    _run(engine, migration.downgrade)
    inspector = sa.inspect(engine)
    for name, table, _columns in migration.DASHBOARD_DATE_INDEXES:
        names = {idx["name"] for idx in inspector.get_indexes(table)}
        assert name not in names
