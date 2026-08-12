"""OrganizationAccessContext — נקודת ההכרעה היחידה לגישה ארגונית.

עד עכשיו ההכרעה הייתה מפוזרת: `get_current_org_id` בחר ארגון,
`require_admin` בדק `User.role`, ו-`users.organization_id` שימש fallback
שקט. שלוש שכבות שאינן מדברות זו עם זו — ולכן אפשר היה לעבור ביניהן.

הקשר יחיד מחזיק את כל המצב: מי המשתמש, באיזה ארגון, מכוח איזו חברות,
עם איזה תפקיד **בארגון הזה**, ואיך הארגון נבחר.

## שלוש ההכרעות שהטסטים כאן אוכפים

**1. רשומת חברות שאינה פעילה חוסמת — היא אינה "אין חברות".**
זה הפער שנשאר פתוח אחרי `bb5365c`: המיגרציה נותנת למשתמש מושבת חברות
`suspended`, אבל אם ההכרעה מתייחסת אליה כאל היעדר חברות היא נופלת
ל-`users.organization_id` והגישה חוזרת בשקט. רשומה קיימת שאינה פעילה
היא **סירוב מפורש**, לא היעדר מידע.

**2. כותרת מפורשת לעולם אינה מוחלפת בשקט.**
מי שביקש ארגון א' ומקבל את ארגון ב' — קורא נתונים של תיק אחר בלי לדעת.
עדיף להיכשל. (זו הפיכה של ההתנהגות שקובעה קודם ב-
`test_header_for_a_non_member_org_never_widens_scope`.)

**3. התפקיד בארגון גובר על התפקיד הגלובלי.**
`User.role` הוא שדה פלטפורמה. אדם יכול להיות ADMIN בעסק שלו ו-VIEWER
בעסק של שותף; `User.role=ADMIN` אינו רשאי להקנות לו כתיבה בעסק השני.
"""
import pytest

from cfo.database import SessionLocal
from cfo.models import Organization, OrganizationMembership, User, UserRole
from cfo.services import membership_service


NEEDS_ORG = 409
FORBIDDEN = 403


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


def _org(name: str, active: bool = True) -> int:
    db = SessionLocal()
    try:
        o = Organization(name=name, is_active=active)
        db.add(o)
        db.commit()
        return o.id
    finally:
        db.close()


def _grant(org_id: int, user_id: int, role=UserRole.ADMIN, status="active"):
    db = SessionLocal()
    try:
        membership_service.grant(
            db, organization_id=org_id, user_id=user_id, role=role,
            granted_by_user_id=user_id, status=status,
        )
        db.commit()
    finally:
        db.close()


def _set_status(org_id: int, user_id: int, status: str):
    db = SessionLocal()
    try:
        db.query(OrganizationMembership).filter(
            OrganizationMembership.user_id == user_id,
            OrganizationMembership.organization_id == org_id,
        ).update({"status": status})
        db.commit()
    finally:
        db.close()


def _set_org_active(org_id: int, active: bool):
    db = SessionLocal()
    try:
        db.query(Organization).filter(Organization.id == org_id).update(
            {"is_active": active})
        db.commit()
    finally:
        db.close()


def _status(client, headers):
    return client.get("/api/integration/status", headers=headers)


# ==================================================================== #
# 1. רשומת חברות לא-פעילה חוסמת — אין נפילה לעמודה הישנה
# ==================================================================== #
def test_revoked_membership_does_not_fall_back_to_the_legacy_column(client):
    """הפער שנשאר פתוח אחרי bb5365c.

    למשתמש יש `users.organization_id` **וגם** רשומת חברות מבוטלת. אם
    ההכרעה מתייחסת ל"אין חברות פעילה" כאל "אין חברות", היא נופלת לעמודה
    הישנה והגישה חוזרת — למרות שמישהו ביטל אותה במפורש."""
    person = _register(client, "revoked-fallback@example.com")
    home = person["own_org"]
    _grant(home, person["user_id"])
    _set_status(home, person["user_id"], "revoked")

    resp = _status(client, person["headers"])

    assert resp.status_code == FORBIDDEN, (
        f"חברות מבוטלת נפלה חזרה ל-users.organization_id: {resp.status_code} "
        f"{resp.text[:200]}"
    )


@pytest.mark.parametrize("status", ["suspended", "invited", "revoked"])
def test_no_inactive_membership_status_grants_access(client, status):
    person = _register(client, f"inactive-{status}@example.com")
    _grant(person["own_org"], person["user_id"])
    _set_status(person["own_org"], person["user_id"], status)

    assert _status(client, person["headers"]).status_code == FORBIDDEN


def test_reactivating_a_user_does_not_restore_suspended_access(client):
    """התרחיש המלא שה-backfill הכין: משתמש מושבת קיבל חברות `suspended`.
    הפעלתו מחדש אינה מחזירה גישה — הרשומה עדיין מושעית."""
    person = _register(client, "reactivated@example.com")
    _grant(person["own_org"], person["user_id"])
    _set_status(person["own_org"], person["user_id"], "suspended")

    db = SessionLocal()
    try:
        db.query(User).filter(User.id == person["user_id"]).update(
            {"is_active": True})
        db.commit()
    finally:
        db.close()

    assert _status(client, person["headers"]).status_code == FORBIDDEN


# ==================================================================== #
# 2. כותרת מפורשת לעולם אינה מוחלפת בשקט
# ==================================================================== #
def test_explicit_header_for_a_non_member_org_fails_instead_of_substituting(client):
    """היפוך התנהגות מכוון: קודם התעלמנו מהכותרת והחזרנו את הארגון של
    המשתמש. מי שביקש ארגון א' וקיבל את ב' קורא תיק אחר בלי לדעת."""
    person = _register(client, "explicit-wrong-org@example.com")
    mine = person["own_org"]
    theirs = _org("לא שלו")
    _grant(mine, person["user_id"])

    resp = _status(client, {**person["headers"], "X-Active-Org-Id": str(theirs)})

    assert resp.status_code in (FORBIDDEN, NEEDS_ORG), resp.text
    assert resp.json().get("organization_id") != mine, (
        "הכותרת הוחלפה בשקט בארגון של המשתמש"
    )


def test_explicit_header_for_a_revoked_membership_fails(client):
    person = _register(client, "explicit-revoked@example.com")
    a, b = _org("א-מבוטל"), _org("ב-פעיל")
    _grant(a, person["user_id"])
    _grant(b, person["user_id"])
    _set_status(a, person["user_id"], "revoked")

    resp = _status(client, {**person["headers"], "X-Active-Org-Id": str(a)})

    assert resp.status_code in (FORBIDDEN, NEEDS_ORG)
    assert resp.json().get("organization_id") != b, (
        "בקשה לארגון מבוטל בוצעה בארגון האחר"
    )


def test_a_failed_selection_does_not_leak_organization_names(client):
    """403 אינו מקום לפרסם את קטלוג הלקוחות."""
    person = _register(client, "no-leak@example.com")
    _grant(person["own_org"], person["user_id"])
    secret = _org("שם-סודי-של-לקוח")

    body = _status(client, {**person["headers"],
                            "X-Active-Org-Id": str(secret)}).text

    assert "שם-סודי-של-לקוח" not in body


# ==================================================================== #
# 3. תפקיד החברות גובר על התפקיד הגלובלי
# ==================================================================== #
def _set_global_role(user_id: int, role: UserRole):
    db = SessionLocal()
    try:
        db.query(User).filter(User.id == user_id).update({"role": role})
        db.commit()
    finally:
        db.close()


def test_global_admin_with_viewer_membership_cannot_write(client):
    """`User.role=ADMIN` אינו מקנה כתיבה בעסק שבו האדם הוא VIEWER."""
    person = _register(client, "global-admin-local-viewer@example.com")
    org = _org("עסק של שותף")
    _grant(org, person["user_id"], role=UserRole.VIEWER)
    _set_global_role(person["user_id"], UserRole.ADMIN)

    resp = client.post("/api/tasks", json={"title": "לא אמור לעבור"},
                       headers={**person["headers"], "X-Active-Org-Id": str(org)})

    assert resp.status_code == FORBIDDEN, (
        f"תפקיד גלובלי עקף את תפקיד החברות: {resp.status_code}"
    )


def test_global_viewer_with_admin_membership_may_write(client):
    """הכיוון ההפוך: התפקיד הגלובלי הנמוך אינו חוסם ADMIN בארגון שלו."""
    person = _register(client, "global-viewer-local-admin@example.com")
    org = _org("העסק שלו")
    _grant(org, person["user_id"], role=UserRole.ADMIN)
    _set_global_role(person["user_id"], UserRole.VIEWER)

    resp = client.post("/api/tasks", json={"title": "אמור לעבור"},
                       headers={**person["headers"], "X-Active-Org-Id": str(org)})

    assert resp.status_code == 200, resp.text


# ==================================================================== #
# 4. ארגון לא פעיל, ושינוי חברות בין בקשות
# ==================================================================== #
def test_inactive_organization_is_always_blocked(client):
    person = _register(client, "inactive-org@example.com")
    org = _org("ארגון שיושבת")
    _grant(org, person["user_id"])
    headers = {**person["headers"], "X-Active-Org-Id": str(org)}
    assert _status(client, headers).status_code == 200

    _set_org_active(org, False)

    assert _status(client, headers).status_code in (FORBIDDEN, NEEDS_ORG)


def test_membership_change_takes_effect_on_the_very_next_request(client):
    """אין cache ואין הסתמכות על טוקן: ההכרעה נבנית מחדש בכל בקשה."""
    person = _register(client, "live-change@example.com")
    org = _org("שינוי חי")
    _grant(org, person["user_id"])
    headers = {**person["headers"], "X-Active-Org-Id": str(org)}
    assert _status(client, headers).status_code == 200

    _set_status(org, person["user_id"], "revoked")

    assert _status(client, headers).status_code in (FORBIDDEN, NEEDS_ORG)


# ==================================================================== #
# 5. ההקשר עצמו
# ==================================================================== #
def test_context_exposes_the_full_decision(client):
    from cfo.api.dependencies import OrganizationAccessContext

    for field in ("user", "organization_id", "membership", "effective_role",
                  "is_super_admin", "selection_source", "channel"):
        assert field in OrganizationAccessContext.__dataclass_fields__, field


def test_selection_source_records_how_the_org_was_chosen(client):
    """ראיית ביקורת: "מאיפה הגיע הארגון" הוא בדיוק מה שצריך לדעת אחרי
    כתיבה לתיק הלא-נכון."""
    import asyncio
    from cfo.api.dependencies import resolve_access_context

    person = _register(client, "selection-source@example.com")
    org = _org("מקור בחירה")
    _grant(org, person["user_id"])

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == person["user_id"]).first()
        ctx = asyncio.run(resolve_access_context(user, None, db))
        assert ctx.selection_source == "sole_membership"
        assert ctx.organization_id == org
        assert ctx.effective_role == UserRole.ADMIN
        assert ctx.membership is not None
    finally:
        db.close()
