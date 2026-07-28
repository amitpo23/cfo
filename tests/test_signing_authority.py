"""Owner/signatory policy for irreversible actions."""
import pytest

from cfo.auth import create_access_token
from cfo.database import SessionLocal
from cfo.models import IntegrationType, Organization, User, UserRole


def _token_headers(user_id: int, **extra_headers):
    token = create_access_token({"sub": user_id})
    return {
        "Authorization": f"Bearer {token}",
        **extra_headers,
    }


def _create_admin(client, owner, email: str):
    response = client.post(
        "/api/admin/users",
        headers=owner["headers"],
        json={
            "email": email,
            "password": "owner-flow-secret",
            "full_name": "Additional Admin",
            "role": "admin",
            "organization_id": owner["user"]["organization_id"],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _propose(client, headers, *, action_type: str, key: str):
    response = client.post(
        "/api/approvals",
        headers=headers,
        json={
            "action_type": action_type,
            "payload": {"test_key": key},
            "idempotency_key": key,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_self_registered_org_bootstraps_one_owner_authority(client, owner):
    response = client.get(
        "/api/approvals/signing-authorities",
        headers=owner["headers"],
    )

    assert response.status_code == 200, response.text
    matching = [
        row for row in response.json()["items"]
        if row["user_id"] == owner["user"]["id"]
    ]
    assert len(matching) == 1
    assert matching[0]["authority_type"] == "owner"
    assert matching[0]["action_types"] == ["*"]
    assert matching[0]["is_active"] is True


def test_admin_is_not_owner_until_owner_grants_scoped_authority(client, owner):
    admin = _create_admin(
        client,
        owner,
        "signing-authority-admin@example.com",
    )
    admin_headers = _token_headers(admin["id"])

    period_close = _propose(
        client,
        admin_headers,
        action_type="period_close",
        key="signer-test:period-close",
    )
    refused = client.post(
        f"/api/approvals/{period_close['id']}/approve",
        headers=admin_headers,
    )
    assert refused.status_code == 403, refused.text
    assert "signing authority" in refused.json()["detail"].lower()

    grant = client.post(
        "/api/approvals/signing-authorities",
        headers=owner["headers"],
        json={
            "user_id": admin["id"],
            "authority_type": "authorized_signer",
            "action_types": ["payment"],
        },
    )
    assert grant.status_code == 201, grant.text

    payment = _propose(
        client,
        admin_headers,
        action_type="payment",
        key="signer-test:payment",
    )
    approved = client.post(
        f"/api/approvals/{payment['id']}/approve",
        headers=admin_headers,
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"
    assert (
        approved.json()["approved_by_authority_id"]
        == grant.json()["id"]
    )

    still_refused = client.post(
        f"/api/approvals/{period_close['id']}/approve",
        headers=admin_headers,
    )
    assert still_refused.status_code == 403

    deactivate = client.patch(
        f"/api/admin/users/{admin['id']}",
        headers=owner["headers"],
        json={"is_active": False},
    )
    assert deactivate.status_code == 409, deactivate.text
    assert "signing authority" in deactivate.json()["detail"].lower()

    make_viewer = client.patch(
        f"/api/admin/users/{admin['id']}",
        headers=owner["headers"],
        json={"role": "viewer"},
    )
    assert make_viewer.status_code == 409, make_viewer.text
    assert "signing authority" in make_viewer.json()["detail"].lower()


def test_super_admin_cannot_substitute_for_business_owner(client, owner):
    db = SessionLocal()
    try:
        super_admin = User(
            organization_id=None,
            email="signing-super-admin@example.com",
            password_hash="not-used",
            full_name="System Operator",
            role=UserRole.SUPER_ADMIN,
            is_active=True,
        )
        db.add(super_admin)
        db.commit()
        db.refresh(super_admin)
        headers = _token_headers(
            super_admin.id,
            **{
                "X-Active-Org-Id": str(owner["user"]["organization_id"]),
            },
        )
    finally:
        db.close()

    proposal = _propose(
        client,
        headers,
        action_type="refund",
        key="signer-test:super-admin-refund",
    )
    response = client.post(
        f"/api/approvals/{proposal['id']}/approve",
        headers=headers,
    )

    assert response.status_code == 403, response.text
    assert "signing authority" in response.json()["detail"].lower()


def test_last_owner_authority_cannot_be_revoked(client, owner):
    listing = client.get(
        "/api/approvals/signing-authorities",
        headers=owner["headers"],
    )
    owner_authority = next(
        row for row in listing.json()["items"]
        if row["user_id"] == owner["user"]["id"]
    )

    response = client.delete(
        f"/api/approvals/signing-authorities/{owner_authority['id']}",
        headers=owner["headers"],
    )

    assert response.status_code == 409, response.text
    assert "last owner" in response.json()["detail"].lower()


def test_existing_org_requires_explicit_one_time_owner_bootstrap(client):
    db = SessionLocal()
    try:
        organization = Organization(
            name="Existing Before Owner Policy",
            integration_type=IntegrationType.MANUAL,
            is_active=True,
        )
        db.add(organization)
        db.flush()
        admin = User(
            organization_id=organization.id,
            email="existing-owner-bootstrap@example.com",
            password_hash="not-used",
            full_name="Existing Owner",
            role=UserRole.ADMIN,
            is_active=True,
        )
        db.add(admin)
        db.commit()
        db.refresh(admin)
        headers = _token_headers(admin.id)
    finally:
        db.close()

    wrong = client.post(
        "/api/approvals/signing-authorities/bootstrap",
        headers=headers,
        json={"confirmation": "maybe"},
    )
    assert wrong.status_code == 400, wrong.text

    created = client.post(
        "/api/approvals/signing-authorities/bootstrap",
        headers=headers,
        json={"confirmation": "I_AM_AUTHORIZED_OWNER"},
    )
    assert created.status_code == 201, created.text
    assert created.json()["authority_type"] == "owner"
    assert created.json()["user_id"] == admin.id

    replay = client.post(
        "/api/approvals/signing-authorities/bootstrap",
        headers=headers,
        json={"confirmation": "I_AM_AUTHORIZED_OWNER"},
    )
    assert replay.status_code == 409, replay.text
