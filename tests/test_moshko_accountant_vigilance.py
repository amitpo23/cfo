"""מושקו חושב תמיד כמו מנהל חשבונות ורואה חשבון — לא רק בכובע החשבונאי.

**ההנחיה (18/08/2026).** "מושקו צריך לחשוב תמיד כמו מנהל חשבונות ורואה
חשבון... לבדוק תמיד תנועות הנהלת חשבונות מול בנק... לעצור אותי לקלוט
הוצאות שאסור לבקש עליהן מע"מ... להבין את חיי העסק והחיים הפרטיים...
לאתגר בכל דרך אפשרית."

**למה ב-BASE_SYSTEM_PROMPT ולא בתוספת כובע.** שלושת הכובעים (bookkeeper
/cfo/accountant) הם ציר טון+סדר-כלים בלבד (הכרעת מועצה 26/07: "NEVER a
permission gate"). ערנות חשבונאית — לבדוק בנק מול ספרים, לחשוד בהוצאה
מעורבת עסקי/פרטי, לא לאשר מע"מ על הוצאה אסורה — אינה תלוית-כובע ואסור
לה לכבות כשהמשתמש שואל שאלת CFO. לכן היא נכנסת לבסיס המשותף.

**מה זה לא.** לא הוראה "תמציא ביקורת" — כל טענה עדיין חייבת לבוא מכלי
אמיתי (honest-null נשאר). זו הוראה **מתי** להריץ כלים ומה לחשוד בו, לא
רישיון לנחש.
"""
from cfo.services.ai_chat_personas import (
    BASE_SYSTEM_PROMPT,
    PERSONAS,
    build_system_prompt,
)


def test_the_base_prompt_instructs_cross_checking_bank_against_books():
    """הליבה של הבקשה: לא לענות על מצב חשבון בלי להצליב מול הבנק."""
    assert "get_bank_reconciliation" in BASE_SYSTEM_PROMPT
    assert "get_ap_aging" in BASE_SYSTEM_PROMPT


def test_the_base_prompt_instructs_flagging_non_deductible_vat():
    """"לעצור אותי לקלוט הוצאות שאסור לבקש עליהן מע"מ" — הוראה מפורשת,
    לא רק כלי זמין שאולי ייקרא."""
    assert "מע\"מ" in BASE_SYSTEM_PROMPT
    assert any(w in BASE_SYSTEM_PROMPT for w in ("לעצור", "לחשוד", "לסמן", "לאתגר"))


def test_the_base_prompt_distinguishes_personal_from_business_life():
    """"להבין את חיי העסק והחיים הפרטיים" — הוצאה מעורבת חייבת להיתפס,
    לא רק להירשם."""
    assert "פרטי" in BASE_SYSTEM_PROMPT


def test_the_base_prompt_still_forbids_inventing_findings():
    """שער נגדי, והוא הקריטי ביותר: ערנות אינה רישיון לנחש. אתגור בלי
    honest-null היה מייצר האשמות מומצאות במקום ביקורת אמיתית."""
    assert "honest-null" in BASE_SYSTEM_PROMPT or "אל תמציא" in BASE_SYSTEM_PROMPT


def test_the_vigilance_directive_applies_to_every_persona():
    """כיוון שהיא ב-BASE ולא בתוספת כובע — היא חייבת להופיע בפרומפט
    המורכב של שלושתם, לא רק באחד."""
    for key, persona in PERSONAS.items():
        prompt = build_system_prompt(persona, include_office=False)
        assert "get_bank_reconciliation" in prompt, f"חסר בכובע {key}"


def test_car_and_vat_rules_are_referenced_via_the_knowledge_base_not_invented():
    """"חוקי המע"מ וחוקי מס הכנסה על רכב" — מושקו מופנה למרכז הידע
    (kb_lookup) שכבר מכיל את התקנות המדויקות, לא מוזמן לצטט שיעור מס
    מהזיכרון שלו."""
    assert "kb_lookup" in BASE_SYSTEM_PROMPT
