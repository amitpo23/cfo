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
    # סדר קריטי מכאן: fines/travel/vehicle_purchase נבדקים *לפני* vehicle כי
    # "רכב" הוא substring גם של "רכבת" (רכבת=רכב+ת, לא הרכב עצמו) וגם של
    # "רכישת רכב" (רכישה, לא הרכב עצמו), ו"חניה" הוא substring של "דוח חניה"
    # (קנס חניה — fines, לא vehicle). בלי הסדר הזה "נסיעה ברכבת" הייתה מסווגת
    # vehicle, ו"דוח חניה" הייתה מסווגת vehicle במקום fines.
    "fines": ["קנס", "דוח חניה", "עיצום", "משטרה"],
    "travel": ["נסיעות", "נסיעה", "מונית", "רכבת", "טיסה", "מלון",
                "travel", "taxi", "flight", "hotel", "uber"],
    "vehicle_purchase": ["רכישת רכב", "vehicle purchase"],
    "vehicle": ["רכב", "דלק", "תדלוק", "חניה", "פז", "סונול", "דור אלון", "טסט", "ליסינג",
                 "כביש 6", "vehicle", "fuel", "gas station", "parking"],
    "hospitality": ["מסעדה", "בית קפה", "ארומה", "קפה גרג", "רולדין", "restaurant", "cafe"],
    "refreshments": ["כיבוד", "קפה למשרד", "שתיה למשרד"],
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
    ("רכישת רכב", "vehicle_purchase"),  # לפני "רכב" — אחרת substring הופך vehicle
    ("דלק", "vehicle"),
    ("רכב", "vehicle"),
    ("חניה", "vehicle"),
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

# interest_authorities/donations/social_insurance_owner: אין להם מילות מפתח
# אוטומטיות (סיווג-שגוי של אלה הוא יקר — PERSONAL_DEDUCTION/NONE, ר'
# israeli_tax_rules.py) — נבחרים ידנית או דרך שם פריט SUMIT מפורש, ולכן
# אינם ב-CATEGORY_KEYWORDS, אך כן קטגוריות תקפות לאחסון/בחירה.
VALID_CATEGORIES = set(CATEGORY_KEYWORDS.keys()) | {
    "office", "petty_cash", "other",
    "interest_authorities", "donations", "social_insurance_owner",
}

# שמות תצוגה בעברית לקטגוריות המובנות — משמש את GET /expenses/categories כדי
# להציג את הכרטיסים המובנים לצד הכרטיסים המותאמים אישית של הארגון.
CATEGORY_NAMES_HE: Dict[str, str] = {
    "rent": "שכירות",
    "salary": "משכורות",
    "utilities": "חשמל/מים/תקשורת",
    "professional": "שירותים מקצועיים",
    "marketing": "שיווק ופרסום",
    "travel": "נסיעות",
    "vehicle": "רכב",
    "vehicle_purchase": "רכישת רכב",
    "hospitality": "אירוח",
    "refreshments": "כיבוד",
    "fines": "קנסות",
    "interest_authorities": "ריבית לרשויות",
    "donations": "תרומות",
    "social_insurance_owner": 'ב"ל/פנסיה בעלים',
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


def normalize_supplier_key(supplier_name: Optional[str]) -> str:
    """נרמול שם ספק להשוואה בין כלל נלמד לבין הוצאה חדשה: strip + הקטנת
    אותיות (case-fold). ספק None/ריק -> מחרוזת ריקה (לעולם לא מתאים לכלל).
    משמש גם את classifier_ml_training.py כדי לבנות את מפתחות הכלל הנלמד
    באותה צורה בדיוק שבה classify_expense מחפש אותם."""
    return (supplier_name or "").strip().lower()


def classify_expense_detailed(
    supplier_name: Optional[str] = None,
    description: Optional[str] = None,
    invoice_number: Optional[str] = None,
    sumit_item_name: Optional[str] = None,
    org_categories: Optional[List[Dict]] = None,
    learned_rules: Optional[Dict[str, str]] = None,
) -> Dict[str, Optional[str]]:
    """כמו classify_expense, אך מחזיר גם את מקור ההחלטה
    (classification_source) — לצורך שקיפות ובדיקות. classify_expense עצמה
    היא עטיפה דקה שמחזירה רק את ["category"], כדי שקריאה קיימת (str) לא
    תישבר בשום נקודת קריאה קיימת בקוד.

    סדר עדיפויות (מפורש — אין לשנות בלי לעדכן את התיעוד כאן):
      1. 'sumit_item'    — שם פריט SUMIT מפורש (לא גנרי). האות האמין ביותר,
                           קיים מאז ומעולם — לא נגעתי בעדיפות שלו.
      2. 'org_category'  — כרטיס מותאם אישית שהמשתמש הגדיר (מילות מפתח).
                           כלל *מפורש* של המשתמש — גובר תמיד על מה שנלמד
                           אוטומטית (סעיף 3) ועל מילות המפתח המובנות (סעיף 4).
      3. 'learned'        — כלל נלמד (learned_rules): מפה supplier_key (מנורמל
                           strip+lower) -> קטגוריה, שנבנתה מתוך >=3 תיקוני
                           משתמש לאותו ספק (ר' classifier_ml_training.
                           ClassifierMLTrainingService.get_learned_rules_map).
                           מתאים לפי שם ספק בלבד — לא substring בתיאור/
                           בחשבונית. **לעולם לא עוקף שם פריט SUMIT או כרטיס
                           מותאם אישית** (סעיפים 1-2) — זו בדיוק הדרישה שלא
                           לתת ללמידה האוטומטית לעקוף כלל מפורש של המשתמש.
      4. 'keyword'        — מילות מפתח מובנות (CATEGORY_KEYWORDS).
      5. 'sumit_item'/'default' — שם פריט SUMIT שמיפה במפורש ל-'other' (פריט
                           גנרי) גובר על ברירת המחדל הכללית; אחרת 'other'.

    learned_rules: מתקבל כפרמטר מוכן מראש (dict), ולא נטען כאן מה-DB — אותו
    עקרון בדיוק כמו org_categories (הפונקציה נשארת טהורה, ללא תלות ב-DB,
    וללא קריאה ל-analyze_feedback/get_learned_rules_map פר-הוצאה). הקורא
    האחראי על ריצת סיווג גורפת (למשל ExpenseFilingService.classify_pending)
    טוען את המפה פעם אחת לפני הלולאה ומעביר אותה לכל קריאה.
    """
    # 1. שם פריט SUMIT — האות האמין ביותר
    by_item = _classify_by_sumit_item(sumit_item_name) if sumit_item_name else None
    if by_item and by_item != "other":
        return {"category": by_item, "classification_source": "sumit_item"}

    text = " ".join(filter(None, [supplier_name, description, invoice_number])).lower()

    # 2. כרטיסים מותאמים אישית לארגון — כלל מפורש של המשתמש, גובר תמיד
    if text.strip():
        for cat in org_categories or []:
            keywords = cat.get("keywords") or []
            if any(str(kw).lower() in text for kw in keywords):
                return {"category": cat["key"], "classification_source": "org_category"}

    # 3. כלל נלמד — לפי שם ספק מנורמל בלבד, ורק אם לא נמצאה כבר התאמה מפורשת
    supplier_key = normalize_supplier_key(supplier_name)
    if supplier_key and learned_rules:
        learned_category = learned_rules.get(supplier_key)
        if learned_category:
            return {"category": learned_category, "classification_source": "learned"}

    # 4. מילות מפתח מובנות
    if text.strip():
        for category, keywords in CATEGORY_KEYWORDS.items():
            if any(kw.lower() in text for kw in keywords):
                return {"category": category, "classification_source": "keyword"}

    # 5. אם פריט SUMIT מיפה במפורש ל-"other" (פריט גנרי) — נשתמש בו לפני ברירת מחדל
    if by_item:
        return {"category": by_item, "classification_source": "sumit_item"}
    return {"category": "other", "classification_source": "default"}


def classify_expense(
    supplier_name: Optional[str] = None,
    description: Optional[str] = None,
    invoice_number: Optional[str] = None,
    sumit_item_name: Optional[str] = None,
    org_categories: Optional[List[Dict]] = None,
    learned_rules: Optional[Dict[str, str]] = None,
) -> str:
    """מחזיר קטגוריה (אחת מ-VALID_CATEGORIES, או מפתח כרטיס מותאם אישית).
    ברירת מחדל: 'other'.

    עדיפות: שם פריט SUMIT -> כרטיסים מותאמים אישית לארגון (org_categories)
    -> כלל נלמד (learned_rules) -> מילות מפתח מובנות. ר' תיעוד מלא ב-
    classify_expense_detailed (שהיא זו שמבצעת בפועל את הלוגיקה; פונקציה זו
    היא רק עטיפה שמחזירה את הקטגוריה כמחרוזת, לשמירת תאימות לאחור עם כל
    נקודות הקריאה הקיימות).

    org_categories: רשימת dict-ים בצורה {"key": ..., "keywords": [...]} —
    הכרטיסים המותאמים אישית של הארגון (ExpenseCategory). מתקבלת כפרמטר
    ולא נטענת כאן מה-DB כדי לשמור על הפונקציה הזו טהורה וללא תלות ב-DB.

    learned_rules: dict אופציונלי supplier_key (מנורמל) -> קטגוריה. ר'
    classify_expense_detailed לפירוט מלא על העדיפות והמקור.
    """
    return classify_expense_detailed(
        supplier_name=supplier_name,
        description=description,
        invoice_number=invoice_number,
        sumit_item_name=sumit_item_name,
        org_categories=org_categories,
        learned_rules=learned_rules,
    )["category"]
