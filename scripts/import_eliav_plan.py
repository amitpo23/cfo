#!/usr/bin/env python3
"""Import an Eliav-tool plan export into a Rezef dashboard.

Dry-run prints the diff and writes nothing. ``--apply`` writes the plan,
a revision, and monthly category totals on the existing ``budgets`` table.
A second apply of the same export is a no-op.

Budget lines are written in the canonical plan format the dashboard editor
saves (``{id, label, category, kind, months: {"YYYY-MM": {quantity, rate}}}``),
so the editor can keep editing an imported plan. Each Eliav group maps to a
P&L category (``eliav_import.GROUPS``); a line may name its own ``category``.
Only the active scenario (``statusParameters.scenario``, default ``base``) is
projected. Cells of other scenarios are kept under
``eliavImport.otherScenarios`` and are not projected or shown in the editor.
An export the editor could not save (unknown category, rule field, too long
an id) is refused before anything is written.

The script refuses a non-local database. It does not call SUMIT, Financy,
or Open Finance.

    python scripts/import_eliav_plan.py --dashboard-id 1 --plan export.json
    python scripts/import_eliav_plan.py --dashboard-id 1 --plan export.json --apply
    python scripts/import_eliav_plan.py reconcile --dashboard-id 1 --baseline baseline.json
"""
from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cfo.services.dashboards.eliav_import import (  # noqa: E402
    ImportRejected,
    import_plan,
    reconcile,
    render_report,
)


def _assert_local_database() -> None:
    from cfo.config import settings

    url = settings.database_url or ""
    if url.startswith("sqlite"):
        return
    host = ""
    if "://" in url:
        tail = url.split("://", 1)[1].split("@")[-1]
        host = tail.split("/")[0].split(":")[0]
    if host in {"localhost", "127.0.0.1"}:
        return
    raise SystemExit("הסקריפט רץ רק על מסד מקומי")


def _load_json(path: Path) -> dict:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"לא ניתן לקרוא את הקובץ: {exc.__class__.__name__}")
    if not isinstance(document, dict):
        raise SystemExit("הקובץ חייב להכיל אובייקט JSON")
    return document


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ייבוא חד-פעמי של תוכנית אליהב לרצף")
    sub = parser.add_subparsers(dest="command")
    reconcile_parser = sub.add_parser("reconcile", help="השוואת סכומים חודשיים לבסיס שמור")
    reconcile_parser.add_argument("--dashboard-id", type=int, required=True)
    reconcile_parser.add_argument("--baseline", type=Path, required=True)
    reconcile_parser.add_argument("--tolerance", default="1")
    parser.add_argument("--dashboard-id", type=int)
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--apply", action="store_true", help="כותב למסד. בלי הדגל זו הרצת בדיקה")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    _assert_local_database()
    from cfo.database import SessionLocal

    db = SessionLocal()
    try:
        if args.command == "reconcile":
            report = reconcile(
                db, args.dashboard_id, _load_json(args.baseline),
                tolerance=Decimal(args.tolerance),
            )
            print(render_report(report))
            return 0 if report["ok"] else 1
        if args.dashboard_id is None or args.plan is None:
            raise SystemExit("נדרשים --dashboard-id ו--plan")
        result = import_plan(db, args.dashboard_id, _load_json(args.plan), apply=args.apply)
    except ImportRejected as exc:
        print(f"{exc.code}: {exc.message}", file=sys.stderr)
        return 2
    finally:
        db.close()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
