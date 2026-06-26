"""Tests for Phase 9 advanced features."""
from datetime import date
from decimal import Decimal

import pytest

from cfo.database import SessionLocal
from cfo.models import Invoice, InvoiceStatus, Bill, BillStatus, Contact, Expense
from cfo.services.self_invoice_service import SelfInvoiceService
from cfo.services.check_reconciliation import CheckReconciliationService
from cfo.services.ar_ap_aging import ARAPAgingService
from cfo.services.classifier_ml_training import ClassifierMLTrainingService


@pytest.fixture(scope="module")
def acc(client):
    reg = client.post("/api/admin/auth/register", json={
        "email": "phase9@example.com", "password": "secret123", "full_name": "Phase 9 Tester",
    })
    assert reg.status_code == 201, reg.text
    return {"headers": {"Authorization": f"Bearer {reg.json()['access_token']}"},
            "org_id": reg.json()["user"]["organization_id"]}


# ==================== SELF-INVOICES ====================

def test_create_owner_drawing(acc):
    """Create owner drawing (משיכה בעלים)."""
    org_id = acc["org_id"]
    db = SessionLocal()
    try:
        service = SelfInvoiceService(db, org_id)
        result = service.create_owner_drawing(
            Decimal("5000"),
            description="Weekly owner withdrawal",
            check_number="CHK-1001",
        )

        assert result["type"] == "owner_drawing"
        assert result["amount"] == 5000.0
        assert result["status"] == "created"
        assert result["id"] is not None
    finally:
        db.close()


def test_create_internal_transfer(acc):
    """Create internal transfer between accounts."""
    org_id = acc["org_id"]
    db = SessionLocal()
    try:
        service = SelfInvoiceService(db, org_id)
        result = service.create_internal_transfer(
            Decimal("10000"),
            from_account="Operating",
            to_account="Savings",
        )

        assert result["type"] == "internal_transfer"
        assert result["total"] == 10000.0
    finally:
        db.close()


def test_list_and_summary_self_invoices(acc):
    """List and summarize self-invoices."""
    org_id = acc["org_id"]
    db = SessionLocal()
    try:
        service = SelfInvoiceService(db, org_id)

        # Create a few
        service.create_owner_drawing(Decimal("1000"))
        service.create_reimbursement(Decimal("500"), "John Doe", "Travel")
        service.create_loan_repayment(Decimal("2000"), "Bank", "Loan repayment")

        # List all
        all_invoices = service.list_self_invoices()
        assert len(all_invoices) >= 3

        # Summary
        summary = service.get_self_invoice_summary()
        assert summary["owner_drawing"]["count"] >= 1
        assert summary["reimbursement"]["count"] >= 1
        assert summary["loan_repay"]["count"] >= 1
    finally:
        db.close()


# ==================== CHECK RECONCILIATION ====================

def test_record_check_deposit(acc):
    """Record a deposited check."""
    org_id = acc["org_id"]
    db = SessionLocal()
    try:
        service = CheckReconciliationService(db, org_id)
        result = service.record_check_deposit(
            check_number="CHK-5001",
            amount=2500.0,
            payer_name="Client Corp Ltd",
            deposit_date=date(2026, 6, 20),
        )

        assert result["check_number"] == "CHK-5001"
        assert result["amount"] == 2500.0
        assert result["status"] == "deposited"
        assert result["deposit_date"] == "2026-06-20"
    finally:
        db.close()


def test_list_pending_checks(acc):
    """List pending (uncleared) checks."""
    org_id = acc["org_id"]
    db = SessionLocal()
    try:
        service = CheckReconciliationService(db, org_id)

        # Create a few
        service.record_check_deposit("CHK-1", 100.0, "Payer A", date(2026, 6, 15))
        service.record_check_deposit("CHK-2", 200.0, "Payer B", date(2026, 6, 18))

        pending = service.list_pending_checks()
        assert len(pending) >= 2
        assert all(p["status"] == "deposited" for p in pending)
    finally:
        db.close()


def test_check_aging_report(acc):
    """Check aging by days pending."""
    org_id = acc["org_id"]
    db = SessionLocal()
    try:
        service = CheckReconciliationService(db, org_id)

        # Old check (30+ days)
        service.record_check_deposit("OLD-CHECK", 500.0, "Old Payer", date(2026, 5, 1))
        # Recent check (5 days)
        service.record_check_deposit("NEW-CHECK", 300.0, "New Payer", date(2026, 6, 20))

        aging = service.get_check_aging()
        assert aging["0_7_days"]["count"] >= 1
        assert aging["30plus_days"]["count"] >= 1
    finally:
        db.close()


# ==================== AR/AP AGING ====================

def test_ar_aging_report(acc):
    """Accounts Receivable aging."""
    org_id = acc["org_id"]
    db = SessionLocal()
    try:
        service = ARAPAgingService(db, org_id)
        report = service.ar_aging_report()

        # Just verify structure
        assert "total_receivable" in report
        assert "aging" in report
        assert report["aging"]["current"]["count"] >= 0
    finally:
        db.close()


def test_ap_aging_report(acc):
    """Accounts Payable aging."""
    org_id = acc["org_id"]
    db = SessionLocal()
    try:
        # Just test the service, no need to create bills
        service = ARAPAgingService(db, org_id)
        report = service.ap_aging_report()

        assert "total_payable" in report
        assert "aging" in report
    finally:
        db.close()


def test_ar_ap_summary(acc):
    """Combined AR/AP summary."""
    org_id = acc["org_id"]
    db = SessionLocal()
    try:
        service = ARAPAgingService(db, org_id)
        summary = service.ar_ap_summary()

        assert "accounts_receivable" in summary
        assert "accounts_payable" in summary
        assert "net_working_capital" in summary
    finally:
        db.close()


# ==================== ML CLASSIFIER TRAINING ====================

def test_analyze_feedback_patterns(acc):
    """Analyze classifier feedback to identify patterns."""
    org_id = acc["org_id"]
    db = SessionLocal()
    try:
        # Create expenses with feedback
        for i in range(3):
            exp = Expense(
                organization_id=org_id,
                supplier_name="עו\"ד כהן",
                amount=Decimal("100"),
                total=Decimal("100"),
                expense_date=date.today(),
                category="office",
                classifier_feedback=[
                    {
                        "timestamp": "2026-06-24T10:00:00",
                        "old_category": "office",
                        "new_category": "professional",
                        "supplier": "עו\"ד כהן",
                        "feedback_text": "Legal services, not office",
                    }
                ],
            )
            db.add(exp)
        db.commit()

        service = ClassifierMLTrainingService(db, org_id)
        analysis = service.analyze_feedback()

        assert analysis["total_feedback_records"] >= 3
        assert "patterns" in analysis
    finally:
        db.close()


def test_retraining_recommendation(acc):
    """Get recommendation on when to retrain."""
    org_id = acc["org_id"]
    db = SessionLocal()
    try:
        service = ClassifierMLTrainingService(db, org_id)
        rec = service.recommend_classifier_update()

        assert "total_expenses" in rec
        assert "should_retrain" in rec
        assert "reason" in rec
    finally:
        db.close()


def test_export_training_data(acc):
    """Export feedback as training data."""
    org_id = acc["org_id"]
    db = SessionLocal()
    try:
        exp = Expense(
            organization_id=org_id,
            supplier_name="Test Supplier",
            amount=Decimal("100"),
            total=Decimal("100"),
            expense_date=date.today(),
            category="other",
            classifier_feedback=[
                {
                    "timestamp": "2026-06-24T10:00:00",
                    "old_category": "other",
                    "new_category": "travel",
                    "supplier": "Test Supplier",
                    "feedback_text": "Actually travel",
                }
            ],
        )
        db.add(exp)
        db.commit()

        service = ClassifierMLTrainingService(db, org_id)
        data = service.export_training_data()

        assert data["metadata"]["total_samples"] >= 1
        assert len(data["samples"]) >= 1
    finally:
        db.close()


# ==================== API ENDPOINTS ====================

def test_self_invoice_api(client, acc):
    """Test self-invoice creation via API."""
    r = client.post("/api/advanced/self-invoices", json={
        "invoice_type": "owner_drawing",
        "amount": 2000.0,
        "description": "Owner withdrawal",
        "vat_amount": 0,
    }, headers=acc["headers"])

    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["type"] == "owner_drawing"
    assert data["amount"] == 2000.0


def test_ar_ap_api(client, acc):
    """Test AR/AP reports via API."""
    r = client.get("/api/advanced/ar-ap-summary", headers=acc["headers"])
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert "accounts_receivable" in data
    assert "accounts_payable" in data


def test_classifier_feedback_api(client, acc):
    """Test classifier feedback analysis via API."""
    r = client.get("/api/advanced/classifier/feedback-analysis", headers=acc["headers"])
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert "total_feedback_records" in data
