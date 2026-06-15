#!/usr/bin/env python3
"""
סקריפט סיווג הוצאות — מסווג אוטומטית הוצאות לפי שם ספק / תיאור.

שימוש:
    python scripts/classify_expenses.py                 # כל הארגונים, רק ללא קטגוריה
    python scripts/classify_expenses.py --org 1         # ארגון מסוים
    python scripts/classify_expenses.py --all           # סיווג מחדש של הכל
    python scripts/classify_expenses.py --dry-run       # תצוגה בלבד, בלי לשמור
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from cfo.database import SessionLocal  # noqa: E402
from cfo.models import Expense, Organization  # noqa: E402
from cfo.services.expense_classifier import classify_expense  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="סיווג אוטומטי של הוצאות")
    parser.add_argument("--org", type=int, help="מזהה ארגון (ברירת מחדל: כל הארגונים)")
    parser.add_argument("--all", action="store_true", help="סיווג מחדש של כל ההוצאות")
    parser.add_argument("--dry-run", action="store_true", help="תצוגה בלבד ללא שמירה")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        org_ids = (
            [args.org] if args.org
            else [o.id for o in db.query(Organization).all()]
        )
        total_updated = 0
        for org_id in org_ids:
            q = db.query(Expense).filter(Expense.organization_id == org_id)
            if not args.all:
                q = q.filter(
                    (Expense.category.is_(None))
                    | (Expense.category == "")
                    | (Expense.category == "other")
                )
            rows = q.all()
            updated = 0
            for exp in rows:
                new_cat = classify_expense(exp.supplier_name, exp.description, exp.invoice_number)
                if new_cat != exp.category:
                    print(f"  [org {org_id}] #{exp.id} {exp.supplier_name!r}: "
                          f"{exp.category!r} -> {new_cat!r}")
                    if not args.dry_run:
                        exp.category = new_cat
                    updated += 1
            total_updated += updated
            print(f"ארגון {org_id}: {updated} הוצאות סווגו (מתוך {len(rows)})")

        if args.dry_run:
            print(f"\n[DRY RUN] {total_updated} שינויים — לא נשמר.")
        else:
            db.commit()
            print(f"\nנשמרו {total_updated} שינויי סיווג.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
