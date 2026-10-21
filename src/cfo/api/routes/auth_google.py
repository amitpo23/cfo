"""Google sign-in בזרימת שרת — נתיבים תואמי NextAuth (Medici).

    GET  /api/auth/signin/google     → state+nonce+PKCE בעוגייה חתומה, redirect ל-Google
    GET  /api/auth/callback/google   → בדיקת state, החלפת code, אימות ID token מקומי,
                                       מיפוי מייל→משתמש, redirect ל-SPA עם קוד חד-פעמי
    POST /api/auth/google/exchange   → קוד חד-פעמי → Token (אותו מבנה כמו /admin/auth/login)

ה-SPA שומר JWT ב-localStorage ושולח Bearer, ולכן הסשן עובר דרך קוד
חד-פעמי של 120 שניות ב-fragment של ה-URL (לא נשלח לשרתים, לא ב-Referer),
ולא דרך עוגייה. JWT ארוך-חיים לעולם אינו נכנס ל-URL.
"""
from __future__ import annotations

from typing import Optional
from urllib.parse import quote, urlencode

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi import Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from ...database import get_db_session
from ...models import Token
from ...services import google_oidc
from ...services.google_login import (
    LOGIN_CODE_TTL_SECONDS, MESSAGES_HE, GoogleLoginRejected, issue_login_code, record_verification_failure,
    redeem_login_code, resolve_user,
)
from ...services.google_oidc import GoogleAuthError

router = APIRouter()

CHANNEL = "server_flow"
LOGIN_BINDING_COOKIE = "rezef_login_binding"


def _spa_error(reason: str) -> RedirectResponse:
    base = google_oidc.auth_base_url()
    response = RedirectResponse(f"{base}/login?{urlencode({'auth_error': reason})}", status_code=302)
    _clear_state_cookie(response)
    return response


def _clear_state_cookie(response) -> None:
    response.delete_cookie(
        google_oidc.STATE_COOKIE, path=google_oidc.STATE_COOKIE_PATH,
        secure=google_oidc.cookie_secure(), httponly=True, samesite="lax",
    )


@router.get("/signin/google")
def signin_google(request: Request, return_to: Optional[str] = None):
    if not google_oidc.is_configured():
        return _spa_error("not_configured")
    start = google_oidc.begin_sign_in(return_to)
    response = RedirectResponse(start.authorize_url, status_code=302)
    response.set_cookie(
        key=google_oidc.STATE_COOKIE,
        value=start.cookie_value,
        max_age=google_oidc.STATE_TTL_SECONDS,
        path=google_oidc.STATE_COOKIE_PATH,
        httponly=True,
        secure=google_oidc.cookie_secure(),
        samesite="lax",
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@router.get("/callback/google")
def callback_google(
    request: Request,
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
    db: Session = Depends(get_db_session),
):
    if not google_oidc.is_configured():
        return _spa_error("not_configured")
    if error:
        # המשתמש ביטל, או ש-Google סירבה. אין מה לאמת.
        return _spa_error("access_denied")
    try:
        saved = google_oidc.read_state_cookie(request.cookies.get(google_oidc.STATE_COOKIE), state)
        if not code:
            raise GoogleAuthError("missing_code")
        tokens = google_oidc.exchange_code(code, saved["cv"])
        id_token = tokens.get("id_token")
        if not id_token:
            raise GoogleAuthError("missing_id_token")
        identity = google_oidc.verify_id_token(
            id_token, expected_nonce=saved.get("nonce"),
            access_token=tokens.get("access_token"),
        )
    except GoogleAuthError as exc:
        record_verification_failure(db, request, exc.reason, channel=CHANNEL)
        return _spa_error("verification_failed")

    try:
        user = resolve_user(db, identity, request, channel=CHANNEL)
    except GoogleLoginRejected as exc:
        return _spa_error(exc.reason)

    login_code, browser_nonce = issue_login_code(db, user)
    next_path = google_oidc.safe_return_to(saved.get("rt"))
    fragment = f"code={quote(login_code)}&next={quote(next_path, safe='/')}"
    response = RedirectResponse(f"{google_oidc.auth_base_url()}/auth/complete#{fragment}", status_code=302)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    _clear_state_cookie(response)
    # קישור הקוד לדפדפן שהתחיל את הזרימה: בלי העוגייה הזו הקוד אינו נפדה.
    response.set_cookie(
        key=LOGIN_BINDING_COOKIE, value=browser_nonce,
        max_age=LOGIN_CODE_TTL_SECONDS, path=google_oidc.STATE_COOKIE_PATH,
        httponly=True, secure=google_oidc.cookie_secure(), samesite="lax",
    )
    return response


class ExchangeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(min_length=10, max_length=200)


@router.post("/google/exchange", response_model=Token)
def exchange_login_code(
    body: ExchangeBody,
    request: Request,
    response: Response,
    db: Session = Depends(get_db_session),
):
    user = redeem_login_code(db, body.code, request.cookies.get(LOGIN_BINDING_COOKIE))
    if user is None:
        raise HTTPException(status_code=401, detail=MESSAGES_HE["code_invalid"])
    from .admin import _token_for_user

    response.delete_cookie(
        LOGIN_BINDING_COOKIE, path=google_oidc.STATE_COOKIE_PATH,
        secure=google_oidc.cookie_secure(), httponly=True, samesite="lax",
    )
    return _token_for_user(user)


@router.get("/google/messages")
def google_messages():
    """הודעות השגיאה בעברית לפי קוד — ה-SPA מציג אותן אחרי redirect."""
    return {"messages": MESSAGES_HE, "configured": google_oidc.is_configured()}
