"""
Authentication and authorization dependencies
"""
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Optional, Generator
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db_session, SessionLocal
from ..models import User, UserRole
from ..auth import decode_access_token

security = HTTPBearer()


def get_db() -> Generator[Session, None, None]:
    """
    Database session dependency
    יצירת חיבור לדאטאבייס
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db_session)
) -> User:
    """
    קבלת המשתמש הנוכחי מה-token
    
    Args:
        credentials: HTTP authorization credentials
        db: Database session
        
    Returns:
        User object
        
    Raises:
        HTTPException: If token is invalid or user not found
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    token = credentials.credentials
    payload = decode_access_token(token)
    
    if payload is None:
        raise credentials_exception
    
    # "sub" is stored as a string in the JWT (python-jose requirement);
    # convert back to the integer primary key before querying.
    try:
        user_id = int(payload.get("sub"))
    except (TypeError, ValueError):
        raise credentials_exception

    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise credentials_exception
    
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is disabled"
        )
    
    return user


async def get_current_org_id(
    current_user: User = Depends(get_current_user)
) -> int:
    """Organization scope of the authenticated user.

    Routes must derive the tenant from the token, never from a
    caller-controlled query parameter.

    A user with no organization (e.g. a super-admin row) must NOT silently fall
    back to org 1 — that would read/write another tenant's data. Reject instead;
    such users must select an org explicitly via an admin path.
    """
    if current_user.organization_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is not scoped to an organization",
        )
    return current_user.organization_id


async def get_current_active_user(
    current_user: User = Depends(get_current_user)
) -> User:
    """בדיקה שהמשתמש פעיל"""
    if not current_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive user"
        )
    return current_user


def require_role(*allowed_roles: UserRole):
    """
    Dependency לבדיקת הרשאות לפי תפקיד
    
    Usage:
        @router.get("/admin-only")
        async def admin_endpoint(user: User = Depends(require_role(UserRole.ADMIN))):
            ...
    """
    async def role_checker(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied. Required roles: {[r.value for r in allowed_roles]}"
            )
        return current_user
    
    return role_checker


async def get_super_admin(
    current_user: User = Depends(get_current_user)
) -> User:
    """בדיקה שהמשתמש הוא מנהל על"""
    if current_user.role != UserRole.SUPER_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Super admin access required"
        )
    return current_user


async def get_organization_admin(
    current_user: User = Depends(get_current_user)
) -> User:
    """בדיקה שהמשתמש הוא מנהל ארגון או מנהל על"""
    if current_user.role not in [UserRole.SUPER_ADMIN, UserRole.ADMIN]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    return current_user


async def get_sumit_integration(
    org_id: int = Depends(get_current_org_id),
    db: Session = Depends(get_db_session),
):
    """Get a SUMIT integration instance scoped to the caller's organization.

    Resolves credentials from the per-org encrypted vault (IntegrationConnection,
    source="sumit"). Environment credentials are honored ONLY for the default org
    (org 1); every other tenant must configure its own SUMIT key, so its requests
    never silently run against another org's SUMIT account.

    Raises:
        HTTPException 400: if no SUMIT credentials are configured for this org.
    """
    from ..integrations.sumit_integration import SumitIntegration
    from ..models import IntegrationConnection
    from ..services.credentials_vault import decrypt_credentials

    conn = db.query(IntegrationConnection).filter(
        IntegrationConnection.organization_id == org_id,
        IntegrationConnection.source == "sumit",
        IntegrationConnection.status == "active",
    ).order_by(IntegrationConnection.id).first()
    creds = decrypt_credentials(conn.credentials_encrypted) if conn else {}

    env_allowed = org_id == 1
    api_key = creds.get("api_key") or (settings.sumit_api_key if env_allowed else None)
    company_id = creds.get("company_id") or (settings.sumit_company_id if env_allowed else None)

    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="SUMIT API key not configured for this organization",
        )

    return SumitIntegration(api_key=api_key, company_id=company_id)


def sumit_for_org(db: Session, org_id: int):
    """בונה SumitIntegration לארגון נתון מחוץ ל-request (ל-cron). None אם אין מפתח."""
    from ..integrations.sumit_integration import SumitIntegration
    from ..models import IntegrationConnection
    from ..services.credentials_vault import decrypt_credentials

    conn = db.query(IntegrationConnection).filter(
        IntegrationConnection.organization_id == org_id,
        IntegrationConnection.source == "sumit",
        IntegrationConnection.status == "active",
    ).order_by(IntegrationConnection.id).first()
    creds = decrypt_credentials(conn.credentials_encrypted) if conn else {}

    env_allowed = org_id == 1
    api_key = creds.get("api_key") or (settings.sumit_api_key if env_allowed else None)
    company_id = creds.get("company_id") or (settings.sumit_company_id if env_allowed else None)
    if not api_key:
        return None
    return SumitIntegration(api_key=api_key, company_id=company_id)


def require_admin(current_user: dict = Depends(get_current_user)):
    """
    Require admin role
    
    Args:
        current_user: Current user from JWT
        
    Returns:
        User object

    Raises:
        HTTPException: If user is not admin
    """
    if current_user.role not in (UserRole.ADMIN, UserRole.SUPER_ADMIN):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    return current_user
