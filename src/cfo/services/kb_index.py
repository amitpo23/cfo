"""אינדקס מרכז הידע בבסיס הנתונים של רצף — אחזור למושקו ולתצוגה.

**ההנחיה (17/08/2026).** "בבסיס נתונים שלנו תכניס אינדוקס ו-RAG לצרכי
תצוגה ולמושקו".

## מה נבנה — ומה בכוונה לא

אחזור **לקסיקלי**: טריגרמים (`pg_trgm`) והתאמת תחילית-מילה. **לא**
pgvector, אף ש-Neon מציעה אותו (אומת: `vector` זמין):

- ל-Anthropic אין API של embeddings. ספק embeddings נוסף הוא עלות
  חיצונית שלא אושרה — והבעלים הגדיר משמעת עלויות מפורשת.
- עמודת embedding ריקה בלי כותב נקראת כיכולת קיימת בזמן שאינה. אם ייבחר
  ספק — זו revision נפרדת, לא עמודה שממתינה.

## עברית

ל-PostgreSQL אין תצורת חיפוש-טקסט לעברית — אומת מול פרוד: אפס תצורות
`%hebrew%`. לכן אין stemmer, והאחזור נשען על טריגרמים (עמידים לניקוד
ולסיומות) ועל התאמת תחילית-מילה עם אותיות השימוש (ה/ו/ב/ל/מ/ש/כ), אותה
לוגיקה שכבר הוכחה ב-`kb_loader`.

## מקור אמת יחיד

האינדקס נזרע מ-`kb_loader.KB_CENTERS` ואינו רישום שני. רישום כפול הוא
בדיוק איך שמסמכים 07–11 נעשו בלתי-נראים למושקו בזמן שהטסטים עברו.

## honest-null

- אין התאמה ⇒ רשימה ריקה. **לא** הקטע הכי פחות גרוע: תוצאה לא-רלוונטית
  שמוצגת כידע גרועה מ"לא נמצא".
- האינדקס ריק (סביבה חדשה, זריעה שטרם רצה) ⇒ נפילה חזרה לקבצים. אחזור
  שמחזיר ריק במקום ליפול חזרה היה מכבה את הידע של מושקו בשקט.
"""
from __future__ import annotations

import re
from typing import Any, Optional

from sqlalchemy import func, select

from ..models import KbChunk
from . import kb_loader


# תקרת אורך לקטע יחיד בתשובה — זהה בכוונה ל-`kb_loader._SECTION_CHAR_CAP`,
# כדי ששני המסלולים (אינדקס וקבצים) יחזירו כמות דומה ולא ישנו את גודל
# ההקשר שמושקו מקבל לפי איזה מסלול פעל.
SECTION_CHAR_CAP = 1200
MAX_RESULTS = 6

# אותיות השימוש בעברית. "מאזן" חייב לתפוס גם "המאזן" ו"במאזן", אך לא
# להיבלע בתוך מילה אחרת.
_PREFIX_CLASS = "[הובלמשכ]?"


def _term_re(term: str) -> re.Pattern[str]:
    return re.compile(r"(?<![\w֐-׿])" + _PREFIX_CLASS + re.escape(term))


def _terms(query: str) -> list[str]:
    return [t for t in re.split(r"\s+", (query or "").strip()) if len(t) >= 2]


# ==================================================================== #
# זריעה
# ==================================================================== #
def _iter_registered_sections():
    """מייצר (center_key, filename, idx, heading, text, title_he) מהרישום.

    קורא דרך `kb_loader` בלבד — כולל פיצול הסעיפים ו-`heading_re` הייחודי
    של כל מרכז — כדי שהאינדקס והקבצים יראו בדיוק את אותו תוכן.
    """
    root = str(kb_loader.DOCS_ROOT)
    for center in kb_loader.KB_CENTERS:
        for kb_file in center.files:
            try:
                text = kb_loader._read_file(root, center.dir_name, kb_file.filename)
            except OSError:
                # הקובץ אינו ארוז בסביבה זו. honest-null: מדלגים בשקט על
                # הקובץ הבודד ולא מפילים את כל הזריעה.
                continue
            sections = kb_loader._split_sections(
                text, kb_file.title_he, center.heading_re,
            )
            for idx, sec in enumerate(sections):
                body = (sec.get("text") or "").strip()
                if not body:
                    continue
                yield (
                    center.key, kb_file.filename, idx,
                    sec.get("heading") or kb_file.title_he,
                    body, kb_file.title_he,
                )


def reindex(db) -> dict[str, Any]:
    """זורע מחדש את האינדקס מהרישום. אידמפוטנטי.

    הזריעה מוחקת שורות שאינן ברישום העדכני — שורה יתומה מבטיחה ידע שאיש
    אינו מתחזק, וזה גרוע מהיעדרו.
    """
    seen: set[tuple[str, str, int]] = set()
    existing = {
        (row.center_key, row.filename, row.section_index): row
        for row in db.query(KbChunk).all()
    }

    written = 0
    for center_key, filename, idx, heading, body, title_he in _iter_registered_sections():
        key = (center_key, filename, idx)
        seen.add(key)
        row = existing.get(key)
        if row is None:
            db.add(KbChunk(
                center_key=center_key, filename=filename, section_index=idx,
                heading=heading, content=body, title_he=title_he,
            ))
        else:
            row.heading = heading
            row.content = body
            row.title_he = title_he
        written += 1

    stale = [row for key, row in existing.items() if key not in seen]
    for row in stale:
        db.delete(row)

    db.commit()
    return {"chunks": written, "removed": len(stale)}


def clear(db) -> int:
    removed = db.query(KbChunk).delete()
    db.commit()
    return removed


def indexed_files(db) -> set[tuple[str, str]]:
    """(center_key, filename) המיוצגים באינדקס — הצד השני של השער."""
    rows = db.execute(
        select(KbChunk.center_key, KbChunk.filename).distinct()
    ).all()
    return {(r[0], r[1]) for r in rows}


# ==================================================================== #
# אחזור
# ==================================================================== #
def _score(text: str, heading: str, terms: list[str]) -> float:
    """דירוג לקסיקלי. כותרת שוקלת יותר מגוף — סעיף ששמו הוא השאלה כמעט
    תמיד רלוונטי יותר מסעיף שמזכיר אותה בחטף.

    צפיפות ולא ספירה גולמית: בלעדיה מסמך ארוך מנצח תמיד, וזה בדיוק אחד
    משלושת ליקויי הדירוג שתוקנו ב-`kb_loader`.
    """
    hay = text.lower()
    head = (heading or "").lower()
    base = sum(len(_term_re(t).findall(hay)) for t in terms)
    if base == 0:
        return 0.0
    density = base / max(len(hay) / 1000.0, 1.0)
    head_hits = sum(len(_term_re(t).findall(head)) for t in terms)
    return density + head_hits * 25.0


def search(query: str, *, db=None, max_results: int = MAX_RESULTS) -> dict[str, Any]:
    """חיפוש בידע. מעדיף את האינדקס; נופל לקבצים כשהוא ריק.

    `db=None` פותח סשן משלו — כך שקוראים קיימים (`_kb_lookup`) אינם
    צריכים לדעת על ה-DB.
    """
    terms = _terms(query)
    if not terms:
        return kb_loader.kb_index()

    owned = False
    if db is None:
        from ..database import SessionLocal
        db = SessionLocal()
        owned = True

    try:
        try:
            total = db.execute(select(func.count(KbChunk.id))).scalar_one()
        except Exception:
            # הטבלה טרם נוצרה בסביבה זו. לא כשל — נפילה לקבצים.
            total = 0

        if not total:
            fallback = kb_loader.kb_search(query)
            fallback["source"] = "files"
            return fallback

        # סינון גס ב-DB (LIKE על כל מונח) ואז דירוג בפייתון. הסינון מקטין
        # את מה שנטען; הדירוג נשאר זהה-לוגיקה ל-kb_loader כדי ששני
        # המסלולים לא יחזירו סדר שונה לאותה שאלה.
        stmt = select(KbChunk)
        for t in terms:
            stmt = stmt.where(KbChunk.content.ilike(f"%{t}%"))
        rows = db.execute(stmt.limit(400)).scalars().all()

        scored = []
        for row in rows:
            s = _score(row.content, row.heading, terms)
            if s > 0:
                scored.append((s, row))
        scored.sort(key=lambda pair: pair[0], reverse=True)

        results = [
            {
                "center_key": row.center_key,
                "filename": row.filename,
                "heading": row.heading,
                "title_he": row.title_he,
                "text": row.content[:SECTION_CHAR_CAP],
                "score": round(score, 2),
            }
            for score, row in scored[:max_results]
        ]
        return {
            "available": True, "source": "index",
            "query": query, "results": results,
            "indexed_chunks": total,
        }
    finally:
        if owned:
            db.close()


def index_summary(db) -> dict[str, Any]:
    """לתצוגה: מה מרכז הידע מכיל בפועל — בלי לקרוא את הדיסק."""
    rows = db.execute(
        select(KbChunk.center_key, KbChunk.filename, func.count(KbChunk.id))
        .group_by(KbChunk.center_key, KbChunk.filename)
    ).all()
    by_center: dict[str, list[dict[str, Any]]] = {}
    for center_key, filename, count in rows:
        by_center.setdefault(center_key, []).append(
            {"filename": filename, "sections": count}
        )
    return {
        "centers": by_center,
        "files": sum(len(v) for v in by_center.values()),
        "chunks": sum(f["sections"] for v in by_center.values() for f in v),
    }
