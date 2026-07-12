"""טסטים למנוע פער בנק-חשבוניות (bank_expense_gap.py) — סיווג תנועות בנק
יוצאות, בדיקת קיום מסמך, דוח פער חודשי, וסריקה יומית שיוצרת התרעות (CfoInsight).

כתוב לפי TDD: הקובץ הזה נכתב לפני המימוש ב-src/cfo/services/bank_expense_gap.py.
"""
from datetime import date, timedelta
from decimal import Decimal

from cfo.database import SessionLocal
from cfo.models import Bill, BillStatus, BankTransaction, CfoInsight, Contact, ContactType, Expense, Invoice, InvoiceStatus, Organization
from cfo.services import bank_expense_gap as svc


# --------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------- #
def _mk_txn(db, org_id, *, amount, description="עסקה", days_ago=0,
            category_main=None, category_sub=None, merchant=None,
            matched_entity_type=None, matched_entity_id=None,
            is_reconciled=False):
    raw = {}
    if category_main or category_sub:
        raw["category"] = {"main": category_main, "sub": category_sub}
    if merchant:
        raw["merchantName"] = merchant
    txn = BankTransaction(
        organization_id=org_id,
        transaction_date=date.today() - timedelta(days=days_ago),
        description=description, amount=Decimal(str(amount)), currency="ILS",
        raw_data=raw or None,
        matched_entity_type=matched_entity_type, matched_entity_id=matched_entity_id,
        is_reconciled=is_reconciled,
    )
    db.add(txn)
    db.flush()
    return txn


def _mk_bill(db, org_id, *, total, days_ago=0, bill_number="B-1"):
    b = Bill(organization_id=org_id, bill_number=bill_number, status=BillStatus.RECEIVED,
              issue_date=date.today() - timedelta(days=days_ago), total=Decimal(str(total)))
    db.add(b)
    db.flush()
    return b


def _mk_expense(db, org_id, *, total, days_ago=0, supplier_name="ספק בדיקה"):
    e = Expense(organization_id=org_id, supplier_name=supplier_name, amount=Decimal(str(total)),
                total=Decimal(str(total)), expense_date=date.today() - timedelta(days=days_ago))
    db.add(e)
    db.flush()
    return e


# --------------------------------------------------------------------- #
# classify_transaction
# --------------------------------------------------------------------- #
def test_classify_card_settlement_by_category_sub():
    txn = BankTransaction(amount=Decimal("-500"), description="חיוב חודשי",
                           raw_data={"category": {"main": "INCOMES_EXPENSES", "sub": "CREDIT_CARD_CHECKING"}})
    assert svc.classify_transaction(txn) == "card_settlement"


def test_classify_card_settlement_by_keyword():
    txn = BankTransaction(amount=Decimal("-320"), description="חיוב ישראכרט", raw_data=None)
    assert svc.classify_transaction(txn) == "card_settlement"


def test_classify_tax_payment():
    txn = BankTransaction(amount=Decimal("-1800"), description="תשלום מע\"מ תקופתי", raw_data=None)
    assert svc.classify_transaction(txn) == "tax_payment"


def test_classify_tax_payment_bituach_leumi():
    txn = BankTransaction(amount=Decimal("-900"), description="ביטוח לאומי - עצמאי", raw_data=None)
    assert svc.classify_transaction(txn) == "tax_payment"


def test_classify_salary():
    txn = BankTransaction(amount=Decimal("-8000"), description="העברת משכורת לעובד", raw_data=None)
    assert svc.classify_transaction(txn) == "salary"


def test_classify_loan_or_finance():
    txn = BankTransaction(amount=Decimal("-2500"), description="החזר הלוואה חודשי", raw_data=None)
    assert svc.classify_transaction(txn) == "loan_or_finance"


def test_classify_self_transfer():
    txn = BankTransaction(amount=Decimal("-3000"), description="העברה עצמית לחיסכון", raw_data=None)
    assert svc.classify_transaction(txn) == "self_transfer"


def test_classify_bank_fee():
    txn = BankTransaction(amount=Decimal("-25"), description="עמלת ניהול חשבון", raw_data=None)
    assert svc.classify_transaction(txn) == "bank_fee"


def test_classify_default_expense_candidate_when_unclear():
    """אין סיווג ברור -> expense_candidate (עדיף false-positive)."""
    txn = BankTransaction(amount=Decimal("-450"), description="תשלום לספק שיווק דיגיטלי", raw_data=None)
    assert svc.classify_transaction(txn) == "expense_candidate"


def test_classify_ignores_inflow_amount():
    txn = BankTransaction(amount=Decimal("500"), description="תקבול לקוח", raw_data=None)
    assert svc.classify_transaction(txn) != "expense_candidate"


# --------------------------------------------------------------------- #
# has_document
# --------------------------------------------------------------------- #
def test_has_document_true_via_matched_entity_type(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        txn = _mk_txn(db, org_id, amount=-500, matched_entity_type="bill", matched_entity_id=999)
        db.commit()
        assert svc.has_document(db, org_id, txn) is True
    finally:
        db.close()


def test_has_document_true_via_amount_and_date_window_bill(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _mk_bill(db, org_id, total=1180, days_ago=2)
        txn = _mk_txn(db, org_id, amount=-1180, days_ago=0)
        db.commit()
        assert svc.has_document(db, org_id, txn) is True
    finally:
        db.close()


def test_has_document_true_via_amount_and_date_window_expense(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _mk_expense(db, org_id, total=350, days_ago=1)
        txn = _mk_txn(db, org_id, amount=-350.5, days_ago=0)  # within ₪1 tolerance
        db.commit()
        assert svc.has_document(db, org_id, txn) is True
    finally:
        db.close()


def test_has_document_false_outside_date_window(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _mk_bill(db, org_id, total=1180, days_ago=20)  # outside ±7 days
        txn = _mk_txn(db, org_id, amount=-1180, days_ago=0)
        db.commit()
        assert svc.has_document(db, org_id, txn) is False
    finally:
        db.close()


def test_has_document_false_amount_mismatch(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _mk_bill(db, org_id, total=1180, days_ago=1)
        txn = _mk_txn(db, org_id, amount=-50, days_ago=0)
        db.commit()
        assert svc.has_document(db, org_id, txn) is False
    finally:
        db.close()


# --------------------------------------------------------------------- #
# gap_report
# --------------------------------------------------------------------- #
def test_gap_report_undocumented_vs_documented_and_org_isolation(fresh_org):
    org_a = fresh_org()["org_id"]
    org_b = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        today = date.today()
        year, month = today.year, today.month
        # org_a: one documented, one undocumented expense_candidate, one card_settlement excluded.
        _mk_bill(db, org_a, total=1000, days_ago=1)
        _mk_txn(db, org_a, amount=-1000, description="ספק א", days_ago=0)
        _mk_txn(db, org_a, amount=-300, description="ספק ב ללא מסמך", days_ago=0)
        _mk_txn(db, org_a, amount=-450, description="חיוב ישראכרט", days_ago=0)
        # org_b: a large undocumented transaction that must NOT leak into org_a's report.
        _mk_txn(db, org_b, amount=-99999, description="לא שייך לארגון א", days_ago=0)
        db.commit()

        report = svc.gap_report(db, org_a, year, month)
        assert report["totals"]["documented_total"] == 1000.0
        assert report["totals"]["undocumented_total"] == 300.0
        assert report["totals"]["undocumented_count"] == 1
        assert report["totals"]["excluded_by_class"]["card_settlement"]["total"] == 450.0
        assert report["totals"]["total_bank_outflow"] == 1750.0
        assert 99999 not in [t["amount"] for t in report["transactions"]]
    finally:
        db.close()


def test_gap_report_totals_invariant(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        today = date.today()
        _mk_bill(db, org_id, total=1000, days_ago=1)
        _mk_txn(db, org_id, amount=-1000, days_ago=0)
        _mk_txn(db, org_id, amount=-300, days_ago=0)
        _mk_txn(db, org_id, amount=-450, description="חיוב ישראכרט", days_ago=0)
        db.commit()

        report = svc.gap_report(db, org_id, today.year, today.month)
        totals = report["totals"]
        excluded_sum = sum(b["total"] for b in totals["excluded_by_class"].values())
        assert round(totals["documented_total"] + totals["undocumented_total"] + excluded_sum, 2) == totals["total_bank_outflow"]
    finally:
        db.close()


def test_gap_report_potential_vat_computed_on_undocumented(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        today = date.today()
        _mk_txn(db, org_id, amount=-1180, description="ללא מסמך", days_ago=0)
        db.commit()
        report = svc.gap_report(db, org_id, today.year, today.month)
        assert report["totals"]["undocumented_total"] == 1180.0
        assert report["totals"]["potential_vat"] == round(1180 * 0.18 / 1.18, 2)
    finally:
        db.close()


def test_gap_report_inflows_without_invoice(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        today = date.today()
        _mk_txn(db, org_id, amount=2500, description="תקבול ללא חשבונית", days_ago=0)
        db.commit()
        report = svc.gap_report(db, org_id, today.year, today.month)
        assert report["inflows"]["undocumented_total"] == 2500.0
        assert report["inflows"]["undocumented_count"] == 1
    finally:
        db.close()


# --------------------------------------------------------------------- #
# scan_and_alert
# --------------------------------------------------------------------- #
def test_scan_and_alert_creates_insight_for_undocumented_expense(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _mk_txn(db, org_id, amount=-777, description="ספק ג ללא חשבונית", days_ago=1)
        db.commit()

        result = svc.scan_and_alert(db, org_id, lookback_days=14)
        assert result["created"] == 1
        assert result["skipped_existing"] == 0

        insights = db.query(CfoInsight).filter(
            CfoInsight.organization_id == org_id, CfoInsight.insight_type == "missing_document",
        ).all()
        assert len(insights) == 1
        assert "777" in insights[0].title or "777.00" in insights[0].title
        assert insights[0].status == "active"
    finally:
        db.close()


def test_scan_and_alert_does_not_duplicate_on_second_run(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _mk_txn(db, org_id, amount=-777, description="ספק ד ללא חשבונית", days_ago=1)
        db.commit()

        first = svc.scan_and_alert(db, org_id, lookback_days=14)
        second = svc.scan_and_alert(db, org_id, lookback_days=14)
        assert first["created"] == 1
        assert second["created"] == 0
        assert second["skipped_existing"] == 1

        count = db.query(CfoInsight).filter(
            CfoInsight.organization_id == org_id, CfoInsight.insight_type == "missing_document",
        ).count()
        assert count == 1
    finally:
        db.close()


def test_scan_and_alert_skips_documented_and_excluded_transactions(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _mk_bill(db, org_id, total=600, days_ago=1)
        _mk_txn(db, org_id, amount=-600, days_ago=0)  # documented -> no alert
        _mk_txn(db, org_id, amount=-200, description="חיוב ויזה", days_ago=0)  # excluded -> no alert
        db.commit()

        result = svc.scan_and_alert(db, org_id, lookback_days=14)
        assert result["created"] == 0
        assert result["scanned"] == 2
    finally:
        db.close()


# --------------------------------------------------------------------- #
# route
# --------------------------------------------------------------------- #
def test_bank_expense_gap_route_requires_auth(client):
    r = client.get("/api/daily-reports/bank-expense-gap?year=2026&month=6")
    assert r.status_code == 403


def test_bank_expense_gap_route_returns_expected_shape(client, fresh_org):
    org = fresh_org()
    db = SessionLocal()
    try:
        today = date.today()
        _mk_txn(db, org["org_id"], amount=-500, description="הוצאה בלי מסמך", days_ago=0)
        db.commit()
    finally:
        db.close()

    today = date.today()
    r = client.get(
        f"/api/daily-reports/bank-expense-gap?year={today.year}&month={today.month}",
        headers=org["headers"],
    )
    assert r.status_code == 200
    body = r.json()
    assert "transactions" in body
    assert "totals" in body
    assert "undocumented_total" in body["totals"]
    assert "inflows" in body


# --------------------------------------------------------------------- #
# cron
# --------------------------------------------------------------------- #
def test_cron_bank_gap_scan_requires_secret(client):
    r = client.get("/api/cron/bank-gap-scan")
    assert r.status_code in (401, 403)


def test_cron_bank_gap_scan_runs_for_active_orgs(client, fresh_org, monkeypatch):
    from cfo.config import settings
    monkeypatch.setattr(settings, "cron_secret", "testsecret", raising=False)

    org = fresh_org()
    db = SessionLocal()
    try:
        _mk_txn(db, org["org_id"], amount=-640, description="הוצאה לסריקת cron", days_ago=1)
        db.commit()
    finally:
        db.close()

    r = client.get("/api/cron/bank-gap-scan", headers={"Authorization": "Bearer testsecret"})
    assert r.status_code == 200
    body = r.json()
    assert "summary" in body
    assert body["summary"]["created"] >= 1
    assert body["errors"] == []


def test_classify_bank_transfer_stays_expense_candidate():
    """תשלום לספק בהעברה בנקאית מסווג ב-OF כ-TRANSFER/BANK_TRANSFER —
    אסור להחריג אותו כהעברה עצמית (רגרסיה: שכ"ט עו"ד ₪11,800 בהעברה)."""
    txn = BankTransaction(
        amount=Decimal("-11800"), description="העברה לבנק אחר",
        raw_data={"category": {"main": "TRANSFER", "sub": "BANK_TRANSFER"}},
    )
    assert svc.classify_transaction(txn) == "expense_candidate"
