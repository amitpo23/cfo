#!/usr/bin/env python3
"""
משיכת צילום/PDF של טיוטות הוצאה מ-SUMIT (getpdf) ושמירתן לדיסק, כדי ש-Claude
יוכל לקרוא אותן בעצמו (חילוץ ראייה ללא מפתח LLM חיצוני).

שימוש:
    DATABASE_URL="sqlite:///./cfo.db" python scripts/dump_expense_pdf.py --ids 3 4 5
    DATABASE_URL="sqlite:///./cfo.db" python scripts/dump_expense_pdf.py --pending --limit 5
"""
import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from cfo.database import SessionLocal  # noqa: E402
from cfo.models import Expense  # noqa: E402
from cfo.services.sync_engine import get_connector_for_org  # noqa: E402

OUT_DIR = "/tmp/cfo_receipts"


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--org", type=int, default=1)
    parser.add_argument("--ids", type=int, nargs="*", default=None)
    parser.add_argument("--pending", action="store_true",
                        help="כל הטיוטות הממתינות (source=sumit, לא מתויקות)")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--delay", type=float, default=1.5)
    args = parser.parse_args()

    os.makedirs(OUT_DIR, exist_ok=True)
    db = SessionLocal()
    try:
        if args.ids:
            rows = [db.query(Expense).get(i) for i in args.ids]
            rows = [r for r in rows if r]
        else:
            q = (
                db.query(Expense)
                .filter(
                    Expense.organization_id == args.org,
                    Expense.source == "sumit",
                    Expense.external_id.isnot(None),
                    Expense.status != "filed",
                )
                .order_by(Expense.id)
            )
            rows = q.all()
        if args.limit:
            rows = rows[: args.limit]

        connector, _cid, source = get_connector_for_org(
            db, args.org, preferred_source="sumit"
        )
        if source != "sumit":
            raise SystemExit("SUMIT not connected for org")

        for i, e in enumerate(rows):
            try:
                pdf = await connector.get_document_pdf(e.external_id)
            except Exception as exc:
                print(f"#{e.id} ext={e.external_id} ERROR: {str(exc)[:80]}", flush=True)
                if "403" in str(exc):
                    print("rate-limited; stopping", flush=True)
                    break
                continue
            path = os.path.join(OUT_DIR, f"exp_{e.id}_{e.external_id}.pdf")
            with open(path, "wb") as f:
                f.write(pdf)
            head = pdf[:5]
            print(f"#{e.id} -> {path}  ({len(pdf)} bytes, {head})", flush=True)
            if args.delay and i < len(rows) - 1:
                await asyncio.sleep(args.delay)
    finally:
        db.close()


if __name__ == "__main__":
    asyncio.run(main())
