"""W6.7 משימה 2 — שינוי סיסמה למשתמש מחובר ואיפוס "שכחתי סיסמה" בשני שלבים.

- POST /auth/change-password: אימות הסיסמה הנוכחית, מינימום 8 תווים, AuditLog.
- POST /auth/request-password-reset: טוקן חד-פעמי (sha256, 30 דקות) + מייל;
  בלי SMTP → 503 כן; תשובה זהה בין מייל קיים ללא-קיים.
- POST /auth/reset-password: אימות hash+תוקף+חד-פעמיות, איפוס נעילה, AuditLog.
"""
import hashlib
import re
from datetime import datetime, timedelta

import pytest


def _register(client, email, password="secret123"):
    resp = client.post("/api/admin/auth/register", json={
        "email": email, "password": password, "full_name": "בדיקת סיסמה",
    })
    assert resp.status_code == 201, resp.text
    data = resp.json()
    return {"headers": {"Authorization": f"Bearer {data['access_token']}"},
            "user": data["user"]}


def _login(client, email, password):
    return client.post("/api/admin/auth/login", json={
        "email": email, "password": password,
    })


# --------------------------------------------------------------------------
# שינוי סיסמה (משתמש מחובר)
# --------------------------------------------------------------------------

def test_change_password_requires_auth(client):
    resp = client.post("/api/admin/auth/change-password", json={
        "current_password": "secret123", "new_password": "newsecret1",
    })
    assert resp.status_code == 403


def test_change_password_rejects_wrong_current(client, owner):
    acct = _register(client, "chpw-wrong@example.com")
    resp = client.post("/api/admin/auth/change-password", json={
        "current_password": "not-my-password", "new_password": "newsecret1",
    }, headers=acct["headers"])
    assert resp.status_code == 403, resp.text


def test_change_password_rejects_short_new_password(client, owner):
    acct = _register(client, "chpw-short@example.com")
    resp = client.post("/api/admin/auth/change-password", json={
        "current_password": "secret123", "new_password": "kurz1",
    }, headers=acct["headers"])
    assert resp.status_code == 422, resp.text


def test_change_password_happy_path_writes_audit_log(client, owner):
    email = "chpw-ok@example.com"
    acct = _register(client, email)
    resp = client.post("/api/admin/auth/change-password", json={
        "current_password": "secret123", "new_password": "newsecret1",
    }, headers=acct["headers"])
    assert resp.status_code == 200, resp.text

    # הסיסמה הישנה כבר אינה עובדת; החדשה כן
    assert _login(client, email, "secret123").status_code == 401
    assert _login(client, email, "newsecret1").status_code == 200

    from cfo.database import SessionLocal
    from cfo.models import AuditLog

    db = SessionLocal()
    try:
        log = db.query(AuditLog).filter(
            AuditLog.user_id == acct["user"]["id"],
            AuditLog.action == "PASSWORD_CHANGE",
        ).first()
        assert log is not None
    finally:
        db.close()


# --------------------------------------------------------------------------
# איפוס סיסמה — שלב א': בקשה
# --------------------------------------------------------------------------

def test_request_reset_without_smtp_returns_503(client, owner):
    resp = client.post("/api/admin/auth/request-password-reset", json={
        "email": "whoever@example.com",
    })
    assert resp.status_code == 503, resp.text
    assert "SMTP" in resp.json()["detail"] or "מייל" in resp.json()["detail"]


@pytest.fixture
def smtp_configured(monkeypatch):
    """מדמה SMTP מוגדר ולוכד את המיילים שנשלחו — בלי רשת אמיתית."""
    from cfo.config import settings
    from cfo.api.routes import admin as admin_routes

    monkeypatch.setattr(settings, "smtp_host", "smtp.test.local")
    monkeypatch.setattr(settings, "smtp_from", "rezef@test.local")

    sent = []

    async def _fake_send(to, subject, body, _settings, **kwargs):
        sent.append({"to": to, "subject": subject, "body": body})
        return True

    monkeypatch.setattr(admin_routes, "send_email_smtp", _fake_send)
    return sent


def test_request_reset_identical_response_for_unknown_email(client, owner, smtp_configured):
    email = "reset-exists@example.com"
    _register(client, email)

    r_known = client.post("/api/admin/auth/request-password-reset", json={"email": email})
    r_unknown = client.post("/api/admin/auth/request-password-reset", json={
        "email": "reset-ghost@example.com",
    })
    assert r_known.status_code == 200
    assert r_unknown.status_code == 200
    assert r_known.json() == r_unknown.json()

    # מייל נשלח רק לכתובת הקיימת — אבל התשובה לא מסגירה זאת
    assert len(smtp_configured) == 1
    assert smtp_configured[0]["to"] == email


def _extract_token(sent_email):
    m = re.search(r"token=([A-Za-z0-9_\-]+)", sent_email["body"])
    assert m, f"אין token בגוף המייל: {sent_email['body']}"
    return m.group(1)


# --------------------------------------------------------------------------
# איפוס סיסמה — שלב ב': ביצוע
# --------------------------------------------------------------------------

def test_reset_password_full_flow(client, owner, smtp_configured):
    email = "reset-flow@example.com"
    acct = _register(client, email)

    assert client.post("/api/admin/auth/request-password-reset",
                       json={"email": email}).status_code == 200
    token = _extract_token(smtp_configured[0])

    resp = client.post("/api/admin/auth/reset-password", json={
        "token": token, "new_password": "afterreset1",
    })
    assert resp.status_code == 200, resp.text

    assert _login(client, email, "secret123").status_code == 401
    assert _login(client, email, "afterreset1").status_code == 200

    # הטוקן חד-פעמי — שימוש חוזר נדחה
    resp2 = client.post("/api/admin/auth/reset-password", json={
        "token": token, "new_password": "anotherpass1",
    })
    assert resp2.status_code == 400

    from cfo.database import SessionLocal
    from cfo.models import AuditLog

    db = SessionLocal()
    try:
        log = db.query(AuditLog).filter(
            AuditLog.user_id == acct["user"]["id"],
            AuditLog.action == "PASSWORD_RESET",
        ).first()
        assert log is not None
    finally:
        db.close()


def test_reset_password_clears_login_lock(client, owner, smtp_configured):
    email = "reset-unlocks@example.com"
    _register(client, email)
    for _ in range(5):
        _login(client, email, "wrong-password")
    assert _login(client, email, "secret123").status_code == 429

    client.post("/api/admin/auth/request-password-reset", json={"email": email})
    token = _extract_token(smtp_configured[-1])
    assert client.post("/api/admin/auth/reset-password", json={
        "token": token, "new_password": "unlockedpw1",
    }).status_code == 200

    assert _login(client, email, "unlockedpw1").status_code == 200


def test_reset_password_rejects_bad_and_expired_tokens(client, owner, smtp_configured):
    email = "reset-expired@example.com"
    _register(client, email)

    # טוקן שלא הונפק מעולם
    assert client.post("/api/admin/auth/reset-password", json={
        "token": "totally-made-up-token", "new_password": "whatever12",
    }).status_code == 400

    # טוקן אמיתי שפג תוקפו
    client.post("/api/admin/auth/request-password-reset", json={"email": email})
    token = _extract_token(smtp_configured[-1])

    from cfo.database import SessionLocal
    from cfo.models import PasswordResetToken

    db = SessionLocal()
    try:
        row = db.query(PasswordResetToken).filter(
            PasswordResetToken.token_hash == hashlib.sha256(token.encode()).hexdigest(),
        ).first()
        assert row is not None
        row.expires_at = datetime.utcnow() - timedelta(minutes=1)
        db.commit()
    finally:
        db.close()

    assert client.post("/api/admin/auth/reset-password", json={
        "token": token, "new_password": "whatever12",
    }).status_code == 400


def test_reset_password_rejects_short_new_password(client, owner, smtp_configured):
    email = "reset-short@example.com"
    _register(client, email)
    client.post("/api/admin/auth/request-password-reset", json={"email": email})
    token = _extract_token(smtp_configured[-1])
    assert client.post("/api/admin/auth/reset-password", json={
        "token": token, "new_password": "kurz1",
    }).status_code == 422
