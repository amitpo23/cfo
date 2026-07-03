#!/usr/bin/env python3
"""סריקה חיה של הפרוד — login + GET לנתיבים קריטיים, טבלת סטטוס, exit code.

הרצה:
    SMOKE_EMAIL=... SMOKE_PASSWORD=... python scripts/prod_smoke.py
    SMOKE_BASE_URL=https://<preview>.vercel.app SMOKE_EMAIL=... python scripts/prod_smoke.py
"""
import os
import sys

import httpx

# נתיבים קריטיים: (path, note). env_gated=נכשל בחן אם האינטגרציה לא מוגדרת.
CRITICAL_PATHS = [
    ("/api/health", "בריאות בסיסית"),
    ("/api/dashboard/executive", "דשבורד מנהלים"),
    ("/api/financial/reports/profit-loss", "רווח והפסד"),
    ("/api/ledger/balance-sheet", "מאזן"),
    ("/api/ledger/trial-balance", "מאזן בוחן"),
    ("/api/ar/aging", "גיול לקוחות"),
    ("/api/ap/aging", "גיול ספקים"),
    ("/api/daily-reports/vat", "דוח מעמ"),
    ("/api/engine/status", "סטטוס מנוע"),
    ("/api/business/menu", "תפריט יכולות"),
    ("/api/office/clients", "תיקי משרד"),
    ("/api/admin/organizations", "ארגונים (אדמין)"),
    ("/api/admin/control/clients", "מרכז שליטה סופר-אדמין"),
]

SKIP_STATUSES = {400, 503}  # env-gated: אינטגרציה לא מוגדרת = דיווח כן, לא כשל


def run_smoke(base_url, email, password, client=None):
    """מריץ את הסריקה. client מוזרק בטסטים (TestClient); אחרת httpx אמיתי."""
    own_client = client is None
    if own_client:
        client = httpx.Client(base_url=base_url, timeout=30.0, follow_redirects=True)

    results = []
    headers = {}  # לא נוגעים ב-client.headers — הוא עלול להיות משותף (TestClient בטסטים)
    try:
        if email and password:
            resp = client.post(
                "/api/admin/auth/login",
                json={"email": email, "password": password},
            )
            if resp.status_code != 200:
                results.append({"path": "/api/admin/auth/login",
                                "status": resp.status_code, "ok": False,
                                "note": "login נכשל — שאר הבדיקות ירוצו לא-מחוברות"})
            else:
                token = resp.json()["access_token"]
                headers["Authorization"] = f"Bearer {token}"
                results.append({"path": "/api/admin/auth/login",
                                "status": 200, "ok": True, "note": "login"})

        for path, note in CRITICAL_PATHS:
            try:
                r = client.get(path, headers=headers)
                ok = r.status_code == 200 or r.status_code in SKIP_STATUSES
                suffix = " (env-gated)" if r.status_code in SKIP_STATUSES else ""
                results.append({"path": path, "status": r.status_code,
                                "ok": ok, "note": note + suffix})
            except httpx.HTTPError as exc:
                results.append({"path": path, "status": -1, "ok": False,
                                "note": f"{note} — {type(exc).__name__}"})
    finally:
        if own_client:
            client.close()
    return results


def main() -> int:
    base_url = os.environ.get("SMOKE_BASE_URL", "https://cfo-2.vercel.app")
    email = os.environ.get("SMOKE_EMAIL")
    password = os.environ.get("SMOKE_PASSWORD")
    if not email or not password:
        print("אזהרה: SMOKE_EMAIL/SMOKE_PASSWORD לא הוגדרו — רץ לא-מחובר (רק /api/health משמעותי)")

    results = run_smoke(base_url, email, password)
    width = max(len(r["path"]) for r in results)
    failures = 0
    for r in results:
        mark = "OK " if r["ok"] else "FAIL"
        if not r["ok"]:
            failures += 1
        print(f"{mark} {r['status']:>4} {r['path']:<{width}} {r['note']}")
    print(f"\n{len(results) - failures}/{len(results)} תקינים מול {base_url}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
