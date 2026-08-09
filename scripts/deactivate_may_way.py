#!/usr/bin/env python3
"""השבתת רשומת הרפאים 'may way' בפנקס לקוחות המשרד (sumit_companies id=5).

הרשומה נקלטה ב-30/06/2026 ממסך "לקוחות המשרד" ב-SUMIT Books (חברת המשרד
844329067) ונקשרה ל-target_organization_id=5 — אותו ארגון של עומר ועודד פורת.
חברת SUMIT 895072659 אינה קיימת בפועל; הרשומה לא כתבה שום נתון (created=0
בכל הישויות), אבל היא גורמת לשני נזקים:

  1. office_rollup (office_service.py:301) רץ על כל רשומה active בנפרד, ולכן
     org 5 מסונתז פעמיים — המע"מ והפעולות הנדרשות שלו נספרים כפול בדוח המשרד.
     אותו דבר ב-get_client_org_ids (שורה 343).
  2. סנכרון SUMIT שעתי מבוזבז מול חברה שלא קיימת (משמעת עלויות API).

הפעולה הפיכה: מעדכן status='inactive' ומכבה את מתג האוטומציה בלבד. כל
היסטוריית ה-raw_data נשמרת. מבטל את עצמו אם השורה אינה הרפאים הצפויה.

הרצה:
    python3 scripts/deactivate_may_way.py

לביטול: UPDATE sumit_companies SET status='active' WHERE id=5;
"""
import json
import os

ENV_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    ".vercel", ".env.production.local",
)
ROW_ID = 5
EXPECT_COMPANY = "895072659"
EXPECT_TARGET = 5


def load_env(path):
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k, v.strip().strip('"'))


load_env(ENV_FILE)

from sqlalchemy import create_engine, text  # noqa: E402

url = os.environ["DATABASE_URL"]
for prefix in ("postgres://", "postgresql://"):
    if url.startswith(prefix):
        url = "postgresql+psycopg://" + url[len(prefix):]
        break

engine = create_engine(url)

SELECT_ROW = (
    "select id, company_id, name, target_organization_id, status,"
    " raw_data::text from sumit_companies where id = :i"
)

with engine.begin() as c:
    row = c.execute(text(SELECT_ROW), {"i": ROW_ID}).first()

    if row is None:
        raise SystemExit(f"ABORT: no sumit_companies row id={ROW_ID}")
    if row[1] != EXPECT_COMPANY or row[3] != EXPECT_TARGET:
        raise SystemExit(
            f"ABORT: row id={ROW_ID} is not the expected phantom "
            f"(company_id={row[1]}, target={row[3]})"
        )

    print("BEFORE:")
    print(f"  id={row[0]} company_id={row[1]} name={row[2]}"
          f" target_org={row[3]} status={row[4]}")
    raw = json.loads(row[5]) if row[5] else {}
    auto = raw.get("automation", {})
    print(f"  automation.enabled={auto.get('enabled')}"
          f" state={auto.get('state')} loop={auto.get('loop')}")

    auto["enabled"] = False
    auto["state"] = "disabled"
    auto["disabled_reason"] = (
        "phantom roster row: SUMIT company does not exist; was double-counting "
        "org 5 in office_rollup and burning an hourly sync"
    )
    raw["automation"] = auto

    c.execute(text(
        "update sumit_companies"
        " set status = 'inactive', raw_data = cast(:r as json),"
        " updated_at = now()"
        " where id = :i"
    ), {"r": json.dumps(raw, ensure_ascii=False), "i": ROW_ID})

with engine.connect() as c:
    row = c.execute(text(SELECT_ROW), {"i": ROW_ID}).first()
    raw = json.loads(row[5]) if row[5] else {}
    auto = raw.get("automation", {})
    print("\nAFTER:")
    print(f"  id={row[0]} company_id={row[1]} name={row[2]}"
          f" target_org={row[3]} status={row[4]}")
    print(f"  automation.enabled={auto.get('enabled')}"
          f" state={auto.get('state')}")

    print("\nActive roster now feeding office_rollup / get_client_org_ids:")
    for r in c.execute(text(
        "select id, company_id, name, target_organization_id, status"
        " from sumit_companies where office_organization_id = 1"
        " and status = 'active' order by id"
    )):
        print(f"  id={r[0]} {r[1]} {r[2]} -> org {r[3]} ({r[4]})")

    dupes = list(c.execute(text(
        "select target_organization_id, count(*) from sumit_companies"
        " where status = 'active' and target_organization_id is not null"
        " group by 1 having count(*) > 1"
    )))
    print("\nRemaining duplicate target orgs among ACTIVE rows:",
          dupes if dupes else "none - double-count resolved")
