"""PR2 of the bookkeeper daily-cycle plan — credit-line breach detector.

Builds on PR1 (Account.credit_limit, the bank overdraft framework / מסגרת
חח"ד). This module walks CashFlowService.get_daily_cash_position's daily
balance series against the known credit-limit floor(s) for the org and
raises a CfoInsight when the balance breaches or comes within 10% of the
framework.

`get_daily_cash_position` is org-level (it sums the legacy `Transaction`
table for the whole org, not per-account), so tests move the balance via
plain `Transaction` rows rather than `BankTransaction` rows.

Written TDD-first: this file existed before src/cfo/services/credit_line_service.py.
"""
from datetime import datetime, timedelta
from decimal import Decimal

from cfo.database import SessionLocal
from cfo.models import Account, AccountType, CfoInsight, Transaction, TransactionType
from cfo.services import credit_line_service as svc


def _mk_account(db, org_id, *, credit_limit=None, name="עו\"ש ראשי"):
    acc = Account(
        organization_id=org_id, name=name, account_type=AccountType.BANK,
        balance=Decimal("0"), currency="ILS", source="open_finance",
        credit_limit=Decimal(str(credit_limit)) if credit_limit is not None else None,
    )
    db.add(acc)
    db.flush()
    return acc


def _mk_txn(db, org_id, account_id, *, amount, txn_type, days_ago=5):
    when = datetime.now() - timedelta(days=days_ago)
    when = when.replace(hour=12, minute=0, second=0, microsecond=0)
    t = Transaction(
        organization_id=org_id, account_id=account_id,
        transaction_type=txn_type, amount=Decimal(str(amount)),
        description="test", transaction_date=when,
    )
    db.add(t)
    db.flush()
    return t


# --------------------------------------------------------------------- #
# get_credit_line_status
# --------------------------------------------------------------------- #
def test_unknown_when_no_account_has_credit_limit(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _mk_account(db, org_id, credit_limit=None)
        db.commit()

        status = svc.get_credit_line_status(db, org_id)
        assert status["status"] == "unknown"
        assert "מסגרת אשראי" in status["reason"]
    finally:
        db.close()


def test_ok_when_balance_stays_above_floor(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _mk_account(db, org_id, credit_limit=10000)
        db.commit()

        status = svc.get_credit_line_status(db, org_id)
        assert status["status"] == "ok"
        assert status["basis"] == "org_level"
        assert status["breach_date"] is None
    finally:
        db.close()


def test_breach_when_projected_balance_crosses_floor(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        acc = _mk_account(db, org_id, credit_limit=10000)
        # floor = -10000; an outflow of 15000 pushes the running balance to -15000.
        _mk_txn(db, org_id, acc.id, amount=15000, txn_type=TransactionType.EXPENSE, days_ago=5)
        db.commit()

        status = svc.get_credit_line_status(db, org_id)
        assert status["status"] == "breach"
        assert status["breach_date"] is not None
        assert status["min_headroom"] < 0
    finally:
        db.close()


def test_warning_when_projected_balance_within_10_percent_of_floor(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        acc = _mk_account(db, org_id, credit_limit=10000)
        # floor = -10000, warning threshold = -9000. -9500 is inside the band,
        # never crosses the floor itself.
        _mk_txn(db, org_id, acc.id, amount=9500, txn_type=TransactionType.EXPENSE, days_ago=5)
        db.commit()

        status = svc.get_credit_line_status(db, org_id)
        assert status["status"] == "warning"
        assert status["breach_date"] is None
        assert status["warning_date"] is not None
    finally:
        db.close()


def test_hebrew_strings_present_in_unknown_reason(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        status = svc.get_credit_line_status(db, org_id)
        assert status["status"] == "unknown"
        assert any("֐" <= ch <= "׿" for ch in status["reason"])
    finally:
        db.close()


# --------------------------------------------------------------------- #
# check_and_alert
# --------------------------------------------------------------------- #
def test_check_and_alert_creates_breach_insight_with_hebrew_text(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        acc = _mk_account(db, org_id, credit_limit=10000)
        _mk_txn(db, org_id, acc.id, amount=15000, txn_type=TransactionType.EXPENSE, days_ago=5)
        db.commit()

        result = svc.check_and_alert(db, org_id)
        assert result["status"] == "breach"

        insight = db.query(CfoInsight).filter(
            CfoInsight.organization_id == org_id,
            CfoInsight.insight_type == "credit_line_breach",
        ).first()
        assert insight is not None
        assert insight.severity == "critical"
        assert any("֐" <= ch <= "׿" for ch in insight.title)
        assert any("֐" <= ch <= "׿" for ch in (insight.message or ""))
    finally:
        db.close()


def test_check_and_alert_creates_warning_insight_with_high_severity(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        acc = _mk_account(db, org_id, credit_limit=10000)
        _mk_txn(db, org_id, acc.id, amount=9500, txn_type=TransactionType.EXPENSE, days_ago=5)
        db.commit()

        result = svc.check_and_alert(db, org_id)
        assert result["status"] == "warning"

        insight = db.query(CfoInsight).filter(
            CfoInsight.organization_id == org_id,
            CfoInsight.insight_type == "credit_line_breach",
        ).first()
        assert insight is not None
        assert insight.severity == "high"
    finally:
        db.close()


def test_check_and_alert_dedups_on_fingerprint_across_double_run(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        acc = _mk_account(db, org_id, credit_limit=10000)
        _mk_txn(db, org_id, acc.id, amount=15000, txn_type=TransactionType.EXPENSE, days_ago=5)
        db.commit()

        svc.check_and_alert(db, org_id)
        svc.check_and_alert(db, org_id)

        rows = db.query(CfoInsight).filter(
            CfoInsight.organization_id == org_id,
            CfoInsight.insight_type == "credit_line_breach",
        ).all()
        assert len(rows) == 1
    finally:
        db.close()


def test_check_and_alert_no_insight_when_ok(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _mk_account(db, org_id, credit_limit=10000)
        db.commit()

        result = svc.check_and_alert(db, org_id)
        assert result["status"] == "ok"

        rows = db.query(CfoInsight).filter(
            CfoInsight.organization_id == org_id,
            CfoInsight.insight_type == "credit_line_breach",
        ).all()
        assert len(rows) == 0
    finally:
        db.close()


def test_check_and_alert_resolves_previously_active_insight_when_back_to_ok(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        acc = _mk_account(db, org_id, credit_limit=10000)
        txn = _mk_txn(db, org_id, acc.id, amount=15000, txn_type=TransactionType.EXPENSE, days_ago=5)
        db.commit()

        svc.check_and_alert(db, org_id)
        insight = db.query(CfoInsight).filter(
            CfoInsight.organization_id == org_id,
            CfoInsight.insight_type == "credit_line_breach",
        ).first()
        assert insight.status == "active"

        # Undo the breaching transaction — status recomputes to "ok".
        db.delete(txn)
        db.commit()

        result = svc.check_and_alert(db, org_id)
        assert result["status"] == "ok"

        db.refresh(insight)
        assert insight.status == "resolved"
        assert insight.resolved_at is not None
    finally:
        db.close()
