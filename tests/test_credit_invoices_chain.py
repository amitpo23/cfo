"""חשבוניות זיכוי (CreditInvoice) בצד העסקאות — סנכרון, מע"מ, PCN874, openfrmt, דשבורד.

קוד סוג המסמך: לפי ה-swagger הרשמי (docs/sumit_swagger_v1_2026-07-10.json,
Accounting_Typed_DocumentType — אותו enum גם ב-request וגם ב-response של
documents/list): CreditInvoice = 5, Receipt = 2.

הערת אי-ודאות (מתועדת גם בקוד): אודיט 2026-07-05 תייג את סוג 5 כ"קבלה" —
אך התיוג נשען על הערת קוד מ-2026-06-23 שקדמה להורדת ה-swagger (2026-07-10)
ולא אומת מול המפרט. שורת הפרוד external_id=974527677 (total=-23600, doc_type='5')
מוחרגת מצד העסקאות בכל מקרה (הסכמה כפולה: קבלה אינה מסמך מע"מ, וזיכוי-legacy
שסונכרן לפני הנרמול אינו ניתן לאימות) — סנכרון מחדש מייבא זיכויים עם
document_type='credit_note' והם כן נספרים.
"""
import asyncio
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from cfo.database import SessionLocal
from cfo.models import Invoice, Bill, Expense, InvoiceStatus
from cfo.services import daily_reports_service, financial_synthesis, pcn874


# ---------------------------------------------------------------------------
# עזרי connector (בסגנון tests/test_sumit_connector_bills_types.py — בלי רשת)
# ---------------------------------------------------------------------------

def _doc(doc_id, total, status="closed", day=date(2026, 5, 10)):
    return SimpleNamespace(
        id=doc_id, total=total, paid_amount=0, date=day,
        customer_id="c1", document_number=f"N-{doc_id}", status=status,
        currency="ILS",
    )


class _TypeAwareClient:
    """מחזיר מסמכים שונים לפי type_code שנשלח ב-DocumentListRequest."""

    def __init__(self, docs_by_type):
        self.requested_types = []
        self.docs_by_type = docs_by_type

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def list_documents(self, request):
        (type_code,) = request.document_types
        if type_code in self.requested_types:
            return []  # עמוד שני — סיום עימוד
        self.requested_types.append(type_code)
        return self.docs_by_type.get(type_code, [])


def _fetch_invoices(monkeypatch, docs_by_type):
    from cfo.services.sumit_connector import SumitConnector

    connector = SumitConnector(api_key="k", company_id="c")
    client = _TypeAwareClient(docs_by_type)

    async def _fake_get_client(self):
        return client

    monkeypatch.setattr(SumitConnector, "_get_client", _fake_get_client)
    return client, asyncio.run(connector.fetch_invoices())


# ---------------------------------------------------------------------------
# 1. סנכרון: fetch_invoices מושך גם זיכויים (סוג 5), עם skip-drafts ודה-דופ
# ---------------------------------------------------------------------------

def test_fetch_invoices_pulls_credit_type_and_skips_credit_drafts(monkeypatch):
    client, result = _fetch_invoices(monkeypatch, {
        "0": [_doc("inv0", 1180, status="open")],
        "1": [_doc("invrcpt1", 590, status="open")],
        "5": [_doc("cr1", -1180, status="closed"),
              _doc("cr-draft", 0, status="draft")],
    })
    assert sorted(client.requested_types) == ["0", "1", "5", "6"], (
        f"fetch_invoices חייב לבקש גם את סוג הזיכוי 5, ביקש: {client.requested_types}"
    )
    ids = sorted(i.external_id for i in result.items)
    assert ids == ["cr1", "inv0", "invrcpt1"], f"expected credit too, got {ids}"
    assert "cr-draft" not in ids, "טיוטת זיכוי לא נכנסת לספרים"


def test_fetch_invoices_dedupes_credit_appearing_twice(monkeypatch):
    # אותו מסמך חוזר גם בסוג 0 וגם בסוג 5 (הגנת דה-דופ לפי id)
    dup = _doc("dup1", -590, status="closed")
    client, result = _fetch_invoices(monkeypatch, {
        "0": [dup],
        "5": [dup],
    })
    ids = [i.external_id for i in result.items]
    assert ids.count("dup1") == 1


# ---------------------------------------------------------------------------
# 2. נרמול זיכוי: סכומים שליליים, status=paid, balance=0, document_type מנורמל
# ---------------------------------------------------------------------------

def test_credit_invoice_negative_amounts_kept_and_normalized(monkeypatch):
    """SUMIT מחזיר זיכויים בשלילי (מוסכמת כיוון-כסף, כמו מסמכי הוצאה — אומת
    בשורת הפרוד 974527677 total=-23600) — הסימן נשמר, לא מוכפל."""
    _, result = _fetch_invoices(monkeypatch, {
        "5": [_doc("cr1", -1180, status="closed")],
    })
    (inv,) = result.items
    assert float(inv.total) == -1180.0
    # פיצול 18% (2026): נטו 1000-, מע"מ 180-
    assert float(inv.subtotal) == -1000.0
    assert float(inv.tax) == -180.0
    assert float(inv.subtotal) + float(inv.tax) == float(inv.total)


def test_credit_invoice_positive_total_flipped_negative(monkeypatch):
    """הגנה: אם SUMIT אי-פעם יחזיר זיכוי בחיובי — הופכים סימן (זיכוי תמיד מקטין)."""
    _, result = _fetch_invoices(monkeypatch, {
        "5": [_doc("cr-pos", 1180, status="closed")],
    })
    (inv,) = result.items
    assert float(inv.total) == -1180.0
    assert float(inv.tax) == -180.0


def test_credit_invoice_not_open_debt_in_ar(monkeypatch):
    """AR: זיכוי לעולם לא חוב פתוח — balance=0 (עיצוב: אפס, לא שלילי), status=paid."""
    _, result = _fetch_invoices(monkeypatch, {
        "5": [_doc("cr1", -1180, status="open")],  # גם זיכוי "פתוח" אינו חוב לגבייה
    })
    (inv,) = result.items
    assert inv.status == "paid"
    assert float(inv.balance) == 0.0
    assert float(inv.paid_amount) == float(inv.total)


def test_credit_invoice_marked_credit_note_in_raw_data(monkeypatch):
    _, result = _fetch_invoices(monkeypatch, {
        "5": [_doc("cr1", -1180, status="closed")],
    })
    (inv,) = result.items
    assert inv.raw_data["document_type"] == "credit_note"
    assert inv.raw_data["sumit_type_code"] == "5"


# ---------------------------------------------------------------------------
# עזרי DB — ארגון מבודד עם חשבונית רגילה + זיכוי ביוני 2026
# ---------------------------------------------------------------------------

def _seed(org_id, rows):
    db = SessionLocal()
    try:
        for model in (Bill, Invoice, Expense):
            db.query(model).filter(model.organization_id == org_id).delete()
        db.commit()
        for r in rows:
            db.add(r)
        db.commit()
    finally:
        db.close()


def _invoice(org_id, ext, number, subtotal, tax, total, *, status=InvoiceStatus.SENT,
             day=date(2026, 6, 5), raw=None, balance=0):
    return Invoice(organization_id=org_id, external_id=ext, source="credit-test",
                   invoice_number=number, issue_date=day, status=status,
                   subtotal=subtotal, tax=tax, total=total, balance=balance,
                   raw_data=raw)


def _seed_sale_and_credit(org_id):
    """חשבונית 1000+180 וזיכוי 500-/90- ביוני 2026 → מע"מ עסקאות נטו 90."""
    _seed(org_id, [
        _invoice(org_id, "CI-INV-1", "3001", 1000, 180, 1180),
        _invoice(org_id, "CI-CR-1", "4001", -500, -90, -590,
                 status=InvoiceStatus.PAID, raw={"document_type": "credit_note"}),
    ])


# ---------------------------------------------------------------------------
# 3. קבלה (סוג 5) מוחרגת מצד העסקאות של המע"מ — המקרה החי 974527677
# ---------------------------------------------------------------------------

def test_receipt_type5_row_excluded_from_vat_sales(fresh_org):
    """הרשומה החיה: external_id=974527677, total=-23600, raw doc_type='5' —
    קבלה אינה מסמך מע"מ; אסור שתשפיע על עסקאות הדוח (לא בסכום ולא במניין)."""
    org_id = fresh_org()["org_id"]
    _seed(org_id, [
        _invoice(org_id, "CI-INV-1", "3001", 1000, 180, 1180),
        _invoice(org_id, "974527677", "2002", -20000, -3600, -23600,
                 status=InvoiceStatus.OVERDUE, day=date(2026, 6, 30),
                 raw={"document_type": "5"}),
    ])
    db = SessionLocal()
    try:
        sel = financial_synthesis.select_vat_documents(
            db, org_id, start=date(2026, 6, 1), end=date(2026, 6, 30))
        ext_ids = {r["external_id"] for r in sel["sales"]}
        assert "974527677" not in ext_ids, "קבלה (doc_type='5') נכללה בעסקאות"
        rep = daily_reports_service.vat_report_period(db, org_id, 2026, 6)
        assert rep["output_vat"] == 180.0
        assert rep["sales_documents"] == 1
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 4. זיכוי מקטין את מע"מ העסקאות ומופיע במסמכים בסכום שלילי
# ---------------------------------------------------------------------------

def test_credit_note_reduces_output_vat_and_listed_negative(fresh_org):
    org_id = fresh_org()["org_id"]
    _seed_sale_and_credit(org_id)
    db = SessionLocal()
    try:
        rep = daily_reports_service.vat_report_period(db, org_id, 2026, 6)
        assert rep["output_vat"] == 90.0          # 180 - 90
        assert rep["sales_documents"] == 2         # הזיכוי נספר כמסמך
        credit_docs = [d for d in rep["documents"] if d["number"] == "4001"]
        assert credit_docs, "הזיכוי חייב להופיע ברשימת המסמכים"
        assert credit_docs[0]["amount"] == -500.0
        assert credit_docs[0]["vat"] == -90.0
    finally:
        db.close()


def test_credit_note_positive_stored_amounts_still_reduce(fresh_org):
    """זיכוי שנשמר בחיובי (יבוא ישן/ידני) — הסיווג credit_note קובע סימן שלילי."""
    org_id = fresh_org()["org_id"]
    _seed(org_id, [
        _invoice(org_id, "CI-INV-1", "3001", 1000, 180, 1180),
        _invoice(org_id, "CI-CR-POS", "4002", 500, 90, 590,
                 status=InvoiceStatus.PAID, raw={"document_type": "credit_note"}),
    ])
    db = SessionLocal()
    try:
        rep = daily_reports_service.vat_report_period(db, org_id, 2026, 6)
        assert rep["output_vat"] == 90.0
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 5. PCN874 — שורת S1 עם סימן, שורת O משקפת נטו, תיאום 1:1 מול vat_report_period
# ---------------------------------------------------------------------------

def test_pcn874_net_totals_include_credit_and_reconcile(fresh_org):
    org_id = fresh_org()["org_id"]
    _seed_sale_and_credit(org_id)
    db = SessionLocal()
    try:
        out = pcn874.build_pcn874(db, org_id, 2026, 6, company_vat_id="512345678")
        rep = daily_reports_service.vat_report_period(db, org_id, 2026, 6)

        # תיאום 1:1 מול הדוח התקופתי — כולל הזיכוי
        assert out["summary"]["output_vat"] == rep["output_vat"] == 90.0
        assert out["summary"]["sales"] == 500.0      # 1000 - 500 נטו
        assert out["summary"]["net_vat"] == rep["net_vat"]

        lines = out["content"].split("\r\n")
        s1_lines = [l for l in lines if l.startswith("S1")]
        assert len(s1_lines) == 2, "גם הזיכוי מקבל רשומת S1"
        credit_lines = [l for l in s1_lines if "-" in l]
        assert credit_lines, "שורת הזיכוי חייבת לשאת ייצוג סימן שלילי"

        # שורת ה-O (header) נושאת את הנטו: מכירות 500, מע"מ עסקאות 90
        header = lines[0]
        assert header.startswith("O")
        assert "00000000500" in header   # total_sales נטו, רוחב 11
        assert "000000090" in header     # output_vat נטו, רוחב 9
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 6. openfrmt — C100 לזיכוי: קוד 330, סכום שלילי כמו שהוא
# ---------------------------------------------------------------------------

def test_openfrmt_c100_credit_gets_330_and_negative_amounts(fresh_org):
    from cfo.services import openfrmt

    org_id = fresh_org()["org_id"]
    _seed_sale_and_credit(org_id)
    db = SessionLocal()
    try:
        out = openfrmt.build_openfrmt(db, org_id, date(2026, 6, 1), date(2026, 6, 30))
        c100 = [l for l in out["bkmvdata"].split("\r\n") if l.startswith("C100")]
        assert len(c100) == 2
        credit_lines = [l for l in c100 if "4001" in l]
        assert credit_lines, "לא נמצאה שורת C100 לזיכוי"
        line = credit_lines[0]
        assert "330" in line[:30], f"קוד סוג מסמך 330 חסר בשורת הזיכוי: {line[:40]}"
        assert "-" in line, "סכום הזיכוי חייב להישאר שלילי בשורת C100"
        # המיפוי 330 מתועד כהערכה (approximate_mappings) — לא ערך מומצא-בשקט
        assert "330" in str(out["summary"]["approximate_mappings"])
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 7. דשבורד — הכנסות החודש (accrual) כוללות את הזיכוי (מקטין)
# ---------------------------------------------------------------------------

def test_dashboard_month_revenue_includes_credit(fresh_org):
    from cfo.services.dashboard_service import DashboardService

    org_id = fresh_org()["org_id"]
    _seed_sale_and_credit(org_id)
    db = SessionLocal()
    try:
        svc = DashboardService(db, org_id)
        revenue = svc._month_revenue_accrual(date(2026, 6, 1), date(2026, 6, 30))
        assert revenue == 590.0  # 1180 - 590
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 8. AR aging — זיכוי (balance=0, paid) לא מופיע כחוב פתוח
# ---------------------------------------------------------------------------

def test_credit_note_absent_from_ar_aging(fresh_org):
    from cfo.services.dashboard_service import DashboardService

    org_id = fresh_org()["org_id"]
    _seed(org_id, [
        _invoice(org_id, "CI-INV-1", "3001", 1000, 180, 1180,
                 status=InvoiceStatus.SENT, balance=1180),
        # זיכוי כפי שהנרמול שומר אותו: paid, balance=0
        _invoice(org_id, "CI-CR-1", "4001", -500, -90, -590,
                 status=InvoiceStatus.PAID, raw={"document_type": "credit_note"}),
    ])
    db = SessionLocal()
    try:
        aging = DashboardService(db, org_id).get_ar_aging()
        total = float(aging.get("total", aging.get("total_ar", 0)) or 0)
        assert total == 1180.0, f"זיכוי חדר לגיול החובות: {aging}"
    finally:
        db.close()


def test_supplier_credit_reduces_input_vat(fresh_org):
    """זיכוי ספק (bill שלילי אחרי הנרמול) מקטין את מע"מ התשומות —
    abs() ישן היה הופך אותו להגדלה (קיזוז ביתר, אסור בחוק)."""
    from datetime import date
    from decimal import Decimal
    from cfo.database import SessionLocal
    from cfo.models import Bill, BillStatus
    from cfo.services import financial_synthesis

    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        db.add(Bill(organization_id=org_id, external_id="b-reg", source="sumit",
                    bill_number="B-1", issue_date=date(2026, 5, 10), status=BillStatus.PAID,
                    subtotal=Decimal("1000"), tax=Decimal("180"), total=Decimal("1180"),
                    paid_amount=Decimal("1180"), balance=Decimal("0")))
        db.add(Bill(organization_id=org_id, external_id="b-credit", source="sumit",
                    bill_number="B-2", issue_date=date(2026, 5, 20), status=BillStatus.PAID,
                    subtotal=Decimal("-500"), tax=Decimal("-90"), total=Decimal("-590"),
                    paid_amount=Decimal("-590"), balance=Decimal("0")))
        db.commit()
        pos = financial_synthesis.compute_vat_position(db, org_id,
                                                       start=date(2026, 5, 1), end=date(2026, 5, 31))
        assert round(pos["input_vat"], 2) == 90.0  # 180 - 90, לא 270
    finally:
        db.close()
