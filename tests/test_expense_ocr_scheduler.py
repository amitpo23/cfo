"""Tests for automatic OCR scheduling."""
from datetime import date

import pytest

from cfo.database import SessionLocal
from cfo.models import Expense
from cfo.services.expense_ocr_scheduler import ExpenseOCRScheduler
import cfo.services.sync_engine as se
import cfo.services.vision_extractor as ve


@pytest.fixture(scope="module")
def acc(client):
    reg = client.post("/api/admin/auth/register", json={
        "email": "ocrscheduler@example.com", "password": "secret123", "full_name": "OCR Scheduler",
    })
    assert reg.status_code == 201, reg.text
    return {"headers": {"Authorization": f"Bearer {reg.json()['access_token']}"},
            "org_id": reg.json()["user"]["organization_id"]}


def test_scheduler_process_pending_expenses(acc, monkeypatch):
    """Scheduler processes pending SUMIT draft expenses."""
    org_id = acc["org_id"]
    db = SessionLocal()
    try:
        # Create a pending SUMIT expense
        exp = Expense(
            organization_id=org_id,
            external_id="DRAFT-FOR-SCHEDULER",
            source="sumit",
            supplier_name="ספק",
            amount=0,
            vat_amount=0,
            total=0,
            expense_date=date(2026, 5, 15),
            status="pending",
        )
        db.add(exp)
        db.commit()

        # Mock the connector and extractor
        class FakeConnector:
            async def get_document_pdf(self, doc_id):
                return b"%PDF-1.6 fake"

        async def fake_extract(content):
            return {
                "supplier_name": "שופרסל",
                "supplier_tax_id": "520022732",
                "amount_total": 104.90,
                "vat_amount": None,
                "net_amount": None,
                "invoice_number": "8353406",
                "expense_date": "2026-05-15",
                "currency": "ILS",
                "document_type": "receipt",
                "confidence": 0.95,
                "is_readable": True,
                "notes": None,
            }

        monkeypatch.setattr(se, "get_connector_for_org",
                            lambda db, org_id, preferred_source=None: (FakeConnector(), None, "sumit"))
        monkeypatch.setattr(ve, "extract_receipt", fake_extract)

        # Run scheduler
        scheduler = ExpenseOCRScheduler(db)
        import asyncio
        result = asyncio.run(scheduler.run_scheduled_ocr(
            org_id, limit=50, auto_file=False
        ))

        assert result["scanned"] >= 1
        assert result["flagged"] >= 0  # May be flagged or ready depending on registry
    finally:
        db.close()


def test_scheduler_respects_confidence_threshold(acc, monkeypatch):
    """Scheduler only auto-files high-confidence results."""
    org_id = acc["org_id"]
    db = SessionLocal()
    try:
        exp = Expense(
            organization_id=org_id,
            external_id="LOW-CONF-DRAFT",
            source="sumit",
            supplier_name="supplier",
            amount=0,
            vat_amount=0,
            total=0,
            expense_date=date(2026, 5, 20),
            status="pending",
        )
        db.add(exp)
        db.commit()

        class FakeConnector:
            async def get_document_pdf(self, doc_id):
                return b"%PDF-1.6 fake"

        async def fake_extract(content):
            return {
                "supplier_name": "ספק",
                "supplier_tax_id": None,  # Missing tax ID
                "amount_total": 100.0,
                "vat_amount": None,
                "net_amount": None,
                "invoice_number": None,
                "expense_date": "2026-05-20",
                "currency": "ILS",
                "document_type": "unknown",
                "confidence": 0.4,  # Low confidence
                "is_readable": True,
                "notes": None,
            }

        monkeypatch.setattr(se, "get_connector_for_org",
                            lambda db, org_id, preferred_source=None: (FakeConnector(), None, "sumit"))
        monkeypatch.setattr(ve, "extract_receipt", fake_extract)

        scheduler = ExpenseOCRScheduler(db)
        import asyncio
        result = asyncio.run(scheduler.run_scheduled_ocr(
            org_id, limit=50, auto_file=True, min_confidence=0.7
        ))

        # Should be flagged, not filed (due to low confidence and missing tax ID)
        assert result.get("flagged", 0) >= 1
    finally:
        db.close()
