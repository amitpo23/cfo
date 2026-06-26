"""Tests for manual bank reconciliation — user override and feedback."""
from datetime import date

import pytest

from cfo.database import SessionLocal
from cfo.models import BankTransaction, Invoice, InvoiceStatus, Expense
from cfo.services.manual_reconciliation import ManualReconciliationService


@pytest.fixture(scope="module")
def acc(client):
    reg = client.post("/api/admin/auth/register", json={
        "email": "reconowner@example.com", "password": "secret123", "full_name": "Recon Owner",
    })
    assert reg.status_code == 201, reg.text
    return {"headers": {"Authorization": f"Bearer {reg.json()['access_token']}"},
            "org_id": reg.json()["user"]["organization_id"]}


def test_manual_match_transaction_to_invoice(acc):
    """User manually matches a bank txn to an invoice."""
    org_id = acc["org_id"]
    db = SessionLocal()
    try:
        # Create test data
        inv = Invoice(
            organization_id=org_id,
            external_id="SUMIT-INV-MANUAL",
            source="sumit",
            issue_date=date(2026, 6, 4),
            status=InvoiceStatus.SENT,
            total=1000,
            balance=1000,
        )
        txn = BankTransaction(
            organization_id=org_id,
            external_id="OF-TXN-MANUAL",
            source="open_finance",
            transaction_date=date(2026, 6, 5),
            description="תשלום לקוח",
            amount=1000,
            currency="ILS",
        )
        db.add_all([inv, txn])
        db.commit()

        # Manually match via service
        service = ManualReconciliationService(db, organization_id=org_id)
        result = service.match_transaction(txn.id, "invoice", inv.id)

        assert result["status"] == "matched"
        assert result["matched_entity_type"] == "invoice"
        assert result["matched_entity_id"] == inv.id

        # Verify DB state
        db.refresh(txn)
        assert txn.is_reconciled is True
        assert txn.matched_entity_type == "invoice"
        assert txn.matched_entity_id == inv.id
    finally:
        db.close()


def test_manual_unmatch_transaction(acc):
    """User manually unmatches a transaction."""
    org_id = acc["org_id"]
    db = SessionLocal()
    try:
        inv = Invoice(
            organization_id=org_id,
            external_id="SUMIT-INV-UNMATCH",
            source="sumit",
            issue_date=date(2026, 6, 4),
            status=InvoiceStatus.SENT,
            total=500,
            balance=500,
        )
        txn = BankTransaction(
            organization_id=org_id,
            external_id="OF-TXN-UNMATCH",
            source="open_finance",
            transaction_date=date(2026, 6, 5),
            description="payment",
            amount=500,
            currency="ILS",
            is_reconciled=True,
            matched_entity_type="invoice",
        )
        txn.matched_entity_id = 999  # Dummy
        db.add_all([inv, txn])
        db.commit()

        service = ManualReconciliationService(db, organization_id=org_id)
        result = service.unmatch_transaction(txn.id)

        assert result["status"] == "unmatched"

        db.refresh(txn)
        assert txn.is_reconciled is False
        assert txn.matched_entity_type is None
        assert txn.matched_entity_id is None
    finally:
        db.close()


def test_classifier_feedback_records_learning(acc):
    """User feedback on classifier correction is recorded."""
    org_id = acc["org_id"]
    db = SessionLocal()
    try:
        exp = Expense(
            organization_id=org_id,
            supplier_name="אקמה בעמ",
            amount=100,
            vat_amount=18,
            total=118,
            expense_date=date(2026, 6, 1),
            category="office",  # Wrong category
        )
        db.add(exp)
        db.commit()

        service = ManualReconciliationService(db, organization_id=org_id)
        result = service.record_classifier_feedback(
            exp.id,
            "expense",
            "professional",
            feedback_text="This is actually professional services (accounting)",
        )

        assert result["status"] == "feedback_recorded"
        assert result["new_category"] == "professional"
        assert result["old_category"] == "office"

        db.refresh(exp)
        assert exp.category == "professional"
        assert exp.classifier_feedback is not None
        assert len(exp.classifier_feedback) == 1
        assert exp.classifier_feedback[0]["old_category"] == "office"
        assert exp.classifier_feedback[0]["new_category"] == "professional"
    finally:
        db.close()


def test_list_unmatched_transactions(acc):
    """Get list of unmatched txns for review."""
    org_id = acc["org_id"]
    db = SessionLocal()
    try:
        # Create some unmatched txns
        for i in range(3):
            txn = BankTransaction(
                organization_id=org_id,
                external_id=f"OF-UNMATCHED-{i}",
                source="open_finance",
                transaction_date=date(2026, 6, 10 + i),
                description=f"unmatched txn {i}",
                amount=100 + i*10,
                currency="ILS",
                is_reconciled=False,
            )
            db.add(txn)
        db.commit()

        service = ManualReconciliationService(db, organization_id=org_id)
        unmatched = service.list_unmatched_transactions(limit=10)

        assert len(unmatched) >= 3
        assert all(u["amount"] > 0 for u in unmatched)
    finally:
        db.close()


def test_manual_match_invalid_entity_type(acc):
    """Error when using invalid entity type."""
    org_id = acc["org_id"]
    db = SessionLocal()
    try:
        txn = BankTransaction(
            organization_id=org_id,
            external_id="OF-ERR",
            source="open_finance",
            transaction_date=date(2026, 6, 5),
            description="test",
            amount=100,
            currency="ILS",
        )
        db.add(txn)
        db.commit()

        service = ManualReconciliationService(db, organization_id=org_id)
        with pytest.raises(ValueError, match="Invalid entity_type"):
            service.match_transaction(txn.id, "invalid_type", 999)
    finally:
        db.close()


def test_manual_match_not_found(acc):
    """Error when txn/entity not found."""
    org_id = acc["org_id"]
    db = SessionLocal()
    try:
        service = ManualReconciliationService(db, organization_id=org_id)
        with pytest.raises(ValueError, match="not found"):
            service.match_transaction(99999, "invoice", 99999)
    finally:
        db.close()


def test_manual_match_via_api(client, acc):
    """Test manual match endpoint."""
    org_id = acc["org_id"]
    db = SessionLocal()
    try:
        inv = Invoice(
            organization_id=org_id,
            external_id="API-INV",
            source="sumit",
            issue_date=date(2026, 6, 4),
            status=InvoiceStatus.SENT,
            total=750,
            balance=750,
        )
        txn = BankTransaction(
            organization_id=org_id,
            external_id="API-TXN",
            source="open_finance",
            transaction_date=date(2026, 6, 5),
            description="test",
            amount=750,
            currency="ILS",
        )
        db.add_all([inv, txn])
        db.commit()

        # Match via API
        r = client.post("/api/reconcile-manual/match", json={
            "bank_txn_id": txn.id,
            "entity_type": "invoice",
            "entity_id": inv.id,
        }, headers=acc["headers"])

        assert r.status_code == 200, r.text
        data = r.json()["data"]
        assert data["status"] == "matched"
        assert data["matched_entity_type"] == "invoice"
    finally:
        db.close()


def test_feedback_via_api(client, acc):
    """Test classifier feedback endpoint."""
    org_id = acc["org_id"]
    db = SessionLocal()
    try:
        exp = Expense(
            organization_id=org_id,
            supplier_name="תחנת דלק",
            amount=100,
            vat_amount=18,
            total=118,
            expense_date=date(2026, 6, 1),
            category="other",
        )
        db.add(exp)
        db.commit()

        r = client.post("/api/reconcile-manual/feedback", json={
            "expense_id": exp.id,
            "corrected_category": "travel",
            "feedback_text": "This is fuel, should be travel",
        }, headers=acc["headers"])

        assert r.status_code == 200, r.text
        data = r.json()["data"]
        assert data["new_category"] == "travel"
        assert data["status"] == "feedback_recorded"
    finally:
        db.close()
