"""W6.7 משימה 4 — היגיינת טוקנים: jti בכל טוקן חדש, logout מבטל, תאימות לאחור.

- create_access_token מוסיף claim ‏jti (uuid).
- POST /auth/logout מוסיף את ה-jti ל-denylist; טוקן שבוטל נדחה (401).
- טוקן ישן בלי jti ממשיך לעבוד (תאימות) — אך אינו ניתן לביטול.
- רשומות denylist שפג תוקפן נמחקות הזדמנותית ב-logout.
"""
from datetime import datetime, timedelta


def _register(client, email):
    resp = client.post("/api/admin/auth/register", json={
        "email": email, "password": "secret123", "full_name": "בדיקת טוקנים",
    })
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_new_tokens_carry_jti_claim(client, owner):
    data = _register(client, "jti-claim@example.com")
    from cfo.auth import decode_access_token

    payload = decode_access_token(data["access_token"])
    assert payload is not None
    assert payload.get("jti"), "טוקן חדש חייב לשאת jti"


def test_logout_revokes_token(client, owner):
    data = _register(client, "logout-revokes@example.com")
    headers = {"Authorization": f"Bearer {data['access_token']}"}

    # הטוקן עובד לפני ההתנתקות
    assert client.get("/api/admin/auth/me", headers=headers).status_code == 200

    resp = client.post("/api/admin/auth/logout", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["revoked"] is True

    # אותו טוקן — נדחה
    assert client.get("/api/admin/auth/me", headers=headers).status_code == 401


def test_logout_does_not_revoke_other_tokens_of_same_user(client, owner):
    email = "logout-scope@example.com"
    data = _register(client, email)
    headers_a = {"Authorization": f"Bearer {data['access_token']}"}

    login = client.post("/api/admin/auth/login", json={
        "email": email, "password": "secret123",
    })
    headers_b = {"Authorization": f"Bearer {login.json()['access_token']}"}

    client.post("/api/admin/auth/logout", headers=headers_a)
    assert client.get("/api/admin/auth/me", headers=headers_a).status_code == 401
    assert client.get("/api/admin/auth/me", headers=headers_b).status_code == 200


def test_legacy_token_without_jti_still_works(client, owner):
    """טוקן ישן (בלי jti) חייב להמשיך לעבוד — תאימות לאחור."""
    data = _register(client, "legacy-token@example.com")

    from jose import jwt as jose_jwt
    from cfo.auth import ALGORITHM, SECRET_KEY

    legacy = jose_jwt.encode({
        "sub": str(data["user"]["id"]),
        "role": data["user"]["role"],
        "exp": datetime.utcnow() + timedelta(hours=1),
    }, SECRET_KEY, algorithm=ALGORITHM)

    headers = {"Authorization": f"Bearer {legacy}"}
    assert client.get("/api/admin/auth/me", headers=headers).status_code == 200

    # logout עם טוקן בלי jti — תשובה כנה: אין מה לבטל
    resp = client.post("/api/admin/auth/logout", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["revoked"] is False

    # והטוקן עדיין עובד (אין דרך לבטל אותו — הוא יפוג מעצמו)
    assert client.get("/api/admin/auth/me", headers=headers).status_code == 200


def test_logout_purges_expired_denylist_rows(client, owner):
    from cfo.database import SessionLocal
    from cfo.models import RevokedToken

    db = SessionLocal()
    try:
        db.add(RevokedToken(
            jti="stale-jti-for-purge-test",
            revoked_at=datetime.utcnow() - timedelta(days=3),
            expires_at=datetime.utcnow() - timedelta(days=2),
        ))
        db.commit()
    finally:
        db.close()

    data = _register(client, "purge-check@example.com")
    headers = {"Authorization": f"Bearer {data['access_token']}"}
    assert client.post("/api/admin/auth/logout", headers=headers).status_code == 200

    db = SessionLocal()
    try:
        stale = db.query(RevokedToken).filter(
            RevokedToken.jti == "stale-jti-for-purge-test",
        ).first()
        assert stale is None, "רשומה שפג תוקפה חייבת להימחק הזדמנותית"
    finally:
        db.close()
