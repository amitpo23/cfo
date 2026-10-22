#!/usr/bin/env python3
"""Import reviewed Z-report totals (pizza revenue) into a dashboard plan.

Reads the Eliav tool's ``lib/reviewed-evidence.json`` (``pizza_z``: month,
revenue_ex_vat, total_net_vat_included, cash_net, card_net) and writes them to
``plan.zReports`` for one organization (``services/dashboards/z_reports.py``).
Months already on the plan for that organization are replaced, other months
and every other plan key are kept. The write goes through ``service.save_plan``
as ``--user-id``, so it is validated, versioned and audited like ``PUT /plan``,
and it is refused unless that user is the dashboard's owner.

Dry-run (the default) prints the months and writes nothing. Same database guard
as ``import_eliav_plan.py``: a non-local database needs ``--allow-remote``, and a
remote write also needs ``REZEF_ALLOW_REMOTE_WRITE=1``. No provider calls.

    python scripts/import_z_reports.py --dashboard-id 1 --organization-id 6 \
        --user-id 1 --file reviewed-evidence.json --source "דוחות Z יולי–ספטמבר"
    python scripts/import_z_reports.py ... --apply
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from import_eliav_plan import _assert_database, _load_json  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ייבוא דוחות Z (הכנסות פיצה) לתוכנית הדשבורד")
    parser.add_argument("--dashboard-id", type=int, required=True)
    parser.add_argument("--organization-id", type=int, required=True, help="הארגון של הפיצה (פוד גרופ)")
    parser.add_argument("--user-id", type=int, required=True, help="משתמש בעלים של הדשבורד")
    parser.add_argument("--file", type=Path, required=True, help="reviewed-evidence.json של הכלי")
    parser.add_argument("--source", required=True, help="מקור, למשל 'דוחות Z מאומתים יולי–ספטמבר'")
    parser.add_argument("--allow-remote", action="store_true", help="מאפשר מסד מרוחק (פרוד, לפי ה-runbook)")
    parser.add_argument("--apply", action="store_true", help="כותב למסד. בלי הדגל זו הרצת בדיקה")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    _assert_database(allow_remote=args.allow_remote, writes=bool(args.apply))
    from cfo.database import SessionLocal
    from cfo.models import DashboardPlan, User
    from cfo.services.dashboards import service, z_reports

    try:
        incoming = z_reports.from_tool_file(_load_json(args.file), args.organization_id, args.source.strip())
    except z_reports.ZReportError as exc:
        raise SystemExit(f"הקובץ נדחה: {exc}")
    with SessionLocal() as db:
        current = db.get(DashboardPlan, args.dashboard_id)
        payload = dict(current.payload) if current is not None and isinstance(current.payload, dict) else {}
        merged = z_reports.merge_items(payload.get("zReports"), incoming)
        for item in incoming:
            print(json.dumps(item, ensure_ascii=False))
        if merged == payload.get("zReports"):
            print("אין שינויים")
            return 0
        if not args.apply:
            print(f"הרצת בדיקה: {len(incoming)} חודשים, לא נכתב דבר")
            return 0
        user = db.get(User, args.user_id)
        if user is None:
            raise SystemExit("המשתמש לא נמצא")
        try:
            saved = service.save_plan(db, user, args.dashboard_id, {**payload, "zReports": merged},
                                      f'"{current.version}"' if current is not None else "null")
        except service.DashboardError as exc:
            raise SystemExit(f"נדחה ({exc.status} {exc.code}): {exc.message_he}")
        print(f"נכתב. גרסת תוכנית חדשה: {saved['version']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
