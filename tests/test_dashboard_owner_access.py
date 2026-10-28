"""Owner access on /d/<slug> and self-service org + dashboard creation.

A logged-in platform admin opens a link-mode dashboard with no share cookie.
An anonymous visitor gets a login prompt, not a generic not-found.
Creating the workspace and reading provider status never builds a provider client.
A SUMIT or Open Finance action runs only after the exact confirmation, and the
default action still does not call the provider.
"""
from datetime import datetime, timezone

from cfo.auth import create_access_token
from cfo.database import SessionLocal
from cfo.models import Organization, OrganizationMembership, User, UserRole
from cfo.services.dashboards import provider_gate


def _activate(client, headers, dashboard_id):
    response = client.patch(
        f"/api/dashboards/{dashboard_id}", headers=headers, json={"status": "active"},
    )
    assert response.status_code == 200, response.text


def test_logged_in_admin_opens_eliav_without_a_share_link(client, fresh_org, platform_admin):
    owner = fresh_org()
    created = client.post("/api/dashboards", headers=owner["headers"], json={
        "primary_organization_id": owner["org_id"],
        "slug": "eliav",
        "title": "שף אליהב",
        "access_mode": "link",
    })
    assert created.status_code == 201, created.text
    dashboard_id = created.json()["id"]
    _activate(client, owner["headers"], dashboard_id)

    meta = client.get("/api/dashboards/by-slug/eliav", headers=platform_admin["headers"])
    view = client.get(f"/api/dashboards/{dashboard_id}/view", headers=platform_admin["headers"])

    assert meta.status_code == 200, meta.text
    assert view.status_code == 200, view.text
    assert meta.json()["slug"] == "eliav"
    assert meta.json()["role"] == "owner"
    assert view.json()["provider_calls"] == 0
    assert view.status_code not in (404, 500)


def test_anonymous_link_visitor_is_asked_to_log_in(client, fresh_org):
    owner = fresh_org()
    created = client.post("/api/dashboards", headers=owner["headers"], json={
        "primary_organization_id": owner["org_id"],
        "slug": "eliav-login",
        "title": "שף אליהב",
        "access_mode": "link",
    })
    _activate(client, owner["headers"], created.json()["id"])

    public = client.get("/api/public/d/eliav-login")

    assert public.status_code == 401, public.text
    error = public.json()["error"]
    assert error["code"] == "login_required"
    assert error["message_he"] != "הדשבורד לא נמצא"
    assert "התחברו" in error["message_he"]
    assert error["login_path"] == "/?login=1&next=/d/eliav-login"
    assert public.headers["referrer-policy"] == "no-referrer"
    assert "pnl" not in public.json()


def test_closed_and_unknown_dashboards_stay_not_found(client, fresh_org):
    owner = fresh_org()
    created = client.post("/api/dashboards", headers=owner["headers"], json={
        "primary_organization_id": owner["org_id"],
        "slug": "eliav-closed",
        "title": "סגור",
        "access_mode": "members",
    })
    _activate(client, owner["headers"], created.json()["id"])

    closed = client.get("/api/public/d/eliav-closed")
    missing = client.get("/api/public/d/no-such-dashboard")
    draft = client.post("/api/dashboards", headers=owner["headers"], json={
        "primary_organization_id": owner["org_id"],
        "slug": "eliav-draft",
        "title": "טיוטה",
        "access_mode": "link",
    })
    hidden_draft = client.get("/api/public/d/eliav-draft")

    assert draft.status_code == 201
    assert closed.status_code == 404 and closed.json()["error"]["code"] == "not_found"
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "not_found"
    assert hidden_draft.status_code == 404


def test_admin_creates_a_closed_workspace_without_calling_providers(client, fresh_org, monkeypatch):
    admin = fresh_org()
    calls = []

    def sumit(*_args, **_kwargs):
        calls.append("sumit")
        return {"executed": True, "provider_calls": 1, "message_he": "mock sumit"}

    def finance(*_args, **_kwargs):
        calls.append("open_finance")
        return {"executed": True, "provider_calls": 1, "message_he": "mock finance"}

    monkeypatch.setattr(provider_gate, "place_sumit_call", sumit)
    monkeypatch.setattr(provider_gate, "place_open_finance_refresh", finance)

    created = client.post("/api/dashboards/workspaces", headers=admin["headers"], json={
        "name": "עסק בדיקה",
        "slug": "workspace-test",
        "title": "דשבורד בדיקה",
        "entities": [],
    })

    assert created.status_code == 201, created.text
    body = created.json()
    assert body["provider_calls"] == 0
    assert body["dashboard"]["status"] == "draft"
    assert body["dashboard"]["access_mode"] == "members"
    assert body["dashboard"]["access_mode"] != "public"
    assert body["organization"]["name"] == "עסק בדיקה"
    assert body["entities"] == [{
        "id": body["entities"][0]["id"],
        "organization_id": body["organization"]["id"],
        "label": "עסק בדיקה",
        "role": "primary",
        "accounts": [],
    }]
    providers = body["providers"]
    assert providers["provider_calls"] == 0
    assert providers["sumit"]["connected"] is False
    assert providers["sumit"]["status"] == "missing"
    assert providers["open_finance"]["connected"] is False
    quota = providers["sumit_quota"]
    assert quota["live_shared_cap"] == 50
    assert quota["shared"] is True
    assert quota["remaining"] == max(0, quota["limit"] - quota["used"])
    assert calls == []

    dashboard_id = body["dashboard"]["id"]
    status = client.get(f"/api/dashboards/{dashboard_id}/providers", headers=admin["headers"])
    assert status.status_code == 200, status.text
    assert status.json()["provider_calls"] == 0
    assert calls == []

    refused = client.post(
        f"/api/dashboards/{dashboard_id}/providers/sumit",
        headers=admin["headers"], json={"confirmation": "לא עכשיו"},
    )
    assert refused.status_code == 400
    assert refused.json()["error"]["code"] == "confirmation_required"
    assert calls == []

    confirmed = client.post(
        f"/api/dashboards/{dashboard_id}/providers/sumit",
        headers=admin["headers"],
        json={"confirmation": status.json()["confirmations"]["sumit"]},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["provider_calls"] == 1
    assert calls == ["sumit"]

    finance_refused = client.post(
        f"/api/dashboards/{dashboard_id}/providers/open-finance/refresh",
        headers=admin["headers"], json={},
    )
    assert finance_refused.status_code == 400
    assert calls == ["sumit"]
    finance_ok = client.post(
        f"/api/dashboards/{dashboard_id}/providers/open-finance/refresh",
        headers=admin["headers"],
        json={"confirmation": status.json()["confirmations"]["open_finance"]},
    )
    assert finance_ok.status_code == 200, finance_ok.text
    assert calls == ["sumit", "open_finance"]


def test_confirmed_provider_actions_do_not_build_clients(client, fresh_org, monkeypatch):
    admin = fresh_org()
    created = client.post("/api/dashboards/workspaces", headers=admin["headers"], json={
        "name": "בלי ספק", "slug": "no-provider-client",
    })
    assert created.status_code == 201, created.text
    dashboard_id = created.json()["dashboard"]["id"]

    def boom(*_args, **_kwargs):
        raise AssertionError("provider client was built")

    monkeypatch.setattr("cfo.integrations.sumit_integration.SumitIntegration.__init__", boom)
    monkeypatch.setattr("cfo.api.routes.open_finance.get_open_finance_client", boom)

    sumit = client.post(
        f"/api/dashboards/{dashboard_id}/providers/sumit",
        headers=admin["headers"], json={"confirmation": provider_gate.SUMIT_CONFIRMATION},
    )
    finance = client.post(
        f"/api/dashboards/{dashboard_id}/providers/open-finance/refresh",
        headers=admin["headers"],
        json={"confirmation": provider_gate.OPEN_FINANCE_CONFIRMATION},
    )

    assert sumit.status_code == 200, sumit.text
    assert finance.status_code == 200, finance.text
    assert sumit.json()["executed"] is False and sumit.json()["provider_calls"] == 0
    assert finance.json()["executed"] is False and finance.json()["provider_calls"] == 0
    assert "לא יצאה קריאה" in sumit.json()["message_he"]
    assert "לא יצא רענון" in finance.json()["message_he"]


def test_a_new_dashboard_cannot_be_public_and_a_failed_entity_rolls_back(client, fresh_org):
    admin = fresh_org()
    public = client.post("/api/dashboards/workspaces", headers=admin["headers"], json={
        "name": "לא ציבורי", "slug": "never-public", "access_mode": "public",
    })
    assert public.status_code == 422
    assert public.json()["error"]["code"] == "invalid_access"

    mismatch = client.post("/api/dashboards/workspaces", headers=admin["headers"], json={
        "name": "לא נשמר",
        "slug": "rolled-back-workspace",
        "entities": [{"organization_id": admin["org_id"], "label": "אחר"}],
    })
    assert mismatch.status_code == 422, mismatch.text
    assert mismatch.json()["error"]["code"] == "entity_office_mismatch"
    with SessionLocal() as db:
        assert db.query(Organization).filter_by(name="לא ציבורי").count() == 0
        assert db.query(Organization).filter_by(name="לא נשמר").count() == 0


def test_legacy_admin_role_without_an_admin_membership_cannot_create_a_workspace(client, fresh_org):
    owner = fresh_org()
    with SessionLocal() as db:
        user = User(
            organization_id=owner["org_id"],
            email=f"legacy-workspace-{owner['org_id']}@example.com",
            password_hash="x",
            full_name="Legacy",
            role=UserRole.ADMIN,
            is_active=True,
            token_version=0,
        )
        db.add(user)
        db.flush()
        db.add(OrganizationMembership(
            organization_id=owner["org_id"],
            user_id=user.id,
            role=UserRole.VIEWER,
            status="suspended",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        ))
        db.commit()
        user_id = user.id
    token = create_access_token({"sub": str(user_id)})

    denied = client.post("/api/dashboards/workspaces", headers={"Authorization": f"Bearer {token}"}, json={
        "name": "לא שלו", "slug": "not-his-workspace",
    })

    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "forbidden"
    with SessionLocal() as db:
        assert db.query(Organization).filter_by(name="לא שלו").count() == 0
