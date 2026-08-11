"""יכולות ברמת חברת המשרד (CompanyID 844329067).

עד 11/08/2026 היו לרצף רק הרשאות פר-תיק. מפתח חברת ההנה"ח וניהול
המשרד פותח פעולות שאין להן משמעות ברמת תיק בודד — מכסות החשבון, פרטי
חברות בפורטל, ורשימת מסמכים חוצת-תיקים.

**הכלל המרכזי:** פעולה ברמת משרד בלי מפתח משרד נכשלת בגלוי ואינה
נופלת חזרה ל-`sumit_api_key`. נפילה כזו הייתה שולחת קריאה עם הרשאה
שגויה, או — גרוע יותר — מחזירה נתונים של תיק לקוח בודד כאילו הם של
המשרד כולו.

מה שמפתח המשרד **אינו** פותח: קריאת מנות, פקודות יומן, או סטטוס תיק.
`Books (Transactions)` חושף endpoint אחד — `createbatch`, כותב בלבד.
זו מגבלה של SUMIT ולא של ההרשאה.
"""
from __future__ import annotations

from typing import Any


class OfficeCredentialsMissing(RuntimeError):
    """אין הרשאות ברמת משרד. הפעולה נעצרה ולא נשלחה עם מפתח אחר."""


OFFICE_TASKS: dict[str, dict[str, Any]] = {
    "account_quotas": {
        "capability": "list_quotas",
        "endpoint": "/website/companies/listquotas/",
        "writes": False,
        "description_he": "מכסות החשבון — רישיונות הנה\"ח, מיילים, אחסון, אובליגו",
        "answers_he": "כמה תיקים מחויבים בפועל, והאם יש חסימת אובליגו",
    },
    "company_details": {
        "capability": "get_company_details",
        "endpoint": "/website/companies/getdetails/",
        "writes": False,
        "description_he": "פרטי חברה בפורטל המשרד",
        "answers_he": "איזה עסק מחובר לאיזה תיק",
    },
    "office_documents": {
        "capability": "list_documents",
        "endpoint": "/accounting/documents/list/",
        "writes": False,
        "description_he": "מסמכים ברמת המשרד",
        "answers_he": "אילו מסמכים קיימים בתיקי המשרד",
    },
    # --- פעולות כתיבה: כולן בלתי-הפיכות אצל הספק ---
    "create_client_company": {
        "capability": "create_company",
        "endpoint": "/website/companies/create/",
        "writes": True,
        "description_he": "פתיחת עסק/ארגון חדש בפורטל המשרד",
        "answers_he": "קליטת לקוח חדש בלי מסך",
        "warning_he": (
            "יוצר ישות חדשה ב-SUMIT. לפני יצירה יש לוודא שאין עסק קיים "
            "לאותו ח.פ — ביבוא של עומר ועודד נבחר במכוון 'חיבור לעסק "
            "קיים' כדי לא להקים כפיל."
        ),
    },
    "update_client_company": {
        "capability": "update_company",
        "endpoint": "/website/companies/update/",
        "writes": True,
        "description_he": "עדכון פרטי עסק בפורטל",
        "answers_he": "תיקון שם, ח.פ או פרטי קשר בלי מסך",
    },
    "install_applications": {
        "capability": "install_applications",
        "endpoint": "/website/companies/installapplications/",
        "writes": True,
        "description_he": "התקנת מודולים לעסק (הנה\"ח, חשבוניות, סליקה)",
        "answers_he": "הפעלת יכולת חסרה אצל לקוח",
        "warning_he": (
            "התקנת מודול עשויה לשנות את המסלול והחיוב. `listquotas` לפני "
            "ואחרי מראה את ההשפעה בפועל."
        ),
    },
    "grant_permission": {
        "capability": "set_permission",
        "endpoint": "/website/permissions/set/",
        "writes": True,
        "description_he": "הענקת הרשאה למשתמש בעסק",
        "answers_he": "חיבור משרד הנה\"ח או עובד לתיק",
        "warning_he": (
            "מרכז הידע: \"לא ניתן להעניק הרשאה לשני משרדי רו\"ח בו-זמנית — "
            "חובה **להסיר** את הישן לפני הוספת החדש.\" הענקה לפני הסרה "
            "תיכשל או תשאיר מצב שגוי."
        ),
    },
    "revoke_permission": {
        "capability": "remove_permission",
        "endpoint": "/website/permissions/remove/",
        "writes": True,
        "description_he": "הסרת הרשאה ממשתמש",
        "answers_he": "ניתוק משרד הנה\"ח קודם — התנאי להחלפת משרד",
    },
    "create_user": {
        "capability": "create_user",
        "endpoint": "/website/users/create/",
        "writes": True,
        "description_he": "יצירת משתמש והענקת הרשאות לעסק הנוכחי",
        "answers_he": "פתיחת גישה ללקוח או לעובד",
    },
    "login_redirect": {
        "capability": "user_login_redirect",
        "endpoint": "/website/users/loginredirect/",
        "writes": False,
        "description_he": "כתובת כניסה למשתמש בלי חשיפת סיסמה ב-URL",
        "answers_he": "מעבר לפורטל בהקשר של לקוח",
        "warning_he": (
            "דורש EmailAddress+Password של המשתמש — הוא אינו עוקף סיסמה "
            "אלא רק לא חושף אותה בכתובת. ה-endpoint גם אינו מאמת את "
            "הפרטים, ולכן טוקן ייווצר גם לפרטים שגויים."
        ),
    },
}


def office_credentials() -> dict[str, str]:
    """הרשאות חברת המשרד, או חריגה.

    honest-null: אין נפילה חזרה ל-`sumit_api_key`. הגדרה חלקית (מפתח
    בלי CompanyID או להפך) נחשבת גם היא חוסר — עדיף להיכשל כאן מאשר
    לשלוח קריאה חלקית שתיכשל אצל הספק בהודעה עמומה.
    """
    from ..config import settings

    api_key = getattr(settings, "sumit_office_api_key", None)
    company_id = getattr(settings, "sumit_office_company_id", None)
    if not api_key or not company_id:
        missing = [
            name
            for name, value in (
                ("SUMIT_OFFICE_API_KEY", api_key),
                ("SUMIT_OFFICE_COMPANY_ID", company_id),
            )
            if not value
        ]
        raise OfficeCredentialsMissing(
            f"חסרות הרשאות ברמת משרד: {', '.join(missing)}. "
            "מפתח של תיק בודד אינו תחליף — פעולה ברמת משרד תיכשל או "
            "תחזיר נתונים של תיק אחד כאילו הם של המשרד."
        )
    return {"api_key": api_key, "company_id": company_id}


def office_tasks_status() -> dict[str, Any]:
    """מה זמין ברמת המשרד ומה חסום.

    **אינו מחזיר את המפתח.** הסטטוס מגיע למסכי אדמין וללוגים; ה-
    CompanyID אינו סוד, המפתח כן.
    """
    try:
        creds = office_credentials()
        configured = True
        blocked: list[str] = []
        company_id = creds["company_id"]
    except OfficeCredentialsMissing:
        configured = False
        blocked = ["sumit_office_credentials"]
        company_id = None

    return {
        "configured": configured,
        "company_id": company_id,
        "tasks": [
            {
                "task": name,
                "capability": task["capability"],
                "endpoint": task["endpoint"],
                "description_he": task["description_he"],
                "answers_he": task["answers_he"],
                "writes": task["writes"],
                # כתיבה ברמת משרד היא בלתי-הפיכה אצל הספק — יצירת ארגון,
                # הענקת/הסרת הרשאה, התקנת מודול. אפס אוטונומיה.
                "requires_approval": task["writes"],
                "executable": configured,
                "blocked_by": list(blocked),
                **({"warning_he": task["warning_he"]} if "warning_he" in task else {}),
            }
            for name, task in OFFICE_TASKS.items()
        ],
        "not_available_he": (
            "קריאת מנות, פקודות יומן וסטטוס תיק אינם נגישים ב-API של SUMIT "
            "בשום הרשאה — Books חושף רק createbatch (כתיבה)."
        ),
    }
