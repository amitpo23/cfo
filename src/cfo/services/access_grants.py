"""הרשאות גישה לפי מייל — ארגון ודשבורד.

פורט של סמנטיקת האישור של price-monitor (profiles.is_approved +
hotel_user_access): מנהל מעניק גישה למייל מסוים → ההרשאה ממתינה
(``invited``) → נעשית ``active`` בהתחברות המאומתת הראשונה של אותו מייל →
``revoked`` בביטול.

ההבדלים המכוונים מהמקור (ראו docs/AUTH_MEDICI_PORT.md):
- price-monitor יצר פרופיל לכל משתמש Google והעניק ``is_approved`` בהוספת
  גישה; ה-endpoint ``/api/admin/users/approve`` שם אף לא בדק שהקורא אדמין.
  כאן כל הענקה עוברת בדיקת סמכות בארגון היעד, ומייל לא מוכר נדחה.
- ארגון: ההרשאה היא ``OrganizationMembership`` בסטטוס ``invited`` (דרך
  ``membership_service.invite_checked``). כדי שתהיה רשומת חברות, למייל שאין
  לו עדיין משתמש נוצרת **זהות** (users) בלי סיסמה שמישה ובלי ארגון. זו לא
  הצטרפות לפי התאמת מייל: מנהל הארגון בחר במפורש את המייל הזה.
- דשבורד: ``DashboardAccessGrant`` לפי מייל.
"""
from __future__ import annotations

import secrets
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..auth import get_password_hash
from ..models import (
    ClientDashboard, DashboardAccessGrant, Organization, OrganizationMembership,
    User, UserRole,
)
from . import membership_service
from .rbac import DASHBOARD_GRANT_ROLES, MEDICI_ROLE_ALIASES, ORG_GRANT_ROLES

INVITED = "invited"
ACTIVE = "active"
REVOKED = "revoked"


class GrantError(Exception):
    def __init__(self, status: int, message_he: str):
        self.status = status
        self.message_he = message_he
        super().__init__(message_he)


def normalize_email(email: str) -> str:
    value = (email or "").strip().lower()
    if "@" not in value or len(value) > 320 or value.startswith("@") or value.endswith("@"):
        raise GrantError(422, "כתובת מייל לא תקינה")
    return value


def find_user(db: Session, email: str) -> Optional[User]:
    """חיפוש משתמש ללא תלות ברישיות. התאמה מדויקת קודמת, אם יש כמה."""
    raw = (email or "").strip()
    exact = db.query(User).filter(User.email == raw).first()
    if exact is not None:
        return exact
    return (
        db.query(User)
        .filter(func.lower(User.email) == raw.lower())
        .order_by(User.id.asc())
        .first()
    )


# --------------------------------------------------------------------- #
# סמכות
# --------------------------------------------------------------------- #
def is_super_admin(user: User) -> bool:
    return bool(user and user.is_active and user.role == UserRole.SUPER_ADMIN)


def actor_role_in(db: Session, actor: User, organization_id: int) -> Optional[str]:
    """התפקיד האפקטיבי (מפתח ROLE_CONFIG) של הפועל בארגון היעד."""
    if is_super_admin(actor):
        return "super_admin"
    role = membership_service.role_in(db, actor.id, organization_id)
    return role.value if role is not None else None


def assert_can_grant(db: Session, actor: User, organization_id: int) -> None:
    org = db.get(Organization, organization_id)
    if org is None:
        raise GrantError(404, "הארגון לא נמצא")
    if actor_role_in(db, actor, organization_id) not in ("super_admin", "admin"):
        raise GrantError(403, "אין לך הרשאת ניהול בארגון הזה")


# --------------------------------------------------------------------- #
# ארגון
# --------------------------------------------------------------------- #
def _ensure_identity(db: Session, email: str) -> User:
    user = find_user(db, email)
    if user is not None:
        return user
    user = User(
        email=email,
        # סיסמה אקראית שאיש אינו יודע: הכניסה הראשונה היא Google, או
        # "שכחתי סיסמה".
        password_hash=get_password_hash(secrets.token_urlsafe(32)),
        full_name=email.split("@", 1)[0],
        role=UserRole.USER,
        organization_id=None,
        is_active=True,
    )
    db.add(user)
    db.flush()
    return user


def grant_org(db: Session, actor: User, *, organization_id: int, email: str, role: str,
              activate_now: bool = False) -> OrganizationMembership:
    """``activate_now`` — מנהל-על בלבד, למשתמש **קיים**: חברות פעילה מיד.
    זה מסלול השחרור למשתמש קיים בלי חברות (למשל אחרי שה-backfill לא רץ),
    בלי fallback ל-users.organization_id."""
    email = normalize_email(email)
    if role not in ORG_GRANT_ROLES:
        raise GrantError(422, "תפקיד לא חוקי להרשאת ארגון")
    assert_can_grant(db, actor, organization_id)
    if activate_now:
        if not is_super_admin(actor):
            raise GrantError(403, "הפעלה מיידית שמורה למנהל-על")
        if find_user(db, email) is None:
            raise GrantError(409, "הפעלה מיידית רק למשתמש קיים; למייל חדש שלחו הזמנה")
    target = _ensure_identity(db, email)
    if target.role == UserRole.SUPER_ADMIN:
        raise GrantError(409, "מנהל-על אינו זקוק להרשאת ארגון")
    if not target.is_active:
        raise GrantError(409, "המשתמש מושבת")
    is_super = is_super_admin(actor)
    existing = (
        db.query(OrganizationMembership)
        .filter_by(organization_id=organization_id, user_id=target.id)
        .first()
    )
    try:
        if activate_now or (existing is not None and existing.status == ACTIVE):
            # כבר פעיל — שינוי תפקיד בלבד, לא החזרה ל-invited.
            membership = membership_service.grant_checked(
                db, organization_id=organization_id, user_id=target.id,
                role=UserRole(role), acting_user_id=actor.id, status=ACTIVE,
                acting_is_platform_super_admin=is_super,
            )
        else:
            membership = membership_service.invite_checked(
                db, organization_id=organization_id, user_id=target.id,
                role=UserRole(role), acting_user_id=actor.id,
                acting_is_platform_super_admin=is_super,
            )
    except PermissionError as exc:
        raise GrantError(403, str(exc)) from exc
    except ValueError as exc:
        raise GrantError(409, str(exc)) from exc
    return membership


def revoke_org(db: Session, actor: User, *, organization_id: int, email: str) -> OrganizationMembership:
    email = normalize_email(email)
    assert_can_grant(db, actor, organization_id)
    target = find_user(db, email)
    if target is None:
        raise GrantError(404, "אין הרשאה לביטול")
    try:
        return membership_service.revoke_checked(
            db, organization_id=organization_id, user_id=target.id,
            acting_user_id=actor.id,
            acting_is_platform_super_admin=is_super_admin(actor),
        )
    except PermissionError as exc:
        raise GrantError(403, str(exc)) from exc
    except ValueError as exc:
        raise GrantError(409, str(exc)) from exc


# --------------------------------------------------------------------- #
# דשבורד
# --------------------------------------------------------------------- #
def _dashboard(db: Session, dashboard_id: int) -> ClientDashboard:
    row = db.get(ClientDashboard, dashboard_id)
    if row is None:
        raise GrantError(404, "הדשבורד לא נמצא")
    return row


def grant_dashboard(db: Session, actor: User, *, dashboard_id: int, email: str,
                    role: str = "client_viewer", source: str = "rezef") -> DashboardAccessGrant:
    email = normalize_email(email)
    if role not in DASHBOARD_GRANT_ROLES:
        raise GrantError(422, "תפקיד לא חוקי להרשאת דשבורד")
    row = _dashboard(db, dashboard_id)
    assert_can_grant(db, actor, row.primary_organization_id)
    grant = db.query(DashboardAccessGrant).filter_by(dashboard_id=row.id, email=email).first()
    if grant is None:
        grant = DashboardAccessGrant(
            dashboard_id=row.id, email=email, role=role, status=INVITED,
            source=source, granted_by_user_id=actor.id,
        )
        db.add(grant)
    else:
        grant.role = role
        grant.granted_by_user_id = actor.id
        grant.revoked_at = None
        grant.revoked_by_user_id = None
        if grant.status != ACTIVE:
            grant.status = INVITED
    db.flush()
    return grant


def revoke_dashboard(db: Session, actor: User, *, dashboard_id: int, email: str) -> DashboardAccessGrant:
    email = normalize_email(email)
    row = _dashboard(db, dashboard_id)
    assert_can_grant(db, actor, row.primary_organization_id)
    grant = db.query(DashboardAccessGrant).filter_by(dashboard_id=row.id, email=email).first()
    if grant is None:
        raise GrantError(404, "אין הרשאה לביטול")
    grant.status = REVOKED
    grant.revoked_at = datetime.utcnow()
    grant.revoked_by_user_id = actor.id
    db.flush()
    return grant


def dashboard_grant_role(db: Session, user: Optional[User], dashboard_id: int) -> Optional[str]:
    if user is None or not user.is_active:
        return None
    grant = (
        db.query(DashboardAccessGrant)
        .filter_by(dashboard_id=dashboard_id, user_id=user.id, status=ACTIVE)
        .first()
    )
    return grant.role if grant is not None else None


def has_pending_dashboard_grant(db: Session, email: str) -> bool:
    return (
        db.query(DashboardAccessGrant.id)
        .filter(DashboardAccessGrant.email == email.strip().lower(),
                DashboardAccessGrant.status.in_((INVITED, ACTIVE)))
        .first()
        is not None
    )


# --------------------------------------------------------------------- #
# הפעלה בהתחברות מאומתת
# --------------------------------------------------------------------- #
def activate_pending_for_login(db: Session, user: User) -> dict[str, int]:
    """invited → active לכל ההרשאות שמנהל הנפיק לזהות הזו.

    נקרא רק אחרי הוכחת זהות (Google עם email_verified, או סיסמה נכונה).
    """
    if not user.is_active:
        return {"organizations": 0, "dashboards": 0}
    orgs = 0
    pending = (
        db.query(OrganizationMembership)
        .filter_by(user_id=user.id, status=INVITED)
        .all()
    )
    for membership in pending:
        try:
            membership_service.accept(
                db, organization_id=membership.organization_id,
                user_id=user.id, acting_user_id=user.id,
            )
            orgs += 1
        except (ValueError, PermissionError):
            continue  # הזמנה שפגה נשארת invited — לא מופעלת בשקט.
    dashboards = 0
    email = (user.email or "").strip().lower()
    for grant in db.query(DashboardAccessGrant).filter_by(email=email, status=INVITED).all():
        grant.status = ACTIVE
        grant.user_id = user.id
        grant.activated_at = datetime.utcnow()
        dashboards += 1
    db.flush()
    return {"organizations": orgs, "dashboards": dashboards}


def ensure_identity_for_dashboard_grant(db: Session, email: str) -> User:
    """זהות למי שיש לו רק הרשאת דשבורד ממתינה (אין לו משתמש עדיין)."""
    return _ensure_identity(db, normalize_email(email))


# --------------------------------------------------------------------- #
# רשימה, ייצוא וייבוא (פורמט שמיועד ל-Medici)
# --------------------------------------------------------------------- #
def _org_rows(db: Session, organization_ids: Optional[list[int]]) -> list[dict[str, Any]]:
    query = db.query(OrganizationMembership, User).join(User, User.id == OrganizationMembership.user_id)
    if organization_ids is not None:
        query = query.filter(OrganizationMembership.organization_id.in_(organization_ids))
    rows = []
    for membership, user in query.order_by(OrganizationMembership.organization_id, User.email).all():
        rows.append({
            "email": (user.email or "").lower(),
            "target": {"type": "organization", "id": membership.organization_id},
            "role": membership.role.value,
            "status": membership.status,
            "source": "rezef",
        })
    return rows


def _dashboard_rows(db: Session, organization_ids: Optional[list[int]]) -> list[dict[str, Any]]:
    query = db.query(DashboardAccessGrant, ClientDashboard).join(
        ClientDashboard, ClientDashboard.id == DashboardAccessGrant.dashboard_id,
    )
    if organization_ids is not None:
        query = query.filter(ClientDashboard.primary_organization_id.in_(organization_ids))
    return [
        {
            "email": grant.email,
            "target": {"type": "dashboard", "id": dash.id, "slug": dash.slug,
                       "organization_id": dash.primary_organization_id},
            "role": grant.role,
            "status": grant.status,
            "source": grant.source,
        }
        for grant, dash in query.order_by(ClientDashboard.id, DashboardAccessGrant.email).all()
    ]


def export_grants(db: Session, organization_ids: Optional[list[int]] = None) -> dict[str, Any]:
    return {
        "version": 1,
        "source": "rezef",
        "exported_at": datetime.utcnow().isoformat() + "Z",
        "grants": _org_rows(db, organization_ids) + _dashboard_rows(db, organization_ids),
    }


def import_grants(db: Session, actor: User, payload: dict[str, Any]) -> dict[str, Any]:
    """מיישם רשימת הרשאות. ``active`` בייבוא הופך ל-``invited``: הפעלה
    קורית רק בהתחברות מאומתת, לא בהצהרה של מערכת אחרת."""
    if payload.get("version") != 1 or not isinstance(payload.get("grants"), list):
        raise GrantError(422, "פורמט ייבוא לא נתמך (נדרש version=1 ו-grants)")
    results = []
    for item in payload["grants"]:
        target = item.get("target") or {}
        status = item.get("status", INVITED)
        # תאימות Medici: booker → viewer. admin של Medici אינו ממופה אוטומטית
        # (כהרשאת ארגון הוא דו-משמעי) ולכן ייכשל כתפקיד לא חוקי — במכוון.
        if target.get("type") == "organization" and item.get("role") == "booker":
            item = {**item, "role": MEDICI_ROLE_ALIASES["booker"]}
        savepoint = db.begin_nested()
        try:
            if target.get("type") == "organization":
                if status == REVOKED:
                    revoke_org(db, actor, organization_id=int(target["id"]), email=item["email"])
                else:
                    grant_org(db, actor, organization_id=int(target["id"]),
                              email=item["email"], role=item.get("role", "viewer"))
            elif target.get("type") == "dashboard":
                if status == REVOKED:
                    revoke_dashboard(db, actor, dashboard_id=int(target["id"]), email=item["email"])
                else:
                    grant_dashboard(db, actor, dashboard_id=int(target["id"]), email=item["email"],
                                    role=item.get("role", "client_viewer"),
                                    source=str(item.get("source") or "medici")[:20])
            else:
                raise GrantError(422, "סוג יעד לא מוכר")
            savepoint.commit()
            results.append({"email": item.get("email"), "ok": True})
        except (GrantError, KeyError, TypeError, ValueError) as exc:
            savepoint.rollback()
            message = exc.message_he if isinstance(exc, GrantError) else "רשומה לא תקינה"
            results.append({"email": item.get("email"), "ok": False, "error": message})
    return {"applied": sum(1 for r in results if r["ok"]), "results": results}
