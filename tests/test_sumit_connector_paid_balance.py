"""חשבונית שסטטוס SUMIT שלה paid/closed חייבת להתנרמל עם יתרה 0.

באג חי (org 1, נמצא 2026-07-12): SUMIT לא מאכלס paid_amount על מסמכים סגורים,
ולכן balance = total - 0 = total. ארבע חשבוניות "PAID" הציגו יתרה פתוחה של
₪215,400 — מה שהיה שולח תזכורות גבייה שגויות ומנפח את דוח ה-AR.
"""
import asyncio
from datetime import date
from types import SimpleNamespace


def _doc(doc_id, total, status, paid_amount=0):
    return SimpleNamespace(
        id=doc_id, total=total, paid_amount=paid_amount, date=date(2026, 5, 10),
        customer_id="c1", document_number=f"N-{doc_id}", status=status,
        currency="ILS", document_type="invoice",
    )


class _Client:
    def __init__(self, docs):
        self._docs = docs
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
        return self._docs if type_code == "0" else []


def _fetch(monkeypatch, docs):
    from cfo.services.sumit_connector import SumitConnector

    connector = SumitConnector(api_key="k", company_id="c")
    client = _Client(docs)

    async def _fake_get_client(self):
        return client

    monkeypatch.setattr(SumitConnector, "_get_client", _fake_get_client)
    return asyncio.run(connector.fetch_invoices())


def test_paid_invoice_without_paid_amount_normalizes_to_zero_balance(monkeypatch):
    result = _fetch(monkeypatch, [_doc("d1", 75000, status="paid")])
    (inv,) = result.items
    assert inv.status == "paid"
    assert float(inv.balance) == 0.0
    assert float(inv.paid_amount) == 75000.0


def test_closed_invoice_normalizes_to_zero_balance(monkeypatch):
    result = _fetch(monkeypatch, [_doc("d2", 23600, status="closed")])
    (inv,) = result.items
    assert inv.status == "paid"
    assert float(inv.balance) == 0.0


def test_open_invoice_keeps_real_balance(monkeypatch):
    result = _fetch(monkeypatch, [_doc("d3", 10000, status="open", paid_amount=4000)])
    (inv,) = result.items
    assert float(inv.balance) == 6000.0
    assert float(inv.paid_amount) == 4000.0
