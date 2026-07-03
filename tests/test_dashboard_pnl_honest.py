"""TDD test for P&L COGS honesty: drop fabricated 30% estimate, use None + flag."""
from datetime import date, datetime
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


def test_pnl_cogs_real_when_classified_transactions_exist(client, fresh_org):
    """P&L must compute real COGS from Transactions classified into direct-cost
    categories (same DIRECT_CATEGORIES as cost_analysis_service — no duplication).

    Given: one PAID invoice (revenue=10000), one expense Transaction categorized
    "materials" (2000), one expense Transaction categorized "rent" (500, indirect).
    Expected: cogs=2000 (materials only, not rent), cogs_available=True,
    gross_profit=revenue-cogs=8000.
    """
    from cfo.database import SessionLocal
    from cfo.models import Account, AccountType, Invoice, InvoiceStatus, Transaction, TransactionType
    from cfo.services.dashboard_service import DashboardService

    org = fresh_org()
    org_id = org["org_id"]

    db = SessionLocal()
    try:
        today = date.today()
        acct = Account(organization_id=org_id, name="בנק", account_type=AccountType.BANK, balance=0)
        db.add(acct)
        db.flush()
        db.add(Invoice(
            organization_id=org_id,
            issue_date=today,
            status=InvoiceStatus.PAID,
            paid_amount=Decimal("10000"),
            total=Decimal("10000"),
        ))
        db.add(Transaction(
            organization_id=org_id,
            account_id=acct.id,
            transaction_date=datetime.combine(today, datetime.min.time()),
            transaction_type=TransactionType.EXPENSE,
            amount=Decimal("2000"),
            category="materials",
            description="raw materials purchase",
        ))
        db.add(Transaction(
            organization_id=org_id,
            account_id=acct.id,
            transaction_date=datetime.combine(today, datetime.min.time()),
            transaction_type=TransactionType.EXPENSE,
            amount=Decimal("500"),
            category="rent",
            description="office rent",
        ))
        db.commit()

        service = DashboardService(db, org_id)
        pnl = service.get_pnl(months=1)

        assert len(pnl) == 1
        entry = pnl[0]

        assert entry["cogs"] == 2000.0, f"Expected cogs=2000.0 (materials only), got {entry['cogs']}"
        assert entry["cogs_available"] is True
        assert entry["gross_profit"] == 8000.0, f"Expected gross_profit=8000.0, got {entry['gross_profit']}"
    finally:
        db.close()
