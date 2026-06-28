"""
TDD tests for admin user management CRUD.
Task 1: Backend - app-User provision + manage roles.

Test order: red → green for each requirement.
"""
import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _register(client, email, password="password123", full_name="Test User"):
    """Register a new user (self-registration path)."""
    resp = client.post("/api/admin/auth/register", json={
        "email": email,
        "password": password,
        "full_name": full_name,
    })
    return resp


def _login(client, email, password):
    """Login and return token."""
    resp = client.post("/api/admin/auth/login", json={
        "email": email,
        "password": password,
    })
    return resp


def _auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# 1. test_create_app_user_success
# ---------------------------------------------------------------------------

def test_create_app_user_success(client, owner):
    """POST /api/admin/users creates an app User, returns 201, fields correct."""
    org_id = owner["user"]["organization_id"]
    payload = {
        "email": "newuser_mgmt_1@example.com",
        "password": "securepass",
        "full_name": "New User",
        "organization_id": org_id,
        "role": "user",
    }
    resp = client.post("/api/admin/users", json=payload, headers=owner["headers"])
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["email"] == payload["email"]
    assert data["full_name"] == payload["full_name"]
    assert data["role"] == "user"
    assert data["organization_id"] == org_id
    assert data["is_active"] is True
    # password must NOT appear in response
    assert "password" not in data
    assert "password_hash" not in data

    # Verify the password hash works — login with the new credentials
    login_resp = _login(client, payload["email"], payload["password"])
    assert login_resp.status_code == 200, login_resp.text


# ---------------------------------------------------------------------------
# 2. test_create_app_user_duplicate_email
# ---------------------------------------------------------------------------

def test_create_app_user_duplicate_email(client, owner):
    """POST /api/admin/users with duplicate email → 409 Conflict."""
    org_id = owner["user"]["organization_id"]
    payload = {
        "email": "dup_mgmt@example.com",
        "password": "securepass",
        "full_name": "Dup User",
        "organization_id": org_id,
    }
    r1 = client.post("/api/admin/users", json=payload, headers=owner["headers"])
    assert r1.status_code == 201, r1.text

    r2 = client.post("/api/admin/users", json=payload, headers=owner["headers"])
    assert r2.status_code == 409, r2.text


# ---------------------------------------------------------------------------
# 3. test_create_app_user_short_password
# ---------------------------------------------------------------------------

def test_create_app_user_short_password(client, owner):
    """POST /api/admin/users with password < 8 chars → 422."""
    org_id = owner["user"]["organization_id"]
    payload = {
        "email": "shortpw_mgmt@example.com",
        "password": "short",
        "full_name": "Short PW",
        "organization_id": org_id,
    }
    resp = client.post("/api/admin/users", json=payload, headers=owner["headers"])
    assert resp.status_code == 422, resp.text


# ---------------------------------------------------------------------------
# 4. test_create_app_user_missing_org
# ---------------------------------------------------------------------------

def test_create_app_user_missing_org(client, owner):
    """POST /api/admin/users with no organization_id → 422."""
    payload = {
        "email": "noorg_mgmt@example.com",
        "password": "securepass",
        "full_name": "No Org",
        # organization_id intentionally omitted
    }
    resp = client.post("/api/admin/users", json=payload, headers=owner["headers"])
    assert resp.status_code == 422, resp.text


# ---------------------------------------------------------------------------
# 5. test_create_app_user_unauthenticated
# ---------------------------------------------------------------------------

def test_create_app_user_unauthenticated(client, owner):
    """POST /api/admin/users without Authorization → 403 (HTTPBearer returns 403)."""
    org_id = owner["user"]["organization_id"]
    payload = {
        "email": "unauth_mgmt@example.com",
        "password": "securepass",
        "full_name": "Unauth",
        "organization_id": org_id,
    }
    resp = client.post("/api/admin/users", json=payload)
    # FastAPI HTTPBearer raises 403 when no token is supplied
    assert resp.status_code in (401, 403), resp.text


# ---------------------------------------------------------------------------
# 6. test_create_app_user_non_admin
# ---------------------------------------------------------------------------

def test_create_app_user_non_admin(client, owner):
    """POST /api/admin/users as a non-admin user → 403."""
    org_id = owner["user"]["organization_id"]
    # Create a regular (non-admin) user via the admin endpoint
    regular_email = "regular_mgmt@example.com"
    create_resp = client.post("/api/admin/users", json={
        "email": regular_email,
        "password": "securepass1",
        "full_name": "Regular",
        "organization_id": org_id,
        "role": "user",
    }, headers=owner["headers"])
    assert create_resp.status_code == 201, create_resp.text

    # Login as the regular user
    login_resp = _login(client, regular_email, "securepass1")
    assert login_resp.status_code == 200, login_resp.text
    regular_token = login_resp.json()["access_token"]

    # Try to create a user as regular user → should be 403
    resp = client.post("/api/admin/users", json={
        "email": "shouldfail_mgmt@example.com",
        "password": "securepass",
        "full_name": "Should Fail",
        "organization_id": org_id,
    }, headers=_auth_headers(regular_token))
    assert resp.status_code == 403, resp.text


# ---------------------------------------------------------------------------
# 7. test_sumit_users_route_still_exists
# ---------------------------------------------------------------------------

def test_sumit_users_route_still_exists(client, owner):
    """POST /api/admin/sumit-users route still exists after rename (may fail with SUMIT error, not 404)."""
    resp = client.post("/api/admin/sumit-users", json={
        "email": "sumituser@example.com",
        "name": "SUMIT User",
    }, headers=owner["headers"])
    # Route exists — must NOT be 404 (could be 400/422/500 from SUMIT call)
    assert resp.status_code != 404, f"Route does not exist: {resp.status_code} {resp.text}"


# ---------------------------------------------------------------------------
# 8. test_patch_user_role_change
# ---------------------------------------------------------------------------

def test_patch_user_role_change(client, owner):
    """PATCH /api/admin/users/{id} changes the user's role."""
    org_id = owner["user"]["organization_id"]
    # Create a user to patch
    create_resp = client.post("/api/admin/users", json={
        "email": "patch_role_mgmt@example.com",
        "password": "securepass",
        "full_name": "Patch Role",
        "organization_id": org_id,
        "role": "user",
    }, headers=owner["headers"])
    assert create_resp.status_code == 201, create_resp.text
    user_id = create_resp.json()["id"]

    # Patch the role
    patch_resp = client.patch(f"/api/admin/users/{user_id}", json={
        "role": "accountant",
    }, headers=owner["headers"])
    assert patch_resp.status_code == 200, patch_resp.text
    assert patch_resp.json()["role"] == "accountant"


# ---------------------------------------------------------------------------
# 9. test_patch_self_deactivation_blocked
# ---------------------------------------------------------------------------

def test_patch_self_deactivation_blocked(client, owner):
    """PATCH own user with is_active=False → 422."""
    owner_id = owner["user"]["id"]
    resp = client.patch(f"/api/admin/users/{owner_id}", json={
        "is_active": False,
    }, headers=owner["headers"])
    assert resp.status_code == 422, resp.text


# ---------------------------------------------------------------------------
# 10. test_patch_self_role_change_blocked
# ---------------------------------------------------------------------------

def test_patch_self_role_change_blocked(client, owner):
    """PATCH own user changing role → 422."""
    owner_id = owner["user"]["id"]
    resp = client.patch(f"/api/admin/users/{owner_id}", json={
        "role": "user",
    }, headers=owner["headers"])
    assert resp.status_code == 422, resp.text


# ---------------------------------------------------------------------------
# 11. test_patch_last_admin_protection
# ---------------------------------------------------------------------------

def test_patch_last_admin_protection(client, owner, fresh_org, sec_actors):
    """
    Last-admin protection: cannot demote the last active admin of an org → 409.
    A SUPER_ADMIN can operate cross-org, so use them as the caller — this verifies
    the last-admin guard fires even for SUPER_ADMIN.
    """
    # fresh_org creates a new isolated org; its creator is an ADMIN
    iso = fresh_org()

    # Get the iso org's admin user id (the user who registered)
    me_resp = client.get("/api/admin/auth/me", headers=iso["headers"])
    assert me_resp.status_code == 200, me_resp.text
    iso_admin_id = me_resp.json()["id"]

    # SUPER_ADMIN tries to demote the sole admin of the iso org to role=user → 409
    resp = client.patch(f"/api/admin/users/{iso_admin_id}", json={
        "role": "user",
    }, headers=sec_actors["super_admin_headers"])
    assert resp.status_code == 409, f"Expected 409 (last admin protection), got {resp.status_code}: {resp.text}"


# ---------------------------------------------------------------------------
# 12. test_delete_soft_deactivates
# ---------------------------------------------------------------------------

def test_delete_soft_deactivates(client, owner):
    """DELETE /api/admin/users/{id} → 204, user becomes inactive."""
    org_id = owner["user"]["organization_id"]
    # Create user to delete
    create_resp = client.post("/api/admin/users", json={
        "email": "delete_soft_mgmt@example.com",
        "password": "securepass",
        "full_name": "Delete Me",
        "organization_id": org_id,
        "role": "user",
    }, headers=owner["headers"])
    assert create_resp.status_code == 201, create_resp.text
    user_id = create_resp.json()["id"]

    # Delete the user
    del_resp = client.delete(f"/api/admin/users/{user_id}", headers=owner["headers"])
    assert del_resp.status_code == 204, del_resp.text

    # Confirm user is now inactive (cannot login)
    login_resp = _login(client, "delete_soft_mgmt@example.com", "securepass")
    assert login_resp.status_code == 403, f"Expected 403 (inactive), got {login_resp.status_code}"


# ---------------------------------------------------------------------------
# 13. test_delete_self_blocked
# ---------------------------------------------------------------------------

def test_delete_self_blocked(client, owner):
    """DELETE own user → 422."""
    owner_id = owner["user"]["id"]
    resp = client.delete(f"/api/admin/users/{owner_id}", headers=owner["headers"])
    assert resp.status_code == 422, resp.text


# ---------------------------------------------------------------------------
# 14. test_delete_last_admin_blocked
# ---------------------------------------------------------------------------

def test_delete_last_admin_blocked(client, owner, fresh_org, sec_actors):
    """
    DELETE the last active admin of an org → 409.
    Strategy: use fresh_org to create an isolated org with exactly 1 admin.
    SUPER_ADMIN (cross-org allowed) tries to delete that sole admin → 409.
    """
    iso = fresh_org()

    # Get the iso org's admin user id
    me_resp = client.get("/api/admin/auth/me", headers=iso["headers"])
    assert me_resp.status_code == 200, me_resp.text
    iso_admin_id = me_resp.json()["id"]

    # SUPER_ADMIN tries to delete the sole admin of the iso org → 409
    resp = client.delete(f"/api/admin/users/{iso_admin_id}", headers=sec_actors["super_admin_headers"])
    assert resp.status_code == 409, f"Expected 409 (last admin protection), got {resp.status_code}: {resp.text}"


# ===========================================================================
# Security: Multi-tenancy / privilege-escalation guards
# ===========================================================================
#
# Helper fixture: create an admin in org B and a super_admin we can use.
#
# We need:
#  - org_b_admin: ADMIN of a second (isolated) org
#  - super_admin_headers: headers for a SUPER_ADMIN user
#
# Strategy for super_admin: register fresh org → that user is ADMIN → use the
# DB (via SessionLocal) to promote to SUPER_ADMIN and re-issue a token by
# logging in (role claim is read from DB on each login).
#

@pytest.fixture(scope="session")
def sec_actors(client, owner):
    """
    Returns dict with:
      org_b_admin:      headers + user info for an ADMIN in org B
      super_admin:      headers for a SUPER_ADMIN (promoted from a fresh org)
      owner_org_id:     organization_id of the owner (org A)
    """
    from cfo.database import SessionLocal
    from cfo.models import User, UserRole

    # Create org B by registering a new user (they become ADMIN of a new org)
    org_b_resp = client.post("/api/admin/auth/register", json={
        "email": "sec_org_b_admin@example.com",
        "password": "secret123",
        "full_name": "Org B Admin",
    })
    assert org_b_resp.status_code == 201, org_b_resp.text
    org_b_data = org_b_resp.json()
    org_b_headers = {"Authorization": f"Bearer {org_b_data['access_token']}"}
    org_b_user = org_b_data["user"]
    org_b_id = org_b_user["organization_id"]

    # Create a fresh user to be promoted to SUPER_ADMIN
    sa_resp = client.post("/api/admin/auth/register", json={
        "email": "sec_super_admin@example.com",
        "password": "secret123",
        "full_name": "Super Admin",
    })
    assert sa_resp.status_code == 201, sa_resp.text
    sa_data = sa_resp.json()
    sa_user_id = sa_data["user"]["id"]

    # Promote directly via DB
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.id == sa_user_id).first()
        u.role = UserRole.SUPER_ADMIN
        db.commit()
    finally:
        db.close()

    # Login again to get a fresh token reflecting SUPER_ADMIN role
    login_resp = client.post("/api/admin/auth/login", json={
        "email": "sec_super_admin@example.com",
        "password": "secret123",
    })
    assert login_resp.status_code == 200, login_resp.text
    sa_token = login_resp.json()["access_token"]
    sa_headers = {"Authorization": f"Bearer {sa_token}"}

    return {
        "org_b_admin_headers": org_b_headers,
        "org_b_admin_user": org_b_user,
        "org_b_id": org_b_id,
        "super_admin_headers": sa_headers,
        "super_admin_email": "sec_super_admin@example.com",
        "owner_org_id": owner["user"]["organization_id"],
    }


# ---------------------------------------------------------------------------
# SEC-1. POST /users cross-org blocked for non-super ADMIN
# ---------------------------------------------------------------------------

def test_create_user_cross_org_blocked(client, owner, sec_actors):
    """ADMIN of org A cannot create a user in org B → 403."""
    org_b_id = sec_actors["org_b_id"]
    resp = client.post("/api/admin/users", json={
        "email": "sec_cross_org_create@example.com",
        "password": "securepass",
        "full_name": "Cross Org",
        "organization_id": org_b_id,
        "role": "user",
    }, headers=owner["headers"])
    assert resp.status_code == 403, f"Expected 403, got {resp.status_code}: {resp.text}"


# ---------------------------------------------------------------------------
# SEC-2. POST /users privilege escalation to super_admin blocked
# ---------------------------------------------------------------------------

def test_create_user_super_admin_role_blocked(client, owner):
    """ADMIN cannot create a user with role=super_admin → 403."""
    org_id = owner["user"]["organization_id"]
    resp = client.post("/api/admin/users", json={
        "email": "sec_escalate_create@example.com",
        "password": "securepass",
        "full_name": "Escalate",
        "organization_id": org_id,
        "role": "super_admin",
    }, headers=owner["headers"])
    assert resp.status_code == 403, f"Expected 403, got {resp.status_code}: {resp.text}"


# ---------------------------------------------------------------------------
# SEC-3. PATCH user in org B blocked for non-super ADMIN
# ---------------------------------------------------------------------------

def test_patch_cross_org_blocked(client, owner, sec_actors):
    """ADMIN of org A cannot PATCH a user belonging to org B → 403."""
    org_b_user = sec_actors["org_b_admin_user"]
    resp = client.patch(f"/api/admin/users/{org_b_user['id']}", json={
        "full_name": "Hacked Name",
    }, headers=owner["headers"])
    assert resp.status_code == 403, f"Expected 403, got {resp.status_code}: {resp.text}"


# ---------------------------------------------------------------------------
# SEC-4. PATCH to set role=super_admin blocked for non-super ADMIN
# ---------------------------------------------------------------------------

def test_patch_escalate_to_super_admin_blocked(client, owner):
    """ADMIN cannot PATCH a user to role=super_admin → 403."""
    org_id = owner["user"]["organization_id"]
    # Create a regular user in same org
    create_resp = client.post("/api/admin/users", json={
        "email": "sec_escalate_patch_target@example.com",
        "password": "securepass",
        "full_name": "Escalate Target",
        "organization_id": org_id,
        "role": "user",
    }, headers=owner["headers"])
    assert create_resp.status_code == 201, create_resp.text
    user_id = create_resp.json()["id"]

    resp = client.patch(f"/api/admin/users/{user_id}", json={
        "role": "super_admin",
    }, headers=owner["headers"])
    assert resp.status_code == 403, f"Expected 403, got {resp.status_code}: {resp.text}"


# ---------------------------------------------------------------------------
# SEC-5. PATCH a super_admin user blocked for non-super ADMIN
# ---------------------------------------------------------------------------

def test_patch_super_admin_user_blocked(client, owner, sec_actors):
    """ADMIN cannot PATCH a user who is a SUPER_ADMIN → 403."""
    # sec_actors.super_admin user id
    sa_me = client.get("/api/admin/auth/me", headers=sec_actors["super_admin_headers"])
    assert sa_me.status_code == 200
    sa_user_id = sa_me.json()["id"]

    resp = client.patch(f"/api/admin/users/{sa_user_id}", json={
        "full_name": "Hacked SA",
    }, headers=owner["headers"])
    assert resp.status_code == 403, f"Expected 403, got {resp.status_code}: {resp.text}"


# ---------------------------------------------------------------------------
# SEC-6. DELETE user in org B blocked for non-super ADMIN
# ---------------------------------------------------------------------------

def test_delete_cross_org_blocked(client, owner, sec_actors):
    """ADMIN of org A cannot DELETE a user belonging to org B → 403."""
    org_b_user = sec_actors["org_b_admin_user"]
    resp = client.delete(f"/api/admin/users/{org_b_user['id']}", headers=owner["headers"])
    assert resp.status_code == 403, f"Expected 403, got {resp.status_code}: {resp.text}"


# ---------------------------------------------------------------------------
# SEC-7. SUPER_ADMIN can create in any org with any role (sanity)
# ---------------------------------------------------------------------------

def test_super_admin_can_create_cross_org(client, sec_actors):
    """SUPER_ADMIN can create a user in any org (sanity)."""
    org_b_id = sec_actors["org_b_id"]
    resp = client.post("/api/admin/users", json={
        "email": "sec_sa_cross_create@example.com",
        "password": "securepass",
        "full_name": "SA Cross Create",
        "organization_id": org_b_id,
        "role": "user",
    }, headers=sec_actors["super_admin_headers"])
    assert resp.status_code == 201, f"Expected 201, got {resp.status_code}: {resp.text}"


def test_super_admin_can_assign_super_admin_role(client, sec_actors):
    """SUPER_ADMIN can create a user with role=super_admin (sanity)."""
    org_b_id = sec_actors["org_b_id"]
    resp = client.post("/api/admin/users", json={
        "email": "sec_sa_role_assign@example.com",
        "password": "securepass",
        "full_name": "SA Role Assign",
        "organization_id": org_b_id,
        "role": "super_admin",
    }, headers=sec_actors["super_admin_headers"])
    assert resp.status_code == 201, f"Expected 201, got {resp.status_code}: {resp.text}"


def test_super_admin_can_patch_cross_org(client, sec_actors):
    """SUPER_ADMIN can PATCH a user in any org (sanity)."""
    org_b_user = sec_actors["org_b_admin_user"]
    resp = client.patch(f"/api/admin/users/{org_b_user['id']}", json={
        "full_name": "SA Patched",
    }, headers=sec_actors["super_admin_headers"])
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
