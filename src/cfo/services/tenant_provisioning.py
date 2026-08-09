"""הקצאת מסד לעוסק, ואכיפת "הכול או כלום".

שלב 2 של `docs/superpowers/plans/2026-08-08-db-per-tenant-plan.md`.

התבנית לעוסק חדש אינה נכתבת כאן: היא 54 הטבלאות שב-`models.py` ו-42
המיגרציות שמייצרות אותן. מסד לעוסק נוצר ב-`alembic upgrade head` על מסד
ריק — בדיוק המסלול שכבר מוכח ב-`test_fresh_database_migrations`.
המודול הזה הוא העטיפה: להריץ, לאמת, לרשום, ולוודא שאף מסד לא נשאר מאחור.

המיגרציה מורצת ב-subprocess עם `DATABASE_URL` בסביבה, ולא דרך ה-API
של alembic בתוך התהליך. שתי סיבות: `alembic/env.py` דורס את
`sqlalchemy.url` מתוך `settings`, ותהליך נפרד אינו נוגע ב-engine
הגלובלי של האפליקציה החיה. זה אותו דפוס שהטסט הקיים משתמש בו.

**אין כאן שום קריאה ל-Neon.** יצירת הפרויקט המרוחק היא פעולת בעלים;
המודול מקבל DSN מוכן ומטפל בסכימה ובאימות.
"""
from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from ..models import TenantDatabase
from .schema_sync import compute_missing
from .tenant_control_plane import dsn_for_organization, register_tenant_database

_ROOT = Path(__file__).resolve().parents[3]
_MIGRATION_TIMEOUT_SECONDS = 120


class ProvisioningError(RuntimeError):
    """הקצאה נעצרה לפני שביצעה שינוי בלתי-הפיך."""


def _run_upgrade(dsn: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=_ROOT,
        env={**os.environ, "DATABASE_URL": dsn},
        capture_output=True,
        text=True,
        timeout=_MIGRATION_TIMEOUT_SECONDS,
    )


def _table_names(dsn: str) -> list[str]:
    engine = sa.create_engine(dsn)
    try:
        return sa.inspect(engine).get_table_names()
    finally:
        engine.dispose()


def verify_tenant_schema(dsn: str) -> list[str]:
    """מה חסר במסד ביחס למודלים. רשימה ריקה = תקין.

    מסד ריק לגמרי מחזיר את כל הטבלאות כחסרות ולא "תקין" — שער שמדווח
    OK על מסד שלא הוקצה גרוע מאין שער.
    """
    engine = sa.create_engine(dsn)
    try:
        missing = compute_missing(engine)
    finally:
        engine.dispose()

    problems = [f"טבלה חסרה: {name}" for name in missing["tables"]]
    problems += [
        f"עמודות חסרות ב-{table}: {', '.join(columns)}"
        for table, columns in missing["columns"].items()
    ]
    return problems


def _revision_from_engine(engine: sa.Engine) -> str | None:
    """ה-revision של מסד נתון, או None כשאין `alembic_version`.

    היעדר הטבלה אינו שגיאה: מסד שנבנה ב-`create_all` (סביבות בדיקה)
    או מסד ריק לגמרי פשוט אינו מנוהל ע"י alembic. הדוח מדווח None
    במקום לקרוס — honest-null.
    """
    try:
        with engine.connect() as connection:
            return connection.execute(
                sa.text("SELECT version_num FROM alembic_version")
            ).scalar_one_or_none()
    except sa.exc.SQLAlchemyError:
        return None


def tenant_revision(dsn: str) -> str | None:
    """ה-revision שהמסד נמצא בו, או None כשאין `alembic_version`."""
    engine = sa.create_engine(dsn)
    try:
        return _revision_from_engine(engine)
    finally:
        engine.dispose()


def provision_tenant_database(
    db: Session,
    organization_id: int,
    dsn: str,
    *,
    force: bool = False,
    notes: str | None = None,
) -> dict[str, Any]:
    """בונה את מלוא הסכימה על מסד ריק, מאמת אותה, ורושם אותו כפעיל.

    נעצר לפני מסד שכבר מכיל טבלאות אלא אם `force=True`. הקצאה חוזרת
    בטעות על מסד חי היא אובדן נתוני לקוח — אפס אוטונומיה בבלתי-הפיך.

    הרישום במסד הבקרה נעשה **רק אחרי** שהאימות עבר, כדי שלא ייווצר
    מצב שבו ארגון מנותב למסד שאינו שלם.
    """
    existing = _table_names(dsn)
    substantive = [name for name in existing if name != "alembic_version"]
    if substantive and not force:
        raise ProvisioningError(
            f"המסד כבר מכיל {len(substantive)} טבלאות. הקצאה תדרוס נתונים קיימים — "
            "העבר force=True רק אחרי אימות שזה מסד ריק שנועד לכך."
        )

    result = _run_upgrade(dsn)
    if result.returncode != 0:
        raise ProvisioningError(
            f"alembic upgrade head נכשל עבור ארגון {organization_id}:\n"
            f"{result.stdout}\n{result.stderr}"
        )

    drift = verify_tenant_schema(dsn)
    if drift:
        raise ProvisioningError(
            f"המסד עבר מיגרציה אך אינו תואם את המודלים: {'; '.join(drift[:5])}"
        )

    revision = tenant_revision(dsn)
    row = register_tenant_database(db, organization_id, dsn, notes=notes)
    row.schema_revision = revision
    row.last_verified_at = datetime.utcnow()
    db.commit()

    return {
        "organization_id": organization_id,
        "status": row.status,
        "revision": revision,
        "tables_created": len(_table_names(dsn)),
        "drift": drift,
    }


def migration_readiness(db: Session) -> dict[str, Any]:
    """דוח "הכול או כלום" — מסד הבקרה וכל מסדי העוסקים.

    `all_or_nothing` הוא True רק כאשר **כל** המסדים באותו revision ובלי
    drift. זו אכיפת המדיניות שנקבעה ב-09/08: מיגרציה נחשבת מוצלחת רק
    כשכולם עברו; כשל בודד מגלגל את כולם אחורה.

    הקוד שרץ הוא אחד לכל המסדים — לכן תיק שנשאר מאחור אינו "פחות
    מעודכן", הוא תיק שיקרוס בשימוש הראשון בעמודה החדשה.
    """
    from ..database import engine as control_engine

    control_missing = compute_missing(control_engine)
    control_problems = [f"טבלה חסרה: {name}" for name in control_missing["tables"]]
    control_problems += [
        f"עמודות חסרות ב-{table}: {', '.join(columns)}"
        for table, columns in control_missing["columns"].items()
    ]

    control_revision = _revision_from_engine(control_engine)

    tenants: list[dict[str, Any]] = []
    for row in db.query(TenantDatabase).filter(TenantDatabase.status == "active").all():
        dsn = dsn_for_organization(db, row.organization_id)
        if not dsn:
            tenants.append(
                {
                    "organization_id": row.organization_id,
                    "revision": None,
                    "drift": ["DSN אינו ניתן לפענוח"],
                }
            )
            continue
        tenants.append(
            {
                "organization_id": row.organization_id,
                "revision": tenant_revision(dsn),
                "drift": verify_tenant_schema(dsn),
            }
        )

    # drift הוא המדד המכריע: הוא משווה את הסכימה החיה מול המודלים, כלומר
    # מול מה שהקוד בפועל מצפה לו. revision הוא אינדיקטור משני — מסד
    # שנבנה ב-create_all (סביבות בדיקה) תקין לחלוטין אך חסר
    # `alembic_version`. לכן revisions לא-ידועים אינם נספרים כחוסר
    # עקביות, אך מדווחים ב-`unmanaged` כדי שהמידע לא ייעלם.
    known_revisions = {
        revision
        for revision in ({control_revision} | {t["revision"] for t in tenants})
        if revision
    }
    unmanaged = [t["organization_id"] for t in tenants if not t["revision"]]
    if control_revision is None:
        unmanaged.append("control_plane")

    all_green = (
        not control_problems
        and all(not tenant["drift"] for tenant in tenants)
        and len(known_revisions) <= 1
    )

    return {
        "control_plane": {"revision": control_revision, "drift": control_problems},
        "tenants": tenants,
        "all_or_nothing": all_green,
        "revisions_seen": sorted(known_revisions),
        "unmanaged": unmanaged,
    }
