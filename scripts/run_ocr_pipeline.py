#!/usr/bin/env python3
"""
הרצת ה-OCR pipeline על טיוטות הוצאה ב-SUMIT: משיכת צילום -> חילוץ ראייה (LLM)
-> אימות ח.פ ברשם החברות -> סיווג -> עדכון DB -> (אופציונלי) תיוק ל-SUMIT.

דורש מפתח LLM ב-.env.local: ANTHROPIC_API_KEY (מומלץ) או OPENAI_API_KEY.
מתייק אוטומטית רק כאשר ח.פ + ספק + סכום חולצו בביטחון; השאר מסומן לבדיקה.

שימוש:
    DATABASE_URL="sqlite:///./cfo.db" python scripts/run_ocr_pipeline.py --org 1 \
        --since 2025-12-01 --auto-file
"""
import argparse
import asyncio
import os
import sys
from datetime import date, datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from cfo.database import SessionLocal  # noqa: E402
from cfo.services.expense_ocr_pipeline import ExpenseOCRPipeline  # noqa: E402


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--org", type=int, default=1)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--delay", type=float, default=1.0,
                        help="השהיה בין קבלות (rate-limit של SUMIT)")
    parser.add_argument("--min-confidence", type=float, default=0.6, dest="min_confidence")
    parser.add_argument("--since", type=str, default=None,
                        help="עבד רק מתאריך זה (YYYY-MM-DD) — חלון 6 החודשים")
    parser.add_argument("--auto-file", action="store_true", dest="auto_file",
                        help="גם לתייק ב-SUMIT הוצאות שאומתו")
    args = parser.parse_args()

    since = None
    if args.since:
        since = datetime.strptime(args.since, "%Y-%m-%d").date()

    db = SessionLocal()
    try:
        pipeline = ExpenseOCRPipeline(
            db, organization_id=args.org, min_confidence=args.min_confidence
        )
        summary = await pipeline.process_pending(
            limit=args.limit, auto_file=args.auto_file, delay=args.delay, since=since
        )
        print(f"\nscanned={summary['scanned']} filed={summary['filed']} "
              f"flagged={summary['flagged']} errors={summary['errors']}", flush=True)
        for r in summary["results"]:
            status = r.get("status")
            if status == "filed":
                print(f"  ✓ #{r['expense_id']} {r.get('supplier_name')} "
                      f"₪{r.get('total')} -> {r.get('sumit_expense_id')}", flush=True)
            elif status == "ready":
                print(f"  ○ #{r['expense_id']} {r.get('supplier_name')} ₪{r.get('total')} "
                      f"(מאומת, לא תויק)", flush=True)
            elif status == "flagged":
                print(f"  ⚠ #{r['expense_id']} לבדיקה: "
                      f"{', '.join(r.get('review_reasons', []))}", flush=True)
            else:
                print(f"  ✗ #{r['expense_id']} {status}: {r.get('error', '')}", flush=True)
    finally:
        db.close()


if __name__ == "__main__":
    asyncio.run(main())
