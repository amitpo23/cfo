"""Liquidity strip for /cashflow-detail.

The checking figure is ``checking_snapshot``. Credit used, headroom and breach
come from the same hero the client dashboard already shows. A missing balance
stays missing: it is not a current ratio of 0 and not a runway of 0.

No provider call.
"""
from __future__ import annotations

from datetime import date

from ..credit_line_service import get_credit_line_status
from .liquidity import build_liquidity, checking_snapshot
from .liquidity_today import build_liquidity_today


def ratios_from_checking(balance: float | None) -> dict:
    """Accounting ratios are not invented from an unknown checking balance.

    A positive balance can be shown as cash on hand. An overdraft is utilization
    of the credit line, not a current-asset figure of 0. Current, quick and cash
    ratios need a full current balance sheet, which this snapshot does not carry.
    """
    if balance is None:
        return {
            "current_ratio": None,
            "quick_ratio": None,
            "cash_ratio": None,
            "working_capital": None,
            "current_assets": None,
            "current_liabilities": None,
            "missing_label": "יתרת העו״ש לא ידועה לשימוש. חסר אינו 0.",
        }
    assets = round(float(balance), 2) if float(balance) >= 0 else None
    if assets is None:
        label = "העו״ש במינוס, ולכן הוא מוצג כניצול מסגרת ולא כנכס שוטף."
    else:
        label = "הסכום בנכסים שוטפים הוא יתרת העו״ש בלבד. יחס שוטף, מהיר ומזומן דורשים מאזן שוטף מלא."
    return {
        "current_ratio": None,
        "quick_ratio": None,
        "cash_ratio": None,
        "working_capital": None,
        "current_assets": assets,
        "current_liabilities": None,
        "missing_label": label,
    }


def cashflow_liquidity_surface(db, organization_id: int, *, today: date | None = None) -> dict:
    today = today or date.today()
    snap = checking_snapshot(db, organization_id, today=today)
    section = build_liquidity(
        db, organization_id, date(today.year, today.month, 1), today,
        classified=[], today=today,
    )
    hero = build_liquidity_today(section, None, today=today)
    balance = snap.get("balance")
    if balance is None:
        checking = dict(hero["checking"])
        checking["balance"] = None
        checking["status"] = "unknown"
        facility = dict(hero["facility"])
        facility["used"] = None
        facility["headroom"] = None
        facility["breach"] = None
    else:
        checking = hero["checking"]
        facility = hero["facility"]
    credit = get_credit_line_status(db, organization_id)
    status = credit.get("status")
    reason = credit.get("reason") if balance is None or status in {"breach", "warning"} else None
    return {
        "ratios": ratios_from_checking(balance),
        "checking": checking,
        "facility": facility,
        "credit_line_status": status,
        "credit_line_reason": reason,
        "provider_calls": 0,
    }
