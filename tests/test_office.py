"""End-to-end tests for the accounting-office (multi-company) routes."""

from cfo.database import SessionLocal
from cfo.models import IntegrationConnection, IntegrationType, OnboardingTask, Organization, SumitCompany
from cfo.services.client_automation_service import (
    mark_client_loop_result,
    repair_missing_client_roster,
    roster_sync_targets,
)
from cfo.services.credentials_vault import encrypt_credentials


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

        assert (org_id, "sumit") in roster_sync_targets(db)

        mark_client_loop_result(
            db,
            organization_id=org_id,
            source="sumit",
            ok=True,
            summary={"sync_run_id": 123, "status": "completed"},
        )
        db.commit()
        roster = db.query(SumitCompany).filter(
            SumitCompany.target_organization_id == org_id,
        ).first()
        assert roster.last_synced_at is not None
        automation = roster.raw_data["automation"]
        assert automation["state"] == "active"
        assert "sumit" in automation["sources"]
        assert automation["sources_state"]["sumit"]["summary"]["sync_run_id"] == 123
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
    payloads = (
        {"name": "שם ראשון", "business_type": "old", "tax_id": "111"},
        {"name": "שם מעודכן", "business_type": "company", "tax_id": "222"},
    )
    first_org_id = None
    for payload in payloads:
        r = client.post("/api/office/clients", headers=owner["headers"], json={
            **payload, "company_id": "999888777", "api_key": "k",
        })
        assert r.status_code == 200
        first_org_id = first_org_id or r.json()["target_organization_id"]
        assert r.json()["target_organization_id"] == first_org_id
    listing = client.get("/api/office/clients", headers=owner["headers"]).json()["clients"]
    matches = [c for c in listing if c["company_id"] == "999888777"]
    assert len(matches) == 1  # not duplicated
    assert matches[0]["name"] == "שם מעודכן"

    db = SessionLocal()
    try:
        org = db.get(Organization, first_org_id)
        assert org.name == "שם מעודכן"
        assert org.business_type == "company"
        assert org.tax_id == "222"
    finally:
        db.close()


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
    assert rec["organization_id"] == rec["target_organization_id"]
    assert "connection_statuses" in rec
    assert "automation" in rec


def test_cron_repair_backfills_legacy_sumit_roster(client, owner):
    db = SessionLocal()
    try:
        legacy = Organization(
            name="Legacy SUMIT Client",
            business_type="legacy",
            integration_type=IntegrationType.SUMIT,
            is_active=True,
        )
        db.add(legacy)
        db.flush()
        db.add(IntegrationConnection(
            organization_id=legacy.id,
            source="sumit",
            status="active",
            credentials_encrypted=encrypt_credentials({
                "api_key": "legacy-key",
                "company_id": "303030303",
            }),
            config={},
        ))
        db.commit()

        repaired = repair_missing_client_roster(db, office_organization_id=owner["user"]["organization_id"])
        assert any(row["company_id"] == "303030303" for row in repaired)
        roster = db.query(SumitCompany).filter(
            SumitCompany.company_id == "303030303",
            SumitCompany.target_organization_id == legacy.id,
        ).first()
        assert roster is not None
        assert roster.raw_data["automation"]["state"] == "queued"
        assert "sumit" in roster.raw_data["automation"]["sources"]
        assert (legacy.id, "sumit") in roster_sync_targets(db)
    finally:
        db.close()


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
