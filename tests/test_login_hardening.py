"""W6.7 משימה 1 — הקשחת login: נעילה אחרי כישלונות + אורך סיסמה בהרשמה.

הכללים:
- 5 כישלונות רצופים → נעילה ל-15 דקות (429, הודעה כנה בעברית).
- התחברות מוצלחת מאפסת את המונה.
- הודעת כישלון זהה בין מייל לא קיים לסיסמה שגויה (anti-enumeration).
- הרשמה עם סיסמה קצרה מ-8 תווים נדחית (422).
"""
from datetime import datetime, timedelta

from sqlalchemy import select


def _register(client, email, password="secret123"):
    return client.post("/api/admin/auth/register", json={
        "email": email, "password": password, "full_name": "בדיקת נעילה",
    })


def _login(client, email, password):
    return client.post("/api/admin/auth/login", json={
        "email": email, "password": password,
    })


def test_register_rejects_short_password(client, owner):
    resp = _register(client, "shortpw-register@example.com", "kurz123")
    assert resp.status_code == 422, resp.text


def test_register_accepts_password_of_exactly_8_chars(client, owner):
    resp = _register(client, "exact8@example.com", "12345678")
    assert resp.status_code == 201, resp.text


def test_unknown_email_and_wrong_password_get_same_message(client, owner):
    _register(client, "enum-check@example.com")
    r_unknown = _login(client, "no-such-user@example.com", "whatever123")
    r_wrong = _login(client, "enum-check@example.com", "wrong-password")
    assert r_unknown.status_code == 401
    assert r_wrong.status_code == 401
    assert r_unknown.json()["detail"] == r_wrong.json()["detail"]


def test_lockout_after_five_failures_even_with_correct_password(client, owner):
    email = "lockme@example.com"
    assert _register(client, email).status_code == 201

    for _ in range(5):
        assert _login(client, email, "wrong-password").status_code == 401

    # הניסיון השישי — נעול, גם עם הסיסמה הנכונה
    locked = _login(client, email, "secret123")
    assert locked.status_code == 429, locked.text
    detail = locked.json()["detail"]
    assert "נעול" in detail or "ננעל" in detail
    # ההודעה אינה מהדהדת את כתובת המייל
    assert email not in detail


def test_successful_login_resets_failure_counter(client, owner):
    email = "resetcounter@example.com"
    assert _register(client, email).status_code == 201

    for _ in range(4):
        assert _login(client, email, "wrong-password").status_code == 401

    # הצלחה מאפסת את המונה
    assert _login(client, email, "secret123").status_code == 200

    # אחרי האיפוס — עוד 4 כישלונות אינם נועלים
    for _ in range(4):
        assert _login(client, email, "wrong-password").status_code == 401
    assert _login(client, email, "secret123").status_code == 200


def test_lock_expires_after_window(client, owner):
    email = "lockexpires@example.com"
    assert _register(client, email).status_code == 201

    for _ in range(5):
        _login(client, email, "wrong-password")
    assert _login(client, email, "secret123").status_code == 429

    # מזיזים את הנעילה לעבר — ההתחברות חוזרת לעבוד
    from cfo.database import SessionLocal
    from cfo.models import User

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        user.locked_until = datetime.utcnow() - timedelta(minutes=1)
        db.commit()
    finally:
        db.close()

    assert _login(client, email, "secret123").status_code == 200


def test_failed_login_counter_is_atomic_across_stale_sessions(client, owner):
    """Five workers that all observed zero must still produce count=5 + lock.

    Loading the same row in every session before the first write forces the
    stale-read ordering that defeated the former ORM read/modify/write code.
    """
    email = "atomic-lock-counter@example.com"
    assert _register(client, email).status_code == 201

    from cfo.api.routes.admin import _record_failed_login
    from cfo.database import SessionLocal
    from cfo.models import User

    sessions = [SessionLocal() for _ in range(5)]
    try:
        stale_users = [
            db.execute(select(User).where(User.email == email)).scalar_one()
            for db in sessions
        ]
        assert [user.failed_login_attempts for user in stale_users] == [0] * 5

        observed = []
        now = datetime.utcnow()
        for db, stale_user in zip(sessions, stale_users):
            observed.append(_record_failed_login(db, stale_user.id, now=now)[0])
            db.commit()

        assert observed == [1, 2, 3, 4, 5]
    finally:
        for db in sessions:
            db.close()

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).one()
        assert user.failed_login_attempts == 5
        assert user.locked_until == now + timedelta(minutes=15)
    finally:
        db.close()


def test_login_is_rate_limited_by_source_before_account_lockout(
    client, owner, monkeypatch,
):
    """Unknown-account traffic is throttled by source, not account state."""
    from cfo.api.routes import admin as admin_routes

    monkeypatch.setattr(admin_routes, "LOGIN_SOURCE_ATTEMPTS_PER_MINUTE", 2)
    headers = {"x-forwarded-for": "203.0.113.177"}

    first = client.post("/api/admin/auth/login", headers=headers, json={
        "email": "source-rate-limit-1@example.com", "password": "wrong-pass",
    })
    second = client.post("/api/admin/auth/login", headers=headers, json={
        "email": "source-rate-limit-2@example.com", "password": "wrong-pass",
    })
    blocked = client.post("/api/admin/auth/login", headers=headers, json={
        "email": "source-rate-limit-3@example.com", "password": "wrong-pass",
    })
    other_source = client.post(
        "/api/admin/auth/login",
        headers={"x-forwarded-for": "203.0.113.178"},
        json={
            "email": "source-rate-limit-4@example.com",
            "password": "wrong-pass",
        },
    )

    assert first.status_code == 401
    assert second.status_code == 401
    assert blocked.status_code == 429
    assert other_source.status_code == 401

    from cfo.database import SessionLocal
    from cfo.models import ProviderRequestBudget

    db = SessionLocal()
    try:
        rows = db.query(ProviderRequestBudget).filter(
            ProviderRequestBudget.provider == "auth",
            ProviderRequestBudget.limit_value == 2,
        ).all()
        assert sorted(row.used for row in rows) == [1, 2]
        assert all(row.scope_key.startswith("source:") for row in rows)
    finally:
        db.close()
