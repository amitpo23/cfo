"""S5 (ספרינט זהות-מושקו, 25/08/2026) — שער נגד-דריפט בין BASE_SYSTEM_PROMPT
לבין TOOLS. הבעיה שנמצאה: BASE_SYSTEM_PROMPT מונה כלים בפרוזה כתובה-ביד
(get_bank_reconciliation, get_ap_aging, email_report, propose_vat_filing_
approval, verify_filing, rezef_help, search_history, get_ledger_card,
get_ar_aging, kb_lookup) — כפול מול ai_chat_tools.TOOLS (~50 כלים).
בלי שער, שינוי-שם/מחיקת-כלי משאיר את הפרומפט מצטט כלי שכבר לא קיים,
ומושקו "יודע" על יכולת רפאים.

לא בונים כאן מחדש את כל פסקת-היכולות (זו עבודה נפרדת, גדולה יותר,
שדורשת בדיקה זהירה שהניסוח לא נשבר) — זה השער המבני שמונע רגרסיה
שקטה בינתיים, באותו דפוס כמו test_sumit_rate_limit_hard_rule.py.
"""
import re

from cfo.services.ai_chat_personas import BASE_SYSTEM_PROMPT
from cfo.services.ai_chat_tools import TOOLS

# שמות-כלים המוזכרים במפורש בפרוזה של BASE_SYSTEM_PROMPT, נכון ל-25/08/2026.
# רשימה מתוחזקת בכוונה (לא נגזרת אוטומטית) — שינוי כאן אמור לקרות ביד,
# באותו קומיט שמשנה את הפרומפט או את TOOLS.
_TOOLS_MENTIONED_IN_BASE_PROMPT = {
    "get_bank_reconciliation", "get_ap_aging", "email_report",
    "propose_vat_filing_approval", "verify_filing", "rezef_help",
    "search_history", "get_ledger_card", "get_ar_aging", "kb_lookup",
}


def test_every_tool_named_in_the_base_prompt_still_exists():
    """אם כלי שהפרומפט מצטט נמחק/שונה-שם — זה אמור להיתפס כאן, לא
    כשמושקו יגיד למשתמש שהוא 'יודע' לעשות משהו שכבר לא קיים."""
    missing = _TOOLS_MENTIONED_IN_BASE_PROMPT - set(TOOLS.keys())
    assert not missing, f"הפרומפט מצטט כלים שלא קיימים יותר: {missing}"


def test_the_maintained_list_actually_appears_in_the_prompt():
    """שער הפוך: אם מישהו מוחק אזכור-כלי מהפרומפט בלי לעדכן את הרשימה
    כאן, זה אומר שהרשימה עצמה יצאה מסונכרנת — גם זה דריפט."""
    missing_from_prompt = {
        name for name in _TOOLS_MENTIONED_IN_BASE_PROMPT
        if not re.search(rf"\b{re.escape(name)}\b", BASE_SYSTEM_PROMPT)
    }
    assert not missing_from_prompt, (
        f"כלים ברשימה שכבר לא מוזכרים בפועל בפרומפט: {missing_from_prompt} — "
        "עדכן את הרשימה הזו כדי שתשקף את המצב האמיתי"
    )


def test_no_untracked_tool_name_sneaks_into_the_prompt():
    """גילוי אוטומטי: כל טוקן שנראה כמו שם-כלי (snake_case) ונמצא גם
    ב-TOOLS וגם בפרומפט — אמור להיות ברשימה המתוחזקת. אם לא, מישהו
    הוסיף אזכור-כלי חדש לפרומפט בלי לעדכן את השער הזה."""
    candidates = set(re.findall(r"\b[a-z][a-z0-9_]*_[a-z0-9_]*\b", BASE_SYSTEM_PROMPT))
    actual_tool_mentions = candidates & set(TOOLS.keys())
    untracked = actual_tool_mentions - _TOOLS_MENTIONED_IN_BASE_PROMPT
    assert not untracked, (
        f"אזכורי-כלי חדשים בפרומפט שלא נוספו לרשימה המתוחזקת: {untracked}"
    )
