"""ריצת סנכרון אחת ביום — **לכל מפתח**, לא לכל ארגון.

**ההנחיה (17/08/2026).** הבעלים: "אל תריץ יותר משאילתא ביום מכל מפתח וגם
משם תעשה מראה לבסיס נתונים שלנו ורק עדכונים תחזיר בחזרה - פעם ביום".
בהבהרה נבחר: **ריצת סנכרון אחת ביום למפתח** (ולא בקשת HTTP אחת — ריצה
מוציאה עשרות בקשות בגלל עימוד וריבוי ישויות, ומגבלה מילולית הייתה שוברת
את הסנכרון).

**הפער שהתגלה.** `SumitRequestLimiter.claim` תובע חלון יומי לפי
`scope_key=f"org:{organization_id}"` — כלומר **לפי ארגון**. אבל
`SUMIT_OFFICE_API_KEY` הוא הגדרה גלובלית אחת המשרתת את כל הארגונים
(`office_capabilities.py`). לכן N ארגונים יכולים כל אחד לשרוף מכסה מלאה
על **אותו מפתח** — בדיוק מה שהמגבלה נועדה למנוע, והמכסה בתשלום היא 50.

**הכלל:** החלון נתבע לפי טביעת-אצבע של המפתח. המפתח עצמו לעולם אינו
נשמר ואינו נרשם — רק hash.
"""
import pytest

from cfo.database import SessionLocal
from cfo.models import ProviderRequestBudget
from cfo.services import sumit_request_budget as budget


KEY_A = "9f3c1a7e-2b44-4d18-9c6a-7e5b1d0f8a23"
KEY_B = "1a2b3c4d-5e6f-7a8b-9c0d-1e2f3a4b5c6d"


@pytest.fixture(autouse=True)
def _clear_request_budgets(client):
    """`client` יוצר את הסכימה; הניקוי מונע דליפת חלונות בין טסטים —
    חלון יומי שנשאר תפוס היה מכשיל את הטסט הבא באופן תלוי-סדר."""
    db = SessionLocal()
    try:
        db.query(ProviderRequestBudget).delete()
        db.commit()
        yield
    finally:
        db.query(ProviderRequestBudget).delete()
        db.commit()
        db.close()


# ==================================================================== #
# טביעת האצבע — המפתח לא נשמר
# ==================================================================== #
def test_the_fingerprint_never_contains_the_key():
    """מפתח שנשמר בטבלה או בהודעת שגיאה הוא מפתח שדלף. `scope_key` נכתב
    ל-DB ומופיע בלוגים, ולכן חייב להיות חד-כיווני."""
    fp = budget.key_fingerprint(KEY_A)

    assert KEY_A not in fp
    assert KEY_A[:8] not in fp
    assert fp.startswith("key:")


def test_different_keys_get_different_fingerprints():
    assert budget.key_fingerprint(KEY_A) != budget.key_fingerprint(KEY_B)


def test_the_same_key_always_maps_to_the_same_window():
    """אם ה-fingerprint לא יציב בין תהליכים, כל instance של Vercel היה
    תובע חלון משלו והמגבלה לא הייתה קיימת."""
    assert budget.key_fingerprint(KEY_A) == budget.key_fingerprint(KEY_A)


# ==================================================================== #
# החלון היומי
# ==================================================================== #
def test_the_first_sync_run_of_the_day_is_allowed():
    budget.claim_daily_sync_run(KEY_A, organization_id=1)


def test_the_second_run_on_the_same_key_is_refused(monkeypatch):
    """הלב של ההנחיה."""
    budget.claim_daily_sync_run(KEY_B, organization_id=1)

    with pytest.raises(budget.SumitRequestBudgetExceeded):
        budget.claim_daily_sync_run(KEY_B, organization_id=1)


def test_a_second_organization_cannot_spend_the_same_key_again():
    """**התרחיש שהוליד את התיקון.** מפתח המשרד משרת את כל הארגונים. עם
    scope לפי ארגון, org2 היה מקבל ריצה נוספת על אותו מפתח."""
    office_key = "0fficeKEY-shared-across-every-organization"

    budget.claim_daily_sync_run(office_key, organization_id=1)

    with pytest.raises(budget.SumitRequestBudgetExceeded):
        budget.claim_daily_sync_run(office_key, organization_id=2)


def test_a_different_key_is_not_blocked_by_another_keys_run():
    """שער נגדי: המגבלה היא פר-מפתח. אם היא הייתה גלובלית, תיק אחד היה
    חוסם את כל השאר וכל הלקוחות היו מפסיקים להסתנכרן."""
    budget.claim_daily_sync_run("key-tenant-one", organization_id=1)

    budget.claim_daily_sync_run("key-tenant-two", organization_id=2)


def test_an_empty_key_is_refused_rather_than_sharing_one_window():
    """מפתח ריק/None היה ממפה את כל הארגונים לאותו hash — כלומר ארגון
    בלי מפתח היה חוסם את כולם. fail-closed, ובקול."""
    for bad in ("", "   ", None):
        with pytest.raises(budget.SumitRequestBudgetError):
            budget.claim_daily_sync_run(bad, organization_id=1)


def test_the_limit_is_one(monkeypatch):
    """המספר עצמו הוא ההנחיה — לא ערך שנשחק בהדרגה."""
    assert budget.DAILY_SYNC_RUNS_PER_KEY == 1


# ==================================================================== #
# החיווט — שער שלא מחווט אינו שער
# ==================================================================== #
def test_the_sync_cron_actually_claims_the_per_key_window():
    """הטסטים למעלה מוכיחים שהפונקציה חוסמת. זה מוכיח שמישהו קורא לה.

    זהו הכשל שחזר בסשן הזה יותר מפעם אחת: שער נכתב, נבדק, עבר — ולא היה
    על המסלול. `getdetails` היה מגודר בזמן ש-`getpdf` לא; מסמכי ה-KB
    נכתבו ולא נרשמו.
    """
    import inspect

    from cfo.api.routes import cron

    source = inspect.getsource(cron.scheduled_sync_sumit)
    assert "_per_key_daily_gate" in source, (
        "ריצת הסנכרון היומית אינה תובעת את חלון המפתח — המגבלה אינה על המסלול"
    )

    gate = inspect.getsource(cron._per_key_daily_gate)
    assert "claim_daily_sync_run" in gate


def test_the_key_resolver_matches_the_one_the_sync_actually_uses():
    """אם השער פותר מפתח אחד והריצה משתמשת באחר — נתבע חלון על מפתח
    שלא נשלח בו דבר, והמגבלה אינה חוסמת כלום. שני המסלולים חייבים לכבד
    את אותו כלל: אישורי-סביבה שייכים לארגון 1 בלבד."""
    import inspect

    from cfo.api.routes import cron

    resolver = inspect.getsource(cron._resolve_sumit_key)

    assert "api_credentials" in resolver
    assert "org_id == 1" in resolver, "כלל אישורי-הסביבה חסר — דליפה בין ארגונים"
