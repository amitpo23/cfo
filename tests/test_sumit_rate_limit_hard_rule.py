"""חוק קשיח: אין דרך לבנות SumitIntegration בקוד הייצור בלי מגביל אמיתי.

**ההנחיה (18/08/2026, חוזרת).** "תבדוק בכל המקומות שיש הגבלה בקריאות
ל-API של סאמיט שלא יעברו את המכסה המותרת ... תקבע חוק שאסור לעקוף אותו,
בכל הארגונים ובכל המערכת."

זה לא בקשה לשער נוסף — כל שכבות ההגנה כבר קיימות (`SumitRequestLimiter`
פר-ארגון+פר-דקה, `claim_daily_sync_run` פר-מפתח,
`assert_paid_action_within_quota`, `SUMIT_ENRICHMENT_DAILY_ACTION_LIMIT`
מתג כיבוי). הבקשה היא **סריקה חוזרת שמונעת רגרסיה שקטה** — הדיוק הזה
חשוב כי אתמול בדיוק נמצאה רגרסיה: שער-מפתח שנפרס תקין נשען על עמודת DB
ריקה ודילג על 3 מתוך 4 ארגונים בלי שאיש שם לב עד בדיקה ידנית.

## המצאי (נמדד היום, 17 נקודות בנייה)

כל הבנייות בקוד הייצור (`cli.py`, `dependencies.py`×2, `data_sync_service.py`,
`agreement_cashflow_service.py`, `payment_request_service.py`×6,
`invoice_service.py`×5, `ai_chat_tools.py`, `sumit_connector.py`) מעבירות
`request_limiter=SumitRequestLimiter(...)` אמיתי. **אפס בנייה חשופה.**

## למה זה שער ולא רק ממצא

`SumitIntegration.__init__` מקבל `request_limiter=None` כברירת מחדל —
בכוונה: השער אינו במקום הבנייה אלא ברגע הרשת עצמה (`_make_request`,
`_post_binary`), fail-closed עם `SumitRequestBudgetRequired`. אבל
**מבנה חסין תלוי בכך שאיש לא ימסור מגביל-דמה** — מחלקה עם `.claim()`
שמחזירה `None` תמיד עוברת את `is not None` ומשתיקה את השער בשקט. הטסט
כאן תופס גם את זה, לא רק בנייה חשופה.
"""
import ast
import pathlib


REPO_SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "cfo"

# הקובץ שמגדיר את המחלקה עצמה, ו-cli.py שם הבנייה בתוך פונקציית טסט
# ידנית ("test()") — עדיין נבדק, לא מוחרג.
_CLASS_DEFINITION_FILE = REPO_SRC / "integrations" / "sumit_integration.py"


def _iter_production_py_files():
    for path in REPO_SRC.rglob("*.py"):
        yield path


def _construction_call_sites(tree, source_lines):
    """כל קריאה ל-SumitIntegration(...) בעץ ה-AST, עם מקטע המקור שלה."""
    sites = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            name = fn.id if isinstance(fn, ast.Name) else getattr(fn, "attr", None)
            if name == "SumitIntegration":
                start = node.lineno - 1
                end = getattr(node, "end_lineno", node.lineno)
                sites.append("\n".join(source_lines[start:end]))
    return sites


def test_every_production_construction_passes_a_real_limiter():
    """כיוון א': כל בנייה מעבירה request_limiter=SumitRequestLimiter(...).

    זה נבדק על ה-AST (לא grep על טקסט) כדי לא לפספס בנייה מרובת-שורות
    ולא להיתפס ע"י הערה שמזכירה את שם המחלקה.
    """
    offenders = []
    for path in _iter_production_py_files():
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        lines = source.splitlines()
        for site in _construction_call_sites(tree, lines):
            if "SumitRequestLimiter(" not in site:
                offenders.append(f"{path.relative_to(REPO_SRC.parent.parent)}: {site.strip()[:80]}")

    assert not offenders, (
        "בנייה של SumitIntegration בלי SumitRequestLimiter אמיתי:\n  "
        + "\n  ".join(offenders)
    )


def test_no_production_code_defines_a_no_op_claim_bypass():
    """כיוון ב': אין מחלקה בקוד הייצור עם `.claim` שמחזירה תמיד None.

    כזו הייתה עוברת את בדיקת 'is not None' ומשתיקה את השער בשקט — בדיוק
    הפרצה שהמבנה fail-closed נועד לחסום. (מותר בטסטים/סקריפטים חד-פעמיים
    שמודדים מכסה במפורש לפני ואחרי; אסור כאן, בקוד שרץ בפרוד.)
    """
    offenders = []
    for path in _iter_production_py_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            for item in node.body:
                if not (isinstance(item, ast.FunctionDef) and item.name == "claim"):
                    continue
                body = item.body
                if len(body) == 1 and isinstance(body[0], ast.Return):
                    val = body[0].value
                    if val is None or (isinstance(val, ast.Constant) and val.value is None):
                        offenders.append(f"{path.relative_to(REPO_SRC.parent.parent)}::{node.name}")

    assert not offenders, f"מגביל-דמה בקוד הייצור: {offenders}"


def test_the_network_chokepoints_still_refuse_a_missing_limiter():
    """השער עצמו: fail-closed ברגע הרשת, לא רק בבנייה. שער נגד-רגרסיה
    למקרה שמישהו ירכך את `_make_request`/`_post_binary` בעתיד."""
    source = _CLASS_DEFINITION_FILE.read_text(encoding="utf-8")

    assert source.count("SumitRequestBudgetRequired") >= 3, (
        "פחות משלוש הפניות ל-SumitRequestBudgetRequired — "
        "ייתכן ששער הרשת ברגע ה-getdetails/getpdf נחלש"
    )


def test_the_paid_action_kill_switch_and_quota_reader_are_both_wired():
    """שני שערים בלתי-תלויים חייבים להתקיים יחד: מתג כיבוי גורף
    (0 = הכול כבוי) **וגם** קורא מכסה שחוסם fail-closed בלי מדידה טרייה.
    אחד בלי השני הוא הגנה חלקית."""
    import inspect

    from cfo.integrations import sumit_integration as mod

    assert hasattr(mod.SumitIntegration, "_assert_paid_actions_enabled")
    assert hasattr(mod, "PaidSumitActionDisabled")

    src = inspect.getsource(mod)
    assert "assert_paid_action_within_quota" in src


def test_the_per_key_daily_gate_is_still_the_authoritative_credential_source():
    """רגרסיית 17/08 חזרה בקצרה: השער תבע חלון על מקור אישורים שגוי
    ודילג על ארגונים בשקט. שער קבוע שמונע חזרה על אותה מחלקת באג."""
    import inspect

    from cfo.api.routes import cron

    resolver = inspect.getsource(cron._resolve_sumit_key)
    assert "IntegrationConnection" in resolver
    assert "decrypt_credentials" in resolver
    # ה-DB-ROW הראשי חייב להישאל **לפני** הנפילה ל-api_credentials —
    # לא רק שהמילה מופיעה איפשהו (כולל בתיעוד ההיסטורי של הבאג).
    conn_pos = resolver.find("IntegrationConnection).filter")
    fallback_pos = resolver.find("org.api_credentials if org")
    assert 0 <= conn_pos < fallback_pos, (
        "org.api_credentials נבדק לפני/בלי שאילתת IntegrationConnection — "
        "בדיוק רגרסיית 17/08"
    )
