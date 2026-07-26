"""KB loader for the conversational chat assistant (channels/personas plan,
Package 2 — see docs/superpowers/plans/2026-07-26-conversational-channels-personas.md).

Exposes the two static, on-disk knowledge centers to the chat tool layer:

- ``docs/bookkeeper_kb/`` — the bookkeeper's professional knowledge base
  (Israeli income-tax expense recognition, VAT input deductibility, the
  classification bridge, evidence rules, the daily analysis prompt set).
- ``docs/sumit_help_kb/`` — the SUMIT help-center corpus (operational
  how-to for the accounting portal itself).

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

_HEADING_RE = re.compile(r"^##[ \t]+(.*)$", re.MULTILINE)

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
    dir_name: str  # relative to DOCS_ROOT
    files: tuple[KBFile, ...]


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
    """The two knowledge centers and the files actually present on disk,
    with hand-written Hebrew titles/summaries. honest-null (``available:
    False`` + reason) if nothing is found on disk at all — never a silent
    empty ``centers`` list."""
    return _index_for(str(DOCS_ROOT))


def _split_sections(text: str, file_title: str) -> list[dict[str, str]]:
    """Split a markdown document into sections at each ``## `` heading.
    Content before the first ``## `` heading (the ``# `` title + any intro)
    becomes one section named after the file itself, so nothing is lost."""
    matches = list(_HEADING_RE.finditer(text))
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
            for section in _split_sections(text, f.title_he):
                haystack = section["text"].lower()
                score = sum(haystack.count(t) for t in lowered_terms)
                if score > 0:
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
    for s in scored:
        remaining = max_chars - used
        if remaining <= 0:
            break
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
