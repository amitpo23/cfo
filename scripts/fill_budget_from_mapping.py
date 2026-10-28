#!/usr/bin/env python3
"""Report budget lines that already have an amount, and optionally write those months.

Dry-run is the default. Nothing here calls SUMIT or Open Finance, and nothing
is written to a database. The mapping file records account codes only; it does
not invent amounts for lines that lack quantity or rate.

The draft ``eliav/work/build_budget_mapping.py`` was not in this environment.
The account list is the journal draft already in ``source_journal.py``.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from cfo.services.dashboards.budget_fill import seed_status  # noqa: E402
from cfo.services.dashboards.eliav_import import seed_export  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="סטטוס מילוי תקציב בלי המצאת סכומים")
    parser.add_argument("--seed", type=Path, required=True, help="קובץ seed של שורות התקציב")
    parser.add_argument("--mapping", type=Path, help="מיפוי כרטיסים; לא משמש להמצאת סכום")
    parser.add_argument("--months", nargs="*", default=[], help="חודשים YYYY-MM שאליהם מעתיקים סכום קיים")
    parser.add_argument("--write", type=Path, help="קובץ פלט. בלי הדגל זו הרצה יבשה")
    args = parser.parse_args()
    seed = json.loads(args.seed.read_text(encoding="utf-8"))
    report = seed_status(seed)
    if args.mapping:
        mapping = json.loads(args.mapping.read_text(encoding="utf-8"))
        report["mapping_accounts"] = [
            {"code": row.get("code"), "line_id": row.get("line_id"), "amount": None}
            for row in mapping.get("accounts") or []
        ]
        report["mapping_note"] = mapping.get("note")
    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    if args.write:
        if not args.months:
            raise SystemExit("כתיבה דורשת --months")
        document = seed_export(seed, args.months)
        args.write.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
