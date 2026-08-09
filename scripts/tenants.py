#!/usr/bin/env python3
"""ניהול מסדי העוסקים — CLI.

    python scripts/tenants.py list                     # מי מפוצל ומה הסטטוס
    python scripts/tenants.py readiness                # דוח "הכול או כלום"
    python scripts/tenants.py verify <org_id>          # drift על מסד של עוסק
    TENANT_DSN=... python scripts/tenants.py provision <org_id>  # הקצאה

ה-DSN נקרא מ-`TENANT_DSN` או בהקלדה שאינה מהדהדת — לא כארגומנט,
כדי שסיסמת מסד של לקוח לא תישאר בהיסטוריית ה-shell וב-`ps`.

`provision` מריץ `alembic upgrade head` על מסד **ריק** ומאמת מול המודלים
לפני שהוא רושם. הוא נעצר על מסד שכבר מכיל טבלאות — הקצאה חוזרת בטעות
על מסד חי היא אובדן נתוני לקוח. `--force` עוקף, ורק אחרי אימות ידני.

**אין כאן קריאה ל-Neon.** יצירת הפרויקט המרוחק היא פעולת בעלים; ה-CLI
מקבל DSN מוכן. ה-DSN אינו מודפס לעולם.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.cfo.database import SessionLocal  # noqa: E402
from src.cfo.services.tenant_control_plane import (  # noqa: E402
    dsn_for_organization,
    tenant_database_rows,
)
from src.cfo.services.tenant_provisioning import (  # noqa: E402
    ProvisioningError,
    migration_readiness,
    provision_tenant_database,
    verify_tenant_schema,
)


def cmd_list(args) -> int:
    db = SessionLocal()
    try:
        rows = tenant_database_rows(db)
        if not rows:
            print("אין עוסק מפוצל — כל הארגונים על המסד המשותף.")
            return 0
        print(f"{'org':>5}  {'ספק':10} {'סטטוס':10} {'revision':16} אומת לאחרונה")
        for row in rows:
            print(
                f"{row['organization_id']:>5}  {row['provider']:10} {row['status']:10} "
                f"{str(row['schema_revision'] or '—'):16} {row['last_verified_at'] or '—'}"
            )
        return 0
    finally:
        db.close()


def cmd_readiness(args) -> int:
    db = SessionLocal()
    try:
        report = migration_readiness(db)
        control = report["control_plane"]
        print(f"מסד הבקרה: revision={control['revision'] or '—'}")
        for problem in control["drift"]:
            print(f"  ⚠ {problem}")

        for tenant in report["tenants"]:
            mark = "✓" if not tenant["drift"] else "✗"
            print(f"{mark} org{tenant['organization_id']}: revision={tenant['revision'] or '—'}")
            for problem in tenant["drift"][:5]:
                print(f"    ⚠ {problem}")

        if report["unmanaged"]:
            print(f"\nלא מנוהלים ב-alembic: {report['unmanaged']}")

        print(f"\nהכול או כלום: {'✓ ירוק' if report['all_or_nothing'] else '✗ אדום'}")
        return 0 if report["all_or_nothing"] else 1
    finally:
        db.close()


def cmd_verify(args) -> int:
    db = SessionLocal()
    try:
        dsn = dsn_for_organization(db, args.org_id)
        if dsn is None:
            print(f"org{args.org_id} אינו מפוצל — אין מסד ייעודי לאמת.")
            return 1
        problems = verify_tenant_schema(dsn)
        if not problems:
            print(f"org{args.org_id}: אין drift ✓")
            return 0
        print(f"org{args.org_id}: drift נמצא")
        for problem in problems:
            print(f"  ⚠ {problem}")
        return 1
    finally:
        db.close()


def _read_dsn(args) -> str:
    """קורא את ה-DSN בלי להשאיר סיסמה בהיסטוריית ה-shell או ב-`ps`.

    DSN כארגומנט מיקומי היה מותיר את הסיסמה בהיסטוריה ובטבלת התהליכים
    (Codex QA 09/08). לכן: משתנה סביבה, או הקלדה שאינה מהדהדת.
    """
    import getpass
    import os

    from_env = os.environ.get("TENANT_DSN")
    if from_env:
        return from_env
    return getpass.getpass(f"DSN עבור org{args.org_id} (לא מוצג): ")


def cmd_provision(args) -> int:
    dsn = _read_dsn(args)
    if not dsn:
        print("לא התקבל DSN.")
        return 1

    db = SessionLocal()
    try:
        result = provision_tenant_database(db, args.org_id, dsn, force=args.force)
        print(
            f"org{result['organization_id']}: הוקצה — {result['tables_created']} טבלאות, "
            f"revision={result['revision']}, drift={len(result['drift'])}"
        )
        return 0
    except ProvisioningError as exc:
        print(f"ההקצאה נעצרה: {exc}")
        return 1
    finally:
        db.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="ניהול מסדי העוסקים")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="מי מפוצל ומה הסטטוס").set_defaults(func=cmd_list)
    sub.add_parser("readiness", help="דוח הכול-או-כלום").set_defaults(func=cmd_readiness)

    p_verify = sub.add_parser("verify", help="drift על מסד של עוסק")
    p_verify.add_argument("org_id", type=int)
    p_verify.set_defaults(func=cmd_verify)

    p_prov = sub.add_parser("provision", help="הקצאת מסד ריק לעוסק")
    p_prov.add_argument("org_id", type=int)
    p_prov.add_argument("--force", action="store_true", help="לאשר הקצאה על מסד לא ריק")
    p_prov.set_defaults(func=cmd_provision)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
