"""fetch_customers() derived the customer roster from SUMIT's get_debt_report()
-- found via the live 2026-07-04 data-parity check to be badly incomplete
(2 generic "Unknown"-named debt rows for a company with 15 real, named,
open invoices) because of a reverse-engineered DebitSource/CreditSource
payload that only captures a narrow subset of debt. Confirmed live: SUMIT's
list_documents() already returns the real customer_id + customer_name for
every document -- the same information fetch_invoices() already uses for
contact_external_id, just never wired into the Contact side. Every invoice
whose real customer never appeared in the debt report silently got
contact_id=None on sync (ledger_service._upsert_invoice only sets contact_id
when a matching Contact row already exists) -- the direct root cause of
every AR invoice showing customer "Unknown" in production.
"""
import asyncio
from datetime import date
from decimal import Decimal

import pytest


class _FakeDoc:
    def __init__(self, id_, customer_id, customer_name):
        self.id = id_
        self.customer_id = customer_id
        self.customer_name = customer_name
        self.total = Decimal("100")
        self.date = date(2026, 1, 1)


class _FakeClient:
    """Fails the test if get_debt_report is ever called -- the whole point
    of the fix is to stop depending on that endpoint for customer identity."""

    def __init__(self, documents):
        self._documents = documents

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def list_documents(self, request):
        return self._documents

    async def get_debt_report(self, request):
        raise AssertionError("fetch_customers must not call get_debt_report anymore")


def test_fetch_customers_derives_real_names_from_documents(monkeypatch):
    from cfo.services.sumit_connector import SumitConnector

    docs = [
        _FakeDoc("d1", "cust-1", "אליהב כהן"),
        _FakeDoc("d2", "cust-2", "מדיצי שיווק בתי מלון בעמ"),
        _FakeDoc("d3", "cust-1", "אליהב כהן"),  # same customer, second invoice
    ]
    connector = SumitConnector(api_key="k", company_id="c")
    async def _fake_get_client():
        return _FakeClient(docs)
    monkeypatch.setattr(connector, "_get_client", _fake_get_client)

    result = asyncio.run(connector.fetch_customers())

    assert len(result.items) == 2  # deduplicated by customer_id
    by_id = {c.external_id: c for c in result.items}
    assert by_id["cust-1"].name == "אליהב כהן"
    assert by_id["cust-2"].name == "מדיצי שיווק בתי מלון בעמ"
    assert all(c.contact_type == "customer" for c in result.items)


def test_fetch_customers_skips_documents_without_customer_id(monkeypatch):
    from cfo.services.sumit_connector import SumitConnector

    docs = [_FakeDoc("d1", None, None), _FakeDoc("d2", "cust-1", "לקוח אמיתי")]
    connector = SumitConnector(api_key="k", company_id="c")
    async def _fake_get_client():
        return _FakeClient(docs)
    monkeypatch.setattr(connector, "_get_client", _fake_get_client)

    result = asyncio.run(connector.fetch_customers())

    assert len(result.items) == 1
    assert result.items[0].external_id == "cust-1"
