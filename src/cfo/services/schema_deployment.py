"""Fail-closed reconciliation for the owner-approved Gate-0 deployment.

Legacy production databases were originally created by ``create_all`` and may
contain current tables without matching Alembic history.  Declaring such a
database to be at ``head`` before checking the complete ORM structural shape
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
from .schema_sync import compute_schema_drift


class SchemaDeploymentError(RuntimeError):
    """The database could not be proven structurally ready for this release."""


def _has_drift(report: dict[str, Any]) -> bool:
    return schema_sync.has_schema_drift(report)


# --------------------------------------------------------------------- #
# תיקון סמנטי — נתונים, לא רק מבנה
# --------------------------------------------------------------------- #
# `apply_additive` יוצר טבלאות ועמודות חסרות. זה מספיק כשהמיגרציה שנעקפה
# היא מבנית בלבד. `organization_memberships` אינה כזו: המיגרציה שלה
# נושאת backfill שממיר את `users.organization_id` לרשומות חברות.
#
# בלי הקוד כאן, `apply_additive` היה יוצר טבלה **ריקה**, `compute_missing`
# היה מרוצה, ו-`head` היה נחתם — כלומר המערכת מאמינה שהמיגרציה רצה
# כשהנתונים מעולם לא הועברו. התוצאה בפרוד: הבטחת ה-`suspended` מתבטלת,
# ומשתמש מושבת שיופעל מחדש מקבל גישה בשקט.

_BACKFILL_SQL = """
    INSERT INTO organization_memberships
        (organization_id, user_id, role, status, verified_at,
         created_at, updated_at)
    SELECT u.organization_id, u.id, u.role,
           CASE WHEN u.is_active THEN 'active' ELSE 'suspended' END,
           CASE WHEN u.is_active THEN CURRENT_TIMESTAMP ELSE NULL END,
           CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
    FROM users u
    WHERE u.organization_id IS NOT NULL
      AND u.role != 'SUPER_ADMIN'
      AND NOT EXISTS (
          SELECT 1 FROM organization_memberships m
          WHERE m.user_id = u.id AND m.organization_id = u.organization_id
      )
"""


def backfill_memberships(engine: Engine) -> int:
    """ממלא חברויות חסרות מ-`users.organization_id`. אידמפוטנטי.

    זהה בסמנטיקה ל-backfill שבמיגרציה `d2e3f4a5b6c7`; `NOT EXISTS`
    מאפשר הרצה חוזרת בלי כפילות.
    """
    with engine.begin() as conn:
        result = conn.execute(sa.text(_BACKFILL_SQL))
        return result.rowcount or 0


def _pending_backfill_keys(engine: Engine) -> set[tuple[int, int]]:
    """משתמשים שעדיין אין להם חברות — כלומר מי שה-backfill עומד ליצור.

    נדרש כדי לאמת התאמת תפקיד **רק על מה שנוצר עכשיו**. חברות שמנהל
    שינה במכוון אחרי ה-backfill (למשל הורדה ל-VIEWER בתיק אחד) סוטה
    בכוונה מ-`User.role`, ובדיקה גורפת הייתה מכשילה עליה את הפריסה.
    """
    with engine.connect() as conn:
        rows = conn.execute(sa.text(
            "SELECT u.id, u.organization_id FROM users u "
            "WHERE u.organization_id IS NOT NULL AND u.role != 'SUPER_ADMIN' "
            "AND NOT EXISTS (SELECT 1 FROM organization_memberships m "
            "  WHERE m.user_id = u.id AND m.organization_id = u.organization_id)"
        )).fetchall()
    return {(r[0], r[1]) for r in rows}


def verify_membership_backfill(
    engine: Engine, created_keys: set[tuple[int, int]] | None = None,
) -> list[str]:
    """postconditions סמנטיים. מחזיר רשימת פערים — ריקה = תקין.

    `created_keys` מגביל את בדיקת התאמת התפקיד לשורות שנוצרו בריצה הזו.
    חברות ששונתה במכוון אחרי ה-backfill סוטה מ-`User.role` כדין.
    """
    gaps: list[str] = []
    inspector = sa.inspect(engine)
    if "organization_memberships" not in inspector.get_table_names():
        return ["organization_memberships table is missing"]

    with engine.connect() as conn:
        missing = conn.execute(sa.text(
            "SELECT COUNT(*) FROM users u WHERE u.organization_id IS NOT NULL "
            "AND u.role != 'SUPER_ADMIN' AND NOT EXISTS ("
            "  SELECT 1 FROM organization_memberships m "
            "  WHERE m.user_id = u.id AND m.organization_id = u.organization_id)"
        )).scalar_one()
        if missing:
            gaps.append(f"{missing} legacy users have no membership")

        duplicated = conn.execute(sa.text(
            "SELECT COUNT(*) FROM (SELECT user_id, organization_id "
            "FROM organization_memberships GROUP BY user_id, organization_id "
            "HAVING COUNT(*) > 1) d"
        )).scalar_one()
        if duplicated:
            gaps.append(f"{duplicated} duplicated memberships")

        if created_keys:
            rows = conn.execute(sa.text(
                "SELECT u.id, u.organization_id FROM users u "
                "JOIN organization_memberships m ON m.user_id = u.id "
                "  AND m.organization_id = u.organization_id "
                "WHERE m.role != u.role"
            )).fetchall()
            drifted = [r for r in rows if (r[0], r[1]) in created_keys]
            if drifted:
                gaps.append(
                    f"{len(drifted)} backfilled memberships do not match the "
                    "user's role"
                )

        wrongly_active = conn.execute(sa.text(
            "SELECT COUNT(*) FROM users u JOIN organization_memberships m "
            "ON m.user_id = u.id AND m.organization_id = u.organization_id "
            # `IS FALSE` ולא `= 0`: ב-PostgreSQL `boolean = 0` הוא שגיאת
            # טיפוס, ולכן ה-postcondition הזה היה **קורס** בפרוד — כלומר
            # החתימה הייתה נעצרת מסיבה שאינה קשורה לנתונים. ב-SQLite
            # `IS FALSE` נתמך ומתנהג זהה.
            "WHERE u.is_active IS FALSE AND m.status = 'active'"
        )).scalar_one()
        if wrongly_active:
            gaps.append(
                f"{wrongly_active} inactive users hold an active membership"
            )

    return gaps


def _signing_authority_count(engine: Engine) -> int:
    if "organization_signing_authorities" not in sa.inspect(engine).get_table_names():
        return 0
    with engine.connect() as conn:
        return conn.execute(sa.text(
            "SELECT COUNT(*) FROM organization_signing_authorities"
        )).scalar_one()


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
    A legacy/conflicted database is stamped only after the full structural
    drift report is empty.
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

    authorities_before = _signing_authority_count(engine)

    schema_sync_report = schema_sync.apply_additive(engine)
    remaining = compute_schema_drift(engine)
    if _has_drift(remaining):
        raise SchemaDeploymentError(
            "schema drift remains after additive reconciliation; "
            "refusing to mark Alembic head"
        )

    # אילוצי CHECK — `compute_schema_drift` אינו בודק אותם, ו-
    # `apply_additive` אינו יכול להוסיף אותם לטבלה קיימת ב-SQLite.
    # מסד שסומן `head` בלי `ck_membership_role_not_super_admin` נושא
    # הצהרה שקרית: ההגנה שמונעת חברות SUPER_ADMIN אינה קיימת בו.
    check_drift = schema_sync.compute_check_constraint_drift(engine)
    if check_drift:
        raise SchemaDeploymentError(
            "required check constraints are missing; refusing to mark Alembic "
            f"head: {check_drift}"
        )

    # תיקון סמנטי — לפני החתימה, לא אחריה.
    pending = _pending_backfill_keys(engine)
    created = backfill_memberships(engine) or 0
    gaps = verify_membership_backfill(engine, created_keys=pending)
    if gaps:
        raise SchemaDeploymentError(
            "membership backfill is incomplete; refusing to mark Alembic head: "
            + "; ".join(gaps)
        )

    # התיקון אינו מעניק בעלות עסקית. מורשה חתימה שנוצר בדרך הוא סמכות
    # לאשר תשלומים, בלי שאיש ביקש אותה.
    authorities_after = _signing_authority_count(engine)
    if authorities_after != authorities_before:
        raise SchemaDeploymentError(
            "reconciliation changed organization_signing_authorities "
            f"({authorities_before} -> {authorities_after}); refusing to stamp"
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
        "membership_backfill": {"created": created, "gaps": gaps},
    }
