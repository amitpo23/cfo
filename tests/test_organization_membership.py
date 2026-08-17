"""חברות רב-ארגונית — אדם אחד, כמה עסקים, תפקיד שונה בכל אחד.

עד 11/08/2026 `User.organization_id` היה FK יחיד: אדם שייך לארגון אחד
ותו לא. זה שגוי במציאות שהמערכת משרתת — בעל עסק יכול להיות בעלים בחברה
שלו ו-viewer בחברה של שותף, ומנהלת חשבונות עובדת על עשרות תיקים.

`OrganizationMembership` מפריד בין **מי האדם** (`users`, נשאר) לבין **במה
הוא חבר ובאיזה תפקיד** (רשומה פר ארגון).

**הכלל המרכזי:** חברות נוצרת בהזמנה או ב-bootstrap מפורש — לעולם לא
מהתאמת מייל, דומיין או נתון שהגיע מ-SUMIT. Google מאמת **אדם**; הוא אינו
מוכיח בעלות על עסק. ההפרדה הזו היא כל ההבדל בין "התחברת" לבין "מותר לך
לראות את הכספים של החברה הזו".

`users.organization_id` **אינו נמחק**: הוא מקור ה-backfill ונשאר כ-fallback
לקריאה עד שכל הקוראים יעברו. מיגרציה שמנחשת בעלות היא בדיוק מה שאסור.
"""
import pytest
from datetime import datetime, timedelta, timezone

from cfo.database import SessionLocal
from cfo.models import Organization, User, UserRole
from cfo.services import membership_service


@pytest.fixture
def db(client):
    """`client` הוא מי שיוצר את הסכימה ב-SQLite המקומי — בלעדיו אין טבלאות."""
    s = SessionLocal()
    try:
        yield s
    finally:
        s.rollback()
        s.close()


def _org(db, name: str) -> Organization:
    o = Organization(name=name, is_active=True)
    db.add(o)
    db.flush()
    return o


def _user(db, email: str) -> User:
    u = User(
        email=email, password_hash="x", full_name=email,
        role=UserRole.USER, is_active=True, organization_id=None,
    )
    db.add(u)
    db.flush()
    return u


# --------------------------------------------------------------------- #
# הליבה — אדם אחד, שני ארגונים, תפקידים שונים
# --------------------------------------------------------------------- #
def test_one_person_two_organizations_with_different_roles(db):
    person = _user(db, "dual@example.com")
    alpha, beta = _org(db, "אלפא"), _org(db, "בטא")

    membership_service.grant(db, organization_id=alpha.id, user_id=person.id,
                             role=UserRole.ADMIN, granted_by_user_id=person.id)
    membership_service.grant(db, organization_id=beta.id, user_id=person.id,
                             role=UserRole.VIEWER, granted_by_user_id=person.id)

    assert membership_service.role_in(db, person.id, alpha.id) == UserRole.ADMIN
    assert membership_service.role_in(db, person.id, beta.id) == UserRole.VIEWER


def test_active_organization_ids_lists_exactly_the_memberships(db):
    person = _user(db, "lister@example.com")
    a, b, c = _org(db, "א"), _org(db, "ב"), _org(db, "ג")
    membership_service.grant(db, organization_id=a.id, user_id=person.id,
                             role=UserRole.USER, granted_by_user_id=person.id)
    membership_service.grant(db, organization_id=b.id, user_id=person.id,
                             role=UserRole.USER, granted_by_user_id=person.id)

    ids = membership_service.active_organization_ids(db, person.id)

    assert set(ids) == {a.id, b.id}
    assert c.id not in ids


# --------------------------------------------------------------------- #
# חסימה — לא-חבר, מושעה, מבוטל, פג-תוקף
# --------------------------------------------------------------------- #
def test_non_member_has_no_role(db):
    stranger = _user(db, "stranger@example.com")
    org = _org(db, "לא שלו")

    assert membership_service.role_in(db, stranger.id, org.id) is None
    assert not membership_service.is_member(db, stranger.id, org.id)


@pytest.mark.parametrize("status", ["invited", "suspended", "revoked"])
def test_only_active_status_grants_access(db, status):
    """`invited` אינו גישה — ההזמנה טרם התקבלה."""
    person = _user(db, f"status-{status}@example.com")
    org = _org(db, f"ארגון {status}")
    m = membership_service.grant(db, organization_id=org.id, user_id=person.id,
                                 role=UserRole.ADMIN, granted_by_user_id=person.id)
    m.status = status
    db.flush()

    assert membership_service.role_in(db, person.id, org.id) is None
    assert not membership_service.is_member(db, person.id, org.id)


def test_expired_membership_is_blocked_immediately(db):
    """גישה זמנית שפגה נחסמת בלי משימת ניקוי — הבדיקה היא בזמן השאילתה."""
    person = _user(db, "expired@example.com")
    org = _org(db, "תוקף")
    m = membership_service.grant(db, organization_id=org.id, user_id=person.id,
                                 role=UserRole.ADMIN, granted_by_user_id=person.id)
    m.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.flush()

    assert not membership_service.is_member(db, person.id, org.id)


def test_future_expiry_still_grants_access(db):
    person = _user(db, "not-yet-expired@example.com")
    org = _org(db, "תוקף עתידי")
    m = membership_service.grant(db, organization_id=org.id, user_id=person.id,
                                 role=UserRole.ADMIN, granted_by_user_id=person.id)
    m.expires_at = datetime.now(timezone.utc) + timedelta(days=1)
    db.flush()

    assert membership_service.is_member(db, person.id, org.id)


def test_inactive_user_is_blocked_even_with_active_membership(db):
    """השעיית אדם גוברת על כל חברות פעילה שיש לו."""
    person = _user(db, "suspended-person@example.com")
    org = _org(db, "ארגון")
    membership_service.grant(db, organization_id=org.id, user_id=person.id,
                             role=UserRole.ADMIN, granted_by_user_id=person.id)
    person.is_active = False
    db.flush()

    assert not membership_service.is_member(db, person.id, org.id)


def test_revocation_takes_effect_immediately(db):
    person = _user(db, "revoked-now@example.com")
    org = _org(db, "ביטול")
    membership_service.grant(db, organization_id=org.id, user_id=person.id,
                             role=UserRole.ADMIN, granted_by_user_id=person.id)
    assert membership_service.is_member(db, person.id, org.id)

    membership_service.revoke(db, organization_id=org.id, user_id=person.id,
                              revoked_by_user_id=person.id)

    assert not membership_service.is_member(db, person.id, org.id)


# --------------------------------------------------------------------- #
# אין הצטרפות לפי מייל / SUMIT / דומיין
# --------------------------------------------------------------------- #
def test_membership_is_never_created_from_a_matching_email(db):
    """הכלל המכונן: Google מאמת אדם, לא בעלות על עסק. אימייל תואם —
    גם כשהוא בדיוק ה-email של הארגון — אינו מקנה גישה."""
    org = _org(db, "עסק עם מייל")
    org.email = "boss@company.co.il"
    db.flush()
    person = _user(db, "boss@company.co.il")

    assert not membership_service.is_member(db, person.id, org.id)
    assert membership_service.active_organization_ids(db, person.id) == []


def test_service_exposes_no_email_or_domain_based_join():
    """שער מבני: אם מישהו יוסיף פונקציית הצטרפות-לפי-מייל, זה ייתפס
    כאן ולא בסקירה אנושית."""
    forbidden = [
        name for name in dir(membership_service)
        if any(t in name.lower() for t in ("by_email", "by_domain", "from_sumit", "autojoin", "auto_join"))
    ]
    assert not forbidden, f"נתיב הצטרפות אוטומטי נחשף: {forbidden}"


# --------------------------------------------------------------------- #
# יושרה — כפילות, זליגה
# --------------------------------------------------------------------- #
def test_regranting_updates_instead_of_duplicating(db):
    person = _user(db, "regrant@example.com")
    org = _org(db, "כפילות")
    membership_service.grant(db, organization_id=org.id, user_id=person.id,
                             role=UserRole.VIEWER, granted_by_user_id=person.id)
    membership_service.grant(db, organization_id=org.id, user_id=person.id,
                             role=UserRole.ADMIN, granted_by_user_id=person.id)

    assert membership_service.role_in(db, person.id, org.id) == UserRole.ADMIN
    assert len(membership_service.memberships_for(db, person.id)) == 1


def test_membership_lookup_never_leaks_another_persons_organizations(db):
    """זליגה חוצת-ארגונים: שאילתה על אדם אחד לא מחזירה ארגונים של אחר."""
    a, b = _user(db, "person-a@example.com"), _user(db, "person-b@example.com")
    org_a, org_b = _org(db, "של א"), _org(db, "של ב")
    membership_service.grant(db, organization_id=org_a.id, user_id=a.id,
                             role=UserRole.ADMIN, granted_by_user_id=a.id)
    membership_service.grant(db, organization_id=org_b.id, user_id=b.id,
                             role=UserRole.ADMIN, granted_by_user_id=b.id)

    assert membership_service.active_organization_ids(db, a.id) == [org_a.id]
    assert membership_service.active_organization_ids(db, b.id) == [org_b.id]
