"""הרשאות SUMIT ברמת חברת המשרד (CompanyID 844329067).

עד עכשיו היו רק `SUMIT_API_KEY`/`SUMIT_COMPANY_ID` — מפתח ברמת ארגון
בודד. פורטל ההנה"ח של המשרד הוא ישות אחרת: הוא מחזיק את כל התיקים,
ו-`SUMIT_BOOKS_AMIT_PORAT.md` השאיר את זה כשאלה פתוחה — "איזה API key
מורשה ל-DatabaseID של התיק, של חברת ה-org או של חברת המשרד?"

הפרדה מפורשת מונעת את התאונה המסוכנת: דריסת המפתח של org1 (עמית פורת,
CompanyID 439924597) במפתח המשרד, מה שהיה מפנה את הסנכרון של תיק הלקוח
לחברה הלא נכונה.
"""
from cfo.config import Settings


def test_office_credentials_are_separate_fields():
    settings = Settings()

    assert hasattr(settings, "sumit_office_api_key")
    assert hasattr(settings, "sumit_office_company_id")


def test_office_credentials_default_to_none_not_to_the_org_key():
    """honest-null: בלי הגדרה מפורשת אין מפתח משרד. נפילה חזרה ל-
    `sumit_api_key` הייתה שולחת קריאות ברמת משרד עם מפתח של תיק בודד."""
    settings = Settings(sumit_api_key="org-level-key", sumit_company_id="439924597")

    assert settings.sumit_office_api_key is None
    assert settings.sumit_office_company_id is None


def test_office_and_org_credentials_do_not_overwrite_each_other():
    settings = Settings(
        sumit_api_key="org-key",
        sumit_company_id="439924597",
        sumit_office_api_key="office-key",
        sumit_office_company_id="844329067",
    )

    assert settings.sumit_api_key == "org-key"
    assert settings.sumit_company_id == "439924597"
    assert settings.sumit_office_api_key == "office-key"
    assert settings.sumit_office_company_id == "844329067"
