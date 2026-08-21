"""W6.7 משימה 1 — הקשחת login: נעילה אחרי כישלונות + אורך סיסמה בהרשמה.

הכללים:
- 5 כישלונות רצופים → נעילה ל-15 דקות (429, הודעה כנה בעברית).
- התחברות מוצלחת מאפסת את המונה.
- הודעת כישלון זהה בין מייל לא קיים לסיסמה שגויה (anti-enumeration).
- הרשמה עם סיסמה קצרה מ-8 תווים נדחית (422).
"""
from datetime import datetime, timedelta


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
