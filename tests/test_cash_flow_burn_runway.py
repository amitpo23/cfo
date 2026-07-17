"""Regression: cash burn runway must never be negative / absurd.

Bug: CashFlowService.get_cash_burn_rate sourced current_balance from
_get_current_balance, which sums the entire (frozen) Transaction history and can
land deeply negative — producing runway_months in the thousands-negative range.
current_balance should come from real Account balances (bank/asset), like
DashboardService._get_cash_balance does. And when net_burn<=0 or
current_balance<=0, runway must be a sane finite sentinel (999.0), never negative.
"""
from datetime import datetime, timedelta
from decimal import Decimal

from cfo.database import SessionLocal
from cfo.models import Account, AccountType, Transaction, TransactionType
from cfo.services.cash_flow_service import CashFlowService


def test_runway_uses_account_balance_and_is_never_negative(fresh_org):
    org = fresh_org()
    org_id = org["org_id"]
    db = SessionLocal()
    try:
        # A real bank account with a healthy positive balance.
        acct = Account(
            organization_id=org_id,
            name="Bank Main",
            account_type=AccountType.BANK,
            balance=Decimal("50000.00"),
        )
        db.add(acct)
        db.flush()

        # Historical Transaction rows that would sum to a huge NEGATIVE balance if
        # used directly (this is exactly the pre-fix bug) — expenses far exceed
        # income over old history, unrelated to the real account balance above.
        old_date = datetime.now() - timedelta(days=900)
        db.add(Transaction(
            organization_id=org_id,
            account_id=acct.id,
            transaction_type=TransactionType.EXPENSE,
            amount=Decimal("500000.00"),
            transaction_date=old_date,
            description="huge old expense",
        ))
        db.add(Transaction(
            organization_id=org_id,
            account_id=acct.id,
            transaction_type=TransactionType.INCOME,
            amount=Decimal("10.00"),
            transaction_date=old_date,
            description="tiny old income",
        ))

        # Small recent burn so net_burn is tiny and positive.
        recent_date = datetime.now() - timedelta(days=5)
        db.add(Transaction(
            organization_id=org_id,
            account_id=acct.id,
            transaction_type=TransactionType.EXPENSE,
            amount=Decimal("100.00"),
            transaction_date=recent_date,
            description="small recent expense",
        ))
        db.commit()

        svc = CashFlowService(db)
        result = svc.get_cash_burn_rate(org_id, months=3)

        assert result["current_balance"] == 50000.0
        assert result["runway_months"] >= 0
        # Tiny burn against a real 50k balance should yield a large (or 999 sentinel)
        # runway — never the absurd negative value the frozen-Transaction bug produced.
        assert result["runway_months"] > 0
    finally:
        db.close()


def test_runway_sentinel_when_no_burn(fresh_org):
    org = fresh_org()
    org_id = org["org_id"]
    db = SessionLocal()
    try:
        acct = Account(
            organization_id=org_id,
            name="Bank Main",
            account_type=AccountType.BANK,
            balance=Decimal("10000.00"),
        )
        db.add(acct)
        db.commit()

        svc = CashFlowService(db)
        result = svc.get_cash_burn_rate(org_id, months=3)

        # No expense/income transactions at all -> net_burn == 0 -> sentinel, not negative.
        assert result["runway_months"] == 999.0
    finally:
        db.close()


def test_runway_sentinel_when_balance_non_positive(fresh_org):
    org = fresh_org()
    org_id = org["org_id"]
    db = SessionLocal()
    try:
        # An account exists (Transaction.account_id is NOT NULL) but it is NOT a
        # bank/asset account, so the Account-balance sum matches no rows -> None ->
        # falls back to the Transaction-derived balance, which nets deeply negative
        # here; runway must still not be reported as a negative number.
        expense_acct = Account(
            organization_id=org_id,
            name="Expense Ledger",
            account_type=AccountType.EXPENSE,
            balance=Decimal("0.00"),
        )
        db.add(expense_acct)
        db.flush()

        old_date = datetime.now() - timedelta(days=900)
        db.add(Transaction(
            organization_id=org_id,
            account_id=expense_acct.id,
            transaction_type=TransactionType.EXPENSE,
            amount=Decimal("500000.00"),
            transaction_date=old_date,
            description="huge old expense",
        ))
        recent_date = datetime.now() - timedelta(days=5)
        db.add(Transaction(
            organization_id=org_id,
            account_id=expense_acct.id,
            transaction_type=TransactionType.EXPENSE,
            amount=Decimal("100.00"),
            transaction_date=recent_date,
            description="small recent expense",
        ))
        db.commit()

        svc = CashFlowService(db)
        result = svc.get_cash_burn_rate(org_id, months=3)

        assert result["current_balance"] < 0  # confirms the fallback path is exercised
        assert result["runway_months"] == 999.0
    finally:
        db.close()
