"""
Admin API routes
ניהול מערכת, משתמשים, ארגונים וחברות
"""
from fastapi import APIRouter, Depends, HTTPException, Request, status, Query
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, EmailStr
from sqlalchemy import case, func, or_, update
from sqlalchemy.orm import Session
from typing import List, Optional, Dict, Any
import hashlib
import logging
import secrets
from urllib.parse import urlencode
from datetime import date, datetime, timedelta, timezone

from ...database import get_db_session
from ...models import (
    User, Organization, AuditLog, IntegrationConnection, SyncRun,
    UserCreate, UserUpdate, UserResponse, UserLogin, GoogleLogin, Token,
    OrganizationCreate, OrganizationUpdate, OrganizationResponse,
    UserRole, IntegrationType, SumitCompany, Invoice, Bill, BankTransaction,
    Alert, Task, OnboardingTask, AlertStatus, TaskStatus,
    OrganizationSigningAuthority, OrganizationMembership, Account,
    ChatMessage, LLMUsage, MoshkoToolCall, MoshkoMemory, MoshkoFeedback,
    PasswordResetToken, RevokedToken,
)
from ...auth import (
    verify_password, get_password_hash, create_access_token,
    decode_access_token,
)
from ...services.email_sender import send_email_smtp
from ...config import settings
from ...services.sync_engine import SyncEngine, get_connector_for_org
from ...services.client_automation_service import mark_client_loop_result, run_post_sync_tasks
from ...services.account_ownership import ownership_status, review_queue
from ..dependencies import (
    get_current_user,
    security,
    get_super_admin,
    get_organization_admin,
    get_sumit_integration,
    require_admin,
    get_access_context,
    OrganizationAccessContext,
)
from ...integrations.sumit_integration import SumitIntegration
from ...integrations.sumit_models import (
    CompanyRequest, CompanyResponse,
    UserRequest, UserResponse as SumitUserResponse, UserPermission,
    StockItemResponse
)

router = APIRouter()
logger = logging.getLogger(__name__)


def _require_selected_organization(ctx: OrganizationAccessContext, supplied: Optional[int]) -> None:
    """נתיב ארגוני מקבל scope רק מ-OrganizationAccessContext.

    פרמטר legacy מותר רק אם הוא מאשר את אותה בחירה; הוא לעולם אינו
    selector שני, גם לא עבור SUPER_ADMIN.
    """
    if supplied is not None and supplied != ctx.organization_id:
        raise HTTPException(status_code=403, detail="Access denied")


# ==================== Authentication ====================

PLAN_PRICE_FALLBACKS = {
    "company_up_to_2_5m": {"monthly_ils": 750, "label": "חברה / שותפות עד 2.5M"},
    "company_above_2_5m": {"monthly_ils": 750, "label": "חברה בצמיחה מעל 2.5M"},
    "office": {"monthly_ils": None, "label": "רצף Office"},
}

STRIPE_PRICE_ENV_BY_PLAN = {
    "company_up_to_2_5m": "STRIPE_PRICE_COMPANY_UP_TO_2_5M",
    "company_above_2_5m": "STRIPE_PRICE_COMPANY_ABOVE_2_5M",
    "office": "STRIPE_PRICE_OFFICE",
}


class CheckoutCreate(BaseModel):
    selected_plan: str
    annual_revenue: Optional[str] = None
    payment_template: str = "credit_card"
    annual_report_requested: bool = True
    email: Optional[str] = None
    success_path: str = "/"
    cancel_path: str = "/"


SCHEMA_MIGRATION_CONFIRMATION = "I_UNDERSTAND_SCHEMA_MIGRATION_IS_GLOBAL"


class DatabaseMigrationRequest(BaseModel):
    confirmation: str


def _to_float(value) -> float:
    return float(value or 0)


def _freshness_status(last_finished_at: Optional[datetime]) -> dict:
    if not last_finished_at:
        return {
            "state": "never_synced",
            "age_hours": None,
            "label": "טרם סונכרן",
            "is_stale": True,
        }
    now = datetime.now(timezone.utc)
    finished = last_finished_at
    if finished.tzinfo is None:
        finished = finished.replace(tzinfo=timezone.utc)
    age_hours = max((now - finished).total_seconds() / 3600, 0)
    if age_hours <= 2:
        state = "fresh"
        label = "מעודכן"
    elif age_hours <= 24:
        state = "aging"
        label = "דורש רענון"
    else:
        state = "stale"
        label = "לא מעודכן"
    return {
        "state": state,
        "age_hours": round(age_hours, 1),
        "label": label,
        "is_stale": age_hours > 24,
    }


async def _assert_registration_allowed(
    registration_code: Optional[str],
    checkout_session_id: Optional[str] = None,
):
    from ...config import settings
    from os import getenv

    if checkout_session_id:
        if checkout_session_id.startswith("mock_") and getenv("VERCEL_ENV") != "production":
            # Preview/dev: mock checkout satisfies payment. Skip VERCEL registration gate;
            # still enforce registration_secret if one is explicitly configured.
            if not settings.registration_secret:
                return
            # fall through to registration_secret check below
        if settings.stripe_secret_key and checkout_session_id.startswith("cs_"):
            import httpx

            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"https://api.stripe.com/v1/checkout/sessions/{checkout_session_id}",
                    headers={"Authorization": f"Bearer {settings.stripe_secret_key}"},
                )
            if resp.status_code >= 400:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Checkout session could not be verified",
                )
            session = resp.json()
            if session.get("status") == "complete" and session.get("payment_status") in {"paid", "no_payment_required"}:
                return
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Checkout session is not paid",
            )
    if getenv("VERCEL") and not settings.registration_secret:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Self-registration is disabled in production"
        )
    if settings.registration_secret and registration_code != settings.registration_secret:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Registration requires a valid registration code"
        )


def _plan_settings(
    *,
    selected_plan: Optional[str],
    annual_revenue: Optional[str],
    annual_report_requested: Optional[bool],
    payment_template: Optional[str],
    checkout_session_id: Optional[str] = None,
    payment_status: Optional[str] = None,
) -> dict:
    return {
        "selected_plan": selected_plan or "company_above_2_5m",
        "annual_revenue": annual_revenue or "up_to_2_5m",
        "annual_report_requested": annual_report_requested if annual_report_requested is not None else True,
        "payment_template": payment_template or "credit_card",
        "checkout_session_id": checkout_session_id,
        "payment_status": payment_status or ("checkout_started" if checkout_session_id else "pending"),
        "subscription_status": "active" if payment_status in {"paid", "active", "trialing"} else "pending",
        "brand": "rezef",
    }


def _stripe_price_id(plan_id: str) -> Optional[str]:
    from ...config import settings

    return {
        "company_up_to_2_5m": settings.stripe_price_company_up_to_2_5m,
        "company_above_2_5m": settings.stripe_price_company_above_2_5m,
        "office": settings.stripe_price_office,
    }.get(plan_id)


def _billing_readiness() -> dict:
    from ...config import settings
    from os import getenv

    price_ids = {
        "company_up_to_2_5m": settings.stripe_price_company_up_to_2_5m,
        "company_above_2_5m": settings.stripe_price_company_above_2_5m,
        "office": settings.stripe_price_office,
    }
    configured = {
        "stripe_secret_key": bool(settings.stripe_secret_key),
        **{env_name.lower(): bool(price_ids[plan_id]) for plan_id, env_name in STRIPE_PRICE_ENV_BY_PLAN.items()},
    }
    missing = []
    if not settings.stripe_secret_key:
        missing.append("STRIPE_SECRET_KEY")
    missing.extend(env_name for plan_id, env_name in STRIPE_PRICE_ENV_BY_PLAN.items() if not price_ids[plan_id])

    ready = not missing
    production = getenv("VERCEL_ENV") == "production"
    return {
        "provider": "stripe" if ready else "mock" if not production else "stripe",
        "production": production,
        "ready": ready,
        "configured": configured,
        "missing": missing,
        "supports": ["card", "apple_pay", "google_pay"] if ready else [],
        "notes": [
            "Apple Pay and Google Pay are shown by Stripe Checkout when payment methods are enabled on the Stripe account.",
            "Apple Pay requires registering and verifying the production domain in Stripe.",
        ],
    }


async def _create_stripe_checkout(body: CheckoutCreate) -> Optional[dict]:
    from ...config import settings
    import httpx

    if not settings.stripe_secret_key:
        return None
    price_id = _stripe_price_id(body.selected_plan)
    if not price_id:
        return None

    success_url = f"{settings.app_url.rstrip('/')}{body.success_path}?checkout=success&session_id={{CHECKOUT_SESSION_ID}}#signup"
    cancel_url = f"{settings.app_url.rstrip('/')}{body.cancel_path}?checkout=cancelled#plans"
    form = {
        "mode": "subscription",
        "line_items[0][price]": price_id,
        "line_items[0][quantity]": "1",
        "success_url": success_url,
        "cancel_url": cancel_url,
        "client_reference_id": body.selected_plan,
        "metadata[selected_plan]": body.selected_plan,
        "metadata[annual_revenue]": body.annual_revenue or "up_to_2_5m",
        "metadata[payment_template]": body.payment_template,
        "metadata[annual_report_requested]": str(body.annual_report_requested).lower(),
        "allow_promotion_codes": "true",
        "automatic_payment_methods[enabled]": "true",
        "billing_address_collection": "auto",
        "locale": "he",
    }
    if body.email:
        form["customer_email"] = body.email

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            "https://api.stripe.com/v1/checkout/sessions",
            data=form,
            headers={"Authorization": f"Bearer {settings.stripe_secret_key}"},
        )
    if resp.status_code >= 400:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Stripe checkout failed: {resp.text[:300]}",
        )
    session = resp.json()
    return {
        "provider": "stripe",
        "checkout_session_id": session.get("id"),
        "checkout_url": session.get("url"),
        "payment_status": session.get("payment_status") or "checkout_started",
        "subscription_status": "checkout_started",
        "supports": ["card", "apple_pay", "google_pay"],
    }


@router.get("/billing/status", tags=["Billing"])
async def get_billing_status():
    """Expose checkout readiness for the public signup screen."""
    return _billing_readiness()


@router.post("/billing/checkout", tags=["Billing"])
async def create_billing_checkout(body: CheckoutCreate):
    """Create a signup checkout session before tenant registration."""
    if body.selected_plan not in PLAN_PRICE_FALLBACKS:
        raise HTTPException(status_code=400, detail="Unknown plan")

    stripe_session = await _create_stripe_checkout(body)
    if stripe_session:
        return stripe_session

    from os import getenv
    if getenv("VERCEL_ENV") == "production":
        readiness = _billing_readiness()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "התשלום בפרודקשן עדיין לא הופעל. חסרים משתני סביבה: "
                + ", ".join(readiness["missing"])
                + ". אחרי הגדרת Stripe Price IDs ואימות הדומיין, Apple Pay/Google Pay יופיעו ב-checkout."
            ),
        )

    session_id = "mock_" + secrets.token_urlsafe(18)
    query = urlencode({
        "checkout": "mock",
        "session_id": session_id,
        "plan": body.selected_plan,
    })
    fallback = PLAN_PRICE_FALLBACKS[body.selected_plan]
    return {
        "provider": "mock",
        "checkout_session_id": session_id,
        "checkout_url": f"{body.success_path}?{query}#signup",
        "payment_status": "mock_ready",
        "subscription_status": "pending",
        "supports": ["card", "apple_pay", "google_pay"],
        "plan": {
            "id": body.selected_plan,
            "label": fallback["label"],
            "monthly_ils": fallback["monthly_ils"],
        },
        "note": "Stripe is not configured; checkout is simulated for onboarding.",
    }


def _create_self_registered_user(
    db: Session,
    *,
    email: str,
    full_name: str,
    password_hash: str,
    phone: Optional[str] = None,
    organization_id: Optional[int] = None,
    selected_plan: Optional[str] = None,
    annual_revenue: Optional[str] = None,
    annual_report_requested: Optional[bool] = None,
    payment_template: Optional[str] = None,
    checkout_session_id: Optional[str] = None,
    payment_status: Optional[str] = None,
) -> User:
    requested_organization_id = organization_id
    existing_user = db.query(User).filter(User.email == email).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )
    
    if organization_id:
        org = db.query(Organization).filter(Organization.id == organization_id).first()
        if not org:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Organization not found"
            )
    
    # Open registration must never honor a client-supplied role: the first
    # registered user bootstraps the system as admin, everyone after that
    # starts as a regular user and is promoted by an admin.
    is_first_user = db.query(User).first() is None

    # Every self-registered user gets an organization of their own (and is
    # its admin), so integrations/credentials are isolated per tenant. On a
    # fresh PostgreSQL database this row must be created before the user because
    # the FK is enforced (SQLite tests historically hid that bootstrapping bug).
    if organization_id is None:
        org = db.query(Organization).filter(Organization.id == 1).first() if is_first_user else None
        if org is None:
            org = Organization(
                name=f"{full_name}",
                business_type="financial_management",
                integration_type=IntegrationType.MANUAL,
                settings={
                    "self_registered": True,
                    **_plan_settings(
                        selected_plan=selected_plan,
                        annual_revenue=annual_revenue,
                        annual_report_requested=annual_report_requested,
                        payment_template=payment_template,
                        checkout_session_id=checkout_session_id,
                        payment_status=payment_status,
                    ),
                },
                is_active=True,
            )
            db.add(org)
            db.flush()
        organization_id = org.id

    if (
        selected_plan or annual_revenue or annual_report_requested is not None
        or payment_template or checkout_session_id or payment_status
    ):
        org = db.query(Organization).filter(Organization.id == organization_id).first()
        if org:
            org.settings = {
                **(org.settings or {}),
                **_plan_settings(
                    selected_plan=selected_plan or (org.settings or {}).get("selected_plan"),
                    annual_revenue=annual_revenue or (org.settings or {}).get("annual_revenue"),
                    annual_report_requested=(
                        annual_report_requested
                        if annual_report_requested is not None
                        else (org.settings or {}).get("annual_report_requested")
                    ),
                    payment_template=payment_template or (org.settings or {}).get("payment_template"),
                    checkout_session_id=checkout_session_id or (org.settings or {}).get("checkout_session_id"),
                    payment_status=payment_status or (org.settings or {}).get("payment_status"),
                ),
            }

    new_user = User(
        email=email,
        password_hash=password_hash,
        full_name=full_name,
        phone=phone,
        role=UserRole.ADMIN if is_first_user or requested_organization_id is None else UserRole.USER,
        organization_id=organization_id,
    )
    
    db.add(new_user)
    db.flush()

    # חברות באותה טרנזקציה כמו המשתמש והארגון.
    #
    # בלי זה, המשתמש החדש היה נשאר בלי מקור סמכות ונחסם. ארגון שנוצר
    # בלי חברות הוא גם תיק שאיש אינו יכול לפתוח.
    #
    # `flush` ולא `commit`: אם שלב מאוחר יותר ייכשל, המשתמש, הארגון
    # והחברות מתגלגלים אחורה יחד.
    from ...services import membership_service as _membership_service

    _membership_service.grant(
        db,
        organization_id=organization_id,
        user_id=new_user.id,
        role=new_user.role,
        granted_by_user_id=new_user.id,
        status="active",
    )

    if requested_organization_id is None:
        existing_authority = db.query(OrganizationSigningAuthority).filter(
            OrganizationSigningAuthority.organization_id == organization_id,
            OrganizationSigningAuthority.is_active.is_(True),
        ).first()
        if existing_authority is None:
            authority = OrganizationSigningAuthority(
                organization_id=organization_id,
                user_id=new_user.id,
                authority_type="owner",
                action_types=["*"],
                is_active=True,
                granted_by_user_id=new_user.id,
            )
            db.add(authority)
            db.flush()
            db.add(AuditLog(
                user_id=new_user.id,
                organization_id=organization_id,
                action="BOOTSTRAP_OWNER_AUTHORITY",
                entity_type="OrganizationSigningAuthority",
                entity_id=authority.id,
                details={"source": "self_registration"},
            ))
    db.commit()
    db.refresh(new_user)
    return new_user


def _token_for_user(user: User) -> Token:
    access_token = create_access_token(data={
        "sub": user.id,
        "role": user.role.value,
        "token_version": user.token_version or 0,
    })
    return Token(
        access_token=access_token,
        user=UserResponse.model_validate(user)
    )


@router.post("/auth/register", response_model=Token, status_code=status.HTTP_201_CREATED, tags=["Auth"])
async def register(
    user_data: UserCreate,
    db: Session = Depends(get_db_session)
):
    """הרשמת משתמש חדש"""
    await _assert_registration_allowed(user_data.registration_code, user_data.checkout_session_id)
    new_user = _create_self_registered_user(
        db,
        email=user_data.email,
        full_name=user_data.full_name,
        password_hash=get_password_hash(user_data.password),
        phone=user_data.phone,
        organization_id=user_data.organization_id,
        selected_plan=user_data.selected_plan,
        annual_revenue=user_data.annual_revenue,
        annual_report_requested=user_data.annual_report_requested,
        payment_template=user_data.payment_template,
        checkout_session_id=user_data.checkout_session_id,
        payment_status=user_data.payment_status,
    )
    return _token_for_user(new_user)


@router.post("/auth/google", response_model=Token, tags=["Auth"])
async def google_login(
    login_data: GoogleLogin,
    db: Session = Depends(get_db_session),
):
    """Login or register with a verified Google ID token."""
    from ...config import settings
    import httpx

    if not settings.google_client_id:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google Sign-In is not configured"
        )

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            "https://oauth2.googleapis.com/tokeninfo",
            params={"id_token": login_data.id_token},
        )
    if resp.status_code >= 400:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Google token")

    payload = resp.json()
    if payload.get("aud") != settings.google_client_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Google token audience mismatch")
    if str(payload.get("email_verified")).lower() != "true":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Google email is not verified")

    email = payload.get("email")
    if not email:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Google token missing email")

    user = db.query(User).filter(User.email == email).first()
    if user:
        if not user.is_active:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User account is disabled")
        user.last_login = datetime.now(timezone.utc)
        db.commit()
        db.refresh(user)
        return _token_for_user(user)

    await _assert_registration_allowed(login_data.registration_code, login_data.checkout_session_id)
    full_name = payload.get("name") or email.split("@", 1)[0]
    new_user = _create_self_registered_user(
        db,
        email=email,
        full_name=full_name,
        password_hash=get_password_hash(secrets.token_urlsafe(32)),
        selected_plan=login_data.selected_plan,
        annual_revenue=login_data.annual_revenue,
        annual_report_requested=login_data.annual_report_requested,
        payment_template=login_data.payment_template,
        checkout_session_id=login_data.checkout_session_id,
        payment_status=login_data.payment_status,
    )
    return _token_for_user(new_user)


# --- הקשחת login (W6.7) --- #
# 5 כישלונות רצופים → נעילה ל-15 דקות. המונה במסד (serverless — אין state
# בזיכרון). הודעת הכישלון זהה בין "מייל לא קיים" ל"סיסמה שגויה" כדי לא
# לאפשר enumeration של חשבונות.
LOGIN_LOCKOUT_THRESHOLD = 5
LOGIN_LOCKOUT_MINUTES = 15
# שכבת מקור משלימה את נעילת החשבון: תוקף מאותו מקור אינו יכול לסרוק
# חשבונות ללא גבול. המונה עמיד ומשותף בין instances דרך מסד הנתונים.
# ‏config ולא קבוע: סוויטת הטסטים כולה מגיעה ממקור אחד ("testserver")
# וחוצה 60/דקה בלגיטימיות — בסביבת טסט התקרה מוגבהת דרך env.
LOGIN_SOURCE_ATTEMPTS_PER_MINUTE = settings.auth_source_attempts_per_minute
LOGIN_FAILED_DETAIL = "אימייל או סיסמה שגויים"
LOGIN_LOCKED_DETAIL = (
    "החשבון נעול זמנית עקב ניסיונות התחברות כושלים חוזרים. "
    f"נסו שוב בעוד כ-{LOGIN_LOCKOUT_MINUTES} דקות, או אפסו סיסמה."
)


def _login_source_scope(request: Request) -> str:
    """Return a privacy-preserving, stable login source key.

    Vercel/proxy deployments supply the original client in forwarding headers;
    direct ASGI deployments fall back to ``request.client.host``. Only a hash
    is persisted in provider_request_budgets, not the raw IP address.
    """
    source = ""
    for header in ("x-vercel-forwarded-for", "x-forwarded-for", "x-real-ip"):
        value = request.headers.get(header, "")
        if value:
            source = value.split(",", 1)[0].strip()
            if source:
                break
    if not source and request.client is not None:
        source = request.client.host or ""
    if not source:
        # Fail into one shared bucket instead of producing a unique key that
        # would silently disable throttling when client metadata is absent.
        source = "unknown"
    digest = hashlib.sha256(source.encode("utf-8")).hexdigest()[:40]
    return f"source:{digest}"


def _claim_login_source(db: Session, request: Request, *, now: datetime) -> bool:
    """Atomically claim one source login attempt in the current UTC minute."""
    from ...services.sumit_request_budget import SumitRequestLimiter

    window_start = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    return SumitRequestLimiter._claim_window(
        db,
        provider="auth",
        scope_key=_login_source_scope(request),
        organization_id=None,
        window_kind="minute",
        window_start=window_start,
        limit_value=LOGIN_SOURCE_ATTEMPTS_PER_MINUTE,
        now=now.replace(tzinfo=timezone.utc),
    )


def _record_failed_login(
    db: Session,
    user_id: int,
    *,
    now: datetime,
) -> tuple[int, Optional[datetime]]:
    """Increment failures and derive lock state in one atomic UPDATE.

    The returned count is the database result of ``failed + 1``; it never
    depends on an ORM object that another worker may have loaded earlier.
    """
    next_attempt = func.coalesce(User.failed_login_attempts, 0) + 1
    lock_until = now + timedelta(minutes=LOGIN_LOCKOUT_MINUTES)
    statement = (
        update(User)
        .where(User.id == user_id)
        .values(
            failed_login_attempts=next_attempt,
            locked_until=case(
                (next_attempt >= LOGIN_LOCKOUT_THRESHOLD, lock_until),
                else_=User.locked_until,
            ),
        )
        .returning(User.failed_login_attempts, User.locked_until)
        .execution_options(synchronize_session=False)
    )
    row = db.execute(statement).one()
    return int(row.failed_login_attempts), row.locked_until


@router.post("/auth/login", response_model=Token, tags=["Auth"])
async def login(
    login_data: UserLogin,
    request: Request,
    db: Session = Depends(get_db_session)
):
    """התחברות למערכת — עם נעילה זמנית אחרי כישלונות חוזרים"""
    now = datetime.utcnow()
    try:
        source_claimed = _claim_login_source(db, request, now=now)
        if source_claimed:
            # Unknown-user failures also need a durable claim; commit this
            # security counter independently of the authentication outcome.
            db.commit()
        else:
            db.rollback()
    except Exception:
        db.rollback()
        logger.exception("auth login source limiter unavailable")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="שירות ההתחברות אינו זמין זמנית. נסו שוב מאוחר יותר.",
        )
    if not source_claimed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="יותר מדי ניסיונות התחברות ממקור זה. נסו שוב בעוד דקה.",
        )

    user = db.query(User).filter(User.email == login_data.email).first()

    # נעילה נבדקת לפני אימות הסיסמה: חשבון נעול נשאר נעול גם מול סיסמה
    # נכונה, אחרת התוקף פשוט ממשיך לנחש בזמן הנעילה.
    if user is not None and user.locked_until is not None:
        if user.locked_until > now:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=LOGIN_LOCKED_DETAIL,
            )
        # הנעילה פגה — מתחילים חלון ספירה נקי
        db.execute(
            update(User)
            .where(
                User.id == user.id,
                User.locked_until.is_not(None),
                User.locked_until <= now,
            )
            .values(locked_until=None, failed_login_attempts=0)
            .execution_options(synchronize_session=False)
        )
        db.commit()
        db.refresh(user)

    if not user or not verify_password(login_data.password, user.password_hash):
        if user is not None:
            _record_failed_login(db, user.id, now=now)
            db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=LOGIN_FAILED_DETAIL,
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is disabled"
        )

    # Update last login; הצלחה מאפסת את מונה הכישלונות
    user.last_login = datetime.now(timezone.utc)
    user.failed_login_attempts = 0
    user.locked_until = None
    db.commit()
    
    # Log login
    audit_log = AuditLog(
        user_id=user.id,
        organization_id=user.organization_id,
        action="LOGIN",
        entity_type="User",
        entity_id=user.id
    )
    db.add(audit_log)
    db.commit()
    
    access_token = create_access_token(
        data={
            "sub": user.id,
            "role": user.role.value,
            "org_id": user.organization_id,
            "token_version": user.token_version or 0,
        }
    )
    
    return Token(
        access_token=access_token,
        user=UserResponse.model_validate(user)
    )


# ==================== סיסמאות וטוקנים (W6.7) ====================

MIN_PASSWORD_LENGTH = 8
SHORT_PASSWORD_DETAIL = "הסיסמה חייבת להכיל לפחות 8 תווים"
RESET_TOKEN_TTL_MINUTES = 30
# תשובה זהה בין מייל קיים ללא-קיים — anti-enumeration
RESET_NEUTRAL_MESSAGE = "אם הכתובת קיימת במערכת, נשלח אליה קישור לאיפוס הסיסמה."


def _require_min_password(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=SHORT_PASSWORD_DETAIL,
        )


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str

    model_config = {"extra": "forbid"}


class PasswordResetRequest(BaseModel):
    email: EmailStr

    model_config = {"extra": "forbid"}


class PasswordResetConfirm(BaseModel):
    token: str
    new_password: str

    model_config = {"extra": "forbid"}


def _claim_password_reset_token(
    db: Session,
    token_hash: str,
    *,
    now: datetime,
) -> Optional[int]:
    """Atomically mark one valid reset token used and return its user id.

    ``rowcount == 0`` is the only rejection signal: the token is unknown,
    expired, or another transaction already claimed it. The follow-up query is
    in the same transaction, while the successful UPDATE keeps the row claimed
    until the password change commits.
    """
    claim = db.execute(
        update(PasswordResetToken)
        .where(
            PasswordResetToken.token_hash == token_hash,
            PasswordResetToken.used_at.is_(None),
            PasswordResetToken.expires_at >= now,
        )
        .values(used_at=now)
        .execution_options(synchronize_session=False)
    )
    if claim.rowcount != 1:
        return None
    return db.query(PasswordResetToken.user_id).filter(
        PasswordResetToken.token_hash == token_hash,
    ).scalar()


@router.post("/auth/change-password", tags=["Auth"])
async def change_password(
    body: ChangePasswordRequest,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
):
    """שינוי סיסמה למשתמש מחובר — מאומת מול הסיסמה הנוכחית."""
    _require_min_password(body.new_password)
    if not verify_password(body.current_password, current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="הסיסמה הנוכחית שגויה",
        )
    new_password_hash = get_password_hash(body.new_password)
    db.execute(
        update(User)
        .where(User.id == current_user.id)
        .values(
            password_hash=new_password_hash,
            token_version=User.token_version + 1,
        )
        .execution_options(synchronize_session=False)
    )
    db.add(AuditLog(
        user_id=current_user.id,
        organization_id=current_user.organization_id,
        action="PASSWORD_CHANGE",
        entity_type="User",
        entity_id=current_user.id,
    ))
    db.commit()
    return {"message": "הסיסמה עודכנה בהצלחה"}


@router.post("/auth/request-password-reset", tags=["Auth"])
async def request_password_reset(
    body: PasswordResetRequest,
    request: Request,
    db: Session = Depends(get_db_session),
):
    """שלב א' של "שכחתי סיסמה": הנפקת טוקן חד-פעמי ושליחתו במייל.

    honest-null: בלי SMTP מוגדר אין דרך לשלוח קישור — 503 כן, לא "נשלח"
    מומצא. הבדיקה נעשית לפני חיפוש המשתמש, ולכן אחידה לכל כתובת.
    """
    if not (settings.smtp_host and settings.smtp_from):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "שליחת מייל אינה מוגדרת במערכת (SMTP). "
                "פנו למנהל המערכת לאיפוס סיסמה ידני."
            ),
        )

    user = db.query(User).filter(User.email == body.email).first()
    if user is not None and user.is_active:
        raw_token = secrets.token_urlsafe(32)
        db.add(PasswordResetToken(
            user_id=user.id,
            token_hash=hashlib.sha256(raw_token.encode()).hexdigest(),
            expires_at=datetime.utcnow() + timedelta(minutes=RESET_TOKEN_TTL_MINUTES),
        ))
        db.commit()

        # Canonical public URL prevents Host-header/proxy injection into reset
        # mail. Empty legacy configuration falls back explicitly and loudly.
        configured_base = (settings.app_url or "").strip()
        if configured_base:
            base = configured_base.rstrip("/")
        else:
            logger.warning(
                "settings.app_url is empty; password reset URL falls back to request.base_url",
            )
            base = str(request.base_url).rstrip("/")
        reset_link = f"{base}/reset-password?token={raw_token}"
        await send_email_smtp(
            user.email,
            "איפוס סיסמה — רצף",
            (
                "שלום,\n\n"
                "התקבלה בקשה לאיפוס הסיסמה בחשבונך במערכת רצף.\n"
                f"לאיפוס הסיסמה היכנסו לקישור הבא (תקף ל-{RESET_TOKEN_TTL_MINUTES} דקות):\n\n"
                f"{reset_link}\n\n"
                "אם לא ביקשתם איפוס — התעלמו מהודעה זו; הסיסמה לא שונתה.\n"
            ),
            settings,
        )

    # אותה תשובה בדיוק גם כשהמייל אינו קיים
    return {"message": RESET_NEUTRAL_MESSAGE}


@router.post("/auth/reset-password", tags=["Auth"])
async def reset_password(
    body: PasswordResetConfirm,
    db: Session = Depends(get_db_session),
):
    """שלב ב' של "שכחתי סיסמה": אימות הטוקן וקביעת סיסמה חדשה."""
    _require_min_password(body.new_password)

    invalid_token = HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=(
            "קישור האיפוס אינו תקף — ייתכן שפג תוקפו או שכבר נעשה בו "
            "שימוש. בקשו קישור חדש."
        ),
    )

    now = datetime.utcnow()
    token_hash = hashlib.sha256(body.token.encode()).hexdigest()
    user_id = _claim_password_reset_token(db, token_hash, now=now)
    if user_id is None:
        raise invalid_token

    user = db.query(User).filter(User.id == user_id).first()
    if user is None or not user.is_active:
        db.rollback()
        raise invalid_token

    new_password_hash = get_password_hash(body.new_password)
    db.execute(
        update(User)
        .where(User.id == user.id)
        .values(
            password_hash=new_password_hash,
            # איפוס מוצלח משחרר גם נעילת login — המשתמש הוכיח שליטה במייל.
            failed_login_attempts=0,
            locked_until=None,
            token_version=User.token_version + 1,
        )
        .execution_options(synchronize_session=False)
    )
    db.add(AuditLog(
        user_id=user.id,
        organization_id=user.organization_id,
        action="PASSWORD_RESET",
        entity_type="User",
        entity_id=user.id,
    ))
    db.commit()
    return {"message": "הסיסמה אופסה בהצלחה. אפשר להתחבר עם הסיסמה החדשה."}


@router.post("/auth/logout", tags=["Auth"])
async def logout(
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
):
    """התנתקות — ביטול הטוקן הנוכחי דרך denylist לפי jti.

    טוקן ישן בלי jti אינו ניתן לביטול (תאימות לאחור) — התשובה אומרת
    זאת בפירוש במקום להעמיד פני הצלחה.
    """
    # ניקוי הזדמנותי: רשומות denylist שהטוקן שלהן ממילא פג נמחקות
    db.query(RevokedToken).filter(
        RevokedToken.expires_at.isnot(None),
        RevokedToken.expires_at < datetime.utcnow(),
    ).delete(synchronize_session=False)

    payload = decode_access_token(credentials.credentials) if credentials else None
    jti = (payload or {}).get("jti")
    if not jti:
        db.commit()
        return {
            "revoked": False,
            "message": (
                "לטוקן הזה אין מזהה ביטול (jti) — טוקן מדור קודם שאינו "
                "ניתן לביטול; הוא יפוג מעצמו במועד התפוגה."
            ),
        }

    exp = payload.get("exp")
    expires_at = datetime.utcfromtimestamp(exp) if exp else None
    already = db.query(RevokedToken.id).filter(RevokedToken.jti == jti).first()
    if already is None:
        db.add(RevokedToken(
            jti=jti,
            revoked_at=datetime.utcnow(),
            expires_at=expires_at,
        ))
    db.add(AuditLog(
        user_id=current_user.id,
        organization_id=current_user.organization_id,
        action="LOGOUT",
        entity_type="User",
        entity_id=current_user.id,
    ))
    db.commit()
    return {"revoked": True, "message": "ההתנתקות הושלמה והטוקן בוטל."}


@router.post("/db/migrate", tags=["Admin"])
async def run_db_migrations(
    request: DatabaseMigrationRequest,
    current_user: User = Depends(get_super_admin),
    db: Session = Depends(get_db_session),
):
    """
    Apply the global schema transition after explicit operator confirmation.

    This endpoint is intentionally SUPER_ADMIN-only: organization admins do
    not own the shared database schema. Legacy ``create_all`` databases are
    repaired additively, verified against the ORM contract, and only then
    stamped to Alembic head.
    """
    from pathlib import Path

    from alembic.config import Config as AlembicConfig

    from ...database import engine
    from ...services.schema_deployment import reconcile_schema_to_head

    if request.confirmation != SCHEMA_MIGRATION_CONFIRMATION:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Exact confirmation required: "
                f"{SCHEMA_MIGRATION_CONFIRMATION}"
            ),
        )

    root = Path(__file__).resolve().parents[4]
    cfg = AlembicConfig(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "alembic"))

    result = reconcile_schema_to_head(engine, alembic_config=cfg)

    with engine.connect() as conn:
        from sqlalchemy import text
        revision = conn.execute(text("select version_num from alembic_version")).scalar()

    db.add(AuditLog(
        user_id=current_user.id,
        organization_id=current_user.organization_id,
        action="GLOBAL_SCHEMA_MIGRATION",
        entity_type="DatabaseSchema",
        details={
            "action": result["action"],
            "current_revision": revision,
            "schema_sync": result["schema_sync"],
        },
    ))
    db.commit()

    return {
        **result,
        "current_revision": revision,
    }


@router.get("/auth/me", response_model=UserResponse, tags=["Auth"])
async def get_current_user_info(
    current_user: User = Depends(get_current_user)
):
    """קבלת מידע על המשתמש המחובר"""
    return UserResponse.model_validate(current_user)


# ==================== Organizations Management ====================

@router.post("/organizations", response_model=OrganizationResponse, status_code=status.HTTP_201_CREATED, tags=["Organizations"])
async def create_organization(
    org_data: OrganizationCreate,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_super_admin)
):
    """יצירת ארגון חדש (רק super admin)"""
    new_org = Organization(
        name=org_data.name,
        business_type=org_data.business_type,
        tax_id=org_data.tax_id,
        phone=org_data.phone,
        email=org_data.email,
        address=org_data.address,
        integration_type=org_data.integration_type,
        api_credentials=org_data.api_credentials or {}
    )
    
    db.add(new_org)
    db.commit()
    db.refresh(new_org)
    
    audit_log = AuditLog(
        user_id=current_user.id,
        action="CREATE",
        entity_type="Organization",
        entity_id=new_org.id,
        details={"name": new_org.name}
    )
    db.add(audit_log)
    db.commit()
    
    return OrganizationResponse.model_validate(new_org)


@router.get("/organizations", response_model=List[OrganizationResponse], tags=["Organizations"])
async def list_organizations(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_super_admin)
):
    """רשימת כל הארגונים (רק super admin)"""
    orgs = db.query(Organization).offset(skip).limit(limit).all()
    return [OrganizationResponse.model_validate(org) for org in orgs]


@router.get("/control/clients", tags=["Super Admin Control"])
async def super_admin_clients_overview(
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_super_admin),
):
    """Global super-admin control plane over every tenant organization."""
    orgs = db.query(Organization).order_by(Organization.id.asc()).all()
    roster_by_org: Dict[int, SumitCompany] = {
        row.target_organization_id: row
        for row in db.query(SumitCompany).filter(
            SumitCompany.target_organization_id.isnot(None),
        ).all()
    }
    clients = []
    invoice_stats = {
        row.organization_id: row
        for row in db.query(
            Invoice.organization_id,
            func.count(Invoice.id).label("count"),
            func.coalesce(func.sum(Invoice.total), 0).label("total"),
        ).group_by(Invoice.organization_id).all()
    }
    bill_stats = {
        row.organization_id: row
        for row in db.query(
            Bill.organization_id,
            func.count(Bill.id).label("count"),
            func.coalesce(func.sum(Bill.total), 0).label("total"),
        ).group_by(Bill.organization_id).all()
    }
    bank_stats = {
        row.organization_id: row
        for row in db.query(
            BankTransaction.organization_id,
            func.count(BankTransaction.id).label("count"),
            func.sum(case((BankTransaction.is_reconciled.is_(False), 1), else_=0)).label("unreconciled_count"),
        ).group_by(BankTransaction.organization_id).all()
    }
    alert_stats = {
        row.organization_id: row
        for row in db.query(
            Alert.organization_id,
            func.count(Alert.id).label("open_count"),
        ).filter(
            Alert.status.in_([AlertStatus.ACTIVE, AlertStatus.ACKNOWLEDGED])
        ).group_by(Alert.organization_id).all()
    }
    task_stats = {
        row.organization_id: row
        for row in db.query(
            Task.organization_id,
            func.count(Task.id).label("open_count"),
        ).filter(
            Task.status.in_([TaskStatus.OPEN, TaskStatus.IN_PROGRESS])
        ).group_by(Task.organization_id).all()
    }
    onboarding_stats = {
        row.organization_id: row
        for row in db.query(
            OnboardingTask.organization_id,
            func.count(OnboardingTask.id).label("total"),
            func.sum(case((OnboardingTask.status == "completed", 1), else_=0)).label("completed"),
            func.sum(case((OnboardingTask.status == "failed", 1), else_=0)).label("failed"),
        ).group_by(OnboardingTask.organization_id).all()
    }

    for org in orgs:
        today = date.today()
        soon = today + timedelta(days=14)
        roster = roster_by_org.get(org.id)
        connections = db.query(IntegrationConnection).filter(
            IntegrationConnection.organization_id == org.id,
        ).all()
        connection_statuses = {c.source: c.status for c in connections}
        if org.id == 1 and settings.sumit_api_key and "sumit" not in connection_statuses:
            connection_statuses["sumit"] = "env"

        last_sync = db.query(SyncRun).filter(
            SyncRun.organization_id == org.id,
        ).order_by(SyncRun.created_at.desc()).first()

        users_count = db.query(User).filter(User.organization_id == org.id).count()
        active_connections = [
            source for source, status_value in connection_statuses.items()
            if status_value in {"active", "env", "ACTIVE"}
        ]
        inv = invoice_stats.get(org.id)
        bills = bill_stats.get(org.id)
        bank = bank_stats.get(org.id)
        alerts = alert_stats.get(org.id)
        tasks = task_stats.get(org.id)
        onboarding = onboarding_stats.get(org.id)
        revenue = float(inv.total or 0) if inv else 0.0
        expenses = abs(float(bills.total or 0)) if bills else 0.0
        net_profit = revenue - expenses
        ar_open = _to_float(db.query(func.coalesce(func.sum(Invoice.balance), 0)).filter(
            Invoice.organization_id == org.id,
            Invoice.balance > 0,
        ).scalar())
        ap_open = _to_float(db.query(func.coalesce(func.sum(Bill.balance), 0)).filter(
            Bill.organization_id == org.id,
            Bill.balance > 0,
        ).scalar())
        overdue_ar = int(db.query(func.count(Invoice.id)).filter(
            Invoice.organization_id == org.id,
            Invoice.balance > 0,
            Invoice.due_date.isnot(None),
            Invoice.due_date < today,
        ).scalar() or 0)
        due_ap_14d = int(db.query(func.count(Bill.id)).filter(
            Bill.organization_id == org.id,
            Bill.balance > 0,
            Bill.due_date.isnot(None),
            Bill.due_date >= today,
            Bill.due_date <= soon,
        ).scalar() or 0)
        unreconciled_count = int(bank.unreconciled_count or 0) if bank else 0
        open_alerts = int(alerts.open_count or 0) if alerts else 0
        open_tasks = int(tasks.open_count or 0) if tasks else 0
        onboarding_total = int(onboarding.total or 0) if onboarding else 0
        onboarding_completed = int(onboarding.completed or 0) if onboarding else 0
        onboarding_failed = int(onboarding.failed or 0) if onboarding else 0
        onboarding_pending = max(onboarding_total - onboarding_completed - onboarding_failed, 0)
        freshness = _freshness_status(last_sync.finished_at if last_sync else None)
        action_score = (
            (1 if (last_sync and last_sync.error_summary) else 0)
            + (1 if freshness["is_stale"] else 0)
            + min(unreconciled_count, 10)
            + min(overdue_ar, 10)
            + min(due_ap_14d, 10)
            + min(open_alerts, 10)
            + min(open_tasks, 10)
            + onboarding_failed
            + onboarding_pending
        )

        clients.append({
            "organization_id": org.id,
            "name": org.name,
            "roster_id": roster.id if roster else None,
            "sumit_company_id": roster.company_id if roster else None,
            "office_organization_id": roster.office_organization_id if roster else None,
            "business_type": org.business_type,
            "tax_id": org.tax_id,
            "email": org.email,
            "is_active": org.is_active,
            "users_count": users_count,
            "connections": active_connections,
            "connection_statuses": connection_statuses,
            "automation": (roster.raw_data or {}).get("automation", {}) if roster else {},
            "roster_last_synced_at": roster.last_synced_at.isoformat() if roster and roster.last_synced_at else None,
            "finance": {
                "invoice_count": int(inv.count) if inv else 0,
                "bill_count": int(bills.count) if bills else 0,
                "bank_transaction_count": int(bank.count) if bank else 0,
                "revenue": revenue,
                "expenses": expenses,
                "net_profit": net_profit,
                "ar_open": ar_open,
                "ap_open": ap_open,
                "overdue_ar_count": overdue_ar,
                "ap_due_14d_count": due_ap_14d,
                "has_activity": bool((inv and inv.count) or (bills and bills.count) or (bank and bank.count)),
            },
            "freshness": freshness,
            "work_queues": {
                "unreconciled_bank_transactions": unreconciled_count,
                "overdue_receivables": overdue_ar,
                "payables_due_14d": due_ap_14d,
                "open_alerts": open_alerts,
                "open_tasks": open_tasks,
                "onboarding_pending": onboarding_pending,
                "onboarding_failed": onboarding_failed,
                "action_score": action_score,
            },
            "reconciliation": {
                "matched": int((bank.count or 0) - unreconciled_count) if bank else 0,
                "txn_count": int(bank.count or 0) if bank else 0,
                "unmatched_txns": unreconciled_count,
                "coverage_pct": round((((bank.count or 0) - unreconciled_count) / bank.count) * 100, 1) if bank and bank.count else None,
            },
            "last_sync": {
                "id": last_sync.id,
                "source": last_sync.source,
                "status": last_sync.status.value if last_sync.status else None,
                "started_at": last_sync.started_at.isoformat() if last_sync.started_at else None,
                "finished_at": last_sync.finished_at.isoformat() if last_sync.finished_at else None,
                "error_summary": last_sync.error_summary,
                "counts": last_sync.counts,
            } if last_sync else None,
        })

    totals = {
        "organizations": len(clients),
        "roster_clients": sum(1 for c in clients if c["roster_id"] is not None),
        "connected_sumit": sum(1 for c in clients if "sumit" in c["connections"]),
        "connected_open_finance": sum(1 for c in clients if "open_finance" in c["connections"]),
        "with_sync_errors": sum(1 for c in clients if (c["last_sync"] or {}).get("error_summary")),
        "total_revenue": sum(c["finance"]["revenue"] for c in clients),
        "total_expenses": sum(c["finance"]["expenses"] for c in clients),
        "net_profit": sum(c["finance"]["net_profit"] for c in clients),
        "with_financial_activity": sum(1 for c in clients if c["finance"]["has_activity"]),
        "stale_clients": sum(1 for c in clients if c["freshness"]["is_stale"]),
        "unreconciled_bank_transactions": sum(c["work_queues"]["unreconciled_bank_transactions"] for c in clients),
        "overdue_receivables": sum(c["work_queues"]["overdue_receivables"] for c in clients),
        "payables_due_14d": sum(c["work_queues"]["payables_due_14d"] for c in clients),
        "open_alerts": sum(c["work_queues"]["open_alerts"] for c in clients),
        "open_tasks": sum(c["work_queues"]["open_tasks"] for c in clients),
        "onboarding_pending": sum(c["work_queues"]["onboarding_pending"] for c in clients),
        "action_score": sum(c["work_queues"]["action_score"] for c in clients),
    }
    return {"operator_org_id": current_user.organization_id, "totals": totals, "clients": clients}


@router.post("/control/clients/{org_id}/sync", tags=["Super Admin Control"])
async def super_admin_sync_client(
    org_id: int,
    entity_types: Optional[str] = Query(None),
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_super_admin),
):
    """Run an on-demand sync for one tenant as super admin."""
    org = db.query(Organization).filter(Organization.id == org_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    targets = {
        conn.source for conn in db.query(IntegrationConnection).filter(
            IntegrationConnection.organization_id == org_id,
            IntegrationConnection.status == "active",
        ).all()
    }
    if org_id == 1 and settings.sumit_api_key:
        targets.add("sumit")

    if not targets:
        return {"organization_id": org_id, "synced": 0, "results": []}

    types = [t.strip() for t in entity_types.split(",") if t.strip()] if entity_types else None
    results = []
    for source in sorted(targets):
        connector = None
        try:
            connector, conn_id, resolved = get_connector_for_org(db, org_id, source)
            engine = SyncEngine(db, connector, org_id, resolved, conn_id)
            run = await engine.run_full_sync(entity_types=types)
            automation = await run_post_sync_tasks(
                db, org_id, sources=[resolved], resume_onboarding=True
            )
            mark_client_loop_result(
                db,
                organization_id=org_id,
                source=resolved,
                ok=run.status.value in {"completed", "partial"},
                summary={
                    "sync_run_id": run.id,
                    "status": run.status.value if run.status else None,
                    "counts": run.counts,
                    "error_summary": run.error_summary,
                },
                error=run.error_summary,
            )
            db.commit()
            results.append({
                "source": resolved,
                "sync_run_id": run.id,
                "status": run.status.value if run.status else None,
                "counts": run.counts,
                "error_summary": run.error_summary,
                "automation": automation,
            })
        except Exception as exc:  # noqa: BLE001 - surfaced to operator dashboard
            results.append({"source": source, "status": "error", "error": str(exc)})
        finally:
            if connector is not None:
                try:
                    await connector.close()
                except Exception:
                    pass

    return {
        "organization_id": org_id,
        "synced": sum(1 for r in results if r.get("status") in {"completed", "partial"}),
        "results": results,
    }


@router.get("/organizations/{org_id}", response_model=OrganizationResponse, tags=["Organizations"])
async def get_organization(
    org_id: int,
    db: Session = Depends(get_db_session),
    ctx: OrganizationAccessContext = Depends(get_access_context),
):
    """פרטי ארגון — **חייב להיות הארגון הפעיל**.

    לשעבר הושווה מול `current_user.organization_id`, ולכן אדם עם ארגון
    בית A וחברות ב-B יכול היה לקרוא את A בזמן שההקשר הוא B. מזהה בנתיב
    שאינו תואם להקשר נכשל — הוא אינו מחליף אותו.
    """
    if org_id != ctx.organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied"
        )


    org = db.query(Organization).filter(Organization.id == org_id).first()
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found"
        )
    
    return OrganizationResponse.model_validate(org)


@router.patch("/organizations/{org_id}", response_model=OrganizationResponse, tags=["Organizations"])
async def update_organization(
    org_id: int,
    org_data: OrganizationUpdate,
    db: Session = Depends(get_db_session),
    ctx: OrganizationAccessContext = Depends(get_access_context),
    current_user: User = Depends(get_organization_admin),
):
    """עדכון ארגון"""
    _require_selected_organization(ctx, org_id)
    
    org = db.query(Organization).filter(Organization.id == org_id).first()
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found"
        )
    
    update_data = org_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(org, field, value)
    
    db.commit()
    db.refresh(org)
    
    audit_log = AuditLog(
        user_id=current_user.id,
        organization_id=org_id,
        action="UPDATE",
        entity_type="Organization",
        entity_id=org_id,
        details=update_data
    )
    db.add(audit_log)
    db.commit()
    
    return OrganizationResponse.model_validate(org)


@router.delete("/organizations/{org_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["Organizations"])
async def delete_organization(
    org_id: int,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_super_admin)
):
    """מחיקת ארגון (רק super admin)"""
    org = db.query(Organization).filter(Organization.id == org_id).first()
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found"
        )
    
    audit_log = AuditLog(
        user_id=current_user.id,
        action="DELETE",
        entity_type="Organization",
        entity_id=org_id,
        details={"name": org.name}
    )
    db.add(audit_log)
    
    db.delete(org)
    db.commit()


# ==================== Users Management ====================


class MembershipInviteRequest(BaseModel):
    email: str
    role: UserRole = UserRole.USER
    expires_at: Optional[datetime] = None

    model_config = {"extra": "forbid"}


class MembershipAcceptRequest(BaseModel):
    organization_id: int

    model_config = {"extra": "forbid"}


def _membership_payload(membership: OrganizationMembership) -> dict[str, Any]:
    return {
        "id": membership.id,
        "organization_id": membership.organization_id,
        "user_id": membership.user_id,
        "role": membership.role,
        "status": membership.status,
        "expires_at": membership.expires_at,
        "verified_at": membership.verified_at,
    }


@router.post("/memberships/invite", status_code=201, tags=["Users"])
async def invite_existing_identity(
    body: MembershipInviteRequest,
    db: Session = Depends(get_db_session),
    ctx: OrganizationAccessContext = Depends(get_access_context),
    current_user: User = Depends(require_admin),
):
    if body.role == UserRole.SUPER_ADMIN:
        raise HTTPException(status_code=403, detail="SUPER_ADMIN is not a membership role")
    target = db.query(User).filter(User.email == body.email).first()
    if target is None:
        raise HTTPException(status_code=404, detail="User identity not found")
    if not target.is_active:
        raise HTTPException(status_code=409, detail="User identity is disabled")
    from ...services import membership_service
    try:
        membership = membership_service.invite_checked(
            db, organization_id=ctx.organization_id, user_id=target.id,
            role=body.role, acting_user_id=current_user.id,
            expires_at=body.expires_at,
            acting_is_platform_super_admin=ctx.is_super_admin,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.commit()
    db.refresh(membership)
    return _membership_payload(membership)


@router.post("/memberships/accept", tags=["Users"])
async def accept_membership_invitation(
    body: MembershipAcceptRequest,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
):
    """קבלת הזמנה אינה תלויה ב-get_access_context: לפני הקבלה החברות
    עדיין invited ולכן, בצדק, אינה יכולה לבנות הקשר פעיל."""
    from ...services import membership_service
    try:
        membership = membership_service.accept(
            db, organization_id=body.organization_id, user_id=current_user.id,
            acting_user_id=current_user.id,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.commit()
    db.refresh(membership)
    return _membership_payload(membership)


@router.post("/memberships/{user_id}/suspend", tags=["Users"])
async def suspend_organization_membership(
    user_id: int,
    db: Session = Depends(get_db_session),
    ctx: OrganizationAccessContext = Depends(get_access_context),
    current_user: User = Depends(require_admin),
):
    from ...services import membership_service
    try:
        membership = membership_service.suspend_checked(
            db, organization_id=ctx.organization_id, user_id=user_id,
            acting_user_id=current_user.id,
            acting_is_platform_super_admin=ctx.is_super_admin,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.commit()
    db.refresh(membership)
    return _membership_payload(membership)


@router.post("/memberships/{user_id}/revoke", tags=["Users"])
async def revoke_organization_membership(
    user_id: int,
    db: Session = Depends(get_db_session),
    ctx: OrganizationAccessContext = Depends(get_access_context),
    current_user: User = Depends(require_admin),
):
    from ...services import membership_service
    try:
        membership = membership_service.revoke_checked(
            db, organization_id=ctx.organization_id, user_id=user_id,
            acting_user_id=current_user.id,
            acting_is_platform_super_admin=ctx.is_super_admin,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.commit()
    db.refresh(membership)
    return _membership_payload(membership)

@router.get("/users", tags=["Users"])
async def list_users(
    organization_id: int = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db_session),
    ctx: OrganizationAccessContext = Depends(get_access_context),
    _admin: User = Depends(get_organization_admin),
):
    """רשימת משתמשים **בארגון הפעיל**.

    לשעבר סינן לפי `current_user.organization_id` — ארגון הבית. אדם עם
    ארגון בית A וחברות ב-B היה מקבל את רשימת המשתמשים של A בזמן שכל
    שאר המסך מציג את B.
    """
    _require_selected_organization(ctx, organization_id)
    rows = (
        db.query(User, OrganizationMembership)
        .join(OrganizationMembership, OrganizationMembership.user_id == User.id)
        .filter(OrganizationMembership.organization_id == ctx.organization_id)
        .order_by(User.id.asc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    result = []
    for user, membership in rows:
        payload = UserResponse.model_validate(user).model_dump()
        payload.update({
            "role": membership.role,
            "organization_id": ctx.organization_id,
            "membership_status": membership.status,
            "membership_expires_at": membership.expires_at,
        })
        result.append(payload)
    return result


@router.get("/users/{user_id}", response_model=UserResponse, tags=["Users"])
async def get_user(
    user_id: int,
    db: Session = Depends(get_db_session),
    ctx: OrganizationAccessContext = Depends(get_access_context),
    _admin: User = Depends(get_organization_admin),
):
    """קבלת פרטי משתמש"""
    row = (
        db.query(User, OrganizationMembership)
        .join(OrganizationMembership, OrganizationMembership.user_id == User.id)
        .filter(
            User.id == user_id,
            OrganizationMembership.organization_id == ctx.organization_id,
        )
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="User not found")
    user, membership = row
    payload = UserResponse.model_validate(user).model_dump()
    payload.update({
        "role": membership.role,
        "organization_id": ctx.organization_id,
        "membership_status": membership.status,
        "membership_expires_at": membership.expires_at,
    })
    return payload


# ==================== SUMIT Companies Management ====================

@router.post("/sumit/companies", response_model=CompanyResponse, tags=["SUMIT"])
async def create_sumit_company(
    company: CompanyRequest,
    sumit: SumitIntegration = Depends(get_sumit_integration),
    current_user: User = Depends(get_organization_admin)
):
    """Create new SUMIT company"""
    async with sumit:
        return await sumit.create_company(company)


@router.get("/sumit/companies/{company_id}", response_model=CompanyResponse, tags=["SUMIT"])
async def get_sumit_company(
    company_id: str,
    sumit: SumitIntegration = Depends(get_sumit_integration),
    current_user: User = Depends(get_current_user)
):
    """Get SUMIT company details"""
    async with sumit:
        return await sumit.get_company_details(company_id)


# ==================== Audit Logs ====================

@router.get("/audit-logs", tags=["Audit"])
async def get_audit_logs(
    organization_id: int = None,
    user_id: int = None,
    action: str = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db_session),
    ctx: OrganizationAccessContext = Depends(get_access_context),
    _admin: User = Depends(get_organization_admin),
):
    """לוגים למעקב **בארגון הפעיל**.

    audit הוא בדיוק המקום שבו הבאג הזה הרסני: מי שבודק מה קרה בתיק B
    היה רואה פעולות מתיק A, ומסיק מסקנות על התיק הלא-נכון.
    """
    _require_selected_organization(ctx, organization_id)
    query = db.query(AuditLog).filter(
        AuditLog.organization_id == ctx.organization_id,
    )


    if user_id:
        query = query.filter(AuditLog.user_id == user_id)
    if action:
        query = query.filter(AuditLog.action == action)
    
    logs = query.order_by(AuditLog.created_at.desc()).offset(skip).limit(limit).all()
    
    return [
        {
            "id": log.id,
            "user_id": log.user_id,
            "organization_id": log.organization_id,
            "action": log.action,
            "entity_type": log.entity_type,
            "entity_id": log.entity_id,
            "details": log.details,
            "created_at": log.created_at
        }
        for log in logs
    ]


# ==================== Companies ====================

@router.post("/companies", response_model=CompanyResponse)
async def create_company(
    company: CompanyRequest,
    sumit: SumitIntegration = Depends(get_sumit_integration),
    current_user: dict = Depends(require_admin)
):
    """Create new company"""
    async with sumit:
        return await sumit.create_company(company)


@router.get("/companies/{company_id}", response_model=CompanyResponse)
async def get_company(
    company_id: str,
    sumit: SumitIntegration = Depends(get_sumit_integration),
    current_user: dict = Depends(get_current_user)
):
    """Get company details"""
    async with sumit:
        return await sumit.get_company_details(company_id)


@router.put("/companies/{company_id}", response_model=CompanyResponse)
async def update_company(
    company_id: str,
    company: CompanyRequest,
    sumit: SumitIntegration = Depends(get_sumit_integration),
    current_user: dict = Depends(require_admin)
):
    """Update company details"""
    async with sumit:
        return await sumit.update_company(company_id, company)


# ==================== Users ====================

@router.post("/sumit-users")
async def create_sumit_user(
    user: UserRequest,
    sumit: SumitIntegration = Depends(get_sumit_integration),
    current_user: dict = Depends(require_admin)
):
    """Create new user in SUMIT (external accounting system)"""
    async with sumit:
        return await sumit.create_user(user)


@router.post("/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED, tags=["Users"])
async def create_app_user(
    user_data: UserCreate,
    db: Session = Depends(get_db_session),
    ctx: OrganizationAccessContext = Depends(get_access_context),
    current_user: User = Depends(require_admin),
):
    """יצירת חשבון משתמש + **הזמנה** לארגון הפעיל.

    ההיקף נגזר מההקשר, לא מ-`users.organization_id`: אדם עם ארגון בית A
    שפועל בהקשר B היה יוצר משתמשים ב-A.
    """
    # organization_id is required — admin must specify which org to provision into
    if user_data.organization_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="organization_id is required",
        )

    _require_selected_organization(ctx, user_data.organization_id)
    if user_data.role == UserRole.SUPER_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="SUPER_ADMIN is a platform role, not an organization membership",
        )

    # Enforce minimum password length
    if len(user_data.password) < 8:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Password must be at least 8 characters",
        )

    # Email uniqueness
    existing = db.query(User).filter(User.email == user_data.email).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )

    new_user = User(
        email=user_data.email,
        password_hash=get_password_hash(user_data.password),
        full_name=user_data.full_name,
        phone=user_data.phone,
        # התפקיד הארגוני נשמר רק בחברות. השדה הגלובלי נשאר תפקיד בסיס
        # כדי שנתיב legacy שלא חובר עדיין לא יעניק בטעות סמכות רחבה.
        role=UserRole.USER,
        organization_id=ctx.organization_id,
        is_active=True,
    )
    db.add(new_user)
    db.flush()

    # הזמנה, לא הענקה. `invited` אינו גישה — האדם עדיין לא קיבל.
    # הענקת `active` כאן הייתה הופכת כל הקלדת מייל שגויה לגישה לכספים
    # של לקוח. `flush` ולא `commit`: כשל בהזמנה מגלגל גם את המשתמש,
    # אחרת נשאר חשבון התחברות בלי שום חברות — משתמש שאיש אינו יכול לנהל.
    #
    # SUPER_ADMIN הוא תפקיד פלטפורמה ואינו מתקבל כלל בנתיב הארגוני הזה.
    from ...services import membership_service as _membership_service

    _membership_service.invite_checked(
        db,
        organization_id=ctx.organization_id,
        user_id=new_user.id,
        role=user_data.role,
        acting_user_id=current_user.id,
        acting_is_platform_super_admin=ctx.is_super_admin,
    )

    db.commit()
    db.refresh(new_user)
    payload = UserResponse.model_validate(new_user)
    return payload.model_copy(update={
        "role": user_data.role,
        "organization_id": ctx.organization_id,
    })


@router.patch("/users/{user_id}", response_model=UserResponse, tags=["Users"])
async def update_app_user(
    user_id: int,
    user_update: UserUpdate,
    db: Session = Depends(get_db_session),
    ctx: OrganizationAccessContext = Depends(get_access_context),
    current_user: User = Depends(require_admin),
):
    """עדכון משתמש. **שינוי תפקיד נוגע בחברות בארגון הפעיל בלבד.**"""
    row = (
        db.query(User, OrganizationMembership)
        .join(OrganizationMembership, OrganizationMembership.user_id == User.id)
        .filter(
            User.id == user_id,
            OrganizationMembership.organization_id == ctx.organization_id,
        )
        .first()
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    user, membership = row
    if user.role == UserRole.SUPER_ADMIN or user_update.role == UserRole.SUPER_ADMIN:
        raise HTTPException(
            status_code=403,
            detail="Platform roles cannot be changed from an organization route",
        )

    # Self-guards (checked BEFORE last-admin protection)
    if user_update.is_active is False and current_user.id == user.id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Cannot deactivate yourself",
        )
    if user_update.role is not None and current_user.id == user.id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Cannot change your own role",
        )

    active_signing_authority = db.query(OrganizationSigningAuthority).filter(
        OrganizationSigningAuthority.organization_id == ctx.organization_id,
        OrganizationSigningAuthority.user_id == user.id,
        OrganizationSigningAuthority.is_active.is_(True),
    ).first()
    if active_signing_authority is not None and (
        user_update.is_active is False
        or user_update.role == UserRole.VIEWER
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "User has an active signing authority; an organization owner "
                "must revoke it before deactivation or viewer demotion"
            ),
        )

    # פרטי identity הם גלובליים ומשותפים לכל הארגונים. נתיב ארגוני אינו
    # משנה אותם בשם תיק אחד.
    if any(value is not None for value in (
        user_update.email, user_update.full_name, user_update.phone,
    )):
        raise HTTPException(
            status_code=403,
            detail="Global identity fields require a platform identity endpoint",
        )

    from ...services import membership_service as _membership_service

    def _membership_error(exc: Exception) -> HTTPException:
        return HTTPException(
            status_code=403 if isinstance(exc, PermissionError) else 409,
            detail=str(exc),
        )

    if user_update.role is not None:
        try:
            _membership_service.grant_checked(
                db,
                organization_id=ctx.organization_id,
                user_id=user.id,
                role=user_update.role,
                acting_user_id=current_user.id,
                status=membership.status,
                expires_at=membership.expires_at,
                acting_is_platform_super_admin=ctx.is_super_admin,
            )
        except (ValueError, PermissionError) as exc:
            raise _membership_error(exc) from exc
    if user_update.is_active is not None:
        try:
            if user_update.is_active:
                _membership_service.grant_checked(
                    db, organization_id=ctx.organization_id, user_id=user.id,
                    role=user_update.role or membership.role,
                    acting_user_id=current_user.id,
                    status=_membership_service.ACTIVE,
                    expires_at=membership.expires_at,
                    acting_is_platform_super_admin=ctx.is_super_admin,
                )
            else:
                _membership_service.suspend_checked(
                    db, organization_id=ctx.organization_id, user_id=user.id,
                    acting_user_id=current_user.id,
                    acting_is_platform_super_admin=ctx.is_super_admin,
                )
        except (ValueError, PermissionError) as exc:
            raise _membership_error(exc) from exc

    db.commit()
    db.refresh(user)

    # התשובה מדווחת את התפקיד **בארגון הפעיל**. `User.role` הוא שדה
    # פלטפורמה, ודיווח שלו כאן היה מציג למנהל תפקיד שאינו זה שהוא זה
    # עתה שינה.
    from ...services import membership_service as _ms_resp

    payload = UserResponse.model_validate(user)
    effective = _ms_resp.role_in(db, user.id, ctx.organization_id)
    if effective is None:
        refreshed_membership = next(
            (m for m in _ms_resp.memberships_for(db, user.id)
             if m.organization_id == ctx.organization_id),
            None,
        )
        effective = refreshed_membership.role if refreshed_membership else None
    if effective is not None:
        payload = payload.model_copy(update={"role": effective})
    return payload


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["Users"])
async def delete_app_user(
    user_id: int,
    db: Session = Depends(get_db_session),
    ctx: OrganizationAccessContext = Depends(get_access_context),
    current_user: User = Depends(require_admin),
):
    """ביטול חברות בארגון הפעיל; אינו משבית את ה-identity הגלובלי."""
    row = (
        db.query(User, OrganizationMembership)
        .join(OrganizationMembership, OrganizationMembership.user_id == User.id)
        .filter(
            User.id == user_id,
            OrganizationMembership.organization_id == ctx.organization_id,
        )
        .first()
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    user, _membership = row
    if user.role == UserRole.SUPER_ADMIN:
        raise HTTPException(status_code=403, detail="Cannot modify a platform super admin")

    # Self-guard (checked BEFORE last-admin)
    if current_user.id == user.id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Cannot delete yourself",
        )

    if db.query(OrganizationSigningAuthority).filter(
        OrganizationSigningAuthority.organization_id == ctx.organization_id,
        OrganizationSigningAuthority.user_id == user.id,
        OrganizationSigningAuthority.is_active.is_(True),
    ).first() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "User has an active signing authority; an organization owner "
                "must revoke it before deletion"
            ),
        )

    from ...services import membership_service as _membership_service
    try:
        _membership_service.revoke_checked(
            db, organization_id=ctx.organization_id, user_id=user.id,
            acting_user_id=current_user.id,
            acting_is_platform_super_admin=ctx.is_super_admin,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.commit()


@router.post("/users/{user_id}/permissions")
async def set_user_permissions(
    user_id: str,
    permissions: List[UserPermission],
    sumit: SumitIntegration = Depends(get_sumit_integration),
    current_user: dict = Depends(require_admin)
):
    """Set user permissions"""
    async with sumit:
        return await sumit.set_user_permissions(user_id, permissions)


@router.post("/users/{user_id}/permissions/remove")
async def remove_user_permissions(
    user_id: str,
    permission_names: List[str],
    sumit: SumitIntegration = Depends(get_sumit_integration),
    current_user: dict = Depends(require_admin)
):
    """Remove user permissions"""
    async with sumit:
        return await sumit.remove_user_permissions(user_id, permission_names)


@router.post("/users/login-redirect")
async def user_login_redirect(
    user_id: str = Query(...),
    return_url: Optional[str] = Query(None),
    sumit: SumitIntegration = Depends(get_sumit_integration),
    current_user: dict = Depends(require_admin)
):
    """Get user login redirect URL"""
    async with sumit:
        redirect_url = await sumit.user_login_redirect(user_id, return_url)
        return {"redirect_url": redirect_url}


# ==================== Webhooks ====================

@router.post("/webhooks/subscribe")
async def subscribe_webhook(
    trigger_type: str = Query(...),
    webhook_url: str = Query(...),
    sumit: SumitIntegration = Depends(get_sumit_integration),
    current_user: dict = Depends(require_admin)
):
    """Subscribe to webhook trigger"""
    async with sumit:
        return await sumit.subscribe_trigger(trigger_type, webhook_url)


@router.post("/webhooks/{subscription_id}/unsubscribe")
async def unsubscribe_webhook(
    subscription_id: str,
    sumit: SumitIntegration = Depends(get_sumit_integration),
    current_user: dict = Depends(require_admin)
):
    """Unsubscribe from webhook trigger"""
    async with sumit:
        return await sumit.unsubscribe_trigger(subscription_id)


# ==================== Stock ====================

@router.get("/stock", response_model=List[StockItemResponse])
async def list_stock(
    sumit: SumitIntegration = Depends(get_sumit_integration),
    current_user: dict = Depends(get_current_user)
):
    """List stock items"""
    async with sumit:
        return await sumit.list_stock()


# ==================== Applications ====================

@router.post("/applications/install")
async def install_applications(
    application_ids: List[str],
    sumit: SumitIntegration = Depends(get_sumit_integration),
    current_user: dict = Depends(require_admin)
):
    """Install applications"""
    async with sumit:
        return await sumit.install_applications(application_ids)


# ==================== System ====================

@router.get("/quotas")
async def list_quotas(
    sumit: SumitIntegration = Depends(get_sumit_integration),
    current_user: dict = Depends(require_admin)
):
    """List API quotas and usage"""
    async with sumit:
        return await sumit.list_quotas()


@router.get("/test-connection")
async def test_connection(
    sumit: SumitIntegration = Depends(get_sumit_integration),
    current_user: dict = Depends(get_current_user)
):
    """Test SUMIT API connection"""
    async with sumit:
        is_connected = await sumit.test_connection()
        return {
            "connected": is_connected,
            "message": "Connection successful" if is_connected else "Connection failed"
        }


# ==================== Moshko: ownership review (Package H) ====================
# The sole "super admin" is the business owner — there is no separate "org
# admin" role that self-declares ownership. Identification is automatic by
# default (account_ownership.ownership_status); this queue exists ONLY for
# the cases where it doesn't converge (honest-null).

class OwnershipResolveRequest(BaseModel):
    account_id: int
    tax_id: Optional[str] = None


class MoshkoMemoryCreateRequest(BaseModel):
    organization_id: int
    user_id: Optional[int] = None
    content: str
    category: str = "business_fact"


class MoshkoMemoryUpdateRequest(BaseModel):
    content: Optional[str] = None
    category: Optional[str] = None
    approved: Optional[bool] = None


class MoshkoFeedbackReviewRequest(BaseModel):
    correction: Optional[str] = None
    status: Optional[str] = None
    promote_to_memory: bool = False


_MOSHKO_MEMORY_CATEGORIES = {
    "preference", "business_fact", "correction", "convention",
}
_MOSHKO_MEMORY_SOURCES = {"conversation", "admin", "inferred"}


def _memory_payload(row: MoshkoMemory) -> dict[str, Any]:
    return {
        "id": row.id,
        "organization_id": row.organization_id,
        "user_id": row.user_id,
        "scope": "org" if row.user_id is None else "user",
        "content": row.content,
        "category": row.category,
        "source": row.source,
        "approved_at": row.approved_at,
        "approved_by": row.approved_by,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "last_used_at": row.last_used_at,
    }


def _memory_audit_snapshot(row: MoshkoMemory) -> dict[str, Any]:
    payload = _memory_payload(row)
    for field in ("approved_at", "created_at", "updated_at", "last_used_at"):
        value = payload[field]
        payload[field] = value.isoformat() if value is not None else None
    return payload


def _memory_row_for_actor(
    db: Session, memory_id: int, ctx: OrganizationAccessContext,
) -> MoshkoMemory:
    query = db.query(MoshkoMemory).filter(
        MoshkoMemory.id == memory_id,
        MoshkoMemory.organization_id == ctx.organization_id,
    )
    if not ctx.is_super_admin:
        query = query.filter(
            or_(MoshkoMemory.user_id.is_(None), MoshkoMemory.user_id == ctx.user.id),
        )
    row = query.first()
    if row is None:
        raise HTTPException(status_code=404, detail="Memory not found")
    return row


def _validate_memory_category(category: str) -> str:
    if category not in _MOSHKO_MEMORY_CATEGORIES:
        raise HTTPException(status_code=400, detail="Invalid memory category")
    return category


def _validate_memory_capacity(
    db: Session,
    *,
    organization_id: int,
    user_id: Optional[int],
    content: str,
    exclude_id: Optional[int] = None,
) -> None:
    from ...services.moshko_memory import ORG_MEMORY_CHAR_CAP, USER_MEMORY_CHAR_CAP

    query = db.query(MoshkoMemory).filter(MoshkoMemory.organization_id == organization_id)
    if user_id is None:
        query = query.filter(MoshkoMemory.user_id.is_(None))
        cap = ORG_MEMORY_CHAR_CAP
    else:
        query = query.filter(MoshkoMemory.user_id == user_id)
        cap = USER_MEMORY_CHAR_CAP
    if exclude_id is not None:
        query = query.filter(MoshkoMemory.id != exclude_id)
    used = sum(len(row.content) for row in query.all())
    if used + len(content) > cap:
        raise HTTPException(
            status_code=409,
            detail="Memory character cap reached; shorten or delete another memory first",
        )


def _moshko_channel(session_id: str) -> str:
    if session_id.startswith("wa-"):
        return "whatsapp"
    if session_id.startswith("tg-"):
        return "telegram"
    return "web"


def _apply_moshko_filters(
    query,
    model,
    *,
    organization_id: Optional[int],
    user_id: Optional[int],
    channel: Optional[str],
    date_from: Optional[datetime],
    date_to: Optional[datetime],
):
    if organization_id is not None:
        query = query.filter(model.organization_id == organization_id)
    if user_id is not None:
        query = query.filter(model.user_id == user_id)
    if channel:
        prefix = {"whatsapp": "wa-", "telegram": "tg-"}.get(channel)
        if prefix:
            query = query.filter(model.session_id.like(f"{prefix}%"))
        elif channel == "web":
            query = query.filter(
                ~model.session_id.like("wa-%"), ~model.session_id.like("tg-%")
            )
        else:
            raise HTTPException(status_code=400, detail="channel must be web, telegram or whatsapp")
    if date_from is not None:
        query = query.filter(model.created_at >= date_from)
    if date_to is not None:
        query = query.filter(model.created_at <= date_to)
    return query


@router.get("/moshko/conversations", tags=["Moshko"])
async def get_moshko_conversations(
    organization_id: Optional[int] = None,
    user_id: Optional[int] = None,
    channel: Optional[str] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_super_admin),
):
    query = db.query(
        ChatMessage.organization_id,
        ChatMessage.user_id,
        ChatMessage.session_id,
        func.min(ChatMessage.created_at).label("started_at"),
        func.max(ChatMessage.created_at).label("last_message_at"),
        func.count(ChatMessage.id).label("message_count"),
    )
    # moshko_regression.py runs training cases under session ids
    # `regression-{gap_id}-{hex}` — synthetic traffic, not real
    # conversations. Excluded ONLY from this listing (not from
    # tool-calls/usage aggregates, and not from the single-session
    # transcript lookup below) so the regression sessions stay queryable by
    # anyone who already knows the session_id, but don't pollute the human
    # conversations view.
    query = query.filter(~ChatMessage.session_id.like("regression-%"))
    query = _apply_moshko_filters(
        query, ChatMessage, organization_id=organization_id, user_id=user_id,
        channel=channel, date_from=date_from, date_to=date_to,
    ).group_by(ChatMessage.organization_id, ChatMessage.user_id, ChatMessage.session_id)
    total = query.count()
    rows = query.order_by(func.max(ChatMessage.created_at).desc()).offset(skip).limit(limit).all()
    return {
        "items": [
            {
                "organization_id": row.organization_id,
                "user_id": row.user_id,
                "session_id": row.session_id,
                "channel": _moshko_channel(row.session_id),
                "started_at": row.started_at,
                "last_message_at": row.last_message_at,
                "message_count": row.message_count,
            }
            for row in rows
        ],
        "total": total,
        "skip": skip,
        "limit": limit,
    }


@router.get("/moshko/conversations/{session_id}", tags=["Moshko"])
async def get_moshko_conversation_transcript(
    session_id: str,
    organization_id: Optional[int] = None,
    user_id: Optional[int] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=500),
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_super_admin),
):
    base = db.query(ChatMessage).filter(ChatMessage.session_id == session_id)
    if organization_id is not None:
        base = base.filter(ChatMessage.organization_id == organization_id)
    if user_id is not None:
        base = base.filter(ChatMessage.user_id == user_id)
    scopes = base.with_entities(
        ChatMessage.organization_id, ChatMessage.user_id
    ).distinct().all()
    if not scopes:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if len(scopes) > 1:
        raise HTTPException(
            status_code=409,
            detail="session_id is ambiguous; provide organization_id and user_id",
        )
    total = base.count()
    rows = base.order_by(ChatMessage.id.asc()).offset(skip).limit(limit).all()
    return {
        "organization_id": scopes[0].organization_id,
        "user_id": scopes[0].user_id,
        "session_id": session_id,
        "channel": _moshko_channel(session_id),
        "messages": [
            {
                "id": row.id,
                "role": row.role,
                "content": row.content,
                "pending_action": row.pending_action,
                "executed": row.executed,
                "created_at": row.created_at,
            }
            for row in rows
        ],
        "total": total,
        "skip": skip,
        "limit": limit,
    }


@router.get("/moshko/tool-calls", tags=["Moshko"])
async def get_moshko_tool_calls(
    organization_id: Optional[int] = None,
    user_id: Optional[int] = None,
    channel: Optional[str] = None,
    target_system: Optional[str] = None,
    succeeded: Optional[bool] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_super_admin),
):
    query = _apply_moshko_filters(
        db.query(MoshkoToolCall), MoshkoToolCall,
        organization_id=organization_id, user_id=user_id, channel=channel,
        date_from=date_from, date_to=date_to,
    )
    if target_system is not None:
        if target_system not in {"sumit", "open_finance", "rezef_db", "local"}:
            raise HTTPException(status_code=400, detail="Invalid target_system")
        query = query.filter(MoshkoToolCall.target_system == target_system)
    if succeeded is not None:
        query = query.filter(MoshkoToolCall.succeeded.is_(succeeded))
    total = query.count()
    rows = query.order_by(MoshkoToolCall.created_at.desc()).offset(skip).limit(limit).all()
    return {
        "items": [
            {
                "id": row.id,
                "organization_id": row.organization_id,
                "user_id": row.user_id,
                "session_id": row.session_id,
                "channel": _moshko_channel(row.session_id),
                "message_id": row.message_id,
                "tool_name": row.tool_name,
                "target_system": row.target_system,
                "arguments": row.arguments,
                "succeeded": row.succeeded,
                "error": row.error,
                "duration_ms": row.duration_ms,
                "result_size_bytes": row.result_size_bytes,
                "created_at": row.created_at,
            }
            for row in rows
        ],
        "total": total,
        "skip": skip,
        "limit": limit,
    }


def _usage_aggregate_payload(row, *, key_name: Optional[str] = None) -> dict:
    request_count = int(row.request_count or 0)
    priced_count = int(row.priced_count or 0)
    payload = {
        "requests": request_count,
        "input_tokens": int(row.input_tokens or 0),
        "output_tokens": int(row.output_tokens or 0),
        "cache_read_input_tokens": int(row.cache_read_input_tokens or 0),
        "cache_creation_input_tokens": int(row.cache_creation_input_tokens or 0),
        # A partial sum is deceptive. If any request in the bucket has an
        # unknown price, the bucket cost is honestly unknown too.
        "cost_usd": float(row.cost_usd) if request_count == priced_count and row.cost_usd is not None else None,
    }
    if key_name is not None:
        payload[key_name] = row.group_key
    return payload


def _usage_columns():
    return (
        func.count(LLMUsage.id).label("request_count"),
        func.count(LLMUsage.cost_usd).label("priced_count"),
        func.sum(LLMUsage.input_tokens).label("input_tokens"),
        func.sum(LLMUsage.output_tokens).label("output_tokens"),
        func.sum(LLMUsage.cache_read_input_tokens).label("cache_read_input_tokens"),
        func.sum(LLMUsage.cache_creation_input_tokens).label("cache_creation_input_tokens"),
        func.sum(LLMUsage.cost_usd).label("cost_usd"),
    )


@router.get("/moshko/usage", tags=["Moshko"])
async def get_moshko_usage(
    organization_id: Optional[int] = None,
    user_id: Optional[int] = None,
    channel: Optional[str] = None,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    purpose: Optional[str] = None,
    group_by: str = Query("day", pattern="^(day|organization|model)$"),
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_super_admin),
):
    def filtered(query):
        query = _apply_moshko_filters(
            query, LLMUsage, organization_id=organization_id, user_id=user_id,
            channel=channel, date_from=date_from, date_to=date_to,
        )
        if provider is not None:
            query = query.filter(LLMUsage.provider == provider)
        if model is not None:
            query = query.filter(LLMUsage.model == model)
        if purpose is not None:
            query = query.filter(LLMUsage.purpose == purpose)
        return query

    summary_row = filtered(db.query(*_usage_columns())).one()
    group_column, key_name = {
        "day": (func.date(LLMUsage.created_at), "day"),
        "organization": (LLMUsage.organization_id, "organization_id"),
        "model": (LLMUsage.model, "model"),
    }[group_by]
    grouped = filtered(db.query(group_column.label("group_key"), *_usage_columns())).group_by(group_column)
    total = grouped.count()
    rows = grouped.order_by(group_column.desc()).offset(skip).limit(limit).all()
    return {
        "summary": _usage_aggregate_payload(summary_row),
        "group_by": group_by,
        "groups": [_usage_aggregate_payload(row, key_name=key_name) for row in rows],
        "total": total,
        "skip": skip,
        "limit": limit,
    }


@router.get("/moshko/focus-metrics", tags=["Moshko"])
async def get_moshko_focus_metrics(
    organization_id: Optional[int] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_super_admin),
):
    """S9 (ספרינט זהות-מושקו, 24-25/08/2026) — מדד המיקוד: אחוז
    תשובות-ויתור, gaps ל-100 תורים, אחוז regression-pass. קריאה בלבד.
    בייסליין לפני S5/S6, כדי שיהיה 'לפני' אמיתי להשוואה מול 'אחרי'."""
    from ...services.moshko_focus_metrics import compute_focus_metrics

    return compute_focus_metrics(
        db, organization_id=organization_id, since=date_from, until=date_to,
    )


@router.get("/moshko/pilot-summary", tags=["Moshko"])
async def get_moshko_pilot_summary(
    channel: str = Query("whatsapp", pattern="^(whatsapp|telegram)$"),
    organization_id: Optional[int] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_super_admin),
):
    """S4 (ספרינט זהות-מושקו, 25/08/2026) — לוח פיילוט read-only.
    קריטריון ההצלחה: שאילתה אחת עונה 'כמה עלה השבוע ומה נשבר'."""
    from ...services.moshko_pilot_summary import compute_pilot_summary

    return compute_pilot_summary(
        db, channel=channel, organization_id=organization_id,
        since=date_from, until=date_to,
    )


def _feedback_admin_payload(row: MoshkoFeedback) -> dict[str, Any]:
    return {
        "id": row.id,
        "organization_id": row.organization_id,
        "user_id": row.user_id,
        "message_id": row.message_id,
        "session_id": row.session_id,
        "channel": row.channel,
        "category": row.category,
        "comment": row.comment,
        "question": row.question,
        "answer": row.answer,
        "status": row.status,
        "correction": row.correction,
        "reviewed_by": row.reviewed_by,
        "reviewed_at": row.reviewed_at,
        "promoted_memory_id": row.promoted_memory_id,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


@router.get("/moshko/feedback", tags=["Moshko"])
async def list_moshko_feedback(
    organization_id: Optional[int] = None,
    user_id: Optional[int] = None,
    category: Optional[str] = None,
    feedback_status: Optional[str] = Query(None, alias="status"),
    channel: Optional[str] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db_session),
    _current_user: User = Depends(get_super_admin),
):
    """Platform-owner quality queue; conversation content is never public."""
    query = db.query(MoshkoFeedback)
    if organization_id is not None:
        query = query.filter(MoshkoFeedback.organization_id == organization_id)
    if user_id is not None:
        query = query.filter(MoshkoFeedback.user_id == user_id)
    if category is not None:
        if category not in {"helpful", "inaccurate", "unknown", "unsafe"}:
            raise HTTPException(400, "Invalid feedback category")
        query = query.filter(MoshkoFeedback.category == category)
    if feedback_status is not None:
        if feedback_status not in {"open", "reviewed", "resolved", "dismissed"}:
            raise HTTPException(400, "Invalid feedback status")
        query = query.filter(MoshkoFeedback.status == feedback_status)
    if channel is not None:
        if channel not in {"web", "whatsapp", "telegram"}:
            raise HTTPException(400, "Invalid feedback channel")
        query = query.filter(MoshkoFeedback.channel == channel)
    total = query.count()
    rows = query.order_by(
        MoshkoFeedback.created_at.desc(), MoshkoFeedback.id.desc(),
    ).offset(skip).limit(limit).all()
    return {
        "items": [_feedback_admin_payload(row) for row in rows],
        "total": total,
        "skip": skip,
        "limit": limit,
    }


@router.patch("/moshko/feedback/{feedback_id}", tags=["Moshko"])
async def review_moshko_feedback(
    feedback_id: int,
    body: MoshkoFeedbackReviewRequest,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_super_admin),
):
    row = db.query(MoshkoFeedback).filter(MoshkoFeedback.id == feedback_id).first()
    if row is None:
        raise HTTPException(404, "Feedback not found")
    if body.status is not None and body.status not in {
        "open", "reviewed", "resolved", "dismissed",
    }:
        raise HTTPException(400, "Invalid feedback status")
    correction = body.correction.strip()[:8000] if body.correction is not None else None
    if body.correction is not None and not correction:
        raise HTTPException(400, "Correction cannot be empty")
    if body.promote_to_memory and not (correction or row.correction):
        raise HTTPException(400, "A correction is required before promotion")

    old = _feedback_admin_payload(row)
    if correction is not None:
        row.correction = correction
    if body.status is not None:
        row.status = body.status
    elif correction is not None:
        row.status = "reviewed"
    now = datetime.utcnow()
    row.reviewed_by = current_user.id
    row.reviewed_at = now
    row.updated_at = now

    if body.promote_to_memory:
        content = row.correction or ""
        _validate_memory_capacity(
            db,
            organization_id=row.organization_id,
            user_id=None,
            content=content,
            exclude_id=row.promoted_memory_id,
        )
        memory = None
        if row.promoted_memory_id is not None:
            memory = db.query(MoshkoMemory).filter(
                MoshkoMemory.id == row.promoted_memory_id,
                MoshkoMemory.organization_id == row.organization_id,
            ).first()
        memory_old = _memory_audit_snapshot(memory) if memory is not None else None
        if memory is None:
            memory = MoshkoMemory(
                organization_id=row.organization_id,
                user_id=None,
                content=content,
                category="correction",
                source="admin",
                approved_at=now,
                approved_by=current_user.id,
                created_at=now,
                updated_at=now,
            )
            db.add(memory)
            db.flush()
            row.promoted_memory_id = memory.id
        else:
            memory.content = content
            memory.category = "correction"
            memory.source = "admin"
            memory.approved_at = now
            memory.approved_by = current_user.id
            memory.updated_at = now
            db.flush()
        row.status = "resolved"
        db.add(AuditLog(
            user_id=current_user.id,
            organization_id=row.organization_id,
            action="MOSHKO_MEMORY_CREATE" if memory_old is None else "MOSHKO_MEMORY_UPDATE",
            entity_type="MoshkoMemory",
            entity_id=memory.id,
            details={"old": memory_old, "new": _memory_audit_snapshot(memory),
                     "source_feedback_id": row.id},
        ))

    db.flush()
    new = _feedback_admin_payload(row)
    for payload in (old, new):
        for key in ("reviewed_at", "created_at", "updated_at"):
            if payload[key] is not None:
                payload[key] = payload[key].isoformat()
    db.add(AuditLog(
        user_id=current_user.id,
        organization_id=row.organization_id,
        action="MOSHKO_FEEDBACK_REVIEW",
        entity_type="MoshkoFeedback",
        entity_id=row.id,
        details={"old": old, "new": new},
    ))
    db.commit()
    db.refresh(row)
    return _feedback_admin_payload(row)


# ------------------------------------------------------------------ #
# W1.1 — תור הכישלונות/פערי-היכולת של מושקו (moshko_gaps)
# ------------------------------------------------------------------ #

def _gap_payload(row) -> dict:
    return {
        "id": row.id,
        "organization_id": row.organization_id,
        "user_id": row.user_id,
        "session_id": row.session_id,
        "message_id": row.message_id,
        "question": row.question,
        "answer": row.answer,
        "gap_kind": row.gap_kind,
        "tool_name": row.tool_name,
        "error": row.error,
        "status": row.status,
        "resolution": row.resolution,
        "promoted_memory_id": row.promoted_memory_id,
        "regression_status": row.regression_status,
        "regression_checked_at": (
            row.regression_checked_at.isoformat() if row.regression_checked_at else None
        ),
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


@router.get("/moshko/gaps", tags=["Moshko"])
async def list_moshko_gaps(
    organization_id: Optional[int] = None,
    status: Optional[str] = None,
    gap_kind: Optional[str] = None,
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db_session),
    _admin: User = Depends(get_super_admin),
):
    """תור הפערים: כלי שנפל / המודל ויתר / המשתמש דיגל. שורה = משהו
    שמושקו לא ידע לעשות והבעלים יכול לענות עליו."""
    from ...models import MoshkoGap

    q = db.query(MoshkoGap)
    if organization_id is not None:
        q = q.filter(MoshkoGap.organization_id == organization_id)
    if status is not None:
        q = q.filter(MoshkoGap.status == status)
    if gap_kind is not None:
        q = q.filter(MoshkoGap.gap_kind == gap_kind)
    rows = q.order_by(MoshkoGap.created_at.desc()).limit(limit).all()
    return {"gaps": [_gap_payload(r) for r in rows]}


class MoshkoGapReviewRequest(BaseModel):
    status: Optional[str] = None          # answered | dismissed | open
    resolution: Optional[str] = None
    promote_to_memory: bool = False


@router.patch("/moshko/gaps/{gap_id}", tags=["Moshko"])
async def review_moshko_gap(
    gap_id: int,
    body: MoshkoGapReviewRequest,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_super_admin),
):
    """מענה לפער: תשובה חופשית, ובאופציה קידום לזיכרון ארגוני מאושר —
    כך שהתשובה משפיעה על ההתנהגות מהשיחה הבאה (אותה לולאה כמו פידבק)."""
    from ...models import MoshkoGap

    row = db.query(MoshkoGap).filter(MoshkoGap.id == gap_id).first()
    if row is None:
        raise HTTPException(404, "Gap not found")
    if body.status is not None and body.status not in {"open", "answered", "dismissed"}:
        raise HTTPException(400, "Invalid gap status")
    resolution = body.resolution.strip()[:8000] if body.resolution is not None else None
    if body.promote_to_memory and not (resolution or row.resolution):
        raise HTTPException(400, "A resolution is required before promotion")

    now = datetime.utcnow()
    if resolution is not None:
        row.resolution = resolution
    if body.status is not None:
        row.status = body.status
    elif resolution is not None:
        row.status = "answered"
    row.resolved_by = current_user.id
    row.resolved_at = now
    row.updated_at = now

    if body.promote_to_memory:
        content = row.resolution or ""
        _validate_memory_capacity(
            db,
            organization_id=row.organization_id,
            user_id=None,
            content=content,
            exclude_id=row.promoted_memory_id,
        )
        memory = None
        if row.promoted_memory_id is not None:
            memory = db.query(MoshkoMemory).filter(
                MoshkoMemory.id == row.promoted_memory_id,
                MoshkoMemory.organization_id == row.organization_id,
            ).first()
        if memory is None:
            memory = MoshkoMemory(
                organization_id=row.organization_id,
                user_id=None,
                content=content,
                category="correction",
                source="admin",
                approved_at=now,
                approved_by=current_user.id,
                created_at=now,
                updated_at=now,
            )
            db.add(memory)
            db.flush()
            row.promoted_memory_id = memory.id
        else:
            memory.content = content
            memory.approved_at = now
            memory.approved_by = current_user.id
            memory.updated_at = now
            db.flush()
        db.add(AuditLog(
            user_id=current_user.id,
            organization_id=row.organization_id,
            action="MOSHKO_MEMORY_CREATE",
            entity_type="MoshkoMemory",
            entity_id=memory.id,
            details={"source_gap_id": row.id},
        ))

    db.add(AuditLog(
        user_id=current_user.id,
        organization_id=row.organization_id,
        action="MOSHKO_GAP_REVIEW",
        entity_type="MoshkoGap",
        entity_id=row.id,
        details={"status": row.status, "promoted": bool(body.promote_to_memory)},
    ))
    db.commit()
    db.refresh(row)
    return _gap_payload(row)


@router.post("/moshko/regression/run", tags=["Moshko"])
async def run_moshko_regression(
    organization_id: Optional[int] = None,
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_super_admin),
):
    """W1.5 — regression runner: מריץ מחדש כל שאלה שקודמה לזיכרון (gap עם
    promoted_memory_id) דרך AIChatService, ובודק (א) שהזיכרון שקודם אכן
    הוזרק להקשר, (ב) שהתשובה אינה תשובת-ויתור (הגלאי הקיים). מקרה שנכשל
    נפתח מחדש בתור הפערים לתיקון הבעלים — סיבוב הלולאה.

    **ריצה ידנית בלבד**: עולה טוקני LLM אמיתיים (ולפעמים גם קריאות
    SUMIT/Open-Finance דרך כלים שהמודל בוחר להפעיל, תחת שערי המכסה
    הקיימים) — לכן route אדמין מפורש בלבד. אין cron; ראו
    tests/test_vercel_cron_contract.py."""
    from ...services.moshko_regression import run_regression

    result = await run_regression(db, organization_id=organization_id, limit=limit)
    db.add(AuditLog(
        user_id=current_user.id,
        organization_id=organization_id,
        action="MOSHKO_REGRESSION_RUN",
        entity_type="MoshkoGap",
        details={
            "total": result["total"], "passed": result["passed"],
            "failed": result["failed"], "skipped": result["skipped"],
            "errored": result["errored"],
        },
    ))
    db.commit()
    return result


@router.get("/moshko/memory", tags=["Moshko"])
async def list_moshko_memory(
    organization_id: Optional[int] = None,
    user_id: Optional[int] = None,
    category: Optional[str] = None,
    source: Optional[str] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db_session),
    ctx: OrganizationAccessContext = Depends(get_access_context),
    _admin: User = Depends(get_organization_admin),
):
    # זיכרון מושקו נושא עובדות עסק — דליפה שלו היא דליפה חשבונאית.
    # ההיקף נגזר מההקשר, לא מ-`users.organization_id`.
    current_user = ctx.user
    _require_selected_organization(ctx, organization_id)
    query = db.query(MoshkoMemory)
    if ctx.is_super_admin:
        query = query.filter(MoshkoMemory.organization_id == ctx.organization_id)
        if user_id is not None:
            query = query.filter(MoshkoMemory.user_id == user_id)
    else:
        if organization_id is not None and organization_id != ctx.organization_id:
            raise HTTPException(status_code=403, detail="Access denied")
        if user_id is not None and user_id != current_user.id:
            raise HTTPException(status_code=403, detail="Personal memory is private")
        query = query.filter(MoshkoMemory.organization_id == ctx.organization_id)
        if user_id is None:
            query = query.filter(
                or_(MoshkoMemory.user_id.is_(None), MoshkoMemory.user_id == current_user.id)
            )
        else:
            query = query.filter(MoshkoMemory.user_id == current_user.id)
    if category is not None:
        query = query.filter(MoshkoMemory.category == _validate_memory_category(category))
    if source is not None:
        if source not in _MOSHKO_MEMORY_SOURCES:
            raise HTTPException(status_code=400, detail="Invalid memory source")
        query = query.filter(MoshkoMemory.source == source)
    total = query.count()
    rows = query.order_by(MoshkoMemory.updated_at.desc(), MoshkoMemory.id.desc()).offset(skip).limit(limit).all()
    return {
        "items": [_memory_payload(row) for row in rows],
        "total": total,
        "skip": skip,
        "limit": limit,
    }


@router.post("/moshko/memory", status_code=status.HTTP_201_CREATED, tags=["Moshko"])
async def create_moshko_memory(
    body: MoshkoMemoryCreateRequest,
    db: Session = Depends(get_db_session),
    ctx: OrganizationAccessContext = Depends(get_access_context),
    current_user: User = Depends(get_organization_admin),
):
    _require_selected_organization(ctx, body.organization_id)
    org = db.query(Organization).filter(Organization.id == ctx.organization_id).first()
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    if body.user_id is not None:
        target = (
            db.query(User)
            .join(OrganizationMembership, OrganizationMembership.user_id == User.id)
            .filter(
                User.id == body.user_id,
                OrganizationMembership.organization_id == ctx.organization_id,
            )
            .first()
        )
        if target is None:
            raise HTTPException(status_code=403, detail="User does not belong to organization")
        if not ctx.is_super_admin and body.user_id != current_user.id:
            raise HTTPException(status_code=403, detail="Personal memory is private")
    content = (body.content or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="Memory content is required")
    category = _validate_memory_category(body.category)
    _validate_memory_capacity(
        db,
        organization_id=ctx.organization_id,
        user_id=body.user_id,
        content=content,
    )
    now = datetime.utcnow()
    row = MoshkoMemory(
        organization_id=ctx.organization_id,
        user_id=body.user_id,
        content=content,
        category=category,
        source="admin",
        approved_at=now,
        approved_by=current_user.id,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    db.flush()
    db.add(AuditLog(
        user_id=current_user.id,
        organization_id=ctx.organization_id,
        action="MOSHKO_MEMORY_CREATE",
        entity_type="MoshkoMemory",
        entity_id=row.id,
        details={"old": None, "new": _memory_audit_snapshot(row)},
    ))
    db.commit()
    db.refresh(row)
    return _memory_payload(row)


@router.patch("/moshko/memory/{memory_id}", tags=["Moshko"])
async def update_moshko_memory(
    memory_id: int,
    body: MoshkoMemoryUpdateRequest,
    db: Session = Depends(get_db_session),
    ctx: OrganizationAccessContext = Depends(get_access_context),
    current_user: User = Depends(get_organization_admin),
):
    row = _memory_row_for_actor(db, memory_id, ctx)
    old = _memory_audit_snapshot(row)
    changed = False
    if body.content is not None:
        content = body.content.strip()
        if not content:
            raise HTTPException(status_code=400, detail="Memory content is required")
        _validate_memory_capacity(
            db,
            organization_id=row.organization_id,
            user_id=row.user_id,
            content=content,
            exclude_id=row.id,
        )
        row.content = content
        changed = True
    if body.category is not None:
        row.category = _validate_memory_category(body.category)
        changed = True
    if body.approved is not None:
        row.approved_at = datetime.utcnow() if body.approved else None
        row.approved_by = current_user.id if body.approved else None
        changed = True
    if not changed:
        raise HTTPException(status_code=400, detail="No memory changes supplied")
    row.updated_at = datetime.utcnow()
    db.flush()
    db.add(AuditLog(
        user_id=current_user.id,
        organization_id=row.organization_id,
        action="MOSHKO_MEMORY_UPDATE",
        entity_type="MoshkoMemory",
        entity_id=row.id,
        details={"old": old, "new": _memory_audit_snapshot(row)},
    ))
    db.commit()
    db.refresh(row)
    return _memory_payload(row)


@router.delete("/moshko/memory/{memory_id}", tags=["Moshko"])
async def delete_moshko_memory(
    memory_id: int,
    db: Session = Depends(get_db_session),
    ctx: OrganizationAccessContext = Depends(get_access_context),
    current_user: User = Depends(get_organization_admin),
):
    row = _memory_row_for_actor(db, memory_id, ctx)
    old = _memory_audit_snapshot(row)
    organization_id = row.organization_id
    db.add(AuditLog(
        user_id=current_user.id,
        organization_id=organization_id,
        action="MOSHKO_MEMORY_DELETE",
        entity_type="MoshkoMemory",
        entity_id=row.id,
        details={"old": old, "new": None},
    ))
    db.delete(row)
    db.commit()
    return {"status": "deleted", "id": memory_id}


@router.get("/moshko/knowledge", tags=["Moshko"])
async def get_moshko_knowledge_index(
    current_user: User = Depends(get_organization_admin),
):
    from ...services.moshko_knowledge import list_topics

    return list_topics()


@router.get("/moshko/knowledge/{topic_id}", tags=["Moshko"])
async def get_moshko_knowledge_topic(
    topic_id: str,
    current_user: User = Depends(get_organization_admin),
):
    from ...services.moshko_knowledge import get_topic

    result = get_topic(topic_id)
    if result.get("found") is False:
        raise HTTPException(status_code=404, detail="Knowledge topic not found")
    return result


@router.get("/moshko/ownership-review", tags=["Moshko"])
async def get_ownership_review_queue(
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_super_admin),
):
    """כל הארגונים שההתאמה האוטומטית שלהם לא הכריעה, ממוין לפי חומרה."""
    return review_queue(db)


@router.post("/moshko/ownership-review/{organization_id}/resolve", tags=["Moshko"])
async def resolve_ownership_review(
    organization_id: int,
    body: OwnershipResolveRequest,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_super_admin),
):
    """הכרעה ידנית של הבעלים: מסמן איזה חשבון הוא חשבון העסק הראשי.

    לא ניחוש — רק מנהל המערכת (הבעלים) יכול לקבוע זאת, ורק כשההתאמה
    האוטומטית לא התלכדה. מסמן, כותב AuditLog, ולא חוזר לתור ההכרעה.
    """
    org = db.query(Organization).filter(Organization.id == organization_id).first()
    if not org:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")

    account = db.query(Account).filter(Account.id == body.account_id).first()
    if not account or account.organization_id != organization_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Account does not belong to this organization",
        )

    # Clear any previous primary flag before setting the new one — exactly
    # one account may be marked primary at a time.
    db.query(Account).filter(
        Account.organization_id == organization_id,
        Account.is_primary_business_account.is_(True),
    ).update({"is_primary_business_account": False})

    account.is_primary_business_account = True
    if body.tax_id:
        org.tax_id = body.tax_id
    org.ownership_reviewed_at = datetime.now(timezone.utc)

    audit_log = AuditLog(
        user_id=current_user.id,
        organization_id=organization_id,
        action="RESOLVE",
        entity_type="OwnershipReview",
        entity_id=organization_id,
        details={"account_id": body.account_id, "tax_id": body.tax_id},
    )
    db.add(audit_log)
    db.commit()

    return ownership_status(db, organization_id)


@router.get("/cost-protection-status", tags=["Admin"])
async def cost_protection_status(
    current_user: User = Depends(get_super_admin),
):
    """ערכי-האמת של הגנות-העלות כפי שה-runtime באמת רואה אותם (30/08/2026).

    נולד מחקירת "minute budget exceeded" שרצה מ-24/08: ניתוח קוד+env
    מרחוק לא הצליח להכריע מה ה-runtime של Vercel טוען בפועל. קריאה-בלבד,
    אפס קריאות SUMIT — רק חשיפת settings + המגביל כפי שהיה נבנה עכשיו.
    """
    from ...config import settings as live_settings
    from ...services.sumit_request_budget import SumitRequestLimiter

    limiter = SumitRequestLimiter(current_user.organization_id or 1)
    return {
        "sumit": {
            "environment": live_settings.sumit_environment,
            "global_requests_per_minute": live_settings.sumit_global_requests_per_minute,
            "org_daily_request_limit": live_settings.sumit_org_daily_request_limit,
            "test_requests_per_minute": live_settings.sumit_test_requests_per_minute,
            "test_org_daily_request_limit": live_settings.sumit_test_org_daily_request_limit,
            "test_monthly_request_limit": live_settings.sumit_test_monthly_request_limit,
            "live_monthly_request_limit": live_settings.sumit_live_monthly_request_limit,
            "enrichment_daily_action_limit": live_settings.sumit_enrichment_daily_action_limit,
            "sync_min_interval_hours": live_settings.sumit_sync_min_interval_hours,
            "effective_per_minute_limit": limiter.per_minute_limit,
            "effective_daily_limit": limiter.daily_limit,
        },
        "open_finance": {
            "sync_min_interval_hours": live_settings.of_sync_min_interval_hours,
        },
    }
