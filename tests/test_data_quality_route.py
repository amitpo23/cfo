"""GET /api/data-quality — נגיש עם auth, מוגבל ל-org, ומחזיר את מבנה run_checks."""


def test_data_quality_route_requires_auth(client):
    resp = client.get("/api/data-quality")
    assert resp.status_code in (401, 403)


def test_data_quality_route_returns_ok_status(client, fresh_org):
    org = fresh_org()
    resp = client.get("/api/data-quality", headers=org["headers"])
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] in ("ok", "issues")
    assert isinstance(data["checks"], list)
    assert "issues_count" in data
    assert "checked_at" in data
