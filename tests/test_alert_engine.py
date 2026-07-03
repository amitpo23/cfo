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


def test_one_check_failing_does_not_abort_the_others(fresh_org, monkeypatch):
    """A single check raising must not crash evaluate_all() nor block the other
    checks — it must be caught, logged, and counted, while other checks still run.

    Current (RED): no try/except anywhere in evaluate_all(); one check's
    exception propagates and aborts the whole run, silently dropping every
    other check's alerts too.
    """
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        today = date.today()
        db.add(Invoice(
            organization_id=org_id,
            invoice_number="INV-OD2",
            due_date=today - timedelta(days=45),
            status=InvoiceStatus.SENT,
            balance=Decimal("1000"),
            total=Decimal("1000"),
        ))
        db.commit()

        engine = AlertEngine(db, org_id)
        monkeypatch.setattr(
            engine, "_check_bills_due_soon",
            lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("simulated failure")),
        )

        alerts = engine.evaluate_all()

        # The overdue-invoice check still ran and produced its alert.
        alert_types = [a.alert_type for a in alerts]
        assert "overdue_invoice" in alert_types

        # The failure was caught, logged, and counted — not silently swallowed.
        assert len(engine.last_run_failures) == 1
        assert engine.last_run_failures[0]["check"] == "_check_bills_due_soon"
        assert "simulated failure" in engine.last_run_failures[0]["error"]
    finally:
        db.close()
