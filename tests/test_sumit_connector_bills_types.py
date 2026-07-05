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
