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

def test_patch_last_admin_protection(client, owner, fresh_org):
    """
    Last-admin protection: cannot demote the last active admin of an org → 409.
    Strategy: use fresh_org to create an isolated org with exactly 1 admin.
    Then owner (acting as caller) patches that sole admin to role=user → 409.
    """
    # fresh_org creates a new isolated org; its creator is an ADMIN
    iso = fresh_org()
    iso_token = iso["headers"]["Authorization"].split(" ")[1]

    # Get the iso org's admin user id (the user who registered)
    me_resp = client.get("/api/admin/auth/me", headers=iso["headers"])
    assert me_resp.status_code == 200, me_resp.text
    iso_admin_id = me_resp.json()["id"]
    iso_org_id = me_resp.json()["organization_id"]

    # owner tries to demote the sole admin of the iso org to role=user → 409
    resp = client.patch(f"/api/admin/users/{iso_admin_id}", json={
        "role": "user",
    }, headers=owner["headers"])
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

def test_delete_last_admin_blocked(client, owner, fresh_org):
    """
    DELETE the last active admin of an org → 409.
    Strategy: use fresh_org to create an isolated org with exactly 1 admin.
    owner deletes that sole admin → 409.
    """
    iso = fresh_org()

    # Get the iso org's admin user id
    me_resp = client.get("/api/admin/auth/me", headers=iso["headers"])
    assert me_resp.status_code == 200, me_resp.text
    iso_admin_id = me_resp.json()["id"]

    # owner tries to delete the sole admin of the iso org → 409
    resp = client.delete(f"/api/admin/users/{iso_admin_id}", headers=owner["headers"])
    assert resp.status_code == 409, f"Expected 409 (last admin protection), got {resp.status_code}: {resp.text}"
