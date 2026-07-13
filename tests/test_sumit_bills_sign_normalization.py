"""נרמול סימן וסטטוס למסמכי הוצאה (bills) מ-SUMIT.

ממצא חי (פרוד, 2026-07-12): SUMIT מחזיר total **שלילי** לכל מסמכי ההוצאה
(types 15/16) — 730/730 מסמכים בפרוד. fetch_bills שמר את הסימן כמו-שהוא,
מה שהפך את "ספקים לתשלום" (AP) לשלילי (‎-947,035). מסמך סוג 15
(חשבונית-מס-קבלה על הוצאה) גם שולם מעצם טבעה — לא "לתשלום".

רגרסיה קשיחה: הנרמול לא יכול לשבור את דוח המע"מ (compute_vat_position/
vat_report) — הם כבר עוטפים Bill.tax ב-abs(), כך שהתוצאה חייבת להישאר זהה
בין bill שמור בסימן הישן (שלילי) לבין אותו bill אחרי הנרמול (חיובי).
"""
import asyncio
from datetime import date
from decimal import Decimal
from types import SimpleNamespace


def _doc(doc_id, total, document_type, vat_amount=None, paid_amount=0, status="open"):
    """SimpleNamespace שמדמה DocumentResponse אמיתי — כולל vat_amount, כי
    בפרוד השדה הזה תמיד מאוכלס (לא Optional ב-DocumentResponse האמיתי);
    בדיקה בלי vat_amount הייתה עוברת ב-branch שגוי (split_inclusive) ומחביאה
    את הבאג האמיתי (ראו PR review)."""
    return SimpleNamespace(
        id=doc_id, total=total, paid_amount=paid_amount, date=date(2026, 5, 10),
        customer_id="v1", document_number=f"N-{doc_id}", status=status,
        currency="ILS", document_type=document_type, vat_amount=vat_amount,
    )


class _Client:
    def __init__(self, docs_by_type):
        self.docs_by_type = docs_by_type
        self._served = set()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def list_documents(self, request):
        (type_code,) = request.document_types
        if type_code in self._served:
            return []
        self._served.add(type_code)
        return self.docs_by_type.get(type_code, [])


def _fetch(monkeypatch, docs_by_type):
    from cfo.services.sumit_connector import SumitConnector

    connector = SumitConnector(api_key="k", company_id="c")
    client = _Client(docs_by_type)

    async def _fake_get_client(self):
        return client

    monkeypatch.setattr(SumitConnector, "_get_client", _fake_get_client)
    return asyncio.run(connector.fetch_bills())


def test_type_15_receipt_normalizes_to_positive_and_paid(monkeypatch):
    """type 15 (ExpenseReceipt): total הפוך לחיובי, status=paid, balance=0."""
    result = _fetch(monkeypatch, {
        "15": [_doc("d15", total=-61.47, document_type="15", vat_amount=-9.37)],
    })
    (bill,) = result.items
    assert float(bill.total) == 61.47
    assert bill.status == "paid"
    assert float(bill.paid_amount) == 61.47
    assert float(bill.balance) == 0.0
    # subtotal+tax==total חייב להישמר אחרי ההיפוך (גם עם vat_amount מפורש)
    assert bill.subtotal + bill.tax == bill.total
    assert bill.tax > 0  # מע"מ תשומות חיובי


def test_type_16_invoice_normalizes_to_positive_and_open(monkeypatch):
    """type 16 (ExpenseInvoice): total חיובי, status=received, balance=total-paid."""
    result = _fetch(monkeypatch, {
        "16": [_doc("d16", total=-236.0, document_type="16", vat_amount=-36.0, paid_amount=0)],
    })
    (bill,) = result.items
    assert float(bill.total) == 236.0
    assert bill.status == "received"
    assert float(bill.balance) == 236.0
    assert bill.subtotal + bill.tax == bill.total


def test_type_16_partial_payment_keeps_open_balance(monkeypatch):
    result = _fetch(monkeypatch, {
        "16": [_doc("d16p", total=-236.0, document_type="16", vat_amount=-36.0, paid_amount=-100.0)],
    })
    (bill,) = result.items
    assert float(bill.total) == 236.0
    assert float(bill.paid_amount) == 100.0
    assert float(bill.balance) == 136.0


def test_derives_split_from_gross_when_vat_amount_absent(monkeypatch):
    """בלי vat_amount מפורש — split_inclusive על הגולמי, ואז היפוך יחד."""
    result = _fetch(monkeypatch, {
        "16": [_doc("d16n", total=-118.0, document_type="16", vat_amount=None)],
    })
    (bill,) = result.items
    assert float(bill.total) == 118.0
    assert bill.subtotal + bill.tax == bill.total
    assert bill.tax > 0


def test_unknown_type_falls_back_to_received_like_before(monkeypatch):
    """מסמך בלי document_type (תאימות עם דוקומנטים ישנים בטסטים אחרים) —
    מתנהג כמו type 16 (received), לא נופל."""
    result = _fetch(monkeypatch, {
        "15": [_doc("dX", total=-50.0, document_type="", vat_amount=-7.63)],
    })
    (bill,) = result.items
    assert bill.status == "received"
    assert float(bill.total) == 50.0


# --------------------------------------------------------------------- #
# רגרסיה קשיחה: דוח מע"מ תשומות זהה לפני/אחרי הנרמול
# --------------------------------------------------------------------- #
def test_vat_report_input_vat_unchanged_after_sign_normalization(monkeypatch, fresh_org):
    """אותו מסמך SUMIT — פעם נשמר כ-Bill בסימן הישן (שלילי, לפני התיקון),
    ופעם עובר דרך fetch_bills המתוקן (חיובי). compute_vat_position (שכבר
    עוטף ב-abs()) חייב להחזיר בדיוק את אותו input_vat בשני המקרים."""
    from cfo.database import SessionLocal
    from cfo.models import Contact, ContactType, Bill, BillStatus
    from cfo.services.financial_synthesis import compute_vat_position

    result = _fetch(monkeypatch, {
        "16": [_doc("dreg", total=-1000.0, document_type="16", vat_amount=-152.54, paid_amount=0)],
    })
    (normalized_bill,) = result.items
    assert float(normalized_bill.tax) > 0  # מנורמל חיובי

    org_after = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        vend2 = Contact(organization_id=org_after, contact_type=ContactType.VENDOR, name="ספק")
        db.add(vend2)
        db.flush()
        # הערכים המנורמלים בפועל מ-fetch_bills המתוקן — חיוביים, נספרים כתשומות.
        # (שורות "סימן ישן" שליליות כבר לא נתמכות: הן הוסבו במיגרציית הדאטה
        # scripts/fix_bills_sign_status.py; שלילי מעתה = זיכוי ספק, שמקטין.)
        db.add(Bill(
            organization_id=org_after, vendor_id=vend2.id, bill_number="NEW",
            issue_date=date(2026, 5, 10), subtotal=normalized_bill.subtotal,
            tax=normalized_bill.tax, total=normalized_bill.total,
            paid_amount=normalized_bill.paid_amount, balance=normalized_bill.balance,
            status=BillStatus.RECEIVED,
        ))
        db.commit()

        pos_after = compute_vat_position(db, org_after, start=date(2026, 5, 1), end=date(2026, 5, 31))
        assert pos_after["input_vat"] == 152.54
    finally:
        db.close()


def test_type_15_paid_bill_still_counts_in_input_vat(monkeypatch, fresh_org):
    """type 15 עובר גם היפוך סימן וגם RECEIVED->PAID (task 1, שני צירים
    עצמאיים). vat_utils.bill_counts מוציא רק draft/void — PAID כלול —
    אז המע"מ-תשומות של type 15 (רוב ההוצאות בפרוד, 274 מסמכי 2026) לא
    נעלם מדוח המע"מ אחרי שהוא הופך ל-PAID. זו הרגרסיה שה-abs()-בלבד לא
    תופס: כאן הצומת הקריטי הוא שינוי הסטטוס, לא הסימן."""
    from cfo.database import SessionLocal
    from cfo.services.financial_synthesis import compute_vat_position
    from cfo.services.sync_engine import SyncEngine

    result = _fetch(monkeypatch, {
        "15": [_doc("dpaid", total=-1180.0, document_type="15", vat_amount=-180.0)],
    })
    (bill,) = result.items
    assert bill.status == "paid"  # מוודא שאנחנו בודקים בדיוק את המסלול הזה

    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        engine = SyncEngine(db, None, org_id, "sumit")
        engine._upsert_bill(bill)
        db.commit()

        pos = compute_vat_position(db, org_id, start=date(2026, 5, 1), end=date(2026, 5, 31))
        assert pos["input_vat"] == 180.0  # ה-VAT של ה-bill ה-PAID עדיין נספר
    finally:
        db.close()


def test_numeric_currency_codes_map_to_iso():
    """SUMIT מחזיר לעיתים קוד מטבע מספרי — "1"=ILS (מסמכי ₪ רגילים),
    "2"=USD (מנויים דולריים). אומת חי: 20 מסמכים בפרוד."""
    from cfo.services.sumit_connector import _normalize_currency
    assert _normalize_currency("1") == "ILS"
    assert _normalize_currency("2") == "USD"
    assert _normalize_currency("ILS") == "ILS"
    assert _normalize_currency(None) == "ILS"
    assert _normalize_currency("EUR") == "EUR"
