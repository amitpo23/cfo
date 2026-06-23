"""
Admin API routes
ניהול מערכת, משתמשים, ארגונים וחברות
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import List, Optional, Dict, Any
import secrets
from urllib.parse import urlencode

from ...database import get_db_session
from ...models import (
    User, Organization, AuditLog,
    UserCreate, UserUpdate, UserResponse, UserLogin, GoogleLogin, Token,
    OrganizationCreate, OrganizationUpdate, OrganizationResponse,
    UserRole, IntegrationType
)
from ...auth import verify_password, get_password_hash, create_access_token
from ..dependencies import (
    get_current_user, 
    get_super_admin, 
    get_organization_admin,
    get_sumit_integration,
    require_admin
)
from ...integrations.sumit_integration import SumitIntegration
from ...integrations.sumit_models import (
    CompanyRequest, CompanyResponse,
    UserRequest, UserResponse as SumitUserResponse, UserPermission,
    StockItemResponse
)

router = APIRouter()


# ==================== Authentication ====================

PLAN_PRICE_FALLBACKS = {
    "company_up_to_2_5m": {"monthly_ils": 750, "label": "חברה / שותפות עד 2.5M"},
    "company_above_2_5m": {"monthly_ils": 750, "label": "חברה בצמיחה מעל 2.5M"},
    "office": {"monthly_ils": None, "label": "רצף Office"},
}


class CheckoutCreate(BaseModel):
    selected_plan: str
    annual_revenue: Optional[str] = None
    payment_template: str = "credit_card"
    annual_report_requested: bool = True
    email: Optional[str] = None
    success_path: str = "/"
    cancel_path: str = "/"


async def _assert_registration_allowed(
    registration_code: Optional[str],
    checkout_session_id: Optional[str] = None,
):
    from ...config import settings
    from os import getenv

    if checkout_session_id:
        if checkout_session_id.startswith("mock_") and not getenv("VERCEL"):
            return
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


@router.post("/billing/checkout", tags=["Billing"])
async def create_billing_checkout(body: CheckoutCreate):
    """Create a signup checkout session before tenant registration."""
    if body.selected_plan not in PLAN_PRICE_FALLBACKS:
        raise HTTPException(status_code=400, detail="Unknown plan")

    stripe_session = await _create_stripe_checkout(body)
    if stripe_session:
        return stripe_session

    from os import getenv
    if getenv("VERCEL"):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Stripe checkout is not configured for production",
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
    # its admin), so integrations/credentials are isolated per tenant. The
    # first user attaches to the default org, which may use env credentials.
    if organization_id is None:
        if is_first_user:
            organization_id = 1
        else:
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
    db.commit()
    db.refresh(new_user)
    return new_user


def _token_for_user(user: User) -> Token:
    access_token = create_access_token(data={"sub": user.id, "role": user.role.value})
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
        from datetime import datetime
        user.last_login = datetime.utcnow()
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


@router.post("/auth/login", response_model=Token, tags=["Auth"])
async def login(
    login_data: UserLogin,
    db: Session = Depends(get_db_session)
):
    """התחברות למערכת"""
    user = db.query(User).filter(User.email == login_data.email).first()
    
    if not user or not verify_password(login_data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password"
        )
    
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is disabled"
        )
    
    # Update last login
    from datetime import datetime
    user.last_login = datetime.utcnow()
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
            "org_id": user.organization_id
        }
    )
    
    return Token(
        access_token=access_token,
        user=UserResponse.model_validate(user)
    )


@router.post("/db/migrate", tags=["Admin"])
async def run_db_migrations(current_user: User = Depends(require_admin)):
    """
    Apply Alembic migrations (admin only).

    Databases created before Alembic was introduced (via create_all) are
    stamped to the baseline first, then upgraded.
    """
    from pathlib import Path

    from alembic import command as alembic_command
    from alembic.config import Config as AlembicConfig
    from sqlalchemy import inspect as sa_inspect

    from ...database import engine

    root = Path(__file__).resolve().parents[4]
    cfg = AlembicConfig(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "alembic"))

    inspector = sa_inspect(engine)
    tables = inspector.get_table_names()
    if "users" in tables and "alembic_version" not in tables:
        # Pre-Alembic database: schema already matches the baseline.
        alembic_command.stamp(cfg, "head")
        action = "stamped"
    else:
        alembic_command.upgrade(cfg, "head")
        action = "upgraded"

    with engine.connect() as conn:
        from sqlalchemy import text
        revision = conn.execute(text("select version_num from alembic_version")).scalar()

    return {"action": action, "current_revision": revision}


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


@router.get("/organizations/{org_id}", response_model=OrganizationResponse, tags=["Organizations"])
async def get_organization(
    org_id: int,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user)
):
    """קבלת פרטי ארגון"""
    if current_user.role != UserRole.SUPER_ADMIN and current_user.organization_id != org_id:
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
    current_user: User = Depends(get_organization_admin)
):
    """עדכון ארגון"""
    if current_user.role != UserRole.SUPER_ADMIN and current_user.organization_id != org_id:
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

@router.get("/users", response_model=List[UserResponse], tags=["Users"])
async def list_users(
    organization_id: int = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_organization_admin)
):
    """רשימת משתמשים"""
    query = db.query(User)
    
    if current_user.role != UserRole.SUPER_ADMIN:
        query = query.filter(User.organization_id == current_user.organization_id)
    elif organization_id:
        query = query.filter(User.organization_id == organization_id)
    
    users = query.offset(skip).limit(limit).all()
    return [UserResponse.model_validate(user) for user in users]


@router.get("/users/{user_id}", response_model=UserResponse, tags=["Users"])
async def get_user(
    user_id: int,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user)
):
    """קבלת פרטי משתמש"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    if current_user.role not in [UserRole.SUPER_ADMIN, UserRole.ADMIN]:
        if current_user.id != user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied"
            )
    elif current_user.role == UserRole.ADMIN:
        if user.organization_id != current_user.organization_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied"
            )
    
    return UserResponse.model_validate(user)


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
    current_user: User = Depends(get_organization_admin)
):
    """קבלת לוגים למעקב"""
    query = db.query(AuditLog)
    
    if current_user.role != UserRole.SUPER_ADMIN:
        query = query.filter(AuditLog.organization_id == current_user.organization_id)
    elif organization_id:
        query = query.filter(AuditLog.organization_id == organization_id)
    
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

@router.post("/users", response_model=UserResponse)
async def create_user(
    user: UserRequest,
    sumit: SumitIntegration = Depends(get_sumit_integration),
    current_user: dict = Depends(require_admin)
):
    """Create new user"""
    async with sumit:
        return await sumit.create_user(user)


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
