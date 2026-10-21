"""זהות Google מאומתת → משתמש רצף. המקבילה ל-signIn callback של Medici.

Medici (lib/auth.ts) יצר משתמש לכל חשבון Google שנכנס. כאן מייל לא מוכר
**נדחה**: נכנס רק מי שכבר קיים כמשתמש, או שמנהל הנפיק לו הרשאה (הזמנת
ארגון יוצרת זהות; הרשאת דשבורד ממתינה יוצרת זהות כאן). אין הרשמה עצמית
ואין הצטרפות לארגון קיים בלי הזמנה.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Request
from sqlalchemy import update
from sqlalchemy.orm import Session

from ..models import AuthLoginCode, User
from . import access_grants, auth_audit
from .google_oidc import GoogleIdentity

LOGIN_CODE_TTL_SECONDS = 120

MESSAGES_HE = {
    "unknown_email": "כתובת המייל הזו אינה מורשית להיכנס לרצף. בקשו ממנהל הארגון להזמין אתכם.",
    "account_disabled": "החשבון מושבת. פנו למנהל המערכת.",
    "verification_failed": "אימות מול Google נכשל. נסו להתחבר שוב.",
    "not_configured": "התחברות עם Google אינה מוגדרת במערכת.",
    "access_denied": "ההתחברות עם Google בוטלה.",
    "code_invalid": "קישור ההתחברות פג או כבר נוצל. התחברו שוב.",
}


class GoogleLoginRejected(Exception):
    def __init__(self, reason: str):
        self.reason = reason
        self.message_he = MESSAGES_HE.get(reason, MESSAGES_HE["verification_failed"])
        super().__init__(reason)


def _email_domain(email: str) -> str:
    return email.rsplit("@", 1)[-1] if "@" in email else ""


def resolve_user(db: Session, identity: GoogleIdentity, request: Optional[Request], *, channel: str) -> User:
    """מחזיר משתמש פעיל (אחרי הפעלת הרשאות ממתינות) או זורק GoogleLoginRejected."""
    user = access_grants.find_user(db, identity.email)
    if user is None and access_grants.has_pending_dashboard_grant(db, identity.email):
        user = access_grants.ensure_identity_for_dashboard_grant(db, identity.email)
    if user is None:
        auth_audit.record(
            db, action="GOOGLE_LOGIN_REJECTED", resource="AUTH.GOOGLE", status=403,
            request=request, error="unknown_email",
            # דומיין בלבד — לא כתובת מלאה של מי שאינו משתמש.
            extra={"channel": channel, "email_domain": _email_domain(identity.email)},
        )
        raise GoogleLoginRejected("unknown_email")
    if not user.is_active:
        auth_audit.record(
            db, action="GOOGLE_LOGIN_REJECTED", resource="AUTH.GOOGLE", status=403,
            request=request, user_id=user.id, error="account_disabled",
            extra={"channel": channel},
        )
        raise GoogleLoginRejected("account_disabled")
    activated = access_grants.activate_pending_for_login(db, user)
    user.last_login = datetime.now(timezone.utc)
    user.failed_login_attempts = 0
    user.locked_until = None
    auth_audit.record(
        db, action="GOOGLE_LOGIN", resource="AUTH.GOOGLE", status=200, request=request,
        user_id=user.id, entity_type="User", entity_id=user.id,
        extra={"channel": channel, "activated": activated},
    )
    db.refresh(user)
    return user


def record_verification_failure(db: Session, request: Optional[Request], reason: str, *, channel: str) -> None:
    auth_audit.record(
        db, action="GOOGLE_TOKEN_REJECTED", resource="AUTH.GOOGLE", status=401,
        request=request, error=reason, extra={"channel": channel},
    )


def _sha(value: str) -> str:
    return hashlib.sha256((value or "").encode()).hexdigest()


def issue_login_code(db: Session, user: User) -> tuple[str, str]:
    """מחזיר (code, browser_nonce). ה-nonce הולך לעוגיית HttpOnly; רק
    ה-hash שלו נשמר, והפדיון דורש את שניהם."""
    code = secrets.token_urlsafe(32)
    browser_nonce = secrets.token_urlsafe(32)
    db.add(AuthLoginCode(
        code_hash=_sha(code),
        browser_binding=_sha(browser_nonce),
        user_id=user.id,
        expires_at=datetime.utcnow() + timedelta(seconds=LOGIN_CODE_TTL_SECONDS),
    ))
    db.commit()
    return code, browser_nonce


def redeem_login_code(db: Session, code: str, browser_nonce: Optional[str]) -> Optional[User]:
    """חד-פעמי ומקושר-דפדפן: UPDATE מותנה אחד. קוד שנוצל/פג/מדפדפן אחר → None."""
    if not browser_nonce:
        return None
    code_hash = _sha(code)
    now = datetime.utcnow()
    result = db.execute(
        update(AuthLoginCode)
        .where(
            AuthLoginCode.code_hash == code_hash,
            AuthLoginCode.browser_binding == _sha(browser_nonce),
            AuthLoginCode.used_at.is_(None),
            AuthLoginCode.expires_at > now,
        )
        .values(used_at=now)
        .execution_options(synchronize_session=False)
    )
    db.commit()
    if result.rowcount != 1:
        return None
    row = db.query(AuthLoginCode).filter(AuthLoginCode.code_hash == code_hash).first()
    user = db.get(User, row.user_id) if row else None
    if user is None or not user.is_active:
        return None
    return user
