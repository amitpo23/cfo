"""שער כפילויות ברמת ה-fingerprint למסמכי הוצאה (Bill+Expense) — רצף P0.

רקע: הבודק המובנה של SUMIT משווה מסמכים לפי אסמכתא (reference) בלבד ומפספס
כפילויות שנוצרות מסיבות אחרות (למשל: מנה שסונכרנה פעמיים, ×N הזנה ידנית).
השבוע נתפסו כמעט-כפילות שגרמו לכפל-ספירה של ₪150K (מנה 4 חפפה 14 שורות
למנה 2 הסגורה); בעבר אצל לקוח אחר הזנה ×4 ניפחה ₪9.6K.

שני רבדים:
1. מפתח ראשי — (ח.פ ספק מנורמל, אסמכתא מנורמלת). התאמה = HIGH confidence
   (כמעט בוודאות אותו מסמך, הוזן/סונכרן פעמיים).
2. רובד שני (fallback, כשאין ח.פ/אסמכתא, וגם כבדיקת-רשת עצמאית) — סכום
   זהה (±₪1) + תאריך קרוב (±3 ימים) = SUSPECT. טעון הכרעת אדם: שתי נסיעות
   מונית זהות באותו יום הן לגיטימיות ולא כפילות.
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Optional

from .company_registry import normalize_tax_id

AMOUNT_TOLERANCE = Decimal("1")
DATE_TOLERANCE_DAYS = 3


def _normalize_reference(reference: Optional[str]) -> str:
    """מנקה אסמכתא להשוואה: משאיר אלפאנומרי בלבד (כולל עברית), אחיד לאותיות גדולות.

    כך "INV-1234" ו-"inv 1234" נחשבים אותה אסמכתא, אבל לא מתעלמים ממספרים
    שונים באמת.
    """
    if not reference:
        return ""
    return re.sub(r"[^0-9A-Za-z֐-׿]", "", str(reference)).upper()


def _as_decimal(amount: Any) -> Optional[Decimal]:
    if amount is None:
        return None
    try:
        return Decimal(str(amount))
    except Exception:
        return None


def _as_date(value: Any) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    try:
        from datetime import datetime as _dt
        return _dt.fromisoformat(str(value)).date()
    except Exception:
        return None


def expense_fingerprint(
    supplier_tax_id: Optional[str],
    reference: Optional[str],
    amount: Any = None,
    doc_date: Any = None,
) -> dict:
    """בונה fingerprint למסמך הוצאה/חשבון-ספק.

    מחזיר {"tier": "primary", "key": (tax_id, ref)} כשיש גם ח.פ וגם אסמכתא
    מנורמלים (המפתח הראשי לזיהוי כפילות ודאי). כשחסר אחד מהם — נופל לרובד
    השני: {"tier": "fallback", "key": (amount, doc_date)} המבוסס על סכום
    ותאריך (נבדק בסבילות ±₪1/±3 ימים ברמת find_duplicate_candidates, לא כאן).
    """
    tax_id = normalize_tax_id(supplier_tax_id)
    ref = _normalize_reference(reference)
    if tax_id and ref:
        return {"tier": "primary", "key": (tax_id, ref)}

    amt = _as_decimal(amount)
    d = _as_date(doc_date)
    return {"tier": "fallback", "key": (amt, d)}


def _row_supplier_tax_id(row: Any, source: str) -> Optional[str]:
    if source == "expense":
        return getattr(row, "supplier_tax_id", None)
    # Bill: tax id lives on the linked vendor Contact, not on the Bill row itself.
    vendor = getattr(row, "vendor", None)
    return getattr(vendor, "tax_id", None) if vendor is not None else None


def _row_reference(row: Any, source: str) -> Optional[str]:
    if source == "expense":
        return getattr(row, "invoice_number", None)
    return getattr(row, "bill_number", None)


def _row_amount(row: Any) -> Optional[Decimal]:
    return _as_decimal(getattr(row, "total", None))


def _row_date(row: Any, source: str) -> Optional[date]:
    if source == "expense":
        return getattr(row, "expense_date", None)
    return getattr(row, "issue_date", None) or getattr(row, "due_date", None)


def _row_supplier_name(row: Any, source: str) -> Optional[str]:
    if source == "expense":
        return getattr(row, "supplier_name", None)
    vendor = getattr(row, "vendor", None)
    return getattr(vendor, "name", None) if vendor is not None else None


def find_duplicate_candidates(
    db,
    org_id: int,
    *,
    supplier_tax_id: Optional[str] = None,
    reference: Optional[str] = None,
    amount: Any = None,
    doc_date: Any = None,
    exclude_id: Optional[int] = None,
    exclude_source: Optional[str] = None,
) -> list[dict]:
    """מחפש מועמדי-כפילות למסמך (ח.פ/אסמכתא/סכום/תאריך נתונים) מול Bill+Expense
    של הארגון.

    מחזיר רשימת מועמדים ממוינת (HIGH לפני SUSPECT), כל אחד:
    {"confidence": "HIGH"|"SUSPECT", "source": "bill"|"expense", "id": int,
     "supplier_name": str|None, "amount": float, "doc_date": iso str|None,
     "reference": str|None}

    exclude_id/exclude_source: מסנן שורה אחת עם id זהה *באותה טבלה בלבד*
    (source == exclude_source) — כדי שמסמך שכבר קיים ב-DB (למשל ההוצאה
    שעומדת להיות מתויקת) לא יתאים לעצמו. חיוני: Bill ו-Expense הן טבלאות
    עצמאיות מבחינת רצף ה-id — סינון "עיוור למקור" (רק לפי id) היה מחריג
    בטעות שורה לא-קשורה מהטבלה השנייה, ובכך *מפספס* כפילות אמיתית חוצת-טבלה
    (למשל bill#7 שהוא הכפילות האמיתית של expense#7 שעומד להיות מתויק —
    בדיוק תרחיש כפל-הספירה חוצה-הטבלאות שהשער הזה נועד לתפוס). ללא
    exclude_source, exclude_id מתעלם (לא מסנן דבר) — בטוח בברירת מחדל.
    """
    from ..models import Bill, Expense

    new_amount = _as_decimal(amount)
    new_date = _as_date(doc_date)
    new_fp = expense_fingerprint(supplier_tax_id, reference, amount, doc_date)

    candidates: list[dict] = []

    def _scan(rows: list[Any], source: str):
        for row in rows:
            if exclude_id is not None and exclude_source == source and row.id == exclude_id:
                continue
            row_tax_id = _row_supplier_tax_id(row, source)
            row_ref = _row_reference(row, source)
            row_amount = _row_amount(row)
            row_date = _row_date(row, source)
            row_fp = expense_fingerprint(row_tax_id, row_ref, row_amount, row_date)

            confidence = None
            if new_fp["tier"] == "primary" and row_fp["tier"] == "primary" and new_fp["key"] == row_fp["key"]:
                confidence = "HIGH"
            elif (
                new_amount is not None and row_amount is not None
                and new_date is not None and row_date is not None
                and abs(new_amount - row_amount) <= AMOUNT_TOLERANCE
                and abs((new_date - row_date).days) <= DATE_TOLERANCE_DAYS
            ):
                confidence = "SUSPECT"

            if confidence is None:
                continue

            candidates.append({
                "confidence": confidence,
                "source": source,
                "id": row.id,
                "supplier_name": _row_supplier_name(row, source),
                "amount": float(row_amount) if row_amount is not None else None,
                "doc_date": row_date.isoformat() if row_date else None,
                "reference": row_ref,
            })

    bills = db.query(Bill).filter(Bill.organization_id == org_id).all()
    expenses = db.query(Expense).filter(Expense.organization_id == org_id).all()
    _scan(bills, "bill")
    _scan(expenses, "expense")

    candidates.sort(key=lambda c: 0 if c["confidence"] == "HIGH" else 1)
    return candidates
