"""
Authentication and authorization dependencies
"""
from dataclasses import dataclass

from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Optional, Generator
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db_session, SessionLocal
from ..models import Organization, User, UserRole
from ..auth import decode_access_token
from ..auth import get_password_hash
from ..services import membership_service

security = HTTPBearer(auto_error=False)


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
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
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
    missing_credentials_exception = HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )
    invalid_credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if credentials is None:
        if settings.auth_bypass_enabled:
            return _get_or_create_auth_bypass_user(db)
        raise missing_credentials_exception

    token = credentials.credentials
    payload = decode_access_token(token)
    
    if payload is None:
        if settings.auth_bypass_enabled:
            return _get_or_create_auth_bypass_user(db)
        raise invalid_credentials_exception
    
    # "sub" is stored as a string in the JWT (python-jose requirement);
    # convert back to the integer primary key before querying.
    try:
        user_id = int(payload.get("sub"))
    except (TypeError, ValueError):
        if settings.auth_bypass_enabled:
            return _get_or_create_auth_bypass_user(db)
        raise invalid_credentials_exception

    # טוקן שבוטל ב-logout (denylist לפי jti) נדחה — fail-closed, גם תחת
    # auth_bypass: ביטול הוא פעולת אבטחה מפורשת ואין לעקוף אותה בשקט.
    # שאילתה ממוקדת על אינדקס unique; טוקנים ישנים בלי jti עוברים (תאימות).
    token_jti = payload.get("jti")
    if token_jti:
        from ..models import RevokedToken

        revoked = (
            db.query(RevokedToken.id)
            .filter(RevokedToken.jti == token_jti)
            .first()
        )
        if revoked is not None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="הטוקן בוטל (logout) — יש להתחבר מחדש",
                headers={"WWW-Authenticate": "Bearer"},
            )

    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        if settings.auth_bypass_enabled:
            return _get_or_create_auth_bypass_user(db)
        raise invalid_credentials_exception
    
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is disabled"
        )
    
    return user


def _get_or_create_auth_bypass_user(db: Session) -> User:
    """Return a deterministic development super-admin user.

    This is intentionally controlled by `AUTH_BYPASS_ENABLED`; it lets local QA
    use the whole system without login while keeping org-scoping behavior intact.
    """
    user = db.query(User).filter(User.role == UserRole.SUPER_ADMIN, User.is_active == True).first()
    if user:
        return user

    org = db.query(Organization).order_by(Organization.id.asc()).first()
    if not org:
        org = Organization(name="Rezef Dev", is_active=True)
        db.add(org)
        db.flush()

    user = db.query(User).filter(User.email == "dev@rezef.local").first()
    if user:
        user.role = UserRole.SUPER_ADMIN
        user.is_active = True
        user.organization_id = None
    else:
        user = User(
            email="dev@rezef.local",
            password_hash=get_password_hash("auth-bypass-disabled-password"),
            full_name="Rezef Dev Super Admin",
            role=UserRole.SUPER_ADMIN,
            organization_id=None,
            is_active=True,
        )
        db.add(user)
    db.commit()
    db.refresh(user)
    return user


ACTIVE_ORG_HEADER = "X-Active-Org-Id"


def _resolve_super_admin_active_org(request: Request, current_user: User) -> Optional[int]:
    """Resolve a SUPER_ADMIN's chosen active organization from the request header.

    Returns the validated target org id, or None when no override applies. The
    override is the single chokepoint that lets one operator act inside any
    client org; it is therefore honored ONLY for a confirmed SUPER_ADMIN (role
    read from the DB via get_current_user, never a token claim). For any other
    role the header is silently ignored — sending it must never widen scope.

    Mutating requests (anything other than GET/HEAD/OPTIONS) under an active
    override are recorded to AuditLog so writes/sync done while impersonating an
    org leave an attributable trail.
    """
    if request is None or current_user.role != UserRole.SUPER_ADMIN:
        return None
    raw = request.headers.get(ACTIVE_ORG_HEADER)
    if not raw:
        return None
    try:
        target = int(raw)
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid {ACTIVE_ORG_HEADER} header",
        )

    db = SessionLocal()
    try:
        from ..models import Organization, AuditLog

        org = db.query(Organization).filter(Organization.id == target).first()
        if org is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Organization not found",
            )
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            db.add(AuditLog(
                user_id=current_user.id,
                organization_id=target,
                action="IMPERSONATE",
                entity_type="Organization",
                entity_id=target,
                details={"method": request.method, "path": request.url.path},
            ))
            db.commit()
    finally:
        db.close()
    return target


def _selectable_organizations(db: Session) -> list[dict]:
    """הארגונים שסופר-אדמין יכול לבחור מהם.

    נקרא **רק** במסלול הסירוב לסופר-אדמין. זו רשימה חוצת-ארגונים, ולכן
    אסור שתגיע למשתמש אחר — הטסט
    `test_non_super_without_org_is_still_refused` שומר על כך.
    """
    rows = (
        db.query(Organization.id, Organization.name)
        .filter(Organization.is_active.is_(True))
        .order_by(Organization.id.asc())
        .all()
    )
    return [{"id": r.id, "name": r.name} for r in rows]


def _organizations_by_ids(db: Session, org_ids: list[int]) -> list[dict]:
    """שמות ארגונים לרשימת בחירה, מצומצמת למזהים שהותרו כבר.

    נפרד מ-`_selectable_organizations` במכוון: זו מחזירה **רק** את מה
    שנשלח אליה, ולכן אינה יכולה להדליף ארגון שהמשתמש אינו חבר בו — גם
    אם ייקרא בטעות ממקום אחר.
    """
    if not org_ids:
        return []
    rows = (
        db.query(Organization.id, Organization.name)
        .filter(Organization.id.in_(org_ids))
        .order_by(Organization.id.asc())
        .all()
    )
    return [{"id": r.id, "name": r.name} for r in rows]


def _requested_org(request: Optional[Request]) -> Optional[int]:
    """הארגון שהלקוח **ביקש** בכותרת — בקשה בלבד, לא היתר.

    ההיתר נבדק בנפרד מול `organization_memberships` בכל בקשה מחדש.
    """
    if request is None:
        return None
    raw = request.headers.get(ACTIVE_ORG_HEADER)
    if not raw:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid {ACTIVE_ORG_HEADER} header",
        )


@dataclass
class OrganizationAccessContext:
    """כל מה שנדרש כדי להכריע גישה ארגונית — בהקשר אחד.

    ההכרעה הייתה מפוזרת בין `get_current_org_id` (איזה ארגון),
    `require_admin` (`User.role`) ו-`users.organization_id` (fallback שקט).
    שלוש שכבות שאינן מדברות זו עם זו, ולכן אפשר היה לעבור ביניהן.

    `effective_role` הוא התפקיד **בארגון הזה**, לא בפלטפורמה. אדם יכול
    להיות ADMIN בעסק שלו ו-VIEWER בעסק של שותף; `User.role` אינו רשאי
    להקנות לו כתיבה בעסק השני.

    `selection_source` הוא ראיית ביקורת: "מאיפה הגיע הארגון" הוא בדיוק
    מה שצריך לדעת אחרי כתיבה לתיק הלא-נכון.
    """
    user: User
    organization_id: int
    membership: Optional["OrganizationMembership"]
    effective_role: UserRole
    is_super_admin: bool
    selection_source: str
    channel: str


CHANNEL_HEADER = "X-Rezef-Channel"

# מקורות בחירה אפשריים
SOURCE_SUPER_ADMIN_HEADER = "super_admin_header"
SOURCE_SUPER_ADMIN_OWN = "super_admin_own_org"
SOURCE_HEADER = "explicit_header"
SOURCE_SOLE = "sole_membership"


def _needs_selection(detail_msg: str, organizations: list[dict]) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "error": "active_organization_required",
            "message_he": detail_msg,
            "header": ACTIVE_ORG_HEADER,
            "organizations": organizations,
        },
    )


def _forbidden(reason: str) -> HTTPException:
    """403 בלי שם ארגון.

    סירוב אינו מקום לפרסם את קטלוג הלקוחות: מי שקיבל שם ארגון שאינו שלו
    למד משהו שאסור היה לו לדעת.
    """
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=reason)


def _assert_org_usable(db: Session, organization_id: int) -> None:
    """ארגון מושבת חוסם תמיד — גם לסופר-אדמין וגם לחבר פעיל."""
    org = (
        db.query(Organization)
        .filter(Organization.id == organization_id)
        .first()
    )
    if org is None:
        raise _forbidden("organization_not_found")
    if org.is_active is False:
        raise _forbidden("organization_inactive")


async def resolve_access_context(
    current_user: User,
    request: Optional[Request],
    db: Session,
) -> OrganizationAccessContext:
    """נקודת ההכרעה היחידה. נבנית מחדש בכל בקשה.

    אין cache ואין הסתמכות על claim בטוקן: ביטול חברות, השעיה, פקיעה
    והשבתת ארגון חייבים להיכנס לתוקף בבקשה הבאה, לא אחרי logout.
    """
    from ..models import OrganizationMembership  # noqa: F401  (typing only)

    channel = (
        request.headers.get(CHANNEL_HEADER, "web") if request is not None else "web"
    )
    requested = _requested_org(request)
    is_super = current_user.role == UserRole.SUPER_ADMIN

    # --- SUPER_ADMIN: מפעיל מערכת, בוחר ארגון מפורשות ------------------ #
    if is_super:
        target = _resolve_super_admin_active_org(request, current_user)
        if target is not None:
            _assert_org_usable(db, target)
            return OrganizationAccessContext(
                user=current_user, organization_id=target, membership=None,
                effective_role=UserRole.SUPER_ADMIN, is_super_admin=True,
                selection_source=SOURCE_SUPER_ADMIN_HEADER, channel=channel,
            )
        # **אין מסלול שני.** סופר-אדמין עם `organization_id` נכנס קודם
        # לארגון הבית שלו בלי כותרת — שתי התנהגויות שונות לאותו תפקיד,
        # תלוי בשדה שהוא שריד היסטורי. זה החזיר בדלת האחורית בדיוק את
        # הבעיה שנסגרה: פעולה רוחבית שנוחתת בתיק שאיש לא בחר בו במפורש.
        #
        # מפעיל מערכת אינו "שייך" לתיק — הוא **נכנס** לתיק, וזו הכרעה
        # שצריכה להיות מפורשת בכל סשן. (החלטת ברירת מחדל 11/08/2026.)
        raise _needs_selection(
            f"יש לבחור ארגון פעיל. שלח את הכותרת {ACTIVE_ORG_HEADER} "
            "עם מזהה הארגון.",
            _selectable_organizations(db),
        )

    # --- משתמש רגיל: החברות היא מקור הסמכות -------------------------- #
    memberships = membership_service.memberships_for(db, current_user.id)
    live = {
        m.organization_id: m
        for m in memberships
        if membership_service.is_member(db, current_user.id, m.organization_id)
    }

    if requested is not None:
        # כותרת מפורשת לעולם אינה מוחלפת בשקט: מי שביקש ארגון א' וקיבל
        # את ב' קורא תיק אחר בלי לדעת.
        m = live.get(requested)
        if m is None:
            raise _forbidden("no_active_membership_for_requested_organization")
        _assert_org_usable(db, requested)
        return OrganizationAccessContext(
            user=current_user, organization_id=requested, membership=m,
            effective_role=m.role, is_super_admin=False,
            selection_source=SOURCE_HEADER, channel=channel,
        )

    if len(live) == 1:
        org_id, m = next(iter(live.items()))
        _assert_org_usable(db, org_id)
        return OrganizationAccessContext(
            user=current_user, organization_id=org_id, membership=m,
            effective_role=m.role, is_super_admin=False,
            selection_source=SOURCE_SOLE, channel=channel,
        )

    if len(live) > 1:
        raise _needs_selection(
            "יש לך גישה לכמה ארגונים. בחר את הארגון הפעיל ושלח אותו "
            f"בכותרת {ACTIVE_ORG_HEADER}.",
            _organizations_by_ids(db, sorted(live)),
        )

    # אין חברות פעילה. **רשומה קיימת שאינה פעילה היא סירוב מפורש**, לא
    # היעדר מידע: מי שבוטל או הושעה אינו רשאי ליפול חזרה לעמודה הישנה.
    # בלי ההבחנה הזו, `bb5365c` (חברות `suspended` למשתמש מושבת) היה
    # חסר משמעות — הפעלה מחדש הייתה מחזירה גישה בשקט.
    if memberships:
        raise _forbidden("membership_not_active")

    # אין fallback ל-users.organization_id. המיגרציה מבצעת backfill מאומת;
    # אחרי כן העמודה הישנה היא מטא־דאטה בלבד, לא מקור סמכות. השארת fallback
    # הייתה מאפשרת לזהות שלא קיבלה חברות לעקוף את כל מחזור החיים החדש.
    raise _forbidden("no_organization_membership")


async def get_access_context(
    current_user: User = Depends(get_current_user),
    request: Request = None,
    db: Session = Depends(get_db_session),
) -> OrganizationAccessContext:
    ctx = await resolve_access_context(current_user, request, db)
    # שער הכתיבה של viewer נשען על `effective_role` — התפקיד בארגון הזה,
    # לא בפלטפורמה. אדם עם `User.role=ADMIN` שהוא VIEWER בעסק הנוכחי
    # נחסם כאן; אדם עם `User.role=VIEWER` שהוא ADMIN בעסק שלו — לא.
    if (
        request is not None
        and ctx.effective_role == UserRole.VIEWER
        and request.method not in ("GET", "HEAD", "OPTIONS")
    ):
        raise _forbidden("Viewer role is read-only")
    return ctx


async def get_current_org_id(
    ctx: OrganizationAccessContext = Depends(get_access_context),
) -> int:
    """מזהה הארגון הפעיל — עטיפה דקה מעל ההקשר.

    נשארת כדי ש-400+ מסלולים קיימים לא ישתנו; ההכרעה עצמה עברה כולה ל-
    `resolve_access_context`.
    """
    return ctx.organization_id


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
    async def role_checker(
        ctx: OrganizationAccessContext = Depends(get_access_context),
    ) -> User:
        # `effective_role` ולא `User.role`: התפקיד בארגון הפעיל הוא הקובע.
        # אדם יכול להיות ADMIN בעסק שלו ו-VIEWER בעסק של שותף.
        if ctx.effective_role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied. Required roles: {[r.value for r in allowed_roles]}"
            )
        return ctx.user

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
    ctx: OrganizationAccessContext = Depends(get_access_context),
) -> User:
    """מנהל **בארגון הפעיל**, או מנהל-על.

    נשען על `effective_role`. `User.role=ADMIN` אינו מקנה ניהול בעסק
    שבו האדם הוא VIEWER — זה בדיוק הפער שהמודל הרב-ארגוני פותח.
    """
    current_user = ctx.user
    if ctx.effective_role not in [UserRole.SUPER_ADMIN, UserRole.ADMIN]:
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

    from ..services.sumit_request_budget import SumitRequestLimiter
    return SumitIntegration(
        api_key=api_key,
        company_id=company_id,
        request_limiter=SumitRequestLimiter(org_id),
    )


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
    from ..services.sumit_request_budget import SumitRequestLimiter
    return SumitIntegration(
        api_key=api_key,
        company_id=company_id,
        request_limiter=SumitRequestLimiter(org_id),
    )


def require_admin(ctx: OrganizationAccessContext = Depends(get_access_context)):
    """מנהל **בארגון הפעיל** (44 מסלולים תלויים בזה).

    נשען על `effective_role` ולא על `User.role`: תפקיד גלובלי אינו מקנה
    ניהול בעסק של מישהו אחר.
    """
    current_user = ctx.user
    if ctx.effective_role not in (UserRole.ADMIN, UserRole.SUPER_ADMIN):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    return current_user
