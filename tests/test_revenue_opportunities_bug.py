"""
Test for the percentage_of_total KeyError bug in identify_investment_opportunities.

The bug: line 199 of revenue_analytics.py accesses cust["percentage_of_total"]
but analyze_revenue_by_customer() returns "percentage_of_total_revenue".

This test seeds ONE customer with FOUR invoices to trigger invoice_count >= 4,
which causes identify_investment_opportunities to raise KeyError on the wrong key.
"""
from datetime import datetime, timezone, timedelta
from decimal import Decimal

import pytest

from cfo.database import SessionLocal
from cfo.models import Contact, ContactType, Invoice, InvoiceStatus
from cfo.services.revenue_analytics import RevenueAnalyticsService


def test_identify_investment_opportunities_with_four_invoices(fresh_org):
    """
    Test that identify_investment_opportunities works when customer has >=4 invoices.

    This reproduces the KeyError: "percentage_of_total" bug and verifies the fix.

    RED (before fix): KeyError is raised.
    GREEN (after fix): returns a list (may be empty or contain opportunities).
    """
    org = fresh_org()
    org_id = org["org_id"]
    db = SessionLocal()

    try:
        # Create one customer
        customer = Contact(
            organization_id=org_id,
            name="Test Customer with 4 Invoices",
            contact_type=ContactType.CUSTOMER,
        )
        db.add(customer)
        db.flush()
        customer_id = customer.id

        # Create FOUR invoices for this customer, all within last 90 days
        now = datetime.now(timezone.utc)
        for i in range(4):
            invoice = Invoice(
                organization_id=org_id,
                contact_id=customer_id,
                total=Decimal("5000"),
                paid_amount=Decimal("5000"),
                status=InvoiceStatus.PAID,
                created_at=now - timedelta(days=10*i),  # spread over time
                issue_date=(now - timedelta(days=10*i)).date(),
            )
            db.add(invoice)

        db.commit()

        # Call the method that had the bug
        service = RevenueAnalyticsService(db, org_id)
        result = service.identify_investment_opportunities(days=90)

        # Verify it returns a list without raising KeyError
        assert isinstance(result, list), f"Expected list, got {type(result)}"

        # The customer might or might not be in opportunities depending on percentage_of_total_revenue
        # (it triggers when >= 4 invoices AND < 15% of total revenue)
        # Since we have 1 customer with 4 invoices, they are 100% of total revenue,
        # so they should NOT be in opportunities (condition < 15 fails).
        # But the important thing is NO KeyError is raised.

    finally:
        db.close()
