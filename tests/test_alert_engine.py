"""
Behavior tests for AlertEngine.
Covers the _check_overdue_invoices built-in rule.
"""
from datetime import date, timedelta
from decimal import Decimal

from cfo.database import SessionLocal
from cfo.models import Invoice, InvoiceStatus
from cfo.services.alert_engine import AlertEngine


def test_overdue_invoice_creates_alert(fresh_org):
    """AlertEngine.evaluate_all() raises an overdue_invoice alert for a 45-day overdue invoice."""
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        today = date.today()
        db.add(Invoice(
            organization_id=org_id,
            invoice_number="INV-OD",
            due_date=today - timedelta(days=45),
            status=InvoiceStatus.SENT,
            balance=Decimal("1000"),
            total=Decimal("1000"),
        ))
        db.commit()

        alerts = AlertEngine(db, org_id).evaluate_all()

        assert len(alerts) > 0, "Expected at least one alert for the overdue invoice"
        alert_types = [a.alert_type for a in alerts]
        assert "overdue_invoice" in alert_types, (
            f"Expected 'overdue_invoice' in alert types, got: {alert_types}"
        )
    finally:
        db.close()


def test_no_data_does_not_raise(fresh_org):
    """AlertEngine.evaluate_all() on an org with no data returns a list without raising."""
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        result = AlertEngine(db, org_id).evaluate_all()
        assert isinstance(result, list), "Expected evaluate_all() to return a list"
    finally:
        db.close()
