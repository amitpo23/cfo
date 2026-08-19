"""KB loader for the conversational chat assistant (channels/personas plan,
Package 2 — see docs/superpowers/plans/2026-07-26-conversational-channels-personas.md;
Package J — procedures center, see the same plan directory).

Exposes three static, on-disk knowledge centers to the chat tool layer,
mirroring the Hermes-agent split between reference knowledge and
procedure:

- ``docs/bookkeeper_kb/`` — the bookkeeper's professional knowledge base
  (Israeli income-tax expense recognition, VAT input deductibility, the
  classification bridge, evidence rules, the daily analysis prompt set).
- ``docs/sumit_help_kb/`` — the SUMIT help-center corpus (operational
  how-to for the accounting portal itself).
- ``procedures`` (key ``"procedures"``) — standing operating procedures:
  files that live directly under ``docs/`` (not a subdirectory) and answer
  "what is the order of operations for X", as opposed to "what does the
  law say" (bookkeeper_kb) or "how does the SUMIT UI work" (sumit_help_kb).
  A center's files may therefore sit in a subdirectory (``dir_name`` set)
  or directly under ``DOCS_ROOT`` (``dir_name=""`` — pathlib composes
  ``Path(root) / "" / filename`` to ``Path(root) / filename``, so every
  path-construction site below needs no special-casing for the flat case).

Design goals:

1. **honest-null over silent-empty.** If the KB directories aren't present
   at runtime (e.g. not packaged into the Vercel function), every entry
   point here returns ``{"available": False, "reason": "..."}`` — never an
   empty list that could be mistaken for "there is no relevant content".
2. **No RAG, no embeddings.** This is a plain keyword search over
   markdown ``## `` sections, ranked by keyword-occurrence count. Good
   enough for a handful of files; deliberately not more than that
   (see the plan: "אין RAG").
3. **Static content, cached reads.** The files ship with the deployment
   and don't change at runtime, so both the index and file contents are
   ``lru_cache``d. Cache keys include the resolved docs root (not just
   "no args") so a test that monkeypatches the root to a missing path
   can't poison the cache for every other caller in the same process.

Path-discovery pattern mirrors ``capability_control_plane.py``
(``REPO_ROOT = Path(__file__).resolve().parents[3]``) — this is the
established precedent in this codebase for reading repo-relative docs at
runtime.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
DOCS_ROOT = REPO_ROOT / "docs"

# Ceiling on a single section's contributed text, so one huge "## " block in
# a long SUMIT help file (some run 1,000+ lines) can't alone consume the
# entire max_chars budget and crowd out every other matching source.
_SECTION_CHAR_CAP = 1200

# Section-splitting heading depth. bookkeeper_kb/sumit_help_kb files are
# short and flat (## only) — kept as-is so their existing search results
# don't shift. The procedures docs are long, deeply-nested runbooks (##
# through ####; e.g. BOOKKEEPER_ARMY_OPERATING_MODEL.md's chapter 2 runs
# ~490 lines under a single ## heading) — splitting only on ## would hand
# back one multi-thousand-char section that outranks and crowds out every
# more specific ###/#### SOP subsection at the same score. Splitting one
# level deeper keeps each returned section scoped to the actual procedure.
_HEADING_RE = re.compile(r"^##[ \t]+(.*)$", re.MULTILINE)
_HEADING_RE_DEEP = re.compile(r"^#{2,4}[ \t]+(.*)$", re.MULTILINE)

NOT_AVAILABLE_REASON = "מרכז הידע אינו זמין בסביבה זו (docs לא נארזו בפריסה)"


@dataclass(frozen=True)
class KBFile:
    filename: str
    title_he: str
    summary_he: str


@dataclass(frozen=True)
class KBCenter:
    key: str
    title_he: str
    dir_name: str  # relative to DOCS_ROOT; "" means the files sit directly under it
    files: tuple[KBFile, ...]
    heading_re: re.Pattern[str] = _HEADING_RE


# Manually curated from reading every file in both directories (2026-07-26) —
# titles/summaries are not generated, per the plan's "אל תמציא" instruction.
KB_CENTERS: tuple[KBCenter, ...] = (
    KBCenter(
        key="bookkeeper_kb",
        title_he="מרכז ידע מנהל החשבונות",
        dir_name="bookkeeper_kb",
        files=(
            KBFile(
                "README.md", "אינדקס מרכז הידע ומשמעת הטעינה",
                "אינדקס כל הקבצים במרכז הידע + טבלת \"מתי לטעון מה\".",
            ),
            KBFile(
                "00-role-and-daily-order.md", "התפקיד וסדר היום של מנהל החשבונות",
                "סדר הבוקר המחייב (8 צעדים) — למה טריות והתאמה משולשת קודמים לכל דבר אחר.",
            ),
            KBFile(
                "01-income-tax-recognition.md", "הכרה בהוצאות — מס הכנסה",
                "סעיף 17 לפקודה + תקנות רכב/הוצאות מסוימות; כלל הזהב 100%/חלקי, "
                "טבלת רכב \"הגבוה מבין\".",
            ),
            KBFile(
                "02-vat-input-deductibility.md", "ניכוי מס תשומות — מע\"מ",
                "שער המסמך (בלי חשבונית מס אין ניכוי), תקנות 14/15א/18, שיעור המע\"מ הנוכחי.",
            ),
            KBFile(
                "03-classification-bridge.md",
                "גשר סיווג — קטגוריית הוצאה -> כרטיס SUMIT -> מס הכנסה -> מע\"מ תשומות",
                "טבלה מיוצרת אוטומטית מ-israeli_tax_rules.py (render_bookkeeper_kb.py) — "
                "אסור לערוך ידנית.",
            ),
            KBFile(
                "04-documents-and-evidence.md", "מסמכים ואסמכתאות",
                "אילו מסמכים קבילים למס הכנסה/למע\"מ (חשבונית מס מול קבלה מול דף בנק).",
            ),
            KBFile(
                "05-external-references.md", "מצביעים חיצוניים",
                "טבלת קישורים למקורות נוספים בריפו (ספר חוקי SUMIT, המודל המכונן, לוח חשבונות).",
            ),
            KBFile(
                "06-daily-analysis-prompts.md", "סט הניתוח היומי — 10 שאלות",
                "פרומפטים מוכנים לצ'אטבוט/סוכן ולמפרט מחזור הבוקר האוטומטי, עם דגלים אדומים.",
            ),
            # --- תהליכי עבודה מול הספרים (16–17/08/2026) --- #
            # התקציר הוא מה שמושקו רואה בחיפוש, ולכן הוא נושא את מילות
            # השאלה שבעל עסק ישאל בפועל ("מנה", "מאזן בוחן", "כפילות"),
            # ולא רק תיאור אקדמי של הקובץ.
            KBFile(
                "07-books-batches.md", "מנות ותנועות יומן — קליטה וסגירת מנה",
                "קליטת מנה, מנות פתוחות, פקודות יומן: הסדר המחייב, מה ה-API "
                "נותן (createbatch בלבד), ולמה קריאת מנה וסגירתה ידניות. "
                "מאזן בוחן עם מנות פתוחות אינו סופי.",
            ),
            KBFile(
                "08-duplicate-detection.md", "זיהוי כפילויות",
                "כפילות דורשת ≥3 שדות; מספר אסמכתא לבדו מייצר התראות שווא "
                "(אגודה חקלאית 16749 מול 16713 — שתי חשבוניות נפרדות). "
                "מחיקת תנועה שאינה כפילות היא מחיקת הוצאה מוכרת.",
            ),
            KBFile(
                "09-sumit-operations-map.md", "מפת הפעולות מול SUMIT",
                "מה נמשך מ-API, מה רצף מחשבת בעצמה (מאזן בוחן, רווח והפסד, "
                "כרטסת, מאזן), ומה קיים רק בדפדפן. משמעת קריאות ה-API.",
            ),
            KBFile(
                "10-month-end-close.md", "סגירת חודש — סדר השלבים",
                "11 שלבים ותנאי מעבר: קליטה, סיווג, כפילויות, מסמכים חסרים, "
                "התאמת בנק, מנה, מאזן בוחן, אימות משולש, סגירה ודיווח.",
            ),
            KBFile(
                "11-updating-sumit.md", "איך נתונים נכנסים ל-SUMIT",
                "createbatch כקריאה אחת למנה שלמה, מסלול אקסל לעדכון מפתחות "
                "חשבון באפס קריאות, ושלוש מלכודות: תאריך העלאה מול תאריך "
                "מסמך, סימון מסמכים כישנים, והוצאות שחוזרות מה-API בסכום 0.",
            ),

            KBFile(
                "12-workflow-expense-classification.md",
                "תהליך סיווג הוצאה",
                "סדר הצעדים לסיווג ותיוק הוצאה, שער המסמך, ושתי מלכודות: "
                "תאריך העלאה מול תאריך מסמך, והוצאות שחוזרות מה-API בסכום 0.",
            ),
            KBFile(
                "13-workflow-bank-reconciliation.md",
                "תהליך התאמת בנקים",
                "התאמת תנועת בנק מול מסמך ותשלום. ל-SUMIT אין endpoint "
                "להתאמות — רצף רואה את שני הצדדים ומתאימה אצלה, והתוצאה "
                "נכתבת כפקודת יומן.",
            ),
            KBFile(
                "14-parity-check.md",
                "התאמת מאזן בוחן רצף מול SUMIT",
                "מאזן של רצף שלא הוצלב מול SUMIT הוא חישוב ולא ספר. "
                "ארבעה תנאים להצלבה תקפה, ולמה פער שלא הוסבר חוסם דיווח.",
            ),
            # נספגו מ-.claude/skills ב-18/08/2026. שלושת התחומים האלה היו
            # בכיסוי **אפס** במרכז הידע בזמן שהסקילים החזיקו קבצי ייחוס
            # מלאים — כלומר הידע היה בריפו ובלתי-נגיש למושקו ולפרודקשיין.
            # הרישום כאן הוא מה שהופך אותם לנגישים; קובץ שאינו רשום אינו
            # קיים מבחינת kb_lookup (הכשל של מסמכים 07–11).
            KBFile(
                "15-payroll-rates.md",
                "שכר — מדרגות מס, ביטוח לאומי ונקודות זיכוי",
                "מדרגות מס הכנסה 2026 (תיקון 288, רטרואקטיבי ל-1.1.2026), "
                "שיעורי ביטוח לאומי (תיקון 252), ונקודות זיכוי. נדרש לכל "
                "בדיקת תלוש, פקודת שכר ושאלת עלות מעביד.",
            ),
            KBFile(
                "16-annual-reports.md",
                "דוחות שנתיים — צ'ק-ליסט ומונחים",
                "צ'ק-ליסט סגירת שנה ומילון מונחים פיננסיים בעברית. סגירת "
                "שנה היא הנקודה שבה טעות תיוק הופכת לדיווח שגוי.",
            ),
            KBFile(
                "17-corporate-tax.md",
                "מס חברות — שיעורים, סעיף 3(ט) ומשיכות בעלים",
                "שיעורי מס חברות 2026, כללי סעיף 3(ט) על משיכות בעלים, "
                "ודרכי משיכה. משיכה שלא סווגה נכון הופכת להכנסה חייבת.",
            ),
        ),
    ),
    KBCenter(
        key="sumit_help_kb",
        title_he="מרכז ידע SUMIT (מרכז העזרה)",
        dir_name="sumit_help_kb",
        files=(
            KBFile(
                "01-books-portal.md", "פורטל הנהלת חשבונות ועדכוני מערכת",
                "29 מאמרים — מבוא לפורטל הנהלת החשבונות ועדכוני מערכת.",
            ),
            KBFile(
                "02-welcome-basics.md", "מדור \"ברוכים הבאים\" — יסודות ותמחור",
                "78 מאמרים — מודל התמחור הדו-שכבתי, אחסון, יסודות ההתחלה עם המערכת.",
            ),
            KBFile(
                "03-income-customers-expenses.md", "הכנסות, לקוחות, הוצאות, ספקים",
                "מדריך אופרטיבי (צעדים/מגבלות/מלכודות) למודולי הליבה: הכנסות, לקוחות, "
                "הוצאות, ספקים.",
            ),
            KBFile(
                "04-billing-collection.md", "חיוב וגבייה",
                "165 מאמרים — סליקת אשראי, חיוב מס\"ב, הוראות קבע, דפי תשלום.",
            ),
            KBFile(
                "05-other-modules.md", "מודולים נוספים",
                "92 מאמרים ב-17 מדורים — דיוור במייל, CRM ועוד (לא הכנסות/הוצאות/סליקה/מס\"ב).",
            ),
            KBFile(
                "06-developers-general.md", "מפתחים, אינטגרציה, אתרי סחר וכללי",
                "73 מאמרים — API/אינטגרציה/אתרי מסחר, וכללי ושונות.",
            ),
            # קבצים 07–12: מרכז הידע למייצגים (SUMIT Books, 517 מאמרים).
            # חולצו ב-19/08/2026 מ-worktree נטוש — עד אז כל צד המייצגים
            # (מנות, שידור לשע"מ, מאזנים, ניהול משרד) היה בלתי-נראה למושקו.
            KBFile(
                "07-books-welcome-case-setup.md",
                "Books — הקמת תיקים, תבניות ויבוא",
                "69+31 מאמרים — פתיחת תיק (עם/בלי היסטוריה, תיק-בקליק מ-13 "
                "מערכות), תבניות תיק ומשרד, אינדקס כרטיסי חשבון וסוגי תנועה, "
                "ובדיקות חובה אחרי יבוא.",
            ),
            KBFile(
                "08-books-data-intake-bookkeeping.md",
                "Books — קליטת נתונים והנהלת חשבונות שוטפת",
                "מנות (יצירה/איזון/סגירה בלתי-הפיכה), תיוק הוצאות (AI/OCR/"
                "ZUGFeRD), רישום תנועות, סטורנו, פחת ונכסים, חשבונית עצמית, "
                "תשלומים לספקים.",
            ),
            KBFile(
                "09-books-periodic-reporting.md",
                "Books — דיווחים תקופתיים ושידור לשע\"מ",
                "90 מאמרים — שידור מקוון לרשות המסים ב-API (מע\"מ/מקדמות/"
                "ניכויים 102/856), שידור מרוכז רב-תיקים, PCN874, סטטוסי דוח, "
                "קודי שגיאה, דוח מתקן והפרשים.",
            ),
            KBFile(
                "10-books-reports-bank-recon.md",
                "Books — דוחות, מאזן בוחן והתאמות בנק",
                "מאזן בוחן (יתרות/תנועות/מנות סגורות בלבד), כרטסות, רווח "
                "והפסד, 6111, סגירת שנה, רציפות אסמכתאות, סנכרון בנקים "
                "והתאמות (ידניות/מהירות/AI).",
            ),
            KBFile(
                "11-books-office-client-interface.md",
                "Books — ניהול משרד מייצגים וממשק צד לקוח",
                "ניהול צוות והרשאות, חיבורי רשות המסים של המשרד, מעקב "
                "דיווחים רוחבי, גבייה למייצגים, SSO, והממשק מול צד הלקוח "
                "(העברת חומרים, השלמת הוצאות).",
            ),
            KBFile(
                "12-books-tax-planning-annual.md",
                "Books — תכנון מס ודוחות שנתיים",
                "תכנון מס אישי/חברה/רוחבי, תיאומים (כולל תיאום רכב), דוח "
                "שנתי 1301, טופס 1399 ונקודות זיכוי.",
            ),
        ),
    ),
    KBCenter(
        key="procedures",
        title_he="פרוצדורות ונהלי עבודה",
        dir_name="",  # these files sit directly under docs/, not a subdirectory
        heading_re=_HEADING_RE_DEEP,
        files=(
            KBFile(
                "BOOKKEEPER_ARMY_OPERATING_MODEL.md",
                "מודל ההפעלה של צבא מנהלי החשבונות — ה-workflow וה-SOP המכוננים",
                "865 שורות: 4 דוקטרינות-על (verify-first, אימות משולש, אפס אוטונומיה "
                "בבלתי-הפיך, שובל אסמכתאות סעיף 224א), לוח השנה הרגולטורי, ה-workflow "
                "המלא פר תיק (יומי/שבועי/חודשי/רבעוני/שנתי) כולל סגירת מנה ואיחוד "
                "עולמות התיוק, SOP-ים מלאים לזיכויים / דוח מתקן ומסמך רטרואקטיבי / "
                "מספרי הקצאה (חשבונית ישראל) / בקרת VAT מגלה, ארכיטקטורת הצבא "
                "והסקיילביליות, פערים פתוחים, ונספח \"היום הראשון של סוכן חדש בתיק\".",
            ),
            KBFile(
                "REZEF_OPERATING_SYSTEM.md",
                "מערכת ההפעלה של רצף — חוזה ארכיטקטוני יציב",
                "היררכיית מקור האמת פר-שאלה, מטרת המערכת, חלוקת בעלות על אמת "
                "(מה SUMIT/Open Finance מחזיקים מול מה רצף מחזיקה), ארבעת התפקידים "
                "(integration steward / מנהל חשבונות / controller-רו\"ח / CFO), "
                "ה-workflow היומי הקנוני ותקציבי ה-cron, מצב היעד של הנה\"ח כפולה, "
                "ארבעת מסלולי הליבה (הוצאה / הכנסה וגבייה / ספק ותשלום / סגירת "
                "תקופה), חבילת דוחות CFO, שערים חוצי מערכת, זיכרון/skills, ותכנית "
                "ההשלמה בת 8 השלבים.",
            ),
            KBFile(
                "SUMIT_BOOKS_BATCH_UNIFICATION_PLAYBOOK.md",
                "נוהל איחוד עולמות התיוק (מודול הוצאות ↔ תיק) והפקת קובץ חשבשבת",
                "נוהל בן 9 שלבים, הוכח על org5 (עומר ועודד פורת, מנה 2): חילוץ המנה "
                "מהפורטל, הצלבה מול מסמכי העסק, החלטות בעלים על שורות חשודות, מחיקת "
                "שורה, השלמת צד-נגדי חסר, אימות איזון ('מאזן: 0'), סגירת המנה "
                "כרישום בלתי-הפיך, יבוא הכנסות מהעסק, והפקת קובץ חשבשבת מלא; כולל "
                "מלכודות דפדפן Blazor/SUMIT ותנאים להחלה על תיקים אחרים.",
            ),
        ),
    ),
)


@lru_cache(maxsize=None)
def _read_file(root: str, dir_name: str, filename: str) -> str:
    path = Path(root) / dir_name / filename
    return path.read_text(encoding="utf-8")


@lru_cache(maxsize=8)
def _index_for(root: str) -> dict[str, Any]:
    centers_out: list[dict[str, Any]] = []
    total_files = 0
    for center in KB_CENTERS:
        center_dir = Path(root) / center.dir_name
        files_out = []
        for f in center.files:
            if (center_dir / f.filename).exists():
                files_out.append({
                    "filename": f.filename,
                    "title": f.title_he,
                    "summary": f.summary_he,
                })
        if files_out:
            centers_out.append({
                "key": center.key,
                "title": center.title_he,
                "files": files_out,
            })
        total_files += len(files_out)

    if total_files == 0:
        return {"available": False, "reason": NOT_AVAILABLE_REASON}
    return {"available": True, "centers": centers_out, "file_count": total_files}


def kb_index() -> dict[str, Any]:
    """The three knowledge centers and the files actually present on disk,
    with hand-written Hebrew titles/summaries. honest-null (``available:
    False`` + reason) if nothing is found on disk at all — never a silent
    empty ``centers`` list."""
    return _index_for(str(DOCS_ROOT))


def kb_document(center_key: str, filename: str) -> dict[str, Any]:
    """Return one curated markdown document without accepting arbitrary paths.

    The requested center/file must exist in ``KB_CENTERS``. If the curated
    document is known but not packaged, return the same explicit unavailable
    shape as the index; unknown identifiers remain distinguishable.
    """
    center = next((item for item in KB_CENTERS if item.key == center_key), None)
    if center is None:
        return {"available": True, "found": False}
    metadata = next((item for item in center.files if item.filename == filename), None)
    if metadata is None:
        return {"available": True, "found": False}
    path = DOCS_ROOT / center.dir_name / metadata.filename
    if not path.exists():
        return {"available": False, "reason": NOT_AVAILABLE_REASON, "found": None}
    return {
        "available": True,
        "found": True,
        "center": center.title_he,
        "title": metadata.title_he,
        "summary": metadata.summary_he,
        "content": _read_file(str(DOCS_ROOT), center.dir_name, metadata.filename),
    }


def _split_sections(
    text: str, file_title: str, heading_re: re.Pattern[str] = _HEADING_RE
) -> list[dict[str, str]]:
    """Split a markdown document into sections at each heading matched by
    ``heading_re`` (``## `` only by default; centers with deeply-nested
    runbooks pass ``_HEADING_RE_DEEP`` to split on ``##``-``####`` so one
    long chapter can't crowd out its own subsections — see ``KBCenter``).
    Content before the first matched heading (the ``# `` title + any intro)
    becomes one section named after the file itself, so nothing is lost."""
    matches = list(heading_re.finditer(text))
    if not matches:
        return [{"heading": file_title, "text": text.strip()}]

    sections: list[dict[str, str]] = []
    if matches[0].start() > 0:
        intro = text[: matches[0].start()].strip()
        if intro:
            sections.append({"heading": file_title, "text": intro})

    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        sections.append({"heading": m.group(1).strip(), "text": text[start:end].strip()})
    return sections


@lru_cache(maxsize=512)
def _word_start_re(term: str) -> re.Pattern[str]:
    """ביטוי שתופס את המונח בתחילת מילה בלבד.

    ספירת תת-מחרוזת גולמית שברה את הדירוג: `"מנה"` נספרה בתוך `הזמנה`
    ו-`תמונה`, ולכן מסמך על הזמנות דורג גבוה משאלה על מנות חשבונאיות
    (נמדד 17/08/2026 — `"סגירת מנה"` החזיר את המודל המכונן במקום את
    המסמך שאומר שאין API לסגירת מנה).

    אות תחילית עברית אחת (ה/ו/ב/ל/מ/ש/כ) מותרת, כדי ש-`"המנה"` ו-
    `"למנה"` כן ייספרו — הן אותו מונח.
    """
    return re.compile(
        r"(?<![\w֐-׿])[הובלמשכ]?"
        + re.escape(term)
    )


def _count_word_starts(haystack: str, term: str) -> int:
    return len(_word_start_re(term).findall(haystack))


def kb_search(query: str, *, max_chars: int = 4000) -> dict[str, Any]:
    """Case-insensitive keyword search across every KB file's ``## ``
    sections, ranked by keyword-occurrence count, returned up to
    ``max_chars`` total. Each result carries a source (center + file +
    heading) so an answer can be attributed.

    honest-null: if the KB isn't present on disk at all, returns the same
    ``{"available": False, "reason": ...}`` shape as ``kb_index()`` instead
    of pretending there was simply nothing relevant. A real search with no
    hits returns ``{"results": [], "note": "לא נמצאו תוצאות ל-'...'..."}``.
    """
    idx = kb_index()
    if not idx.get("available"):
        return idx

    no_results = {"results": [], "note": f"לא נמצאו תוצאות ל-'{query}' במרכזי הידע"}

    terms = [t for t in re.split(r"\s+", (query or "").strip()) if t]
    if not terms:
        return no_results

    lowered_terms = [t.lower() for t in terms]
    root = str(DOCS_ROOT)
    scored: list[dict[str, Any]] = []
    for center in KB_CENTERS:
        center_dir = DOCS_ROOT / center.dir_name
        for f in center.files:
            if not (center_dir / f.filename).exists():
                continue
            text = _read_file(root, center.dir_name, f.filename)
            # התאמה לכותרת/תקציר הרשומים מקבלת משקל גבוה. בלי זה הדירוג
            # הוא ספירת מופעים גולמית, וקבצים ארוכים (מרכז העזרה של SUMIT,
            # המודל המכונן) גוברים תמיד — כך ש"סגירת מנה" החזיר את המודל
            # המכונן ולא את המסמך שאומר שאין API לסגירה. נמדד 17/08/2026.
            label = f"{f.title_he} {f.summary_he}".lower()
            label_hits = sum(1 for t in lowered_terms if t in label)

            for section in _split_sections(text, f.title_he, center.heading_re):
                haystack = section["text"].lower()
                base = sum(_count_word_starts(haystack, t) for t in lowered_terms)
                # נרמול לפי אורך הקטע: קטע ארוך צובר מופעים בלי להיות
                # רלוונטי יותר.
                density = base / max(len(haystack) / 1000.0, 1.0)
                score = density + (label_hits * 25.0)
                if base > 0 or label_hits:
                    scored.append({
                        "score": score,
                        "center": center.title_he,
                        "file": f.filename,
                        "heading": section["heading"],
                        "text": section["text"],
                    })

    if not scored:
        return no_results

    scored.sort(key=lambda s: s["score"], reverse=True)

    results: list[dict[str, Any]] = []
    used = 0
    # תקרת קטעים לקובץ: בלי זה מסמך ארוך אחד צורך את כל תקציב ה-
    # max_chars בקטעים רצופים, ומסמכים רלוונטיים אחרים לא מקבלים מקום
    # כלל. נמדד 17/08/2026 — "סגירת חודש" החזיר ארבעה קטעים מאותו
    # מסמך, ו-10-month-end-close.md לא הופיע בתשובה בכלל.
    _MAX_SECTIONS_PER_FILE = 2
    per_file: dict[str, int] = {}
    for s in scored:
        remaining = max_chars - used
        if remaining <= 0:
            break
        if per_file.get(s["file"], 0) >= _MAX_SECTIONS_PER_FILE:
            continue
        per_file[s["file"]] = per_file.get(s["file"], 0) + 1
        text = s["text"]
        cap = min(_SECTION_CHAR_CAP, remaining)
        if len(text) > cap:
            trimmed = max(cap - 1, 0)
            text = text[:trimmed].rstrip() + "…"
        results.append({
            "source": f'{s["center"]} — {s["file"]} § {s["heading"]}',
            "center": s["center"],
            "file": s["file"],
            "heading": s["heading"],
            "text": text,
        })
        used += len(text)

    return {"results": results}
