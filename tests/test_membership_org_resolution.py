"""בחירת הארגון הפעיל נגזרת מהחברות — בשרת, לא מהלקוח.

`get_current_org_id` קרא רק את `User.organization_id`. עם חברות
רב-ארגונית זה כבר לא מספיק: אדם עם שני עסקים צריך לבחור, ואדם עם עסק
אחד לא צריך.

הכללים:

- חברות אחת   ⇒ נכנסים אליה, בלי בחירה.
- כמה חברויות ⇒ **409** עם רשימת הארגונים **שלו בלבד**.
- כותרת `X-Active-Org-Id` מכובדת למי שהוא חבר פעיל בארגון היעד; לארגון
  שאינו חבר בו — **מתעלמים ממנה**, בדיוק כמו קודם. הכותרת לעולם לא
  מרחיבה scope, היא רק בוחרת מתוך מה שכבר מותר.
- אין חברויות כלל ⇒ 403. `users.organization_id` הוא מטא־דאטה ישנה,
  ולעולם אינו מקור סמכות.

`X-Active-Org-Id` מגיע מ-localStorage בלקוח, ולכן הוא **קלט לא מהימן**.
הוא משמש כאן כ*בקשה* לבחירה; ההיתר עצמו נבדק מול `organization_memberships`
בכל בקשה מחדש.
"""
import pytest

from cfo.database import SessionLocal
from cfo.models import Organization, OrganizationMembership, User, UserRole
from cfo.services import membership_service


NEEDS_ORG_STATUS = 409


def _register(client, email: str):
    resp = client.post("/api/admin/auth/register", json={
        "email": email, "password": "secret123", "full_name": email,
    })
    assert resp.status_code == 201, resp.text
    data = resp.json()
    return {
        "headers": {"Authorization": f"Bearer {data['access_token']}"},
        "user_id": data["user"]["id"],
        "own_org": data["user"]["organization_id"],
    }


def _active_org(client, headers):
    return client.get("/api/integration/status", headers=headers)


def _new_org(name: str) -> int:
    db = SessionLocal()
    try:
        o = Organization(name=name, is_active=True)
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


def _clear_legacy_org(user_id: int):
    """מנטרל את `users.organization_id` **ואת חברות הבית** שההרשמה יוצרת.

    מאז שההרשמה יוצרת חברות `ADMIN` בטרנזקציה אחת, ניקוי העמודה לבדו
    אינו מותיר את המשתמש בלי ארגון — ולכן הטסטים כאן היו בודקים מצב
    אחר ממה שהם מתארים.
    """
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        home = user.organization_id if user else None
        if home is not None:
            membership_service.revoke(
                db, organization_id=home, user_id=user_id,
                revoked_by_user_id=user_id,
            )
        db.query(User).filter(User.id == user_id).update({"organization_id": None})
        db.commit()
    finally:
        db.close()


# --------------------------------------------------------------------- #
def test_single_membership_enters_without_choosing(client):
    person = _register(client, "single-member@example.com")
    org = _new_org("יחיד")
    _clear_legacy_org(person["user_id"])
    _grant(org, person["user_id"])

    resp = _active_org(client, person["headers"])

    assert resp.status_code == 200, resp.text
    assert resp.json()["organization_id"] == org


def test_multi_membership_must_choose(client):
    person = _register(client, "multi-member@example.com")
    a, b = _new_org("רב א"), _new_org("רב ב")
    _clear_legacy_org(person["user_id"])
    _grant(a, person["user_id"], role=UserRole.ADMIN)
    _grant(b, person["user_id"], role=UserRole.VIEWER)

    resp = _active_org(client, person["headers"])

    assert resp.status_code == NEEDS_ORG_STATUS, (
        f"צפוי {NEEDS_ORG_STATUS}, התקבל {resp.status_code}: {resp.text[:250]}"
    )


def test_choice_list_contains_only_the_persons_own_organizations(client):
    """הרשימה שמוצגת לבחירה היא **שלו** — לא קטלוג הלקוחות של המשרד."""
    person = _register(client, "multi-scoped-list@example.com")
    a, b = _new_org("שלי א"), _new_org("שלי ב")
    other = _new_org("של מישהו אחר")
    _clear_legacy_org(person["user_id"])
    _grant(a, person["user_id"])
    _grant(b, person["user_id"])

    detail = _active_org(client, person["headers"]).json()["detail"]
    ids = {o["id"] for o in detail["organizations"]}

    assert ids == {a, b}
    assert other not in ids, "ארגון שאינו של המשתמש דלף לרשימת הבחירה"


def test_header_selects_among_own_memberships(client):
    person = _register(client, "multi-picks@example.com")
    a, b = _new_org("בחירה א"), _new_org("בחירה ב")
    _clear_legacy_org(person["user_id"])
    _grant(a, person["user_id"])
    _grant(b, person["user_id"])

    resp = _active_org(client, {**person["headers"], "X-Active-Org-Id": str(b)})

    assert resp.status_code == 200, resp.text
    assert resp.json()["organization_id"] == b


def test_header_for_a_non_member_org_fails_instead_of_substituting(client):
    """**היפוך התנהגות מכוון, 11/08/2026.**

    קודם התעלמנו מהכותרת והחזרנו את הארגון של המשתמש. זה נראה בטוח —
    scope לא הורחב — אבל הוא גרוע בדרך אחרת: מי שביקש ארגון א' וקיבל את
    ב' קורא וכותב לתיק אחר **בלי לדעת**. החלפה שקטה של יעד היא בדיוק
    סוג התקלה שהסרנו מסופר-אדמין.

    הכלל עכשיו: כותרת מפורשת מכובדת או נכשלת — לעולם לא מוחלפת."""
    person = _register(client, "scope-attack@example.com")
    mine, theirs = _new_org("שלי"), _new_org("שלהם")
    _clear_legacy_org(person["user_id"])
    _grant(mine, person["user_id"])

    resp = _active_org(client, {**person["headers"], "X-Active-Org-Id": str(theirs)})

    assert resp.status_code in (403, NEEDS_ORG_STATUS), resp.text
    assert resp.json().get("organization_id") not in (mine, theirs), (
        "הכותרת הוחלפה בשקט או שהורחב scope"
    )


def test_revoked_membership_loses_access_immediately(client):
    """ביטול נכנס לתוקף בבקשה הבאה — לא אחרי logout ולא אחרי cron."""
    person = _register(client, "revoke-live@example.com")
    a, b = _new_org("ביטול א"), _new_org("ביטול ב")
    _clear_legacy_org(person["user_id"])
    _grant(a, person["user_id"])
    _grant(b, person["user_id"])
    headers = {**person["headers"], "X-Active-Org-Id": str(b)}
    assert _active_org(client, headers).json()["organization_id"] == b

    db = SessionLocal()
    try:
        membership_service.revoke(db, organization_id=b, user_id=person["user_id"],
                                  revoked_by_user_id=person["user_id"])
        db.commit()
    finally:
        db.close()

    resp = _active_org(client, headers)

    assert resp.json().get("organization_id") != b, "גישה נשמרה אחרי ביטול"


def test_invited_membership_does_not_grant_access_yet(client):
    person = _register(client, "invited-only@example.com")
    org = _new_org("הזמנה")
    _clear_legacy_org(person["user_id"])
    _grant(org, person["user_id"], status="invited")

    resp = _active_org(client, {**person["headers"], "X-Active-Org-Id": str(org)})

    assert resp.json().get("organization_id") != org


def test_user_without_memberships_is_denied_even_with_legacy_column(client):
    """עמודת users.organization_id היא מטא־דאטה ישנה, לא מקור סמכות."""
    person = _register(client, "legacy-only@example.com")

    db = SessionLocal()
    try:
        db.query(OrganizationMembership).filter(
            OrganizationMembership.user_id == person["user_id"],
        ).delete()
        db.commit()
    finally:
        db.close()

    resp = _active_org(client, person["headers"])

    assert resp.status_code == 403, resp.text
