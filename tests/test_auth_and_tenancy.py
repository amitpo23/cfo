import pytest
def test_health(client):
    assert client.get("/api/health").json() == {"status": "healthy"}


def test_protected_routes_require_token(client):
    for path in ["/api/integration/status", "/api/control/overview", "/api/brain/insights", "/api/sync/runs"]:
        assert client.get(path).status_code == 403, path


def test_first_user_is_admin_of_default_org(owner):
    assert owner["user"]["role"] == "admin"
    assert owner["user"]["organization_id"] == 1


def test_client_supplied_role_is_ignored(client, owner):
    resp = client.post("/api/admin/auth/register", json={
        "email": "wannabe@example.com",
        "password": "secret123",
        "full_name": "Wannabe",
        "role": "super_admin",
        "organization_id": 1,
    })
    assert resp.status_code == 201
    assert resp.json()["user"]["role"] == "user"


def test_second_user_gets_own_org(owner, tenant):
    assert tenant["user"]["organization_id"] != owner["user"]["organization_id"]
    assert tenant["user"]["role"] == "admin"  # admin of their own org


def test_billing_checkout_returns_self_service_session(client):
    resp = client.post("/api/admin/billing/checkout", json={
        "selected_plan": "company_up_to_2_5m",
        "annual_revenue": "up_to_2_5m",
        "payment_template": "apple_pay",
        "annual_report_requested": True,
        "email": "checkout@example.com",
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["checkout_session_id"]
    assert "apple_pay" in body["supports"]
    assert body["payment_status"] in {"mock_ready", "checkout_started", "paid"}


def test_checkout_session_opens_isolated_tenant_without_registration_code(client, owner):
    checkout = client.post("/api/admin/billing/checkout", json={
        "selected_plan": "company_above_2_5m",
        "annual_revenue": "above_2_5m",
        "payment_template": "card",
        "annual_report_requested": True,
    }).json()

    resp = client.post("/api/admin/auth/register", json={
        "email": "selfserve@example.com",
        "password": "secret123",
        "full_name": "Self Serve",
        "selected_plan": "company_above_2_5m",
        "annual_revenue": "above_2_5m",
        "payment_template": "card",
        "checkout_session_id": checkout["checkout_session_id"],
        "payment_status": checkout["payment_status"],
    })
    assert resp.status_code == 201, resp.text
    user = resp.json()["user"]
    assert user["role"] == "admin"
    assert user["organization_id"] != owner["user"]["organization_id"]

    from cfo.database import SessionLocal
    from cfo.models import Organization

    db = SessionLocal()
    try:
        org = db.query(Organization).filter(Organization.id == user["organization_id"]).first()
        assert org.settings["selected_plan"] == "company_above_2_5m"
        assert org.settings["checkout_session_id"] == checkout["checkout_session_id"]
        assert org.settings["payment_template"] == "card"
    finally:
        db.close()


def test_mock_checkout_is_disabled_on_vercel(client, monkeypatch):
    monkeypatch.setenv("VERCEL", "1")
    resp = client.post("/api/admin/billing/checkout", json={
        "selected_plan": "company_up_to_2_5m",
        "annual_revenue": "up_to_2_5m",
        "payment_template": "card",
    })
    assert resp.status_code == 503


def test_unverified_checkout_does_not_open_tenant_on_vercel(client, monkeypatch):
    monkeypatch.setenv("VERCEL", "1")
    resp = client.post("/api/admin/auth/register", json={
        "email": "fakecheckout@example.com",
        "password": "secret123",
        "full_name": "Fake Checkout",
        "checkout_session_id": "fake_checkout_id",
        "payment_status": "paid",
    })
    assert resp.status_code == 403


def test_login(client, owner):
    resp = client.post("/api/admin/auth/login", json={
        "email": "owner@example.com", "password": "secret123",
    })
    assert resp.status_code == 200
    assert resp.json()["access_token"]


def test_wrong_password_rejected(client, owner):
    resp = client.post("/api/admin/auth/login", json={
        "email": "owner@example.com", "password": "wrong",
    })
    assert resp.status_code == 401


def test_org_id_cannot_be_spoofed_via_query(client, tenant):
    resp = client.get("/api/integration/status?org_id=1", headers=tenant["headers"])
    assert resp.json()["organization_id"] == tenant["user"]["organization_id"]


def test_env_credentials_only_for_default_org(client, owner, tenant):
    owner_status = client.get("/api/integration/status", headers=owner["headers"]).json()
    tenant_status = client.get("/api/integration/status", headers=tenant["headers"]).json()
    assert owner_status["configured"]["sumit"] is True
    assert tenant_status["configured"]["sumit"] is False


def test_tenant_configures_own_sumit_credentials(client, tenant):
    resp = client.post("/api/integration/sumit/configure", json={
        "api_key": "tenant-own-key", "company_id": "123",
    }, headers=tenant["headers"])
    assert resp.status_code == 200
    status = client.get("/api/integration/status", headers=tenant["headers"]).json()
    assert status["configured"]["sumit"] is True


def test_credentials_are_encrypted_at_rest(client, tenant):
    import os
    import sqlite3
    db_path = os.environ["DATABASE_URL"].replace("sqlite:///", "")
    rows = sqlite3.connect(db_path).execute(
        "select credentials_encrypted from integration_connections"
    ).fetchall()
    assert rows
    for (blob,) in rows:
        assert "tenant-own-key" not in blob
        assert not blob.strip().startswith("{")


def test_users_list_is_org_scoped(client, owner, tenant):
    owner_emails = {u["email"] for u in client.get("/api/admin/users", headers=owner["headers"]).json()}
    tenant_emails = {u["email"] for u in client.get("/api/admin/users", headers=tenant["headers"]).json()}
    assert "tenant@example.com" not in owner_emails
    assert "owner@example.com" not in tenant_emails


def test_cron_requires_secret(client):
    assert client.get("/api/cron/sync").status_code == 401
    assert client.get(
        "/api/cron/sync", headers={"Authorization": "Bearer wrong"}
    ).status_code == 401


def test_cron_runs_with_secret(client):
    resp = client.get("/api/cron/sync", headers={"Authorization": "Bearer test-cron-secret"})
    assert resp.status_code == 200
    body = resp.json()
    assert "synced" in body and isinstance(body["results"], list)


# --- Cross-tenant isolation: PATCH routes must be org-scoped (P0) ----------
def test_cannot_patch_another_orgs_task(client, owner, fresh_org):
    """A task created by org A must not be modifiable by org B."""
    r = client.post("/api/tasks", json={"title": "Owner task"}, headers=owner["headers"])
    assert r.status_code == 200, r.text
    task_id = r.json()["id"]

    other = fresh_org()
    hijack = client.patch(f"/api/tasks/{task_id}", json={"title": "hijacked"},
                          headers=other["headers"])
    assert hijack.status_code == 404, hijack.text

    own = client.patch(f"/api/tasks/{task_id}", json={"title": "renamed"},
                       headers=owner["headers"])
    assert own.status_code == 200, own.text
    assert own.json()["title"] == "renamed"


def test_cannot_read_another_orgs_sync_run(client, owner, fresh_org):
    """GET /sync/runs/{id} must be org-scoped — a missing/foreign run is 404."""
    other = fresh_org()
    # An arbitrary run id that does not belong to `other` must not leak.
    resp = client.get("/api/sync/runs/999999", headers=other["headers"])
    assert resp.status_code == 404, resp.text


# --- NULL organization_id must be rejected, not silently defaulted (P0) -----
def test_null_org_id_is_rejected():
    import asyncio
    from fastapi import HTTPException
    from cfo.api.dependencies import get_current_org_id
    from cfo.models import User

    with pytest.raises(HTTPException) as exc:
        asyncio.run(get_current_org_id(User(organization_id=None)))
    assert exc.value.status_code == 403

    # a real org passes through unchanged
    assert asyncio.run(get_current_org_id(User(organization_id=5))) == 5


# --- SUMIT direct routes must use per-org vault, not env for other tenants (P0)
def test_sumit_routes_reject_unconfigured_tenant(client, fresh_org):
    """A non-default org with no SUMIT connection must NOT fall back to env creds."""
    other = fresh_org()  # org != 1
    resp = client.get("/api/accounting/documents", headers=other["headers"])
    assert resp.status_code == 400, resp.text
    assert "SUMIT" in resp.text
