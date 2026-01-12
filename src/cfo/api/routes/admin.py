"""
Admin API routes
ניהול מערכת, משתמשים, ארגונים וחברות
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from typing import List, Optional, Dict, Any

from ...database import get_db_session
from ...models import (
    User, Organization, AuditLog,
    UserCreate, UserUpdate, UserResponse, UserLogin, Token,
    OrganizationCreate, OrganizationUpdate, OrganizationResponse,
    UserRole
)
from ...auth import verify_password, get_password_hash, create_access_token
from ..dependencies import (
    get_current_user, 
    get_super_admin, 
    get_organization_admin,
    get_sumit_integration
)
from ...integrations.sumit_integration import SumitIntegration
from ...integrations.sumit_models import (
    CompanyRequest, CompanyResponse,
    UserRequest, UserResponse as SumitUserResponse, UserPermission,
    StockItemResponse
)

router = APIRouter()


# ==================== Authentication ====================

@router.post("/auth/register", response_model=Token, status_code=status.HTTP_201_CREATED, tags=["Auth"])
async def register(
    user_data: UserCreate,
    db: Session = Depends(get_db_session)
):
    """הרשמת משתמש חדש"""
    existing_user = db.query(User).filter(User.email == user_data.email).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )
    
    if user_data.organization_id:
        org = db.query(Organization).filter(Organization.id == user_data.organization_id).first()
        if not org:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Organization not found"
            )
    
    new_user = User(
        email=user_data.email,
        password_hash=get_password_hash(user_data.password),
        full_name=user_data.full_name,
        phone=user_data.phone,
        role=user_data.role,
        organization_id=user_data.organization_id
    )
    
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    
    access_token = create_access_token(data={"sub": new_user.id, "role": new_user.role.value})
    
    return Token(
        access_token=access_token,
        user=UserResponse.model_validate(new_user)
    )


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
