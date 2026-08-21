"""W6.2 — reaper לפעולות כסף תקועות (סיכון #2 ב-SWOT ‏20/08).

`confirm_action` כותב `action_claimed_at` — ועד היום אף תהליך לא קרא
אותו: פעולה שנתקעה ב-`executing` (קריסת instance באמצע) או ב-`unknown`
נשארה כך לנצח, בלתי-נראית.

העקרונות:
- executing מעל STALE_MINUTES ⇒ **unknown**, לעולם לא retry ולעולם לא
  "failed": הספק אולי כן ביצע — ההכרעה חייבת אדם + אימות מול הספק.
- כל unknown מקבל שורה בתור הפערים (moshko_gaps) + CfoInsight קריטי —
  פעם אחת (אידמפוטנטי לפי message_id/fingerprint).
- IrreversibleActionRequest תקוע ב-executing ⇒ CfoInsight בלבד (מכונת
  המצבים שלו דורשת הכרעה מפורשת; אין מעבר אוטומטי).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from ..models import CfoInsight, ChatMessage, MoshkoGap

STALE_MINUTES = 15


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _ensure_gap_and_insight(db: Session, msg: ChatMessage) -> bool:
    """שורת פער + תובנה לפעולה תקועה — אידמפוטנטי. מחזיר אם נוצר חדש."""
    created = False
    existing_gap = db.query(MoshkoGap).filter(
        MoshkoGap.message_id == msg.id,
    ).first()
    tool_name = (msg.pending_action or {}).get("tool")
    if existing_gap is None:
        db.add(MoshkoGap(
            organization_id=msg.organization_id,
            user_id=msg.user_id,
            session_id=msg.session_id,
            message_id=msg.id,
            question=None,
            answer=msg.content,
            gap_kind="tool_failed",
            tool_name=tool_name,
            error=(
                f"פעולה תקועה במצב '{msg.action_status}' — ייתכן שהספק ביצע "
                "אותה. נדרש אימות ידני מול SUMIT/הבנק לפני כל ניסיון נוסף."
            ),
        ))
        created = True

    fingerprint = f"stuck_action:{msg.organization_id}:{msg.id}"
    existing_insight = db.query(CfoInsight).filter(
        CfoInsight.organization_id == msg.organization_id,
        CfoInsight.fingerprint == fingerprint,
    ).first()
    if existing_insight is None:
        db.add(CfoInsight(
            organization_id=msg.organization_id,
            fingerprint=fingerprint,
            insight_type="stuck_action",
            severity="critical",
            title=f"פעולת כסף תקועה: {tool_name or 'לא ידוע'} (הודעה {msg.id})",
            message=(
                "הפעולה אושרה והביצוע לא הסתיים — ייתכן שהספק ביצע אותה "
                "בלי שנרשם אצלנו. אין לנסות שוב לפני אימות ידני מול הספק."
            ),
            evidence={
                "message_id": msg.id,
                "session_id": msg.session_id,
                "tool": tool_name,
                "action_status": msg.action_status,
            },
            recommended_action="לאמת מול SUMIT/הבנק אם הפעולה בוצעה; לעדכן את הספרים בהתאם ולסגור את הפער.",
        ))
        created = True
    return created


def sweep(db: Session) -> dict[str, Any]:
    """סריקה אחת: מיישן executing, ומוודא נראות לכל unknown."""
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(minutes=STALE_MINUTES)

    stale_executing = 0
    surfaced_unknown = 0

    executing = db.query(ChatMessage).filter(
        ChatMessage.action_status == "executing",
    ).all()
    for msg in executing:
        claimed = _aware(msg.action_claimed_at)
        if claimed is not None and claimed > cutoff:
            continue  # עדיין בתוך חלון ביצוע לגיטימי
        msg.action_status = "unknown"
        msg.action_error = (
            (msg.action_error or "")
            + f" | reaper: תקוע ב-executing מעל {STALE_MINUTES} דקות"
        ).strip(" |")
        _ensure_gap_and_insight(db, msg)
        stale_executing += 1

    unknown = db.query(ChatMessage).filter(
        ChatMessage.action_status == "unknown",
    ).all()
    for msg in unknown:
        if _ensure_gap_and_insight(db, msg):
            surfaced_unknown += 1

    db.commit()
    return {
        "stale_executing": stale_executing,
        "surfaced_unknown": surfaced_unknown,
        "checked_at": now.isoformat(),
    }
