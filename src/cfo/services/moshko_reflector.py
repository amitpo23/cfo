"""S7 (ספרינט זהות-מושקו, 25/08/2026) — "Reflector" בסגנון ACE
(Reflector/Curator), מפורטט מ-`amitpo23/medici-travel-os` (`src/core/
learning/reflector.ts`) — ריפו אחר של הבעלים שכבר פתר בדיוק את הבעיה
שחסרה כאן: הפער בין תור-הכישלונות (`moshko_gaps`, קיים) לבין הפרומפט.

הופך שורת `MoshkoGap` אחת (שאלה+תשובה — "תמליל+outcome") לעד 3 לקחים
מועמדים, דרך קריאת LLM אחת. חילוץ צר במכוון — קטגוריות מותרות בלבד,
לעולם לא נוגע בכסף/אישור/שידור (ה-Curator ב-`moshko_curator.py` אוכף
את הגבול הזה שוב בשלב הקידום — הגנה כפולה, לא שער יחיד).

fail-quiet כשאין client: מחזיר [] בלי לזרוק — ריצת-batch לא אמורה
ליפול על סביבה בלי ANTHROPIC_API_KEY, בדיוק כמו הרפרנס.
"""
from __future__ import annotations

import json
import re
from typing import Any, Optional

MODEL = "claude-sonnet-5"
MAX_TOKENS = 512
MAX_LESSONS = 3

VALID_CATEGORIES = {"preference", "communication", "process"}

SYSTEM_PROMPT = (
    "את/ה 'Reflector' בצינור למידה מבוקר (ACE — Reflector/Curator) עבור "
    "מושקו, סוכן ה-CFO הדיגיטלי של רצף.\n"
    "המשימה שלך: לקרוא שאלה של משתמש ותשובה שמושקו נתן לה (או ויתור-מפורש "
    "עליה), ולחלץ ממנה עד 3 לקחים כלליים וניתנים-להפעלה שיעזרו לשיחות "
    "עתידיות דומות.\n\n"
    "כללים מחייבים (אין לחרוג מהם):\n"
    "- לקח מותר אך ורק באחת משלוש הקטגוריות: preference (העדפת משתמש), "
    "communication (סגנון/טון תשובה), process (סדר-פעולות/איזה כלי לבדוק "
    "קודם).\n"
    "- אסור בהחלט לחלץ לקח שנוגע, ולו במרומז, להוצאה/תשלום/חשבונית/מע\"מ/"
    "אישור/שידור לרשויות/מכסת API. אם התמליל מלמד משהו בתחום הזה — "
    "פשוט התעלם ממנו.\n"
    "- כל לקח הוא משפט אחד, קצר, ברור ופעיל בעברית — לא ניתוח כללי.\n"
    "- אם אין לקח כללי אמיתי לחלץ — החזר מערך ריק.\n\n"
    "פורמט התשובה: אך ורק מערך JSON תקני, ללא טקסט נוסף לפני/אחרי:\n"
    '[{"text": "...", "category": "preference"}, ...]'
)


def _parse_candidate_lessons(raw_text: str) -> list[dict[str, str]]:
    match = re.search(r"\[[\s\S]*\]", raw_text or "")
    if not match:
        return []
    try:
        parsed = json.loads(match.group(0))
    except (json.JSONDecodeError, ValueError):
        return []
    if not isinstance(parsed, list):
        return []

    lessons: list[dict[str, str]] = []
    for item in parsed:
        if len(lessons) >= MAX_LESSONS:
            break
        if not isinstance(item, dict):
            continue
        text = item.get("text")
        category = item.get("category")
        if not isinstance(text, str) or not text.strip():
            continue
        if category not in VALID_CATEGORIES:
            continue
        lessons.append({"text": text.strip(), "category": category})
    return lessons


async def extract_candidate_lessons(
    gap, *, client: Optional[Any] = None,
) -> list[dict[str, str]]:
    """`gap` הוא שורת MoshkoGap (question/answer/gap_kind). מחזיר []
    fail-quiet כשאין client/מפתח — לא זורק, לא מפיל ריצת-batch."""
    if client is None:
        from ..config import settings
        if not settings.anthropic_api_key:
            return []
        import anthropic
        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    user_content = json.dumps({
        "question": gap.question, "answer": gap.answer,
        "outcome": {"kind": gap.gap_kind},
    }, ensure_ascii=False)

    try:
        response = await client.messages.create(
            model=MODEL, max_tokens=MAX_TOKENS, system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_content}],
        )
    except Exception:
        return []

    text = "\n".join(
        block.text for block in response.content
        if getattr(block, "type", None) == "text"
    )
    return _parse_candidate_lessons(text)
