"""אבטחת ריבוי-דיירים: monthly-report/extended-securities אינם תומכים
ב-connectionId (מאומת מול ה-OpenAPI spec — סעיף Reports/Monthly-report
במיפוי הכיסוי, 2026-07-12) — הם מוחזרים מצטברים לפי userId בלבד. כשכמה
ארגונים חולקים אותו userId ב-Financy (מקרה חי: org1+org2 מחוברים תחת
אותו userId אמיתי של Financy), קריאה אליהם הייתה מחזירה נתונים ממוזגים
משני התיקים — דליפה חוצת-לקוחות. חייבים לסרב בכנות, לא לסנן (אין מה
לסנן — הם מצרפים כבר בשרת הספק)."""
from cfo.database import SessionLocal
from cfo.models import IntegrationConnection
from cfo.services.credentials_vault import encrypt_credentials


def _configure_of(org_id, user_id):
    db = SessionLocal()
    try:
        db.add(IntegrationConnection(
            organization_id=org_id, source="open_finance", status="active",
            credentials_encrypted=encrypt_credentials({
                "client_id": "cid", "client_secret": "sec", "user_id": user_id,
            }),
        ))
        db.commit()
    finally:
        db.close()


def test_monthly_report_blocked_when_userid_shared_with_another_org(client, fresh_org):
    org_a = fresh_org(); org_b = fresh_org()
    _configure_of(org_a["org_id"], "shared-financy-user")
    _configure_of(org_b["org_id"], "shared-financy-user")

    r = client.get("/api/open-finance/monthly-report", headers=org_a["headers"])
    assert r.status_code == 409
    assert "משותף" in r.json()["detail"]


def test_securities_blocked_when_userid_shared_with_another_org(client, fresh_org):
    org_a = fresh_org(); org_b = fresh_org()
    _configure_of(org_a["org_id"], "shared-financy-user-2")
    _configure_of(org_b["org_id"], "shared-financy-user-2")

    r = client.get("/api/open-finance/securities", headers=org_a["headers"])
    assert r.status_code == 409


def test_monthly_report_allowed_when_userid_not_shared(client, fresh_org, monkeypatch):
    from cfo.services.open_finance_client import OpenFinanceClient

    org_a = fresh_org(); org_b = fresh_org()
    _configure_of(org_a["org_id"], "solo-user-a")
    _configure_of(org_b["org_id"], "solo-user-b")

    async def fake_report(self, user_id=None):
        return {"openBankingReportId": "r1"}
    monkeypatch.setattr(OpenFinanceClient, "get_monthly_report", fake_report)

    r = client.get("/api/open-finance/monthly-report", headers=org_a["headers"])
    assert r.status_code == 200


def test_insights_generate_skips_enrichment_gracefully_when_shared(client, fresh_org):
    org_a = fresh_org(); org_b = fresh_org()
    _configure_of(org_a["org_id"], "shared-financy-user-3")
    _configure_of(org_b["org_id"], "shared-financy-user-3")

    r = client.post("/api/open-finance/insights/generate", headers=org_a["headers"])
    assert r.status_code == 200


def test_shared_identity_check_ignores_other_sources_and_inactive_rows(client, fresh_org):
    """ארגון עם SUMIT בלבד, או OF לא-פעיל, לא נספר כ'שותף'."""
    org_a = fresh_org(); org_b = fresh_org()
    _configure_of(org_a["org_id"], "unique-user-x")
    db = SessionLocal()
    try:
        db.add(IntegrationConnection(
            organization_id=org_b["org_id"], source="open_finance", status="inactive",
            credentials_encrypted=encrypt_credentials({
                "client_id": "cid", "client_secret": "sec", "user_id": "unique-user-x",
            }),
        ))
        db.commit()
    finally:
        db.close()

    from cfo.api.routes.open_finance import _has_shared_of_identity
    from cfo.database import SessionLocal as SL
    check_db = SL()
    try:
        assert _has_shared_of_identity(check_db, org_a["org_id"]) is False
    finally:
        check_db.close()
