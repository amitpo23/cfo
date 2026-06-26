"""TDD test for P&L COGS honesty: drop fabricated 30% estimate, use None + flag."""
from datetime import date
from decimal import Decimal
import pytest


def test_pnl_cogs_honest_null_when_unavailable(client, fresh_org):
    """P&L must return honest None for COGS/gross_profit when we can't separate costs.

    Given: one PAID invoice (revenue=10000), one PAID bill (expenses=4000).
    Expected: net_profit=6000, but cogs/gross_profit=None, cogs_available=False.
    Current (RED): cogs=1200 (fabricated 30% of expenses).
    """
    from cfo.database import SessionLocal
    from cfo.models import Invoice, InvoiceStatus, Bill, BillStatus
    from cfo.services.dashboard_service import DashboardService

    org = fresh_org()
    org_id = org["org_id"]

    db = SessionLocal()
    try:
        # Seed current month with one paid invoice and one paid bill
        today = date.today()
        db.add(Invoice(
            organization_id=org_id,
            issue_date=today,
            status=InvoiceStatus.PAID,
            paid_amount=Decimal("10000"),
            total=Decimal("10000"),
        ))
        db.add(Bill(
            organization_id=org_id,
            issue_date=today,
            status=BillStatus.PAID,
            paid_amount=Decimal("4000"),
            total=Decimal("4000"),
        ))
        db.commit()

        # Get P&L for current month
        service = DashboardService(db, org_id)
        pnl = service.get_pnl(months=1)

        assert len(pnl) == 1, f"Expected 1 month, got {len(pnl)}"
        entry = pnl[0]

        # Verify: honest null + flag for COGS
        assert entry["cogs"] is None, f"Expected cogs=None, got {entry['cogs']}"
        assert entry["cogs_available"] is False, f"Expected cogs_available=False"

        # Verify: gross_profit also None (derived from COGS)
        assert entry["gross_profit"] is None, f"Expected gross_profit=None, got {entry['gross_profit']}"

        # Verify: opex = all expenses (no COGS deduction)
        assert entry["opex"] == 4000.0, f"Expected opex=4000.0, got {entry['opex']}"

        # Verify: net_profit unchanged (revenue - expenses)
        assert entry["net_profit"] == 6000.0, f"Expected net_profit=6000.0, got {entry['net_profit']}"
    finally:
        db.close()
