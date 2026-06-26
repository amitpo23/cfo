"""T1.1 — CashFlowService aging delegates to ARAPAgingService (real data, no zeros)."""
from datetime import date, timedelta

import pytest

from cfo.database import SessionLocal
from cfo.models import Contact, ContactType, Invoice, InvoiceStatus, Bill, BillStatus
from cfo.services.cash_flow_service import CashFlowService


@pytest.fixture
def aging_org(fresh_org):
    """Seed one overdue invoice (40 days) and one overdue bill (45 days)."""
    org = fresh_org()
    org_id = org["org_id"]
    today = date.today()
    db = SessionLocal()
    try:
        # AR: a customer with an outstanding invoice due 40 days ago → 31-60 bucket
        customer = Contact(
            organization_id=org_id,
            contact_type=ContactType.CUSTOMER,
            name="Test Customer",
        )
        db.add(customer)
        db.flush()

        invoice = Invoice(
            organization_id=org_id,
            contact_id=customer.id,
            invoice_number="TEST-AR-001",
            issue_date=today - timedelta(days=50),
            due_date=today - timedelta(days=40),
            status=InvoiceStatus.SENT,
            subtotal=1000.0,
            tax=0.0,
            total=1000.0,
            balance=1000.0,
        )
        db.add(invoice)

        # AP: a vendor with an outstanding bill due 45 days ago → 31-60 bucket
        vendor = Contact(
            organization_id=org_id,
            contact_type=ContactType.VENDOR,
            name="Test Vendor",
        )
        db.add(vendor)
        db.flush()

        bill = Bill(
            organization_id=org_id,
            vendor_id=vendor.id,
            due_date=today - timedelta(days=45),
            status=BillStatus.RECEIVED,
            total=500.0,
            balance=500.0,
        )
        db.add(bill)
        db.commit()

        return {"org_id": org_id}
    finally:
        db.close()


def test_receivables_aging_real_not_zeros(aging_org):
    """days_30_60 must reflect the seeded invoice, not hardcoded zeros."""
    org_id = aging_org["org_id"]
    db = SessionLocal()
    try:
        result = CashFlowService(db).get_receivables_aging(org_id)

        # The invoice is 40 days overdue → falls in days_30_60 bucket
        assert result["days_30_60"]["amount"] == 1000.0, (
            f"Expected 1000.0, got {result['days_30_60']['amount']}"
        )
        assert result["days_30_60"]["count"] == 1
        assert result["total"]["amount"] == 1000.0, (
            f"Expected total 1000.0, got {result['total']['amount']}"
        )
        assert result["total"]["count"] == 1

        # Other buckets should be empty
        assert result["current"]["amount"] == 0.0
        assert result["days_60_90"]["amount"] == 0.0
        assert result["over_90"]["amount"] == 0.0

        # Labels must be preserved
        assert result["current"]["label"] == "0-30 ימים"
        assert result["days_30_60"]["label"] == "31-60 ימים"
        assert result["days_60_90"]["label"] == "61-90 ימים"
        assert result["over_90"]["label"] == "מעל 90 ימים"
    finally:
        db.close()


def test_payables_aging_real_not_zeros(aging_org):
    """days_30_60 must reflect the seeded bill, not hardcoded zeros."""
    org_id = aging_org["org_id"]
    db = SessionLocal()
    try:
        result = CashFlowService(db).get_payables_aging(org_id)

        # The bill is 45 days overdue → falls in days_30_60 bucket
        assert result["days_30_60"]["amount"] == 500.0, (
            f"Expected 500.0, got {result['days_30_60']['amount']}"
        )
        assert result["days_30_60"]["count"] == 1
        assert result["total"]["amount"] == 500.0, (
            f"Expected total 500.0, got {result['total']['amount']}"
        )
        assert result["total"]["count"] == 1

        # Other buckets should be empty
        assert result["current"]["amount"] == 0.0
        assert result["days_60_90"]["amount"] == 0.0
        assert result["over_90"]["amount"] == 0.0

        # Labels must be preserved
        assert result["current"]["label"] == "0-30 ימים"
        assert result["days_30_60"]["label"] == "31-60 ימים"
        assert result["days_60_90"]["label"] == "61-90 ימים"
        assert result["over_90"]["label"] == "מעל 90 ימים"
    finally:
        db.close()
