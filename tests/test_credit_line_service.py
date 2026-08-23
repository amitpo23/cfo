"""PR2 of the bookkeeper daily-cycle plan — credit-line breach detector.

Builds on PR1 (Account.credit_limit, the bank overdraft framework / מסגרת
חח"ד). This module walks LiveCashFlowService.daily_cash_position's daily
balance series against the known credit-limit floor(s) for the org and
raises a CfoInsight when the balance breaches or comes within 10% of the
framework.

Follow-up (21/08/2026 review): moved off the frozen `Transaction` table onto
`LiveCashFlowService.daily_cash_position` — org-scoped, `BankTransaction`-
based, with `Account.balance` as the live running-balance anchor. Tests move
the balance via `BankTransaction` rows + a matching `Account.balance`
(the live balance is the anchor; `daily_cash_position` walks backwards from
it using the BankTransaction net-flow series, so `Account.balance` must
equal the account's balance *after* the modeled transactions).

Written TDD-first: this file existed before src/cfo/services/credit_line_service.py.
"""
from datetime import date, datetime, timedelta
from decimal import Decimal

from cfo.database import SessionLocal
from cfo.models import Account, AccountType, BankTransaction, CfoInsight
from cfo.services import credit_line_service as svc


def _mk_account(db, org_id, *, credit_limit=None, balance=0, name="עו\"ש ראשי",
                 source="open_finance", balance_as_of=None):
    # P0-B (23/08/2026): _live_cash_balance דורש עכשיו גם source="open_finance"
    # וגם חותמת-זמן טרייה (balance_as_of) — ברירת המחדל כאן "עכשיו", כדי
    # שהפיקסצ'ורה תמשיך לייצג חשבון כשיר כברירת מחדל; טסטים שבודקים בפירוש
    # את הסינון עוקפים את זה במפורש (source="manual" / balance_as_of=None).
    if balance_as_of is None and source == "open_finance":
        balance_as_of = datetime.utcnow()
    acc = Account(
        organization_id=org_id, name=name, account_type=AccountType.BANK,
        balance=Decimal(str(balance)), currency="ILS", source=source,
        balance_as_of=balance_as_of,
        credit_limit=Decimal(str(credit_limit)) if credit_limit is not None else None,
    )
    db.add(acc)
    db.flush()
    return acc


def _mk_bank_txn(db, org_id, account_id, *, amount, days_ago=5):
    when = date.today() - timedelta(days=days_ago)
    t = BankTransaction(
        organization_id=org_id, account_id=account_id,
        amount=Decimal(str(amount)), description="test", transaction_date=when,
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
        acc = _mk_account(db, org_id, credit_limit=10000, balance=5000)
        _mk_bank_txn(db, org_id, acc.id, amount=5000, days_ago=5)
        db.commit()

        status = svc.get_credit_line_status(db, org_id)
        assert status["status"] == "ok"
        assert status["basis"] == "org_level"
        assert status["breach_date"] is None
    finally:
        db.close()


def test_unknown_when_credit_limit_known_but_no_bank_data(fresh_org):
    """honest-null: an org with a known credit_limit but no bank-transaction
    data (or bank data but no live Account.balance to anchor it) must not be
    reported "ok" by silent default — that would be a confident ₪0 lie."""
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _mk_account(db, org_id, credit_limit=10000)
        db.commit()

        status = svc.get_credit_line_status(db, org_id)
        assert status["status"] == "unknown"
        assert status["breach_date"] is None
        assert status["min_headroom"] is None
        assert any("֐" <= ch <= "׿" for ch in status["reason"])
    finally:
        db.close()


def test_breach_when_projected_balance_crosses_floor(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        # floor = -10000; a live balance of -15000 crosses it.
        acc = _mk_account(db, org_id, credit_limit=10000, balance=-15000)
        _mk_bank_txn(db, org_id, acc.id, amount=-15000, days_ago=5)
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
        # floor = -10000, warning threshold = -9000. -9500 is inside the band,
        # never crosses the floor itself.
        acc = _mk_account(db, org_id, credit_limit=10000, balance=-9500)
        _mk_bank_txn(db, org_id, acc.id, amount=-9500, days_ago=5)
        db.commit()

        status = svc.get_credit_line_status(db, org_id)
        assert status["status"] == "warning"
        assert status["breach_date"] is None
        assert status["warning_date"] is not None
    finally:
        db.close()


def test_breach_not_masked_by_unrelated_asset_account_balance(fresh_org):
    """תיקון-ביקורת 23/08/2026 (P0-B, ממצא 1+3): 'מזומן' = BANK+Open
    Finance בלבד. חשבון ASSET לא-קשור (חסכון/נכס ידני) עם יתרה ענקית לא
    אמור למסך חריגה אמיתית ממסגרת האשראי הבנקאית — לפני התיקון היה נספר
    לתוך אותה סכימה ומעלים את ה-breach."""
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        # floor = -10000; יתרה חיה בפועל של -15000 חוצה אותה.
        acc = _mk_account(db, org_id, credit_limit=10000, balance=-15000)
        _mk_bank_txn(db, org_id, acc.id, amount=-15000, days_ago=5)
        db.add(Account(
            organization_id=org_id, name="נכס לא-קשור", account_type=AccountType.ASSET,
            balance=Decimal("1000000"), currency="ILS", source="manual",
        ))
        db.commit()

        status = svc.get_credit_line_status(db, org_id)
        assert status["status"] == "breach"
    finally:
        db.close()


def test_unknown_when_credit_limit_account_is_not_open_finance_sourced(fresh_org):
    """חשבון BANK עם credit_limit אבל ממקור ידני/SUMIT (לא Open Finance) —
    אין לו מה לספק כ'רצפה' כשהיתרה שמושווית אליה חייבת להיות OF-בלבד
    (סימטריה עם fix 1/3 — ר' תיעוד credit_line_service.py)."""
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _mk_account(db, org_id, credit_limit=10000, balance=-15000, source="manual")
        db.commit()

        status = svc.get_credit_line_status(db, org_id)
        assert status["status"] == "unknown"
        assert status["accounts"] == []
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
        acc = _mk_account(db, org_id, credit_limit=10000, balance=-15000)
        _mk_bank_txn(db, org_id, acc.id, amount=-15000, days_ago=5)
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
        acc = _mk_account(db, org_id, credit_limit=10000, balance=-9500)
        _mk_bank_txn(db, org_id, acc.id, amount=-9500, days_ago=5)
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
        acc = _mk_account(db, org_id, credit_limit=10000, balance=-15000)
        _mk_bank_txn(db, org_id, acc.id, amount=-15000, days_ago=5)
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
        acc = _mk_account(db, org_id, credit_limit=10000, balance=5000)
        _mk_bank_txn(db, org_id, acc.id, amount=5000, days_ago=5)
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
        acc = _mk_account(db, org_id, credit_limit=10000, balance=-15000)
        txn = _mk_bank_txn(db, org_id, acc.id, amount=-15000, days_ago=5)
        db.commit()

        svc.check_and_alert(db, org_id)
        insight = db.query(CfoInsight).filter(
            CfoInsight.organization_id == org_id,
            CfoInsight.insight_type == "credit_line_breach",
        ).first()
        assert insight.status == "active"

        # Reverse the breaching outflow into an inflow and restore the live
        # balance to match — status recomputes to "ok". (Deleting the row
        # outright would leave zero bank data, which is honest-null
        # "unknown", not "ok" — this models the condition genuinely
        # clearing, not the data disappearing.)
        txn.amount = Decimal("5000")
        acc.balance = Decimal("5000")
        db.commit()

        result = svc.check_and_alert(db, org_id)
        assert result["status"] == "ok"

        db.refresh(insight)
        assert insight.status == "resolved"
        assert insight.resolved_at is not None
    finally:
        db.close()
