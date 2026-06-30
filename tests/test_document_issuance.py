from datetime import date
from decimal import Decimal

from cfo.database import SessionLocal
from cfo.integrations.sumit_models import DocumentResponse
from cfo.models import Invoice
from cfo.services import document_issuance_service
from cfo.services.document_issuance_service import DocumentIssuanceService


def test_financial_document_create_persists_to_db(client, fresh_org):
    org = fresh_org()
    resp = client.post("/api/financial/documents", headers=org["headers"], json={
        "document_type": "proforma",
        "customer_id": "לקוח בדיקה",
        "customer_name": "לקוח בדיקה",
        "send_to_sumit": False,
        "items": [
            {"description": "שירות", "quantity": 2, "unit_price": 100, "vat_rate": 18, "discount": 0}
        ],
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()["data"]
    assert body["document_type"] == "proforma"
    assert body["total"] == 236

    db = SessionLocal()
    try:
        invoice = db.query(Invoice).filter(
            Invoice.organization_id == org["org_id"],
            Invoice.id == body["id"],
        ).first()
        assert invoice is not None
        assert invoice.raw_data["document_type"] == "proforma"
        assert float(invoice.total) == 236
    finally:
        db.close()


def test_document_service_issues_to_sumit_and_updates_local_row(monkeypatch, fresh_org):
    org = fresh_org()
    db = SessionLocal()

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def create_document(self, request):
            assert request.document_type == "invoice"
            return DocumentResponse(
                document_id="SUMIT-123",
                document_number="10001",
                document_type="invoice",
                customer_id=request.customer_id,
                total_amount=Decimal("118"),
                vat_amount=Decimal("18"),
                status="open",
                issue_date=date.today(),
            )

    class FakeConnector:
        async def _get_client(self):
            return FakeClient()

    def fake_get_connector_for_org(_db, organization_id, preferred_source=None):
        assert organization_id == org["org_id"]
        assert preferred_source == "sumit"
        return FakeConnector(), 1, "sumit"

    monkeypatch.setattr(document_issuance_service, "get_connector_for_org", fake_get_connector_for_org)

    try:
        service = DocumentIssuanceService(db, org["org_id"])
        result = __import__("asyncio").run(service.create_document(
            document_type="invoice",
            customer_id="123",
            customer_name="לקוח",
            send_to_sumit=True,
            items=[{"description": "שירות", "quantity": 1, "unit_price": 100, "vat_rate": 18}],
        ))
        assert result["external_id"] == "SUMIT-123"
        assert result["document_number"] == "10001"

        invoice = db.query(Invoice).filter(Invoice.id == result["id"]).first()
        assert invoice.external_id == "SUMIT-123"
        assert invoice.invoice_number == "10001"
        assert invoice.source == "sumit"
    finally:
        db.close()
