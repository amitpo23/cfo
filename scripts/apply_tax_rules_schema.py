#!/usr/bin/env python3
"""Bring prod's DB schema up to date with the Israeli tax-rules engine additions:
Expense.vat_claimable / Expense.doc_kind, and the new vehicle_profiles table
(migration a4b5c6d7e8f9). Same idempotent pattern as fix_prod_schema_drift.py —
every statement IF NOT EXISTS, no data modified or dropped.

    python scripts/apply_tax_rules_schema.py            # dry-run (prints plan)
    python scripts/apply_tax_rules_schema.py --apply    # executes
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

DDL = [
    "ALTER TABLE expenses ADD COLUMN IF NOT EXISTS vat_claimable NUMERIC(12,2)",
    "ALTER TABLE expenses ADD COLUMN IF NOT EXISTS doc_kind VARCHAR(20)",
    """CREATE TABLE IF NOT EXISTS vehicle_profiles (
        id SERIAL PRIMARY KEY,
        organization_id INTEGER NOT NULL REFERENCES organizations(id),
        label VARCHAR(120) NOT NULL,
        vehicle_kind VARCHAR(20) NOT NULL DEFAULT 'private',
        primarily_business BOOLEAN,
        attached_to_employee_with_use_value BOOLEAN NOT NULL DEFAULT false,
        created_at TIMESTAMP,
        updated_at TIMESTAMP
    )""",
    "CREATE INDEX IF NOT EXISTS ix_vehicle_profiles_organization_id "
    "ON vehicle_profiles (organization_id)",
]


def _load_prod_env() -> str:
    candidates = [str(ROOT / ".env.local")]
    for path in candidates:
        try:
            for line in open(path):
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                v = v.strip().strip('"').strip("'")
                if v and k not in os.environ:
                    os.environ[k] = v
        except FileNotFoundError:
            continue
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        raise SystemExit("DATABASE_URL not found")
    if url.startswith("postgresql://") and "+psycopg" not in url:
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


def main() -> None:
    apply = "--apply" in sys.argv
    url = _load_prod_env()
    from sqlalchemy import create_engine, text

    engine = create_engine(url)
    if not apply:
        print("DRY RUN — would execute on", url.split("@")[-1].split("/")[0])
        for stmt in DDL:
            print("\n" + stmt.strip())
        print("\nthen: alembic stamp head")
        print("\nRe-run with --apply to execute.")
        return

    with engine.begin() as conn:
        for stmt in DDL:
            conn.execute(text(stmt))
            print("OK:", stmt.split("\n")[0][:70])

    from alembic import command as alembic_command
    from alembic.config import Config as AlembicConfig

    cfg = AlembicConfig(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    alembic_command.stamp(cfg, "head")
    print("OK: alembic stamped to head")
    print("\nDone. vat_claimable/doc_kind and vehicle_profiles are live.")


if __name__ == "__main__":
    main()
