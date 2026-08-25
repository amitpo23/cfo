"""S9 (ספרינט זהות-מושקו, 24-25/08/2026) — מדד המיקוד.

שלושה מספרים שקיימים כבר בנתונים, בלי מנוע חדש: אחוז תשובות-ויתור,
gaps ל-100 תורים, אחוז regression-pass (הרצה אחרונה). קריאה בלבד —
לא כותב דבר.

**למה זה קיים (הנחיית הבעלים, 24/08/2026):** "מושקו מתפזר ולא ממוקד".
בלי מספר לפני ואחרי, אי אפשר לדעת אם S5/S6 (פיצול MOSHKO_IDENTITY,
פרוטוקול-תור) שיפרו משהו — רק "מרגיש יותר טוב". נבנה **לפני** S5/S6
במכוון, כדי שיהיה בייסליין אמיתי.

honest-null: אין תורים בתקופה ⇒ None בכל השיעורים, לא 0% (0% היה טוען
"מצוין" על תקופה שאין בה שום ראיה).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional


def compute_focus_metrics(
    db, *, organization_id: Optional[int] = None,
    since: Optional[datetime] = None, until: Optional[datetime] = None,
) -> dict[str, Any]:
    from ..models import ChatMessage, MoshkoGap

    msg_q = db.query(ChatMessage).filter(ChatMessage.role == "assistant")
    gap_q = db.query(MoshkoGap)
    if organization_id is not None:
        msg_q = msg_q.filter(ChatMessage.organization_id == organization_id)
        gap_q = gap_q.filter(MoshkoGap.organization_id == organization_id)
    if since is not None:
        msg_q = msg_q.filter(ChatMessage.created_at >= since)
        gap_q = gap_q.filter(MoshkoGap.created_at >= since)
    if until is not None:
        msg_q = msg_q.filter(ChatMessage.created_at <= until)
        gap_q = gap_q.filter(MoshkoGap.created_at <= until)

    assistant_turns = msg_q.count()
    gaps = gap_q.all()
    gaps_opened = len(gaps)
    giveup_count = sum(1 for g in gaps if g.gap_kind == "model_gave_up")

    # regression-pass: רק gaps שהרצת-הרגרסיה האחרונה נגעה בהם (regression_status
    # לא-ריק) — לא סוגרים על gaps שמעולם לא הורצו כאילו "נכשלו".
    regression_rows = [g for g in gaps if g.regression_status is not None]
    regression_total = len(regression_rows)
    regression_passed = sum(1 for g in regression_rows if g.regression_status == "passed")

    return {
        "period": {
            "since": since.isoformat() if since else None,
            "until": until.isoformat() if until else None,
        },
        "assistant_turns": assistant_turns,
        "giveup_count": giveup_count,
        "giveup_rate": (
            round(100.0 * giveup_count / assistant_turns, 2)
            if assistant_turns else None
        ),
        "gaps_opened": gaps_opened,
        "gaps_per_100_turns": (
            round(100.0 * gaps_opened / assistant_turns, 2)
            if assistant_turns else None
        ),
        "regression_total": regression_total,
        "regression_passed": regression_passed,
        "regression_pass_rate": (
            round(100.0 * regression_passed / regression_total, 2)
            if regression_total else None
        ),
    }
