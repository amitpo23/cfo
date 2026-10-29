"""An active org member, including a viewer, can read that org's /d/:slug.

Non-members stay blocked. Edit stays with roles that may change the plan.
"""
from cfo.auth import create_access_token
from cfo.database import SessionLocal
from cfo.models import User, UserRole
from cfo.services import membership_service


def _activate(client, headers, dashboard_id):
    response = client.patch(
        f"/api/dashboards/{dashboard_id}", headers=headers, json={"status": "active"},
    )
    assert response.status_code == 200, response.text


def _viewer(org_id: int, admin_id: int, email: str) -> dict:
    db = SessionLocal()
    try:
        viewer = User(
            email=email, password_hash="x", full_name="Yuval",
            role=UserRole.VIEWER, organization_id=org_id, is_active=True,
        )
        db.add(viewer)
        db.flush()
        membership_service.grant(
            db, organization_id=org_id, user_id=viewer.id, role=UserRole.VIEWER,
            granted_by_user_id=admin_id, status="active",
        )
        db.commit()
        token = create_access_token({"sub": viewer.id, "role": UserRole.VIEWER.value})
        return {"headers": {"Authorization": f"Bearer {token}", "X-Active-Org-Id": str(org_id)}, "id": viewer.id}
    finally:
        db.close()


def test_viewer_reads_members_and_link_dashboards_for_their_org(client, fresh_org):
    owner = fresh_org()
    db = SessionLocal()
    try:
        admin = db.query(User).filter_by(organization_id=owner["org_id"]).one()
        admin_id = admin.id
    finally:
        db.close()
    viewer = _viewer(owner["org_id"], admin_id, f"viewer-{owner['org_id']}@example.com")

    members = client.post("/api/dashboards", headers=owner["headers"], json={
        "primary_organization_id": owner["org_id"],
        "slug": f"foodgroup-{owner['org_id']}",
        "title": "Food Group",
        "access_mode": "members",
    })
    assert members.status_code == 201, members.text
    _activate(client, owner["headers"], members.json()["id"])

    link = client.post("/api/dashboards", headers=owner["headers"], json={
        "primary_organization_id": owner["org_id"],
        "slug": f"eliav-{owner['org_id']}",
        "title": "שף אליהב",
        "access_mode": "link",
    })
    assert link.status_code == 201, link.text
    _activate(client, owner["headers"], link.json()["id"])

    for slug in (f"foodgroup-{owner['org_id']}", f"eliav-{owner['org_id']}"):
        meta = client.get(f"/api/dashboards/by-slug/{slug}", headers=viewer["headers"])
        public = client.get(f"/api/public/d/{slug}", headers=viewer["headers"])
        assert meta.status_code == 200, meta.text
        assert meta.json()["role"] == "client_viewer"
        assert meta.json()["can_edit"] is False
        assert public.status_code == 200, public.text
        assert public.json().get("error") is None

    refused = client.put(
        f"/api/dashboards/{members.json()['id']}/plan",
        headers={**viewer["headers"], "If-Match": "null"},
        json={"payload": {}},
    )
    assert refused.status_code == 404, refused.text


def test_non_member_cannot_read_the_org_dashboard(client, fresh_org):
    owner = fresh_org()
    stranger = fresh_org()
    created = client.post("/api/dashboards", headers=owner["headers"], json={
        "primary_organization_id": owner["org_id"],
        "slug": f"closed-{owner['org_id']}",
        "title": "סגור",
        "access_mode": "members",
    })
    _activate(client, owner["headers"], created.json()["id"])

    meta = client.get(f"/api/dashboards/by-slug/closed-{owner['org_id']}", headers=stranger["headers"])
    public = client.get(f"/api/public/d/closed-{owner['org_id']}", headers=stranger["headers"])
    assert meta.status_code == 404
    assert public.status_code == 404
    assert public.json()["error"]["code"] == "not_found"


def test_viewer_cannot_invite(client, fresh_org):
    owner = fresh_org()
    db = SessionLocal()
    try:
        admin = db.query(User).filter_by(organization_id=owner["org_id"]).one()
        admin_id = admin.id
    finally:
        db.close()
    viewer = _viewer(owner["org_id"], admin_id, f"invite-viewer-{owner['org_id']}@example.com")

    listing = client.get("/api/admin/users", headers=viewer["headers"])
    assert listing.status_code == 200, listing.text
    assert any(row["role"] == "viewer" for row in listing.json())

    invited = client.post("/api/admin/memberships/invite", headers=viewer["headers"], json={
        "email": "someone@example.com",
        "role": "user",
    })
    assert invited.status_code == 403, invited.text
