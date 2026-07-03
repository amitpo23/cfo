#!/usr/bin/env python3
"""אימות write-back חי מול SUMIT: הצעת מחיר סמלית → PDF → ביטול → וידוא.

מאושר ע"י המשתמש (2026-07-03): הצעת מחיר בלבד, סכום סמלי, ביטול מיידי.
הרצה:  SUMIT_API_KEY=... SUMIT_COMPANY_ID=... python scripts/verify_sumit_writeback.py
"""
import asyncio
import os
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

BACKOFF_SECONDS = 30
MAX_ATTEMPTS = 3


async def _with_backoff(coro_factory, label):
    """403 של SUMIT = rate limit — המתנה ונסיון חוזר, עד MAX_ATTEMPTS."""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return await coro_factory()
        except Exception as exc:
            if "403" not in str(exc) or attempt == MAX_ATTEMPTS:
                raise
            print(f"  {label}: 403 (rate limit) — המתנה {BACKOFF_SECONDS}s, נסיון {attempt}/{MAX_ATTEMPTS}")
            await asyncio.sleep(BACKOFF_SECONDS)


async def main() -> int:
    api_key = os.environ.get("SUMIT_API_KEY")
    company_id = os.environ.get("SUMIT_COMPANY_ID")
    if not api_key:
        print("SUMIT_API_KEY לא מוגדר", file=sys.stderr)
        return 2

    from cfo.integrations.sumit_integration import SumitIntegration
    from cfo.integrations.sumit_models import DocumentItem, DocumentRequest

    sumit = SumitIntegration(api_key=api_key, company_id=company_id)

    print("1) יוצר הצעת מחיר סמלית...")
    request = DocumentRequest(
        customer_id="בדיקת מערכת רצף — למחיקה",
        document_type="quote",
        items=[DocumentItem(description="אימות write-back אוטומטי", quantity=Decimal("1"), price=Decimal("1.0"))],
    )
    doc = await _with_backoff(lambda: sumit.create_document(request), "create")
    doc_id = doc.document_id
    print(f"   נוצר מסמך: {doc_id} (מספר {doc.document_number})")
    if not doc_id:
        print(f"   תשובה לא צפויה: {doc}", file=sys.stderr)
        return 1

    print("2) מוריד PDF...")
    pdf_bytes = await _with_backoff(lambda: sumit.get_document_pdf(doc_id), "getpdf")
    print(f"   PDF: {len(pdf_bytes)} bytes")

    print("3) מבטל את המסמך...")
    cancel = await _with_backoff(lambda: sumit.cancel_document(doc_id), "cancel")
    print(f"   תשובת ביטול: {cancel}")

    print("4) מוודא סטטוס...")
    details = await _with_backoff(lambda: sumit.get_document_details(doc_id), "getdetails")
    print(f"   סטטוס מסמך אחרי ביטול: {details.status}")

    print(f"\nאימות write-back הושלם — מסמך {doc_id}, PDF {len(pdf_bytes)} bytes, סטטוס: {details.status}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
