"""הצ'ק-ליסט של ההתאמה היומית נגזר מהקוד — לא נכתב לידו.

**למה (17/08/2026).** הבעלים ביקש "צ'ק ליסט אמיתי ו-workflow שממפה את רצף
וסאמיט והבנק". "אמיתי" פירושו שהמסמך שמושקו קורא הוא אותו דבר שהקוד מריץ.
צ'ק-ליסט שנכתב ביד נכון ביום שנכתב, ומטעה מהיום שאחריו.

הפרויקט כבר מחזיק את התבנית הזו: `docs/bookkeeper_kb/03-classification-bridge.md`
מיוצר מ-`israeli_tax_rules.render_bridge_table_he()`, ו-CLAUDE.md אוסר לערוך
אותו ידנית. אותו כלל מוחל כאן.

**השער הדו-כיווני הוא העיקר.** זה בדיוק אותו כשל שנמצא ב-`kb_loader`:
מסמכים 07–11 נכתבו, לא נרשמו ברישום, `test_kb_loader.py` המשיך לעבור,
ומושקו לא ראה אותם. אם בדיקה חמישית תיווסף ל-`run_daily_parity` בלי להופיע
ברישום — הצ'ק-ליסט ישקר, והטסט הזה נופל.
"""
import inspect
from pathlib import Path

from cfo.services import parity_service


DOC_PATH = (
    Path(__file__).resolve().parents[1]
    / "docs" / "bookkeeper_kb" / "14-parity-check.md"
)


def test_the_run_executes_exactly_what_the_registry_lists(fresh_org):
    """**השער הדו-כיווני, נמדד על ריצה אמיתית ולא על טקסט המקור.**

    בדיקת שמות ליטרליים במקור הייתה נשברת מול dispatch נגזר-רישום, וגם
    לא הוכיחה שהבדיקה באמת רצה. כאן מריצים את הריצה היומית בפועל
    ומשווים את קבוצת הבדיקות שחזרו לרישום — שוויון מלא בשני הכיוונים:

    - בדיקה שרצה בלי להיות ברישום ⇒ מושקו מבצע משהו שאינו יודע עליו
    - רישום שמבטיח בדיקה שאינה רצה ⇒ הצ'ק-ליסט משקר
    """
    from datetime import date

    from cfo.database import SessionLocal

    db = SessionLocal()
    org_id = fresh_org()["org_id"]

    result = parity_service.run_daily_parity(db, org_id, date(2026, 8, 17))

    executed = {c["name"] for c in result["checks"]}
    registered = {c["key"] for c in parity_service.PARITY_CHECKS}

    assert executed == registered, (
        f"רצו-אך-לא-רשומות: {executed - registered} · "
        f"רשומות-אך-לא-רצו: {registered - executed}"
    )


def test_every_registered_check_resolves_to_a_real_function():
    """רישום עם key שאין לו פונקציה יקרוס ב-KeyError בריצה היומית —
    בפרוד, ב-03:45, בשקט. נתפס כאן."""
    for check in parity_service.PARITY_CHECKS:
        fn_name = f"_check_{check['key']}"
        assert hasattr(parity_service, fn_name), (
            f"הרישום מכיל '{check['key']}' אך {fn_name} אינה קיימת בקוד"
        )


def test_every_registered_check_declares_its_three_sides():
    """הבעלים שאל על מיפוי **רצף מול סאמיט מול הבנק**. כל שורה בצ'ק-ליסט
    חייבת להצהיר איזה שני מקורות היא משווה — אחרת אי-אפשר לדעת איזו צלע
    של המשולש נבדקה ואיזו לא. זה מה שחשף ששתי צלעות היו skipped."""
    for check in parity_service.PARITY_CHECKS:
        assert check.get("compares"), f"{check['key']} אינה מצהירה מה היא משווה"
        assert check.get("title_he"), f"{check['key']} בלי כותרת בעברית"
        assert check.get("blocks_he"), f"{check['key']} אינה אומרת מה חוסם אותה"


def test_the_generated_doc_matches_the_current_render():
    """אם זה נופל — הרץ `python scripts/render_bookkeeper_kb.py`."""
    assert DOC_PATH.exists(), "הרץ scripts/render_bookkeeper_kb.py"
    content = DOC_PATH.read_text(encoding="utf-8")

    assert parity_service.render_parity_checklist_he() in content


def test_the_doc_is_marked_generated_so_nobody_edits_it_by_hand():
    content = DOC_PATH.read_text(encoding="utf-8")

    assert "נוצר" in content and "אוטומטית" in content, (
        "מסמך מיוצר בלי אזהרה — מישהו יערוך אותו ידנית והעריכה תימחק"
    )


def test_the_checklist_reaches_moshko():
    """צ'ק-ליסט שאינו ברישום של kb_loader אינו נגיש ל-kb_lookup — בדיוק
    הכשל של מסמכים 07–11."""
    from cfo.services import kb_loader

    registered = inspect.getsource(kb_loader)
    assert "14-parity-check.md" in registered, (
        "המסמך אינו ברישום kb_loader — מושקו לא ימצא אותו"
    )
