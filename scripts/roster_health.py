#!/usr/bin/env python3
"""בקרת כיסוי מהטרמינל — מי נשר מלולאת הסנכרון, ומה מצב שלמות הנתונים.

קריאה בלבד. אינו נוגע ב-SUMIT או ב-Open Finance ואינו משנה שום סטטוס —
החייאת חיבור היא החלטת בעלים. אפס עלות API.

הרקע: `scheduled_sync_sumit` בונה את היעדים מ-`IntegrationConnection.status
== "active"`. חיבור שעבר ל-`paused`/`inactive` מפיל את הארגון מה-cron בשקט:
אין שגיאה, אין ריצה כושלת, פשוט אין ריצה. באודיט 05/08/2026 נמצא ש-org 2
נשר ב-17/07 ו-org 3 ב-06/07.

שימוש:
    python3 scripts/roster_health.py                  # מול ה-DB שבסביבה
    python3 scripts/roster_health.py --prod           # מול פרוד (.vercel)
    python3 scripts/roster_health.py --prod --json    # פלט מכונה

יוצא עם קוד 1 כשהכיסוי אינו תקין — נוח לשרשור ב-CI או ב-shell.
"""
import argparse
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROD_ENV = os.path.join(REPO, ".vercel", ".env.production.local")

sys.path.insert(0, os.path.join(REPO, "src"))


def _load_prod_env(path: str) -> None:
    if not os.path.exists(path):
        raise SystemExit(
            f"לא נמצא {path}. הרץ: vercel env pull .vercel/.env.production.local "
            "--environment=production"
        )
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ[k] = v.strip().strip('"')
    url = os.environ["DATABASE_URL"]
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            url = "postgresql+psycopg://" + url[len(prefix):]
            break
    os.environ["DATABASE_URL"] = url


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prod", action="store_true",
                        help="לקרוא מ-.vercel/.env.production.local")
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--office", type=int, default=1,
                        help="מזהה ארגון המשרד (ברירת מחדל 1)")
    args = parser.parse_args()

    if args.prod:
        _load_prod_env(PROD_ENV)

    from cfo.database import SessionLocal
    from cfo.services.roster_coverage import (
        coverage_alert_lines,
        roster_coverage_report,
    )

    db = SessionLocal()
    try:
        report = roster_coverage_report(db, office_organization_id=args.office)
    finally:
        db.close()

    if args.as_json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["healthy"] else 1

    s = report["summary"]
    print(f"כיסוי: {s['total']} תיקים | תקין {s['ok']} | "
          f"מנותק {s['disconnected']} | מיושן {s['stale']} | "
          f"ללא סנכרון {s['never_synced']}")
    print()

    for c in report["clients"]:
        mark = "✓" if c["verdict"] == "ok" and not c["issues"] else "✗"
        print(f"{mark} org {c['organization_id']:<3} {c['name']}  "
              f"[{c['verdict']}]")
        for src in c["sources"]:
            age = ("—" if src["hours_since_last_ok"] is None
                   else f"{src['hours_since_last_ok']:.0f}h")
            print(f"     {src['source']:<14} {src['status']:<9} "
                  f"{src['verdict']:<13} last_ok {age}")
        di = c["data_integrity"]
        print(f"     נתונים: הוצאות {di['expenses_total']} "
              f"(ריקות {di['expenses_blank_total']}, "
              f"בלי ח.פ {di['expenses_missing_supplier_tax_id']}) | "
              f"חשבוניות {di['invoices_total']} "
              f"(בלי איש קשר {di['invoices_without_contact']})")
        for issue in c["issues"]:
            print(f"     ! {issue}")
        print()

    for z in report["zombie_runs"]:
        print(f"! ריצה #{z['sync_run_id']} (org {z['organization_id']}, "
              f"{z['source']}) תקועה ב-RUNNING {z['hours_stuck']:.0f} שעות")
    if report["duplicate_target_orgs"]:
        print(f"! ארגונים עם יותר מרשומת פנקס פעילה אחת: "
              f"{report['duplicate_target_orgs']} — מע\"מ נספר כפול ב-office_rollup")

    lines = coverage_alert_lines(report)
    if lines:
        print("\n--- ההתרעה שתישלח לבעלים ---")
        print("\n".join(lines))

    return 0 if report["healthy"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
