"""W1.5 — regression runner לשאלות שקודמו לידע.

כשתשובת בעלים מקודמת לזיכרון מאושר ("ענה וקדם לידע", `admin.py` —
`review_moshko_gap`), השאלה המקורית *נשארת* על אותה שורת ``MoshkoGap``
(``promoted_memory_id`` לא-ריק) — אין טבלה נפרדת למקרי רגרסיה. השורה הזו
היא בדיוק מקרה הרגרסיה: השאלה + הזיכרון שאמור לענות עליה מעכשיו.

הרצה (`run_regression`) מריצה כל מקרה כזה מחדש דרך ``AIChatService``
ובודקת שני דברים בלתי-תלויים:

1. הזיכרון שקודם *אכן הוזרק* להקשר — דרך אותו מנגנון בדיוק ש-
   ``AIChatService.send_message`` משתמש בו (``moshko_memory.render_memory_block``),
   נבדק **לפני** קריאת השיחה (זו בדיוק ההזרקה הקפואה שהתור הזה יקבל —
   ראו התיעוד ב-moshko_memory.render_memory_block).
2. התשובה אינה תשובת-ויתור — הגלאי הקיים מ-W1.1
   (``ai_chat_service.is_giveup_answer``), לא גלאי שני.

מקרה שנכשל נפתח מחדש (status='open') — סיבוב הלולאה: הבעלים רואה אותו
שוב בתור הפערים ויכול לתקן את הזיכרון/לענות מחדש. מקרה שעבר משאיר את
סטטוס הגאפ כפי שהיה (בד"כ 'answered').

ריצה **ידנית בלבד** — עולה טוקני LLM אמיתיים לכל מקרה (ולעיתים גם
קריאות SUMIT/Open-Finance דרך כלי-קריאה שהמודל בוחר להפעיל, תחת שערי
המכסה הקיימים) — הבעלים לוחץ במפורש דרך route אדמין; **אין** קריאה
מ-cron/scheduler בקובץ הזה או במקום אחר.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy.orm import Session

from ..models import MoshkoGap, MoshkoMemory
from . import moshko_memory
from .ai_chat_service import AIChatService, is_giveup_answer

_DEFAULT_LIMIT = 50


async def _run_one_case(db: Session, gap: MoshkoGap) -> dict[str, Any]:
    """מריץ מקרה רגרסיה בודד ומעדכן את שדות התוצאה על שורת ה-gap.

    honest-null: אם אין זיכרון מקודם קיים (נמחק) או שלא נשמרה שאלה
    מקורית — המקרה מדולג (status='skipped'), לא נכשל ולא עובר.
    """
    memory = db.query(MoshkoMemory).filter(
        MoshkoMemory.id == gap.promoted_memory_id,
        MoshkoMemory.organization_id == gap.organization_id,
    ).first()
    if memory is None or not gap.question:
        return {
            "gap_id": gap.id,
            "status": "skipped",
            "reason": "אין זיכרון מקודם קיים או שאלה מקורית לבדיקה",
        }

    # אותו מנגנון בדיוק ש-AIChatService.send_message קורא לו בתחילת התור
    # (הזרקה קפואה) — נבדק לפני קריאת המודל, לא אחריה, כדי לשקף בדיוק את
    # מה שהתור הזה קיבל בפרומפט שלו.
    memory_block = moshko_memory.render_memory_block(
        db, gap.organization_id, gap.user_id,
    )
    injected = memory.content in memory_block

    session_id = f"regression-{gap.id}-{uuid.uuid4().hex[:8]}"
    service = AIChatService(
        db, gap.organization_id, gap.user_id, is_super_admin=False,
    )
    chat_result = await service.send_message(session_id, gap.question)
    reply = chat_result.get("reply") or ""
    gave_up = is_giveup_answer(reply)

    # send_message עצמו עשוי היה ללכוד את תשובת-הוויתור כשורת gap חדשה
    # (W1.1, אותו session_id) — הלולאה הזו היא מקור-האמת היחיד למקרה הזה,
    # אז השורה האוטומטית הכפולה מוסרת במקום להכפיל את התור.
    db.query(MoshkoGap).filter(
        MoshkoGap.session_id == session_id,
        MoshkoGap.organization_id == gap.organization_id,
        MoshkoGap.user_id == gap.user_id,
        MoshkoGap.id != gap.id,
    ).delete(synchronize_session=False)

    passed = injected and not gave_up
    now = datetime.utcnow()
    gap.regression_status = "passed" if passed else "failed"
    gap.regression_checked_at = now
    gap.updated_at = now
    if not passed:
        # סיבוב הלולאה: מקרה שנכשל נפתח מחדש כפער לבדיקה חוזרת של הבעלים.
        gap.status = "open"

    return {
        "gap_id": gap.id,
        "status": gap.regression_status,
        "memory_injected": injected,
        "gave_up": gave_up,
        "reply": reply,
    }


async def run_regression(
    db: Session, *, organization_id: Optional[int] = None,
    limit: int = _DEFAULT_LIMIT,
) -> dict[str, Any]:
    """מריץ את כל מקרי הרגרסיה (gaps מקודמים) דרך AIChatService. ידני
    בלבד — נקרא רק מ-route אדמין super-admin (POST /admin/moshko/regression/run).

    ``organization_id=None`` בודק בכל הארגונים (כמו list_moshko_gaps) —
    צפייה חוצת-ארגונים כבר קיימת לתפקיד super-admin באותו מסך; כל מקרה
    בפועל עדיין רץ בתוך ה-org/user שלו (AIChatService מסונן ארגונית).
    ``limit`` עוצר תפוצת עלות (כל מקרה = טוקני LLM אמיתיים).

    כל מקרה מתבצע ומאושר (commit) בנפרד — כישלון/שגיאת רשת במקרה אחד
    (status='error') לא מוחק את התוצאות שכבר נשמרו למקרים קודמים.
    """
    query = db.query(MoshkoGap).filter(MoshkoGap.promoted_memory_id.isnot(None))
    if organization_id is not None:
        query = query.filter(MoshkoGap.organization_id == organization_id)
    cases = query.order_by(MoshkoGap.id.asc()).limit(limit).all()

    results: list[dict[str, Any]] = []
    for gap in cases:
        try:
            result = await _run_one_case(db, gap)
            db.commit()
        except Exception as exc:  # noqa: BLE001 — honest per-case failure, not a crashed run
            db.rollback()
            result = {"gap_id": gap.id, "status": "error", "reason": str(exc)}
        results.append(result)

    return {
        "total": len(results),
        "passed": sum(1 for r in results if r["status"] == "passed"),
        "failed": sum(1 for r in results if r["status"] == "failed"),
        "skipped": sum(1 for r in results if r["status"] == "skipped"),
        "errored": sum(1 for r in results if r["status"] == "error"),
        "cases": results,
    }
