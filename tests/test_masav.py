"""בדיקות מבנה קובץ מס"ב מול המפרט הרשמי (פוזיציות מדויקות)."""
from datetime import date
from decimal import Decimal

import pytest

from cfo.services.masav_service import (
    MasavInstitution,
    MasavPayment,
    MasavValidationError,
    build_header_record,
    build_transaction_record,
    build_total_record,
    build_nines_record,
    build_records,
    build_masav_file,
    summarize,
    is_valid_israeli_id,
    is_valid_bank_code,
    RECORD_LENGTH,
)


def _inst(payments=None):
    return MasavInstitution(
        institution_code="12345678",
        sending_institution="54321",
        institution_name="חברת בדיקה בעמ",
        payment_date=date(2026, 6, 13),
        payments=payments if payments is not None else [_pay()],
    )


def _pay(**kw):
    base = dict(
        bank_code="12",
        branch="345",
        account_number="123456",
        beneficiary_id="000000000",
        beneficiary_name="ספק בדיקה",
        amount=Decimal("1234.56"),
        reference="SUP-7",
    )
    base.update(kw)
    return MasavPayment(**base)


# ---------- אורך ותווי סיום ----------

def test_all_records_are_128_chars():
    for rec in build_records([_inst()]):
        assert len(rec) == RECORD_LENGTH


def test_file_lines_terminated_with_crlf_and_130_bytes():
    data = build_masav_file([_inst()])
    lines = data.split(b"\r\n")
    # פיצול על CRLF משאיר איבר ריק אחרי ה-CRLF האחרון
    assert lines[-1] == b""
    for line in lines[:-1]:
        assert len(line) == RECORD_LENGTH


# ---------- רשומת כותרת (3.1) ----------

def test_header_field_offsets():
    h = build_header_record(_inst(), creation_date=date(2026, 6, 1))
    assert h[0:1] == "K"
    assert h[1:9] == "12345678"            # מוסד/נושא
    assert h[9:11] == "00"                 # מטבע
    assert h[11:17] == "260613"            # תאריך התשלום YYMMDD
    assert h[17:18] == "0"                 # FILLER
    assert h[18:21] == "001"               # מספר סידורי
    assert h[21:22] == "0"                 # FILLER
    assert h[22:28] == "260601"            # תאריך יצירת הסרט
    assert h[28:33] == "54321"             # מוסד שולח
    assert h[33:39] == "000000"            # FILLER
    assert h[39:69].strip() == "חברת בדיקה בעמ"  # שם מוסד צמוד לימין
    assert len(h[39:69]) == 30
    assert h[69:125] == " " * 56           # FILLER
    assert h[125:128] == "KOT"             # זיהוי כותרת


# ---------- רשומת תנועה (3.2) ----------

def test_transaction_field_offsets():
    t = build_transaction_record(_inst(), _pay())
    assert t[0:1] == "1"
    assert t[1:9] == "12345678"            # מוסד/נושא
    assert t[9:11] == "00"                 # מטבע
    assert t[11:17] == "000000"            # FILLER
    assert t[17:19] == "12"                # קוד בנק
    assert t[19:22] == "345"               # מספר סניף
    assert t[22:26] == "0000"              # סוג חשבון
    assert t[26:35] == "000123456"         # מספר חשבון (9, אפסים מובילים)
    assert t[35:36] == "0"                 # FILLER
    assert t[36:45] == "000000000"         # מס' זיהוי זכאי
    assert len(t[45:61]) == 16             # שם הזכאי
    assert t[61:74] == "0000000123456"     # סכום באגורות (1234.56 -> 123456)
    assert t[74:94] == "000000000000000SUP-7"  # אסמכתא צמודה לימין
    assert t[94:102] == "00000000"         # תקופת תשלום
    assert t[102:105] == "000"             # קוד מלל
    assert t[105:108] == "006"             # סוג תנועה — זיכוי רגיל
    assert t[108:126] == "0" * 18          # FILLER
    assert t[126:128] == "  "              # FILLER


def test_amount_converted_to_agorot_with_rounding():
    t = build_transaction_record(_inst(), _pay(amount=Decimal("100.005")))
    # 100.005 -> 10000.5 אגורות -> עיגול חצי-מעלה -> 10001
    assert t[61:74] == "0000000010001"


def test_zero_amount_rejected():
    with pytest.raises(MasavValidationError):
        build_transaction_record(_inst(), _pay(amount=Decimal("0")))


def test_non_numeric_account_rejected():
    with pytest.raises(MasavValidationError):
        build_transaction_record(_inst(), _pay(account_number="12-34"))


def test_account_too_long_rejected():
    with pytest.raises(MasavValidationError):
        build_transaction_record(_inst(), _pay(account_number="1234567890"))


# ---------- רשומת סה"כ (3.3) ----------

def test_total_record_balances():
    payments = [
        _pay(amount=Decimal("1000.00")),
        _pay(amount=Decimal("250.50")),
        _pay(amount=Decimal("0.49")),
    ]
    inst = _inst(payments)
    s = build_total_record(inst)
    assert s[0:1] == "5"
    assert s[1:9] == "12345678"
    assert s[9:11] == "00"
    assert s[11:17] == "260613"
    assert s[17:18] == "0"
    assert s[18:21] == "001"
    # סכום: 100000 + 25050 + 49 = 125099 אגורות
    assert s[21:36] == "000000000125099"
    assert s[36:51] == "0" * 15            # FILLER
    assert s[51:58] == "0000003"           # מספר התנועות
    assert s[58:65] == "0" * 7             # FILLER
    assert s[65:128] == " " * 63           # FILLER


def test_total_sum_matches_transactions():
    payments = [_pay(amount=Decimal("11.11")), _pay(amount=Decimal("22.22"))]
    inst = _inst(payments)
    total = build_total_record(inst)
    tx_sum = sum(
        int(build_transaction_record(inst, p)[61:74]) for p in payments
    )
    assert int(total[21:36]) == tx_sum     # איזון קובץ (סעיף 2.3)


# ---------- רשומת תשיעיות ----------

def test_nines_record():
    n = build_nines_record()
    assert n == "9" * RECORD_LENGTH


def test_records_end_with_nines():
    records = build_records([_inst()])
    assert records[-1] == "9" * RECORD_LENGTH


def test_record_sequence_order():
    records = build_records([_inst([_pay(), _pay()])])
    assert records[0][0] == "K"            # כותרת ראשונה
    assert records[1][0] == "1"            # תנועה
    assert records[2][0] == "1"            # תנועה
    assert records[3][0] == "5"            # סה"כ
    assert records[4] == "9" * RECORD_LENGTH


# ---------- ולידציה כללית ----------

def test_empty_institutions_rejected():
    with pytest.raises(MasavValidationError):
        build_records([])


def test_institution_without_payments_rejected():
    with pytest.raises(MasavValidationError):
        build_records([_inst([])])


def test_summary():
    inst = _inst([_pay(amount=Decimal("100.00")), _pay(amount=Decimal("50.25"))])
    s = summarize([inst])
    assert s["payment_count"] == 2
    assert s["total_amount"] == 150.25
    assert s["institutions"] == 1


# ---------- ולידציית ת.ז/ח.פ (ביקורת ספרה) ----------

def test_is_valid_israeli_id_checkdigit_accepts_valid():
    # דוגמה מאומתת חיצונית: 78962134 + ספרת ביקורת 9
    assert is_valid_israeli_id("789621349") is True
    # ח.פ אמיתי מ-DB פרודקשן (משתמש באותו אלגוריתם)
    assert is_valid_israeli_id("511402547") is True
    assert is_valid_israeli_id("123456782") is True


def test_is_valid_israeli_id_checkdigit_rejects_invalid():
    assert is_valid_israeli_id("789621340") is False  # ספרת ביקורת שגויה
    assert is_valid_israeli_id("123456789") is False
    assert is_valid_israeli_id("") is False
    assert is_valid_israeli_id("12345678901") is False  # ארוך מדי (מעל 9 ספרות)
    assert is_valid_israeli_id("abcdefghi") is False    # לא ספרות


def test_is_valid_israeli_id_zero_pads_short_ids():
    """ת.ז אמיתית שמתחילה באפס נשמרת לעיתים בלי ה-0 המוביל (8 ספרות
    במקום 9) -- למשל אחרי ייבוא מגיליון Excel שמוריד אפסים מובילים.
    יש לבדוק מול הצורה המלאה (מרופדת ב-0), לא לפסול על הסף לפי אורך."""
    # 062473178 היא ת.ז תקינה (ביקורת ספרה עוברת); מאוחסנת לעיתים כ-62473178.
    assert is_valid_israeli_id("062473178") is True
    assert is_valid_israeli_id("62473178") is True   # אותה ת.ז, בלי ה-0 המוביל
    assert is_valid_israeli_id("2473178") is False    # השחתת נתונים אמיתית, לא ת.ז


# ---------- ולידציית קוד בנק (מול רשימת חברי מס"ב) ----------

def test_is_valid_bank_code_accepts_known_codes():
    # לאומי, הפועלים, דיסקונט, מזרחי-טפחות — קודים ידועים ויציבים
    assert is_valid_bank_code("10") is True
    assert is_valid_bank_code("12") is True
    assert is_valid_bank_code("11") is True
    assert is_valid_bank_code("20") is True
    assert is_valid_bank_code("04") is True   # בנק יהב — נדרש איפוס אפסים
    assert is_valid_bank_code("4") is True    # קלט לא-מרופד גם מתקבל


def test_is_valid_bank_code_rejects_unknown_code():
    assert is_valid_bank_code("00") is False
    assert is_valid_bank_code("77") is False   # לא בשימוש ברשימת חברי מס"ב
    assert is_valid_bank_code("") is False
    assert is_valid_bank_code("abc") is False
    assert is_valid_bank_code("123") is False  # 3 ספרות — עדיין לא בתוקף (המעבר טרם נכנס לתוקף)
