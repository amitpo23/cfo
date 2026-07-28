"""קליטת קבלה בשיחה → הוצאה, בלי לעבור דרך טיוטת SUMIT (חבילה A, תכנית
מושקו — docs/superpowers/plans/2026-07-27-moshko-full-bot.md, פער 1).

משתמש שולח צילום/PDF של קבלה ישירות לצ'אט (היום: טלגרם) במקום להשתמש בזרם
הטיוטות הסרוקות של SUMIT. המודול הזה הוא רכז דק בין רכיבים קיימים בלבד:

1. תקרה יומית פר-ארגון (``settings.chat_receipt_daily_limit``) — נבדקת
   *לפני* כל קריאת LLM, כדי שארגון שמיצה את המכסה לא ישרוף קריאת API
   שממילא לא תשמש אותו.
2. ``vision_extractor.extract_receipt(..., user_initiated=True)`` — אותו
   צינור ראייה שה-OCR של טיוטות SUMIT משתמש בו, אבל עם שער נפרד
   (``chat_receipt_intake_enabled``) — ר' vision_extractor.py למה השערים
   נפרדים.
3. ``duplicate_gate.find_duplicate_candidates`` — אותו שער כפילויות ש-
   ``ExpenseFilingService.file_to_sumit`` מריץ לפני תיוק, מופעל כאן *לפני*
   יצירת כל רשומה — כך שקבלה כפולה לא יוצרת אפילו טיוטת Expense.
4. ``ExpenseFilingService.create_expense`` — שומר שורת Expense בסטטוס טיוטה
   (pending) עם השדות שחולצו; לעולם לא קורא ל-SUMIT.

honest-null: קבלה לא-קריאה/ביטחון נמוך מוחזרת עם status="unreadable" וכל
מה שכן חולץ, אך לעולם לא יוצרת הוצאה עם סכום מומצא/מנוחש.
"""
from __future__ import annotations

import base64
from datetime import date, datetime
from typing import Any, Optional

from sqlalchemy.orm import Session

from ..config import settings

# סף ביטחון מתחת לו קבלה נחשבת "לא קריאה" ולא יוצרת הוצאה — עקבי עם
# min_confidence הדפולטי של ExpenseOCRPipeline (0.6 שם, 0.5 כאן: הסף כאן
# נמוך במעט בכוונה כי קליטת-צ'אט מלווה תמיד באדם חי שיכול לתקן/לאשר מיד,
# בניגוד ל-pipeline הרקע האוטומטי לגמרי).
MIN_CONFIDENCE = 0.5


def _today_bounds() -> tuple[datetime, datetime]:
    today = date.today()
    return datetime.combine(today, datetime.min.time()), datetime.combine(today, datetime.max.time())


def count_receipts_today(db: Session, organization_id: int, source: str) -> int:
    """כמה הוצאות מקור ``source`` נוצרו היום עבור הארגון — המונה שאוכף את
    התקרה היומית כאן, ומשמש גם את כלי הצ'אט get_expense_intake_status."""
    from ..models import Expense

    start, end = _today_bounds()
    return (
        db.query(Expense)
        .filter(
            Expense.organization_id == organization_id,
            Expense.source == source,
            Expense.created_at >= start,
            Expense.created_at <= end,
        )
        .count()
    )


def _parse_date(value: Any) -> Optional[date]:
    if not value:
        return None
    if isinstance(value, date):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _resolve_amounts(extract: dict):
    """(total, net, vat) — שימוש חוזר בגזירת-הסכומים של ExpenseOCRPipeline
    כדי ששני מסלולי קליטת-קבלה (טיוטת-SUMIT מול קליטת-צ'אט) יפעילו בדיוק
    את אותו חשבון השלמת-מע\"מ, לא שני עותקים שעלולים לסטות."""
    from .expense_ocr_pipeline import ExpenseOCRPipeline

    return ExpenseOCRPipeline._resolve_amounts(extract)


def _format_created_message(extract: dict, total, vat, exp_date) -> str:
    supplier = extract.get("supplier_name") or "ספק לא ידוע"
    amount_txt = f"{total:.2f} ₪" if total is not None else "לא זוהה"
    vat_txt = f"{vat:.2f} ₪" if vat is not None else "לא זוהה"
    date_txt = exp_date.isoformat() if exp_date else "לא זוהה"
    parts = [
        f"קלטתי קבלה מ-{supplier}. סכום: {amount_txt}, מע\"מ: {vat_txt}, תאריך: {date_txt}."
    ]
    if not extract.get("supplier_tax_id"):
        parts.append("שים לב: לא זוהה ח.פ/עוסק של הספק — יידרש להשלים ידנית לפני דיווח מע\"מ.")
    return " ".join(parts)


async def intake_receipt_bytes(
    db: Session,
    organization_id: int,
    content: bytes,
    *,
    media_type: Optional[str] = None,
    source: str = "telegram",
    uploaded_by_user_id: Optional[int] = None,
) -> dict:
    """בייטים -> הוצאה (טיוטה), או סטטוס כנה של אי-יצירה. לעולם לא זורק —
    כל מצב כשל (שגיאת LLM, לא קריא, כפילות, מיצוי תקרה) הוא dict מוחזר עם
    status != "created", כדי שקורא (webhook/צ'אט) תמיד יוכל להשיב למשתמש
    בלי להפיל את התור."""
    if not settings.chat_receipt_intake_enabled or settings.chat_receipt_daily_limit <= 0:
        return {
            "status": "disabled",
            "message": "קליטת קבלות דרך הצ'אט כבויה כרגע.",
        }

    count_today = count_receipts_today(db, organization_id, source)
    if count_today >= settings.chat_receipt_daily_limit:
        return {
            "status": "limit_reached",
            "message": (
                f"הגעת למכסה היומית של קליטת קבלות בצ'אט "
                f"({settings.chat_receipt_daily_limit} ליום) — נסה שוב מחר."
            ),
        }

    from .vision_extractor import VisionExtractionError, extract_receipt

    try:
        extract = await extract_receipt(content, media_type, user_initiated=True)
    except VisionExtractionError as exc:
        return {"status": "error", "message": f"חילוץ נתוני הקבלה נכשל: {exc}"}

    if not extract.get("is_readable", True) or (extract.get("confidence") or 0.0) < MIN_CONFIDENCE:
        return {
            "status": "unreadable",
            "extracted": extract,
            "message": (
                "לא הצלחתי לקרוא את הקבלה בביטחון מספיק. אפשר לנסות "
                "לצלם שוב בבהירות טובה יותר, או להזין את הפרטים ידנית."
            ),
        }

    total, net, vat = _resolve_amounts(extract)
    if total is None:
        return {
            "status": "unreadable",
            "extracted": extract,
            "message": (
                "לא הצלחתי לזהות סכום בקבלה. אפשר לנסות לצלם שוב, או "
                "להזין את הסכום ידנית."
            ),
        }

    exp_date = _parse_date(extract.get("expense_date"))

    from .duplicate_gate import find_duplicate_candidates

    candidates = find_duplicate_candidates(
        db, organization_id,
        supplier_tax_id=extract.get("supplier_tax_id"),
        reference=extract.get("invoice_number"),
        amount=total,
        doc_date=exp_date,
    )
    high = [c for c in candidates if c["confidence"] == "HIGH"]
    if high:
        return {
            "status": "duplicate",
            "candidates": high,
            "message": (
                "נראה שהקבלה הזו כבר קיימת במערכת ("
                + ", ".join(f"{c['source']} #{c['id']}" for c in high)
                + ") — לא יצרתי הוצאה חדשה כדי למנוע כפילות."
            ),
        }
    suspect = [c for c in candidates if c["confidence"] == "SUSPECT"]

    from .expense_filing_service import ExpenseFilingService

    receipt_b64 = base64.standard_b64encode(content).decode("ascii")
    service = ExpenseFilingService(db, organization_id=organization_id)
    created = service.create_expense({
        "source": source,
        "supplier_name": extract.get("supplier_name"),
        "amount": net if net is not None else 0,
        "vat_amount": vat if vat is not None else 0,
        "total": total,
        "expense_date": exp_date,
        "invoice_number": extract.get("invoice_number"),
        "receipt_file": receipt_b64,
    })

    # supplier_tax_id ו-raw_data (עקבות ביקורת: מה חולץ, מי העלה) אינם
    # פרמטרים של create_expense — נשמרים ישירות על הרשומה, באותו אופן ש-
    # ExpenseOCRPipeline._process_one עושה עבור מסלול הטיוטות של SUMIT.
    from ..models import Expense

    exp = db.query(Expense).filter(Expense.id == created["id"]).first()
    if exp is not None:
        if extract.get("supplier_tax_id"):
            exp.supplier_tax_id = extract["supplier_tax_id"]
        exp.raw_data = {"uploaded_by_user_id": uploaded_by_user_id, "vision_extract": extract}
        db.commit()
        db.refresh(exp)
        created["supplier_tax_id"] = exp.supplier_tax_id

    return {
        "status": "created",
        "expense_id": created["id"],
        "extracted": extract,
        "suspect_duplicates": suspect,
        "message": _format_created_message(extract, total, vat, exp_date),
    }
