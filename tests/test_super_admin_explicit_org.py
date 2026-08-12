"""SUPER_ADMIN חייב לבחור ארגון — אין ברירת מחדל שקטה ל-org 1.

`get_current_org_id` החזיר `1` לכל SUPER_ADMIN שאין לו `organization_id`
ושלא שלח `X-Active-Org-Id`. זו ברירת מחדל שקטה לתיק של לקוח אמיתי:
החזית קוראת את הכותרת מ-`localStorage`, ולכן דפדפן חדש, מצב פרטי, ניקוי
אחסון או קריאת API ישירה — כולם מייצרים בקשה בלי כותרת. הבקשה הבאה
נכתבת לארגון 1 בלי שאיש בחר בו.

הכלל: אין ארגון פעיל ⇒ **הבקשה נעצרת**, עם שגיאה שאומרת מה לעשות
ורשימת הארגונים שאפשר לבחור מהם. עצירה גלויה עדיפה על כתיבה לתיק הלא-נכון.

`organization_id` משלו נשאר תקף — סופר-אדמין שנרשם רגיל ויש לו ארגון
משלו לא נפגע. השינוי נוגע אך ורק למי שאין לו ארגון כלל.
"""
import pytest

from cfo.database import SessionLocal
from cfo.models import Organization, User, UserRole


NEEDS_ORG_STATUS = 409


@pytest.fixture(scope="module")
def orgless_super(client):
    """SUPER_ADMIN בלי `organization_id` — בדיוק מי שנפל ל-org 1."""
    resp = client.post("/api/admin/auth/register", json={
        "email": "orgless-super@example.com",
        "password": "secret123",
        "full_name": "Orgless Super",
    })
    assert resp.status_code == 201, resp.text
    token = resp.json()["access_token"]

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == "orgless-super@example.com").first()
        user.role = UserRole.SUPER_ADMIN
        user.organization_id = None
        db.commit()
    finally:
        db.close()
    return {"Authorization": f"Bearer {token}"}


def _integration_status(client, headers):
    return client.get("/api/integration/status", headers=headers)


def test_orgless_super_admin_without_header_is_refused(client, orgless_super):
    """הבדיקה המרכזית: בלי בחירה מפורשת הבקשה נעצרת ואינה נופלת ל-org 1."""
    resp = _integration_status(client, orgless_super)

    assert resp.status_code == NEEDS_ORG_STATUS, (
        f"צפוי {NEEDS_ORG_STATUS}, התקבל {resp.status_code}: {resp.text[:300]}"
    )
    body = resp.json()
    assert body.get("organization_id") != 1, "נפל לארגון 1 למרות שאיש לא בחר בו"


def test_refusal_tells_the_caller_what_to_do(client, orgless_super):
    """מי שנעצר חייב לדעת איך להמשיך, אחרת יעקוף את השער."""
    detail = _integration_status(client, orgless_super).json()["detail"]
    text = str(detail)

    assert "X-Active-Org-Id" in text, "השגיאה אינה מציינת את הכותרת הנדרשת"


def test_refusal_lists_selectable_organizations(client, orgless_super, owner):
    """החזית צריכה להציג בורר — ולכן השגיאה נושאת את הרשימה."""
    detail = _integration_status(client, orgless_super).json()["detail"]

    assert isinstance(detail, dict), f"detail אינו מובנה: {detail!r}"
    orgs = detail.get("organizations")
    assert isinstance(orgs, list) and orgs, "אין רשימת ארגונים לבחירה"
    assert all("id" in o and "name" in o for o in orgs), orgs


def test_explicit_header_still_works(client, orgless_super, owner):
    """השער מחייב בחירה — הוא אינו חוסם סופר-אדמין שבחר."""
    target = owner["user"]["organization_id"]
    headers = {**orgless_super, "X-Active-Org-Id": str(target)}

    resp = _integration_status(client, headers)

    assert resp.status_code == 200, resp.text
    assert resp.json()["organization_id"] == target


def test_super_admin_with_own_org_is_unaffected(client):
    """רגרסיה: סופר-אדמין שנרשם רגיל ויש לו ארגון — ממשיך לעבוד בלי כותרת."""
    resp = client.post("/api/admin/auth/register", json={
        "email": "super-with-org@example.com",
        "password": "secret123",
        "full_name": "Super With Org",
    })
    assert resp.status_code == 201, resp.text
    own_org = resp.json()["user"]["organization_id"]
    headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == "super-with-org@example.com").first()
        user.role = UserRole.SUPER_ADMIN
        db.commit()
    finally:
        db.close()

    resp = _integration_status(client, headers)

    assert resp.status_code == 200, resp.text
    assert resp.json()["organization_id"] == own_org


def test_auth_bypass_still_reaches_org_scoped_routes_after_choosing(client, owner, monkeypatch):
    """QA מקומי חייב להישאר עביר.

    משתמש ה-bypass הוא SUPER_ADMIN בלי `organization_id` — כלומר בדיוק
    המסלול שנחסם. הוא נחסם **פעם אחת**, בוחר, וממשיך. אם זה היה נשבר,
    `AUTH_BYPASS` היה מפסיק לשמש כמסלול QA (ראו docs/AUTH_ROADMAP.md).
    """
    from cfo.api import dependencies
    from cfo.models import UserRole as _Role

    monkeypatch.setattr(dependencies.settings, "auth_bypass_enabled", True)
    target = owner["user"]["organization_id"]

    # `_get_or_create_auth_bypass_user` מחזיר את ה-SUPER_ADMIN הראשון
    # הקיים, ולכן ייתכן שיש לו ארגון משלו. שתי ההתנהגויות תקינות —
    # קיבוע אחת מהן היה יוצר טסט תלוי-סדר.
    db = SessionLocal()
    try:
        resolved = (
            db.query(User)
            .filter(User.role == _Role.SUPER_ADMIN, User.is_active.is_(True))
            .first()
        )
        has_own_org = resolved is not None and resolved.organization_id is not None
    finally:
        db.close()

    first = client.get("/api/integration/status")
    if has_own_org:
        assert first.status_code == 200, first.text
    else:
        assert first.status_code == NEEDS_ORG_STATUS, first.text

    # מה שחייב להתקיים תמיד: אחרי בחירה מפורשת, QA מקומי עביר.
    chosen = client.get("/api/integration/status",
                        headers={"X-Active-Org-Id": str(target)})

    assert chosen.status_code == 200, chosen.text
    assert chosen.json()["organization_id"] == target


def test_non_super_without_org_is_still_refused(client):
    """משתמש רגיל בלי ארגון נחסם כמקודם — ולא מקבל את בורר הארגונים,
    שהוא מידע חוצה-ארגונים."""
    resp = client.post("/api/admin/auth/register", json={
        "email": "orgless-plain@example.com",
        "password": "secret123",
        "full_name": "Orgless Plain",
    })
    assert resp.status_code == 201, resp.text
    headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == "orgless-plain@example.com").first()
        user.organization_id = None
        db.commit()
    finally:
        db.close()

    resp = _integration_status(client, headers)

    assert resp.status_code == 403, resp.text
    assert "organizations" not in str(resp.json().get("detail", "")), (
        "רשימת הארגונים דלפה למשתמש שאינו סופר-אדמין"
    )
