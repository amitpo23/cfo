"""השכבה הפרואקטיבית של מושקו — פערים 1+3+5 מחקירת 20/08.

הדוגמה של הבעלים: מושקו צריך לפתוח שיחה ב"שים לב — אין הכנסות ממרץ,
והתזרים הצפוי שלילי" ולשאול עליהם — לא לחכות שישאלו אותו.

המנגנון: בתחילת session (אין היסטוריה) נבנה בלוק דגלים אדומים —
תובנות active בחומרה גבוהה + דממת הכנסות + תזרים מצטבר שלילי — ומוזרק
ל-system prompt עם הוראה לפתוח בו ולשאול. אפס קריאות API — הכל מקומי.
"""
from datetime import date, timedelta
from decimal import Decimal

import pytest

from cfo.database import SessionLocal
from cfo.models import CfoInsight, Invoice, InvoiceStatus
from cfo.services.ai_chat_service import AIChatService


@pytest.fixture(autouse=True)
def _clean(client, fresh_org):
    yield


def _svc(db, org_id):
    return AIChatService(db, org_id, 1, is_super_admin=False)


def test_flags_block_includes_active_high_insights(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        db.add(CfoInsight(
            organization_id=org_id, fingerprint=f"t:{org_id}",
            insight_type="revenue_silence", severity="high",
            title="אין מסמכי הכנסה מאז 01/03/2026 (172 ימים)",
            message="בדוק", status="active",
        ))
        db.commit()

        block = _svc(db, org_id)._build_proactive_flags()
        assert "אין מסמכי הכנסה מאז 01/03/2026" in block
        assert "דגלים אדומים" in block
    finally:
        db.close()


def test_flags_block_detects_revenue_silence_even_without_stored_insight(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        db.add(Invoice(
            organization_id=org_id, invoice_number="R-1",
            issue_date=date.today() - timedelta(days=100),
            due_date=date.today() - timedelta(days=100),
            total=Decimal("500"), status=InvoiceStatus.PAID,
        ))
        db.commit()

        block = _svc(db, org_id)._build_proactive_flags()
        assert "אין מסמכי הכנסה" in block
    finally:
        db.close()


def test_quiet_org_yields_empty_block(fresh_org):
    """אין דגלים — אין בלוק; מושקו לא ימציא בעיות (honest-null)."""
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        db.add(Invoice(
            organization_id=org_id, invoice_number="R-2",
            issue_date=date.today() - timedelta(days=3),
            due_date=date.today(),
            total=Decimal("500"), status=InvoiceStatus.PAID,
        ))
        db.commit()
        assert _svc(db, org_id)._build_proactive_flags() == ""
    finally:
        db.close()


def test_morning_cycle_runs_revenue_watch_step(fresh_org):
    from cfo.services import morning_cycle_service as cycle

    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        result = cycle.run_morning_cycle(db, org_id, date.today(), force=True)
        assert "revenue_watch" in result["steps"]
    finally:
        db.close()


def test_manual_morning_cycle_route_refreshes_insights(client, fresh_org):
    """בלי crons — הכפתור הידני הוא הדרך של המשתמש לרענן את התובנות."""
    iso = fresh_org()
    r = client.post("/api/daily-reports/morning-cycle/run", headers=iso["headers"])
    assert r.status_code == 200, r.text
    body = r.json()
    assert "steps" in body and "revenue_watch" in body["steps"]
