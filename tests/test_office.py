"""End-to-end tests for the accounting-office (multi-company) routes."""

from cfo.database import SessionLocal
from cfo.models import IntegrationConnection, OnboardingTask


def test_office_routes_require_auth(client):
    assert client.get("/api/office/clients").status_code == 403
    assert client.get("/api/office/rollup").status_code == 403


def test_register_client_provisions_isolated_tenant(client, owner):
    headers = owner["headers"]
    office_org = owner["user"]["organization_id"]

    resp = client.post("/api/office/clients", headers=headers, json={
        "name": "לקוח אלפא בע\"מ",
        "company_id": "844329067",
        "api_key": "client-alpha-sumit-key",
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["company_id"] == "844329067"
    # The client file gets its OWN tenant organization, not the office org.
    assert body["target_organization_id"] != office_org
    assert body["automation"]["state"] == "queued"
    assert body["automation"]["target_organization_id"] == body["target_organization_id"]

    # It shows up in the roster with its sumit connection.
    listing = client.get("/api/office/clients", headers=headers).json()["clients"]
    alpha = next(c for c in listing if c["company_id"] == "844329067")
    assert "sumit" in alpha["connections"]
    assert alpha["automation"]["state"] == "queued"
    assert alpha["onboarding"]["sources"]["sumit"]["pending"] >= 1

    db = SessionLocal()
    try:
        org_id = body["target_organization_id"]
        conn = db.query(IntegrationConnection).filter(
            IntegrationConnection.organization_id == org_id,
            IntegrationConnection.source == "sumit",
            IntegrationConnection.status == "active",
        ).first()
        assert conn is not None
        assert db.query(OnboardingTask).filter(
            OnboardingTask.organization_id == org_id,
            OnboardingTask.source == "sumit",
        ).count() >= 1
    finally:
        db.close()


def test_register_client_with_open_finance_creds(client, owner):
    resp = client.post("/api/office/clients", headers=owner["headers"], json={
        "name": "לקוח בטא",
        "company_id": "111222333",
        "api_key": "client-beta-key",
        "open_finance": {"client_id": "of-id", "client_secret": "of-sec", "user_id": "of-user"},
    })
    assert resp.status_code == 200
    assert resp.json()["has_open_finance"] is True
    assert set(resp.json()["automation"]["sources"]) == {"open_finance", "sumit"}
    listing = client.get("/api/office/clients", headers=owner["headers"]).json()["clients"]
    beta = next(c for c in listing if c["company_id"] == "111222333")
    assert "open_finance" in beta["connections"]
    assert "open_finance" in beta["onboarding"]["sources"]


def test_reregister_same_company_updates_in_place(client, owner):
    for name in ("שם ראשון", "שם מעודכן"):
        r = client.post("/api/office/clients", headers=owner["headers"], json={
            "name": name, "company_id": "999888777", "api_key": "k",
        })
        assert r.status_code == 200
    listing = client.get("/api/office/clients", headers=owner["headers"]).json()["clients"]
    matches = [c for c in listing if c["company_id"] == "999888777"]
    assert len(matches) == 1  # not duplicated
    assert matches[0]["name"] == "שם מעודכן"


def test_register_without_key_requires_office_default(client, owner):
    # No office key set yet, no per-client key -> 400.
    r = client.post("/api/office/clients", headers=owner["headers"], json={
        "name": "ללא מפתח", "company_id": "000111222",
    })
    assert r.status_code == 400


def test_office_default_key_serves_clients(client, owner):
    headers = owner["headers"]
    # Set one office-level SUMIT key.
    s = client.post("/api/office/settings", headers=headers, json={"sumit_api_key": "office-master-key"})
    assert s.status_code == 200
    assert s.json()["sumit_key_configured"] is True

    # Register a client WITHOUT a key — it should use the office key.
    r = client.post("/api/office/clients", headers=headers, json={
        "name": "תיק עם מפתח משרד", "company_id": "424242424",
    })
    assert r.status_code == 200, r.text
    assert r.json()["used_office_key"] is True

    listing = client.get("/api/office/clients", headers=headers).json()["clients"]
    rec = next(c for c in listing if c["company_id"] == "424242424")
    assert "sumit" in rec["connections"]


def test_admin_clients_view(client, owner):
    client.post("/api/office/settings", headers=owner["headers"], json={"sumit_api_key": "k"})
    client.post("/api/office/clients", headers=owner["headers"], json={
        "name": "Admin View Client", "company_id": "707070707",
    })
    r = client.get("/api/office/admin/clients", headers=owner["headers"])
    assert r.status_code == 200
    body = r.json()
    assert "totals" in body and "clients" in body
    rec = next(c for c in body["clients"] if c["company_id"] == "707070707")
    assert "required_actions" in rec and "net_vat" in rec and "connections" in rec


def test_office_rollup_aggregates_clients(client, owner):
    client.post("/api/office/clients", headers=owner["headers"], json={
        "name": "Rollup Client", "company_id": "555444333", "api_key": "k",
    })
    r = client.get("/api/office/rollup", headers=owner["headers"])
    assert r.status_code == 200
    body = r.json()
    assert "totals" in body and "clients" in body
    assert body["totals"]["clients"] >= 1
    assert "net_vat" in body["totals"]
