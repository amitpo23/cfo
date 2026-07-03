"""כשל upstream (SUMIT וכו') חייב להחזיר 503 כן — לא 500 גולמי."""
import asyncio

import httpx


def test_httpx_error_returns_503_not_500(client, owner, monkeypatch):
    """מפילים את קריאת ה-upstream ובודקים שהתשובה 503 עם detail ברור."""
    from cfo.integrations.sumit_integration import SumitIntegration

    async def _boom(self, *a, **k):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(SumitIntegration, "list_documents", _boom)
    resp = client.get("/api/accounting/documents", headers=owner["headers"])
    assert resp.status_code == 503
    assert "upstream" in resp.json()["detail"].lower()


def test_sync_route_without_sumit_configured_returns_400_not_500(client, fresh_org, monkeypatch):
    """DataSyncService._get_sumit נקרא ישירות מנתיבי /api/sync/sumit/* (בלי
    Depends(get_sumit_integration)). ללא מפתח SUMIT מוגדר לארגון וללא env
    fallback, זו הייתה מתפוצצת ל-500 גולמי (ValueError לא-מטופל). מצפים ל-400
    נקי, כמו כל שאר נתיבי ה-SUMIT."""
    import cfo.config as config_module

    # מסירים את ה-env fallback כדי שהארגון הטרי (בלי api_credentials) לא ימצא מפתח בכלל.
    monkeypatch.setattr(config_module.settings, "sumit_api_key", None)

    org = fresh_org()
    resp = client.get("/api/sync/sumit/vat-rate", headers=org["headers"])
    assert resp.status_code == 400, resp.text
    assert "sumit" in resp.json()["detail"].lower()


def test_data_sync_service_env_fallback_blocked_for_non_default_org(fresh_org, monkeypatch):
    """DataSyncService._get_sumit היה נופל חזרה למפתח ה-env של הארגון ברירת
    המחדל (org 1) עבור כל ארגון חסר-קרדנציאלס — דליפת קרדנציאלס בין דיירים.
    עם שער env_allowed = organization_id == 1 (כמו ב-get_sumit_integration
    וב-get_connector_for_org), ארגון אחר חייב SumitNotConfiguredError גם אם
    יש מפתח env מוגדר."""
    import cfo.config as config_module
    from cfo.database import SessionLocal
    from cfo.services.data_sync_service import DataSyncService, SumitNotConfiguredError

    monkeypatch.setattr(config_module.settings, "sumit_api_key", "fake-env-key-should-not-leak")

    org_id = fresh_org()["org_id"]

    async def _run():
        db = SessionLocal()
        try:
            service = DataSyncService(db, organization_id=org_id)
            await service._get_sumit()
        finally:
            db.close()

    try:
        asyncio.run(_run())
        raised = None
    except SumitNotConfiguredError as e:
        raised = e

    assert raised is not None, "expected SumitNotConfiguredError, env creds leaked to another org"


def test_data_sync_service_env_fallback_still_works_for_default_org(owner, monkeypatch):
    """אין רגרסיה: ארגון ברירת המחדל (org 1) עדיין יכול ליפול חזרה למפתח ה-env,
    בדיוק כמו ב-get_sumit_integration/get_connector_for_org."""
    import cfo.config as config_module
    from cfo.database import SessionLocal
    from cfo.services.data_sync_service import DataSyncService

    monkeypatch.setattr(config_module.settings, "sumit_api_key", "fake-env-key-for-default-org")

    org_id = owner["user"]["organization_id"]

    async def _run():
        db = SessionLocal()
        try:
            service = DataSyncService(db, organization_id=org_id)
            return await service._get_sumit()
        finally:
            db.close()

    integration = asyncio.run(_run())
    assert integration is not None
    assert integration.api_key == "fake-env-key-for-default-org"


def test_post_binary_upstream_4xx_raises_sumit_api_error():
    """_post_binary (הורדת PDF) חייב לעטוף 4xx/5xx כ-SumitAPIError, בדיוק כמו
    _make_request — אחרת יוצא httpx.HTTPStatusError לא-מטופל בשכבת ה-service."""
    from cfo.integrations.sumit_integration import SumitIntegration, SumitAPIError

    async def _run():
        sumit = SumitIntegration(api_key="test-key", company_id="1")
        try:
            async def _fake_post(url, json=None, **kwargs):
                request = httpx.Request("POST", "https://api.sumit.co.il" + url)
                return httpx.Response(404, request=request, text="Not Found")

            sumit.client.post = _fake_post

            try:
                await sumit._post_binary("/accounting/documents/getpdf/", {"DocumentID": 1})
                raised = None
            except Exception as e:  # noqa: BLE001
                raised = e

            assert raised is not None, "expected an exception to be raised"
            assert isinstance(raised, SumitAPIError), f"expected SumitAPIError, got {type(raised)}"
        finally:
            await sumit.client.aclose()

    asyncio.run(_run())
