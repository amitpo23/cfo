"""End-to-end tests for the Open Finance routes (auth + insights generation)."""
from datetime import date

import pytest


def test_open_finance_routes_require_auth(client):
    for path in ["/api/open-finance/insights", "/api/open-finance/connections"]:
        assert client.get(path).status_code == 403, path


def test_webhook_is_public_and_updates_nothing_gracefully(client):
    # No auth required; unknown connection id is tolerated.
    r = client.post("/api/open-finance/webhooks", json={"connectionId": "nope", "connectionStatus": "ACTIVE"})
    assert r.status_code == 200
    assert r.json()["received"] is True


@pytest.fixture
def seeded_bank_txns(owner):
    """Insert bank transactions for the owner's org directly via the app DB."""
    from cfo.database import SessionLocal
    from cfo.models import BankTransaction

    org_id = owner["user"]["organization_id"]
    db = SessionLocal()
    try:
        # Two identical same-day charges -> duplicate_charge insight.
        for i, ext in enumerate(["of-dup-1", "of-dup-2"]):
            db.add(BankTransaction(
                organization_id=org_id, external_id=ext, source="open_finance",
                transaction_date=date(2026, 6, 1), description="Pizza", amount=-120,
                currency="ILS",
                raw_data={"merchantName": "Pizza Place", "category": {"main": "FOOD_&_DRINKS"}},
            ))
        db.commit()
    finally:
        db.close()
    return owner


def test_generate_and_list_insights(client, seeded_bank_txns):
    headers = seeded_bank_txns["headers"]
    # Generate without the optional monthly report (no OF creds in tests).
    r = client.post(
        "/api/open-finance/insights/generate?include_monthly_report=false", headers=headers
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["transactions_analyzed"] >= 2
    assert body["generated"] >= 1

    r2 = client.get("/api/open-finance/insights", headers=headers)
    assert r2.status_code == 200
    types = {i["type"] for i in r2.json()["items"]}
    assert "duplicate_charge" in types


def test_reconcile_runs(client, owner):
    r = client.post("/api/open-finance/reconcile?persist=false", headers=owner["headers"])
    assert r.status_code == 200
    assert "matched_count" in r.json()


def test_bc_full_coverage_routes_registered_and_auth_gated(client):
    # A sample of the completed B/C surface — every one must require auth.
    for path in [
        "/api/open-finance/atm/p1",
        "/api/open-finance/mandates/r1/status",
        "/api/open-finance/credit-leads",
        "/api/open-finance/decision-extended/j1",
        "/api/open-finance/private-scoring/j1",
        "/api/open-finance/customers/c1/balances",
        "/api/open-finance/customers/c1/osh/accounts",
        "/api/open-finance/merchants/m1",
        "/api/open-finance/financial-report/j1",
    ]:
        assert client.get(path).status_code == 403, path


def test_bc_routes_return_not_configured_without_creds(client, owner):
    # With auth but no Open Finance credentials, thin pass-throughs return 400.
    r = client.get("/api/open-finance/merchants/m1", headers=owner["headers"])
    assert r.status_code == 400


@pytest.fixture
def of_configured_org(fresh_org):
    """An isolated org with real-shaped (fake-valued) Open Finance credentials,
    so get_open_finance_client() succeeds and create_connection is reachable."""
    from cfo.database import SessionLocal
    from cfo.models import IntegrationConnection
    from cfo.services.credentials_vault import encrypt_credentials

    org = fresh_org()
    db = SessionLocal()
    try:
        db.add(IntegrationConnection(
            organization_id=org["org_id"], source="open_finance", status="active",
            credentials_encrypted=encrypt_credentials({
                "client_id": "test-client-id", "client_secret": "test-client-secret",
                "user_id": "test-user-id",
            }),
        ))
        db.commit()
    finally:
        db.close()
    return org


def test_create_connection_returns_connect_url_and_persists_it(client, of_configured_org, monkeypatch):
    from cfo.services.open_finance_client import OpenFinanceClient

    async def fake_create_connection(self, body):
        assert body["language"] == "he"
        return {"id": "conn-123", "connectUrl": "https://consent.example.com/conn-123"}

    monkeypatch.setattr(OpenFinanceClient, "create_connection", fake_create_connection)

    r = client.post(
        "/api/open-finance/connections", json={"language": "he"},
        headers=of_configured_org["headers"],
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["connection_id"] == "conn-123"
    assert body["connect_url"] == "https://consent.example.com/conn-123"

    from cfo.database import SessionLocal
    from cfo.models import BankConnection

    db = SessionLocal()
    try:
        row = db.query(BankConnection).filter(
            BankConnection.organization_id == of_configured_org["org_id"],
            BankConnection.connection_id == "conn-123",
        ).first()
        assert row is not None
        assert row.connect_url == "https://consent.example.com/conn-123"
        assert row.status == "INACTIVE"
    finally:
        db.close()


def test_create_connection_is_org_scoped(client, of_configured_org, fresh_org, monkeypatch):
    from cfo.services.open_finance_client import OpenFinanceClient

    async def fake_create_connection(self, body):
        return {"id": "conn-456", "connectUrl": "https://consent.example.com/conn-456"}

    monkeypatch.setattr(OpenFinanceClient, "create_connection", fake_create_connection)

    client.post(
        "/api/open-finance/connections", json={"language": "he"},
        headers=of_configured_org["headers"],
    )

    other_org = fresh_org()
    r = client.post(
        "/api/open-finance/connections", json={"language": "he"},
        headers=other_org["headers"],
    )
    # The other org has no Open Finance credentials configured -> 400, not a
    # leak of of_configured_org's connection.
    assert r.status_code == 400
