"""Offline proof that a brand-new deployment can reach the current schema."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import sqlalchemy as sa

from cfo.services.schema_sync import compute_missing


ROOT = Path(__file__).resolve().parents[1]


def _upgrade(database_url: str, revision: str = "head") -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", revision],
        cwd=ROOT,
        env={**os.environ, "DATABASE_URL": database_url},
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_alembic_upgrade_head_builds_a_complete_fresh_database(tmp_path):
    """Empty DB -> Alembic head must succeed and match every ORM model.

    This is the local deployment contract for gate 0.  It deliberately uses
    Alembic rather than ``Base.metadata.create_all`` so a missing or
    dialect-incompatible migration cannot be hidden by application startup.
    """
    database_path = tmp_path / "fresh-deployment.db"
    database_url = f"sqlite:///{database_path}"

    result = _upgrade(database_url)

    assert result.returncode == 0, result.stdout + result.stderr

    engine = sa.create_engine(database_url)
    assert compute_missing(engine) == {"tables": [], "columns": {}}

    with engine.connect() as connection:
        revision = connection.execute(
            sa.text("SELECT version_num FROM alembic_version")
        ).scalar_one()
    assert revision == "c1d2e3f4a5b6"
    account_indexes = {
        index["name"]: index
        for index in sa.inspect(engine).get_indexes("accounts")
    }
    source_code_constraint = account_indexes["uq_account_org_source_account_code"]
    assert bool(source_code_constraint["unique"]) is True
    assert source_code_constraint["column_names"] == [
        "organization_id",
        "source_account_code",
    ]

    # The constraint must exist in the DDL, not merely in ORM metadata.
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                "INSERT INTO organizations "
                "(id, name, collection_reminders_enabled) "
                "VALUES (9001, 'migration-proof', 0)"
            )
        )
        connection.execute(
            sa.text(
                "INSERT INTO morning_briefs "
                "(organization_id, brief_date) VALUES (9001, '2026-07-25')"
            )
        )
        try:
            connection.execute(
                sa.text(
                    "INSERT INTO morning_briefs "
                    "(organization_id, brief_date) VALUES (9001, '2026-07-25')"
                )
            )
        except sa.exc.IntegrityError:
            pass
        else:
            raise AssertionError("morning brief org/date uniqueness is missing")

    repeated = _upgrade(database_url)
    assert repeated.returncode == 0, repeated.stdout + repeated.stderr


def test_provisional_migration_accepts_an_existing_additive_repair(tmp_path):
    """Older deployments may already have the column from schema_sync."""
    database_url = f"sqlite:///{tmp_path / 'pre-repaired.db'}"
    before = _upgrade(database_url, "d5e6f7a8b9c0")
    assert before.returncode == 0, before.stdout + before.stderr

    engine = sa.create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                "ALTER TABLE bank_transactions "
                "ADD COLUMN is_provisional BOOLEAN"
            )
        )

    result = _upgrade(database_url)
    assert result.returncode == 0, result.stdout + result.stderr
    assert compute_missing(engine) == {"tables": [], "columns": {}}
