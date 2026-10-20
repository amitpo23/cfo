"""Dashboard access, live view, and share links. No provider calls."""
import ast
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from cfo.auth import create_access_token
from cfo.database import SessionLocal
from cfo.models import (
    DashboardMember, DashboardRateLimit, Invoice, OrganizationMembership,
    PipelineRun, ProviderRequestBudget, PublishedSnapshot, SumitCompany, User,
    UserRole,
)


def _create(client, headers, org_id, slug="foodgroup-cash"):
    response = client.post("/api/dashboards", headers=headers, json={
        "primary_organization_id": org_id,
        "slug": slug,
        "title": "תזרים",
        "access_mode": "link",
    })
    return response


def test_unknown_and_forbidden_dashboards_are_404(client, fresh_org):
    owner = fresh_org()
    stranger = fresh_org()
    created = _create(client, owner["headers"], owner["org_id"], "owner-only-dash")
    assert created.status_code == 201, created.text
    dashboard_id = created.json()["id"]
    missing = client.get("/api/dashboards/999999", headers=owner["headers"])
    forbidden = client.get(f"/api/dashboards/{dashboard_id}", headers=stranger["headers"])
    assert missing.status_code == 404
    assert forbidden.status_code == 404
    assert missing.json()["error"]["code"] == "not_found"
    assert forbidden.json()["error"]["code"] == "not_found"
    assert "403" not in forbidden.text


def test_empty_books_are_unknown_and_make_no_provider_calls(client, fresh_org):
    owner = fresh_org()
    created = _create(client, owner["headers"], owner["org_id"], "empty-books-dash")
    assert created.status_code == 201, created.text
    view = client.get(
        f"/api/dashboards/{created.json()['id']}/view",
        headers=owner["headers"],
        params={"start": "2026-01-01", "end": "2026-10-20"},
    )
    assert view.status_code == 200, view.text
    body = view.json()
    assert body["provider_calls"] == 0
    assert body["pnl"]["status"] == "unknown"
    assert body["pnl"]["total_revenue"] is None
    assert body["pnl"]["tax_expense"] is None
    assert "cashflow" in body


def test_share_token_is_returned_once_and_revocation_closes_the_link(client, fresh_org):
    owner = fresh_org()
    created = _create(client, owner["headers"], owner["org_id"], "shared-dash")
    dashboard_id = created.json()["id"]
    activated = client.patch(
        f"/api/dashboards/{dashboard_id}", headers=owner["headers"],
        json={"status": "active"},
    )
    assert activated.status_code == 200, activated.text
    minted = client.post(
        f"/api/dashboards/{dashboard_id}/share-links", headers=owner["headers"],
        json={"label": "owner link"},
    )
    assert minted.status_code == 201, minted.text
    token = minted.json()["token"]
    listed = client.get(f"/api/dashboards/{dashboard_id}/share-links", headers=owner["headers"])
    assert listed.status_code == 200
    assert "token" not in listed.text
    opened = client.post(f"/api/public/d/shared-dash/session", json={"token": token})
    assert opened.status_code == 200, opened.text
    assert opened.json()["provider_calls"] == 0
    assert opened.headers["referrer-policy"] == "no-referrer"
    assert opened.headers["x-robots-tag"] == "noindex"
    public = client.get("/api/public/d/shared-dash")
    assert public.status_code == 200, public.text
    assert public.json()["provider_calls"] == 0
    assert public.json()["pnl"]["total_revenue"] is None
    revoked = client.delete(
        f"/api/dashboards/{dashboard_id}/share-links/{minted.json()['id']}",
        headers=owner["headers"],
    )
    assert revoked.status_code == 204
    closed = client.get("/api/public/d/shared-dash")
    assert closed.status_code == 404


def test_viewer_cannot_mint_a_link_and_plan_requires_if_match(client, fresh_org):
    owner = fresh_org()
    viewer = fresh_org()
    created = _create(client, owner["headers"], owner["org_id"], "plan-dash")
    dashboard_id = created.json()["id"]
    with SessionLocal() as db:
        from cfo.models import User
        user = db.query(User).filter(User.organization_id == viewer["org_id"]).one()
        db.add(DashboardMember(
            dashboard_id=dashboard_id, user_id=user.id, role="client_viewer", status="active",
        ))
        db.commit()
    denied = client.post(
        f"/api/dashboards/{dashboard_id}/share-links", headers=viewer["headers"], json={},
    )
    assert denied.status_code == 404
    missing = client.put(
        f"/api/dashboards/{dashboard_id}/plan", headers=owner["headers"],
        json={"payload": {"note": "budget"}},
    )
    assert missing.status_code == 412
    saved = client.put(
        f"/api/dashboards/{dashboard_id}/plan",
        headers={**owner["headers"], "If-Match": "null"},
        json={"payload": {"note": "budget"}},
    )
    assert saved.status_code == 200, saved.text
    version = saved.json()["version"]
    conflict = client.put(
        f"/api/dashboards/{dashboard_id}/plan",
        headers={**owner["headers"], "If-Match": "stale-version"},
        json={"payload": {"note": "other"}},
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "plan_conflict"
    current = client.get(f"/api/dashboards/{dashboard_id}/plan", headers=owner["headers"])
    assert current.json()["version"] == version


def test_snapshot_is_idempotent_per_day_and_records_a_pipeline_run(client, fresh_org):
    owner = fresh_org()
    created = _create(client, owner["headers"], owner["org_id"], "snap-dash")
    dashboard_id = created.json()["id"]
    first = client.post(f"/api/dashboards/{dashboard_id}/snapshots", headers=owner["headers"])
    assert first.status_code == 201, first.text
    assert first.json()["provider_calls"] == 0
    with SessionLocal() as db:
        db.add(Invoice(
            organization_id=owner["org_id"],
            invoice_number="snap-1",
            issue_date=date.today(),
            subtotal=Decimal("100.00"),
            total=Decimal("100.00"),
        ))
        db.commit()
    second = client.post(f"/api/dashboards/{dashboard_id}/snapshots", headers=owner["headers"])
    assert second.status_code == 201, second.text
    assert first.json()["id"] == second.json()["id"]
    assert first.json()["content_sha256"] != second.json()["content_sha256"]
    with SessionLocal() as db:
        assert db.query(PublishedSnapshot).filter_by(dashboard_id=dashboard_id).count() == 1
        stored = db.query(PublishedSnapshot).filter_by(dashboard_id=dashboard_id).one()
        assert stored.content_sha256 == second.json()["content_sha256"]
        assert db.query(PipelineRun).filter_by(
            organization_id=owner["org_id"], step="snapshot", run_day=date.today(),
        ).count() == 1


def test_dashboard_package_does_not_import_a_provider():
    root = Path("src/cfo/services/dashboards")
    files = list(root.glob("*.py")) + [Path("src/cfo/api/routes/client_dashboards.py")]
    banned = ("sumit_integration", "open_finance", "httpx", "financy")
    for path in files:
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = []
                if isinstance(node, ast.ImportFrom):
                    names.append(node.module or "")
                    names.extend(alias.name for alias in node.names)
                else:
                    names.extend(alias.name for alias in node.names)
                blob = " ".join(names)
                assert not any(word in blob for word in banned), path


def test_legacy_admin_role_without_a_live_admin_membership_is_404(client, fresh_org):
    owner = fresh_org()
    created = _create(client, owner["headers"], owner["org_id"], "membership-dash")
    assert created.status_code == 201, created.text
    dashboard_id = created.json()["id"]
    with SessionLocal() as db:
        user = User(
            organization_id=owner["org_id"],
            email=f"legacy-admin-{owner['org_id']}@example.com",
            password_hash="x",
            full_name="Legacy Admin",
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
    denied = client.get(
        f"/api/dashboards/{dashboard_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert denied.status_code == 404


def test_office_admin_needs_an_active_management_link(client, fresh_org):
    office = fresh_org()
    client_org = fresh_org()
    refused = _create(client, office["headers"], client_org["org_id"], "office-unlinked")
    assert refused.status_code == 404
    with SessionLocal() as db:
        db.add(SumitCompany(
            office_organization_id=office["org_id"],
            company_id="844329067",
            name="Client file",
            status="active",
            target_organization_id=client_org["org_id"],
        ))
        db.commit()
    created = client.post("/api/dashboards", headers=office["headers"], json={
        "primary_organization_id": client_org["org_id"],
        "office_organization_id": office["org_id"],
        "slug": "office-linked",
        "title": "תיק לקוח",
    })
    assert created.status_code == 201, created.text
    dashboard_id = created.json()["id"]
    with SessionLocal() as db:
        accountant = User(
            organization_id=client_org["org_id"],
            email=f"office-admin-{office['org_id']}@example.com",
            password_hash="x",
            full_name="Office Admin",
            role=UserRole.ADMIN,
            is_active=True,
            token_version=0,
        )
        db.add(accountant)
        db.flush()
        db.add(OrganizationMembership(
            organization_id=office["org_id"],
            user_id=accountant.id,
            role=UserRole.ADMIN,
            status="active",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        ))
        db.commit()
        accountant_id = accountant.id
    headers = {"Authorization": f"Bearer {create_access_token({'sub': str(accountant_id)})}"}
    allowed = client.get(f"/api/dashboards/{dashboard_id}", headers=headers)
    assert allowed.status_code == 200, allowed.text
    with SessionLocal() as db:
        row = db.query(SumitCompany).filter_by(target_organization_id=client_org["org_id"]).one()
        row.status = "inactive"
        db.commit()
    closed = client.get(f"/api/dashboards/{dashboard_id}", headers=headers)
    assert closed.status_code == 404


def test_public_rate_limit_uses_its_own_table_and_the_leftmost_forwarded_for(client, fresh_org):
    from starlette.requests import Request

    from cfo.api.routes.client_dashboards import _claim_public_limit

    def _request(forwarded: str) -> Request:
        return Request({
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/",
            "raw_path": b"/",
            "query_string": b"",
            "headers": [(b"x-forwarded-for", forwarded.encode())],
            "client": ("10.1.1.1", 1234),
            "server": ("test", 80),
        })

    with SessionLocal() as db:
        db.add(DashboardRateLimit(
            scope_key="stale",
            window_kind="minute",
            window_start=datetime.utcnow() - timedelta(days=2),
            used=1,
        ))
        db.commit()
        for _ in range(120):
            assert _claim_public_limit(db, _request("203.0.113.9, 10.1.1.1"), "rate-slug") is None
        blocked = _claim_public_limit(db, _request("203.0.113.9, 10.9.9.9"), "rate-slug")
        assert blocked is not None and blocked.status_code == 429
        other = _claim_public_limit(db, _request("203.0.113.8, 10.1.1.1"), "rate-slug")
        assert other is None
        assert db.query(DashboardRateLimit).filter_by(scope_key="stale").count() == 0
        assert db.query(ProviderRequestBudget).filter_by(provider="dashboard_public").count() == 0
        assert db.query(DashboardRateLimit).count() >= 1


def test_vercel_sets_a_secure_share_cookie_and_the_cookie_secret_is_optional(client, fresh_org, monkeypatch):
    owner = fresh_org()
    created = _create(client, owner["headers"], owner["org_id"], "cookie-dash")
    dashboard_id = created.json()["id"]
    client.patch(
        f"/api/dashboards/{dashboard_id}", headers=owner["headers"], json={"status": "active"},
    )
    minted = client.post(
        f"/api/dashboards/{dashboard_id}/share-links", headers=owner["headers"], json={},
    )
    token = minted.json()["token"]
    monkeypatch.setenv("VERCEL", "1")
    opened = client.post("/api/public/d/cookie-dash/session", json={"token": token})
    assert opened.status_code == 200, opened.text
    cookie = opened.headers["set-cookie"].lower()
    assert "secure" in cookie
    monkeypatch.delenv("VERCEL", raising=False)
    from cfo.config import settings
    monkeypatch.setattr(settings, "dashboard_cookie_secret", "dedicated-dashboard-secret")
    hidden = client.get("/api/public/d/cookie-dash")
    assert hidden.status_code == 404
    again = client.post("/api/public/d/cookie-dash/session", json={"token": token})
    assert again.status_code == 200, again.text
    visible = client.get("/api/public/d/cookie-dash")
    assert visible.status_code == 200, visible.text


def test_duplicate_slug_is_a_conflict(client, fresh_org):
    owner = fresh_org()
    assert _create(client, owner["headers"], owner["org_id"], "same-slug").status_code == 201
    again = _create(client, owner["headers"], owner["org_id"], "same-slug")
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "slug_taken"
