"""ניהול משתמשים דרך ה-API יוצר ומשנה **חברות**, לא `User.role`.

`POST /admin/users` יצר משתמש עם `User.role` ו-`User.organization_id`
בלבד. אחרי מעבר ל-`effective_role`, משתמש כזה נכנס דרך מסלול התאימות
`legacy_column` — ואם הוא נחסם, אין לו גישה כלל. שני המצבים שגויים.

`PATCH /admin/users/{id}` שינה `User.role` — שדה **גלובלי**. שינוי
תפקיד של אדם בתיק אחד היה משנה את תפקידו בכל התיקים.

הכלל: יצירה מייצרת חברות `invited` באותה טרנזקציה; שינוי תפקיד משנה
את החברות **בארגון הפעיל** בלבד.
"""
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
    return {
        "headers": {"Authorization": f"Bearer {d['access_token']}"},
        "user_id": d["user"]["id"],
        "org": d["user"]["organization_id"],
    }


def _membership(user_id: int, org_id: int):
    db = SessionLocal()
    try:
        return db.query(OrganizationMembership).filter(
            OrganizationMembership.user_id == user_id,
            OrganizationMembership.organization_id == org_id,
        ).first()
    finally:
        db.close()


@pytest.fixture(scope="module")
def admin(client):
    a = _register(client, "user-routes-admin@example.com")
    a["headers"] = {**a["headers"], "X-Active-Org-Id": str(a["org"])}
    return a


# ==================================================================== #
# יצירה → invited
# ==================================================================== #
def test_creating_a_user_creates_an_invited_membership(client, admin):
    resp = client.post("/api/admin/users", json={
        "email": "created-invited@example.com",
        "password": "secret123",
        "full_name": "Created Invited",
        "role": "accountant",
        "organization_id": admin["org"],
    }, headers=admin["headers"])

    assert resp.status_code == 201, resp.text
    new_id = resp.json()["id"]
    m = _membership(new_id, admin["org"])

    assert m is not None, "לא נוצרה חברות למשתמש שנוצר דרך ה-API"
    assert m.status == "invited", f"נוצרה חברות בסטטוס {m.status} במקום invited"
    assert m.role == UserRole.ACCOUNTANT


def test_a_created_user_has_no_access_until_acceptance(client, admin):
    """`invited` אינו גישה. משתמש שנוצר ולא קיבל — נחסם."""
    resp = client.post("/api/admin/users", json={
        "email": "created-no-access@example.com",
        "password": "secret123",
        "full_name": "No Access Yet",
        "role": "accountant",
        "organization_id": admin["org"],
    }, headers=admin["headers"])
    assert resp.status_code == 201, resp.text

    login = client.post("/api/admin/auth/login", json={
        "email": "created-no-access@example.com", "password": "secret123",
    })
    assert login.status_code == 200, login.text
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    status_resp = client.get("/api/integration/status", headers=headers)

    assert status_resp.status_code in (403, 409), (
        f"משתמש שטרם קיבל הזמנה קיבל גישה: {status_resp.status_code}"
    )


def test_creating_a_user_in_another_org_is_refused(client, admin):
    db = SessionLocal()
    try:
        other = Organization(name="ארגון זר ליצירת משתמש", is_active=True)
        db.add(other)
        db.commit()
        other_id = other.id
    finally:
        db.close()

    resp = client.post("/api/admin/users", json={
        "email": "cross-org-create@example.com",
        "password": "secret123",
        "full_name": "Cross Org",
        "role": "accountant",
        "organization_id": other_id,
    }, headers=admin["headers"])

    assert resp.status_code == 403, resp.text


def test_creating_a_user_is_transactional(client, admin, monkeypatch):
    """אם יצירת החברות נכשלת, גם המשתמש אינו נוצר — אחרת נשאר חשבון
    התחברות בלי שום חברות, כלומר משתמש שאיש אינו יכול לנהל."""
    from cfo.services import membership_service as ms

    def _boom(*a, **kw):
        raise RuntimeError("invite failed")

    monkeypatch.setattr(ms, "invite", _boom)

    with pytest.raises(RuntimeError):
        client.post("/api/admin/users", json={
            "email": "tx-rollback@example.com",
            "password": "secret123",
            "full_name": "TX Rollback",
            "role": "accountant",
            "organization_id": admin["org"],
        }, headers=admin["headers"])

    db = SessionLocal()
    try:
        orphan = db.query(User).filter(
            User.email == "tx-rollback@example.com").first()
    finally:
        db.close()

    assert orphan is None, "נוצר משתמש בלי חברות"


# ==================================================================== #
# שינוי תפקיד → חברות בארגון הפעיל בלבד
# ==================================================================== #
def test_role_update_changes_the_membership_not_the_global_role(client, admin):
    """`User.role` הוא שדה גלובלי. שינויו בתיק אחד היה משנה את התפקיד
    בכל התיקים שבהם האדם חבר."""
    target = _register(client, "role-change-target@example.com")

    db = SessionLocal()
    try:
        membership_service.grant(
            db, organization_id=admin["org"], user_id=target["user_id"],
            role=UserRole.VIEWER, granted_by_user_id=admin["user_id"],
        )
        db.commit()
        global_role_before = db.query(User).filter(
            User.id == target["user_id"]).first().role
    finally:
        db.close()

    resp = client.patch(f"/api/admin/users/{target['user_id']}",
                        json={"role": "accountant"}, headers=admin["headers"])

    assert resp.status_code == 200, resp.text
    m = _membership(target["user_id"], admin["org"])
    assert m.role == UserRole.ACCOUNTANT, "תפקיד החברות לא השתנה"

    db = SessionLocal()
    try:
        global_role_after = db.query(User).filter(
            User.id == target["user_id"]).first().role
    finally:
        db.close()
    assert global_role_after == global_role_before, (
        "שינוי תפקיד בארגון אחד שינה את התפקיד הגלובלי"
    )


def test_role_update_does_not_touch_other_organizations(client, admin):
    """אותו אדם, שני תיקים: שינוי באחד אינו נוגע בשני."""
    target = _register(client, "role-isolation-target@example.com")
    home = target["org"]

    db = SessionLocal()
    try:
        membership_service.grant(
            db, organization_id=admin["org"], user_id=target["user_id"],
            role=UserRole.VIEWER, granted_by_user_id=admin["user_id"],
        )
        db.commit()
    finally:
        db.close()

    client.patch(f"/api/admin/users/{target['user_id']}",
                 json={"role": "accountant"}, headers=admin["headers"])

    home_membership = _membership(target["user_id"], home)
    assert home_membership.role == UserRole.ADMIN, (
        "שינוי בארגון אחד השפיע על החברות בארגון הבית"
    )
