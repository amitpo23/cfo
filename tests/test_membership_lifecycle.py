"""מחזור חיי חברות — יצירה, הזמנה, ביטול, השעיה.

אחרי שלב 1 `OrganizationAccessContext` דורש חברות פעילה. זה חושף פער
מיידי: **הרשמה עצמית יוצרת ארגון אבל לא יוצרת חברות**, ולכן כל משתמש
חדש שורד רק דרך מסלול התאימות `legacy_column`. מסלול שאמור להיעלם אינו
יכול להיות הדרך שבה משתמשים חדשים נכנסים.

הכללים שנבדקים כאן:

- הרשמה שיוצרת ארגון יוצרת באותה טרנזקציה חברות `ADMIN`. אם אחד משניהם
  נכשל — שניהם מתבטלים. ארגון בלי חברות הוא תיק שאיש אינו יכול לפתוח.
- הזמנה יוצרת `invited`, לא `active`. קבלה היא פעולה של המוזמן.
- שינוי תפקיד הוא שינוי **חברות בארגון מסוים**, לא `User.role`.
- ביטול/השעיה/הענקה דורשים ניהול **באותו ארגון** ונרשמים ב-AuditLog.
- אי-אפשר להסיר את המנהל הפעיל האחרון — התיק היה נשאר בלי מי שינהל אותו.
- משתמש מושבת נחסם בכל הארגונים בבת אחת.
"""
import pytest

from cfo.database import SessionLocal
from cfo.models import (
    AuditLog, Organization, OrganizationMembership, User, UserRole,
)
from cfo.services import membership_service


def _register(client, email: str):
    resp = client.post("/api/admin/auth/register", json={
        "email": email, "password": "secret123", "full_name": email,
    })
    assert resp.status_code == 201, resp.text
    d = resp.json()
    return {
        "headers": {"Authorization": f"Bearer {d['access_token']}"},
        "user_id": d["user"]["id"],
        "own_org": d["user"]["organization_id"],
    }


def _memberships(user_id: int):
    db = SessionLocal()
    try:
        return db.query(OrganizationMembership).filter(
            OrganizationMembership.user_id == user_id).all()
    finally:
        db.close()


# ==================================================================== #
# 1. הרשמה עצמית — חברות באותה טרנזקציה
# ==================================================================== #
def test_self_registration_creates_an_admin_membership(client):
    """הפער שנחשף בשלב 1: משתמש חדש שרד רק דרך מסלול התאימות."""
    person = _register(client, "fresh-signup@example.com")

    rows = _memberships(person["user_id"])

    assert len(rows) == 1, f"נוצרו {len(rows)} חברויות במקום אחת"
    m = rows[0]
    assert m.organization_id == person["own_org"]
    assert m.role == UserRole.ADMIN
    assert m.status == "active"


def test_new_user_does_not_rely_on_the_legacy_compatibility_path(client):
    """מסלול `legacy_column` נועד להיעלם. משתמש חדש חייב להיכנס דרך
    חברות אמיתית, אחרת המסלול הזמני הופך לקבוע."""
    import asyncio
    from cfo.api.dependencies import resolve_access_context

    person = _register(client, "not-legacy@example.com")

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == person["user_id"]).first()
        ctx = asyncio.run(resolve_access_context(user, None, db))
    finally:
        db.close()

    assert ctx.selection_source == "sole_membership", (
        f"משתמש חדש נכנס דרך {ctx.selection_source}"
    )


def test_registration_membership_shares_the_transaction(client, monkeypatch):
    """אם יצירת החברות נכשלת, גם הארגון והמשתמש מתבטלים.

    ארגון שנוצר בלי חברות הוא תיק שאיש אינו יכול לפתוח — ומשתמש בלי
    חברות ייפול למסלול התאימות, כלומר בדיוק מה שאנחנו מסירים."""
    from cfo.services import membership_service as ms

    def _boom(*a, **kw):
        raise RuntimeError("grant failed")

    monkeypatch.setattr(ms, "grant", _boom)

    # `TestClient` מפיץ חריגות שרת כברירת מחדל; מה שנבדק כאן אינו קוד
    # התשובה אלא שהטרנזקציה התגלגלה — כלומר לא נשאר משתמש בלי חברות.
    with pytest.raises(RuntimeError):
        client.post("/api/admin/auth/register", json={
            "email": "rollback@example.com", "password": "secret123",
            "full_name": "Rollback",
        })

    db = SessionLocal()
    try:
        orphan = db.query(User).filter(
            User.email == "rollback@example.com").first()
    finally:
        db.close()

    assert orphan is None, "משתמש נוצר בלי חברות — הטרנזקציה לא התגלגלה"


# ==================================================================== #
# 2. הזמנה אינה גישה
# ==================================================================== #
def test_invitation_creates_invited_not_active(client):
    inviter = _register(client, "inviter@example.com")
    invitee = _register(client, "invitee@example.com")

    db = SessionLocal()
    try:
        membership_service.invite(
            db, organization_id=inviter["own_org"], user_id=invitee["user_id"],
            role=UserRole.ACCOUNTANT, invited_by_user_id=inviter["user_id"],
        )
        db.commit()
        assert not membership_service.is_member(
            db, invitee["user_id"], inviter["own_org"])
    finally:
        db.close()


def test_accepting_an_invitation_activates_it(client):
    inviter = _register(client, "inviter2@example.com")
    invitee = _register(client, "invitee2@example.com")

    db = SessionLocal()
    try:
        membership_service.invite(
            db, organization_id=inviter["own_org"], user_id=invitee["user_id"],
            role=UserRole.ACCOUNTANT, invited_by_user_id=inviter["user_id"],
        )
        membership_service.accept(
            db, organization_id=inviter["own_org"], user_id=invitee["user_id"])
        db.commit()

        assert membership_service.is_member(
            db, invitee["user_id"], inviter["own_org"])
        assert membership_service.role_in(
            db, invitee["user_id"], inviter["own_org"]) == UserRole.ACCOUNTANT
    finally:
        db.close()


def test_only_the_invitee_can_accept(client):
    """קבלה בשם מישהו אחר היא הענקת גישה עצמית."""
    inviter = _register(client, "inviter3@example.com")
    invitee = _register(client, "invitee3@example.com")
    stranger = _register(client, "stranger3@example.com")

    db = SessionLocal()
    try:
        membership_service.invite(
            db, organization_id=inviter["own_org"], user_id=invitee["user_id"],
            role=UserRole.ACCOUNTANT, invited_by_user_id=inviter["user_id"],
        )
        db.commit()
        with pytest.raises(PermissionError):
            membership_service.accept(
                db, organization_id=inviter["own_org"],
                user_id=invitee["user_id"],
                acting_user_id=stranger["user_id"],
            )
    finally:
        db.close()


# ==================================================================== #
# 3. אין הענקה בלי ניהול באותו ארגון
# ==================================================================== #
def test_granting_requires_admin_in_that_specific_organization(client):
    """ADMIN בארגון א' אינו רשאי להעניק חברות בארגון ב'."""
    a = _register(client, "admin-of-a@example.com")
    b = _register(client, "admin-of-b@example.com")
    victim = _register(client, "victim-grant@example.com")

    db = SessionLocal()
    try:
        with pytest.raises(PermissionError):
            membership_service.grant_checked(
                db, organization_id=b["own_org"], user_id=victim["user_id"],
                role=UserRole.ADMIN, acting_user_id=a["user_id"],
            )
    finally:
        db.close()


def test_granting_writes_an_audit_log(client):
    admin = _register(client, "audited-admin@example.com")
    newcomer = _register(client, "audited-newcomer@example.com")

    db = SessionLocal()
    try:
        membership_service.grant_checked(
            db, organization_id=admin["own_org"], user_id=newcomer["user_id"],
            role=UserRole.VIEWER, acting_user_id=admin["user_id"],
        )
        db.commit()
        rows = db.query(AuditLog).filter(
            AuditLog.organization_id == admin["own_org"],
            AuditLog.entity_type == "OrganizationMembership",
        ).all()
    finally:
        db.close()

    assert rows, "הענקת חברות לא נרשמה ב-AuditLog"


def test_revocation_writes_an_audit_log(client):
    admin = _register(client, "revoke-audit-admin@example.com")
    member = _register(client, "revoke-audit-member@example.com")

    db = SessionLocal()
    try:
        membership_service.grant_checked(
            db, organization_id=admin["own_org"], user_id=member["user_id"],
            role=UserRole.VIEWER, acting_user_id=admin["user_id"],
        )
        db.commit()
        membership_service.revoke_checked(
            db, organization_id=admin["own_org"], user_id=member["user_id"],
            acting_user_id=admin["user_id"],
        )
        db.commit()
        rows = db.query(AuditLog).filter(
            AuditLog.organization_id == admin["own_org"],
            AuditLog.action == "MEMBERSHIP_REVOKE",
        ).all()
    finally:
        db.close()

    assert rows, "ביטול חברות לא נרשם ב-AuditLog"


# ==================================================================== #
# 4. אי-אפשר להשאיר ארגון בלי מנהל
# ==================================================================== #
def test_cannot_revoke_the_last_active_admin(client):
    """תיק בלי מנהל פעיל הוא תיק שאיש אינו יכול לתפעל — כולל להחזיר
    לעצמו גישה."""
    solo = _register(client, "solo-admin@example.com")

    db = SessionLocal()
    try:
        with pytest.raises(ValueError):
            membership_service.revoke_checked(
                db, organization_id=solo["own_org"], user_id=solo["user_id"],
                acting_user_id=solo["user_id"],
            )
    finally:
        db.close()


def test_revoking_one_of_two_admins_is_allowed(client):
    first = _register(client, "first-admin@example.com")
    second = _register(client, "second-admin@example.com")

    db = SessionLocal()
    try:
        membership_service.grant_checked(
            db, organization_id=first["own_org"], user_id=second["user_id"],
            role=UserRole.ADMIN, acting_user_id=first["user_id"],
        )
        db.commit()
        membership_service.revoke_checked(
            db, organization_id=first["own_org"], user_id=second["user_id"],
            acting_user_id=first["user_id"],
        )
        db.commit()
        assert not membership_service.is_member(
            db, second["user_id"], first["own_org"])
    finally:
        db.close()


def test_cannot_demote_the_last_admin_to_viewer(client):
    """הורדה בדרגה משאירה את התיק בלי מנהל בדיוק כמו ביטול."""
    solo = _register(client, "solo-demote@example.com")

    db = SessionLocal()
    try:
        with pytest.raises(ValueError):
            membership_service.grant_checked(
                db, organization_id=solo["own_org"], user_id=solo["user_id"],
                role=UserRole.VIEWER, acting_user_id=solo["user_id"],
            )
    finally:
        db.close()


# ==================================================================== #
# 5. השבתת אדם חוסמת בכל הארגונים
# ==================================================================== #
def test_deactivating_a_user_blocks_every_organization(client):
    person = _register(client, "multi-deactivated@example.com")
    second = _register(client, "second-org-owner@example.com")

    db = SessionLocal()
    try:
        membership_service.grant_checked(
            db, organization_id=second["own_org"], user_id=person["user_id"],
            role=UserRole.ADMIN, acting_user_id=second["user_id"],
        )
        db.commit()
        assert len(membership_service.active_organization_ids(
            db, person["user_id"])) == 2

        db.query(User).filter(User.id == person["user_id"]).update(
            {"is_active": False})
        db.commit()

        assert membership_service.active_organization_ids(
            db, person["user_id"]) == []
    finally:
        db.close()
