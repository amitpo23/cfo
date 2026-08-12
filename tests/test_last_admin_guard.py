"""שער "המנהל הנגיש האחרון" — ארבעת המסלולים.

הגרסה הראשונה ספרה חברויות `active` בלבד. זה לא מספיק: חברות יכולה
להיות `active` ובכל זאת לא לתת גישה — אם המשתמש עצמו מושבת, או אם
החברות פגה. שער שסופר כאלה **מאמין שיש מנהל כשאין**, ולכן מתיר להסיר
את האחרון שנותר.

התוצאה היא תיק שאיש אינו יכול לתפעל: אין מי שיעניק חברות, ולכן אין דרך
לחזור פנימה בלי התערבות ידנית במסד.

"מנהל נגיש" = משתמש **פעיל** + חברות `active` + **לא פגה** + תפקיד
ADMIN/SUPER_ADMIN. ארבעת המסלולים שחייבים להיחסם: revoke · suspend ·
demotion · הענקה עם תוקף שכבר פג.
"""
from datetime import datetime, timedelta, timezone

import pytest

from cfo.database import SessionLocal
from cfo.models import Organization, OrganizationMembership, User, UserRole
from cfo.services import membership_service


def _register(client, email: str):
    resp = client.post("/api/admin/auth/register", json={
        "email": email, "password": "secret123", "full_name": email,
    })
    assert resp.status_code == 201, resp.text
    d = resp.json()
    return {"user_id": d["user"]["id"], "org": d["user"]["organization_id"]}


def _add_admin(db, org_id: int, email: str, *, active_user=True,
               expires_at=None, status="active") -> int:
    u = User(email=email, password_hash="x", full_name=email,
             role=UserRole.USER, is_active=active_user, organization_id=None)
    db.add(u)
    db.flush()
    membership_service.grant(
        db, organization_id=org_id, user_id=u.id, role=UserRole.ADMIN,
        granted_by_user_id=u.id, status=status, expires_at=expires_at,
    )
    db.flush()
    return u.id


# ==================================================================== #
# ארבעת המסלולים
# ==================================================================== #
def test_cannot_revoke_the_only_reachable_admin(client):
    solo = _register(client, "guard-revoke@example.com")
    db = SessionLocal()
    try:
        with pytest.raises(ValueError):
            membership_service.revoke_checked(
                db, organization_id=solo["org"], user_id=solo["user_id"],
                acting_user_id=solo["user_id"])
    finally:
        db.rollback(); db.close()


def test_cannot_suspend_the_only_reachable_admin(client):
    solo = _register(client, "guard-suspend@example.com")
    db = SessionLocal()
    try:
        with pytest.raises(ValueError):
            membership_service.suspend_checked(
                db, organization_id=solo["org"], user_id=solo["user_id"],
                acting_user_id=solo["user_id"])
    finally:
        db.rollback(); db.close()


def test_cannot_demote_the_only_reachable_admin(client):
    solo = _register(client, "guard-demote@example.com")
    db = SessionLocal()
    try:
        with pytest.raises(ValueError):
            membership_service.grant_checked(
                db, organization_id=solo["org"], user_id=solo["user_id"],
                role=UserRole.VIEWER, acting_user_id=solo["user_id"])
    finally:
        db.rollback(); db.close()


def test_cannot_expire_the_only_reachable_admin(client):
    """המסלול שנשכח: הענקה חוזרת עם `expires_at` בעבר משאירה את החברות
    `active` — אבל היא כבר פגה, ולכן היא אינה נגישה. זו הסרה בתחפושת."""
    solo = _register(client, "guard-expire@example.com")
    past = datetime.now(timezone.utc) - timedelta(seconds=1)
    db = SessionLocal()
    try:
        with pytest.raises(ValueError):
            membership_service.grant_checked(
                db, organization_id=solo["org"], user_id=solo["user_id"],
                role=UserRole.ADMIN, acting_user_id=solo["user_id"],
                expires_at=past)
    finally:
        db.rollback(); db.close()


# ==================================================================== #
# הספירה עצמה — active אינו מספיק
# ==================================================================== #
def test_a_disabled_user_does_not_count_as_a_reachable_admin(client):
    """מנהל שני שהמשתמש שלו מושבת אינו מציל את התיק. שער שסופר את
    החברות שלו כ-active יתיר להסיר את המנהל הפעיל היחיד."""
    solo = _register(client, "guard-disabled-peer@example.com")
    db = SessionLocal()
    try:
        _add_admin(db, solo["org"], "disabled-peer@example.com",
                   active_user=False)
        db.flush()

        with pytest.raises(ValueError):
            membership_service.revoke_checked(
                db, organization_id=solo["org"], user_id=solo["user_id"],
                acting_user_id=solo["user_id"])
    finally:
        db.rollback(); db.close()


def test_an_expired_membership_does_not_count_as_a_reachable_admin(client):
    solo = _register(client, "guard-expired-peer@example.com")
    past = datetime.now(timezone.utc) - timedelta(days=1)
    db = SessionLocal()
    try:
        _add_admin(db, solo["org"], "expired-peer@example.com",
                   expires_at=past)
        db.flush()

        with pytest.raises(ValueError):
            membership_service.revoke_checked(
                db, organization_id=solo["org"], user_id=solo["user_id"],
                acting_user_id=solo["user_id"])
    finally:
        db.rollback(); db.close()


def test_a_second_reachable_admin_unblocks_every_path(client):
    """שער נגדי: עם מנהל נגיש שני, כל ארבעת המסלולים מותרים —
    אחרת השער חוסם עבודה לגיטימית."""
    solo = _register(client, "guard-two-admins@example.com")
    db = SessionLocal()
    try:
        peer = _add_admin(db, solo["org"], "reachable-peer@example.com")
        db.flush()

        membership_service.revoke_checked(
            db, organization_id=solo["org"], user_id=solo["user_id"],
            acting_user_id=peer)

        assert not membership_service.is_member(db, solo["user_id"], solo["org"])
    finally:
        db.rollback(); db.close()


# ==================================================================== #
# SUPER_ADMIN אינו תפקיד חברות
# ==================================================================== #
def test_super_admin_is_rejected_as_a_membership_role(client):
    """`SUPER_ADMIN` הוא תפקיד פלטפורמה. חברות עם התפקיד הזה הייתה
    מאפשרת למנהל ארגון להעניק סמכות-על בתוך התיק שלו."""
    person = _register(client, "no-super-membership@example.com")
    db = SessionLocal()
    try:
        with pytest.raises(ValueError):
            membership_service.grant(
                db, organization_id=person["org"], user_id=person["user_id"],
                role=UserRole.SUPER_ADMIN, granted_by_user_id=person["user_id"])
    finally:
        db.rollback(); db.close()


def test_database_constraint_rejects_a_super_admin_membership(client):
    """גם כתיבה ישירה שעוקפת את השירות נחסמת — הכלל יושב במסד."""
    import sqlalchemy.exc

    person = _register(client, "no-super-membership-db@example.com")
    db = SessionLocal()
    try:
        # ארגון **חדש**: לולא כן, ההרשמה כבר יצרה חברות לאותו צירוף
        # וה-unique constraint היה נכשל ראשון — כלומר הטסט היה עובר
        # מהסיבה הלא-נכונה בלי שאילוץ ה-CHECK קיים בכלל.
        fresh = Organization(name="ארגון לבדיקת אילוץ", is_active=True)
        db.add(fresh)
        db.flush()

        db.add(OrganizationMembership(
            organization_id=fresh.id, user_id=person["user_id"],
            role=UserRole.SUPER_ADMIN, status="active",
        ))
        with pytest.raises(sqlalchemy.exc.IntegrityError) as err:
            db.flush()

        assert "ck_membership_role_not_super_admin" in str(err.value), (
            f"נכשל מסיבה אחרת: {err.value}"
        )
    finally:
        db.rollback(); db.close()


# ==================================================================== #
# accept דורש acting_user_id
# ==================================================================== #
def test_accept_requires_an_explicit_acting_user(client):
    """`acting_user_id=None` היה מדלג על הבדיקה לגמרי — כלומר כל קורא
    שלא טרח להעביר אותו יכול היה לקבל הזמנה בשם אחר."""
    inviter = _register(client, "accept-inviter@example.com")
    invitee = _register(client, "accept-invitee@example.com")
    db = SessionLocal()
    try:
        membership_service.invite(
            db, organization_id=inviter["org"], user_id=invitee["user_id"],
            role=UserRole.ACCOUNTANT, invited_by_user_id=inviter["user_id"])
        db.flush()

        with pytest.raises(TypeError):
            membership_service.accept(
                db, organization_id=inviter["org"], user_id=invitee["user_id"])
    finally:
        db.rollback(); db.close()
