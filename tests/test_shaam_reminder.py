"""תזכורת מחזורית לחידוש חיבור רשות המסים (שע"מ) — פג כל 3 חודשים לפי
מרכז הידע (docs/SUMIT_KNOWLEDGE_BASE.md). ראה services/shaam_reminder.py."""
from datetime import date

from cfo.database import SessionLocal
from cfo.models import CfoInsight
from cfo.services.shaam_reminder import ensure_shaam_renewal_reminder


def test_creates_insight_with_expected_fields(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        result = ensure_shaam_renewal_reminder(db, org_id, today=date(2026, 7, 13))
        assert result["created"] is True
        assert result["quarter"] == "2026-Q3"

        row = db.query(CfoInsight).filter(
            CfoInsight.organization_id == org_id,
            CfoInsight.insight_type == "shaam_renewal",
        ).first()
        assert row is not None
        assert row.fingerprint == f"shaam_renewal:{org_id}:2026-Q3"
        assert row.severity == "high"
        assert "חידוש חיבור רשות המסים" in row.title
        assert "/accounting/shaamstatus" in (row.recommended_action or "")
    finally:
        db.close()


def test_dedup_same_quarter_does_not_duplicate(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        r1 = ensure_shaam_renewal_reminder(db, org_id, today=date(2026, 7, 1))
        r2 = ensure_shaam_renewal_reminder(db, org_id, today=date(2026, 9, 30))  # אותו רבעון (Q3)
        assert r1["created"] is True
        assert r2["created"] is False
        assert r1["insight_id"] == r2["insight_id"]

        count = db.query(CfoInsight).filter(
            CfoInsight.organization_id == org_id,
            CfoInsight.insight_type == "shaam_renewal",
        ).count()
        assert count == 1
    finally:
        db.close()


def test_new_quarter_creates_new_insight(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        ensure_shaam_renewal_reminder(db, org_id, today=date(2026, 7, 13))   # Q3
        ensure_shaam_renewal_reminder(db, org_id, today=date(2026, 10, 1))  # Q4

        rows = db.query(CfoInsight).filter(
            CfoInsight.organization_id == org_id,
            CfoInsight.insight_type == "shaam_renewal",
        ).all()
        assert len(rows) == 2
        fingerprints = {r.fingerprint for r in rows}
        assert fingerprints == {
            f"shaam_renewal:{org_id}:2026-Q3",
            f"shaam_renewal:{org_id}:2026-Q4",
        }
    finally:
        db.close()


def test_daily_close_cron_creates_shaam_reminder_per_org(client, fresh_org, monkeypatch):
    """אינטגרציה: /api/cron/daily-close חייב לקרוא לתזכורת שע"מ פר-ארגון,
    עם בידוד כשלים (כמו שאר השירותים באותו cron)."""
    from cfo.config import settings
    monkeypatch.setattr(settings, "cron_secret", "testsecret", raising=False)

    org_id = fresh_org()["org_id"]
    r = client.get("/api/cron/daily-close", headers={"Authorization": "Bearer testsecret"})
    assert r.status_code == 200

    db = SessionLocal()
    try:
        row = db.query(CfoInsight).filter(
            CfoInsight.organization_id == org_id,
            CfoInsight.insight_type == "shaam_renewal",
        ).first()
        assert row is not None
    finally:
        db.close()


def test_daily_close_cron_isolates_shaam_failure(client, fresh_org, monkeypatch):
    """כשל בתזכורת השע"מ של ארגון אחד לא מפיל את שאר הריצה (לא את הסנכרון
    היומי של אותו ארגון ולא את הריצה עבור ארגונים אחרים)."""
    from cfo.config import settings
    from cfo.models import DailySnapshot
    monkeypatch.setattr(settings, "cron_secret", "testsecret", raising=False)

    org_a = fresh_org()["org_id"]
    org_b = fresh_org()["org_id"]

    import cfo.services.shaam_reminder as shaam_module
    original = shaam_module.ensure_shaam_renewal_reminder

    def _boom(db, org_id, **kw):
        if org_id == org_a:
            raise RuntimeError("boom")
        return original(db, org_id, **kw)

    monkeypatch.setattr(shaam_module, "ensure_shaam_renewal_reminder", _boom)
    monkeypatch.setattr("cfo.api.routes.cron.ensure_shaam_renewal_reminder", _boom)

    r = client.get("/api/cron/daily-close", headers={"Authorization": "Bearer testsecret"})
    assert r.status_code == 200

    db = SessionLocal()
    try:
        # הסנכרון היומי עצמו (daily_snapshots) לא נפגע מכשל התזכורת.
        snap_a = db.query(DailySnapshot).filter(
            DailySnapshot.organization_id == org_a,
            DailySnapshot.snapshot_date == date.today(),
        ).first()
        assert snap_a is not None

        row_b = db.query(CfoInsight).filter(
            CfoInsight.organization_id == org_b,
            CfoInsight.insight_type == "shaam_renewal",
        ).first()
        assert row_b is not None
    finally:
        db.close()
