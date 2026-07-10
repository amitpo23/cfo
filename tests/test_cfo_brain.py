"""
Behavior / smoke tests for CFOBrainService.

We assert:
  1. run_analysis() returns a dict with the expected top-level keys.
  2. list_insights() returns a list.
  3. After run_analysis on a fresh org (which has no integrations configured),
     at least one insight is generated (connection-type insights are always
     emitted when SUMIT / Open Finance are absent — verified from source).

Below that: direct tests for the 8 insight generators that were previously
only exercised indirectly via run_analysis() (alert_engine.py had the same
gap before it was closed; cfo_brain_service.py's individual generators were
still untested even after the generator-isolation fix). Each generator's
inputs come from FinancialControlService.get_control_overview() -- traced
per-generator which underlying table feeds it: _reconciliation_insights,
_collections_insights, _cashflow_insights (via Account.balance),
_payables_insights, and _large_unreconciled_bank_insights all read from
Invoice/Bill/BankTransaction/Account.balance (real, unaffected by the
already-documented Account/Transaction issue). _profitability_insights and
_budget_insights DO read from the legacy Transaction table -- tested here
by seeding Transaction rows directly, which validates the insight DECISION
LOGIC given known inputs; it says nothing about whether real syncs
populate that table correctly (already documented separately, not
re-litigated here).
"""
from datetime import date, timedelta
from decimal import Decimal

from cfo.database import SessionLocal
from cfo.models import (
    Account, AccountType, BankTransaction, Bill, BillStatus, Budget,
    Invoice, InvoiceStatus, Transaction, TransactionType,
)
from cfo.services.cfo_brain_service import CFOBrainService

# These are the actual top-level keys returned by CFOBrainService.run_analysis()
# (read directly from cfo_brain_service.py lines 100-107).
EXPECTED_RUN_ANALYSIS_KEYS = {
    "organization_id",
    "analyzed_at",
    "insights_generated",
    "tasks_created",
    "overview",
    "insights",
}


def test_run_analysis_shape(fresh_org):
    """run_analysis(create_tasks=False) returns a dict with all expected top-level keys."""
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        result = CFOBrainService(db, org_id).run_analysis(create_tasks=False)
        assert isinstance(result, dict), "Expected run_analysis() to return a dict"
        missing = EXPECTED_RUN_ANALYSIS_KEYS - result.keys()
        assert not missing, f"Missing keys in run_analysis result: {missing}"
    finally:
        db.close()


def test_list_insights_returns_list(fresh_org):
    """list_insights() returns a list (after run_analysis populates it)."""
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        brain = CFOBrainService(db, org_id)
        brain.run_analysis(create_tasks=False)
        result = brain.list_insights()
        assert isinstance(result, list), "Expected list_insights() to return a list"
    finally:
        db.close()


def test_connection_insights_generated_on_fresh_org(fresh_org):
    """
    A fresh org with no integrations always triggers connection-type insights
    (SUMIT and/or Open Finance missing). Verified from _connection_insights() source:
    it checks settings and active IntegrationConnection rows — a fresh org has neither.
    Since SUMIT_API_KEY is set in conftest (test-env-sumit-key), only the
    open_finance insight fires for sure; but either way insights_generated >= 1.
    """
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        result = CFOBrainService(db, org_id).run_analysis(create_tasks=False)
        # open_finance is always missing on a fresh test org → at least 1 insight
        assert result["insights_generated"] >= 1, (
            "Expected at least one insight for a fresh org with no integrations"
        )
        insights = CFOBrainService(db, org_id).list_insights()
        assert len(insights) >= 1, "list_insights() should be non-empty after run_analysis"
    finally:
        db.close()


def test_one_insight_generator_failing_does_not_abort_the_others(fresh_org, monkeypatch):
    """Unlike AlertEngine.evaluate_all() (which isolates each check via
    _run_check), run_analysis() calls each _*_insights() generator directly
    with no isolation — one exception anywhere currently aborts the entire
    analysis, silently dropping every other insight too (client_automation_
    service.run_post_sync_tasks wraps the whole run_analysis() call in a
    try/except that just logs and continues, so this failure mode is
    invisible in production). This must not be the case: a single generator
    failing should be caught, logged, and not block the others."""
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        brain = CFOBrainService(db, org_id)
        monkeypatch.setattr(
            brain, "_cashflow_insights",
            lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("simulated failure")),
        )

        result = brain.run_analysis(create_tasks=False)

        # Connection insights (a different generator) still ran and produced output.
        assert result["insights_generated"] >= 1, (
            "A failing _cashflow_insights must not silently zero out every other insight"
        )
    finally:
        db.close()


def _insight_types(result: dict) -> list:
    return [i["insight_type"] for i in result["insights"]]


def test_reconciliation_insight_fires_for_unreconciled_bank_transactions(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        acct = Account(organization_id=org_id, name="בנק", account_type=AccountType.BANK, balance=0)
        db.add(acct)
        db.flush()
        today = date.today()
        for i in range(3):
            db.add(BankTransaction(
                organization_id=org_id, account_id=acct.id,
                transaction_date=today, amount=Decimal("-500"), is_reconciled=False,
            ))
        db.commit()

        result = CFOBrainService(db, org_id).run_analysis(create_tasks=False)

        assert "reconciliation" in _insight_types(result)
    finally:
        db.close()


def test_reconciliation_insight_does_not_fire_when_all_reconciled(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        acct = Account(organization_id=org_id, name="בנק", account_type=AccountType.BANK, balance=0)
        db.add(acct)
        db.flush()
        db.add(BankTransaction(
            organization_id=org_id, account_id=acct.id,
            transaction_date=date.today(), amount=Decimal("-500"), is_reconciled=True,
        ))
        db.commit()

        result = CFOBrainService(db, org_id).run_analysis(create_tasks=False)

        assert "reconciliation" not in _insight_types(result)
    finally:
        db.close()


def test_collections_insight_fires_for_overdue_invoices(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        db.add(Invoice(
            organization_id=org_id, invoice_number="INV-1",
            due_date=date.today() - timedelta(days=10), status=InvoiceStatus.SENT,
            balance=Decimal("60000"), total=Decimal("60000"),
        ))
        db.commit()

        result = CFOBrainService(db, org_id).run_analysis(create_tasks=False)

        assert "collections" in _insight_types(result)
        collections_insight = next(i for i in result["insights"] if i["insight_type"] == "collections")
        assert collections_insight["severity"] == "critical"  # > 50,000
    finally:
        db.close()


def test_collections_insight_does_not_fire_with_no_overdue(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        db.add(Invoice(
            organization_id=org_id, invoice_number="INV-CURR",
            due_date=date.today() + timedelta(days=10), status=InvoiceStatus.SENT,
            balance=Decimal("5000"), total=Decimal("5000"),
        ))
        db.commit()

        result = CFOBrainService(db, org_id).run_analysis(create_tasks=False)

        assert "collections" not in _insight_types(result)
    finally:
        db.close()


def test_cashflow_insight_fires_for_low_cash_balance(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        db.add(Account(
            organization_id=org_id, name="בנק", account_type=AccountType.BANK,
            balance=Decimal("500"),
        ))
        db.commit()

        result = CFOBrainService(db, org_id).run_analysis(create_tasks=False)

        assert "cashflow" in _insight_types(result)
    finally:
        db.close()


def test_cashflow_insight_does_not_fire_for_healthy_cash(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        db.add(Account(
            organization_id=org_id, name="בנק", account_type=AccountType.BANK,
            balance=Decimal("100000"),
        ))
        db.commit()

        result = CFOBrainService(db, org_id).run_analysis(create_tasks=False)

        assert "cashflow" not in _insight_types(result)
    finally:
        db.close()


def test_payables_insight_fires_for_cash_pressure(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        db.add(Account(
            organization_id=org_id, name="בנק", account_type=AccountType.BANK,
            balance=Decimal("20000"),
        ))
        db.add(Bill(
            organization_id=org_id, bill_number="BILL-1",
            due_date=date.today() + timedelta(days=5), status=BillStatus.APPROVED,
            balance=Decimal("18000"), total=Decimal("18000"),
        ))
        db.commit()

        result = CFOBrainService(db, org_id).run_analysis(create_tasks=False)

        assert "payables" in _insight_types(result)
    finally:
        db.close()


def test_payables_insight_does_not_fire_with_low_upcoming_bills(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        db.add(Account(
            organization_id=org_id, name="בנק", account_type=AccountType.BANK,
            balance=Decimal("100000"),
        ))
        db.add(Bill(
            organization_id=org_id, bill_number="BILL-SMALL",
            due_date=date.today() + timedelta(days=5), status=BillStatus.APPROVED,
            balance=Decimal("500"), total=Decimal("500"),
        ))
        db.commit()

        result = CFOBrainService(db, org_id).run_analysis(create_tasks=False)

        assert "payables" not in _insight_types(result)
    finally:
        db.close()


def test_profitability_insight_fires_for_period_loss(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        acct = Account(organization_id=org_id, name="בנק", account_type=AccountType.BANK, balance=0)
        db.add(acct)
        db.flush()
        today = date.today()
        db.add(Transaction(
            organization_id=org_id, account_id=acct.id,
            transaction_type=TransactionType.INCOME, amount=Decimal("1000"),
            description="הכנסה", transaction_date=today,
        ))
        db.add(Transaction(
            organization_id=org_id, account_id=acct.id,
            transaction_type=TransactionType.EXPENSE, amount=Decimal("5000"),
            description="הוצאה", transaction_date=today,
        ))
        db.commit()

        result = CFOBrainService(db, org_id).run_analysis(create_tasks=False)

        assert "profitability" in _insight_types(result)
    finally:
        db.close()


def test_profitability_insight_does_not_fire_when_profitable(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        acct = Account(organization_id=org_id, name="בנק", account_type=AccountType.BANK, balance=0)
        db.add(acct)
        db.flush()
        today = date.today()
        db.add(Transaction(
            organization_id=org_id, account_id=acct.id,
            transaction_type=TransactionType.INCOME, amount=Decimal("5000"),
            description="הכנסה", transaction_date=today,
        ))
        db.add(Transaction(
            organization_id=org_id, account_id=acct.id,
            transaction_type=TransactionType.EXPENSE, amount=Decimal("1000"),
            description="הוצאה", transaction_date=today,
        ))
        db.commit()

        result = CFOBrainService(db, org_id).run_analysis(create_tasks=False)

        assert "profitability" not in _insight_types(result)
    finally:
        db.close()


def test_month_close_insight_fires_when_connections_missing(fresh_org):
    """A fresh org always has open_finance missing -> _connection_insights()
    always yields a high/critical item -> _month_close_insights always blocks."""
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        result = CFOBrainService(db, org_id).run_analysis(create_tasks=False)

        assert "month_close" in _insight_types(result)
    finally:
        db.close()


def test_budget_insight_fires_for_overspend(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        today = date.today()
        acct = Account(organization_id=org_id, name="בנק", account_type=AccountType.BANK, balance=0)
        db.add(acct)
        db.flush()
        db.add(Budget(
            organization_id=org_id, category_name="שיווק",
            year=today.year, month=today.month, budgeted_amount=Decimal("1000"),
        ))
        db.add(Transaction(
            organization_id=org_id, account_id=acct.id,
            transaction_type=TransactionType.EXPENSE, amount=Decimal("1500"),
            description="קמפיין", category="שיווק", transaction_date=today,
        ))
        db.commit()

        result = CFOBrainService(db, org_id).run_analysis(create_tasks=False)

        assert "budget" in _insight_types(result)
    finally:
        db.close()


def test_budget_insight_does_not_fire_within_budget(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        today = date.today()
        acct = Account(organization_id=org_id, name="בנק", account_type=AccountType.BANK, balance=0)
        db.add(acct)
        db.flush()
        db.add(Budget(
            organization_id=org_id, category_name="שיווק",
            year=today.year, month=today.month, budgeted_amount=Decimal("2000"),
        ))
        db.add(Transaction(
            organization_id=org_id, account_id=acct.id,
            transaction_type=TransactionType.EXPENSE, amount=Decimal("1000"),
            description="קמפיין", category="שיווק", transaction_date=today,
        ))
        db.commit()

        result = CFOBrainService(db, org_id).run_analysis(create_tasks=False)

        assert "budget" not in _insight_types(result)
    finally:
        db.close()


def test_large_unreconciled_bank_insight_fires(fresh_org):
    """Shares insight_type='reconciliation' with _reconciliation_insights, but
    a distinct fingerprint ('reconciliation:large_unmatched_bank_movements')
    -- checked by fingerprint, not type, to isolate this specific generator."""
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        acct = Account(organization_id=org_id, name="בנק", account_type=AccountType.BANK, balance=0)
        db.add(acct)
        db.flush()
        db.add(BankTransaction(
            organization_id=org_id, account_id=acct.id,
            transaction_date=date.today(), amount=Decimal("-15000"), is_reconciled=False,
        ))
        db.commit()

        result = CFOBrainService(db, org_id).run_analysis(create_tasks=False)

        fingerprints = [i["fingerprint"] for i in result["insights"]]
        assert "reconciliation:large_unmatched_bank_movements" in fingerprints
    finally:
        db.close()
