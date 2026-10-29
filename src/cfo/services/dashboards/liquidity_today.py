"""One screen of today's cash position from data already on the dashboard view.

No provider call. A checking balance older than two days is not usable. The
last stored booked amount stays visible beside that label and is never turned
into today's number.
"""
from __future__ import annotations

from datetime import date


def build_liquidity_today(liquidity: dict | None, forecast: dict | None, *, today: date) -> dict:
    liquidity = liquidity if isinstance(liquidity, dict) else {}
    forecast = forecast if isinstance(forecast, dict) else {}
    position = liquidity.get("position") if isinstance(liquidity.get("position"), dict) else {}
    stale = [row for row in (liquidity.get("stale_balances") or []) if isinstance(row, dict)]
    balance = position.get("balance")
    as_of = position.get("as_of")
    source = position.get("balance_source")
    last_booked = balance
    last_as_of = as_of
    status = "ready" if balance is not None else "unknown"
    label = f"נכון ל-{as_of}" if as_of else "לא ידוע"
    if stale:
        last_booked = stale[0].get("observed_balance")
        last_as_of = stale[0].get("as_of")
        balance = None
        status = "unknown"
        label = f"לא ידוע לשימוש נכון ל-{last_as_of}" if last_as_of else "לא ידוע לשימוש — אין תאריך ליתרה"
    elif as_of and as_of != today.isoformat() and balance is not None:
        status = "not_today"
        label = f"היתרה אינה מהיום. נכון ל-{as_of}"
    limit = position.get("limit")
    headroom = None if balance is None or limit is None else position.get("available_to_limit")
    from .money_screens import credit_overrun
    overrun = credit_overrun(balance, limit)
    used = None
    if balance is not None:
        used = round(-float(balance), 2) if float(balance) < 0 else 0.0
    breach = None if headroom is None else float(headroom) < 0
    available_limit = None
    available_as_of = None
    for account in liquidity.get("accounts") or []:
        if not isinstance(account, dict) or account.get("kind") != "checking":
            continue
        if account.get("available_limit") is not None:
            available_limit = account.get("available_limit")
            available_as_of = account.get("as_of")
            break
    upcoming = []
    for item in (liquidity.get("upcoming") or [])[:8]:
        if not isinstance(item, dict):
            continue
        upcoming.append({
            "date": item.get("date"),
            "label": item.get("label"),
            "kind": item.get("kind"),
            "amount": item.get("amount"),
        })
    for item in (forecast.get("overdue") or [])[:4]:
        if isinstance(item, dict):
            upcoming.append({
                "date": item.get("date"),
                "label": item.get("label"),
                "kind": item.get("kind") or "overdue",
                "amount": item.get("amount"),
            })
    weeks = []
    for week in (forecast.get("weeks") or [])[:6]:
        if not isinstance(week, dict):
            continue
        weeks.append({key: week.get(key) for key in ("start", "end", "in", "out", "net", "closing", "headroom")})
    return {
        "as_of_today": today.isoformat(),
        "checking": {
            "balance": balance,
            "as_of": as_of or last_as_of,
            "source": source or "checking_snapshot",
            "status": status,
            "label_he": label,
            "last_booked": last_booked,
            "last_booked_as_of": last_as_of,
        },
        "facility": {
            "limit": limit,
            "used": used,
            "headroom": headroom,
            "breach": breach,
            "overrun": overrun["overrun"],
            "overrun_status": overrun["status"],
            "overrun_label": overrun["label_he"],
            "available_limit": available_limit,
            "available_as_of": available_as_of,
            "note_he": "הפנוי מול המסגרת הוא מסגרת ועוד יתרת העו״ש. יתרה זמינה מהבנק, אם נשמרה, מוצגת בנפרד ואינה מחליפה את היתרה הסגורה.",
        },
        "upcoming": upcoming,
        "weeks": weeks,
        "provider_calls": 0,
    }
