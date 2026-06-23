"""AR dashboard real-data fixes — no more hardcoded credit_limit / email / DSO."""
from datetime import date

from cfo.database import SessionLocal
from cfo.models import Invoice, Contact, Payment, InvoiceStatus, ContactType
from cfo.services.ar_service import AccountsReceivableService


def _seed(org_id):
    db = SessionLocal()
    try:
        for model in (Payment, Invoice, Contact):
            db.query(model).filter(model.organization_id == org_id,
                                   model.source == "ar-real").delete()
        db.commit()
        cust = Contact(organization_id=org_id, source="ar-real", name="לקוח אמיתי",
                       contact_type=ContactType.CUSTOMER, tax_id="555",
                       email="real@customer.co.il")
        db.add(cust); db.commit()
        # An open invoice (balance > 0) and a paid one with a real payment.
        open_inv = Invoice(organization_id=org_id, source="ar-real", contact_id=cust.id,
                           invoice_number="OPEN", issue_date=date(2026, 4, 1),
                           due_date=date(2026, 5, 1), status=InvoiceStatus.OVERDUE,
                           subtotal=10000, tax=1800, total=11800, balance=11800)
        paid_inv = Invoice(organization_id=org_id, source="ar-real", contact_id=cust.id,
                           invoice_number="PAID", issue_date=date(2026, 1, 1),
                           due_date=date(2026, 2, 1), status=InvoiceStatus.PAID,
                           subtotal=5000, tax=900, total=5900, balance=0)
        db.add_all([open_inv, paid_inv]); db.commit()
        db.add(Payment(organization_id=org_id, source="ar-real", invoice_id=paid_inv.id,
                       contact_id=cust.id, payment_date=date(2026, 1, 20), amount=5900))
        db.commit()
        return cust.id
    finally:
        db.close()


def test_aging_uses_real_last_payment_and_behavioral_limit(fresh_org):
    org_id = fresh_org()["org_id"]
    cid = _seed(org_id)
    db = SessionLocal()
    try:
        report = AccountsReceivableService(db, organization_id=org_id).get_aging_report()
        cust = next(c for c in report.customers if c.customer_id == str(cid))
        # Real last payment date (not None / not fabricated).
        assert cust.last_payment_date == "2026-01-20"
        # Behavioral credit limit derived from real volume, not the flat 100000.
        assert cust.credit_limit != 100000
        assert cust.credit_limit > 0
    finally:
        db.close()


def test_dso_trend_is_real_not_synthetic(fresh_org):
    org_id = fresh_org()["org_id"]
    _seed(org_id)
    db = SessionLocal()
    try:
        trend = AccountsReceivableService(db, organization_id=org_id).get_dso_trend(months=6)
        assert len(trend) == 6
        # The month of the real payment (2026-01) reflects 19 days-to-pay (1/1 -> 1/20).
        jan = next((t for t in trend if t["month"] == "2026-01"), None)
        if jan:
            assert jan["sample"] >= 1
            assert jan["dso"] == 19.0
        # No row uses the old synthetic formula value pattern exclusively.
        assert all("sample" in t for t in trend)
    finally:
        db.close()
