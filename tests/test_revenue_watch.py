"""גלאי דממת/צניחת הכנסות — הפער מס' 1 מחקירת 20/08.

הדוגמה של הבעלים: "למה אין הכנסות מחודש מרץ?" — עד היום אף גלאי לא ידע
לשאול את זה. `grep revenue_drop|no_revenue` על src/cfo החזיר 0 תוצאות.
"""
from datetime import date, timedelta
from decimal import Decimal

import pytest

from cfo.database import SessionLocal
from cfo.models import CfoInsight, Invoice, InvoiceStatus
from cfo.services import revenue_watch


@pytest.fixture(autouse=True)
def _clean(client, fresh_org):
    yield


def _invoice(db, org_id, issue_date, total=1000):
    inv = Invoice(
        organization_id=org_id,
        invoice_number=f"T-{org_id}-{issue_date.isoformat()}",
        issue_date=issue_date,
        due_date=issue_date,
        total=Decimal(str(total)),
        status=InvoiceStatus.SENT,
    )
    db.add(inv)
    return inv


def test_long_revenue_silence_creates_a_high_insight(fresh_org):
    """אין מסמך הכנסה 60 יום — נוצרת תובנה עם התאריך האחרון והשאלה."""
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _invoice(db, org_id, date.today() - timedelta(days=60))
        db.commit()

        result = revenue_watch.scan_and_alert(db, org_id, today=date.today())
        assert result["status"] == "silence"
        assert result["days_silent"] >= 59

        insight = db.query(CfoInsight).filter(
            CfoInsight.organization_id == org_id,
            CfoInsight.insight_type == "revenue_silence",
        ).first()
        assert insight is not None
        assert insight.severity in ("high", "critical")
        assert insight.status == "active"
    finally:
        db.close()


def test_recent_revenue_does_not_alert(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _invoice(db, org_id, date.today() - timedelta(days=5))
        db.commit()

        result = revenue_watch.scan_and_alert(db, org_id, today=date.today())
        assert result["status"] == "ok"
        assert db.query(CfoInsight).filter(
            CfoInsight.organization_id == org_id,
            CfoInsight.insight_type == "revenue_silence",
        ).count() == 0
    finally:
        db.close()


def test_no_revenue_history_is_honest_null_not_alert(fresh_org):
    """ארגון בלי אף חשבונית מעולם — אין בסיס לקבוע 'דממה'; honest-null."""
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        result = revenue_watch.scan_and_alert(db, org_id, today=date.today())
        assert result["status"] == "no_history"
        assert db.query(CfoInsight).filter(
            CfoInsight.organization_id == org_id,
            CfoInsight.insight_type == "revenue_silence",
        ).count() == 0
    finally:
        db.close()


def test_rescan_updates_the_same_insight_not_a_duplicate(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _invoice(db, org_id, date.today() - timedelta(days=90))
        db.commit()

        revenue_watch.scan_and_alert(db, org_id, today=date.today())
        revenue_watch.scan_and_alert(db, org_id, today=date.today())

        assert db.query(CfoInsight).filter(
            CfoInsight.organization_id == org_id,
            CfoInsight.insight_type == "revenue_silence",
        ).count() == 1
    finally:
        db.close()
