"""מפתח המשרד מוגבל לתיק המשרד — ולא משרת את תיקי הלקוחות.

**נמדד חי מול SUMIT ב-18/08/2026**, בקריאות חינמיות בלבד
(`listquotas`, שאומתה כלא-מחויבת ע"י מדידת המונה לפני ואחרי):

    מפתח משרד + תיק המשרד (844329067)  → ✓ מכסה 0/50
    מפתח משרד + org1 (439924597)       → ✗ Invalid Credentials
    מפתח משרד + org2 (642076960)       → ✗ Invalid Credentials
    מפתח משרד + org5 (1999386278)      → ✗ Invalid Credentials

**זה סותר טענה שהייתה בקוד.** `office_service.set_office_credentials`
תיעד: "One SUMIT key serves all company files — each file just supplies
its own CompanyID". זה **אינו נכון** — SUMIT דוחה את הצמד מיד.

המשמעות מעשית ולא תיאורטית: מי שיסתמך על התיעוד ההוא יבנה מסלול שמניח
מפתח אחד לכל התיקים, והוא ייכשל ב-`Invalid Credentials` בפרוד. אישורים
פר-תיק (`integration_connections.credentials_encrypted`) נשארים הכרח.

**מה כן נותן מפתח המשרד:** חשבון עם מכסה **נפרדת** (0/50 מול המכסה של
כל לקוח). קריאות ברמת משרד אינן אוכלות את מכסת הלקוח — וזו הסיבה
היחידה שהוא שווה החזקה.
"""
import inspect

from cfo.services import office_service


def test_the_docstring_no_longer_claims_one_key_serves_all():
    """הטענה השגויה תוקנה. טסט על תיעוד נראה מוזר — אבל התיעוד הזה הוא
    מה שמכתיב איך מישהו יבנה את המסלול הבא, והוא היה שגוי."""
    src = inspect.getsource(office_service.set_office_credentials)

    assert "serves all company files" not in src, (
        "התיעוד עדיין טוען שמפתח אחד משרת את כל התיקים — נמדד שהוא לא"
    )


def test_the_measured_scope_is_documented():
    """הממצא חייב להישאר ליד הקוד, לא רק בתמליל שיחה."""
    src = inspect.getsource(office_service.set_office_credentials)

    assert "Invalid Credentials" in src or "תיק המשרד בלבד" in src


def test_per_client_credentials_remain_the_resolution_path():
    """שער נגדי: אם מישהו יחליף את מסלול האישורים למפתח משרד יחיד,
    הסנכרון ייפול לכל הלקוחות. `_resolve_sumit_key` חייב להמשיך לקרוא
    את החיבור המוצפן פר-ארגון."""
    from cfo.api.routes import cron

    src = inspect.getsource(cron._resolve_sumit_key)
    assert "IntegrationConnection" in src
    assert "decrypt_credentials" in src
