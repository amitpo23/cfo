"""T1.4 — revenue_analytics honest values: real average_days_to_payment + no fabricated gross-profit."""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from cfo.database import SessionLocal
from cfo.models import Contact, ContactType, Invoice, InvoiceStatus, Payment
from cfo.services.revenue_analytics import RevenueAnalyticsService


def _seed_paid_invoice(org_id, issue_date: date, payment_date: date, amount: Decimal = Decimal("5000")):
    """Create a Contact + Invoice + Payment and return the org state."""
    db = SessionLocal()
    try:
        c = Contact(
            organization_id=org_id,
            name="לקוח בדיקה",
            contact_type=ContactType.CUSTOMER,
            source="honest-test",
        )
        db.add(c)
        db.flush()

        inv = Invoice(
            organization_id=org_id,
            contact_id=c.id,
            issue_date=issue_date,
            total=amount,
            paid_amount=amount,
            status=InvoiceStatus.PAID,
            created_at=datetime.now(timezone.utc),
            source="honest-test",
        )
        db.add(inv)
        db.flush()

        pmt = Payment(
            organization_id=org_id,
            invoice_id=inv.id,
            payment_date=payment_date,
            amount=amount,
            source="honest-test",
        )
        db.add(pmt)
        db.commit()
        return c.id
    finally:
        db.close()


# ── Test A1: real average_days_to_payment ────────────────────────────────────

def test_average_days_to_payment_real_value(fresh_org):
    """With a payment 10 days after issue_date, result should be 10.0 (not 30)."""
    org_id = fresh_org()["org_id"]
    today = date.today()
    issue = date(today.year, today.month, today.day)
    from datetime import timedelta
    issue = today - timedelta(days=10)
    _seed_paid_invoice(org_id, issue_date=issue, payment_date=today)

    db = SessionLocal()
    try:
        result = RevenueAnalyticsService(db, org_id).get_sales_pipeline_health()
    finally:
        db.close()

    assert result["average_days_to_payment"] == 10.0, (
        f"Expected 10.0 (real computation), got {result['average_days_to_payment']!r}"
    )


# ── Test A2: None when no payments ──────────────────────────────────────────

def test_average_days_to_payment_none_when_no_payments(fresh_org):
    """An org with no payments must return None, not the old fabricated 30."""
    org_id = fresh_org()["org_id"]

    db = SessionLocal()
    try:
        result = RevenueAnalyticsService(db, org_id).get_sales_pipeline_health()
    finally:
        db.close()

    assert result["average_days_to_payment"] is None, (
        f"Expected None for org with no payments, got {result['average_days_to_payment']!r}"
    )


# ── Test B: gross_profit_estimate is None, gross_profit_available is False ──

def test_gross_profit_estimate_is_null_not_fabricated(fresh_org):
    """Customer profitability rows must not carry a fabricated 70% margin estimate."""
    org_id = fresh_org()["org_id"]
    today = date.today()
    from datetime import timedelta
    _seed_paid_invoice(org_id, issue_date=today - timedelta(days=5), payment_date=today)

    db = SessionLocal()
    try:
        rows = RevenueAnalyticsService(db, org_id).get_customer_profitability(days=90)
    finally:
        db.close()

    assert len(rows) >= 1, "Expected at least one customer profitability row"
    for row in rows:
        assert row["gross_profit_estimate"] is None, (
            f"gross_profit_estimate should be None (no cost data), got {row['gross_profit_estimate']!r}"
        )
        assert row["gross_profit_available"] is False, (
            f"gross_profit_available should be False, got {row.get('gross_profit_available')!r}"
        )


# ── Test C: identify_investment_opportunities has no fabricated growth estimate ──

def test_investment_opportunities_have_no_fabricated_growth_fields(fresh_org):
    """A "growing_customer" opportunity previously carried growth_potential: "high"
    (a constant, for every row) and estimated_growth: revenue * 0.3 (a fabricated
    flat 30% multiplier, not derived from any real growth trend). Neither field
    should exist -- only fields backed by real, queried data."""
    org_id = fresh_org()["org_id"]
    today = date.today()

    customer = Contact(organization_id=org_id, name="לקוח צומח", contact_type=ContactType.CUSTOMER)
    db = SessionLocal()
    try:
        db.add(customer)
        db.flush()
        customer_id = customer.id
        for i in range(4):
            db.add(Invoice(
                organization_id=org_id, contact_id=customer_id,
                total=Decimal("1000"), paid_amount=Decimal("1000"),
                status=InvoiceStatus.PAID,
                created_at=datetime.now(timezone.utc),
                issue_date=today - timedelta(days=10 * i),
            ))
        # A second, much larger customer so the first stays under the 15% threshold.
        big_customer = Contact(organization_id=org_id, name="לקוח גדול", contact_type=ContactType.CUSTOMER)
        db.add(big_customer)
        db.flush()
        db.add(Invoice(
            organization_id=org_id, contact_id=big_customer.id,
            total=Decimal("50000"), paid_amount=Decimal("50000"),
            status=InvoiceStatus.PAID, created_at=datetime.now(timezone.utc),
            issue_date=today,
        ))
        db.commit()
    finally:
        db.close()

    db = SessionLocal()
    try:
        opportunities = RevenueAnalyticsService(db, org_id).identify_investment_opportunities(days=90)
    finally:
        db.close()

    growing = [o for o in opportunities if o["customer_id"] == customer_id]
    assert len(growing) == 1, f"Expected the 4-invoice customer to qualify, got {opportunities!r}"
    opp = growing[0]
    assert "estimated_growth" not in opp, "estimated_growth was a fabricated revenue*0.3 value"
    assert "growth_potential" not in opp, "growth_potential was a hardcoded constant, not a real signal"
    assert opp["current_revenue"] == 4000.0
    assert opp["invoice_count"] == 4
