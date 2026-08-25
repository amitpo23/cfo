"""S8 (ספרינט זהות-מושקו, 25/08/2026) — Curator, מפורטט מ-
`amitpo23/medici-travel-os` (`src/core/learning/lessons.ts`): מיזוג
לקחים-מועמדים כמעט-זהים, קידום רק אחרי ≥3 הופעות בלתי-תלויות (בבאצ'
אחד — לא נצבר לאורך זמן בטבלה נפרדת, כדי לא לדרוש מיגרציה חדשה) +
שער-מדיניות קשיח שחוסם כל לקח שנוגע לכסף/אישור/שידור.

**התאמה לדוקטרינות רצף (שונה מהרפרנס):** ברפרנס, לקח שעובר את הסף
הופך "active" ומוזרק ישירות לפלייבוק. ברצף — אפס אוטונומיה בבלתי-הפיך:
קידום יוצר שורת `MoshkoMemory` עם `approved_at=None` — נכנס לתור-
האישור הקיים, לא מוזרק לפרומפט עד שהבעלים מאשר (אותו מנגנון שכבר
קיים לזיכרון ידני/משיחה).
"""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Any, Optional

DEFAULT_MIN_OCCURRENCES = 3

# שער-מדיניות קשיח, מכוון-fail-closed (התאמת-יתר עדיפה על החמצה):
# תבניות שמזהות אזכור כסף/אישור/שידור — משפחת-שורש בעברית, לא מילה
# מדויקת אחת (כתיב-סופיות משתנה: הוצאה/הוצאות/להוציא).
MONEY_PATH_PATTERNS: tuple[re.Pattern, ...] = (
    re.compile(r"הוצא"),       # הוצאה/להוציא/הוצאות
    re.compile(r"תשלום"),
    re.compile(r"לשלם"),
    re.compile(r"שילם"),
    re.compile(r"חשבונ"),      # חשבונית/חשבון
    re.compile(r"מסמך"),       # הפקת מסמך — פעולת-כתיבה שדורשת אישור
    re.compile(r"מע\"מ"),
    re.compile(r"אישור"),
    re.compile(r"לאשר"),
    re.compile(r"מאשר"),
    re.compile(r"שידור"),      # שידור לרשויות
    re.compile(r"לשדר"),       # "לשדר" (השורש שד-ר, בלי תנועת-האמצע שיש ב"שידור")
    re.compile(r"גביי"),       # גבייה/לגבות
    re.compile(r"לדלג"),       # "לדלג על שלב האישור" וכו'
    re.compile(r"מכסת? ?api", re.IGNORECASE),
    re.compile(r"\bbook\b", re.IGNORECASE),
    re.compile(r"\bpay\b", re.IGNORECASE),
    re.compile(r"\bcharge\b", re.IGNORECASE),
    re.compile(r"\bbypass\b", re.IGNORECASE),
)

# reflector category -> moshko_memory.category (documented: preference |
# business_fact | correction | convention)
_CATEGORY_MAP = {"preference": "preference", "communication": "convention", "process": "convention"}


def is_money_path_lesson(text: str) -> bool:
    return any(p.search(text or "") for p in MONEY_PATH_PATTERNS)


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip()).lower()


async def run_learning_batch(
    db, gaps: list, *, client: Optional[Any] = None,
    min_occurrences: int = DEFAULT_MIN_OCCURRENCES,
) -> dict[str, Any]:
    """מריץ Reflector על כל gap ב-batch, ממזג לקחים כמעט-זהים (נורמליזציה
    של רווחים+case), ומקדם רק את מה שעובר גם סף-הופעות וגם שער-המדיניות.
    קריאה-בלבד על gaps עצמם; כותב רק שורות MoshkoMemory ממתינות-אישור."""
    from ..models import MoshkoMemory
    from .moshko_reflector import extract_candidate_lessons

    # normalized_text -> {"text":..., "category":..., "occurrences":int, "org_ids":set}
    candidates: dict[str, dict[str, Any]] = {}
    gaps_processed = 0
    candidates_extracted = 0

    for gap in gaps:
        gaps_processed += 1
        lessons = await extract_candidate_lessons(gap, client=client)
        for lesson in lessons:
            candidates_extracted += 1
            key = _normalize(lesson["text"])
            entry = candidates.setdefault(key, {
                "text": lesson["text"], "category": lesson["category"],
                "occurrences": 0, "org_ids": set(),
            })
            entry["occurrences"] += 1
            entry["org_ids"].add(gap.organization_id)

    promoted: list[dict[str, Any]] = []
    rejected_money_path: list[dict[str, Any]] = []

    for entry in candidates.values():
        if entry["occurrences"] < min_occurrences:
            continue
        if is_money_path_lesson(entry["text"]):
            rejected_money_path.append({
                "text": entry["text"], "occurrences": entry["occurrences"],
            })
            continue

        memory_category = _CATEGORY_MAP.get(entry["category"], "convention")
        memory_ids = []
        for org_id in sorted(entry["org_ids"]):
            row = MoshkoMemory(
                organization_id=org_id, user_id=None,
                content=entry["text"], category=memory_category,
                source="inferred", approved_at=None,
            )
            db.add(row)
            db.flush()
            memory_ids.append(row.id)

        promoted.append({
            "text": entry["text"], "category": memory_category,
            "occurrences": entry["occurrences"],
            "orgs": sorted(entry["org_ids"]), "memory_ids": memory_ids,
        })

    db.commit()
    return {
        "gaps_processed": gaps_processed,
        "candidates_extracted": candidates_extracted,
        "promoted": promoted,
        "rejected_money_path": rejected_money_path,
    }
