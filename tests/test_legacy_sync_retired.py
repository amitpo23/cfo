"""DataSyncService.sync_documents/sync_payments/sync_billing_transactions כותבות
Transaction עם amount=doc.total (מנופח, כולל מע"מ) -- הנתיב ההיסטורי-שבור מאחורי
ממצא ה-P0 "שתי מערכות חשבונאות מקבילות" (ר' PRODUCT_AUDIT_AND_ROADMAP.md).
run_post_sync_tasks כבר לא קורא ל-sync_all() (ר' test_client_automation_service.py),
אבל /api/sync/sumit/full ושלושת נתיבי-הכתיבה הישירים עדיין רשומים וחיים -- ה-UI
היחיד שקרא להם (DataSyncDashboard.tsx) יתום לגמרי (אפס הפניות ב-App.tsx), כך
שההקפאה היום היא נסיבתית (אין קורא), לא אכיפה בקוד. אם מישהו יקרא ישירות ל-route
הזה (script/Postman/UI עתידי), Transaction יתחיל לגדול שוב ויחזיר את הפיצול
המתועד. מוסיפים אכיפה בקוד: קריאה ישירה חוסמת עם 400 כן, מפנה לנתיב הקנוני
(SyncEngine / /office/clients/{id}/sync)."""
import pytest


def test_sync_documents_route_blocked(client, owner):
    resp = client.post("/api/sync/sumit/documents", json={}, headers=owner["headers"])
    assert resp.status_code == 400, resp.text
    assert "sync_engine" in resp.json()["detail"].lower() or "syncengine" in resp.json()["detail"].lower()


def test_sync_payments_route_blocked(client, owner):
    resp = client.post("/api/sync/sumit/payments", json={}, headers=owner["headers"])
    assert resp.status_code == 400, resp.text


def test_sync_billing_route_blocked(client, owner):
    resp = client.post("/api/sync/sumit/billing", json={}, headers=owner["headers"])
    assert resp.status_code == 400, resp.text


def test_sync_full_route_blocked(client, owner):
    resp = client.post("/api/sync/sumit/full", json={}, headers=owner["headers"])
    assert resp.status_code == 400, resp.text


def test_service_methods_raise_directly():
    """גם קריאה ישירה לשירות (לא רק דרך ה-route) חסומה -- הגנה בכל הרבדים."""
    import asyncio
    from cfo.database import SessionLocal
    from cfo.services.data_sync_service import DataSyncService, LegacySyncRetiredError

    async def _run():
        db = SessionLocal()
        try:
            service = DataSyncService(db, organization_id=1)
            with pytest.raises(LegacySyncRetiredError):
                await service.sync_documents()
            with pytest.raises(LegacySyncRetiredError):
                await service.sync_payments()
            with pytest.raises(LegacySyncRetiredError):
                await service.sync_billing_transactions()
        finally:
            db.close()

    asyncio.run(_run())


def test_read_only_sync_routes_still_work(client, owner, monkeypatch):
    """הבלוק חל רק על נתיבי-כתיבה (Transaction) -- get_vat_rate/get_exchange_rate
    נשארים פונקציונליים כרגיל (read-through ל-SUMIT, אין כתיבת Transaction)."""
    from cfo.services.data_sync_service import DataSyncService

    async def _fake_vat_rate(self, for_date=None):
        return 0.18

    monkeypatch.setattr(DataSyncService, "get_vat_rate", _fake_vat_rate)
    resp = client.get("/api/sync/sumit/vat-rate", headers=owner["headers"])
    assert resp.status_code == 200, resp.text
