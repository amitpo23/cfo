"""
מנוע חוקי המס הישראלי — הכרה במס הכנסה + ניכוי מע"מ תשומות, לפי קטגוריית הוצאה.

מקור האמת המשפטי: docs/bookkeeper_kb/01-income-tax-recognition.md (מס הכנסה)
ו-02-vat-input-deductibility.md (מע"מ תשומות) — נכתבו ע"י מוביל הצוות (רו"ח)
ומחייבים. המודול הזה *מקודד* אותם, לא ממציא כללים חדשים. `render_bridge_table_he`
מייצר טבלת-גשר בעברית שנשמרת ל-docs/bookkeeper_kb/03-classification-bridge.md
(דרך scripts/render_bookkeeper_kb.py) — כדי שהמסמך הקריא-לאדם וקוד-האמת לעולם
לא יסטו זה מזה.

עקרונות מכוננים (החלטות עיצוב שאושרו, ר' MEMORY):
1. Expense.vat_amount נשאר תמיד "raw" (המע"מ שעל גבי המסמך). vat_claimable הוא
   המע"מ *הנתבע* בפועל, אחרי שער-המסמך והיחס. רק המשפך הרגולטורי
   (financial_synthesis.select_vat_documents) קורא vat_claimable — שום מקום
   אחר לא משנה משמעות ל-vat_amount.
2. שער-המסמך קודם לכל שבר: קבלה בלבד -> 0 (יכול להיות מוכר במס הכנסה, אבל
   אין מע"מ לניכוי). מסמך לא ידוע -> None (הכרעה, לא ניחוש).
3. רכב הוא פר-רכב (VehicleProfile), לא פר-עסק — פרופיל חסר -> None.
4. honest-null: עמימות -> None -> תור הכרעה. לעולם לא ברירת מחדל מנוחשת.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum
from typing import Optional


class IncomeTaxTreatment(str, Enum):
    """אופן ההכרה בהוצאה לצורך מס הכנסה (סעיף 17 לפקודה ותקנותיו)."""

    FULL = "full"                        # מוכר 100%
    FORMULA = "formula"                   # נוסחה (higher-of רכב וכד') — formula_ref
    PARTIAL_FIXED = "partial_fixed"       # אחוז קבוע חלקי (למשל כיבוד 80%)
    NONE = "none"                         # לא מוכר בכלל (0%)
    DEPRECIATION = "depreciation"         # רכוש קבוע — מופחת, לא הוצאה שוטפת
    PERSONAL_DEDUCTION = "personal_deduction"  # ניכוי/זיכוי אישי, לא הוצאה עסקית


@dataclass(frozen=True)
class TaxRule:
    """כלל מס לקטגוריית הוצאה אחת."""

    category: str
    name_he: str
    income_tax: IncomeTaxTreatment
    income_tax_percent: Optional[Decimal]   # None כשה-treatment הוא FORMULA/DEPRECIATION בלי שיעור קבוע יחיד
    formula_ref: Optional[str]              # שם attribute ב-expense_deduction_service, או None
    input_vat_fraction: Optional[Decimal]   # 0 / 1/4 / 2/3 / 1, או None = תלוי-הקשר (הכרעה)
    sumit_account_default: Optional[int]    # ברירת מחדל מתרשים החשבונות של עמית פורת — ניתן לשינוי פר-ארגון
    evidence: frozenset[str]                # תיעוד נדרש לביסוס הניכוי
    citation_he: str                        # בסיס חוקי
    notes_he: str = ""


# ---------------------------------------------------------------------- #
# קבועי שבר מע"מ (תקנה 18: 2/3 עיקר-עסקי, 1/4 עיקר-פרטי)
# ---------------------------------------------------------------------- #
_FULL = Decimal("1")
_ZERO = Decimal("0")
_QUARTER = Decimal("1") / Decimal("4")
_TWO_THIRDS = Decimal("2") / Decimal("3")


# ספקים נטולי-מע"מ מבנית (KB02 §0): גם כשיש "חשבונית מס" — אין מע"מ בעסקה כלל.
SUPPLIER_KINDS_NO_VAT: frozenset[str] = frozenset(
    {"bank", "insurance", "government", "municipality", "salary", "exempt_dealer"}
)

# תקנה 14 — חריגים שבהם תשומות *רכישת* רכב כן מותרות במלואן.
_VEHICLE_PURCHASE_FULL_KINDS: frozenset[str] = frozenset(
    {"commercial", "taxi", "rental", "driving_school", "dealer_stock"}
)


def _rule(
    category: str,
    name_he: str,
    income_tax: IncomeTaxTreatment,
    *,
    income_tax_percent: Optional[Decimal] = None,
    formula_ref: Optional[str] = None,
    input_vat_fraction: Optional[Decimal],
    sumit_account_default: Optional[int],
    evidence: frozenset[str] = frozenset(),
    citation_he: str,
    notes_he: str = "",
) -> TaxRule:
    return TaxRule(
        category=category,
        name_he=name_he,
        income_tax=income_tax,
        income_tax_percent=income_tax_percent,
        formula_ref=formula_ref,
        input_vat_fraction=input_vat_fraction,
        sumit_account_default=sumit_account_default,
        evidence=evidence,
        citation_he=citation_he,
        notes_he=notes_he,
    )


_S17 = 'סעיף 17 לפקודת מס הכנסה'
_TAKANOT_1972 = 'תקנות מס הכנסה (ניכוי הוצאות מסוימות), תשל"ב-1972'

TAX_RULES: dict[str, TaxRule] = {
    "rent": _rule(
        "rent", "שכירות", IncomeTaxTreatment.FULL, income_tax_percent=Decimal("100"),
        input_vat_fraction=_FULL, sumit_account_default=90504,
        evidence=frozenset({"lease_agreement", "tax_invoice"}), citation_he=_S17,
        notes_he="שכ\"ד משרד ייעודי מוכר 100%. מע\"מ מלא בכפוף לחשבונית מס — "
                 "שכירות מגורים מספק פרטי לרוב ללא מע\"מ כלל (שער המסמך תופס זאת).",
    ),
    "salary": _rule(
        "salary", "משכורות", IncomeTaxTreatment.FULL, income_tax_percent=Decimal("100"),
        input_vat_fraction=_ZERO, sumit_account_default=None,
        evidence=frozenset({"payslip", "form_102"}), citation_he=_S17,
        notes_he="שכר עבודה מוכר 100% אך נטול מע\"מ מבנית לחלוטין. אין כרטיס 90xxx "
                 "ייעודי בתרשים החשבונות — נרשם דרך מודול השכר, לא כהוצאת-ספק.",
    ),
    "utilities": _rule(
        "utilities", "חשמל/מים/תקשורת", IncomeTaxTreatment.FULL, income_tax_percent=Decimal("100"),
        input_vat_fraction=_FULL, sumit_account_default=90505,
        evidence=frozenset({"tax_invoice"}), citation_he=_S17,
        notes_he="אין כרטיס ייעודי לחשמל/מים בתרשים — ברירת המחדל 90505 (אחזקה) "
                 "היא הקרוב ביותר; ניתן לשינוי פר-ארגון. תת-הקטגוריות טלפון/אינטרנט "
                 "כפופות לתקרות נפרדות (ר' KB01 §3) שאינן מיוצגות ברמת-קטגוריה זו.",
    ),
    "professional": _rule(
        "professional", "שירותים מקצועיים", IncomeTaxTreatment.FULL, income_tax_percent=Decimal("100"),
        input_vat_fraction=_FULL, sumit_account_default=90006,
        evidence=frozenset({"tax_invoice"}), citation_he=_S17,
        notes_he="רו\"ח/עו\"ד/יועץ — 90006 (ייעוץ). ייעוץ משפטי ספציפית יכול "
                 "להירשם גם ל-90004 (ייעוץ משפטי) לפי בחירת הארגון.",
    ),
    "marketing": _rule(
        "marketing", "שיווק ופרסום", IncomeTaxTreatment.FULL, income_tax_percent=Decimal("100"),
        input_vat_fraction=_FULL, sumit_account_default=90502,
        evidence=frozenset({"tax_invoice"}), citation_he=_S17,
    ),
    "travel": _rule(
        "travel", "נסיעות", IncomeTaxTreatment.FULL, income_tax_percent=Decimal("100"),
        input_vat_fraction=_FULL, sumit_account_default=90003,
        evidence=frozenset({"tax_invoice", "boarding_pass_or_hotel_invoice"}), citation_he=_TAKANOT_1972,
        notes_he="טיסות/מלונות/רכבת/מונית לצורכי נסיעת עבודה. אש\"ל (ארוחות בנסיעה) "
                 "כפוף לכלל נפרד בצד מס ההכנסה — 50% מהמתועד עד תקרה יומית "
                 "(ר' VERIFICATION_NEEDED) — אינו מיוצג כאן ברמת-קטגוריה. דלק/חניה/"
                 "תדלוק עברו לקטגוריית vehicle.",
    ),
    "equipment": _rule(
        "equipment", "ציוד", IncomeTaxTreatment.DEPRECIATION,
        input_vat_fraction=_FULL, sumit_account_default=90500,
        evidence=frozenset({"tax_invoice", "asset_register"}), citation_he=_S17,
        notes_he="מע\"מ תשומות מלא בכפוף לחשבונית מס. בצד מס ההכנסה: ציוד זול "
                 "(מתחת לסף ⚠️ ~₪1,200) נרשם כהוצאה שוטפת מלאה (FULL); מעל הסף "
                 "הופך רכוש קבוע ומופחת (מחשבים ⚠️33%, ריהוט ⚠️6% לשנה) — לכן "
                 "ה-treatment הכללי כאן הוא DEPRECIATION עם החריג מתועד ב-notes.",
    ),
    "insurance": _rule(
        "insurance", "ביטוח", IncomeTaxTreatment.FULL, income_tax_percent=Decimal("100"),
        input_vat_fraction=_ZERO, sumit_account_default=90009,
        evidence=frozenset({"policy_document"}), citation_he=_S17,
        notes_he="ביטוחי עסק מוכרים 100% במס הכנסה, אך חברת ביטוח היא ספק "
                 "נטול-מע\"מ מבנית (SUPPLIER_KINDS_NO_VAT) — אין מע\"מ בעסקה כלל. "
                 "אין כרטיס ייעודי; 90009 (כללי) הוא ברירת המחדל.",
    ),
    "office": _rule(
        "office", "הוצאות משרד", IncomeTaxTreatment.FULL, income_tax_percent=Decimal("100"),
        input_vat_fraction=_FULL, sumit_account_default=90503,
        evidence=frozenset({"tax_invoice"}), citation_he=_S17,
    ),
    "materials": _rule(
        "materials", "חומרי גלם/סחורה", IncomeTaxTreatment.FULL, income_tax_percent=Decimal("100"),
        input_vat_fraction=_FULL, sumit_account_default=90000,
        evidence=frozenset({"tax_invoice"}), citation_he=_S17,
    ),
    "services": _rule(
        "services", "שירותים ומנויים", IncomeTaxTreatment.FULL, income_tax_percent=Decimal("100"),
        input_vat_fraction=_FULL, sumit_account_default=90005,
        evidence=frozenset({"tax_invoice", "subscription_receipt"}), citation_he=_S17,
        notes_he="תוכנה/SaaS/אחסון — 90005 (הוצאות מחשוב), כפי שמוגדר בתרשים "
                 "החשבונות עבור Microsoft/Vercel/Claude.ai וכד'.",
    ),
    "petty_cash": _rule(
        "petty_cash", "קופה קטנה", IncomeTaxTreatment.FULL, income_tax_percent=Decimal("100"),
        input_vat_fraction=None, sumit_account_default=90007,
        evidence=frozenset({"petty_cash_log"}), citation_he=_S17,
        notes_he="הוצאות קופה קטנה הן לרוב מוכרות (FULL) אך מעורבות מטבען "
                 "(רכישות שונות בלי חשבונית מס פר-פריט) — מע\"מ תשומות: הכרעה "
                 "פר-מקרה, לא ברירת מחדל.",
    ),
    "other": _rule(
        "other", "אחר", IncomeTaxTreatment.FULL, income_tax_percent=Decimal("100"),
        input_vat_fraction=None, sumit_account_default=90009,
        evidence=frozenset(), citation_he=_S17,
        notes_he="קטגוריה גנרית ללא מידע-סיווג ממשי — הכרעת מע\"מ פר-מקרה.",
    ),
    # ------------------------------------------------------------------ #
    # קטגוריות חדשות
    # ------------------------------------------------------------------ #
    "vehicle": _rule(
        "vehicle", "רכב", IncomeTaxTreatment.FORMULA,
        formula_ref="calculate_vehicle_deduction_percent",
        input_vat_fraction=None, sumit_account_default=90009,
        evidence=frozenset({"odometer_log", "use_value_table", "running_cost_invoices"}),
        citation_he='תקנות מס הכנסה (ניכוי הוצאות רכב), התשנ"ה-1995; תקנה 18 לתקנות מע"מ',
        notes_he="הוצאות אחזקה שוטפות (דלק/רישוי/ביטוח/תיקונים/חניה/כביש אגרה). "
                 "מס הכנסה: כלל ה-higher-of (calculate_vehicle_deduction_percent) — "
                 "פר-רכב, לא פר-עסק, מותנה ברישום מד-אוץ. מע\"מ: 2/3 עיקר-עסקי / "
                 "1/4 אחרת, לפי VehicleProfile.primarily_business — ללא פרופיל: הכרעה. "
                 "90003 שמור לנסיעות (travel); כרטיס ייעודי לרכב אינו בתרשים, "
                 "ולכן 90009 (כללי) הוא ברירת המחדל, ניתן לשינוי פר-ארגון. "
                 "רכב צמוד לעובד עם שווי שימוש בתלוש: מוכר 100% למעביד, ה-"
                 "higher-of אינו חל (VehicleProfile.attached_to_employee_with_use_value).",
    ),
    "vehicle_purchase": _rule(
        "vehicle_purchase", "רכישת רכב", IncomeTaxTreatment.DEPRECIATION,
        income_tax_percent=Decimal("15"),
        input_vat_fraction=_ZERO, sumit_account_default=90008,
        evidence=frozenset({"purchase_invoice", "vehicle_registration"}),
        citation_he='תקנה 14 לתקנות מע"מ; תקנות מס הכנסה (ניכוי הוצאות רכב) התשנ"ה-1995',
        notes_he="תקנה 14: תשומות רכישה/יבוא של רכב פרטי אסורות לחלוטין (0%). "
                 "חריגים שבהם התשומות כן מותרות במלואן: מלאי-סוחר, השכרה/ליסינג "
                 "כעיסוק, מוניות, לימוד נהיגה, רכב מסחרי — VehicleProfile.vehicle_kind. "
                 "מס הכנסה: פחת רכב 15% לשנה, נכנס לנוסחת ה-higher-of של vehicle. "
                 "90008 (רכישת רכב) הוא כרטיס ייעודי מדויק בתרשים.",
    ),
    "hospitality": _rule(
        "hospitality", "אירוח", IncomeTaxTreatment.NONE,
        input_vat_fraction=_ZERO, sumit_account_default=90009,
        evidence=frozenset({"guest_registry"}),
        citation_he='תקנה 2(1) ו-15א לתקנות מע"מ; ' + _TAKANOT_1972,
        notes_he="ארוחה/קפה עם לקוח ישראלי, מסעדה — 0% בשני הצדדים (הטעות "
                 "הנפוצה: לחשוב שזה 80%). אירוח אורח מחו\"ל: מוכר בסכום סביר "
                 "במס הכנסה (חובת רישום זהות/מדינה/ימים) אך עדיין 0% במע\"מ תשומות "
                 "(תקנה 15א, למעט חריג צר). אין כרטיס ייעודי — 90009 (כללי).",
    ),
    "refreshments": _rule(
        "refreshments", "כיבוד", IncomeTaxTreatment.PARTIAL_FIXED,
        income_tax_percent=Decimal("80"),
        input_vat_fraction=None, sumit_account_default=90503,
        evidence=frozenset({"tax_invoice"}),
        citation_he=_TAKANOT_1972,
        notes_he="כיבוד קל במקום העסק (קפה/תה/עוגיות למשרד) — 80% מוכר במס "
                 "הכנסה (נוהג רשות המסים). מע\"מ תשומות: עמדה שמרנית עד הכרעה — "
                 "None, לא ברירת מחדל. אין כרטיס ייעודי; 90503 (משרדיות) קרוב ביותר.",
    ),
    "fines": _rule(
        "fines", "קנסות", IncomeTaxTreatment.NONE,
        input_vat_fraction=_ZERO, sumit_account_default=90009,
        evidence=frozenset(),
        citation_he=_S17 + " (הוצאה שלא בייצור הכנסה)",
        notes_he="קנסות ועיצומים (כולל קנסות רשויות המס) — 0% תמיד, בשני "
                 "הצדדים, גם כשמגיעים דרך ספק דלק/ליסינג — יש להפריד מקטגוריית vehicle.",
    ),
    "interest_authorities": _rule(
        "interest_authorities", "ריבית לרשויות", IncomeTaxTreatment.NONE,
        input_vat_fraction=_ZERO, sumit_account_default=90009,
        evidence=frozenset(),
        citation_he=_S17,
        notes_he="ריבית והצמדה לרשויות המס — 0%. להבדיל: ריבית על הלוואה עסקית "
                 "רגילה כן מוכרת (אינה בקטגוריה זו).",
    ),
    "donations": _rule(
        "donations", "תרומות", IncomeTaxTreatment.PERSONAL_DEDUCTION,
        income_tax_percent=Decimal("35"),
        input_vat_fraction=_ZERO, sumit_account_default=None,
        evidence=frozenset({"donation_receipt_46"}),
        citation_he="סעיף 46 לפקודת מס הכנסה",
        notes_he="תרומה למוסד מוכר — זיכוי מס 35% (לא ניכוי הוצאה, לא מע\"מ). "
                 "אסור לרשום כהוצאה עסקית ברו\"ה היומי — עיוות; עוקב לחו\"ז/טופס 1301.",
    ),
    "social_insurance_owner": _rule(
        "social_insurance_owner", 'ב"ל/פנסיה בעלים', IncomeTaxTreatment.PERSONAL_DEDUCTION,
        income_tax_percent=Decimal("52"),
        input_vat_fraction=_ZERO, sumit_account_default=None,
        evidence=frozenset({"bituach_leumi_statement"}),
        citation_he="סעיף 47א לפקודת מס הכנסה",
        notes_he="ביטוח לאומי/פנסיה/קרן השתלמות של העצמאי — ניכוי אישי "
                 "(52%, סעיף 47א), לא הוצאה בעסק. נרשם לחו\"ז/משיכות, עוקב לטופס 1301.",
    ),
}


def claimable_vat(
    *,
    category: str,
    vat_on_doc: Decimal,
    doc_kind: Optional[str],
    supplier_kind: Optional[str] = None,
    vehicle_primarily_business: Optional[bool] = None,
    vehicle_kind: Optional[str] = None,
) -> Optional[Decimal]:
    """המע"מ הנתבע בפועל, לפי סדר-שערים קשיח (KB02):

    0. שער-המסמך *לפני* כל שבר: "receipt" -> 0 (לעולם, בלי קשר לקטגוריה).
       None/"unknown"/כל דבר אחר שאינו "tax_invoice" -> None (הכרעה).
    1. ספק נטול-מע"מ מבנית (SUPPLIER_KINDS_NO_VAT) -> 0.
    2. לוגיקת קטגוריה: רכב/רכישת-רכב תלויים בפרופיל-רכב; שאר הקטגוריות
       לפי TAX_RULES[category].input_vat_fraction (None = הכרעה).
    """
    vat_on_doc = Decimal(str(vat_on_doc))

    if doc_kind == "receipt":
        return Decimal("0.00")
    if doc_kind != "tax_invoice":
        return None  # None/"unknown"/כל ערך אחר — לא מסמך-מע"מ מאומת

    if supplier_kind is not None and supplier_kind in SUPPLIER_KINDS_NO_VAT:
        return Decimal("0.00")

    rule = TAX_RULES.get(category)
    if rule is None:
        return None  # קטגוריה לא מוכרת — לא מנחשים

    if category == "vehicle":
        if vehicle_primarily_business is None:
            return None
        fraction = _TWO_THIRDS if vehicle_primarily_business else _QUARTER
        return (vat_on_doc * fraction).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    if category == "vehicle_purchase":
        if vehicle_kind is None:
            return None
        if vehicle_kind in _VEHICLE_PURCHASE_FULL_KINDS:
            return vat_on_doc.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return Decimal("0.00")

    fraction = rule.input_vat_fraction
    if fraction is None:
        return None
    return (vat_on_doc * fraction).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def resolve_vehicle_profile_args(
    profiles: list[dict],
) -> tuple[Optional[bool], Optional[str]]:
    """בורר (primarily_business, vehicle_kind) מתוך פרופילי-רכב טעונים מה-DB
    (dicts עם מפתחות "primarily_business"/"vehicle_kind") — פונקציה טהורה
    כדי שהיא תיבחן בקלות, בלי DB. עיקר-השימוש הוא עובדה פר-רכב (KB02 §1):
    אפס פרופילים או יותר מאחד -> (None, None) — לא ידוע לאיזה רכב מתייחסת
    ההוצאה, ולכן גם לא primarily_business וגם לא vehicle_kind ניתנים לשימוש.
    פרופיל יחיד -> שני השדות שלו כפי שהם (כל אחד יכול להיות None בנפרד —
    claimable_vat בודק כל שדה בנפרד לפי הקטגוריה שצריכה אותו)."""
    if len(profiles) != 1:
        return None, None
    profile = profiles[0]
    return profile.get("primarily_business"), profile.get("vehicle_kind")


# ---------------------------------------------------------------------- #
# ספים/שיעורים שנויים-במחלוקת או תלויי-עדכון שנתי — לאמת מול gov.il לפני
# הסתמכות בדיווח. כל ⚠️ ב-KB01/KB02 חייב שורה כאן.
# ---------------------------------------------------------------------- #
VERIFICATION_NEEDED: list[str] = [
    'מספרי הקצאה (חשבוניות ישראל) 2026: מקורות סותרים — ₪15,000 לפי לוח '
    'החקיקה המקורי מול ₪10,000→₪5,000 לפי מקורות אחרים. לאמת מול gov.il לפני אכיפה בקוד.',
    'אש"ל בחו"ל: תקרות יומיות ~$97 (עם לינה נפרדת) / ~$162 — לאימות שנתי.',
    'מתנות ללקוחות: עד ₪240 למקבל לשנה בארץ, $15 לתושב חוץ — לאימות שנתי.',
    'ציוד זול הנרשם כהוצאה שוטפת: סף מקובל ~₪1,200 — לאימות.',
    'שווי שימוש רכב (רכבים מ-2010): 2.48% ממחיר המחירון — לאימות שנתי.',
    'עסק זעיר (רפורמת 2026): תקרת הפטור ₪122,833 ל-2026 — לאימות שנתי.',
    'איחור דיווח מע"מ: קנס ~₪239 לכל שבועיים — לאימות שנתי.',
    'קווי טלפון מהבית: רצפה ₪2,700, תקרה ₪26,600 לשנה — לאימות שנתי.',
    'פחת: מחשבים 33% לשנה, ריהוט 6% לשנה — לאימות מול טבלת הפחת המעודכנת.',
]


# ---------------------------------------------------------------------- #
# טבלת-גשר בעברית — נוצרת מהקוד, נשמרת ל-03-classification-bridge.md
# ---------------------------------------------------------------------- #
_INCOME_TAX_DISPLAY: dict[IncomeTaxTreatment, str] = {
    IncomeTaxTreatment.FULL: "מוכר 100%",
    IncomeTaxTreatment.FORMULA: "נוסחה (higher-of)",
    IncomeTaxTreatment.PARTIAL_FIXED: "אחוז קבוע חלקי",
    IncomeTaxTreatment.NONE: "לא מוכר (0%)",
    IncomeTaxTreatment.DEPRECIATION: "רכוש קבוע — פחת",
    IncomeTaxTreatment.PERSONAL_DEDUCTION: "ניכוי/זיכוי אישי (לא הוצאה עסקית)",
}


def _fraction_display(fraction: Optional[Decimal]) -> str:
    if fraction is None:
        return "הכרעה (context)"
    if fraction == _FULL:
        return "100%"
    if fraction == _ZERO:
        return "0%"
    if fraction == _QUARTER:
        return "1/4"
    if fraction == _TWO_THIRDS:
        return "2/3"
    return str(fraction)


def render_bridge_table_he() -> str:
    """טבלת-גשר בעברית: קטגוריה -> כרטיס -> הכרה במס הכנסה -> שבר מע"מ תשומות
    -> תיעוד נדרש -> בסיס חוקי. נוצרת מ-TAX_RULES ו-VERIFICATION_NEEDED —
    דטרמיניסטית (ללא חותמת-זמן) כדי ש-scripts/render_bookkeeper_kb.py ידע
    מתי הקובץ השמור מיושן (diff מול הפלט הנוכחי)."""
    lines: list[str] = ["<!-- BEGIN GENERATED -->", ""]
    lines.append(
        "> נוצר אוטומטית מ-`src/cfo/services/israeli_tax_rules.py` (TAX_RULES + "
        "VERIFICATION_NEEDED). אין לערוך ידנית — הפעל `scripts/render_bookkeeper_kb.py`."
    )
    lines.append("")
    lines.append("| קטגוריה | שם | כרטיס SUMIT | מס הכנסה | מע\"מ תשומות | תיעוד נדרש | בסיס חוקי |")
    lines.append("|---|---|---|---|---|---|---|")
    for key, rule in TAX_RULES.items():
        income = _INCOME_TAX_DISPLAY[rule.income_tax]
        if rule.income_tax_percent is not None:
            income += f" ({rule.income_tax_percent}%)"
        if rule.formula_ref:
            income += f" — `{rule.formula_ref}`"
        account = str(rule.sumit_account_default) if rule.sumit_account_default is not None else "—"
        evidence = ", ".join(sorted(rule.evidence)) if rule.evidence else "—"
        lines.append(
            f"| `{key}` | {rule.name_he} | {account} | {income} | "
            f"{_fraction_display(rule.input_vat_fraction)} | {evidence} | {rule.citation_he} |"
        )

    lines.append("")
    lines.append("### ⚠️ VERIFICATION_NEEDED — ספים/שיעורים לאימות מול gov.il")
    lines.append("")
    for item in VERIFICATION_NEEDED:
        lines.append(f"- {item}")

    lines.append("")
    lines.append("<!-- END GENERATED -->")
    return "\n".join(lines)
