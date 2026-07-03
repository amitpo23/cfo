"""Wave 2 Step 8 service-layer wiring for the gaps closed in the SUMIT
integration client (test_sumit_document_api_gaps.py):

8.4 — issuing a credit_note against an existing invoice must pass
      OriginalDocumentID through to SUMIT and reduce the original invoice's
      local balance (SUMIT has no separate refund/reversal endpoint — a
      linked credit note is the only refund primitive it exposes).
8.1 — cloning an existing document into its next scheduled occurrence.
8.2 — recording a cash/cheque payment on a document at issue time.
"""
import asyncio
from datetime import date
from decimal import Decimal

from cfo.database import SessionLocal
from cfo.integrations.sumit_models import DocumentResponse, ScheduledDocumentResult
from cfo.models import Contact, ContactType, Invoice, InvoiceStatus
from cfo.services import document_issuance_service
from cfo.services.document_issuance_service import DocumentIssuanceService


def _fresh_invoice(db, org_id, total="1000"):
    contact = Contact(organization_id=org_id, name="לקוח קרדיט", contact_type=ContactType.CUSTOMER)
    db.add(contact)
    db.flush()
    invoice = Invoice(
        organization_id=org_id, contact_id=contact.id, invoice_number="INV-1",
        external_id="SUMIT-ORIG-1", source="sumit",
        total=Decimal(total), balance=Decimal(total), status=InvoiceStatus.SENT,
        issue_date=date.today(),
    )
    db.add(invoice)
    db.commit()
    return invoice


def test_credit_note_passes_original_document_id_and_reduces_balance(monkeypatch, fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        original = _fresh_invoice(db, org_id, total="1000")
        captured = {}

        class FakeClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return False

            async def create_document(self, request):
                captured["original_document_id"] = request.original_document_id
                return DocumentResponse(
                    document_id="SUMIT-CREDIT-1", document_number="C-1",
                    document_type="credit_note", customer_id=request.customer_id,
                    total_amount=Decimal("300"), vat_amount=Decimal("0"),
                    status="open", issue_date=date.today(),
                )

        class FakeConnector:
            async def _get_client(self):
                return FakeClient()

        monkeypatch.setattr(
            document_issuance_service, "get_connector_for_org",
            lambda _db, _org, preferred_source=None: (FakeConnector(), 1, "sumit"),
        )

        service = DocumentIssuanceService(db, org_id)
        result = asyncio.run(service.create_document(
            document_type="credit_note",
            customer_id="123", customer_name="לקוח קרדיט",
            items=[{"description": "זיכוי חלקי", "quantity": 1, "unit_price": 300, "vat_rate": 0}],
            send_to_sumit=True,
            original_invoice_id=original.id,
        ))

        assert captured["original_document_id"] == "SUMIT-ORIG-1"
        assert result["credited_invoice_id"] == original.id

        db.refresh(original)
        assert float(original.balance) == 700.0
        assert original.status == InvoiceStatus.PARTIALLY_PAID
    finally:
        db.close()


def test_credit_note_fully_offsetting_marks_original_paid(monkeypatch, fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        original = _fresh_invoice(db, org_id, total="500")

        class FakeClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return False

            async def create_document(self, request):
                return DocumentResponse(
                    document_id="SUMIT-CREDIT-2", document_number="C-2",
                    document_type="credit_note", customer_id=request.customer_id,
                    total_amount=Decimal("500"), vat_amount=Decimal("0"),
                    status="open", issue_date=date.today(),
                )

        class FakeConnector:
            async def _get_client(self):
                return FakeClient()

        monkeypatch.setattr(
            document_issuance_service, "get_connector_for_org",
            lambda _db, _org, preferred_source=None: (FakeConnector(), 1, "sumit"),
        )

        service = DocumentIssuanceService(db, org_id)
        asyncio.run(service.create_document(
            document_type="credit_note",
            customer_id="123", customer_name="לקוח קרדיט",
            items=[{"description": "זיכוי מלא", "quantity": 1, "unit_price": 500, "vat_rate": 0}],
            send_to_sumit=True,
            original_invoice_id=original.id,
        ))

        db.refresh(original)
        assert float(original.balance) == 0.0
        assert original.status == InvoiceStatus.PAID
    finally:
        db.close()


def test_original_invoice_id_from_other_org_is_rejected(monkeypatch, fresh_org):
    """Org isolation: crediting an invoice id from a different org must fail,
    not silently credit whatever row happens to share that id."""
    org_a = fresh_org()["org_id"]
    org_b = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        original = _fresh_invoice(db, org_a, total="1000")

        service = DocumentIssuanceService(db, org_b)
        try:
            asyncio.run(service.create_document(
                document_type="credit_note",
                customer_id="123", customer_name="לקוח",
                items=[{"description": "זיכוי", "quantity": 1, "unit_price": 100, "vat_rate": 0}],
                send_to_sumit=False,
                original_invoice_id=original.id,
            ))
            raised = None
        except ValueError as exc:
            raised = exc
        assert raised is not None
    finally:
        db.close()


def test_create_scheduled_occurrence_clones_invoice_locally(monkeypatch, fresh_org):
    """8.1 — cloning an existing (already-issued) document creates a new
    local Invoice row mirroring the source, at the cloned id/date/total."""
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        source = _fresh_invoice(db, org_id, total="236")

        class FakeClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return False

            async def create_document_from_existing(self, document_id):
                assert document_id == "SUMIT-ORIG-1"
                return [ScheduledDocumentResult(
                    scheduled_document_id="SUMIT-CLONE-1",
                    date=date(2026, 8, 1),
                    total=Decimal("236"),
                )]

        class FakeConnector:
            async def _get_client(self):
                return FakeClient()

        monkeypatch.setattr(
            document_issuance_service, "get_connector_for_org",
            lambda _db, _org, preferred_source=None: (FakeConnector(), 1, "sumit"),
        )

        service = DocumentIssuanceService(db, org_id)
        created = asyncio.run(service.create_scheduled_occurrence(source.id))

        assert len(created) == 1
        assert created[0]["external_id"] == "SUMIT-CLONE-1"
        assert created[0]["total"] == 236.0
        assert created[0]["issue_date"] == "2026-08-01"

        clone = db.query(Invoice).filter(Invoice.external_id == "SUMIT-CLONE-1").first()
        assert clone is not None
        assert clone.organization_id == org_id
        assert clone.contact_id == source.contact_id
        assert float(clone.total) == 236.0
    finally:
        db.close()


def test_create_document_forwards_cash_payment_to_sumit_request(monkeypatch, fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        captured = {}

        class FakeClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return False

            async def create_document(self, request):
                captured["payments"] = request.payments
                return DocumentResponse(
                    document_id="SUMIT-1", document_number="1001",
                    document_type=request.document_type, customer_id=request.customer_id,
                    total_amount=Decimal("100"), vat_amount=Decimal("0"),
                    status="open", issue_date=date.today(),
                )

        class FakeConnector:
            async def _get_client(self):
                return FakeClient()

        monkeypatch.setattr(
            document_issuance_service, "get_connector_for_org",
            lambda _db, _org, preferred_source=None: (FakeConnector(), 1, "sumit"),
        )

        service = DocumentIssuanceService(db, org_id)
        asyncio.run(service.create_document(
            document_type="invoice_receipt",
            customer_id="123", customer_name="לקוח",
            items=[{"description": "שירות", "quantity": 1, "unit_price": 100, "vat_rate": 0}],
            send_to_sumit=True,
            payments=[{"method": "cash", "amount": 100}],
        ))

        assert captured["payments"] is not None
        assert captured["payments"][0].method == "cash"
        assert captured["payments"][0].amount == Decimal("100")
    finally:
        db.close()


def test_route_credits_original_invoice_without_sumit(client, fresh_org):
    """Route-level: original_invoice_id reduces the original's balance even
    with send_to_sumit=False (no live SUMIT credentials needed for this test)."""
    iso = fresh_org()
    org_id, headers = iso["org_id"], iso["headers"]
    db = SessionLocal()
    try:
        original = _fresh_invoice(db, org_id, total="1000")
        original_id = original.id
    finally:
        db.close()

    r = client.post("/api/financial/documents", headers=headers, json={
        "document_type": "credit_note",
        "customer_id": "123", "customer_name": "לקוח קרדיט",
        "items": [{"description": "זיכוי", "quantity": 1, "unit_price": 400, "vat_rate": 0}],
        "send_to_sumit": False,
        "original_invoice_id": original_id,
    })
    assert r.status_code == 200, r.text
    assert r.json()["data"]["credited_invoice_id"] == original_id

    db = SessionLocal()
    try:
        refreshed = db.query(Invoice).filter(Invoice.id == original_id).first()
        assert float(refreshed.balance) == 600.0
        assert refreshed.status == InvoiceStatus.PARTIALLY_PAID
    finally:
        db.close()


def test_route_schedule_next_requires_sumit_configured(client, fresh_org):
    iso = fresh_org()
    org_id, headers = iso["org_id"], iso["headers"]
    db = SessionLocal()
    try:
        source = _fresh_invoice(db, org_id, total="236")
        invoice_id = source.id
    finally:
        db.close()

    r = client.post(f"/api/financial/documents/{invoice_id}/schedule-next", headers=headers)
    assert r.status_code == 400
