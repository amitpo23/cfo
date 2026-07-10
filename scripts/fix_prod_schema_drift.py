#!/usr/bin/env python3
"""Bring the prod DB schema in line with the SQLAlchemy models.

Prod's alembic_version is stale (f1a2b3c4d5e6); new TABLES kept up via
create_all on startup, but three added COLUMNS and one table never landed,
so any Organization query 500s ("column collection_reminders_enabled does
not exist") — which breaks /api/admin/organizations and the super-admin org
switcher.

This applies ONLY the missing, additive pieces, every statement idempotent
(IF NOT EXISTS), then stamps alembic to head so the version reflects reality.
No data is modified or dropped. Run it yourself:

    python scripts/fix_prod_schema_drift.py            # dry-run (prints plan)
    python scripts/fix_prod_schema_drift.py --apply    # executes
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

DDL = [
    # organizations opt-in columns (migration c0ffee010203)
    "ALTER TABLE organizations ADD COLUMN IF NOT EXISTS "
    "collection_reminders_enabled BOOLEAN NOT NULL DEFAULT false",
    "ALTER TABLE organizations ADD COLUMN IF NOT EXISTS "
    "collection_sms_sender VARCHAR(20)",
    # expenses classifier feedback (migration 5f6a7b8c9d0e)
    "ALTER TABLE expenses ADD COLUMN IF NOT EXISTS classifier_feedback JSON",
    # collection_reminders table (migration c0ffee010203)
    """CREATE TABLE IF NOT EXISTS collection_reminders (
        id SERIAL PRIMARY KEY,
        organization_id INTEGER NOT NULL REFERENCES organizations(id),
        contact_id INTEGER REFERENCES contacts(id),
        invoice_numbers VARCHAR(500),
        reminder_type VARCHAR(20) NOT NULL,
        channel VARCHAR(20) NOT NULL,
        amount NUMERIC(12,2) DEFAULT 0,
        days_overdue INTEGER DEFAULT 0,
        status VARCHAR(20) DEFAULT 'sent',
        error TEXT,
        sent_at TIMESTAMPTZ
    )""",
    "CREATE INDEX IF NOT EXISTS ix_collreminder_org_contact "
    "ON collection_reminders (organization_id, contact_id)",
]


def _load_prod_env() -> str:
    candidates = [
        "/private/tmp/claude-501/-Users-mymac-coding-cfo/d2a3e0fb-6883-4c01-adf2-d497a6bb800b/scratchpad/.env.prod",
        str(ROOT / ".env.local"),
    ]
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

    # Stamp alembic to head so the version reflects the real schema.
    from alembic import command as alembic_command
    from alembic.config import Config as AlembicConfig

    cfg = AlembicConfig(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    alembic_command.stamp(cfg, "head")
    print("OK: alembic stamped to head")
    print("\nDone. /api/admin/organizations should now return 200.")


if __name__ == "__main__":
    main()
