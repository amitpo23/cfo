"""Google OIDC — פורט של GoogleProvider של NextAuth (Medici, lib/auth.ts).

הזרימה זהה ל-NextAuth: authorization-code עם state, nonce ו-PKCE (S256),
ונתיבי callback תואמים (/api/auth/callback/google). ההבדל: Medici סומך על
NextAuth; כאן אימות ה-ID token נעשה **מקומית** מול JWKS של Google:
חתימה RS256, aud, iss, exp/iat, email_verified ו-nonce.

שתי קריאות הרשת (JWKS ו-token endpoint) הן פונקציות ברמת המודול כדי
שהטסטים יחליפו אותן — הסוויטה חסומה לרשת (tests/conftest.py).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import secrets
import time
from dataclasses import dataclass
from typing import Any, Optional
from urllib.parse import urlencode

from jose import jwt
from jose.exceptions import ExpiredSignatureError, JWTClaimsError, JWTError

from ..config import settings

GOOGLE_AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
GOOGLE_ISSUERS = ("accounts.google.com", "https://accounts.google.com")

CALLBACK_PATH = "/api/auth/callback/google"
STATE_COOKIE = "rezef_oauth_state"
STATE_COOKIE_PATH = "/api/auth"
STATE_TTL_SECONDS = 600
CLOCK_SKEW_SECONDS = 120
_JWKS_DEFAULT_TTL = 3600

_RETURN_TO_RE = re.compile(r"^/(?![/\\])[A-Za-z0-9_\-./?=&%#]*$")


class GoogleAuthError(Exception):
    """כשל אימות. ``reason`` הוא קוד קצר לביקורת — לעולם לא הטוקן עצמו."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


# --------------------------------------------------------------------- #
# הגדרות
# --------------------------------------------------------------------- #
def is_configured() -> bool:
    return bool(settings.google_client_id and settings.google_client_secret)


def auth_base_url() -> str:
    """בסיס ה-redirect. סדר: AUTH_URL → VERCEL_BRANCH_URL בפריוויו → APP_URL.

    VERCEL_BRANCH_URL נקבע ע"י הפלטפורמה (לא ע"י הלקוח) ולכן אינו Host
    header. בלעדיו פריוויו היה שולח את Google ל-callback של פרוד, שם עוגיית
    ה-state אינה קיימת.
    """
    if settings.auth_url:
        return settings.auth_url.strip().rstrip("/")
    branch = os.getenv("VERCEL_BRANCH_URL", "").strip()
    if os.getenv("VERCEL_ENV") == "preview" and branch:
        return f"https://{branch.removeprefix('https://').rstrip('/')}"
    return (settings.app_url or "").strip().rstrip("/")


def redirect_uri() -> str:
    return f"{auth_base_url()}{CALLBACK_PATH}"


def cookie_secure() -> bool:
    return auth_base_url().startswith("https://")


def safe_return_to(value: Optional[str]) -> str:
    """רק נתיב יחסי. כל דבר אחר (//evil, https://, \\) → "/" — אין open redirect."""
    if value and len(value) <= 512 and _RETURN_TO_RE.fullmatch(value):
        return value
    return "/"


# --------------------------------------------------------------------- #
# state / nonce / PKCE — עוגייה חתומה קצרת-מועד
# --------------------------------------------------------------------- #
def _state_key() -> str:
    return f"{settings.jwt_secret_key}:rezef-google-oauth-state"


def _pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


@dataclass
class SignInStart:
    authorize_url: str
    cookie_value: str


def begin_sign_in(return_to: Optional[str] = None) -> SignInStart:
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    now = int(time.time())
    cookie_value = jwt.encode(
        {
            "state": state,
            "nonce": nonce,
            "cv": verifier,
            "rt": safe_return_to(return_to),
            "iat": now,
            "exp": now + STATE_TTL_SECONDS,
            "aud": "rezef-google-oauth-state",
        },
        _state_key(),
        algorithm="HS256",
    )
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": redirect_uri(),
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "nonce": nonce,
        "code_challenge": _pkce_challenge(verifier),
        "code_challenge_method": "S256",
        "prompt": "select_account",
    }
    return SignInStart(f"{GOOGLE_AUTHORIZE_URL}?{urlencode(params)}", cookie_value)


def read_state_cookie(cookie_value: Optional[str], returned_state: Optional[str]) -> dict:
    if not cookie_value:
        raise GoogleAuthError("state_cookie_missing")
    try:
        data = jwt.decode(
            cookie_value, _state_key(), algorithms=["HS256"],
            audience="rezef-google-oauth-state",
        )
    except JWTError:
        raise GoogleAuthError("state_cookie_invalid")
    if not returned_state or not hmac.compare_digest(
        str(data.get("state", "")), str(returned_state),
    ):
        raise GoogleAuthError("state_mismatch")
    return data


# --------------------------------------------------------------------- #
# רשת — מוחלפות בטסטים
# --------------------------------------------------------------------- #
def fetch_jwks() -> tuple[dict, int]:
    """מחזיר (jwks, ttl_seconds) לפי Cache-Control של Google."""
    import httpx

    resp = httpx.get(GOOGLE_JWKS_URL, timeout=10.0)
    resp.raise_for_status()
    ttl = _JWKS_DEFAULT_TTL
    match = re.search(r"max-age=(\d+)", resp.headers.get("cache-control", ""))
    if match:
        ttl = int(match.group(1))
    return resp.json(), ttl


def exchange_code(code: str, code_verifier: str) -> dict:
    import httpx

    try:
        resp = httpx.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uri": redirect_uri(),
                "grant_type": "authorization_code",
                "code_verifier": code_verifier,
            },
            timeout=10.0,
        )
    except httpx.HTTPError:
        raise GoogleAuthError("token_endpoint_unavailable")
    if resp.status_code >= 400:
        raise GoogleAuthError("token_exchange_failed")
    return resp.json()


_jwks_cache: dict[str, Any] = {"keys": None, "expires": 0.0}


def _reset_jwks_cache() -> None:
    _jwks_cache["keys"] = None
    _jwks_cache["expires"] = 0.0


def _jwk_for(kid: str) -> dict:
    """מפתח לפי kid, מ-cache. החטאה → רענון אחד (סבב מפתחות), ואז כשל."""
    def refresh() -> None:
        try:
            jwks, ttl = fetch_jwks()
        except Exception:
            raise GoogleAuthError("jwks_unavailable")
        _jwks_cache["keys"] = list(jwks.get("keys", []))
        _jwks_cache["expires"] = time.time() + max(60, int(ttl))

    def find() -> Optional[dict]:
        return next((k for k in _jwks_cache["keys"] or [] if k.get("kid") == kid), None)

    refreshed = False
    if _jwks_cache["keys"] is None or time.time() >= _jwks_cache["expires"]:
        refresh()
        refreshed = True
    key = find()
    if key is None and not refreshed:
        refresh()
        key = find()
    if key is None:
        raise GoogleAuthError("unknown_signing_key")
    return key


# --------------------------------------------------------------------- #
# אימות ID token
# --------------------------------------------------------------------- #
@dataclass
class GoogleIdentity:
    email: str
    subject: str
    name: Optional[str]


def verify_id_token(
    id_token: str,
    *,
    expected_nonce: Optional[str],
    access_token: Optional[str] = None,
) -> GoogleIdentity:
    """אימות מקומי מלא. ``expected_nonce=None`` רק למסלול GIS הישן."""
    client_id = settings.google_client_id
    if not client_id:
        raise GoogleAuthError("not_configured")
    try:
        header = jwt.get_unverified_header(id_token)
    except JWTError:
        raise GoogleAuthError("malformed_token")
    if header.get("alg") != "RS256":
        raise GoogleAuthError("bad_algorithm")
    key = _jwk_for(str(header.get("kid", "")))
    try:
        claims = jwt.decode(
            id_token,
            key,
            algorithms=["RS256"],
            audience=client_id,
            issuer=list(GOOGLE_ISSUERS),
            access_token=access_token,
            options={"leeway": CLOCK_SKEW_SECONDS},
        )
    except ExpiredSignatureError:
        raise GoogleAuthError("token_expired")
    except JWTClaimsError as exc:
        text = str(exc).lower()
        if "audience" in text:
            raise GoogleAuthError("bad_audience")
        if "issuer" in text:
            raise GoogleAuthError("bad_issuer")
        raise GoogleAuthError("bad_claims")
    except JWTError:
        raise GoogleAuthError("bad_signature")

    now = int(time.time())
    iat = claims.get("iat")
    if not isinstance(iat, (int, float)) or iat > now + CLOCK_SKEW_SECONDS:
        raise GoogleAuthError("bad_iat")
    if "exp" not in claims:
        raise GoogleAuthError("token_expired")

    verified = claims.get("email_verified")
    if not (verified is True or str(verified).lower() == "true"):
        raise GoogleAuthError("email_not_verified")
    email = (claims.get("email") or "").strip().lower()
    if not email:
        raise GoogleAuthError("missing_email")

    if expected_nonce is not None:
        if not hmac.compare_digest(str(claims.get("nonce", "")), str(expected_nonce)):
            raise GoogleAuthError("nonce_mismatch")

    return GoogleIdentity(email=email, subject=str(claims.get("sub", "")), name=claims.get("name"))
