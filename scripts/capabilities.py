#!/usr/bin/env python3
"""אינדקס היכולות של רצף — CLI.

מה זה פותר: 116 מתודות ב-SUMIT ו-100 ב-Open Finance נבנו, אבל למושקו
נגישים 50 כלים בלבד, ואין מקום אחד לשאול "איזו יכולת משרתת את המשימה
הזו". הקטלוג נגזר מהקוד ב-introspection ולכן אינו מתיישן.

    python scripts/capabilities.py list                      # הכול, מקובץ לפי מערכת
    python scripts/capabilities.py list --system sumit       # מערכת אחת
    python scripts/capabilities.py list --kind write         # רק כותבות
    python scripts/capabilities.py find "expense"            # חיפוש לפי משימה
    python scripts/capabilities.py find "customer" --reads-only
    python scripts/capabilities.py export docs/capability_catalog.json
    python scripts/capabilities.py stats                     # תמונת כיסוי

אין כאן שום קריאת רשת ושום גישה לספק — מבנה בלבד.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.cfo.services.capability_catalog import build_catalog, find_capabilities  # noqa: E402


_MARK = {"read": "קריאה", "write": "כתיבה", "unknown": "לא-מסווג"}


def _line(entry: dict) -> str:
    flag = "🔒" if entry["requires_approval"] else "  "
    params = ", ".join(entry["parameters"][:4])
    summary = entry["summary"][:70]
    return f"  {flag} [{_MARK[entry['kind']]:8}] {entry['name']}({params}) — {summary}"


def cmd_list(args) -> int:
    catalog = build_catalog()
    for system, entries in catalog.items():
        if args.system and system != args.system:
            continue
        rows = [e for e in entries if not args.kind or e["kind"] == args.kind]
        print(f"\n=== {system} ({len(rows)}) ===")
        for entry in rows:
            print(_line(entry))
    return 0


def cmd_find(args) -> int:
    results = find_capabilities(args.task, reads_only=args.reads_only, limit=args.limit)
    if not results:
        # honest-null: אין התאמה = אין התאמה. לא מוצג "הכי קרוב" מנוחש.
        print(f"אין יכולת שתואמת {args.task!r}.")
        return 1
    print(f"{len(results)} יכולות למשימה {args.task!r}:")
    for entry in results:
        print(f"  [{entry['system']}]{_line(entry)}")
    return 0


def cmd_export(args) -> int:
    catalog = build_catalog()
    target = Path(args.path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "note": "נגזר מהקוד ב-introspection. אין לערוך ידנית — הרץ export מחדש.",
        "systems": catalog,
    }
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    total = sum(len(v) for v in catalog.values())
    print(f"נכתבו {total} יכולות ל-{target}")
    return 0


def cmd_stats(args) -> int:
    catalog = build_catalog()
    total = undocumented = 0
    for system, entries in catalog.items():
        kinds = Counter(e["kind"] for e in entries)
        missing = sum(1 for e in entries if not e["summary"])
        total += len(entries)
        undocumented += missing
        print(
            f"{system:14} {len(entries):4} יכולות | "
            f"קריאה {kinds['read']:3} · כתיבה {kinds['write']:3} · לא-מסווג {kinds['unknown']:2} | "
            f"בלי תיעוד {missing}"
        )
    print(f"\nסה\"כ {total} יכולות, {undocumented} בלי docstring.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="אינדקס היכולות של רצף")
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="הצג יכולות")
    p_list.add_argument("--system", choices=["sumit", "open_finance"])
    p_list.add_argument("--kind", choices=["read", "write", "unknown"])
    p_list.set_defaults(func=cmd_list)

    p_find = sub.add_parser("find", help="חפש יכולת לפי משימה")
    p_find.add_argument("task")
    p_find.add_argument("--reads-only", action="store_true", help="יכולות קוראות בלבד")
    p_find.add_argument("--limit", type=int, default=20)
    p_find.set_defaults(func=cmd_find)

    p_export = sub.add_parser("export", help="ייצא קטלוג ל-JSON")
    p_export.add_argument("path", nargs="?", default="docs/capability_catalog.json")
    p_export.set_defaults(func=cmd_export)

    p_stats = sub.add_parser("stats", help="תמונת כיסוי")
    p_stats.set_defaults(func=cmd_stats)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
