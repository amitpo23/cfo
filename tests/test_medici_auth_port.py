"""Medici auth port — Google OIDC בזרימת שרת, RBAC, הרשאות מייל, /d.

אין רשת: JWKS ו-token endpoint של Google מוחלפים ב-monkeypatch, ומפתח
RSA נוצר מקומית. ראו docs/AUTH_MEDICI_PORT.md.
"""
from __future__ import annotations

import base64
import hashlib
import time
import uuid
from urllib.parse import parse_qs, urlparse

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from jose import jwk, jwt

from cfo.api import app
from cfo.auth import get_password_hash
from cfo.config import settings
from cfo.database import SessionLocal
from cfo.models import (
    AuditLog, ClientDashboard, DashboardAccessGrant, OrganizationMembership, User,
    UserRole,
)
from cfo.services import google_oidc
from cfo.services.rbac import (
    ENDPOINT_CAPABILITIES, MEDICI_ROLE_ALIASES, ROLE_CONFIG, PermissionChecker,
)

CLIENT_ID = "test-client.apps.googleusercontent.com"
KID = "test-kid-1"


def _rsa_pem():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()


PRIVATE_PEM = _rsa_pem()
OTHER_PEM = _rsa_pem()


def _public_jwk(pem: str, kid: str) -> dict:
    data = jwk.construct(pem, "RS256").public_key().to_dict()
    data.update({"kid": kid, "use": "sig", "alg": "RS256"})
    return data


def _id_token(email: str, *, nonce: str | None = None, aud: str = CLIENT_ID,
              iss: str = "https://accounts.google.com", exp_delta: int = 3600,
              iat_delta: int = 0, email_verified=True, pem: str = PRIVATE_PEM,
              kid: str = KID, name: str = "Test Person") -> str:
    now = int(time.time())
    claims = {
        "iss": iss, "aud": aud, "sub": f"sub-{email}", "email": email,
        "email_verified": email_verified, "iat": now + iat_delta,
        "exp": now + exp_delta, "name": name,
    }
    if nonce is not None:
        claims["nonce"] = nonce
    return jwt.encode(claims, pem, algorithm="RS256", headers={"kid": kid})


@pytest.fixture(autouse=True)
def _tables(client):
    """ה-fixture ``client`` (session) מריץ את ה-lifespan שיוצר את הטבלאות."""
    yield


@pytest.fixture
def google(monkeypatch):
    """Google מוגדר + JWKS מקומי. מחזיר אובייקט לשליטה על ה-token endpoint."""
    monkeypatch.setattr(settings, "google_client_id", CLIENT_ID)
    monkeypatch.setattr(settings, "google_client_secret", "test-secret")
    monkeypatch.setattr(settings, "auth_url", "https://rezef.example")
    google_oidc._reset_jwks_cache()
    calls = {"jwks": 0, "exchange": []}

    def fake_jwks():
        calls["jwks"] += 1
        return {"keys": [_public_jwk(PRIVATE_PEM, KID)]}, 3600

    monkeypatch.setattr(google_oidc, "fetch_jwks", fake_jwks)
    state = {"token_response": None}

    def fake_exchange(code, verifier):
        calls["exchange"].append((code, verifier))
        return state["token_response"]

    monkeypatch.setattr(google_oidc, "exchange_code", fake_exchange)
    yield type("G", (), {"calls": calls, "state": state})
    google_oidc._reset_jwks_cache()


def _new_client() -> TestClient:
    return TestClient(app, base_url="http://testserver")


def _start(client, return_to=None):
    params = {"return_to": return_to} if return_to else {}
    resp = client.get("/api/auth/signin/google", params=params, follow_redirects=False)
    assert resp.status_code == 302, resp.text
    query = parse_qs(urlparse(resp.headers["location"]).query)
    cookie = resp.cookies.get(google_oidc.STATE_COOKIE)
    assert cookie
    return resp, query, cookie


def _callback(client, cookie, state, code="auth-code"):
    return client.get(
        "/api/auth/callback/google",
        params={"code": code, "state": state},
        headers={"Cookie": f"{google_oidc.STATE_COOKIE}={cookie}"},
        follow_redirects=False,
    )


def _google_login(google, email, **token_kwargs):
    """זרימה מלאה; מחזיר (redirect_response, token_or_None)."""
    client = _new_client()
    _, query, cookie = _start(client)
    nonce = token_kwargs.pop("nonce", query["nonce"][0])
    google.state["token_response"] = {
        "id_token": _id_token(email, nonce=nonce, **token_kwargs),
        "access_token": None,
    }
    resp = _callback(client, cookie, query["state"][0])
    assert resp.status_code == 302, resp.text
    location = resp.headers["location"]
    if "/auth/complete#" not in location:
        return resp, None
    fragment = parse_qs(urlparse(location).fragment)
    exchanged = _exchange(client, resp, fragment["code"][0])
    assert exchanged.status_code == 200, exchanged.text
    return resp, exchanged.json()["access_token"]


BINDING = "rezef_login_binding"


def _exchange(client, callback_resp, code, binding=None):
    value = binding if binding is not None else callback_resp.cookies.get(BINDING)
    headers = {"Cookie": f"{BINDING}={value}"} if value else {}
    return client.post("/api/auth/google/exchange", json={"code": code}, headers=headers)


def _auth_error(resp) -> str | None:
    location = resp.headers["location"]
    return parse_qs(urlparse(location).query).get("auth_error", [None])[0]


def _make_user(email, role=UserRole.USER, password="secret123", active=True) -> int:
    db = SessionLocal()
    try:
        user = User(email=email, password_hash=get_password_hash(password), full_name="T",
                    role=role, is_active=active, organization_id=None)
        db.add(user)
        db.commit()
        return user.id
    finally:
        db.close()


def _login(client, email, password="secret123"):
    return client.post("/api/admin/auth/login", json={"email": email, "password": password})


def _bearer(token):
    return {"Authorization": f"Bearer {token}"}


def _audit_actions(since_id: int) -> list[AuditLog]:
    db = SessionLocal()
    try:
        return db.query(AuditLog).filter(AuditLog.id > since_id).order_by(AuditLog.id).all()
    finally:
        db.close()


def _max_audit_id() -> int:
    db = SessionLocal()
    try:
        row = db.query(AuditLog).order_by(AuditLog.id.desc()).first()
        return row.id if row else 0
    finally:
        db.close()


@pytest.fixture
def super_admin(client):
    email = f"super-{uuid.uuid4().hex[:8]}@example.com"
    _make_user(email, role=UserRole.SUPER_ADMIN)
    resp = _login(client, email)
    assert resp.status_code == 200, resp.text
    return {"email": email, "headers": _bearer(resp.json()["access_token"])}


def _uniq(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}@example.com"


# --------------------------------------------------------------------- #
# RBAC (פורט של permissions.ts)
# --------------------------------------------------------------------- #
def test_rbac_role_config_keeps_medici_shape():
    for role, config in ROLE_CONFIG.items():
        assert {"description", "scopes", "capabilities", "constraints"} <= set(config), role
    for key, endpoint in ENDPOINT_CAPABILITIES.items():
        assert {"description", "method", "path", "required_scopes_any", "audit"} <= set(endpoint), key
    assert MEDICI_ROLE_ALIASES == {"admin": "super_admin", "booker": "viewer"}
    for scope in ("dashboard:read", "org:read", "org:admin", "audit:read", "access:grant"):
        assert any(scope in c["scopes"] for c in ROLE_CONFIG.values()), scope


def test_rbac_scope_checks():
    check = PermissionChecker.can_access_endpoint
    assert check("super_admin", "ADMIN.ACCESS.IMPORT").allowed
    assert check("admin", "ADMIN.ACCESS.GRANT").allowed
    denied = check("admin", "ADMIN.ACCESS.IMPORT")
    assert not denied.allowed  # missing endpoints:* — import is platform-only
    viewer = check("viewer", "ADMIN.ACCESS.GRANT")
    assert not viewer.allowed and "access:grant" in viewer.missing_scopes
    assert check("viewer", "DASHBOARD.READ").allowed
    assert not check("client_viewer", "ORG.READ").allowed
    assert not check(None, "DASHBOARD.READ").allowed
    assert not check("super_admin", "NO.SUCH.ENDPOINT").allowed
    assert PermissionChecker.has_any_scope(["a"], ["b", "a"])
    assert not PermissionChecker.has_all_scopes(["a"], ["a", "b"])
    assert PermissionChecker.has_capability("admin", "CAP_ACCESS_GRANT")
    assert "ADMIN.ACCESS.IMPORT" not in PermissionChecker.accessible_endpoints("admin")


def test_no_medici_demo_credentials_were_ported():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1] / "src" / "cfo"
    text = "".join(p.read_text(encoding="utf-8") for p in root.rglob("*.py"))
    for needle in ("admin-token-123", "booker-token-456", "admin@example.com", "admin123"):
        assert needle not in text, needle


# --------------------------------------------------------------------- #
# אימות ID token מקומי
# --------------------------------------------------------------------- #
def _verify(token, nonce="n-1"):
    return google_oidc.verify_id_token(token, expected_nonce=nonce)


def test_valid_id_token_is_accepted(google):
    identity = _verify(_id_token("Person@Example.com", nonce="n-1"))
    assert identity.email == "person@example.com"


@pytest.mark.parametrize("kwargs,reason", [
    ({"aud": "someone-else.apps.googleusercontent.com"}, "bad_audience"),
    ({"iss": "https://evil.example.com"}, "bad_issuer"),
    ({"exp_delta": -3600}, "token_expired"),
    ({"iat_delta": 3600}, "bad_iat"),
    ({"email_verified": False}, "email_not_verified"),
    ({"email_verified": "false"}, "email_not_verified"),
    ({"nonce": "other-nonce"}, "nonce_mismatch"),
    ({"pem": OTHER_PEM}, "bad_signature"),
    ({"kid": "rotated-away"}, "unknown_signing_key"),
])
def test_bad_id_tokens_are_rejected(google, kwargs, reason):
    kwargs = dict(kwargs)
    nonce = kwargs.pop("nonce", "n-1")
    token = _id_token("bad@example.com", nonce=nonce, **kwargs)
    with pytest.raises(google_oidc.GoogleAuthError) as info:
        _verify(token)
    assert info.value.reason == reason


def test_issuer_without_scheme_is_accepted(google):
    assert _verify(_id_token("x@example.com", nonce="n-1", iss="accounts.google.com"))


def test_jwks_is_cached_and_refetched_once_on_unknown_kid(google):
    _verify(_id_token("a@example.com", nonce="n-1"))
    _verify(_id_token("b@example.com", nonce="n-1"))
    assert google.calls["jwks"] == 1
    with pytest.raises(google_oidc.GoogleAuthError):
        _verify(_id_token("c@example.com", nonce="n-1", kid="new-kid"))
    assert google.calls["jwks"] == 2


# --------------------------------------------------------------------- #
# זרימת השרת
# --------------------------------------------------------------------- #
def test_signin_redirects_with_state_nonce_pkce_and_hardened_cookie(google):
    client = _new_client()
    resp, query, _ = _start(client, return_to="//evil.example.com/x")
    assert resp.headers["location"].startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert query["client_id"] == [CLIENT_ID]
    assert query["redirect_uri"] == ["https://rezef.example/api/auth/callback/google"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["state"][0] and query["nonce"][0] and query["code_challenge"][0]
    set_cookie = resp.headers["set-cookie"].lower()
    for flag in ("httponly", "secure", "samesite=lax", "path=/api/auth", "max-age=600"):
        assert flag in set_cookie, flag
    saved = google_oidc.read_state_cookie(resp.cookies.get(google_oidc.STATE_COOKIE), query["state"][0])
    assert saved["rt"] == "/"  # open redirect neutralized
    challenge = base64.urlsafe_b64encode(hashlib.sha256(saved["cv"].encode()).digest()).decode().rstrip("=")
    assert query["code_challenge"] == [challenge]


def test_redirect_base_never_comes_from_host_header(google):
    client = _new_client()
    resp = client.get("/api/auth/signin/google", headers={"Host": "evil.example.com"},
                      follow_redirects=False)
    query = parse_qs(urlparse(resp.headers["location"]).query)
    assert query["redirect_uri"] == ["https://rezef.example/api/auth/callback/google"]


def test_signin_without_google_config_reports_hebrew_error_code(monkeypatch):
    monkeypatch.setattr(settings, "google_client_id", None)
    monkeypatch.setattr(settings, "google_client_secret", None)
    monkeypatch.setattr(settings, "auth_url", "https://rezef.example")
    resp = _new_client().get("/api/auth/signin/google", follow_redirects=False)
    assert resp.status_code == 302
    assert _auth_error(resp) == "not_configured"


def test_state_mismatch_is_rejected_and_audited(google):
    client = _new_client()
    _, query, cookie = _start(client)
    google.state["token_response"] = {"id_token": _id_token("x@example.com", nonce=query["nonce"][0])}
    since = _max_audit_id()
    resp = _callback(client, cookie, "forged-state")
    assert _auth_error(resp) == "verification_failed"
    assert google.calls["exchange"] == []  # no code exchange on a bad state
    rows = [r for r in _audit_actions(since) if r.action == "GOOGLE_TOKEN_REJECTED"]
    assert rows and rows[-1].details["error"] == "state_mismatch"


def test_missing_state_cookie_is_rejected(google):
    client = _new_client()
    _, query, _ = _start(client)
    resp = client.get("/api/auth/callback/google", params={"code": "c", "state": query["state"][0]},
                      follow_redirects=False)
    assert _auth_error(resp) == "verification_failed"


def test_nonce_mismatch_in_callback_is_rejected(google):
    email = _uniq("nonce")
    _make_user(email)
    resp, token = _google_login(google, email, nonce="not-the-issued-nonce")
    assert token is None
    assert _auth_error(resp) == "verification_failed"


def test_google_cancel_is_reported(google):
    resp = _new_client().get("/api/auth/callback/google", params={"error": "access_denied"},
                             follow_redirects=False)
    assert _auth_error(resp) == "access_denied"


def test_unknown_email_is_rejected_without_creating_a_user(google):
    email = _uniq("stranger")
    since = _max_audit_id()
    resp, token = _google_login(google, email)
    assert token is None
    assert _auth_error(resp) == "unknown_email"
    db = SessionLocal()
    try:
        assert db.query(User).filter(User.email == email).first() is None
    finally:
        db.close()
    rejected = [r for r in _audit_actions(since) if r.action == "GOOGLE_LOGIN_REJECTED"]
    assert rejected and rejected[-1].details["error"] == "unknown_email"
    assert email not in str(rejected[-1].details)  # domain only


def test_existing_user_gets_one_time_code_and_token(google):
    email = _uniq("existing")
    _make_user(email)
    client = _new_client()
    _, query, cookie = _start(client, return_to="/d/some-dash")
    google.state["token_response"] = {"id_token": _id_token(email.upper(), nonce=query["nonce"][0])}
    resp = _callback(client, cookie, query["state"][0])
    location = resp.headers["location"]
    assert location.startswith("https://rezef.example/auth/complete#")
    assert "access_token" not in location and "eyJ" not in location  # no JWT in URL
    fragment = parse_qs(urlparse(location).fragment)
    assert fragment["next"] == ["/d/some-dash"]
    assert "rezef_oauth_state=\"\"" in resp.headers.get("set-cookie", "") or \
        "max-age=0" in resp.headers.get("set-cookie", "").lower()
    binding_cookie = resp.headers.get("set-cookie", "").lower()
    assert "rezef_login_binding=" in binding_cookie
    # בלי עוגיית הקישור (קישור שהודבק בדפדפן אחר — login CSRF) הקוד אינו נפדה.
    no_binding = client.post("/api/auth/google/exchange", json={"code": fragment["code"][0]})
    assert no_binding.status_code == 401
    wrong_binding = _exchange(client, resp, fragment["code"][0], binding="someone-elses-browser")
    assert wrong_binding.status_code == 401
    first = _exchange(client, resp, fragment["code"][0])
    assert first.status_code == 200, first.text
    assert first.json()["user"]["email"] == email
    me = client.get("/api/admin/auth/me", headers=_bearer(first.json()["access_token"]))
    assert me.status_code == 200
    replay = _exchange(client, resp, fragment["code"][0])
    assert replay.status_code == 401
    assert "נוצל" in replay.json()["detail"]


def test_disabled_user_is_rejected(google):
    email = _uniq("disabled")
    _make_user(email, active=False)
    resp, token = _google_login(google, email)
    assert token is None and _auth_error(resp) == "account_disabled"


# --------------------------------------------------------------------- #
# הזמנה לארגון → הפעלה בהתחברות ראשונה
# --------------------------------------------------------------------- #
def test_invited_email_is_accepted_and_membership_activated(client, google, fresh_org):
    org = fresh_org()
    email = _uniq("invitee")
    granted = client.post("/api/admin/access/grants", headers=org["headers"], json={
        "target_type": "organization", "organization_id": org["org_id"],
        "email": email.upper(), "role": "viewer",
    })
    assert granted.status_code == 201, granted.text
    assert granted.json()["status"] == "invited"
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).one()
        membership = db.query(OrganizationMembership).filter_by(user_id=user.id).one()
        assert membership.status == "invited"
    finally:
        db.close()

    _, token = _google_login(google, email)
    assert token is not None
    db = SessionLocal()
    try:
        membership = db.query(OrganizationMembership).filter_by(user_id=user.id).one()
        assert membership.status == "active"
        assert membership.role == UserRole.VIEWER
    finally:
        db.close()
    own = client.get(f"/api/admin/organizations/{org['org_id']}", headers=_bearer(token))
    assert own.status_code == 200, own.text
    other = fresh_org()
    foreign = client.get(f"/api/admin/organizations/{other['org_id']}",
                         headers={**_bearer(token), "X-Active-Org-Id": str(other["org_id"])})
    assert foreign.status_code == 403


def test_revoked_org_grant_blocks_access(client, google, fresh_org):
    org = fresh_org()
    email = _uniq("revokee")
    body = {"target_type": "organization", "organization_id": org["org_id"], "email": email}
    assert client.post("/api/admin/access/grants", headers=org["headers"],
                       json={**body, "role": "viewer"}).status_code == 201
    _, token = _google_login(google, email)
    assert client.get(f"/api/admin/organizations/{org['org_id']}", headers=_bearer(token)).status_code == 200
    revoked = client.post("/api/admin/access/grants/revoke", headers=org["headers"], json=body)
    assert revoked.status_code == 200, revoked.text
    assert client.get(f"/api/admin/organizations/{org['org_id']}", headers=_bearer(token)).status_code == 403


# --------------------------------------------------------------------- #
# /d/<slug>
# --------------------------------------------------------------------- #
def _active_dashboard(client, owner, slug, access_mode="link") -> int:
    created = client.post("/api/dashboards", headers=owner["headers"], json={
        "primary_organization_id": owner["org_id"], "slug": slug, "title": "תזרים",
        "access_mode": access_mode,
    })
    assert created.status_code == 201, created.text
    dashboard_id = created.json()["id"]
    patched = client.patch(f"/api/dashboards/{dashboard_id}", headers=owner["headers"],
                           json={"status": "active"})
    assert patched.status_code == 200, patched.text
    return dashboard_id


def test_dashboard_access_follows_email_grant(client, google, fresh_org):
    owner = fresh_org()
    slug = f"grant-{uuid.uuid4().hex[:8]}"
    dashboard_id = _active_dashboard(client, owner, slug)
    email = _uniq("dash-viewer")

    anonymous = _new_client().get(f"/api/public/d/{slug}")
    assert anonymous.status_code == 404

    granted = client.post("/api/admin/access/grants", headers=owner["headers"], json={
        "target_type": "dashboard", "dashboard_id": dashboard_id, "email": email,
    })
    assert granted.status_code == 201, granted.text
    assert granted.json()["role"] == "client_viewer"

    _, token = _google_login(google, email)
    assert token is not None  # pending dashboard grant = known email
    allowed = _new_client().get(f"/api/public/d/{slug}", headers=_bearer(token))
    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["provider_calls"] == 0

    stranger_email = _uniq("dash-stranger")
    _make_user(stranger_email)
    stranger_token = _login(client, stranger_email).json()["access_token"]
    denied = _new_client().get(f"/api/public/d/{slug}", headers=_bearer(stranger_token))
    assert denied.status_code == 404

    revoked = client.post("/api/admin/access/grants/revoke", headers=owner["headers"], json={
        "target_type": "dashboard", "dashboard_id": dashboard_id, "email": email,
    })
    assert revoked.status_code == 200
    after = _new_client().get(f"/api/public/d/{slug}", headers=_bearer(token))
    assert after.status_code == 404


def test_members_dashboard_requires_signed_in_grant(client, google, fresh_org):
    owner = fresh_org()
    slug = f"members-{uuid.uuid4().hex[:8]}"
    dashboard_id = _active_dashboard(client, owner, slug, access_mode="members")
    assert _new_client().get(f"/api/public/d/{slug}").status_code == 404
    owner_view = _new_client().get(f"/api/public/d/{slug}", headers=owner["headers"])
    assert owner_view.status_code == 200, owner_view.text
    email = _uniq("member-viewer")
    client.post("/api/admin/access/grants", headers=owner["headers"], json={
        "target_type": "dashboard", "dashboard_id": dashboard_id, "email": email,
    })
    _, token = _google_login(google, email)
    assert _new_client().get(f"/api/public/d/{slug}", headers=_bearer(token)).status_code == 200


def test_public_dashboard_stays_public(client, fresh_org):
    owner = fresh_org()
    slug = f"public-{uuid.uuid4().hex[:8]}"
    _active_dashboard(client, owner, slug, access_mode="public")
    resp = _new_client().get(f"/api/public/d/{slug}")
    assert resp.status_code == 200, resp.text


def test_garbage_bearer_on_public_route_is_anonymous(client, fresh_org):
    owner = fresh_org()
    slug = f"garbage-{uuid.uuid4().hex[:8]}"
    _active_dashboard(client, owner, slug)
    resp = _new_client().get(f"/api/public/d/{slug}", headers=_bearer("not-a-jwt"))
    assert resp.status_code == 404


# --------------------------------------------------------------------- #
# סמכות ניהול הרשאות
# --------------------------------------------------------------------- #
def test_org_admin_cannot_grant_on_another_org(client, fresh_org):
    org_a, org_b = fresh_org(), fresh_org()
    since = _max_audit_id()
    resp = client.post("/api/admin/access/grants", headers=org_a["headers"], json={
        "target_type": "organization", "organization_id": org_b["org_id"],
        "email": _uniq("cross"), "role": "admin",
    })
    assert resp.status_code == 403
    denied = [r for r in _audit_actions(since) if r.action == "ACCESS_DENIED"]
    assert denied and denied[-1].organization_id == org_b["org_id"]
    listing = client.get("/api/admin/access/grants", headers=org_a["headers"],
                         params={"organization_id": org_b["org_id"]})
    assert listing.status_code == 403


def test_org_admin_cannot_grant_on_another_orgs_dashboard(client, fresh_org):
    org_a, org_b = fresh_org(), fresh_org()
    dashboard_id = _active_dashboard(client, org_b, f"foreign-{uuid.uuid4().hex[:8]}")
    resp = client.post("/api/admin/access/grants", headers=org_a["headers"], json={
        "target_type": "dashboard", "dashboard_id": dashboard_id, "email": _uniq("x"),
    })
    assert resp.status_code == 403


def test_super_admin_grants_anywhere_and_imports(client, super_admin, fresh_org):
    org = fresh_org()
    email = _uniq("by-super")
    resp = client.post("/api/admin/access/grants", headers=super_admin["headers"], json={
        "target_type": "organization", "organization_id": org["org_id"],
        "email": email, "role": "accountant",
    })
    assert resp.status_code == 201, resp.text
    exported = client.get("/api/admin/access/export", headers=super_admin["headers"],
                          params={"organization_id": org["org_id"]})
    assert exported.status_code == 200
    rows = exported.json()["grants"]
    assert {"email": email, "target": {"type": "organization", "id": org["org_id"]},
            "role": "accountant", "status": "invited", "source": "rezef"} in rows
    imported = client.post("/api/admin/access/import", headers=super_admin["headers"], json={
        "version": 1,
        "grants": [
            {"email": _uniq("imp"), "target": {"type": "organization", "id": org["org_id"]},
             "role": "viewer", "status": "active"},
            {"email": "bad", "target": {"type": "organization", "id": org["org_id"]}, "role": "viewer"},
            {"email": _uniq("imp2"), "target": {"type": "organization", "id": org["org_id"]},
             "role": "super_admin"},
        ],
    })
    assert imported.status_code == 200, imported.text
    body = imported.json()
    assert body["applied"] == 1
    assert [r["ok"] for r in body["results"]] == [True, False, False]


def test_org_admin_cannot_import_or_grant_super_admin(client, fresh_org):
    org = fresh_org()
    imported = client.post("/api/admin/access/import", headers=org["headers"],
                           json={"version": 1, "grants": []})
    assert imported.status_code == 403
    escalated = client.post("/api/admin/access/grants", headers=org["headers"], json={
        "target_type": "organization", "organization_id": org["org_id"],
        "email": _uniq("esc"), "role": "super_admin",
    })
    assert escalated.status_code == 422


def test_viewer_member_cannot_grant(client, google, fresh_org):
    org = fresh_org()
    email = _uniq("viewer-grantor")
    client.post("/api/admin/access/grants", headers=org["headers"], json={
        "target_type": "organization", "organization_id": org["org_id"],
        "email": email, "role": "viewer",
    })
    _, token = _google_login(google, email)
    resp = client.post("/api/admin/access/grants", headers=_bearer(token), json={
        "target_type": "organization", "organization_id": org["org_id"],
        "email": _uniq("x"), "role": "viewer",
    })
    assert resp.status_code == 403


def test_last_admin_cannot_be_revoked_through_grants_api(client, fresh_org):
    org = fresh_org()
    db = SessionLocal()
    try:
        admin_user = (
            db.query(User).join(OrganizationMembership, OrganizationMembership.user_id == User.id)
            .filter(OrganizationMembership.organization_id == org["org_id"]).first()
        )
        admin_email = admin_user.email
    finally:
        db.close()
    resp = client.post("/api/admin/access/grants/revoke", headers=org["headers"], json={
        "target_type": "organization", "organization_id": org["org_id"], "email": admin_email,
    })
    assert resp.status_code == 409


def test_rbac_config_endpoint_exposes_medici_shape(client, owner):
    resp = client.get("/api/admin/access/rbac", headers=owner["headers"])
    assert resp.status_code == 200
    assert set(resp.json()) >= {"roles", "endpoints", "scopes", "medici_role_aliases"}


# --------------------------------------------------------------------- #
# סיסמה + SUPER_ADMIN
# --------------------------------------------------------------------- #
def test_password_login_still_works_case_insensitive_and_audited(client):
    email = _uniq("Mixed.Case")
    stored = email.replace("mixed.case", "Mixed.Case")
    _make_user(stored)
    since = _max_audit_id()
    ok = _login(client, stored.lower())
    assert ok.status_code == 200, ok.text
    bad = _login(client, stored, "wrong-password")
    assert bad.status_code == 401
    actions = [(r.action, (r.details or {}).get("error")) for r in _audit_actions(since)]
    assert ("LOGIN", None) in actions
    assert ("LOGIN_FAILED", "bad_password") in actions
    for row in _audit_actions(since):
        assert "wrong-password" not in str(row.details)


def test_password_login_does_not_accept_invitation(client, fresh_org):
    """עקבי עם test_a_created_user_has_no_access_until_acceptance."""
    org = fresh_org()
    email = _uniq("pw-invitee")
    user_id = _make_user(email)
    client.post("/api/admin/access/grants", headers=org["headers"], json={
        "target_type": "organization", "organization_id": org["org_id"],
        "email": email, "role": "user",
    })
    token = _login(client, email).json()["access_token"]
    db = SessionLocal()
    try:
        assert db.query(OrganizationMembership).filter_by(user_id=user_id).one().status == "invited"
    finally:
        db.close()
    assert client.get(f"/api/admin/organizations/{org['org_id']}", headers=_bearer(token)).status_code == 403


def test_super_admin_can_unblock_existing_user_without_membership(client, super_admin, fresh_org):
    """מצב הפרוד: משתמש קיים עם 0 חברויות → 403 בכל מסלול ארגוני. השחרור:
    מנהל-על מעניק חברות פעילה מיד (בלי fallback ל-users.organization_id)."""
    org = fresh_org()
    email = _uniq("stranded")
    _make_user(email)
    token = _login(client, email).json()["access_token"]
    assert client.get(f"/api/admin/organizations/{org['org_id']}", headers=_bearer(token)).status_code == 403
    body = {"target_type": "organization", "organization_id": org["org_id"], "email": email,
            "role": "admin", "activate_now": True}
    by_org_admin = client.post("/api/admin/access/grants", headers=org["headers"], json=body)
    assert by_org_admin.status_code == 403
    resp = client.post("/api/admin/access/grants", headers=super_admin["headers"], json=body)
    assert resp.status_code == 201, resp.text
    assert resp.json()["status"] == "active"
    assert client.get(f"/api/admin/organizations/{org['org_id']}", headers=_bearer(token)).status_code == 200
    unknown = client.post("/api/admin/access/grants", headers=super_admin["headers"],
                          json={**body, "email": _uniq("nobody")})
    assert unknown.status_code == 409


def test_super_admin_is_not_locked_out(client, google, super_admin, fresh_org):
    org = fresh_org()
    # כניסה בסיסמה (fixture) + בחירת ארגון בכותרת — בלי שום חברות.
    resp = client.get(f"/api/admin/organizations/{org['org_id']}",
                      headers={**super_admin["headers"], "X-Active-Org-Id": str(org["org_id"])})
    assert resp.status_code == 200, resp.text
    _, token = _google_login(google, super_admin["email"])
    assert token is not None
    me = client.get("/api/admin/auth/me", headers=_bearer(token))
    assert me.json()["role"] == "super_admin"


# --------------------------------------------------------------------- #
# GIS (deprecated) — הוקשח
# --------------------------------------------------------------------- #
def test_gis_endpoint_rejects_unknown_email_and_bad_audience(client, google):
    unknown = client.post("/api/admin/auth/google", json={
        "id_token": _id_token(_uniq("gis-unknown")), "registration_code": "anything",
    })
    assert unknown.status_code == 403
    assert "אינה מורשית" in unknown.json()["detail"]
    bad_aud = client.post("/api/admin/auth/google", json={
        "id_token": _id_token(_uniq("gis"), aud="other-client"),
    })
    assert bad_aud.status_code == 401


def test_gis_endpoint_logs_in_existing_user(client, google):
    email = _uniq("gis-known")
    _make_user(email)
    resp = client.post("/api/admin/auth/google", json={"id_token": _id_token(email)})
    assert resp.status_code == 200, resp.text
    assert resp.json()["user"]["email"] == email


def test_dashboard_grant_row_is_lowercased(client, fresh_org):
    owner = fresh_org()
    dashboard_id = _active_dashboard(client, owner, f"lower-{uuid.uuid4().hex[:8]}")
    client.post("/api/admin/access/grants", headers=owner["headers"], json={
        "target_type": "dashboard", "dashboard_id": dashboard_id, "email": "MiXeD@Example.COM",
    })
    db = SessionLocal()
    try:
        grant = db.query(DashboardAccessGrant).filter_by(dashboard_id=dashboard_id).one()
        assert grant.email == "mixed@example.com" and grant.status == "invited"
        assert db.get(ClientDashboard, dashboard_id) is not None
    finally:
        db.close()
