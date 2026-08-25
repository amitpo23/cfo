"""S4 (ספרינט זהות-מושקו, 25/08/2026) — לוח פיילוט read-only ל-WhatsApp
(5 ארגונים). קריטריון ההצלחה מהתוכנית: 'שאילתה אחת עונה כמה עלה השבוע
ומה נשבר'. משתמש בקונבנציית session_id הקיימת (wa-/tg- prefix, ר'
`_apply_moshko_filters` ב-admin.py) — אין מנוע חדש, רק צירוף של נתונים
קיימים (LLMUsage לעלות, ChatMessage לתורים, MoshkoGap למה-נשבר).
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

_CHANNEL_PREFIXES = {"whatsapp": "wa-", "telegram": "tg-"}


def compute_pilot_summary(
    db, *, channel: str = "whatsapp", organization_id: Optional[int] = None,
    since: Optional[datetime] = None, until: Optional[datetime] = None,
) -> dict[str, Any]:
    from ..models import ChatMessage, LLMUsage, MoshkoGap

    prefix = _CHANNEL_PREFIXES.get(channel)
    if prefix is None:
        raise ValueError(f"unknown channel: {channel!r}")

    def _scoped(query, model):
        query = query.filter(model.session_id.like(f"{prefix}%"))
        if organization_id is not None:
            query = query.filter(model.organization_id == organization_id)
        if since is not None:
            query = query.filter(model.created_at >= since)
        if until is not None:
            query = query.filter(model.created_at <= until)
        return query

    usage_rows = _scoped(db.query(LLMUsage), LLMUsage).all()
    llm_calls = len(usage_rows)
    cost_usd_total = sum((row.cost_usd or Decimal("0")) for row in usage_rows)

    assistant_turns = _scoped(
        db.query(ChatMessage).filter(ChatMessage.role == "assistant"), ChatMessage,
    ).count()

    gap_rows = _scoped(db.query(MoshkoGap), MoshkoGap).all()
    gaps_opened = len(gap_rows)
    gaps_still_open = sum(1 for g in gap_rows if g.status == "open")

    return {
        "channel": channel,
        "period": {
            "since": since.isoformat() if since else None,
            "until": until.isoformat() if until else None,
        },
        "llm_calls": llm_calls,
        "cost_usd_total": cost_usd_total,
        "assistant_turns": assistant_turns,
        "gaps_opened": gaps_opened,
        "gaps_still_open": gaps_still_open,
    }
