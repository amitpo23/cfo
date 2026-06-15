"""
מסווג הוצאות — קביעת קטגוריה אוטומטית
Expense classifier.

שני מקורות סיווג, לפי סדר עדיפות:
1. sumit_item_name — שם פריט ההוצאה ב-SUMIT (למשל "הוצאות נסיעה"). זהו האות
   האמין ביותר, כי שם הספק להוצאות שיובאו מ-SUMIT הוא לרוב גנרי ("ספק כללי").
2. שם ספק / תיאור / מספר חשבונית — סיווג מבוסס מילות-מפתח (עברית + אנגלית).
"""
from typing import Optional

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
) -> str:
    """מחזיר קטגוריה (אחת מ-VALID_CATEGORIES). ברירת מחדל: 'other'.

    עדיפות: שם פריט SUMIT -> מילות מפתח בשם ספק/תיאור/חשבונית.
    """
    # 1. שם פריט SUMIT — האות האמין
    by_item = _classify_by_sumit_item(sumit_item_name) if sumit_item_name else None
    if by_item and by_item != "other":
        return by_item

    # 2. מילות מפתח בשם ספק / תיאור
    text = " ".join(filter(None, [supplier_name, description, invoice_number])).lower()
    if text.strip():
        for category, keywords in CATEGORY_KEYWORDS.items():
            if any(kw.lower() in text for kw in keywords):
                return category

    # 3. אם פריט SUMIT מיפה במפורש ל-"other" (פריט גנרי) — נשתמש בו לפני ברירת מחדל
    if by_item:
        return by_item
    return "other"
