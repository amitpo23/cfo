#!/usr/bin/env python3
"""Bring prod's DB schema up to date with the bookkeeper daily-cycle plan additions.

Same idempotent pattern as fix_prod_schema_drift.py / apply_tax_rules_schema.py —
every statement IF NOT EXISTS, no data modified or dropped. This script accumulates
one section per PR of the daily-cycle plan; add new DDL to the end of the DDL list
below rather than creating a new script per PR.

    python scripts/apply_morning_cycle_schema.py            # dry-run (prints plan)
    python scripts/apply_morning_cycle_schema.py --apply    # executes

PR1 (migration f8a9b0c1d2e3): Account.credit_limit — the bank credit framework
(מסגרת אשראי/חח"ד) sourced from Open Finance's top-level `creditLimit` field.
NULL = unknown (the provider didn't return the field); never derived from
`interimAvailable` (that's available-to-use credit, not the limit).

PR4 (migration b3c4d5e6f7a8): DailySnapshot morning-cycle columns — written by
services/morning_cycle_service.run_daily_close_step (the /cron/bookkeeper-morning
orchestrator). All nullable/honest-null: the legacy /cron/daily-close route still
writes the base columns only, leaving these NULL when it runs alone.
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

DDL = [
    # --- PR1: credit-limit persistence (migration f8a9b0c1d2e3) --- #
    "ALTER TABLE accounts ADD COLUMN IF NOT EXISTS credit_limit NUMERIC(14,2)",
    # --- PR4: morning-cycle DailySnapshot columns (migration b3c4d5e6f7a8) --- #
    "ALTER TABLE daily_snapshots ADD COLUMN IF NOT EXISTS unreconciled_count INTEGER",
    "ALTER TABLE daily_snapshots ADD COLUMN IF NOT EXISTS open_expense_drafts INTEGER",
    "ALTER TABLE daily_snapshots ADD COLUMN IF NOT EXISTS exceptions_over_48h INTEGER",
    "ALTER TABLE daily_snapshots ADD COLUMN IF NOT EXISTS parity_status VARCHAR(20)",
    "ALTER TABLE daily_snapshots ADD COLUMN IF NOT EXISTS credit_headroom NUMERIC(14,2)",
    "ALTER TABLE daily_snapshots ADD COLUMN IF NOT EXISTS credit_breach_date DATE",
    "ALTER TABLE daily_snapshots ADD COLUMN IF NOT EXISTS cycle_status VARCHAR(10)",
    "ALTER TABLE daily_snapshots ADD COLUMN IF NOT EXISTS days_to_next_deadline INTEGER",
    "ALTER TABLE daily_snapshots ADD COLUMN IF NOT EXISTS open_items JSON",
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
    print("\nDone. accounts.credit_limit is live.")


if __name__ == "__main__":
    main()
