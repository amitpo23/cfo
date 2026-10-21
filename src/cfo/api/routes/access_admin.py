"""ניהול הרשאות לפי מייל — המקבילה של app/admin/rbac (Medici) ושל
admin-hotel-access (price-monitor), בצד השרת.

SUPER_ADMIN — כל ארגון. ADMIN — רק בארגון שבו יש לו חברות ADMIN פעילה.
הסמכות נבדקת מול ארגון היעד שבגוף הבקשה (RBACGuard.authorize), ולא מול
כותרת X-Active-Org-Id: מנהל-על אינו צריך "להיכנס" לתיק כדי לנהל את
ההרשאות שלו, ומנהל ארגון אינו יכול לבחור ארגון אחר בגוף הבקשה.
"""
from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from ...database import get_db_session
from ...models import ClientDashboard, Organization, OrganizationMembership, User, UserRole
from ...services import access_grants, auth_audit
from ...services.access_grants import GrantError
from ...services.rbac import rbac_export
from ..dependencies import get_current_user
from ..rbac import RBACGuard, require_rbac

router = APIRouter()


class GrantBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_type: Literal["organization", "dashboard"]
    organization_id: Optional[int] = None
    dashboard_id: Optional[int] = None
    email: str = Field(min_length=3, max_length=320)
    role: Optional[str] = None
    # מנהל-על בלבד, משתמש קיים בלבד — ראו access_grants.grant_org.
    activate_now: bool = False


class RevokeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_type: Literal["organization", "dashboard"]
    organization_id: Optional[int] = None
    dashboard_id: Optional[int] = None
    email: str = Field(min_length=3, max_length=320)


def _http(exc: GrantError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail=exc.message_he)


def _target_org(db: Session, target_type: str, organization_id: Optional[int],
                dashboard_id: Optional[int]) -> int:
    if target_type == "organization":
        if organization_id is None:
            raise HTTPException(422, "חסר organization_id")
        return organization_id
    if dashboard_id is None:
        raise HTTPException(422, "חסר dashboard_id")
    row = db.get(ClientDashboard, dashboard_id)
    if row is None:
        raise HTTPException(404, "הדשבורד לא נמצא")
    return row.primary_organization_id


@router.get("/rbac")
def rbac_config(_: User = Depends(get_current_user)):
    """מפת התפקידים/scopes/endpoints — אותו מבנה כמו config.ts של Medici."""
    return rbac_export()


@router.get("/organizations")
def manageable_organizations(
    db: Session = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """הארגונים שהמשתמש רשאי לנהל בהם הרשאות (לבורר במסך)."""
    query = db.query(Organization).filter(Organization.is_active.is_(True))
    if not access_grants.is_super_admin(user):
        org_ids = [
            m.organization_id
            for m in db.query(OrganizationMembership).filter_by(
                user_id=user.id, status="active", role=UserRole.ADMIN,
            ).all()
            if access_grants.actor_role_in(db, user, m.organization_id) == "admin"
        ]
        query = query.filter(Organization.id.in_(org_ids or [-1]))
    orgs = query.order_by(Organization.id).all()
    return {"organizations": [{"id": o.id, "name": o.name} for o in orgs],
            "is_super_admin": access_grants.is_super_admin(user)}


@router.get("/grants")
def list_grants(
    organization_id: int = Query(...),
    db: Session = Depends(get_db_session),
    guard: RBACGuard = Depends(require_rbac("ADMIN.ACCESS.LIST")),
):
    guard.authorize(organization_id)
    exported = access_grants.export_grants(db, [organization_id])
    dashboards = (
        db.query(ClientDashboard)
        .filter(ClientDashboard.primary_organization_id == organization_id)
        .order_by(ClientDashboard.id).all()
    )
    return {
        "organization_id": organization_id,
        "grants": exported["grants"],
        "dashboards": [{"id": d.id, "slug": d.slug, "title": d.title,
                        "access_mode": d.access_mode} for d in dashboards],
    }


@router.post("/grants", status_code=201)
def create_grant(
    body: GrantBody,
    db: Session = Depends(get_db_session),
    guard: RBACGuard = Depends(require_rbac("ADMIN.ACCESS.GRANT")),
):
    org_id = _target_org(db, body.target_type, body.organization_id, body.dashboard_id)
    guard.authorize(org_id)
    try:
        if body.target_type == "organization":
            row = access_grants.grant_org(db, guard.user, organization_id=org_id,
                                          email=body.email, role=body.role or "viewer",
                                          activate_now=body.activate_now)
            result = {"target": {"type": "organization", "id": org_id},
                      "role": row.role.value, "status": row.status}
        else:
            row = access_grants.grant_dashboard(db, guard.user, dashboard_id=body.dashboard_id,
                                                email=body.email, role=body.role or "client_viewer")
            result = {"target": {"type": "dashboard", "id": body.dashboard_id},
                      "role": row.role, "status": row.status}
    except GrantError as exc:
        db.rollback()
        raise _http(exc)
    email = access_grants.normalize_email(body.email)
    auth_audit.record(
        db, action="ACCESS_GRANT", resource="ADMIN.ACCESS.GRANT", status=201,
        request=guard.request, user_id=guard.user.id, organization_id=org_id,
        extra={"target": result["target"], "email": email, "role": result["role"]},
    )
    return {"email": email, **result}


@router.post("/grants/revoke")
def revoke_grant(
    body: RevokeBody,
    db: Session = Depends(get_db_session),
    guard: RBACGuard = Depends(require_rbac("ADMIN.ACCESS.REVOKE")),
):
    org_id = _target_org(db, body.target_type, body.organization_id, body.dashboard_id)
    guard.authorize(org_id)
    try:
        if body.target_type == "organization":
            access_grants.revoke_org(db, guard.user, organization_id=org_id, email=body.email)
            target = {"type": "organization", "id": org_id}
        else:
            access_grants.revoke_dashboard(db, guard.user, dashboard_id=body.dashboard_id, email=body.email)
            target = {"type": "dashboard", "id": body.dashboard_id}
    except GrantError as exc:
        db.rollback()
        raise _http(exc)
    email = access_grants.normalize_email(body.email)
    auth_audit.record(
        db, action="ACCESS_REVOKE", resource="ADMIN.ACCESS.REVOKE", status=200,
        request=guard.request, user_id=guard.user.id, organization_id=org_id,
        extra={"target": target, "email": email},
    )
    return {"email": email, "target": target, "status": "revoked"}


@router.get("/export")
def export_grants(
    organization_id: Optional[int] = None,
    db: Session = Depends(get_db_session),
    guard: RBACGuard = Depends(require_rbac("ADMIN.ACCESS.EXPORT")),
):
    if organization_id is None:
        guard.authorize_platform()
        payload = access_grants.export_grants(db)
    else:
        guard.authorize(organization_id)
        payload = access_grants.export_grants(db, [organization_id])
    db.commit()
    return payload


@router.post("/import")
def import_grants(
    payload: dict,
    db: Session = Depends(get_db_session),
    guard: RBACGuard = Depends(require_rbac("ADMIN.ACCESS.IMPORT")),
):
    guard.authorize_platform()
    try:
        result = access_grants.import_grants(db, guard.user, payload)
    except GrantError as exc:
        db.rollback()
        raise _http(exc)
    auth_audit.record(
        db, action="ACCESS_IMPORT", resource="ADMIN.ACCESS.IMPORT", status=200,
        request=guard.request, user_id=guard.user.id,
        extra={"applied": result["applied"], "total": len(result["results"])},
    )
    return result
