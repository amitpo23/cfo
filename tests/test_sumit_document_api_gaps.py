"""Wave 2 Step 8 — SUMIT API gaps found by reading the real swagger.json
(https://api.sumit.co.il/swagger/v1/swagger.json), not by guessing:

8.1 — /scheduleddocuments/documents/createfromdocument/ only accepts an
      existing DocumentID (clones it) — there is no date-driven "schedule a
      future document from raw details" endpoint.
8.2 — cash/cheque payments are recorded via a "Payments" array on the
      document-create request itself (Accounting_Typed_DocumentPayment),
      not through a separate charge call.
8.4 — "OriginalDocumentID" on document-create is SUMIT's documented
      mechanism for linking a credit note to the invoice it credits.
"""
import asyncio
import httpx
from datetime import date
from decimal import Decimal

from cfo.integrations.sumit_integration import SumitIntegration
from cfo.integrations.sumit_models import DocumentItem, DocumentPayment, DocumentRequest


def _sumit():
    return SumitIntegration(api_key="test-key", company_id="1")


def test_create_document_from_existing_clones_by_document_id():
    """8.1 — the real endpoint clones an existing document; it has no
    schedule_date parameter at all (verified against the live swagger spec)."""
    sumit = _sumit()
    captured = {}

    async def _run():
        async def _fake_post(method=None, url=None, json=None, **kwargs):
            captured["url"] = url
            captured["json"] = json
            request = httpx.Request("POST", "https://api.sumit.co.il" + url)
            return httpx.Response(200, request=request, json={
                "Status": 0,
                "Data": {"ScheduledDocuments": [
                    {"ScheduledDocumentID": 555, "Date": "2026-08-01T00:00:00", "Total": 236.0}
                ]},
            })

        sumit.client.request = _fake_post
        try:
            return await sumit.create_document_from_existing("999")
        finally:
            await sumit.client.aclose()

    result = asyncio.run(_run())

    assert captured["url"] == "/scheduleddocuments/documents/createfromdocument/"
    assert captured["json"]["DocumentID"] == 999
    assert "ScheduleDate" not in captured["json"]
    assert len(result) == 1
    assert result[0].scheduled_document_id == "555"
    assert result[0].date == date(2026, 8, 1)
    assert result[0].total == Decimal("236.0")


def test_create_document_sends_cash_payment_details():
    """8.2 — a cash payment on the document-create Payments array."""
    sumit = _sumit()
    captured = {}

    async def _run():
        async def _fake_post(method=None, url=None, json=None, **kwargs):
            captured["json"] = json
            request = httpx.Request("POST", "https://api.sumit.co.il" + url)
            return httpx.Response(200, request=request, json={
                "Status": 0, "Data": {"DocumentID": 1, "DocumentNumber": "1001"},
            })

        sumit.client.request = _fake_post
        try:
            await sumit.create_document(DocumentRequest(
                customer_id="123",
                document_type="invoice_receipt",
                items=[DocumentItem(description="שירות", quantity=Decimal("1"), price=Decimal("100"))],
                payments=[DocumentPayment(method="cash", amount=Decimal("100"))],
            ))
        finally:
            await sumit.client.aclose()

    asyncio.run(_run())

    payments = captured["json"]["Payments"]
    assert len(payments) == 1
    assert payments[0]["Type"] == "Cash"
    assert payments[0]["Amount"] == 100.0
    assert payments[0]["Details_Cash"] == {}


def test_create_document_sends_cheque_payment_details():
    """8.2 — a cheque payment carries bank/branch/account/cheque number/due date."""
    sumit = _sumit()
    captured = {}

    async def _run():
        async def _fake_post(method=None, url=None, json=None, **kwargs):
            captured["json"] = json
            request = httpx.Request("POST", "https://api.sumit.co.il" + url)
            return httpx.Response(200, request=request, json={
                "Status": 0, "Data": {"DocumentID": 1, "DocumentNumber": "1001"},
            })

        sumit.client.request = _fake_post
        try:
            await sumit.create_document(DocumentRequest(
                customer_id="123",
                document_type="invoice_receipt",
                items=[DocumentItem(description="שירות", quantity=Decimal("1"), price=Decimal("500"))],
                payments=[DocumentPayment(
                    method="cheque", amount=Decimal("500"),
                    bank_number=12, branch_number=345, account_number="6789",
                    cheque_number="1042", due_date=date(2026, 9, 1),
                )],
            ))
        finally:
            await sumit.client.aclose()

    asyncio.run(_run())

    payment = captured["json"]["Payments"][0]
    assert payment["Type"] == "Cheque"
    assert payment["Details_Cheque"] == {
        "BankNumber": 12,
        "BranchNumber": 345,
        "AccountNumber": "6789",
        "ChequeNumber": "1042",
        "DueDate": "2026-09-01",
    }


def test_create_document_without_payments_omits_payments_key():
    """Documents created without an explicit payment (e.g. a plain invoice
    awaiting future collection) must not send an empty Payments array."""
    sumit = _sumit()
    captured = {}

    async def _run():
        async def _fake_post(method=None, url=None, json=None, **kwargs):
            captured["json"] = json
            request = httpx.Request("POST", "https://api.sumit.co.il" + url)
            return httpx.Response(200, request=request, json={
                "Status": 0, "Data": {"DocumentID": 1, "DocumentNumber": "1001"},
            })

        sumit.client.request = _fake_post
        try:
            await sumit.create_document(DocumentRequest(
                customer_id="123",
                document_type="invoice",
                items=[DocumentItem(description="שירות", quantity=Decimal("1"), price=Decimal("100"))],
            ))
        finally:
            await sumit.client.aclose()

    asyncio.run(_run())

    assert "Payments" not in captured["json"]


def test_create_document_sends_original_document_id_for_credit_note():
    """8.4 — SUMIT links a credit note to the invoice it credits via
    OriginalDocumentID on the create-document request (documented field,
    not a separate refund/reversal endpoint — none exists)."""
    sumit = _sumit()
    captured = {}

    async def _run():
        async def _fake_post(method=None, url=None, json=None, **kwargs):
            captured["json"] = json
            request = httpx.Request("POST", "https://api.sumit.co.il" + url)
            return httpx.Response(200, request=request, json={
                "Status": 0, "Data": {"DocumentID": 2, "DocumentNumber": "2001"},
            })

        sumit.client.request = _fake_post
        try:
            await sumit.create_document(DocumentRequest(
                customer_id="123",
                document_type="credit_note",
                items=[DocumentItem(description="זיכוי", quantity=Decimal("1"), price=Decimal("100"))],
                original_document_id="999",
            ))
        finally:
            await sumit.client.aclose()

    asyncio.run(_run())

    assert captured["json"]["OriginalDocumentID"] == 999
