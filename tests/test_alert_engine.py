"""
Behavior tests for AlertEngine.

Covers all 6 built-in/configurable checks. Before this, only
_check_overdue_invoices had direct coverage -- the other 5 (bills_due_soon,
large_transactions, stale_collection_cases, low_cash, spend_spike) ran in
production on every sync/cron with zero test evidence they actually fire.
"""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from cfo.database import SessionLocal
from cfo.models import (
    Account, AccountType, AlertRule, Bill, BillStatus, CollectionCase,
    Invoice, InvoiceStatus, Transaction, TransactionType,
)
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


def test_bill_due_soon_creates_alert(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        today = date.today()
        db.add(Bill(
            organization_id=org_id,
            bill_number="BILL-1",
            due_date=today + timedelta(days=3),
            status=BillStatus.APPROVED,
            balance=Decimal("2500"),
            total=Decimal("2500"),
        ))
        db.commit()

        alerts = AlertEngine(db, org_id).evaluate_all()

        alert_types = [a.alert_type for a in alerts]
        assert "bill_due_soon" in alert_types, alert_types
    finally:
        db.close()


def test_bill_not_due_soon_does_not_alert(fresh_org):
    """A bill due in 30 days is outside the default 7-day window — no alert."""
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        today = date.today()
        db.add(Bill(
            organization_id=org_id,
            bill_number="BILL-FAR",
            due_date=today + timedelta(days=30),
            status=BillStatus.APPROVED,
            balance=Decimal("2500"),
            total=Decimal("2500"),
        ))
        db.commit()

        alerts = AlertEngine(db, org_id).evaluate_all()

        assert "bill_due_soon" not in [a.alert_type for a in alerts]
    finally:
        db.close()


def test_large_transaction_creates_alert(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        acct = Account(organization_id=org_id, name="בנק", account_type=AccountType.BANK, balance=0)
        db.add(acct)
        db.flush()
        db.add(Transaction(
            organization_id=org_id, account_id=acct.id,
            transaction_type=TransactionType.EXPENSE, amount=Decimal("15000"),
            description="ציוד יקר", transaction_date=datetime.now(timezone.utc),
        ))
        db.commit()

        alerts = AlertEngine(db, org_id).evaluate_all()

        assert "large_transaction" in [a.alert_type for a in alerts]
    finally:
        db.close()


def test_transaction_below_threshold_does_not_alert(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        acct = Account(organization_id=org_id, name="בנק", account_type=AccountType.BANK, balance=0)
        db.add(acct)
        db.flush()
        db.add(Transaction(
            organization_id=org_id, account_id=acct.id,
            transaction_type=TransactionType.EXPENSE, amount=Decimal("500"),
            description="קפה", transaction_date=datetime.now(timezone.utc),
        ))
        db.commit()

        alerts = AlertEngine(db, org_id).evaluate_all()

        assert "large_transaction" not in [a.alert_type for a in alerts]
    finally:
        db.close()


def test_broken_collection_promise_creates_alert(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        today = date.today()
        db.add(CollectionCase(
            organization_id=org_id, status="promised",
            promise_date=today - timedelta(days=2), attempts=[],
        ))
        db.commit()

        alerts = AlertEngine(db, org_id).evaluate_all()

        assert "stale_collection_case" in [a.alert_type for a in alerts]
    finally:
        db.close()


def test_collection_case_no_recent_activity_creates_alert(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        stale_created_at = datetime.now(timezone.utc) - timedelta(days=10)
        case = CollectionCase(organization_id=org_id, status="open", attempts=[])
        db.add(case)
        db.flush()
        db.query(CollectionCase).filter(CollectionCase.id == case.id).update(
            {"created_at": stale_created_at}
        )
        db.commit()

        alerts = AlertEngine(db, org_id).evaluate_all()

        assert "stale_collection_case" in [a.alert_type for a in alerts]
    finally:
        db.close()


def test_collection_case_with_recent_attempt_does_not_alert(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        recent = datetime.now(timezone.utc).isoformat()
        db.add(CollectionCase(
            organization_id=org_id, status="open",
            attempts=[{"date": recent, "channel": "phone", "outcome": "no_answer"}],
        ))
        db.commit()

        alerts = AlertEngine(db, org_id).evaluate_all()

        assert "stale_collection_case" not in [a.alert_type for a in alerts]
    finally:
        db.close()


def test_low_cash_creates_alert(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        db.add(Account(
            organization_id=org_id, name="בנק", account_type=AccountType.BANK,
            balance=Decimal("1000"),
        ))
        db.add(AlertRule(
            organization_id=org_id, rule_type="low_cash_threshold", is_active=True,
            config={"threshold": 50000},
        ))
        db.commit()

        alerts = AlertEngine(db, org_id).evaluate_all()

        assert "low_cash" in [a.alert_type for a in alerts]
    finally:
        db.close()


def test_healthy_cash_does_not_alert(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        db.add(Account(
            organization_id=org_id, name="בנק", account_type=AccountType.BANK,
            balance=Decimal("100000"),
        ))
        db.add(AlertRule(
            organization_id=org_id, rule_type="low_cash_threshold", is_active=True,
            config={"threshold": 50000},
        ))
        db.commit()

        alerts = AlertEngine(db, org_id).evaluate_all()

        assert "low_cash" not in [a.alert_type for a in alerts]
    finally:
        db.close()


def _months_before(d: date, n: int) -> date:
    """First-of-month, n calendar months before d's month — avoids the
    day-count drift of `d - timedelta(days=30*n)`, which can land on the
    wrong side of a month/90-day boundary depending on today's day-of-month."""
    month = d.month - n
    year = d.year
    while month <= 0:
        month += 12
        year -= 1
    return date(year, month, 1)


def test_spend_spike_creates_alert(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        acct = Account(organization_id=org_id, name="בנק", account_type=AccountType.BANK, balance=0)
        db.add(acct)
        db.flush()

        month_start = date.today().replace(day=1)
        # 1 month back, safely inside the 90-day window regardless of today's
        # day-of-month (unlike splitting across 2 months, which can land right
        # on the 90-day boundary depending on how late in the month "today" is).
        # amount=3000 -> past_total=3000 -> avg_monthly=1000 (divisor is always
        # 3 in the function, regardless of how many transactions exist).
        db.add(Transaction(
            organization_id=org_id, account_id=acct.id,
            transaction_type=TransactionType.EXPENSE, amount=Decimal("3000"),
            description="הוצאה רגילה",
            transaction_date=datetime.combine(_months_before(month_start, 1), datetime.min.time()),
        ))
        # Current month: a spike well above threshold_pct (30%) over the ~1000/month average
        db.add(Transaction(
            organization_id=org_id, account_id=acct.id,
            transaction_type=TransactionType.EXPENSE, amount=Decimal("5000"),
            description="הוצאה חריגה", transaction_date=datetime.combine(month_start, datetime.min.time()),
        ))
        db.add(AlertRule(
            organization_id=org_id, rule_type="spend_spike", is_active=True,
            config={"threshold_pct": 30},
        ))
        db.commit()

        alerts = AlertEngine(db, org_id).evaluate_all()

        assert "spend_spike" in [a.alert_type for a in alerts]
    finally:
        db.close()


def test_normal_spending_does_not_alert(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        acct = Account(organization_id=org_id, name="בנק", account_type=AccountType.BANK, balance=0)
        db.add(acct)
        db.flush()

        month_start = date.today().replace(day=1)
        db.add(Transaction(
            organization_id=org_id, account_id=acct.id,
            transaction_type=TransactionType.EXPENSE, amount=Decimal("3000"),
            description="הוצאה רגילה",
            transaction_date=datetime.combine(_months_before(month_start, 1), datetime.min.time()),
        ))
        db.add(Transaction(
            organization_id=org_id, account_id=acct.id,
            transaction_type=TransactionType.EXPENSE, amount=Decimal("1050"),
            description="הוצאה רגילה", transaction_date=datetime.combine(month_start, datetime.min.time()),
        ))
        db.add(AlertRule(
            organization_id=org_id, rule_type="spend_spike", is_active=True,
            config={"threshold_pct": 30},
        ))
        db.commit()

        alerts = AlertEngine(db, org_id).evaluate_all()

        assert "spend_spike" not in [a.alert_type for a in alerts]
    finally:
        db.close()
