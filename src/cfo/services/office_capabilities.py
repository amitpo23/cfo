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
                "executable": configured,
                "blocked_by": list(blocked),
            }
            for name, task in OFFICE_TASKS.items()
        ],
        "not_available_he": (
            "קריאת מנות, פקודות יומן וסטטוס תיק אינם נגישים ב-API של SUMIT "
            "בשום הרשאה — Books חושף רק createbatch (כתיבה)."
        ),
    }
