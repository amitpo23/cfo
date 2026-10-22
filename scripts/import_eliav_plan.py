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

``--seed lib/budget-seed.json`` imports the tool's seed lines (127 lines)
instead of a plan export: every line becomes a canonical line, and a line with
a default quantity and rate gets that cell in each month of ``--months``.
``--budget-only`` keeps the filing decisions and rules already in Rezef.

The script refuses a non-local database unless ``--allow-remote`` is given.
Writing to a remote database also needs ``REZEF_ALLOW_REMOTE_WRITE=1`` in the
environment (prod runbook, after a backup). It does not call SUMIT, Financy,
or Open Finance.

    python scripts/import_eliav_plan.py --dashboard-id 1 --plan export.json
    python scripts/import_eliav_plan.py --dashboard-id 1 --plan export.json --apply
    python scripts/import_eliav_plan.py --dashboard-id 1 --seed budget-seed.json \
        --months 2026-01:2027-06 --budget-only
    python scripts/import_eliav_plan.py reconcile --dashboard-id 1 --baseline baseline.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cfo.services.dashboards.eliav_import import (  # noqa: E402
    ImportRejected,
    import_plan,
    reconcile,
    render_report,
    seed_export,
)


def _is_local_database() -> bool:
    from cfo.config import settings

    url = settings.database_url or ""
    if url.startswith("sqlite"):
        return True
    host = ""
    if "://" in url:
        tail = url.split("://", 1)[1].split("@")[-1]
        host = tail.split("/")[0].split(":")[0]
    return host in {"localhost", "127.0.0.1"}


def _assert_database(*, allow_remote: bool, writes: bool) -> None:
    if _is_local_database():
        return
    if not allow_remote:
        raise SystemExit("הסקריפט רץ רק על מסד מקומי (או --allow-remote)")
    if writes and os.environ.get("REZEF_ALLOW_REMOTE_WRITE") != "1":
        raise SystemExit("כתיבה למסד מרוחק דורשת REZEF_ALLOW_REMOTE_WRITE=1 (אחרי גיבוי)")


def _month_range(text: str) -> list[str]:
    try:
        first, last = text.split(":", 1)
        year, month = int(first[:4]), int(first[5:7])
        end = (int(last[:4]), int(last[5:7]))
    except (ValueError, IndexError):
        raise SystemExit("--months בצורת YYYY-MM:YYYY-MM")
    months = []
    while (year, month) <= end:
        months.append(f"{year:04d}-{month:02d}")
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
        if len(months) > 36:
            raise SystemExit("--months ארוך מ-36 חודשים")
    return months


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
    parser.add_argument("--seed", type=Path, help="lib/budget-seed.json של הכלי במקום ייצוא תוכנית")
    parser.add_argument("--months", default="2026-01:2027-06", help="טווח חודשים לברירות המחדל של ה-seed")
    parser.add_argument("--budget-only", action="store_true", help="לא נוגע בהחלטות ובכללי התיוק הקיימים")
    parser.add_argument("--allow-remote", action="store_true", help="מאפשר מסד מרוחק (פרוד, לפי ה-runbook)")
    parser.add_argument("--apply", action="store_true", help="כותב למסד. בלי הדגל זו הרצת בדיקה")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    _assert_database(allow_remote=args.allow_remote,
                     writes=bool(args.apply) and args.command != "reconcile")
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
        if args.dashboard_id is None or (args.plan is None) == (args.seed is None):
            raise SystemExit("נדרשים --dashboard-id ואחד מ--plan או --seed")
        if args.seed is not None:
            try:
                seed = json.loads(args.seed.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise SystemExit(f"לא ניתן לקרוא את הקובץ: {exc.__class__.__name__}")
            document = seed_export(seed, _month_range(args.months))
        else:
            document = _load_json(args.plan)
        result = import_plan(db, args.dashboard_id, document, apply=args.apply,
                             budget_only=args.budget_only)
    except ImportRejected as exc:
        print(f"{exc.code}: {exc.message}", file=sys.stderr)
        return 2
    finally:
        db.close()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
