"""בדיקות דוח מלאי: שערוך, מלאי נמוך/אזל, וסקופ ארגוני."""
import pytest


@pytest.fixture(scope="module")
def stock(owner):
    from cfo.database import SessionLocal
    from cfo.models import InventoryItem

    org_id = owner["user"]["organization_id"]
    db = SessionLocal()
    try:
        db.add_all([
            # תקין: 10 × 50 = 500
            InventoryItem(organization_id=org_id, name="פריט תקין", sku="A1",
                          quantity=10, unit_cost=50, reorder_level=3, source="manual"),
            # נמוך: כמות 2 <= סף 5
            InventoryItem(organization_id=org_id, name="פריט נמוך", sku="A2",
                          quantity=2, unit_cost=100, reorder_level=5, source="manual"),
            # אזל: כמות 0
            InventoryItem(organization_id=org_id, name="פריט אזל", sku="A3",
                          quantity=0, unit_cost=20, reorder_level=5, source="manual"),
        ])
        db.commit()
        return {"org_id": org_id}
    finally:
        db.close()


def test_inventory_report_requires_auth(client):
    assert client.get("/api/inventory/report").status_code == 403


def test_inventory_valuation_and_flags(client, owner, stock):
    resp = client.get("/api/inventory/report", headers=owner["headers"])
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    s = data["summary"]
    assert s["total_items"] == 3
    assert s["total_value"] == 500 + 200 + 0   # 10*50 + 2*100 + 0*20
    assert s["low_stock_count"] == 1
    assert s["out_of_stock_count"] == 1
    by_name = {r["name"]: r for r in data["items"]}
    assert by_name["פריט תקין"]["status"] == "ok"
    assert by_name["פריט נמוך"]["status"] == "low"
    assert by_name["פריט אזל"]["status"] == "out_of_stock"


def test_inventory_upsert_item(client, owner, stock):
    resp = client.post("/api/inventory/items", json={
        "name": "פריט חדש", "quantity": 7, "unit_cost": 10, "reorder_level": 2,
    }, headers=owner["headers"])
    assert resp.status_code == 200, resp.text
    report = client.get("/api/inventory/report", headers=owner["headers"]).json()["data"]
    assert "פריט חדש" in [r["name"] for r in report["items"]]


def test_inventory_is_org_scoped(client, owner, tenant, stock):
    tenant_report = client.get("/api/inventory/report", headers=tenant["headers"]).json()["data"]
    assert tenant_report["summary"]["total_items"] == 0  # לא רואה את המלאי של owner


def test_inventory_sync_without_sumit_fails_cleanly(client):
    # משתמש טרי ללא חיבור SUMIT -> 400 ברור, לא חריגה לא מטופלת
    reg = client.post("/api/admin/auth/register", json={
        "email": "nosumit@example.com", "password": "secret123", "full_name": "NoSumit",
    })
    assert reg.status_code == 201, reg.text
    headers = {"Authorization": f"Bearer {reg.json()['access_token']}"}
    resp = client.post("/api/inventory/sync", headers=headers)
    # 400 = אין חיבור; 502 = חיבור קיים אך כשל מול SUMIT. שניהם מטופלים נקי.
    assert resp.status_code in (400, 502), resp.text
