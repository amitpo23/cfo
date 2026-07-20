"""PR2 of the bookkeeper daily-cycle plan — morning bank-anomaly scan.

Scans BankTransaction rows for bounced checks, failed standing orders, and
returned debits/refused-payment fees (folded into `returned_debit` — the
3-kind taxonomy has no dedicated bucket for the generic fee wording), and
raises a CfoInsight (insight_type="bank_anomaly") per hit, deduped by
fingerprint on the transaction id.

Written TDD-first: this file existed before src/cfo/services/bank_anomalies.py.
"""
from datetime import date, timedelta
from decimal import Decimal

from cfo.database import SessionLocal
from cfo.models import BankTransaction, CfoInsight
from cfo.services import bank_anomalies as svc


def _mk_txn(db, org_id, *, amount, description, days_ago=1):
    t = BankTransaction(
        organization_id=org_id,
        transaction_date=date.today() - timedelta(days=days_ago),
        description=description, amount=Decimal(str(amount)), currency="ILS",
    )
    db.add(t)
    db.flush()
    return t


# --------------------------------------------------------------------- #
# scan_bank_anomalies — keyword classes
# --------------------------------------------------------------------- #
def test_detects_bounced_check(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _mk_txn(db, org_id, amount=3000, description="שיק חוזר מלקוח")
        db.commit()

        hits = svc.scan_bank_anomalies(db, org_id, since=date.today() - timedelta(days=7))
        assert len(hits) == 1
        assert hits[0]["kind"] == "bounced_check"
    finally:
        db.close()


def test_detects_bounced_check_variant_wording(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _mk_txn(db, org_id, amount=1200, description="  החזרת   שיק   ")
        db.commit()

        hits = svc.scan_bank_anomalies(db, org_id, since=date.today() - timedelta(days=7))
        assert len(hits) == 1
        assert hits[0]["kind"] == "bounced_check"
    finally:
        db.close()


def test_detects_failed_standing_order(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _mk_txn(db, org_id, amount=-450, description="הוראת קבע שלא כובדה - ספק חשמל")
        db.commit()

        hits = svc.scan_bank_anomalies(db, org_id, since=date.today() - timedelta(days=7))
        assert len(hits) == 1
        assert hits[0]["kind"] == "failed_standing_order"
    finally:
        db.close()


def test_detects_returned_debit(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _mk_txn(db, org_id, amount=-800, description="החזרת חיוב כרטיס אשראי")
        db.commit()

        hits = svc.scan_bank_anomalies(db, org_id, since=date.today() - timedelta(days=7))
        assert len(hits) == 1
        assert hits[0]["kind"] == "returned_debit"
    finally:
        db.close()


def test_detects_refused_payment_fee_as_returned_debit(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _mk_txn(db, org_id, amount=-25, description="עמלת החזרה")
        db.commit()

        hits = svc.scan_bank_anomalies(db, org_id, since=date.today() - timedelta(days=7))
        assert len(hits) == 1
        assert hits[0]["kind"] == "returned_debit"
    finally:
        db.close()


def test_clean_transactions_are_ignored(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _mk_txn(db, org_id, amount=-100, description="קניה בסופר")
        _mk_txn(db, org_id, amount=5000, description="תקבול מלקוח")
        db.commit()

        hits = svc.scan_bank_anomalies(db, org_id, since=date.today() - timedelta(days=7))
        assert hits == []
    finally:
        db.close()


def test_since_filters_out_older_transactions(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _mk_txn(db, org_id, amount=3000, description="שיק חוזר", days_ago=30)
        db.commit()

        hits = svc.scan_bank_anomalies(db, org_id, since=date.today() - timedelta(days=7))
        assert hits == []
    finally:
        db.close()


# --------------------------------------------------------------------- #
# scan_and_alert
# --------------------------------------------------------------------- #
def test_scan_and_alert_creates_insight(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        txn = _mk_txn(db, org_id, amount=3000, description="שיק חוזר מלקוח")
        db.commit()

        result = svc.scan_and_alert(db, org_id, since=date.today() - timedelta(days=7))
        assert result["created"] == 1

        insight = db.query(CfoInsight).filter(
            CfoInsight.organization_id == org_id,
            CfoInsight.insight_type == "bank_anomaly",
        ).first()
        assert insight is not None
        assert insight.fingerprint == f"bank_anomaly:{txn.id}"
        assert any("֐" <= ch <= "׿" for ch in insight.title)
    finally:
        db.close()


def test_scan_and_alert_dedups_on_double_run(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _mk_txn(db, org_id, amount=3000, description="שיק חוזר מלקוח")
        db.commit()

        svc.scan_and_alert(db, org_id, since=date.today() - timedelta(days=7))
        svc.scan_and_alert(db, org_id, since=date.today() - timedelta(days=7))

        rows = db.query(CfoInsight).filter(
            CfoInsight.organization_id == org_id,
            CfoInsight.insight_type == "bank_anomaly",
        ).all()
        assert len(rows) == 1
    finally:
        db.close()


def test_severity_escalates_above_5000_for_bounced_check(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        txn = _mk_txn(db, org_id, amount=6000, description="שיק חוזר מלקוח")
        db.commit()

        svc.scan_and_alert(db, org_id, since=date.today() - timedelta(days=7))

        insight = db.query(CfoInsight).filter(
            CfoInsight.organization_id == org_id,
            CfoInsight.fingerprint == f"bank_anomaly:{txn.id}",
        ).first()
        assert insight.severity == "critical"
    finally:
        db.close()


def test_severity_stays_high_at_or_below_5000_for_bounced_check(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        txn = _mk_txn(db, org_id, amount=5000, description="שיק חוזר מלקוח")
        db.commit()

        svc.scan_and_alert(db, org_id, since=date.today() - timedelta(days=7))

        insight = db.query(CfoInsight).filter(
            CfoInsight.organization_id == org_id,
            CfoInsight.fingerprint == f"bank_anomaly:{txn.id}",
        ).first()
        assert insight.severity == "high"
    finally:
        db.close()


def test_severity_high_for_non_bounced_kinds_regardless_of_amount(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        txn = _mk_txn(db, org_id, amount=-9000, description="הוראת קבע שלא כובדה")
        db.commit()

        svc.scan_and_alert(db, org_id, since=date.today() - timedelta(days=7))

        insight = db.query(CfoInsight).filter(
            CfoInsight.organization_id == org_id,
            CfoInsight.fingerprint == f"bank_anomaly:{txn.id}",
        ).first()
        assert insight.severity == "high"
    finally:
        db.close()
