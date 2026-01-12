"""
Authentication and authorization dependencies
"""
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Optional
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db_session
from ..models import User, UserRole
from ..auth import decode_access_token

security = HTTPBearer()


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
    
    user_id: int = payload.get("sub")
    if user_id is None:
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


async def get_sumit_integration():
    """
    Get SUMIT integration instance
    
    Returns:
        SumitIntegration instance
        
    Raises:
        HTTPException: If API key is not configured
    """
    from ..integrations.sumit_integration import SumitIntegration
    
    if not settings.sumit_api_key:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="SUMIT API key not configured"
        )
    
    return SumitIntegration(
        api_key=settings.sumit_api_key,
        company_id=settings.sumit_company_id
    )


def require_admin(current_user: dict = Depends(get_current_user)):
    """
    Require admin role
    
    Args:
        current_user: Current user from JWT
        
    Returns:
        User dict
        
    Raises:
        HTTPException: If user is not admin
    """
    if current_user.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    return current_user
