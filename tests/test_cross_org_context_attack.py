"""התקיפה המרכזית: home-org=A, חברות ADMIN ב-B, כותרת=B.

זהו התרחיש שחושף כל route ששכח את ההקשר. למשתמש יש `users.organization_id=A`
(ארגון הבית שנוצר בהרשמה) **וגם** חברות פעילה ב-B. ההקשר בחר B.

מרגע זה, כל route שקורא `current_user.organization_id` במקום את ההקשר
יפעל בארגון A — בעוד שהמשתמש, ה-UI וה-AuditLog חושבים שהוא ב-B.
זו לא זליגה בין לקוחות זרים: זו **כתיבה לתיק הלא-נכון של אותו אדם**,
והיא הרבה יותר קשה לגילוי כי היא נראית לגיטימית.

הכלל: אחרי שההקשר בחר B, כל route חייב לפעול ב-B או להיכשל. אין
אפשרות שלישית.

הטסט סורק **קבוצות routes שלמות** — ארגון, משתמשים, audit וזיכרון
מושקו — ולא מסלול בודד, כדי שהוספת route חדש לאותה משפחה תיתפס.
"""
import pytest

from cfo.database import SessionLocal
from cfo.models import (
    AuditLog, MoshkoMemory, Organization, OrganizationMembership, Task, User,
    UserRole,
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
        "home_org": d["user"]["organization_id"],
    }


@pytest.fixture(scope="module")
def split_identity(client):
    """home-org = A (מההרשמה) · חברות ADMIN ב-B · הכותרת מצביעה על B."""
    person = _register(client, "split-identity@example.com")

    db = SessionLocal()
    try:
        org_b = Organization(name="ארגון ב — היעד", is_active=True)
        db.add(org_b)
        db.flush()
        membership_service.grant(
            db, organization_id=org_b.id, user_id=person["user_id"],
            role=UserRole.ADMIN, granted_by_user_id=person["user_id"],
        )
        db.commit()
        b_id = org_b.id
    finally:
        db.close()

    return {
        "user_id": person["user_id"],
        "home_org": person["home_org"],          # A
        "target_org": b_id,                       # B
        "headers": {**person["headers"], "X-Active-Org-Id": str(b_id)},
    }


def test_the_fixture_really_splits_home_from_target(split_identity):
    """שער נגדי: אם A==B, כל הטסטים כאן עוברים מהסיבה הלא-נכונה."""
    assert split_identity["home_org"] != split_identity["target_org"]


# ==================================================================== #
# כתיבה — נוחתת ב-B, לעולם לא ב-A
# ==================================================================== #
def _rows_in(model, org_id: int):
    db = SessionLocal()
    try:
        return db.query(model).filter(model.organization_id == org_id).all()
    finally:
        db.close()


def test_a_write_lands_in_the_selected_org_never_in_home(client, split_identity):
    title = "משימה-שנוצרה-תחת-הקשר-B"

    resp = client.post("/api/tasks", json={"title": title},
                       headers=split_identity["headers"])

    assert resp.status_code == 200, resp.text
    in_home = [t for t in _rows_in(Task, split_identity["home_org"])
               if t.title == title]
    in_target = [t for t in _rows_in(Task, split_identity["target_org"])
                 if t.title == title]

    assert not in_home, "הכתיבה נחתה בארגון הבית A למרות שההקשר בחר B"
    assert in_target, "הכתיבה לא נחתה בארגון היעד B"


def test_a_read_returns_the_selected_orgs_data_only(client, split_identity):
    """נתון שנכתב ב-A אינו נראה תחת הקשר B."""
    db = SessionLocal()
    try:
        db.add(Task(organization_id=split_identity["home_org"],
                    title="סוד-של-ארגון-A"))
        db.commit()
    finally:
        db.close()

    body = client.get("/api/tasks", headers=split_identity["headers"]).text

    assert "סוד-של-ארגון-A" not in body, "נתון מארגון הבית דלף להקשר B"


# ==================================================================== #
# משפחות ה-routes הרגישות
# ==================================================================== #
SENSITIVE_READ_ROUTES = [
    "/api/tasks",
    "/api/integration/status",
    "/api/admin/audit-logs",
    "/api/admin/users",
    "/api/admin/moshko/memory",
]


@pytest.mark.parametrize("path", SENSITIVE_READ_ROUTES)
def test_sensitive_routes_never_report_the_home_org(client, split_identity, path):
    """כל route רגיש פועל ב-B או נכשל — אין אפשרות שלישית.

    Route שמחזיר `organization_id` של ארגון הבית הוא route ששכח את
    ההקשר; הוא ידווח למשתמש על תיק אחד בזמן שהוא פועל על אחר."""
    resp = client.get(path, headers=split_identity["headers"])

    if resp.status_code >= 400:
        return  # כישלון גלוי — מותר
    body = resp.json()
    reported = body.get("organization_id") if isinstance(body, dict) else None
    if reported is not None:
        assert reported != split_identity["home_org"], (
            f"{path} דיווח על ארגון הבית A במקום על היעד B"
        )
        assert reported == split_identity["target_org"], (
            f"{path} דיווח על ארגון {reported} במקום {split_identity['target_org']}"
        )


def test_audit_log_route_does_not_expose_home_org_records(client, split_identity):
    """audit הוא בדיוק המקום שבו טעות כזו הרסנית: מי שבודק מה קרה
    בתיק B יראה פעולות מתיק A."""
    marker = "AUDIT-MARKER-ORG-A"
    db = SessionLocal()
    try:
        db.add(AuditLog(
            organization_id=split_identity["home_org"],
            user_id=split_identity["user_id"],
            action=marker, entity_type="Test",
        ))
        db.commit()
    finally:
        db.close()

    resp = client.get("/api/admin/audit-logs", headers=split_identity["headers"])

    if resp.status_code < 400:
        assert marker not in resp.text, "רשומת audit מארגון הבית דלפה להקשר B"


def test_moshko_memory_route_does_not_expose_home_org_memories(client, split_identity):
    """זיכרון מושקו נושא עובדות עסק — דליפה שלו היא דליפה חשבונאית."""
    marker = "MEMORY-MARKER-ORG-A"
    db = SessionLocal()
    try:
        db.add(MoshkoMemory(
            organization_id=split_identity["home_org"],
            user_id=None, content=marker, category="business_fact",
            source="admin",
        ))
        db.commit()
    finally:
        db.close()

    resp = client.get("/api/admin/moshko/memory", headers=split_identity["headers"])

    if resp.status_code < 400:
        assert marker not in resp.text, "זיכרון מארגון הבית דלף להקשר B"


def test_users_route_does_not_list_home_org_users(client, split_identity):
    """רשימת המשתמשים של תיק A אינה נראית תחת הקשר B."""
    db = SessionLocal()
    try:
        db.add(User(
            email="only-in-org-a@example.com", password_hash="x",
            full_name="ONLY-IN-ORG-A", role=UserRole.USER,
            organization_id=split_identity["home_org"], is_active=True,
        ))
        db.commit()
    finally:
        db.close()

    resp = client.get("/api/admin/users", headers=split_identity["headers"])

    if resp.status_code < 400:
        assert "ONLY-IN-ORG-A" not in resp.text, (
            "משתמש מארגון הבית דלף להקשר B"
        )


# ==================================================================== #
# organization_id בגוף/נתיב חייב להתאים להקשר
# ==================================================================== #
def test_body_organization_id_cannot_override_the_context(client, split_identity):
    """`organization_id` בגוף הבקשה הוא קלט מהלקוח. אם route מכבד אותו,
    ההקשר כולו הופך לקישוט."""
    title = "ניסיון-לעקוף-דרך-הגוף"

    resp = client.post(
        "/api/tasks",
        json={"title": title, "organization_id": split_identity["home_org"]},
        headers=split_identity["headers"],
    )

    if resp.status_code < 400:
        in_home = [t for t in _rows_in(Task, split_identity["home_org"])
                   if t.title == title]
        assert not in_home, "organization_id מהגוף עקף את ההקשר"


def test_path_organization_id_for_another_org_fails(client, split_identity):
    """נתיב שנושא מזהה ארגון אחר חייב להיכשל, לא להתבצע בהקשר."""
    resp = client.get(
        f"/api/admin/organizations/{split_identity['home_org']}",
        headers=split_identity["headers"],
    )

    assert resp.status_code >= 400, (
        "גישה לארגון הבית דרך הנתיב הצליחה למרות שההקשר הוא B"
    )


def test_patch_organization_cannot_escape_the_selected_context(client, split_identity):
    resp = client.patch(
        f"/api/admin/organizations/{split_identity['home_org']}",
        json={"name": "אסור לשנות את A מתוך B"},
        headers=split_identity["headers"],
    )

    assert resp.status_code == 403, resp.text


def test_get_user_cannot_read_a_home_org_identity_from_another_context(
    client, split_identity,
):
    db = SessionLocal()
    try:
        target = User(
            email="context-get-user-home@example.com", password_hash="x",
            full_name="HOME ONLY USER", role=UserRole.USER,
            organization_id=split_identity["home_org"], is_active=True,
        )
        db.add(target)
        db.commit()
        target_id = target.id
    finally:
        db.close()

    resp = client.get(
        f"/api/admin/users/{target_id}", headers=split_identity["headers"],
    )

    assert resp.status_code in (403, 404), resp.text


def test_user_list_is_sourced_from_membership_not_legacy_home_org(
    client, split_identity,
):
    db = SessionLocal()
    try:
        member = User(
            email="member-of-b-home-a@example.com", password_hash="x",
            full_name="MEMBER OF B", role=UserRole.USER,
            organization_id=split_identity["home_org"], is_active=True,
        )
        db.add(member)
        db.flush()
        membership_service.grant(
            db, organization_id=split_identity["target_org"], user_id=member.id,
            role=UserRole.VIEWER, granted_by_user_id=split_identity["user_id"],
        )
        db.commit()
        member_id = member.id
    finally:
        db.close()

    resp = client.get("/api/admin/users", headers=split_identity["headers"])

    assert resp.status_code == 200, resp.text
    assert member_id in {row["id"] for row in resp.json()}, resp.text


def test_memory_create_update_delete_are_scoped_to_selected_org(
    client, split_identity,
):
    create = client.post(
        "/api/admin/moshko/memory",
        json={
            "organization_id": split_identity["home_org"],
            "content": "אסור לכתוב לזיכרון A מתוך B",
            "category": "business_fact",
        },
        headers=split_identity["headers"],
    )
    assert create.status_code == 403, create.text

    db = SessionLocal()
    try:
        row = MoshkoMemory(
            organization_id=split_identity["home_org"], user_id=None,
            content="זיכרון קיים ב-A", category="business_fact", source="admin",
        )
        db.add(row)
        db.commit()
        row_id = row.id
    finally:
        db.close()

    patch = client.patch(
        f"/api/admin/moshko/memory/{row_id}",
        json={"content": "ניסיון שינוי מתוך B"},
        headers=split_identity["headers"],
    )
    delete = client.delete(
        f"/api/admin/moshko/memory/{row_id}",
        headers=split_identity["headers"],
    )

    assert patch.status_code in (403, 404), patch.text
    assert delete.status_code in (403, 404), delete.text


def _home_user_with_membership_in_target(split_identity, email: str):
    db = SessionLocal()
    try:
        user = User(
            email=email, password_hash="x", full_name=email,
            role=UserRole.USER, organization_id=split_identity["home_org"],
            is_active=True,
        )
        db.add(user)
        db.flush()
        membership_service.grant(
            db, organization_id=split_identity["target_org"], user_id=user.id,
            role=UserRole.VIEWER, granted_by_user_id=split_identity["user_id"],
        )
        db.commit()
        return user.id
    finally:
        db.close()


def test_org_deactivation_suspends_membership_not_global_identity(
    client, split_identity,
):
    user_id = _home_user_with_membership_in_target(
        split_identity, "suspend-only-in-b@example.com",
    )

    resp = client.patch(
        f"/api/admin/users/{user_id}", json={"is_active": False},
        headers=split_identity["headers"],
    )
    assert resp.status_code == 200, resp.text

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).one()
        membership = db.query(OrganizationMembership).filter(
            OrganizationMembership.user_id == user_id,
            OrganizationMembership.organization_id == split_identity["target_org"],
        ).one()
        assert user.is_active is True, "פעולת ארגון השביתה identity בכל הארגונים"
        assert membership.status == "suspended"
    finally:
        db.close()


def test_org_delete_revokes_membership_not_global_identity(client, split_identity):
    user_id = _home_user_with_membership_in_target(
        split_identity, "revoke-only-in-b@example.com",
    )

    resp = client.delete(
        f"/api/admin/users/{user_id}", headers=split_identity["headers"],
    )
    assert resp.status_code == 204, resp.text

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).one()
        membership = db.query(OrganizationMembership).filter(
            OrganizationMembership.user_id == user_id,
            OrganizationMembership.organization_id == split_identity["target_org"],
        ).one()
        assert user.is_active is True, "מחיקה ארגונית השביתה identity גלובלי"
        assert membership.status == "revoked"
    finally:
        db.close()
