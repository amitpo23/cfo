"""מפת משימות — מה מושקו יכול לבצע, ומה חוסם אותו בכל ארגון.

`capability_catalog` עונה "אילו endpoints קיימים" — 172 מהם. זה קטלוג,
לא יכולת ביצוע. מי שמקבל משימה בשפה עסקית ("תוציא חשבונית", "תבדוק אם
ההוצאה שולמה", "תתייק את זה") צריך לדעת **איזה כלי מבצע אותה, האם הוא
כותב, ומה חסר בארגון הזה כדי להפעילו**.

הכלל שנגזר מהבהרת הבעלים (10/08/2026): ארגון בלי חיבור לספק — היכולות
שתלויות בו מוחזרות כ**חסומות עם הסיבה**, ולא נעלמות ולא מוחזרות כזמינות.
מי שקורא רואה שהיכולת קיימת ומה חסר כדי להפעילה.
"""
from __future__ import annotations

from typing import Any, Optional

# משימה → יכולת הביצוע שלה.
#
# `capability` הוא שם המתודה בקטלוג (SUMIT/Open Finance) או השירות
# הפנימי של רצף. `requires` הוא הספק שבלעדיו אי אפשר — משימות של רצף
# עצמה אינן דורשות דבר.
TASKS: dict[str, dict[str, Any]] = {
    "issue_document": {
        "system": "sumit",
        "capability": "create_document",
        "writes": True,
        "requires": "sumit",
        "description_he": "הוצאת מסמך (חשבונית/קבלה/חשבונית מס)",
    },
    "cancel_document": {
        "system": "sumit",
        "capability": "cancel_document",
        "writes": True,
        "requires": "sumit",
        "description_he": "ביטול מסמך קיים",
        "note_he": "ביטול בסאמיט אינו מבטל בשע\"מ — נדרשת פעולה נפרדת מול הרשות.",
    },
    "intake_expense": {
        "system": "sumit",
        "capability": "add_expense",
        "writes": True,
        "requires": "sumit",
        "description_he": "קליטת הוצאה למודול העסק",
    },
    "file_expense": {
        "system": "rezef",
        "capability": "expense_account_filing.file_expense_to_account",
        "writes": True,
        "requires": None,
        "description_he": "תיוק הוצאה לכרטיס באינדקס החשבונות של התיק",
    },
    "suggest_filing": {
        "system": "rezef",
        "capability": "expense_account_filing.suggest_accounts_for_expense",
        "writes": False,
        "requires": None,
        "description_he": "הצעת כרטיסים לתיוק לפי שם הספק",
    },
    "cashflow": {
        "system": "rezef",
        "capability": "ai_chat_tools.get_cashflow",
        "writes": False,
        "requires": None,
        "description_he": "תזרים מזומנים",
    },
    "check_payment_in_bank": {
        "system": "open_finance",
        "capability": "list_transactions",
        "writes": False,
        "requires": "open_finance",
        "description_he": "בדיקה בבנק אם הוצאה שולמה",
    },
    "pay_supplier": {
        "system": "open_finance",
        "capability": "create_payment",
        "writes": True,
        "requires": "open_finance",
        "description_he": "העברה לספק",
        "note_he": "פעולה בלתי-הפיכה — עוברת דרך מנגנון האישורים.",
    },
    "collection_status": {
        "system": "rezef",
        "capability": "ai_chat_tools.get_ar_aging",
        "writes": False,
        "requires": None,
        "description_he": "מצב גבייה — גיול חובות לקוחות",
    },
    "vat_position": {
        "system": "rezef",
        "capability": "ai_chat_tools.get_vat_position",
        "writes": False,
        "requires": None,
        "description_he": "מצב מע\"מ לתקופה",
    },
}


def resolve_task(task: str) -> Optional[dict[str, Any]]:
    """היכולת שמבצעת משימה, או None.

    honest-null: משימה שאינה במפה מחזירה None ולא ניחוש לפי דמיון שם.
    ניחוש היה מפעיל פעולה לא נכונה על נתוני לקוח.
    """
    entry = TASKS.get(task)
    if entry is None:
        return None
    return {
        "task": task,
        **entry,
        # כל כתיבה דורשת אישור — אפס אוטונומיה בבלתי-הפיך.
        "requires_approval": entry["writes"],
    }


def executable_tasks_for_organization(organization_id: int) -> list[dict[str, Any]]:
    """כל המשימות, עם ציון מה ניתן לביצוע בארגון הזה ומה חוסם.

    הרשימה **מלאה תמיד**. משימה חסומה מופיעה עם `blocked_by` ולא
    נעלמת — השמטה שקטה גורמת לקורא לחשוב שהיכולת אינה קיימת, במקום
    להבין שחסר חיבור.
    """
    from ..models import IntegrationConnection
    from . import tenant_routing

    with tenant_routing.session_for(organization_id) as db:
        active = {
            row.source
            for row in db.query(IntegrationConnection)
            .filter(
                IntegrationConnection.organization_id == organization_id,
                IntegrationConnection.status == "active",
            )
            .all()
        }

    results = []
    for name, entry in TASKS.items():
        required = entry["requires"]
        blocked = [required] if required and required not in active else []
        results.append(
            {
                "task": name,
                "system": entry["system"],
                "capability": entry["capability"],
                "description_he": entry["description_he"],
                "writes": entry["writes"],
                "requires_approval": entry["writes"],
                "executable": not blocked,
                "blocked_by": blocked,
                **({"note_he": entry["note_he"]} if "note_he" in entry else {}),
            }
        )
    return results
