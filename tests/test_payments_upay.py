"""Upay wallet-activation routes (SUMIT_MODULE_COVERAGE.md's "wallet
activation" gap): /upay/open-terminal always raised a bare Exception (SUMIT's
endpoint onboards a brand-new merchant terminal with bank details, not a
per-amount payment session) -> unhandled 500 instead of a clean 400. And
setup_upay_credentials() (linking an EXISTING Upay account to the org's SUMIT
company) was implemented in the integration layer but had no route at all --
unreachable dead code from the API/UI's point of view.
"""
from cfo.integrations.sumit_integration import SumitIntegration


def test_upay_routes_require_auth(client):
    assert client.post("/api/payments/upay/open-terminal", params={
        "amount": "10", "description": "x",
    }).status_code == 403
    assert client.post("/api/payments/upay/setup", json={
        "email": "a@b.com", "password": "x",
    }).status_code == 403
    assert client.get("/api/payments/upay/status").status_code == 403


def test_open_terminal_returns_clean_400_not_500(client, owner):
    """org 1 gets the env-var SUMIT fallback (conftest sets SUMIT_API_KEY),
    so get_sumit_integration succeeds and we reach open_upay_terminal itself,
    which always raises -- must surface as 400, not an unhandled 500."""
    r = client.post("/api/payments/upay/open-terminal", params={
        "amount": "10", "description": "בדיקה",
    }, headers=owner["headers"])
    assert r.status_code == 400, r.text
    assert "Upay" in r.json()["detail"] or "upay" in r.json()["detail"].lower()


def test_setup_upay_credentials_marks_org_connected(client, owner, monkeypatch):
    async def fake_setup(self, credentials):
        assert credentials["EmailAddress"] == "owner@upay.example"
        assert credentials["Password"] == "s3cret"
        return {"Status": 0}

    monkeypatch.setattr(SumitIntegration, "setup_upay_credentials", fake_setup)

    status_before = client.get("/api/payments/upay/status", headers=owner["headers"])
    assert status_before.json()["connected"] is False

    r = client.post("/api/payments/upay/setup", json={
        "email": "owner@upay.example", "password": "s3cret",
    }, headers=owner["headers"])
    assert r.status_code == 200, r.text
    assert r.json()["connected"] is True

    status_after = client.get("/api/payments/upay/status", headers=owner["headers"])
    assert status_after.json()["connected"] is True


def test_setup_upay_credentials_does_not_persist_the_password(client, owner, monkeypatch):
    async def fake_setup(self, credentials):
        return {"Status": 0}

    monkeypatch.setattr(SumitIntegration, "setup_upay_credentials", fake_setup)

    client.post("/api/payments/upay/setup", json={
        "email": "owner@upay.example", "password": "s3cret-do-not-store",
    }, headers=owner["headers"])

    from cfo.database import SessionLocal
    from cfo.models import IntegrationConnection

    db = SessionLocal()
    try:
        conn = db.query(IntegrationConnection).filter(
            IntegrationConnection.organization_id == owner["user"]["organization_id"],
            IntegrationConnection.source == "upay",
        ).first()
        assert conn is not None
        assert conn.credentials_encrypted is None
    finally:
        db.close()


def test_upay_setup_is_org_scoped(client, fresh_org, monkeypatch):
    async def fake_setup(self, credentials):
        return {"Status": 0}

    monkeypatch.setattr(SumitIntegration, "setup_upay_credentials", fake_setup)

    from cfo.database import SessionLocal
    from cfo.models import IntegrationConnection
    from cfo.services.credentials_vault import encrypt_credentials

    def _with_sumit(iso):
        db = SessionLocal()
        try:
            db.add(IntegrationConnection(
                organization_id=iso["org_id"], source="sumit", status="active",
                credentials_encrypted=encrypt_credentials({"api_key": "k", "company_id": "1"}),
            ))
            db.commit()
        finally:
            db.close()
        return iso

    org_a = _with_sumit(fresh_org())
    org_b = _with_sumit(fresh_org())

    r = client.post("/api/payments/upay/setup", json={
        "email": "a@b.com", "password": "x",
    }, headers=org_a["headers"])
    assert r.status_code == 200, r.text

    status_a = client.get("/api/payments/upay/status", headers=org_a["headers"])
    status_b = client.get("/api/payments/upay/status", headers=org_b["headers"])
    assert status_a.json()["connected"] is True
    assert status_b.json()["connected"] is False
