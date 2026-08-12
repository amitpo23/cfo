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


def _is_live(m: OrganizationMembership) -> bool:
    """האם החברות מקנה גישה **כרגע**."""
    if m.status != ACTIVE:
        return False
    if m.expires_at is None:
        return True
    expires = m.expires_at
    # עמודות DateTime עשויות לחזור נאיביות מ-SQLite; השוואה מול tz-aware
    # זורקת TypeError. מנרמלים ל-UTC במקום להשוות שני טיפוסים שונים.
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    return expires > _now()


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
