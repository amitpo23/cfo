"""W6.1 — המערכת יודעת לגלות שהיא שבורה (SWOT: הציר החלש ביותר).

הפערים: אין handler גנרי ל-500 (traceback נעלם ב-stdout), ‏health check
מחזיר מחרוזת קבועה גם כשה-DB מת, ואין מונה כשלים שאפשר לשאול.
"""
import pytest

from cfo.database import SessionLocal
from cfo.services import system_health


@pytest.fixture(autouse=True)
def _clean(client):
    db = SessionLocal()
    try:
        from cfo.models import ProviderRequestBudget

        db.query(ProviderRequestBudget).filter(
            ProviderRequestBudget.provider == "system",
        ).delete()
        db.commit()
        yield
    finally:
        db.close()


def test_record_system_error_increments_a_durable_daily_counter():
    system_health.record_system_error_best_effort(path="/api/boom")
    system_health.record_system_error_best_effort(path="/api/boom")
    assert system_health.todays_error_count() == 2


def test_unhandled_exception_returns_500_and_is_counted(client, fresh_org):
    """חריגה לא-מטופלת: המשתמש מקבל 500 כן (בלי traceback), והמונה עולה —
    כך שה-health חושף שהמערכת נשברה גם כשאיש לא הסתכל בלוגים."""
    from fastapi.testclient import TestClient

    from cfo.api import app

    @app.get("/api/_test_boom")
    async def _boom():
        raise RuntimeError("secret internal detail")

    before = system_health.todays_error_count()
    # ה-client הרגיל של הטסטים מרים חריגות שרת מחדש; כאן בודקים את
    # ההתנהגות שהמשתמש האמיתי רואה — ה-handler הגנרי.
    with TestClient(app, raise_server_exceptions=False) as real_client:
        r = real_client.get("/api/_test_boom")
    assert r.status_code == 500
    body = r.json()
    assert "secret internal detail" not in str(body)
    assert system_health.todays_error_count() == before + 1


def test_health_endpoint_reports_real_signals(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["database"] == "ok"
    assert body["alembic_revision"]  # לא ריק — נקרא מ-alembic_version
    assert "errors_today" in body
    assert body["status"] in ("healthy", "degraded")


def test_health_degrades_when_errors_pile_up(client):
    for _ in range(3):
        system_health.record_system_error_best_effort(path="/x")
    r = client.get("/api/health")
    assert r.json()["errors_today"] >= 3
