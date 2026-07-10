"""Tests for M8 bank-aware query service — query_bank_transactions,
get_bank_position, classify_missing_documents. All org-scoped over
BankTransaction/Account; verifies filters, full-set totals (not just the
returned page), exclusion-bucket classification, and org isolation."""
from datetime import date, timedelta
from decimal import Decimal

from cfo.database import SessionLocal
from cfo.models import Account, AccountType, BankTransaction
from cfo.services import bank_query_service as svc


def _mk_account(db, org_id, name="בנק לאומי", account_type=AccountType.BANK, external_id="open_finance:acc1", balance=None):
    acc = Account(
        organization_id=org_id, name=name, account_type=account_type,
        external_id=external_id, balance=balance,
    )
    db.add(acc)
    db.flush()
    return acc


def _mk_txn(
    db, org_id, *, account_id=None, amount, description="עסקה", days_ago=0,
    txn_type="CHECKING", category_main=None, category_sub=None, merchant=None,
    is_reconciled=False, is_provisional=False, status="BOOKED",
):
    raw = {"type": txn_type, "status": status}
    if category_main or category_sub:
        raw["category"] = {"main": category_main, "sub": category_sub}
    if merchant:
        raw["merchantName"] = merchant
    txn = BankTransaction(
        organization_id=org_id, account_id=account_id,
        transaction_date=date.today() - timedelta(days=days_ago),
        description=description, amount=Decimal(str(amount)),
        currency="ILS", is_reconciled=is_reconciled, is_provisional=is_provisional,
        raw_data=raw,
    )
    db.add(txn)
    db.flush()
    return txn


def test_query_bank_transactions_filters_and_full_set_totals(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        acc = _mk_account(db, org_id)
        _mk_txn(db, org_id, account_id=acc.id, amount=1000, description="תקבול לקוח", days_ago=1, txn_type="CHECKING")
        _mk_txn(db, org_id, account_id=acc.id, amount=-200, description="רכישה בסופר", days_ago=2, txn_type="CARD")
        _mk_txn(db, org_id, account_id=acc.id, amount=-300, description="רכישה בדלק", days_ago=3, txn_type="CARD")
        db.commit()

        result = svc.query_bank_transactions(db, org_id, limit=50)
        assert result["count"] == 3
        assert result["total_amount"] == 500.0
        assert len(result["transactions"]) == 3

        only_out = svc.query_bank_transactions(db, org_id, direction="out")
        assert only_out["count"] == 2
        assert only_out["total_amount"] == -500.0

        only_in = svc.query_bank_transactions(db, org_id, direction="in")
        assert only_in["count"] == 1
        assert only_in["total_amount"] == 1000.0

        card_only = svc.query_bank_transactions(db, org_id, txn_type="CARD")
        assert card_only["count"] == 2

        searched = svc.query_bank_transactions(db, org_id, search="סופר")
        assert searched["count"] == 1
        assert searched["transactions"][0]["description"] == "רכישה בסופר"
    finally:
        db.close()


def test_query_bank_transactions_totals_over_full_set_not_just_page(fresh_org):
    """count/total_amount must reflect the entire filtered set even when
    more rows exist than `limit` returns."""
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        acc = _mk_account(db, org_id)
        for i in range(5):
            _mk_txn(db, org_id, account_id=acc.id, amount=-10, description=f"עסקה {i}", days_ago=i)
        db.commit()

        result = svc.query_bank_transactions(db, org_id, limit=2)
        assert result["count"] == 5
        assert result["total_amount"] == -50.0
        assert len(result["transactions"]) == 2
    finally:
        db.close()


def test_query_bank_transactions_only_unmatched(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        acc = _mk_account(db, org_id)
        _mk_txn(db, org_id, account_id=acc.id, amount=-100, is_reconciled=True)
        _mk_txn(db, org_id, account_id=acc.id, amount=-200, is_reconciled=False)
        db.commit()

        result = svc.query_bank_transactions(db, org_id, only_unmatched=True)
        assert result["count"] == 1
        assert result["transactions"][0]["amount"] == -200.0
    finally:
        db.close()


def test_query_bank_transactions_org_isolation(fresh_org):
    org_a = fresh_org()["org_id"]
    org_b = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        acc_a = _mk_account(db, org_a, external_id="open_finance:acc-a")
        acc_b = _mk_account(db, org_b, external_id="open_finance:acc-b")
        _mk_txn(db, org_a, account_id=acc_a.id, amount=-50, description="A")
        _mk_txn(db, org_b, account_id=acc_b.id, amount=-9999, description="B")
        db.commit()

        result_a = svc.query_bank_transactions(db, org_a)
        assert result_a["count"] == 1
        assert result_a["transactions"][0]["description"] == "A"
    finally:
        db.close()


def test_get_bank_position_reports_balance_and_freshness(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        acc = _mk_account(db, org_id, name="בנק הפועלים", balance=Decimal("15000.50"))
        _mk_txn(db, org_id, account_id=acc.id, amount=-100, days_ago=5)
        _mk_txn(db, org_id, account_id=acc.id, amount=-200, days_ago=1, is_provisional=True)
        db.commit()

        result = svc.get_bank_position(db, org_id)
        assert len(result["accounts"]) == 1
        row = result["accounts"][0]
        assert row["name"] == "בנק הפועלים"
        assert row["balance"] == 15000.5
        assert row["transaction_count"] == 2
        assert row["has_provisional_data"] is True
        assert row["last_transaction_date"] == (date.today() - timedelta(days=1)).isoformat()
    finally:
        db.close()


def test_get_bank_position_org_isolation(fresh_org):
    org_a = fresh_org()["org_id"]
    org_b = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _mk_account(db, org_a, name="A-bank", external_id="open_finance:a")
        _mk_account(db, org_b, name="B-bank", external_id="open_finance:b")
        db.commit()

        result_a = svc.get_bank_position(db, org_a)
        names = {a["name"] for a in result_a["accounts"]}
        assert names == {"A-bank"}
    finally:
        db.close()


def test_classify_missing_documents_buckets_known_categories(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        acc = _mk_account(db, org_id)
        # card settlement
        _mk_txn(db, org_id, account_id=acc.id, amount=-1000, description="איסתקארד",
                category_main="INCOMES_EXPENSES", category_sub="CREDIT_CARD_CHECKING")
        # cash withdrawal via keyword
        _mk_txn(db, org_id, account_id=acc.id, amount=-500, description="משיכה מבנקט")
        # transfer
        _mk_txn(db, org_id, account_id=acc.id, amount=-300, description="העברה לבנק אחר")
        # standing order
        _mk_txn(db, org_id, account_id=acc.id, amount=-150, description="הוראת קבע ביטוח")
        # tax
        _mk_txn(db, org_id, account_id=acc.id, amount=-2000, description="מס הכנסה מקדמה")
        # bank fee
        _mk_txn(db, org_id, account_id=acc.id, amount=-25, description="עמלת ניהול חשבון")
        # loan
        _mk_txn(db, org_id, account_id=acc.id, amount=-1200, description="החזר הלוואה")
        # salary
        _mk_txn(db, org_id, account_id=acc.id, amount=-8000, description="שכר עובד")
        # missing-document candidate
        _mk_txn(db, org_id, account_id=acc.id, amount=-400, description="ספק ציוד משרדי", txn_type="CARD", merchant="ציוד משרדי בע\"מ")
        # inflow should never appear (not outgoing)
        _mk_txn(db, org_id, account_id=acc.id, amount=500, description="תקבול")
        # already reconciled outgoing should be excluded entirely
        _mk_txn(db, org_id, account_id=acc.id, amount=-999, description="ספק אחר", is_reconciled=True)
        db.commit()

        result = svc.classify_missing_documents(db, org_id)
        excluded = result["excluded"]
        assert excluded["card_settlement"]["count"] == 1
        assert excluded["card_settlement"]["total"] == 1000.0
        assert excluded["cash"]["count"] == 1
        assert excluded["transfers"]["count"] == 1
        assert excluded["standing_orders"]["count"] == 1
        assert excluded["taxes"]["count"] == 1
        assert excluded["bank_fees"]["count"] == 1
        assert excluded["loans"]["count"] == 1
        assert excluded["salary"]["count"] == 1

        missing = result["missing_document"]
        assert missing["count"] == 1
        assert missing["total"] == 400.0
        assert len(missing["top_candidates"]) == 1
        cand = missing["top_candidates"][0]
        assert cand["channel"] == "CARD"
        assert cand["total"] == 400.0
    finally:
        db.close()


def test_classify_missing_documents_groups_candidates_by_normalized_merchant(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        acc = _mk_account(db, org_id)
        _mk_txn(db, org_id, account_id=acc.id, amount=-100, description="ספק 123", merchant="חברת שילוח", txn_type="BANK", days_ago=3)
        _mk_txn(db, org_id, account_id=acc.id, amount=-150, description="ספק 456", merchant="חברת שילוח", txn_type="BANK", days_ago=1)
        db.commit()

        result = svc.classify_missing_documents(db, org_id)
        candidates = result["missing_document"]["top_candidates"]
        assert len(candidates) == 1
        assert candidates[0]["count"] == 2
        assert candidates[0]["total"] == 250.0
        assert candidates[0]["last_date"] == (date.today() - timedelta(days=1)).isoformat()
    finally:
        db.close()


def test_classify_missing_documents_date_from_filter(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        acc = _mk_account(db, org_id)
        _mk_txn(db, org_id, account_id=acc.id, amount=-400, description="ספק ישן", days_ago=100)
        _mk_txn(db, org_id, account_id=acc.id, amount=-500, description="ספק חדש", days_ago=1)
        db.commit()

        cutoff = (date.today() - timedelta(days=10)).isoformat()
        result = svc.classify_missing_documents(db, org_id, date_from=cutoff)
        assert result["missing_document"]["count"] == 1
        assert result["missing_document"]["total"] == 500.0
    finally:
        db.close()


def test_classify_missing_documents_org_isolation(fresh_org):
    org_a = fresh_org()["org_id"]
    org_b = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        acc_a = _mk_account(db, org_a, external_id="open_finance:mda")
        acc_b = _mk_account(db, org_b, external_id="open_finance:mdb")
        _mk_txn(db, org_a, account_id=acc_a.id, amount=-100, description="A-supplier")
        _mk_txn(db, org_b, account_id=acc_b.id, amount=-99999, description="B-supplier")
        db.commit()

        result_a = svc.classify_missing_documents(db, org_a)
        assert result_a["missing_document"]["total"] == 100.0
    finally:
        db.close()
