"""fetch_bills חייב לכסות את שני סוגי מסמכי ההוצאה של SUMIT — 15 (ExpenseReceipt)
ו-16 (ExpenseInvoice) — בלי טיוטות ובלי כפילויות.

ממצא אודיט התאימות החי (2026-07-05): המסמכים האמיתיים של העסק הם סוג 15
(274 מסמכי 2026); סוג 16 כמעט ריק. commit 23353ca החליף את הפילטר מ-15 ל-16
מתוך הנחה הפוכה — הספרים תאמו באותו רגע אך הסנכרון היה קופא בשקט מכאן והלאה.
"""
import asyncio
from datetime import date
from types import SimpleNamespace


def _doc(doc_id, total, status="closed"):
    return SimpleNamespace(
        id=doc_id, total=total, paid_amount=0, date=date(2026, 5, 10),
        customer_id="c1", document_number=f"N-{doc_id}", status=status,
        currency="ILS",
    )


class _TypeAwareClient:
    """מחזיר מסמכים שונים לפי type_code שנשלח ב-DocumentListRequest."""

    def __init__(self):
        self.requested_types = []
        self.docs_by_type = {
            "15": [_doc("d15", 118), _doc("d15-draft", 0, status="draft")],
            "16": [_doc("d16", 236)],
        }

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def list_documents(self, request):
        (type_code,) = request.document_types
        if type_code in self.requested_types:
            return []  # עמוד שני — ריק (סיום עימוד)
        self.requested_types.append(type_code)
        return self.docs_by_type.get(type_code, [])


def test_fetch_bills_covers_both_expense_types_and_skips_drafts(monkeypatch):
    from cfo.services.sumit_connector import SumitConnector

    connector = SumitConnector(api_key="k", company_id="c")
    client = _TypeAwareClient()

    async def _fake_get_client(self):
        return client

    monkeypatch.setattr(SumitConnector, "_get_client", _fake_get_client)

    result = asyncio.run(connector.fetch_bills())

    assert sorted(client.requested_types) == ["15", "16"], (
        "הסנכרון חייב לשאול את SUMIT גם על סוג 15 וגם על סוג 16"
    )
    ids = sorted(b.external_id for b in result.items)
    assert ids == ["d15", "d16"], f"expected real docs only, got {ids}"
    # הטיוטה הסרוקה (status=draft, סכום 0) לא הופכת ל-Bill בספרים
    assert "d15-draft" not in ids


def test_fetch_invoices_never_pulls_receipts_or_expenses(monkeypatch):
    """חשבוניות נמשכות רק מסוגי הכנסה (0,1) + זיכוי (5) — קבלה (2) והוצאות (15/16)
    לעולם לא.

    עדכון 2026-07-13: לפי ה-swagger הרשמי (Accounting_Typed_DocumentType) קוד 5 הוא
    CreditInvoice (חשבונית זיכוי) — מסמך מע"מ בצד ההכנסות שחייב להימשך, אחרת מע"מ
    העסקאות מדווח ביתר; Receipt הוא קוד 2. שורש ממצא H0 באודיט התאימות (שורת
    legacy עם קוד גולמי '5') מטופל בהחרגה ב-select_vat_documents, לא כאן.
    """
    from cfo.services.sumit_connector import SumitConnector

    connector = SumitConnector(api_key="k", company_id="c")
    client = _TypeAwareClient()  # מחזיר [] לסוגים לא מוכרים

    async def _fake_get_client(self):
        return client

    monkeypatch.setattr(SumitConnector, "_get_client", _fake_get_client)
    asyncio.run(connector.fetch_invoices())

    assert set(client.requested_types) == {"0", "1", "5", "6"}, (
        f"fetch_invoices חייב לבקש סוגי הכנסה 0+1 וזיכוי 5, ביקש: {client.requested_types}"
    )
    for forbidden in ("2", "15", "16"):
        assert forbidden not in client.requested_types, (
            f"סוג {forbidden} (קבלה/הוצאה) לא אמור להימשך כחשבונית"
        )


def test_fetch_invoices_covers_invoice_and_invoice_receipt(monkeypatch):
    """הכנסות = חשבונית (סוג 0) + חשבונית-מס-קבלה (סוג 1). בלי סוג 1 מפספסים הכנסה.

    ממצא חי (2026-07-06, תיק עומר-ועודד org 5): 9 מסמכי סוג 1 בסך ₪124,605
    לא סונכרנו כי fetch_invoices משך רק סוג 0. שניהם מסמכי הכנסה חייבים-מע"מ.
    """
    from cfo.services.sumit_connector import SumitConnector

    connector = SumitConnector(api_key="k", company_id="c")
    client = _TypeAwareClient()
    client.docs_by_type = {
        "0": [_doc("inv0", 234, status="open")],
        "1": [_doc("invrcpt1", 117, status="open"), _doc("d-draft", 0, status="draft")],
    }

    async def _fake_get_client(self):
        return client

    monkeypatch.setattr(SumitConnector, "_get_client", _fake_get_client)
    result = asyncio.run(connector.fetch_invoices())

    # מאז 2026-07-13 נמשך גם סוג 5 (CreditInvoice) — כאן בודקים שסוגי ההכנסה 0+1
    # שניהם נשאלים (הזיכוי נבדק ב-tests/test_credit_invoices_chain.py).
    assert {"0", "1"} <= set(client.requested_types), (
        f"fetch_invoices חייב לבקש סוג 0 וגם סוג 1, ביקש: {client.requested_types}"
    )
    ids = sorted(i.external_id for i in result.items)
    assert ids == ["inv0", "invrcpt1"], f"expected both income docs, got {ids}"
    assert "d-draft" not in ids, "טיוטה לא הופכת לחשבונית"
