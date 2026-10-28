"""Forecast for the coming months: a port of the Eliav tool's "תחזית" tab.

For each coming month and row (revenue, costs, loan principal) a budget saved
on the plan wins. Otherwise the median of the last three full months, grown by
the plan parameters (``statusParameters.revenueGrowthPct`` /
``costGrowthPct`` per month). The median keeps a one-off (a loan paid off
early) from driving the trend. Actuals come from the P&L months of the same
view, so each month has one source (books or classified bank cash, ex-VAT).

Amounts are ex-VAT; the cash line is result minus principal, an approximation
that is labelled as such. Unknown stays ``None``. No provider calls.
"""
from __future__ import annotations

from datetime import date

from . import forecast_rules

DEFAULT_PARAMETERS = {
    "scenario": "בסיס", "horizonMonths": 6, "revenueGrowthPct": 0.0,
    "costGrowthPct": 0.0, "vatRate": 0.18,
}
ROWS = (
    ("revenue", "הכנסות", "revenue"),
    ("costs", "הוצאות", "cost"),
    ("principal", "החזרי קרן — הלוואות וליסינג", "financing"),
)
TREND_MONTHS = 3


def parameters(plan: dict | None) -> dict:
    raw = (plan or {}).get("statusParameters") if isinstance(plan, dict) else None
    raw = raw if isinstance(raw, dict) else {}
    out = dict(DEFAULT_PARAMETERS)
    if isinstance(raw.get("scenario"), str) and raw["scenario"].strip():
        out["scenario"] = raw["scenario"].strip()[:80]
    try:
        out["horizonMonths"] = min(12, max(1, int(raw.get("horizonMonths", out["horizonMonths"]))))
    except (TypeError, ValueError):
        pass
    for key in ("revenueGrowthPct", "costGrowthPct", "vatRate"):
        value = raw.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            out[key] = float(value)
    return out


def _r(value: float) -> float:
    return round(value + 0.0, 2)


def _median(values: list[float]) -> float | None:
    values = sorted(values)
    if not values:
        return None
    mid = len(values) // 2
    return _r(values[mid] if len(values) % 2 else (values[mid - 1] + values[mid]) / 2)


def _next_months(as_of: date, count: int) -> list[str]:
    year, month = as_of.year, as_of.month
    out = []
    for _ in range(count):
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
        out.append(f"{year}-{month:02d}")
    return out


def full_months(pnl_months: list[dict], as_of: date) -> list[dict]:
    """Known months that ended before the month of ``as_of``."""
    current = f"{as_of.year}-{as_of.month:02d}"
    return [
        month for month in pnl_months or []
        if isinstance(month, dict) and month.get("month", "") < current
        and month.get("source") and month.get("revenue") is not None and month.get("costs") is not None
    ]


def build_forecast(pnl_months: list[dict], *, as_of: date, plan: dict | None = None,
                   debt_service: list[dict] | None = None, budget_sums: dict | None = None,
                   opening_balance: float | None = None) -> dict:
    """``budget_sums`` is ``plan_budget.monthly_line_sums`` (None: no budget for this entity)."""
    prm = parameters(plan)
    basis = full_months(pnl_months, as_of)[-TREND_MONTHS:]
    based_on = [month["month"] for month in basis]
    service = {row["month"]: row for row in debt_service or [] if isinstance(row, dict)}
    trend = {
        "revenue": _median([float(m["revenue"]) for m in basis]),
        "costs": _median([float(m["costs"]) for m in basis]),
        "principal": _median([
            float(service[m]["principal"]) for m in based_on
            if m in service and service[m].get("principal") is not None
        ]),
    }
    growth = {"revenue": prm["revenueGrowthPct"] / 100, "costs": prm["costGrowthPct"] / 100, "principal": 0.0}
    months = _next_months(as_of, prm["horizonMonths"])
    sums = budget_sums or {}
    rows = []
    for row_id, label, kind in ROWS:
        cells = {}
        for index, month in enumerate(months, start=1):
            budget = (sums.get(month) or {}).get(kind)
            if budget is not None:
                cells[month] = {"value": _r(budget), "source": "budget"}
            elif trend[row_id] is not None:
                cells[month] = {"value": _r(trend[row_id] * (1 + growth[row_id]) ** index), "source": "trend"}
            else:
                cells[month] = {"value": None, "source": None}
        rows.append({"id": row_id, "label": label, "months": cells})
    by_id = {row["id"]: row for row in rows}
    totals = {}
    cumulative = 0.0
    known = True
    for month in months:
        revenue = by_id["revenue"]["months"][month]["value"]
        costs = by_id["costs"]["months"][month]["value"]
        principal = by_id["principal"]["months"][month]["value"]
        result = None if revenue is None or costs is None else _r(revenue - costs)
        cash = None if result is None else _r(result - (principal or 0.0))
        known = known and cash is not None
        cumulative = _r(cumulative + cash) if known else None
        totals[month] = {
            "revenue": revenue, "costs": costs, "result": result, "principal": principal,
            "cash_flow": cash, "cumulative_cash": cumulative if known else None,
            "projected_balance": None if not known or opening_balance is None else _r(opening_balance + cumulative),
        }
        if not known:
            cumulative = 0.0
    return {
        "status": "ready" if based_on or sums else "unknown",
        "months": months,
        "rows": rows,
        "totals": totals,
        "based_on": based_on,
        "parameters": prm,
        "opening_balance": opening_balance,
        "message": (
            f"לכל חודש: תקציב אם הוזן; אחרת חציון של {', '.join(based_on) or 'אין חודשים מלאים'} "
            f"כפול צמיחה חודשית (הכנסות {prm['revenueGrowthPct']}%, הוצאות {prm['costGrowthPct']}%). "
            "הסכומים ללא מע״מ; תזרים = תוצאה פחות החזרי קרן (קירוב)."
        ),
        "provider_calls": 0,
        "cash_rules": forecast_rules.monthly_table(plan, months),
    }


def combined_pnl_months(sections: list[dict]) -> list[dict]:
    """Per-month sum of every entity's P&L month. A month any entity does not know stays unknown."""
    index: dict[str, list[dict]] = {}
    for section in sections:
        for month in ((section.get("view") or {}).get("pnl") or {}).get("months") or []:
            if isinstance(month, dict) and month.get("month"):
                index.setdefault(month["month"], []).append(month)
    out = []
    for key in sorted(index):
        parts = index[key]
        known = len(parts) == len(sections) and all(
            p.get("source") and p.get("revenue") is not None and p.get("costs") is not None for p in parts
        )
        out.append({
            "month": key,
            "source": "combined" if known else None,
            "revenue": _r(sum(float(p["revenue"]) for p in parts)) if known else None,
            "costs": _r(sum(float(p["costs"]) for p in parts)) if known else None,
        })
    return out
