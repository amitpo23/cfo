"""Wave 2 addition E — /api/assets/* routes. Organization-scoped."""
from datetime import date

from cfo.database import SessionLocal


def test_assets_routes_require_auth(client):
    for method, path in [
        ("get", "/api/assets"),
        ("post", "/api/assets"),
        ("get", "/api/assets/1/schedule"),
        ("delete", "/api/assets/1"),
        ("get", "/api/assets/depreciation/annual?year=2025"),
        ("get", "/api/assets/form-1342?year=2025"),
    ]:
        if method == "post":
            resp = client.post(path, json={})
        else:
            resp = getattr(client, method)(path)
        assert resp.status_code == 403, path


def test_create_list_schedule_roundtrip(client, fresh_org):
    iso = fresh_org()
    headers = iso["headers"]

    r = client.post("/api/assets", headers=headers, json={
        "name": "מחשב נייד", "category": "computers", "cost": 12000,
        "purchase_date": "2024-01-01", "depreciation_rate": 33, "salvage_value": 0,
    })
    assert r.status_code in (200, 201), r.text
    asset = r.json()
    assert asset["name"] == "מחשב נייד"
    asset_id = asset["id"]

    r = client.get("/api/assets", headers=headers)
    assert r.status_code == 200
    assets = r.json()["assets"]
    assert len(assets) == 1
    assert assets[0]["id"] == asset_id

    r = client.get(f"/api/assets/{asset_id}/schedule", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["asset"]["id"] == asset_id
    assert body["schedule"][0]["year"] == 2024
    assert body["schedule"][0]["annual_depreciation"] == 3960.0


def test_create_asset_defaults_rate_when_omitted(client, fresh_org):
    iso = fresh_org()
    r = client.post("/api/assets", headers=iso["headers"], json={
        "name": "בניין", "category": "buildings", "cost": 500000,
        "purchase_date": "2024-01-01",
    })
    assert r.status_code in (200, 201), r.text
    assert r.json()["depreciation_rate"] == 4.0


def test_delete_asset_org_isolation_returns_404(client, fresh_org):
    iso_a = fresh_org()
    iso_b = fresh_org()

    r = client.post("/api/assets", headers=iso_a["headers"], json={
        "name": "רכב", "category": "vehicles", "cost": 100000,
        "purchase_date": "2023-01-01",
    })
    asset_id = r.json()["id"]

    r = client.delete(f"/api/assets/{asset_id}", headers=iso_b["headers"])
    assert r.status_code == 404

    r = client.delete(f"/api/assets/{asset_id}", headers=iso_a["headers"])
    assert r.status_code == 200

    r = client.get(f"/api/assets/{asset_id}/schedule", headers=iso_a["headers"])
    assert r.status_code == 404


def test_schedule_route_404_for_foreign_org(client, fresh_org):
    iso_a = fresh_org()
    iso_b = fresh_org()
    r = client.post("/api/assets", headers=iso_a["headers"], json={
        "name": "רהיטים", "category": "furniture", "cost": 6000,
        "purchase_date": "2024-01-01",
    })
    asset_id = r.json()["id"]
    r = client.get(f"/api/assets/{asset_id}/schedule", headers=iso_b["headers"])
    assert r.status_code == 404


def test_annual_depreciation_route(client, fresh_org):
    iso = fresh_org()
    client.post("/api/assets", headers=iso["headers"], json={
        "name": "ציוד", "category": "equipment", "cost": 10000,
        "purchase_date": "2025-01-01", "depreciation_rate": 10, "salvage_value": 0,
    })
    r = client.get("/api/assets/depreciation/annual?year=2025", headers=iso["headers"])
    assert r.status_code == 200, r.text
    assert r.json()["total_depreciation"] == 1000.0


def test_form_1342_route(client, fresh_org):
    iso = fresh_org()
    client.post("/api/assets", headers=iso["headers"], json={
        "name": "ציוד", "category": "equipment", "cost": 10000,
        "purchase_date": "2025-01-01", "depreciation_rate": 10, "salvage_value": 0,
    })
    r = client.get("/api/assets/form-1342?year=2025", headers=iso["headers"])
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["draft"] is True
    assert len(body["rows"]) == 1
