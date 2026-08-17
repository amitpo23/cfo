"""מחזור חיי חברות חייב להיות שמיש דרך HTTP, לא רק כשירות פנימי."""
from datetime import datetime, timedelta, timezone

from cfo.database import SessionLocal
from cfo.models import AuditLog, OrganizationMembership, User


def _register(client, email: str):
    response = client.post("/api/admin/auth/register", json={
        "email": email, "password": "secret123", "full_name": email,
    })
    assert response.status_code == 201, response.text
    body = response.json()
    return {
        "id": body["user"]["id"],
        "org": body["user"]["organization_id"],
        "headers": {"Authorization": f"Bearer {body['access_token']}"},
    }


def _membership(user_id: int, organization_id: int):
    db = SessionLocal()
    try:
        return db.query(OrganizationMembership).filter(
            OrganizationMembership.user_id == user_id,
            OrganizationMembership.organization_id == organization_id,
        ).one()
    finally:
        db.close()


def test_existing_identity_can_be_invited_accept_and_be_suspended_and_revoked(client):
    admin = _register(client, "http-lifecycle-admin@example.com")
    member = _register(client, "http-lifecycle-member@example.com")
    admin_headers = {
        **admin["headers"], "X-Active-Org-Id": str(admin["org"]),
    }

    invite = client.post(
        "/api/admin/memberships/invite",
        json={"email": "http-lifecycle-member@example.com", "role": "viewer"},
        headers=admin_headers,
    )
    assert invite.status_code == 201, invite.text
    assert _membership(member["id"], admin["org"]).status == "invited"

    accept = client.post(
        "/api/admin/memberships/accept",
        json={"organization_id": admin["org"]},
        headers=member["headers"],
    )
    assert accept.status_code == 200, accept.text
    assert _membership(member["id"], admin["org"]).status == "active"

    suspend = client.post(
        f"/api/admin/memberships/{member['id']}/suspend",
        headers=admin_headers,
    )
    assert suspend.status_code == 200, suspend.text
    assert _membership(member["id"], admin["org"]).status == "suspended"

    reinvite = client.post(
        "/api/admin/memberships/invite",
        json={"email": "http-lifecycle-member@example.com", "role": "viewer"},
        headers=admin_headers,
    )
    assert reinvite.status_code == 201, reinvite.text
    client.post(
        "/api/admin/memberships/accept",
        json={"organization_id": admin["org"]}, headers=member["headers"],
    )

    revoke = client.post(
        f"/api/admin/memberships/{member['id']}/revoke",
        headers=admin_headers,
    )
    assert revoke.status_code == 200, revoke.text
    assert _membership(member["id"], admin["org"]).status == "revoked"

    db = SessionLocal()
    try:
        actions = {
            row.action for row in db.query(AuditLog).filter(
                AuditLog.organization_id == admin["org"],
                AuditLog.entity_type == "OrganizationMembership",
                AuditLog.entity_id == member["id"],
            ).all()
        }
    finally:
        db.close()
    assert {
        "MEMBERSHIP_INVITE", "MEMBERSHIP_ACCEPT", "MEMBERSHIP_SUSPEND",
        "MEMBERSHIP_REVOKE",
    }.issubset(actions)


def test_expired_invitation_cannot_be_accepted(client):
    admin = _register(client, "expired-http-admin@example.com")
    member = _register(client, "expired-http-member@example.com")
    admin_headers = {
        **admin["headers"], "X-Active-Org-Id": str(admin["org"]),
    }
    expired = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()

    invite = client.post(
        "/api/admin/memberships/invite",
        json={
            "email": "expired-http-member@example.com", "role": "viewer",
            "expires_at": expired,
        },
        headers=admin_headers,
    )
    assert invite.status_code == 201, invite.text

    accept = client.post(
        "/api/admin/memberships/accept",
        json={"organization_id": admin["org"]}, headers=member["headers"],
    )

    assert accept.status_code == 409, accept.text


def test_acceptance_cannot_be_performed_for_another_identity(client):
    admin = _register(client, "accept-http-admin@example.com")
    member = _register(client, "accept-http-member@example.com")
    stranger = _register(client, "accept-http-stranger@example.com")
    client.post(
        "/api/admin/memberships/invite",
        json={"email": "accept-http-member@example.com", "role": "viewer"},
        headers={**admin["headers"], "X-Active-Org-Id": str(admin["org"])},
    )

    response = client.post(
        "/api/admin/memberships/accept",
        json={"organization_id": admin["org"], "user_id": member["id"]},
        headers=stranger["headers"],
    )

    assert response.status_code in (403, 422), response.text


def test_organization_admin_cannot_globally_deactivate_an_identity(client):
    admin = _register(client, "no-global-disable-admin@example.com")
    member = _register(client, "no-global-disable-member@example.com")
    headers = {**admin["headers"], "X-Active-Org-Id": str(admin["org"])}
    client.post(
        "/api/admin/memberships/invite",
        json={"email": "no-global-disable-member@example.com", "role": "viewer"},
        headers=headers,
    )

    response = client.patch(
        f"/api/admin/users/{member['id']}", json={"is_active": False},
        headers=headers,
    )
    assert response.status_code == 200, response.text

    db = SessionLocal()
    try:
        assert db.query(User).filter(User.id == member["id"]).one().is_active is True
    finally:
        db.close()
