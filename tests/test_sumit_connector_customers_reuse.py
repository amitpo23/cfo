"""fetch_customers() ↔ fetch_invoices() redundant network call (ממצא
25/08/2026, בדיקה חיה על אליהב כהן/org2). שניהם קוראים באופן עצמאי
ל-`_list_documents_all(..., "0", ...)` — אותם מסמכים בדיוק, פעמיים.

ריצת-sync מלאה אחת לארגון עושה 9 קריאות רשת אמיתיות (invoices=4,
bills=2, payments=2, customers=1; accounts/vendors/bank_transactions/
journal_entries מקומיים, אפס עלות) — מול תקציב גלובלי משותף של 10/דקה
לכל הארגונים יחד. סדר-הסנכרון החדש (25/08) מריץ invoices לפני
customers באותה ריצה בדיוק כדי לאפשר את השימוש-החוזר הזה: אם
fetch_invoices כבר משך את מסמכי סוג-0 באותו updated_since, fetch_customers
צריך להשתמש בהם מהמטמון של המופע במקום לקרוא לרשת שוב — חוסך קריאה
אחת מתוך 9 (~11%) בלי לאבד מידע (אותם מסמכים בדיוק)."""
import asyncio
from datetime import date
from decimal import Decimal


class _FakeDoc:
    def __init__(self, id_, customer_id, customer_name, status="paid"):
        self.id = id_
        self.customer_id = customer_id
        self.customer_name = customer_name
        self.total = Decimal("100")
        self.date = date(2026, 1, 1)
        self.status = status
        self.document_number = f"INV-{id_}"
        self.due_date = None
        self.currency = "ILS"
        self.paid_amount = Decimal("100")


class _CountingClient:
    """Records which document_type code every list_documents call asked for."""

    def __init__(self, docs_by_type):
        self._docs_by_type = docs_by_type
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def list_documents(self, request):
        type_code = request.document_types[0]
        self.calls.append(type_code)
        return self._docs_by_type.get(type_code, [])


def _make_connector(monkeypatch, client):
    from cfo.services.sumit_connector import SumitConnector

    connector = SumitConnector(api_key="k", company_id="c", organization_id=1)

    async def _fake_get_client():
        return client

    monkeypatch.setattr(connector, "_get_client", _fake_get_client)
    return connector


def test_fetch_customers_reuses_type0_documents_already_fetched_by_invoices(monkeypatch):
    docs_0 = [_FakeDoc("d1", "cust-1", "אליהב כהן")]
    client = _CountingClient({"0": docs_0, "1": [], "5": [], "6": []})
    connector = _make_connector(monkeypatch, client)

    invoices_result = asyncio.run(connector.fetch_invoices())
    assert client.calls.count("0") == 1
    assert len(invoices_result.items) == 1

    customers_result = asyncio.run(connector.fetch_customers())

    # No second real call for type-0 documents -- reused invoices' fetch.
    assert client.calls.count("0") == 1
    assert len(customers_result.items) == 1
    assert customers_result.items[0].external_id == "cust-1"
    assert customers_result.items[0].name == "אליהב כהן"


def test_fetch_customers_still_fetches_independently_when_called_standalone(monkeypatch):
    """A caller that never ran fetch_invoices first (e.g. a manual
    "refresh customers only" action) must still get real data -- fall back
    to a real network call, not an empty/stale result."""
    docs_0 = [_FakeDoc("d1", "cust-1", "לקוח אמיתי")]
    client = _CountingClient({"0": docs_0})
    connector = _make_connector(monkeypatch, client)

    result = asyncio.run(connector.fetch_customers())

    assert client.calls.count("0") == 1
    assert len(result.items) == 1
    assert result.items[0].external_id == "cust-1"


def test_fetch_customers_does_not_reuse_a_different_watermark(monkeypatch):
    """Correctness over optimization: if invoices was fetched with a
    different updated_since than customers is now asking for, the cache
    must not be used -- a fresh call is required."""
    from datetime import datetime, timezone

    docs_0 = [_FakeDoc("d1", "cust-1", "לקוח א")]
    client = _CountingClient({"0": docs_0})
    connector = _make_connector(monkeypatch, client)

    asyncio.run(connector.fetch_invoices(updated_since=datetime(2026, 1, 1, tzinfo=timezone.utc)))
    assert client.calls.count("0") == 1

    asyncio.run(connector.fetch_customers(updated_since=datetime(2026, 8, 1, tzinfo=timezone.utc)))

    # Different updated_since -- must not reuse the January cache.
    assert client.calls.count("0") == 2
