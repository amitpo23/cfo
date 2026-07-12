#!/usr/bin/env python3
"""תיקון נתונים אידמפוטנטי ל-bills שסונכרנו לפני נרמול הסימן/סטטוס.

רקע (docs/REZEF_DATA_INTEGRITY_PLAN.md סעיף א/ב): לפני התיקון ב-
sumit_connector.fetch_bills, מסמכי הוצאה (types 15/16) נשמרו עם total
שלילי כמו-שהוא (מוסכמת SUMIT "כסף יוצא"), מה שהפך את "ספקים לתשלום" (AP)
לשלילי. מסמך type 15 (חשבונית-מס-קבלה על הוצאה) גם נשמר תמיד RECEIVED,
בעוד שהוא שולם מעצם טבעה (קבלה = אישור תשלום).

הסקריפט הזה מתקן bills קיימים שכבר סונכרנו בסימן/סטטוס הישן:

1. לכל Bill עם total<0 — הופך סימן ל-total/subtotal/tax/balance,
   ומאפס payload_hash (כדי שהסנכרון הבא — שכבר משתמש ב-fetch_bills
   המתוקן — ידרוס בביטחון בלי להסתמך על ה-hash הישן).
2. לכל Bill מ-raw_data.document_type=="15" — status=PAID,
   paid_amount=total, balance=0.

אידמפוטנטי: bill שכבר בסימן/סטטוס הנכון לא משתנה שוב בהרצה חוזרת.
קורא DATABASE_URL מה-env (לא נוגע בפרוד לבד — dry-run הוא ברירת המחדל).

    python scripts/fix_bills_sign_status.py            # dry-run (ברירת מחדל, לא כותב)
    python scripts/fix_bills_sign_status.py --apply    # מבצע בפועל
"""
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))


def _normalize_url(url: str) -> str:
    if url.startswith("postgresql://") and "+psycopg" not in url:
        return "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


def plan_bill_fixes(db, org_id: "int | None" = None) -> dict[str, Any]:
    """סורק את ה-DB ומחזיר את שתי קבוצות ה-bills הטעונים תיקון, בלי לכתוב.

    org_id=None (ברירת מחדל) = כל הארגונים — כך שהתיקון האמיתי בפרוד רץ פעם
    אחת על כל הדאטה. אפשר להעביר org_id כדי להגביל להרצה/בדיקה של ארגון אחד.
    """
    from cfo.models import Bill

    query = db.query(Bill)
    if org_id is not None:
        query = query.filter(Bill.organization_id == org_id)

    negative_bills = query.filter(Bill.total < 0).all()
    type15_bills = [
        b for b in query.all()
        if isinstance(b.raw_data, dict) and str(b.raw_data.get("document_type")) == "15"
    ]
    return {"negative_bills": negative_bills, "type15_bills": type15_bills}


def apply_bill_fixes(db, org_id: "int | None" = None) -> dict[str, int]:
    """מבצע את התיקון בפועל (בתוך טרנזקציית ה-db הנתונה; הקורא אחראי ל-commit).

    אידמפוטנטי: מריצה חוזרת על bills שכבר תוקנו לא משנה דבר.
    """
    from cfo.models import BillStatus

    plan = plan_bill_fixes(db, org_id=org_id)

    sign_fixed = 0
    for b in plan["negative_bills"]:
        if b.total is None or b.total >= 0:
            continue  # כבר תוקן — אידמפוטנטי
        b.total = -b.total
        b.subtotal = -(b.subtotal or 0)
        b.tax = -(b.tax or 0)
        b.balance = -(b.balance or 0)
        b.payload_hash = None
        sign_fixed += 1

    status_fixed = 0
    for b in plan["type15_bills"]:
        already_fixed = b.status == BillStatus.PAID and float(b.balance or 0) == 0.0
        if already_fixed:
            continue  # כבר תוקן — אידמפוטנטי
        b.status = BillStatus.PAID
        b.paid_amount = b.total
        b.balance = 0
        status_fixed += 1

    return {"sign_fixed": sign_fixed, "status_fixed": status_fixed}


def main() -> None:
    apply = "--apply" in sys.argv
    dry_run = not apply

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise SystemExit("DATABASE_URL לא מוגדר בסביבה")

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(_normalize_url(database_url))
    Session = sessionmaker(bind=engine)
    db = Session()

    try:
        plan = plan_bill_fixes(db)
        print(f"נמצאו {len(plan['negative_bills'])} bills עם total שלילי (לפני נרמול סימן)")
        print(f"נמצאו {len(plan['type15_bills'])} bills מסוג 15 (חשבונית-מס-קבלה על הוצאה)")

        if dry_run:
            print("\n--- DRY RUN --- לא נכתב דבר. הרץ עם --apply לביצוע בפועל.")
            for b in plan["negative_bills"][:10]:
                print(f"  Bill#{b.id} ext={b.external_id} total={b.total} -> {-b.total}")
            if len(plan["negative_bills"]) > 10:
                print(f"  ... ועוד {len(plan['negative_bills']) - 10}")
            return

        counts = apply_bill_fixes(db)
        db.commit()
        print(f"\nתוקנו בפועל: {counts['sign_fixed']} סימנים, "
              f"{counts['status_fixed']} סטטוסים (type 15 -> PAID)")
    finally:
        db.close()


if __name__ == "__main__":
    main()
