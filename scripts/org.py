#!/usr/bin/env python3
"""תשאול ובדיקה לפי ארגון.

    python scripts/org.py list                 # כל התיקים + דגלים
    python scripts/org.py status 5             # תיק אחד, תמונה מלאה
    python scripts/org.py books 5              # ספרים: עבר, הווה, חסמים
    python scripts/org.py list --prod          # מול מסד הפרודקשן
    python scripts/org.py status 1 --prod --json

עובד כבר היום מול המסד המשותף. כשארגון יעבור למסד ייעודי, אותה פקודה
תמשיך לעבוד — השדה `database` מראה מאיפה המספרים הגיעו.

`--prod` קורא DATABASE_URL מקובץ env. **קריאה בלבד** — אין כאן כתיבה
ואין קריאה ל-SUMIT או ל-Open Finance; הכול נקרא מהמסד.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_PROD_ENV_CANDIDATES = (
    ".vercel/.env.production.local",
    ".env.prod",
)


def _load_prod_env(explicit: str | None) -> None:
    """טוען DATABASE_URL לפני שהאפליקציה נטענת — `database.py` בונה את
    ה-engine בזמן import, ולכן הסדר קריטי."""
    candidates = [explicit] if explicit else list(_PROD_ENV_CANDIDATES)
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate)
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            value = value.strip().strip('"')
            # `vercel env pull` מחזיר מחרוזת ריקה עבור משתנים מסומני
            # Sensitive (SMTP_*, WHATSAPP_*, ANTHROPIC_API_KEY). הזרקת
            # ריק הייתה דורסת ברירות מחדל תקינות ומפילה את טעינת
            # ההגדרות — למשל SMTP_PORT שחייב להיות מספר.
            if value:
                os.environ[key.strip()] = value
        return
    raise SystemExit(
        "לא נמצא קובץ env לפרודקשן. הרץ `vercel env pull <path>` והעבר --env-file."
    )


def _mark(issues: list[str]) -> str:
    return "✓" if not issues else "✗"


def cmd_list(args) -> int:
    from src.cfo.services.org_snapshot import list_organizations

    rows = list_organizations()
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0

    print(f"{'':2} {'org':>4}  {'שם':26} {'מסד':9} {'הוצ':>5} {'סכום-0':>7} {'ספק':>5} {'בנק':>6}  בעיות")
    for row in rows:
        print(
            f"{_mark(row['issues']):2} {row['organization_id']:>4}  "
            f"{str(row['name'])[:26]:26} {row['database']:9} "
            f"{row['expenses']:>5} {row['zero_sum_expenses']:>7} "
            f"{row['bills']:>5} {row['bank_transactions']:>6}  "
            f"{'; '.join(row['issues']) if row['issues'] else '—'}"
        )
    return 0 if all(not row["issues"] for row in rows) else 1


def cmd_status(args) -> int:
    from src.cfo.services.org_snapshot import org_snapshot

    snap = org_snapshot(args.org_id)
    if snap is None:
        print(f"org{args.org_id} אינו קיים.")
        return 1
    if args.json:
        print(json.dumps(snap, ensure_ascii=False, indent=2, default=str))
        return 0

    print(f"org{snap['organization_id']} — {snap['name']}")
    print(f"  פעיל: {snap['is_active']} · מסד: {snap['database']}")
    print("  נתונים:", " · ".join(f"{k}={v}" for k, v in snap["data"].items()))
    print("  ספקים:")
    for name, entry in snap["providers"].items():
        if not entry["connected"]:
            print(f"    {name:14} ✗ אין חיבור")
            continue
        hours = entry["hours_since_sync"]
        when = "מעולם" if hours is None else f"לפני {hours:.0f} שעות"
        mark = "✓" if entry["status"] == "active" else "✗"
        print(f"    {name:14} {mark} {entry['status']:10} סונכרן {when}")
    if snap["issues"]:
        print("  בעיות:")
        for issue in snap["issues"]:
            print(f"    ⚠ {issue}")
    else:
        print("  אין בעיות ✓")
    return 0 if not snap["issues"] else 1


def cmd_books(args) -> int:
    from src.cfo.services.org_books_view import org_books_view

    view = org_books_view(args.org_id)
    if view is None:
        print(f"org{args.org_id} אינו קיים.")
        return 1
    if args.json:
        print(json.dumps(view, ensure_ascii=False, indent=2, default=str))
        return 0

    print(f"\norg{view['organization_id']} — {view['name']}  (ח.פ {view['tax_id']})")
    print(f"קו חיתוך: {view['cutoff']}\n")

    past = view["imported_past"]
    print("── העבר שיובא ──")
    print(f"  פקודות יומן:  {past['journal_entries']:,}   מקור: {', '.join(past['sources']) or '—'}")
    print(f"  טווח:         {past['first_date']} → {past['last_date']}")
    print(f"  חובה:         {float(past['debit_total']):>18,.2f}")
    print(f"  זכות:         {float(past['credit_total']):>18,.2f}")
    mark = "✓ מאוזן" if past["balanced"] else f"✗ פער {float(past['imbalance']):,.2f}"
    print(f"  איזון:        {mark}   (חד-צדיות: {past['one_sided']:,})")

    live = view["live_period"]
    print(f"\n── התקופה החיה (מ-{live['from']}) ──")
    print(f"  הוצאות:       {live['expenses']}")
    print(f"    לא מתויקות: {live['unfiled']}")
    print(f"    בסכום 0:    {live['zero_sum']}")
    print(f"  חשבוניות:     {live['invoices']}")

    idx = view["index"]
    print(f"\n── אינדקס החשבונות ──")
    print(f"  כרטיסים:      {idx['accounts']:,}   מקור: {', '.join(idx['sources']) or '—'}")
    if idx["by_sort_code"]:
        print("  לפי מיון:     " + " · ".join(f"{k}={v}" for k, v in idx["by_sort_code"].items()))

    if view["blockers"]:
        print("\n── מה חוסם ──")
        for b in view["blockers"]:
            print(f"  ⚠ {b}")
    else:
        print("\n  אין חסמים ✓")
    return 0 if not view["blockers"] else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="תשאול ובדיקה לפי ארגון")
    parser.add_argument("--prod", action="store_true", help="לקרוא ממסד הפרודקשן")
    parser.add_argument("--env-file", help="קובץ env מפורש ל---prod")
    parser.add_argument("--json", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="כל התיקים").set_defaults(func=cmd_list)
    p_books = sub.add_parser("books", help="ספרים: עבר שיובא, הווה חי, וחסמים")
    p_books.add_argument("org_id", type=int)
    p_books.set_defaults(func=cmd_books)

    p_status = sub.add_parser("status", help="תיק אחד")
    p_status.add_argument("org_id", type=int)
    p_status.set_defaults(func=cmd_status)

    args = parser.parse_args()
    if args.prod:
        _load_prod_env(args.env_file)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
