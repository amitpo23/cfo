"""
מסווג הוצאות — קביעת קטגוריה אוטומטית
Expense classifier.

שני מקורות סיווג, לפי סדר עדיפות:
1. sumit_item_name — שם פריט ההוצאה ב-SUMIT (למשל "הוצאות נסיעה"). זהו האות
   האמין ביותר, כי שם הספק להוצאות שיובאו מ-SUMIT הוא לרוב גנרי ("ספק כללי").
2. שם ספק / תיאור / מספר חשבונית — סיווג מבוסס מילות-מפתח (עברית + אנגלית).
"""
from typing import Dict, List, Optional

# קטגוריה -> מילות מפתח (עברית + אנגלית). הסדר קובע עדיפות.
CATEGORY_KEYWORDS = {
    "rent": ["שכירות", "שכ\"ד", "שכ''ד", "דמי שכירות", "rent", "lease"],
    "salary": ["משכורת", "משכורות", "שכר עבודה", "תלוש", "salary", "payroll", "wage"],
    "utilities": ["חשמל", "מים", "גז", "ארנונה", "בזק", "סלולר", "אינטרנט", "טלפון", "אנרגיה",
                   "electric", "water", "utility", "internet", "phone", "hot", "partner", "cellcom"],
    "professional": ["רו\"ח", "רואה חשבון", "עו\"ד", "עורך דין", "יועץ", "ייעוץ", "הנהלת חשבונות",
                      "accountant", "lawyer", "legal", "consult", "audit", "bookkeep"],
    "marketing": ["שיווק", "פרסום", "קמפיין", "גוגל", "פייסבוק", "אינסטגרם",
                   "marketing", "advertis", "google", "facebook", "instagram", "ads"],
    "travel": ["נסיעות", "נסיעה", "דלק", "תדלוק", "חניה", "מונית", "רכבת", "טיסה", "מלון",
                "travel", "fuel", "gas station", "parking", "taxi", "flight", "hotel", "uber"],
    "equipment": ["ציוד", "מחשב", "מחשבים", "ריהוט", "מדפסת", "חומרה",
                   "equipment", "computer", "laptop", "furniture", "printer", "hardware"],
    "insurance": ["ביטוח", "פוליסה", "insurance", "policy"],
    "office": ["משרד", "מכתבים", "צילום", "office", "stationery"],
    "materials": ["חומרי גלם", "חומרים", "סחורה", "מלאי",
                   "materials", "raw material", "inventory", "goods", "stock"],
    "services": ["שירות", "שירותים", "מנוי", "תוכנה", "אחסון",
                  "service", "subscription", "software", "saas", "hosting", "cloud"],
}

# מיפוי שמות פריט של SUMIT -> קטגוריה. ההתאמה היא substring (מנוקה רווחים),
# כך ש"הוצאות נסיעה לחו\"ל" עדיין יתאים ל"נסיעה". הסדר קובע עדיפות.
SUMIT_ITEM_CATEGORY_MAP = [
    ("ציוד משרדי", "equipment"),
    ("ריהוט", "equipment"),
    ("מחשוב", "equipment"),
    ("מחשב", "equipment"),
    ("ציוד", "equipment"),
    ("הוצאות נסיעה", "travel"),
    ("נסיעה", "travel"),
    ("נסיעות", "travel"),
    ("דלק", "travel"),
    ("רכב", "travel"),
    ("חניה", "travel"),
    ("אנרגיה", "utilities"),
    ("חשמל", "utilities"),
    ("מים", "utilities"),
    ("טלפון", "utilities"),
    ("תקשורת", "utilities"),
    ("שכירות", "rent"),
    ("שכ\"ד", "rent"),
    ("ביטוח", "insurance"),
    ("פרסום", "marketing"),
    ("שיווק", "marketing"),
    ("מקצועי", "professional"),
    ("ייעוץ", "professional"),
    ("יעוץ", "professional"),
    ("משפטי", "professional"),
    ("משפט", "professional"),
    ("הנהלת חשבונות", "professional"),
    ("רו\"ח", "professional"),
    ("עו\"ד", "professional"),
    ("שכר", "salary"),
    ("משכורת", "salary"),
    ("הוצאות משרד", "office"),
    ("משרד", "office"),
    ("קופה קטנה", "petty_cash"),
    ("מלאי", "materials"),
    ("סחורה", "materials"),
    ("חומרי גלם", "materials"),
    ("תוכנה", "services"),
    ("מנוי", "services"),
    ("שירות", "services"),
    # פריטים גנריים שאין בהם מידע סיווג ממשי
    ("הוצאות כלליות", "other"),
    ("כללי", "other"),
]

VALID_CATEGORIES = set(CATEGORY_KEYWORDS.keys()) | {"office", "petty_cash", "other"}

# שמות תצוגה בעברית לקטגוריות המובנות — משמש את GET /expenses/categories כדי
# להציג את הכרטיסים המובנים לצד הכרטיסים המותאמים אישית של הארגון.
CATEGORY_NAMES_HE: Dict[str, str] = {
    "rent": "שכירות",
    "salary": "משכורות",
    "utilities": "חשמל/מים/תקשורת",
    "professional": "שירותים מקצועיים",
    "marketing": "שיווק ופרסום",
    "travel": "נסיעות ורכב",
    "equipment": "ציוד",
    "insurance": "ביטוח",
    "office": "הוצאות משרד",
    "materials": "חומרי גלם/סחורה",
    "services": "שירותים ומנויים",
    "petty_cash": "קופה קטנה",
    "other": "אחר",
}


def _classify_by_sumit_item(item_name: str) -> Optional[str]:
    """מיפוי שם פריט SUMIT -> קטגוריה. מחזיר None אם לא נמצאה התאמה."""
    text = (item_name or "").strip().lower()
    if not text:
        return None
    for needle, category in SUMIT_ITEM_CATEGORY_MAP:
        if needle.lower() in text:
            return category
    return None


def classify_expense(
    supplier_name: Optional[str] = None,
    description: Optional[str] = None,
    invoice_number: Optional[str] = None,
    sumit_item_name: Optional[str] = None,
    org_categories: Optional[List[Dict]] = None,
) -> str:
    """מחזיר קטגוריה (אחת מ-VALID_CATEGORIES, או מפתח כרטיס מותאם אישית).
    ברירת מחדל: 'other'.

    עדיפות: שם פריט SUMIT -> מילות מפתח של כרטיסים מותאמים אישית לארגון
    (org_categories) -> מילות מפתח מובנות בשם ספק/תיאור/חשבונית.

    org_categories: רשימת dict-ים בצורה {"key": ..., "keywords": [...]} —
    הכרטיסים המותאמים אישית של הארגון (ExpenseCategory). מתקבלת כפרמטר
    ולא נטענת כאן מה-DB כדי לשמור על הפונקציה הזו טהורה וללא תלות ב-DB.
    """
    # 1. שם פריט SUMIT — האות האמין ביותר
    by_item = _classify_by_sumit_item(sumit_item_name) if sumit_item_name else None
    if by_item and by_item != "other":
        return by_item

    # 2. מילות מפתח בשם ספק / תיאור / חשבונית
    text = " ".join(filter(None, [supplier_name, description, invoice_number])).lower()
    if text.strip():
        # 2א. כרטיסים מותאמים אישית לארגון — גוברים על המובנות
        for cat in org_categories or []:
            keywords = cat.get("keywords") or []
            if any(str(kw).lower() in text for kw in keywords):
                return cat["key"]
        # 2ב. מילות מפתח מובנות
        for category, keywords in CATEGORY_KEYWORDS.items():
            if any(kw.lower() in text for kw in keywords):
                return category

    # 3. אם פריט SUMIT מיפה במפורש ל-"other" (פריט גנרי) — נשתמש בו לפני ברירת מחדל
    if by_item:
        return by_item
    return "other"
