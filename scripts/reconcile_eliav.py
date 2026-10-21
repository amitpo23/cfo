#!/usr/bin/env python3
"""Compare a dashboard's computed monthly category totals with a baseline JSON.

Tolerance defaults to ₪1. A missing amount stays missing and is not read as zero.
No provider calls, and no writes.

    python scripts/reconcile_eliav.py --dashboard-id 1 --baseline baseline.json
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="התאמת סכומי תקציב חודשיים לבסיס שמור")
    parser.add_argument("--dashboard-id", type=int, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--tolerance", default="1")
    args = parser.parse_args(argv)
    _assert_local_database()
    try:
        baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"לא ניתן לקרוא את הקובץ: {exc.__class__.__name__}")
    from cfo.database import SessionLocal

    db = SessionLocal()
    try:
        report = reconcile(
            db, args.dashboard_id, baseline, tolerance=Decimal(args.tolerance),
        )
    except ImportRejected as exc:
        print(f"{exc.code}: {exc.message}", file=sys.stderr)
        return 2
    finally:
        db.close()
    print(render_report(report))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
