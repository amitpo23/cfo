"""GET /api/cron/daily-close — סגירה יומית: מריץ data_quality ושומר
daily_snapshots פר-org, אידמפוטנטי (unique על org+snapshot_date).
"""
from datetime import date
from decimal import Decimal

from cfo.database import SessionLocal


def test_cron_daily_close_requires_secret(client):
    r = client.get("/api/cron/daily-close")
    assert r.status_code in (401, 403)


def test_cron_daily_close_creates_snapshot_for_active_org(client, fresh_org, monkeypatch):
    from cfo.config import settings
    monkeypatch.setattr(settings, "cron_secret", "testsecret", raising=False)

    org = fresh_org()
    org_id = org["org_id"]

    db = SessionLocal()
    try:
        from cfo.models import Contact, ContactType, Invoice, InvoiceStatus
        cust = Contact(organization_id=org_id, contact_type=ContactType.CUSTOMER, name="לקוח")
        db.add(cust)
        db.flush()
        db.add(Invoice(organization_id=org_id, contact_id=cust.id, invoice_number="I1",
                       issue_date=date.today(), status=InvoiceStatus.SENT,
                       total=1000, paid_amount=0, balance=1000))
        db.commit()
    finally:
        db.close()

    r = client.get("/api/cron/daily-close", headers={"Authorization": "Bearer testsecret"})
    assert r.status_code == 200
    body = r.json()
    assert body["errors"] == []

    db = SessionLocal()
    try:
        from cfo.models import DailySnapshot
        snap = db.query(DailySnapshot).filter(
            DailySnapshot.organization_id == org_id,
            DailySnapshot.snapshot_date == date.today(),
        ).first()
        assert snap is not None
        assert float(snap.ar_total) == 1000.0
        assert snap.data_quality_issues is not None
    finally:
        db.close()


def test_cron_daily_close_is_idempotent_same_day(client, fresh_org, monkeypatch):
    from cfo.config import settings
    monkeypatch.setattr(settings, "cron_secret", "testsecret", raising=False)

    org_id = fresh_org()["org_id"]
    headers = {"Authorization": "Bearer testsecret"}

    r1 = client.get("/api/cron/daily-close", headers=headers)
    assert r1.status_code == 200
    r2 = client.get("/api/cron/daily-close", headers=headers)
    assert r2.status_code == 200

    db = SessionLocal()
    try:
        from cfo.models import DailySnapshot
        count = db.query(DailySnapshot).filter(
            DailySnapshot.organization_id == org_id,
            DailySnapshot.snapshot_date == date.today(),
        ).count()
        assert count == 1  # לא נוצרה שורה כפולה — עדכון UPSERT
    finally:
        db.close()


def test_cron_daily_close_isolates_per_org_failure(client, fresh_org, monkeypatch):
    """כשל בארגון אחד לא מפיל את הריצה עבור אחרים."""
    from cfo.config import settings
    monkeypatch.setattr(settings, "cron_secret", "testsecret", raising=False)

    org_a = fresh_org()["org_id"]
    org_b = fresh_org()["org_id"]

    import cfo.services.dashboard_service as ds_module
    original = ds_module.DashboardService.get_overview

    def _boom(self, today=None):
        if self.org_id == org_a:
            raise RuntimeError("boom")
        return original(self, today=today)

    monkeypatch.setattr(ds_module.DashboardService, "get_overview", _boom)

    r = client.get("/api/cron/daily-close", headers={"Authorization": "Bearer testsecret"})
    assert r.status_code == 200
    body = r.json()
    assert any(e["org"] == org_a for e in body["errors"])

    db = SessionLocal()
    try:
        from cfo.models import DailySnapshot
        snap_b = db.query(DailySnapshot).filter(
            DailySnapshot.organization_id == org_b,
            DailySnapshot.snapshot_date == date.today(),
        ).first()
        assert snap_b is not None  # org_b עדיין נשמר
    finally:
        db.close()
