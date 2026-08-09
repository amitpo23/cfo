"""Fail-closed reconciliation for the owner-approved Gate-0 deployment.

Legacy production databases were originally created by ``create_all`` and may
contain current tables without matching Alembic history.  Declaring such a
database to be at ``head`` before checking the complete ORM table/column shape
creates false migration evidence.  This service always repairs additive drift,
verifies it is closed, and only then stamps a legacy/conflicted database.

This is structural readiness evidence only.  It does not claim that production
data, provider integrations, constraints outside the ORM contract, or the
application smoke test are healthy.
"""

from __future__ import annotations

from typing import Any, Callable

import sqlalchemy as sa
from alembic import command as alembic_command
from sqlalchemy.engine import Engine

# מיובא כמודול ולא כשמות מועתקים. `from .schema_sync import apply_additive`
# מקפיא את ההפניה בזמן ה-import הראשון: אם המודול נטען לראשונה בזמן שטסט
# החליף את הפונקציה (monkeypatch), העותק כאן נשאר על התחליף **לצמיתות**
# גם אחרי ש-monkeypatch ניקה את המקור. זה הפיל את
# test_migrate_endpoint_reports_and_fixes_drift ואת כל מה שרץ אחריו,
# והתגלה בביקורת Codex ב-09/08/2026. גישה דרך המודול נקראת בכל קריאה
# ולכן משקפת תמיד את המצב הנוכחי.
from . import schema_sync
from .schema_sync import compute_missing


class SchemaDeploymentError(RuntimeError):
    """The database could not be proven structurally ready for this release."""


def _has_drift(report: dict[str, Any]) -> bool:
    return bool(report["tables"] or report["columns"])


def reconcile_schema_to_head(
    engine: Engine,
    *,
    alembic_config: Any,
    upgrade: Callable[[Any, str], None] | None = None,
    stamp: Callable[[Any, str], None] | None = None,
) -> dict[str, Any]:
    """Reach the current additive schema without ever stamping unverified drift.

    ``upgrade`` remains the canonical path for an Alembic-managed database.
    Databases predating Alembic, and databases where an already-created object
    conflicts with migration history, use the additive model reconciliation.
    A legacy/conflicted database is stamped only after ``compute_missing`` is
    empty.
    """

    upgrade = upgrade or alembic_command.upgrade
    stamp = stamp or alembic_command.stamp

    table_names = set(sa.inspect(engine).get_table_names())
    legacy_database = "users" in table_names and "alembic_version" not in table_names
    migration_conflict: sa.exc.DatabaseError | None = None

    if not legacy_database:
        try:
            upgrade(alembic_config, "head")
        except sa.exc.DatabaseError as exc:
            if "already exists" not in str(exc).lower():
                raise
            migration_conflict = exc

    schema_sync_report = schema_sync.apply_additive(engine)
    remaining = compute_missing(engine)
    if _has_drift(remaining):
        raise SchemaDeploymentError(
            "schema drift remains after additive reconciliation; "
            "refusing to mark Alembic head"
        )

    if legacy_database:
        stamp(alembic_config, "head")
        action = "reconciled_legacy_database"
    elif migration_conflict is not None:
        stamp(alembic_config, "head")
        action = (
            "reconciled_after_conflict "
            f"({type(migration_conflict).__name__})"
        )
    elif _has_drift(schema_sync_report):
        action = "upgraded_with_additive_reconciliation"
    else:
        action = "upgraded"

    return {
        "action": action,
        "schema_sync": schema_sync_report,
        "remaining": remaining,
    }
