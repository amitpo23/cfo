"""חברות רב-ארגונית — מי חבר, באיזה ארגון, באיזה תפקיד.

זהו נקודת ההכרעה היחידה לשאלה "האם מותר לאדם הזה לגעת בארגון הזה".
כל שאר הקוד חייב לעבור דרך כאן ולא לשאול את `User.organization_id`
ישירות, אחרת החברות הרב-ארגונית לא תיאכף.

**הכלל המכונן:** אין בקובץ הזה פונקציה שיוצרת חברות מהתאמת מייל, דומיין
או נתון שהגיע מ-SUMIT. Google מאמת אדם; הוא אינו מוכיח בעלות על עסק.
חברות נוצרת בהזמנה מפורשת או ב-bootstrap של אדמין —
`tests/test_organization_membership.py::test_service_exposes_no_email_or_domain_based_join`
אוכף זאת מבנית, כדי שהתוספת הזו לא תחמוק בסקירה אנושית.

הפונקציה `is_member` בודקת ארבעה תנאים במצטבר: המשתמש פעיל, החברות
`active`, ולא פגה. הבדיקה נעשית **בזמן השאילתה** ולא במשימת ניקוי —
ביטול ופקיעה חייבים להיכנס לתוקף מיד, לא בהרצה הבאה של cron.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from ..models import OrganizationMembership, User, UserRole

ACTIVE = "active"
INVITED = "invited"
SUSPENDED = "suspended"
REVOKED = "revoked"

VALID_STATUSES = (INVITED, ACTIVE, SUSPENDED, REVOKED)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime) -> datetime:
    """עמודות DateTime עשויות לחזור נאיביות מ-SQLite; השוואה מול tz-aware
    זורקת TypeError. מנרמלים ל-UTC במקום להשוות שני טיפוסים שונים."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _is_live(m: OrganizationMembership) -> bool:
    """האם החברות מקנה גישה **כרגע**."""
    if m.status != ACTIVE:
        return False
    if m.expires_at is None:
        return True
    return _aware(m.expires_at) > _now()


# `SUPER_ADMIN` הוא תפקיד **פלטפורמה**, לא תפקיד בתוך ארגון. חברות עם
# התפקיד הזה הייתה מאפשרת למנהל ארגון להעניק סמכות-על בתוך התיק שלו,
# ובכך לעקוף את ההפרדה בין מפעיל מערכת לבעל עסק.
FORBIDDEN_MEMBERSHIP_ROLES = (UserRole.SUPER_ADMIN,)


def grant(
    db: Session,
    *,
    organization_id: int,
    user_id: int,
    role: UserRole,
    granted_by_user_id: int,
    status: str = ACTIVE,
    expires_at: Optional[datetime] = None,
) -> OrganizationMembership:
    """יוצר או מעדכן חברות. הענקה חוזרת מעדכנת ואינה מכפילה.

    `granted_by_user_id` נשמר תמיד: חברות בלי מי שהעניק אותה היא חברות
    בלי אחריות.
    """
    if status not in VALID_STATUSES:
        raise ValueError(f"סטטוס חברות לא מוכר: {status!r}")
    if role in FORBIDDEN_MEMBERSHIP_ROLES:
        raise ValueError(
            f"{role.value} הוא תפקיד פלטפורמה ואינו תפקיד חברות בארגון"
        )

    existing = (
        db.query(OrganizationMembership)
        .filter(
            OrganizationMembership.user_id == user_id,
            OrganizationMembership.organization_id == organization_id,
        )
        .first()
    )
    if existing is not None:
        existing.role = role
        existing.status = status
        existing.expires_at = expires_at
        existing.invited_by_user_id = granted_by_user_id
        existing.revoked_at = None
        existing.revoked_by_user_id = None
        if status == ACTIVE and existing.verified_at is None:
            existing.verified_at = _now()
        db.flush()
        return existing

    m = OrganizationMembership(
        organization_id=organization_id,
        user_id=user_id,
        role=role,
        status=status,
        invited_by_user_id=granted_by_user_id,
        expires_at=expires_at,
        verified_at=_now() if status == ACTIVE else None,
    )
    db.add(m)
    db.flush()
    return m


def revoke(
    db: Session, *, organization_id: int, user_id: int, revoked_by_user_id: int,
) -> Optional[OrganizationMembership]:
    """מבטל חברות. הביטול נכנס לתוקף מיד — `is_member` בודק בזמן השאילתה."""
    m = (
        db.query(OrganizationMembership)
        .filter(
            OrganizationMembership.user_id == user_id,
            OrganizationMembership.organization_id == organization_id,
        )
        .first()
    )
    if m is None:
        return None
    m.status = REVOKED
    m.revoked_at = _now()
    m.revoked_by_user_id = revoked_by_user_id
    db.flush()
    return m


def suspend(
    db: Session, *, organization_id: int, user_id: int, suspended_by_user_id: int,
) -> Optional[OrganizationMembership]:
    m = (
        db.query(OrganizationMembership)
        .filter(
            OrganizationMembership.user_id == user_id,
            OrganizationMembership.organization_id == organization_id,
        )
        .first()
    )
    if m is None:
        return None
    m.status = SUSPENDED
    m.revoked_by_user_id = suspended_by_user_id
    db.flush()
    return m


def invite(
    db: Session,
    *,
    organization_id: int,
    user_id: int,
    role: UserRole,
    invited_by_user_id: int,
    expires_at: Optional[datetime] = None,
) -> OrganizationMembership:
    """הזמנה — `invited`, לא `active`.

    ההפרדה מכוונת: מי שהוזמן טרם קיבל. הענקת גישה ברגע ההזמנה הופכת כל
    הקלדת מייל שגויה לגישה לכספים של לקוח.
    """
    return grant(
        db, organization_id=organization_id, user_id=user_id, role=role,
        granted_by_user_id=invited_by_user_id, status=INVITED,
        expires_at=expires_at,
    )


def accept(
    db: Session,
    *,
    organization_id: int,
    user_id: int,
    acting_user_id: int,
) -> OrganizationMembership:
    """קבלת הזמנה. **רק המוזמן עצמו** — קבלה בשם אחר היא הענקה עצמית.

    `acting_user_id` הוא פרמטר **חובה**. בגרסה הקודמת הוא היה
    `Optional` עם ברירת מחדל `None`, ואז הבדיקה דולגה לגמרי — כלומר כל
    קורא שלא טרח להעביר אותו יכול היה לקבל הזמנה בשם מישהו אחר. שער
    שאפשר לדלג עליו בהשמטת ארגומנט אינו שער.
    """
    if acting_user_id != user_id:
        raise PermissionError(
            "רק המוזמן עצמו יכול לקבל את ההזמנה"
        )
    m = _find(db, organization_id=organization_id, user_id=user_id)
    if m is None or m.status != INVITED:
        raise ValueError("אין הזמנה ממתינה לצירוף הזה")
    m.status = ACTIVE
    m.verified_at = _now()
    db.flush()
    return m


def _find(
    db: Session, *, organization_id: int, user_id: int,
) -> Optional[OrganizationMembership]:
    return (
        db.query(OrganizationMembership)
        .filter(
            OrganizationMembership.user_id == user_id,
            OrganizationMembership.organization_id == organization_id,
        )
        .first()
    )


def _assert_admin_of(db: Session, *, organization_id: int, acting_user_id: int) -> None:
    """הפעולה מותרת רק למנהל **בארגון הזה**.

    ADMIN בארגון א' אינו רשאי להעניק חברות בארגון ב'. `User.role`
    הגלובלי אינו נבדק כאן במכוון: הוא שדה פלטפורמה ואינו הרשאה ארגונית.
    """
    role = role_in(db, acting_user_id, organization_id)
    if role not in (UserRole.ADMIN, UserRole.SUPER_ADMIN):
        raise PermissionError(
            "נדרשת הרשאת ניהול בארגון הזה כדי לשנות חברות"
        )


def _reachable_admin_ids(db: Session, organization_id: int) -> set[int]:
    """מנהלים ש**באמת אפשר להיכנס איתם** לתיק.

    לא מספיק שהחברות `active`: אם המשתמש עצמו מושבת, או אם החברות פגה,
    אין דרך להשתמש בה. שער שסופר כאלה מאמין שיש מנהל כשאין — ולכן מתיר
    להסיר את האחרון שנותר, ומשאיר תיק שאיש אינו יכול לתפעל.
    """
    rows = (
        db.query(OrganizationMembership)
        .filter(
            OrganizationMembership.organization_id == organization_id,
            OrganizationMembership.status == ACTIVE,
            OrganizationMembership.role.in_([UserRole.ADMIN, UserRole.SUPER_ADMIN]),
        )
        .all()
    )
    return {
        m.user_id for m in rows
        if _is_live(m) and _user_is_active(db, m.user_id)
    }


def _assert_not_last_admin(db: Session, *, organization_id: int, user_id: int) -> None:
    """תיק בלי מנהל נגיש הוא תיק שאיש אינו יכול לתפעל — כולל להחזיר
    לעצמו גישה. חוסם ביטול, השעיה, הורדה בדרגה ופקיעה כאחד."""
    admins = _reachable_admin_ids(db, organization_id)
    if admins == {user_id}:
        raise ValueError(
            "אי-אפשר להסיר את המנהל הנגיש האחרון בארגון"
        )


def _audit(
    db: Session, *, organization_id: int, acting_user_id: int, action: str,
    target_user_id: int, details: dict,
) -> None:
    from ..models import AuditLog

    db.add(AuditLog(
        user_id=acting_user_id,
        organization_id=organization_id,
        action=action,
        entity_type="OrganizationMembership",
        entity_id=target_user_id,
        details=details,
    ))


def grant_checked(
    db: Session,
    *,
    organization_id: int,
    user_id: int,
    role: UserRole,
    acting_user_id: int,
    status: str = ACTIVE,
    expires_at: Optional[datetime] = None,
) -> OrganizationMembership:
    """הענקה/שינוי תפקיד עם בדיקת סמכות ורישום ביקורת.

    שינוי תפקיד הוא שינוי **חברות בארגון מסוים** — לא `User.role`.
    """
    _assert_admin_of(db, organization_id=organization_id,
                     acting_user_id=acting_user_id)

    # שלושה מסלולים שכולם מסירים את המנהל בפועל:
    #   · הורדה בדרגה  · השעיה/הזמנה במקום פעיל  · תוקף שכבר פג
    # השלישי הוא המסלול שנשכח: החברות נשארת `active` אבל אינה נגישה,
    # כלומר הסרה בתחפושת.
    expiry_kills = expires_at is not None and _aware(expires_at) <= _now()
    removes_admin = (
        role not in (UserRole.ADMIN, UserRole.SUPER_ADMIN)
        or status != ACTIVE
        or expiry_kills
    )
    if removes_admin:
        existing = _find(db, organization_id=organization_id, user_id=user_id)
        if existing is not None and existing.role in (UserRole.ADMIN, UserRole.SUPER_ADMIN):
            _assert_not_last_admin(db, organization_id=organization_id,
                                   user_id=user_id)
    m = grant(
        db, organization_id=organization_id, user_id=user_id, role=role,
        granted_by_user_id=acting_user_id, status=status, expires_at=expires_at,
    )
    _audit(db, organization_id=organization_id, acting_user_id=acting_user_id,
           action="MEMBERSHIP_GRANT", target_user_id=user_id,
           details={"role": role.value, "status": status})
    return m


def revoke_checked(
    db: Session, *, organization_id: int, user_id: int, acting_user_id: int,
) -> OrganizationMembership:
    _assert_admin_of(db, organization_id=organization_id,
                     acting_user_id=acting_user_id)
    _assert_not_last_admin(db, organization_id=organization_id, user_id=user_id)
    m = revoke(db, organization_id=organization_id, user_id=user_id,
               revoked_by_user_id=acting_user_id)
    if m is None:
        raise ValueError("אין חברות לביטול")
    _audit(db, organization_id=organization_id, acting_user_id=acting_user_id,
           action="MEMBERSHIP_REVOKE", target_user_id=user_id, details={})
    return m


def suspend_checked(
    db: Session, *, organization_id: int, user_id: int, acting_user_id: int,
) -> OrganizationMembership:
    _assert_admin_of(db, organization_id=organization_id,
                     acting_user_id=acting_user_id)
    _assert_not_last_admin(db, organization_id=organization_id, user_id=user_id)
    m = suspend(db, organization_id=organization_id, user_id=user_id,
                suspended_by_user_id=acting_user_id)
    if m is None:
        raise ValueError("אין חברות להשעיה")
    _audit(db, organization_id=organization_id, acting_user_id=acting_user_id,
           action="MEMBERSHIP_SUSPEND", target_user_id=user_id, details={})
    return m


def memberships_for(db: Session, user_id: int) -> list[OrganizationMembership]:
    """כל רשומות החברות של אדם, בכל סטטוס. לתצוגת ניהול."""
    return (
        db.query(OrganizationMembership)
        .filter(OrganizationMembership.user_id == user_id)
        .order_by(OrganizationMembership.organization_id.asc())
        .all()
    )


def _user_is_active(db: Session, user_id: int) -> bool:
    user = db.query(User).filter(User.id == user_id).first()
    return bool(user and user.is_active)


def is_member(db: Session, user_id: int, organization_id: int) -> bool:
    """האם לאדם יש גישה פעילה לארגון **כרגע**.

    השעיית האדם עצמו (`users.is_active=False`) גוברת על כל חברות פעילה:
    חסימת חשבון חייבת לחסום את כל התיקים בבת אחת, אחרת ביטול גישה הופך
    לפעולה פר-ארגון שקל לשכוח.
    """
    if not _user_is_active(db, user_id):
        return False
    m = (
        db.query(OrganizationMembership)
        .filter(
            OrganizationMembership.user_id == user_id,
            OrganizationMembership.organization_id == organization_id,
        )
        .first()
    )
    return m is not None and _is_live(m)


def role_in(db: Session, user_id: int, organization_id: int) -> Optional[UserRole]:
    """התפקיד של האדם בארגון, או `None` אם אין לו גישה פעילה.

    honest-null: אין נפילה ל-`UserRole.USER` כברירת מחדל. "אין תפקיד"
    ו"תפקיד הכי נמוך" הם שתי תשובות שונות, וערבובן היה נותן גישה למי
    שאינו חבר.
    """
    if not _user_is_active(db, user_id):
        return None
    m = (
        db.query(OrganizationMembership)
        .filter(
            OrganizationMembership.user_id == user_id,
            OrganizationMembership.organization_id == organization_id,
        )
        .first()
    )
    if m is None or not _is_live(m):
        return None
    return m.role


def active_organization_ids(db: Session, user_id: int) -> list[int]:
    """מזהי הארגונים שהאדם חבר פעיל בהם, ממוינים."""
    if not _user_is_active(db, user_id):
        return []
    rows = (
        db.query(OrganizationMembership)
        .filter(
            OrganizationMembership.user_id == user_id,
            OrganizationMembership.status == ACTIVE,
        )
        .order_by(OrganizationMembership.organization_id.asc())
        .all()
    )
    return [m.organization_id for m in rows if _is_live(m)]
