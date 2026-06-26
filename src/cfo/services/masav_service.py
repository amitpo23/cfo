"""
מס"ב — יצירת קובץ זיכויים (תשלומים לספקים/עובדים)
Masav credits/payments file generator.

מבוסס על "מפרט טכני לביצוע תשלומים באמצעות מס\"ב" (המפרט הרשמי של מס"ב).
מבנה הקובץ:
  - רשומת כותרת ('K')   — הרשומה הראשונה בכל קובץ לוגי (מוסד)
  - רשומות תנועה ('1')  — תנועת זיכוי אחת לכל מוטב
  - רשומת סה"כ ('5')    — רשומת בקרה אחרי התנועה האחרונה
  - רשומת תשיעיות       — רשומה מלאה של '9' אחרי קובץ התשלומים האחרון בלבד

כללים מהמפרט:
  - אורך רשומה: 128 תווים, קוד ASCII.
  - בסוף כל רשומה מוסיפים CR (0x0D) ו-LF (0x0A) בפוזיציות 129-130.
  - שדות נומריים (N): ספרות בלבד, מיושרים לימין עם אפסים מובילים.
  - סכומים נשמרים באגורות (11 ספרות ש"ח + 2 ספרות אגורות).
  - איזון: סכום התנועות חייב להיות שווה לסכום ברשומת הסה"כ, וכך גם מספר התנועות.

הערות לאימות לפני הרצה חיה (מול מס"ב / הבנק):
  - יישור שמות (שם מוסד "צמוד לימין"; שם זכאי "מימין לשמאל ערוך להדפסה")
    וקידוד העברית (ברירת מחדל cp862 — הקידוד המסורתי של מס"ב) חייבים אימות.
  - קוד המוסד/נושא (8 ספרות) וקוד המוסד השולח (5 ספרות) ניתנים ע"י מס"ב.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import List, Optional, Sequence

RECORD_LENGTH = 128
LINE_TERMINATOR = "\r\n"  # CR + LF בפוזיציות 129-130
# קידוד עברית מסורתי של מס"ב. ניתן לשנות ל-cp1255/utf-8 לפי דרישת הבנק.
DEFAULT_ENCODING = "cp862"


class MasavValidationError(ValueError):
    """נתון שאינו עומד במבנה קובץ המס"ב."""


@dataclass
class MasavPayment:
    """תנועת זיכוי בודדת למוטב."""
    bank_code: str           # קוד בנק (לפי מסלקת בנק ישראל)
    branch: str              # מספר סניף
    account_number: str      # מספר חשבון הזכאי
    beneficiary_id: str      # מס' זהות / ח.פ של הזכאי (9 ספרות)
    beneficiary_name: str    # שם הזכאי
    amount: Decimal          # סכום לתשלום בש"ח (לא באגורות)
    reference: str = ""      # אסמכתא — מס' ספק/עובד וכו'
    account_type: str = "0"  # סוג חשבון לזיכוי (אפסים כברירת מחדל)
    payment_period: str = "" # תקופת התשלום (YYMMYYMM) — אופציונלי


@dataclass
class MasavInstitution:
    """קובץ לוגי של מוסד אחד: כותרת + תנועות + סה"כ."""
    institution_code: str        # מוסד/נושא (8 ספרות) — ניתן ע"י מס"ב
    sending_institution: str     # מוסד שולח (5 ספרות) — ניתן ע"י מס"ב
    institution_name: str        # שם המוסד/נושא
    payment_date: date           # תאריך התשלום
    payments: List[MasavPayment] = field(default_factory=list)
    currency: str = "00"         # מטבע ('00' = שקל)
    serial: str = "001"          # מספר סידורי


# ---------------------------------------------------------------------------
# פורמט שדות
# ---------------------------------------------------------------------------

def _numeric(value, length: int, field_name: str) -> str:
    """שדה נומרי: ספרות בלבד, מיושר לימין עם אפסים מובילים."""
    text = str(value).strip()
    if text == "":
        text = "0"
    if not text.isdigit():
        raise MasavValidationError(
            f"שדה '{field_name}' חייב להכיל ספרות בלבד, התקבל: {value!r}"
        )
    if len(text) > length:
        raise MasavValidationError(
            f"שדה '{field_name}' ארוך מ-{length} ספרות: {value!r}"
        )
    return text.rjust(length, "0")


def _alpha_left(value: Optional[str], length: int) -> str:
    """שדה אלפאנומרי מיושר לשמאל (רווחים מימין), נחתך לאורך השדה."""
    text = (value or "")
    return text[:length].ljust(length, " ")


def _alpha_right(value: Optional[str], length: int) -> str:
    """שדה אלפאנומרי מיושר לימין (רווחים משמאל), נחתך לאורך השדה."""
    text = (value or "")
    return text[:length].rjust(length, " ")


def _alpha_right_zero(value: Optional[str], length: int, field_name: str) -> str:
    """שדה אלפאנומרי מיושר לימין עם אפסים מובילים (אסמכתא)."""
    text = (value or "0")
    if len(text) > length:
        raise MasavValidationError(
            f"שדה '{field_name}' ארוך מ-{length} תווים: {value!r}"
        )
    return text.rjust(length, "0")


def _yymmdd(d: date) -> str:
    return d.strftime("%y%m%d")


def _to_agorot(amount: Decimal) -> int:
    """המרת ש"ח לאגורות (מספר שלם), עם עיגול חצי-מעלה."""
    if not isinstance(amount, Decimal):
        amount = Decimal(str(amount))
    agorot = (amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(agorot)


def _assert_length(record: str, kind: str) -> str:
    if len(record) != RECORD_LENGTH:
        raise MasavValidationError(
            f"רשומת {kind} באורך {len(record)} במקום {RECORD_LENGTH}"
        )
    return record


# ---------------------------------------------------------------------------
# בניית רשומות
# ---------------------------------------------------------------------------

def build_header_record(inst: MasavInstitution, creation_date: date) -> str:
    """רשומת כותרת ('K') — פוזיציות לפי המפרט (3.1)."""
    rec = (
        "K"                                                  # 1   (1)
        + _numeric(inst.institution_code, 8, "מוסד/נושא")    # 2   (8)
        + _numeric(inst.currency, 2, "מטבע")                 # 10  (2)
        + _yymmdd(inst.payment_date)                         # 12  (6) תאריך התשלום
        + "0"                                                # 18  (1) FILLER
        + _numeric(inst.serial, 3, "מספר סידורי")            # 19  (3)
        + "0"                                                # 22  (1) FILLER
        + _yymmdd(creation_date)                             # 23  (6) תאריך יצירת הסרט
        + _numeric(inst.sending_institution, 5, "מוסד שולח") # 29  (5)
        + "0" * 6                                            # 34  (6) FILLER
        + _alpha_right(inst.institution_name, 30)            # 40  (30) שם המוסד — צמוד לימין
        + " " * 56                                           # 70  (56) FILLER
        + "KOT"                                              # 126 (3) זיהוי כותרת
    )
    return _assert_length(rec, "כותרת")


def build_transaction_record(inst: MasavInstitution, p: MasavPayment) -> str:
    """רשומת תנועה ('1') — פוזיציות לפי המפרט (3.2)."""
    agorot = _to_agorot(p.amount)
    if agorot <= 0:
        raise MasavValidationError(
            f"סכום התשלום ל-{p.beneficiary_name!r} חייב להיות חיובי"
        )
    rec = (
        "1"                                                  # 1   (1)
        + _numeric(inst.institution_code, 8, "מוסד/נושא")    # 2   (8)
        + _numeric(inst.currency, 2, "מטבע")                 # 10  (2)
        + "0" * 6                                            # 12  (6) FILLER
        + _numeric(p.bank_code, 2, "קוד בנק")                # 18  (2)
        + _numeric(p.branch, 3, "מספר סניף")                 # 20  (3)
        + _numeric(p.account_type, 4, "סוג חשבון")           # 23  (4)
        + _numeric(p.account_number, 9, "מספר חשבון")        # 27  (9)
        + "0"                                                # 36  (1) FILLER
        + _numeric(p.beneficiary_id, 9, "מס' זיהוי זכאי")    # 37  (9)
        + _alpha_right(p.beneficiary_name, 16)               # 46  (16) שם הזכאי
        + _numeric(agorot, 13, "סכום לתשלום")                # 62  (13) באגורות
        + _alpha_right_zero(p.reference, 20, "אסמכתא")        # 75  (20) צמוד לימין, אפסים מובילים
        + _numeric(p.payment_period or "0", 8, "תקופת תשלום")# 95  (8)
        + "0" * 3                                            # 103 (3) קוד מלל
        + "006"                                              # 106 (3) סוג תנועה — זיכוי רגיל
        + "0" * 18                                           # 109 (18) FILLER
        + " " * 2                                            # 127 (2) FILLER
    )
    return _assert_length(rec, "תנועה")


def build_total_record(inst: MasavInstitution) -> str:
    """רשומת סה"כ ('5') — פוזיציות לפי המפרט (3.3)."""
    total_agorot = sum(_to_agorot(p.amount) for p in inst.payments)
    count = len(inst.payments)
    rec = (
        "5"                                                  # 1   (1)
        + _numeric(inst.institution_code, 8, "מוסד/נושא")    # 2   (8)
        + _numeric(inst.currency, 2, "מטבע")                 # 10  (2)
        + _yymmdd(inst.payment_date)                         # 12  (6) תאריך התשלום
        + "0"                                                # 18  (1) FILLER
        + _numeric(inst.serial, 3, "מספר סידורי")            # 19  (3)
        + _numeric(total_agorot, 15, "סכום התנועות")         # 22  (15)
        + "0" * 15                                           # 37  (15) FILLER
        + _numeric(count, 7, "מספר התנועות")                 # 52  (7)
        + "0" * 7                                            # 59  (7) FILLER
        + " " * 63                                           # 66  (63) FILLER
    )
    return _assert_length(rec, "סה\"כ")


def build_nines_record() -> str:
    """רשומת תשיעיות — אחרי קובץ התשלומים האחרון בלבד."""
    return _assert_length("9" * RECORD_LENGTH, "תשיעיות")


# ---------------------------------------------------------------------------
# הרכבת קובץ
# ---------------------------------------------------------------------------

def build_records(
    institutions: Sequence[MasavInstitution],
    creation_date: Optional[date] = None,
) -> List[str]:
    """בניית כל רשומות הקובץ (ללא CR/LF), כולל רשומת התשיעיות בסוף."""
    if not institutions:
        raise MasavValidationError("הקובץ חייב להכיל לפחות מוסד אחד")
    if creation_date is None:
        creation_date = date.today()

    records: List[str] = []
    for inst in institutions:
        if not inst.payments:
            raise MasavValidationError(
                f"מוסד {inst.institution_code} ללא תנועות"
            )
        records.append(build_header_record(inst, creation_date))
        for p in inst.payments:
            records.append(build_transaction_record(inst, p))
        records.append(build_total_record(inst))
    records.append(build_nines_record())  # רק אחרי הקובץ האחרון
    return records


def build_masav_file(
    institutions: Sequence[MasavInstitution],
    creation_date: Optional[date] = None,
    encoding: str = DEFAULT_ENCODING,
) -> bytes:
    """בניית קובץ מס"ב מלא כ-bytes, עם CR/LF בסוף כל רשומה."""
    records = build_records(institutions, creation_date)
    text = "".join(rec + LINE_TERMINATOR for rec in records)
    return text.encode(encoding, errors="replace")


def summarize(institutions: Sequence[MasavInstitution]) -> dict:
    """סיכום קריא לתצוגה לפני הורדת הקובץ."""
    total_agorot = 0
    count = 0
    for inst in institutions:
        for p in inst.payments:
            total_agorot += _to_agorot(p.amount)
            count += 1
    return {
        "institutions": len(institutions),
        "payment_count": count,
        "total_amount": round(total_agorot / 100, 2),
        "currency": "ILS",
    }
