#!/usr/bin/env python3
"""Renders docs/bookkeeper_kb/03-classification-bridge.md from
src/cfo/services/israeli_tax_rules.py (TAX_RULES + VERIFICATION_NEEDED).

The generated block is wrapped in <!-- BEGIN/END GENERATED --> markers and is
byte-identical to `israeli_tax_rules.render_bridge_table_he()` — this is
enforced by tests/test_israeli_tax_rules.py::test_generated_doc_file_matches_current_render.
Do not edit the generated block by hand; re-run this script after any change
to TAX_RULES/VERIFICATION_NEEDED.

    python scripts/render_bookkeeper_kb.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

DOC_PATH = ROOT / "docs" / "bookkeeper_kb" / "03-classification-bridge.md"

HEADER = """# גשר סיווג — קטגוריית הוצאה -> כרטיס SUMIT -> מס הכנסה -> מע"מ תשומות

מסמך זה הוא **תמונת-מראה** של `src/cfo/services/israeli_tax_rules.py` —
הטבלה שלמטה (בין `<!-- BEGIN GENERATED -->` ל-`<!-- END GENERATED -->`)
נוצרת אוטומטית ע"י `scripts/render_bookkeeper_kb.py` ואסור לערוך אותה ידנית.
לשינוי כלל — לערוך את `TAX_RULES`/`VERIFICATION_NEEDED` בקוד ואז להריץ מחדש
את הסקריפט. מקור-האמת המשפטי הוא
[01-income-tax-recognition.md](01-income-tax-recognition.md) +
[02-vat-input-deductibility.md](02-vat-input-deductibility.md).

"""


PARITY_DOC_PATH = ROOT / "docs" / "bookkeeper_kb" / "14-parity-check.md"

# המסמך הזה **אינו** מיוצר במלואו: רובו ידע תהליכי שנכתב ביד (מגבלת
# createbatch, ארבעת התנאים המקדימים להצלבה, כלל החסימה). רק הבלוק שבין
# ה-markers נגזר מ-PARITY_CHECKS. כתיבה מלאה של הקובץ הייתה מוחקת את
# הידע — וזה קרה בפועל לפני התיקון הזה.
PARITY_BEGIN = "<!-- BEGIN GENERATED: parity checks -->"
PARITY_END = "<!-- END GENERATED: parity checks -->"

PARITY_HEADER = """
## הבדיקה היומית האוטומטית — ארבע הצלעות

הטבלה שלמטה **נוצרת אוטומטית** ע"י `scripts/render_bookkeeper_kb.py` מתוך
`PARITY_CHECKS` ב-`src/cfo/services/parity_service.py`. אסור לערוך אותה ידנית —
לשינוי בדיקה יש לערוך את הרישום בקוד ולהריץ מחדש את הסקריפט.

### מתי זה רץ

`/api/cron/bookkeeper-morning` ב-**03:45** כל יום → `morning_cycle_service.
_step_parity` → `parity_service.check_and_alert` → `run_daily_parity`.

התוצאה נשמרת בבסיס הנתונים של רצף כ-`CfoInsight` עם `fingerprint` פר
בדיקה-וחודש: אי-התאמה יוצרת/מחייה התראה, וחזרה ל-`ok` סוגרת אותה.

**אפס קריאות API.** כל הבדיקות קוראות את ה-DB המקומי בלבד — לא SUMIT ולא
Open Finance — ולכן הריצה היומית אינה נוגעת במכסת הפעולות בתשלום.

### ארבע הבדיקות

"""

PARITY_FOOTER = """

### איך לקרוא את ההכרעה הכוללת

| סטטוס | פירוש |
|-------|-------|
| `mismatch` | בדיקה סמכותית מצאה פער אמיתי. גובר על כל השאר. |
| `stale` | מקור לא סונכרן בזמן. המספרים מדווחים אך אינם מכריעים. |
| `unknown` | **שום בדיקה מהותית לא השוותה דבר.** לא כשל — אבל גם לא אישור. |
| `ok` | לפחות בדיקה מהותית אחת השוותה בפועל והתאימה. |

`unknown` הוא no-op גמור: אינו מתריע ואינו סוגר התראה קיימת. הסיבה — קודם
לכן ההכרעה הכוללת החזירה `ok` על ארגון מסונכרן-אך-ריק בזמן ששתי צלעות
`skipped` והשלישית השוותה אפס לאפס. דוח ירוק כזה סוגר התראות על בסיס
שתיקה, ולכן הוא גרוע מהיעדר דוח.

### המחסום שנותר לפאריטי מלא

`build_journal` קורא `Invoice`/`Bill`/`Expense`/`Payment` ואינו קורא
`JournalEntry`. לכן פקודות היומן שנקלטו אינן משתתפות בדוחות, ולארגונים
שאין להם מסמכים מסונכרנים הבדיקה השלישית תחזיר `unknown`. עד לתיקון
`build_journal` ולזריעת אינדקס כרטיסים אמיתי, הצלע רצף↔SUMIT **נמדדת
ומדווחת** אך אינה יכולה להגיע ל-`ok`.
"""


def main() -> None:
    from cfo.services.israeli_tax_rules import render_bridge_table_he
    from cfo.services.parity_service import render_parity_checklist_he

    content = HEADER + render_bridge_table_he() + "\n"
    DOC_PATH.write_text(content, encoding="utf-8")
    print(f"OK: wrote {DOC_PATH}")

    block = (
        PARITY_BEGIN + PARITY_HEADER + render_parity_checklist_he()
        + PARITY_FOOTER + "\n" + PARITY_END
    )
    existing = PARITY_DOC_PATH.read_text(encoding="utf-8")
    if PARITY_BEGIN in existing and PARITY_END in existing:
        head = existing.split(PARITY_BEGIN)[0]
        tail = existing.split(PARITY_END)[1]
        merged = head + block + tail
    else:
        # הרצה ראשונה — מצמידים את הבלוק לסוף הידע הידני, לא מוחקים אותו.
        merged = existing.rstrip() + "\n\n" + block + "\n"
    PARITY_DOC_PATH.write_text(merged, encoding="utf-8")
    print(f"OK: updated generated block in {PARITY_DOC_PATH}")


if __name__ == "__main__":
    main()
