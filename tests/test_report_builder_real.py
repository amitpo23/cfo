"""פאזה 2 — ReportBuilder מנתב לשירותים האמיתיים (לא random/קשיח)."""
from datetime import date

import pytest

from cfo.services.report_builder_service import ReportBuilderService


@pytest.fixture
def org_pl(fresh_org):
    from cfo.database import SessionLocal
    from cfo.models import Contact, ContactType, Invoice, InvoiceStatus

    org = fresh_org()
    org_id = org["org_id"]
    db = SessionLocal()
    try:
        cust = Contact(organization_id=org_id, contact_type=ContactType.CUSTOMER, name="לקוח")
        db.add(cust); db.flush()
        db.add(Invoice(organization_id=org_id, contact_id=cust.id, invoice_number="RB-1",
                       issue_date=date(2026, 3, 15), due_date=date(2026, 3, 15),
                       subtotal=1000, tax=180, total=1180, paid_amount=0, balance=1180,
                       status=InvoiceStatus.SENT))
        db.commit()
        return {"org_id": org_id}
    finally:
        db.close()


def test_report_builder_pl_reflects_real_ledger(org_pl):
    from cfo.database import SessionLocal
    db = SessionLocal()
    try:
        svc = ReportBuilderService(db, organization_id=org_pl["org_id"])
        rows = svc._generate_pl_data({"year": 2026, "month": 3})
        amounts = [r["amount"] for r in rows]
        # הכנסה אמיתית 1000 (נטו) מופיעה; הקשיח 500000 לא.
        assert any(abs(a - 1000) < 0.01 for a in amounts)
        assert not any(abs(a - 500000) < 0.01 for a in amounts)
    finally:
        db.close()
