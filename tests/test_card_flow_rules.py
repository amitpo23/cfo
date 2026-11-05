"""Simplify C — product rules for card flows on the bank (synthetic data only).

Max/Isracard/Cal clear merchant sales (money IN) and also issue expense cards
(money OUT). The direction decides the rule, not the issuer name:

* IN from a card company  -> ``clearing_income``: one weekly net deposit against
  many card sales (N:1), fee = gross - net, never a guessed 0.
* OUT to a card company   -> ``card_settlement``: no tax invoice, never a
  supplier bill/expense candidate.
"""
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from cfo.services import bank_expense_gap as gap
from cfo.services import card_flow_rules as rules
from cfo.services.bank_reconciliation import BankTxnLite, DocLite, reconcile


def _row(amount, description, raw=None):
    return SimpleNamespace(amount=Decimal(str(amount)), description=description, raw_data=raw)


# --------------------------------------------------------------------- #
# Direction rule
# --------------------------------------------------------------------- #
@pytest.mark.parametrize("desc", ["מקס איט פיננסים", "ישראכרט בע\"מ", "כאל", "MAX IT FINANCE"])
def test_card_company_inflow_is_clearing_income(desc):
    assert rules.card_flow(desc, 1000) == "clearing_income"


@pytest.mark.parametrize("desc", ["ישראכרט", "כאל", "אמריקן אקספרס", "מקס איט פיננסים"])
def test_card_company_outflow_is_card_settlement(desc):
    assert rules.card_flow(desc, -1000) == "card_settlement"


def test_max_inbound_and_isracard_outbound_differ():
    assert rules.card_flow("מקס איט פיננסים", 5000) != rules.card_flow("ישראכרט", -5000)


@pytest.mark.parametrize("desc", ["MEDICAL CENTER", "LOCAL STORE", "CALENDAR APP", "MAXIMUM GYM"])
def test_card_keywords_match_whole_words_only(desc):
    assert rules.card_flow(desc, -100) is None


def test_gap_classifier_does_not_hide_medical_expense_as_card():
    assert gap.classify_transaction(_row(-250, "MEDICAL CENTER")) == "expense_candidate"


def test_gap_classifier_names_incoming_clearing():
    assert gap.classify_transaction(_row(4800, "מקס איט פיננסים")) == "clearing_income"


def test_gap_classifier_keeps_outgoing_max_card_bill_as_card_settlement():
    assert gap.classify_transaction(_row(-900, "מקס איט פיננסים")) == "card_settlement"


# --------------------------------------------------------------------- #
# Owner / salary / supplier
# --------------------------------------------------------------------- #
def test_owner_alias_transfer_is_owner_draw():
    row = _row(-3000, "העברה לבנק אחר", raw={"creditorName": "ישראל ישראלי"})
    assert gap.classify_transaction(row, owner_aliases=["ישראל ישראלי"]) == "owner_draw"


def test_owner_keyword_is_owner_draw():
    assert gap.classify_transaction(_row(-3000, "משיכת בעלים")) == "owner_draw"


def test_without_owner_aliases_transfer_stays_expense_candidate():
    row = _row(-3000, "העברה לבנק אחר", raw={"creditorName": "ישראל ישראלי"})
    assert gap.classify_transaction(row) == "expense_candidate"


def test_salary_stays_salary():
    assert gap.classify_transaction(_row(-8000, "משכורת")) == "salary"


# --------------------------------------------------------------------- #
# Payee from Open Finance
# --------------------------------------------------------------------- #
def test_payee_prefers_open_finance_party_over_description():
    row = _row(-120, "העברה לבנק אחר", raw={"payeeName": "ספק דוגמה בע\"מ"})
    assert rules.payee(row) == "ספק דוגמה בע\"מ"


def test_payee_is_none_when_open_finance_has_none():
    assert rules.payee(_row(-120, "העברה לבנק אחר")) is None


# --------------------------------------------------------------------- #
# Clearing deposit <-> card sales (N:1)
# --------------------------------------------------------------------- #
D = date(2026, 3, 16)  # a Monday


def _sale(i, amount, days_before):
    return rules.CardSale(id=i, amount=amount, date=D - timedelta(days=days_before))


def test_clearing_match_sums_window_and_records_fee():
    sales = [_sale(1, 600.0, 3), _sale(2, 400.0, 6)]
    m = rules.match_clearing_deposit(980.0, D, sales, as_of=D)
    assert m["status"] == "candidate"
    assert m["gross"] == 1000.0
    assert m["net"] == 980.0
    assert m["fee"] == 20.0
    assert m["fee_rate"] == 0.02
    assert m["sale_ids"] == [1, 2]


def test_clearing_match_ignores_sales_outside_window_and_after_deposit():
    sales = [_sale(1, 500.0, 2), _sale(2, 999.0, 40), _sale(3, 777.0, -1)]
    m = rules.match_clearing_deposit(490.0, D, sales, as_of=D)
    assert m["sale_ids"] == [1]


def test_clearing_match_without_sales_leaves_fee_missing_not_zero():
    m = rules.match_clearing_deposit(980.0, D, [], as_of=D)
    assert m["status"] == "missing"
    assert m["gross"] is None
    assert m["fee"] is None
    assert m["reason"] == "no_card_sales_in_window"
    assert m["as_of"] == D.isoformat()


def test_clearing_match_net_above_gross_needs_review_without_fee():
    m = rules.match_clearing_deposit(1200.0, D, [_sale(1, 1000.0, 3)], as_of=D)
    assert m["status"] == "review"
    assert m["fee"] is None
    assert m["reason"] == "net_exceeds_gross"


def test_clearing_match_fee_above_cap_needs_review():
    m = rules.match_clearing_deposit(800.0, D, [_sale(1, 1000.0, 3)], as_of=D)
    assert m["status"] == "review"
    assert m["fee"] is None
    assert m["reason"] == "fee_above_cap"


def test_match_clearing_deposits_does_not_reuse_a_sale():
    sales = [_sale(1, 500.0, 3)]
    out = rules.match_clearing_deposits(
        [(10, 490.0, D), (11, 490.0, D + timedelta(days=1))], sales, as_of=D)
    assert out[0]["sale_ids"] == [1]
    assert out[1]["status"] == "missing"


# --------------------------------------------------------------------- #
# Bank match must not offer card flows 1:1 against documents
# --------------------------------------------------------------------- #
def test_reconcile_does_not_offer_card_settlement_against_bills():
    txns = [BankTxnLite(id=1, amount=-1500.0, date=D, description="ישראכרט")]
    bills = [DocLite(id=7, entity_type="bill", amount=1500.0, date=D, name="ישראכרט")]
    out = reconcile(txns, [], bills)
    assert out["candidates"] == []
    assert out["card_flows"]["card_settlement"] == [1]


def test_reconcile_does_not_offer_clearing_deposit_one_to_one_against_invoice():
    txns = [BankTxnLite(id=2, amount=980.0, date=D, description="מקס איט פיננסים")]
    invoices = [DocLite(id=9, entity_type="invoice", amount=980.0, date=D, name="לקוח")]
    out = reconcile(txns, invoices, [])
    assert out["candidates"] == []
    assert out["card_flows"]["clearing_income"] == [2]


def test_reconcile_still_offers_supplier_outflow_against_bill():
    txns = [BankTxnLite(id=3, amount=-1500.0, date=D, description="ספק דוגמה")]
    bills = [DocLite(id=7, entity_type="bill", amount=1500.0, date=D, name="ספק דוגמה")]
    out = reconcile(txns, [], bills)
    assert [c["entity_id"] for c in out["candidates"]] == [7]


# --------------------------------------------------------------------- #
# DB consumers: suggest_matches, gap_report, suppliers_missing_invoices
# --------------------------------------------------------------------- #
from cfo.database import SessionLocal  # noqa: E402
from cfo.models import (  # noqa: E402
    BankTransaction, Bill, BillStatus, Invoice, InvoiceStatus, Payment,
)
from cfo.services.manual_reconciliation import ManualReconciliationService  # noqa: E402

TODAY = date.today()


def _db_txn(db, org_id, amount, description, days_ago=0, raw=None):
    t = BankTransaction(organization_id=org_id, amount=Decimal(str(amount)),
                        transaction_date=TODAY - timedelta(days=days_ago),
                        description=description, currency="ILS", raw_data=raw)
    db.add(t)
    db.flush()
    return t


def test_suggest_matches_card_settlement_offers_no_supplier_document(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        db.add(Bill(organization_id=org_id, bill_number="B-1", status=BillStatus.RECEIVED,
                    issue_date=TODAY, total=Decimal("1500")))
        txn = _db_txn(db, org_id, -1500, "ישראכרט")
        db.commit()
        assert ManualReconciliationService(db, org_id).suggest_matches(txn.id) == []
    finally:
        db.close()


def test_suggest_matches_clearing_deposit_offers_card_sales_with_fee(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        db.add(Invoice(organization_id=org_id, invoice_number="INV-9", status=InvoiceStatus.PAID,
                       issue_date=TODAY - timedelta(days=1), total=Decimal("980"),
                       subtotal=Decimal("980"), tax=Decimal("0"), balance=Decimal("0")))
        db.add(Payment(organization_id=org_id, amount=Decimal("1000"), method="credit_card",
                       payment_date=TODAY - timedelta(days=3)))
        txn = _db_txn(db, org_id, 980, "מקס איט פיננסים")
        db.commit()
        out = ManualReconciliationService(db, org_id).suggest_matches(txn.id)
        assert len(out) == 1
        s = out[0]
        assert s["entity_type"] == "card_sales"
        assert s["gross"] == 1000.0 and s["fee"] == 20.0
        assert s["status"] == "candidate"
    finally:
        db.close()


def test_suggest_matches_clearing_without_card_sales_is_missing_not_guess(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        txn = _db_txn(db, org_id, 980, "מקס איט פיננסים")
        db.commit()
        out = ManualReconciliationService(db, org_id).suggest_matches(txn.id)
        assert out[0]["status"] == "missing"
        assert out[0]["fee"] is None and out[0]["gross"] is None
    finally:
        db.close()


def test_gap_report_keeps_clearing_out_of_undocumented_inflows(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _db_txn(db, org_id, 4800, "מקס איט פיננסים")
        _db_txn(db, org_id, 700, "העברה מלקוח")
        db.commit()
        report = gap.gap_report(db, org_id, TODAY.year, TODAY.month)
        assert report["inflows"]["undocumented_count"] == 1
        assert report["inflows"]["undocumented_total"] == 700.0
        assert report["inflows"]["clearing_income"] == {"count": 1, "total": 4800.0}
    finally:
        db.close()


def test_gap_report_fills_counterparty_from_open_finance(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _db_txn(db, org_id, -300, "העברה לבנק אחר", raw={"payeeName": "ספק דוגמה"})
        db.commit()
        report = gap.gap_report(db, org_id, TODAY.year, TODAY.month)
        assert report["transactions"][0]["counterparty"] == "ספק דוגמה"
    finally:
        db.close()


def test_suppliers_missing_invoices_groups_by_open_finance_payee(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _db_txn(db, org_id, -300, "העברה לבנק אחר", raw={"payeeName": "ספק דוגמה"})
        db.commit()
        out = gap.suppliers_missing_invoices(db, org_id, TODAY - timedelta(days=5), TODAY)
        assert [s["name"] for s in out["suppliers"]] == ["ספק דוגמה"]
    finally:
        db.close()


def test_payee_ignores_transfer_memo():
    row = _row(-7000, "העברה לבנק אחר",
               raw={"description": {"additionalInfo": '{"purposeDescription":"שכ\\"ד"}'}})
    assert rules.payee(row) is None


def test_synthesis_card_settlement_is_statement_review_not_document_hunt():
    from cfo.services.financial_synthesis import build_synthesis

    report = build_synthesis([BankTxnLite(1, -1500.0, D, "ישראכרט")], [], [], [])
    types = [a["type"] for a in report["required_actions"]]
    assert types == ["review_card_settlement"]


def test_synthesis_clearing_deposit_asks_for_card_sales_match():
    from cfo.services.financial_synthesis import build_synthesis

    report = build_synthesis([BankTxnLite(2, 980.0, D, "מקס איט פיננסים")], [], [], [])
    types = [a["type"] for a in report["required_actions"]]
    assert types == ["match_clearing_to_card_sales"]


def test_missing_documents_tool_buckets_card_charge_by_keyword(fresh_org):
    from cfo.services import bank_query_service as bq

    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _db_txn(db, org_id, -1500, "ישראכרט", raw={"type": "CHECKING", "status": "BOOKED"})
        db.commit()
        result = bq.classify_missing_documents(db, org_id)
        assert result["excluded"]["card_settlement"]["count"] == 1
        assert result["missing_document"]["count"] == 0
    finally:
        db.close()


def _owner_rule(db, org_id):
    import uuid
    from cfo.models import ClientDashboard, DashboardPlan

    dash = ClientDashboard(slug=f"c-{uuid.uuid4().hex[:10]}", title="t",
                           primary_organization_id=org_id)
    db.add(dash)
    db.flush()
    db.add(DashboardPlan(dashboard_id=dash.id, version=str(uuid.uuid4()), payload={
        "statusRules": [{"id": "r1", "contains": "ישראל ישראלי", "category": "owner_draws",
                         "field": "counterparty", "direction": "out"}]}))


def test_scan_and_alert_skips_owner_transfer_from_saved_rule(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _owner_rule(db, org_id)
        _db_txn(db, org_id, -3000, "העברה לבנק אחר", raw={"creditorName": "ישראל ישראלי"})
        db.commit()
        assert gap.scan_and_alert(db, org_id, lookback_days=14)["created"] == 0
    finally:
        db.close()


def test_gap_report_uses_saved_owner_filing_rule(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _owner_rule(db, org_id)
        _db_txn(db, org_id, -3000, "העברה לבנק אחר", raw={"creditorName": "ישראל ישראלי"})
        db.commit()
        report = gap.gap_report(db, org_id, TODAY.year, TODAY.month)
        assert report["totals"]["excluded_by_class"]["owner_draw"]["total"] == 3000.0
        assert report["totals"]["undocumented_count"] == 0
    finally:
        db.close()


@pytest.mark.parametrize("desc", ["מקס סטוק", "MAX STOCK"])
def test_retail_chain_named_max_is_not_a_card_company(desc):
    assert rules.card_flow(desc, -80) is None
