"""Thirteen-week cash forecast of a dashboard entity ("תזרים חזוי").

Design: ``docs/superpowers/specs/2026-10-26-cash-forecast-13w-design.md``.

A pure function over the ``/d/`` view model of one organization: the opening
balance and its date from ``liquidity.position``, dated items (post-dated
checks, loan maturities, owner items), the monthly loan principal, and an
operating run-rate from ``cash_statement``. Facilities from
``plan.liquidityEvidence.facilities`` give the limit of each week, and a
facility stops counting after its end date. No database, no provider calls.

Each item carries its certainty: ``certain`` (a dated check or maturity),
``scheduled`` (the monthly principal), ``manual`` (an owner item) or
``estimate`` (the run-rate). A known check is paid out of the operating
run-rate of its month instead of being added to it. An owner item is added
on top. Unknown stays ``None``: with no opening balance the closing balance
and the headroom are unknown, and nothing is guessed as 0.
"""
from __future__ import annotations

from calendar import monthrange
from datetime import date, timedelta
from statistics import median

from . import forecast_rules

WEEKS = 13
RUN_RATE_MONTHS = 3
# ``internal`` stays in each entity's run-rate: a transfer from Food Group is cash
# in Eliav's account. The other side sits in Food Group's ``transfers_out``, so the
# combined sum nets the pair. Financing (new loans) is not a run-rate.
# Cheque discounting is an advance on customer receipts, so it stays in operating inflows.
RUN_RATE_GROUPS = {
    "operating_in": "כניסות תפעוליות (הערכה לפי קצב)",
    "operating_out": "יציאות תפעוליות (הערכה לפי קצב)",
    "finance": "עמלות וריבית (הערכה לפי קצב)",
    "internal": "העברות בין ישויות והחזרים (הערכה לפי קצב)",
}
# Cash-statement lines that do not recur: a tax refund, a reversed charge.
ONE_OFF_LINES = frozenset({"tax_refund", "reversal"})
CHECK_STATES = ("future", "no_coverage")
CERTAIN, SCHEDULED, MANUAL, ESTIMATE = "certain", "scheduled", "manual", "estimate"
TOP_REASONS = 3


def _r(value: float) -> float:
    return round(value + 0.0, 2)


def _num(value) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _date(value) -> date | None:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10]) if value else None
    except ValueError:
        return None


MAX_ITEMS = 200
MAX_LABEL = 120


def validate_items(payload: dict) -> str | None:
    """Hebrew error for an invalid ``cashForecastItems``, or None. An item is an owner's
    dated obligation or receipt: an ISO date, a non-zero amount, a label."""
    items = payload.get("cashForecastItems") if isinstance(payload, dict) else None
    if items is None:
        return None
    if not isinstance(items, list) or len(items) > MAX_ITEMS:
        return f"פריטי התזרים חייבים להיות רשימה של עד {MAX_ITEMS} פריטים"
    for item in items:
        if not isinstance(item, dict):
            return "פריט תזרים חייב להיות אובייקט"
        raw = item.get("date")
        if not isinstance(raw, str) or len(raw) != 10 or _date(raw) is None:
            return "תאריך פריט תזרים חייב להיות בפורמט YYYY-MM-DD"
        amount = item.get("amount")
        if isinstance(amount, bool) or not isinstance(amount, (int, float)) or not amount or amount != amount:
            return "סכום פריט תזרים חייב להיות מספר שונה מאפס"
        label = item.get("label")
        if not isinstance(label, str) or not label.strip() or len(label) > MAX_LABEL:
            return f"תיאור פריט תזרים חובה, עד {MAX_LABEL} תווים"
        org = item.get("organizationId")
        if org is not None and (isinstance(org, bool) or not isinstance(org, int)):
            return "organizationId של פריט תזרים חייב להיות מספר"
    return None


def week_windows(today: date, weeks: int = WEEKS) -> list[tuple[date, date]]:
    """Sunday-to-Saturday weeks, starting with the week of ``today``."""
    start = today - timedelta(days=(today.weekday() + 1) % 7)
    return [(start + timedelta(weeks=i), start + timedelta(weeks=i, days=6)) for i in range(weeks)]


def _month(day: date) -> str:
    return f"{day.year}-{day.month:02d}"


def _days(start: date, end: date):
    day = start
    while day <= end:
        yield day
        day += timedelta(days=1)


def _facilities(plan: dict | None, organization_id: int, upcoming: list[dict]) -> list[dict]:
    """Facilities with a limit. The end date is ``validTo``, else a dated
    ``facility_expiry`` event whose reference amount is the same limit."""
    raw = (plan or {}).get("liquidityEvidence") if isinstance(plan, dict) else None
    items = (raw or {}).get("facilities") if isinstance(raw, dict) else None
    expiries = [
        (event, _num(event.get("reference_amount")))
        for event in upcoming
        if event.get("kind") == "facility_expiry" and _date(event.get("date"))
    ]
    out = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict) or item.get("organizationId") not in (None, organization_id):
            continue
        limit = _num(item.get("limit"))
        if limit is None:
            continue
        end = _date(item.get("validTo"))
        if end is None:
            end = min(
                (_date(event["date"]) for event, amount in expiries if amount is not None and abs(amount - limit) < 0.01),
                default=None,
            )
        kind = str(item.get("kind") or "")
        out.append({
            "name": item.get("name") or item.get("label"), "limit": limit,
            "start": _date(item.get("validFrom")), "end": end,
            # Cheque discounting is a separate facility, not the checking overdraft.
            "headroom": kind not in forecast_rules.SHORT_LOAN_KINDS,
        })
    return out


def _limit(facilities: list[dict], fallback: float | None, week_start: date, week_end: date) -> float | None:
    """The facility that covers the week. An ended facility falls back to the account
    limit. A missing limit stays None: headroom is not computed against zero."""
    active = [
        facility for facility in facilities
        if facility.get("headroom", True)
        and (facility["start"] is None or facility["start"] <= week_end)
        and (facility["end"] is None or facility["end"] >= week_start)
    ]
    if active:
        return _r(sum(facility["limit"] for facility in active))
    return fallback


def _dated_items(view: dict, plan: dict | None, organization_id: int, first: date, last: date) -> list[dict]:
    liquidity = view.get("liquidity") or {}
    items = []
    discounted = forecast_rules.discounted_cheque_keys(plan, organization_id)
    for check in liquidity.get("checks") or []:
        when, amount = _date(check.get("date")), _num(check.get("amount"))
        if (str(check.get("check") or ""), when) in discounted:
            continue
        if check.get("state") in CHECK_STATES and when and amount and first <= when <= last:
            label = " · ".join(part for part in (f"צ׳ק {check.get('check')}", check.get("payee")) if part)
            items.append({"date": when, "label": label, "amount": _r(-abs(amount)), "certainty": CERTAIN,
                          "source": "plan.liquidityEvidence.checks", "consumes": "operating_out"})
    for event in liquidity.get("upcoming") or []:
        when, amount = _date(event.get("date")), _num(event.get("amount"))
        if event.get("kind") in ("check", "facility_expiry") or not when or amount is None:
            continue
        if first <= when <= last:
            items.append({"date": when, "label": event.get("label"), "amount": _r(amount), "certainty": CERTAIN,
                          "source": "liquidity.upcoming",
                          "upper_bound": event.get("amount_basis") == "outstanding_balance",
                          "note": event.get("note")})
    for item in (plan or {}).get("cashForecastItems") or [] if isinstance(plan, dict) else []:
        if not isinstance(item, dict) or item.get("organizationId") not in (None, organization_id):
            continue
        when, amount = _date(item.get("date")), _num(item.get("amount"))
        if when and amount and first <= when <= last:
            items.append({"date": when, "label": item.get("label"), "amount": _r(amount), "certainty": MANUAL,
                          "source": "plan.cashForecastItems"})
    return items


def overdue(view: dict, plan: dict | None, organization_id: int, today: date,
            opening_as_of: date | None, first: date) -> list[dict]:
    """Dated obligations already past with no bank row after them to show the payment:
    a loan maturity or an uncovered check later than the last known balance. Listed,
    not added to a week: whether it was paid is unknown. An uncovered check from
    ``first`` on is already a week item."""
    after = opening_as_of or date.min
    raw = (plan or {}).get("liquidityEvidence") if isinstance(plan, dict) else None
    out = []
    for loan in (raw or {}).get("loans") or [] if isinstance(raw, dict) else []:
        if not isinstance(loan, dict) or loan.get("organizationId") not in (None, organization_id):
            continue
        when, balance = _date(loan.get("maturity")), _num(loan.get("balance"))
        if when and balance and after < when < today:
            out.append({"date": when.isoformat(), "label": loan.get("label"), "amount": _r(-abs(balance)),
                        "kind": "loan_maturity", "note": "מועד הפירעון עבר; אין תנועת בנק אחריו שמראה תשלום"})
    for check in (view.get("liquidity") or {}).get("checks") or []:
        when, amount = _date(check.get("date")), _num(check.get("amount"))
        if check.get("state") == "no_coverage" and when and amount and after < when < min(today, first):
            label = " · ".join(part for part in (f"צ׳ק {check.get('check')}", check.get("payee")) if part)
            out.append({"date": when.isoformat(), "label": label, "amount": _r(-abs(amount)),
                        "kind": "check", "note": "מועד הצ׳ק עבר ונתוני הבנק לא מכסים אותו"})
    return sorted(out, key=lambda item: item["date"])


def run_rate(view: dict, today: date) -> dict[str, float]:
    """Mean monthly total per group over the last full months before ``today``.

    A mean, not a median: the combined view is the sum of the entities, and only a
    mean adds up (a median per entity takes each entity's middle month from a
    different month). One-off lines stay out instead (``ONE_OFF_LINES``)."""
    statement = view.get("cash_statement") or {}
    current = _month(today)
    months = [m for m in statement.get("months") or [] if isinstance(m, str) and m < current][-RUN_RATE_MONTHS:]
    out = {}
    for group in RUN_RATE_GROUPS:
        totals = []
        for month in months:
            values = [
                _num((line.get("values") or {}).get(month))
                for line in statement.get("lines") or []
                if line.get("group") == group and line.get("id") not in ONE_OFF_LINES
            ]
            known = [v for v in values if v is not None]
            if known:
                totals.append(sum(known))
        if totals:
            out[group] = _r(sum(totals) / len(totals))
    return out


def _principal(view: dict, today: date) -> float | None:
    current = _month(today)
    rows = [
        _num(row.get("principal")) for row in (view.get("liquidity") or {}).get("debt_service") or []
        if isinstance(row, dict) and str(row.get("month") or "") < current
    ][-RUN_RATE_MONTHS:]
    known = [abs(v) for v in rows if v is not None]
    return _r(median(known)) if known else None


def _daily_streams(rates: dict[str, float], principal: float | None, items: list[dict],
                   first: date, last: date) -> dict[date, dict[str, float]]:
    """Run-rate per day. A known check is paid out of its month's operating run-rate."""
    in_window: dict[str, list[date]] = {}
    for day in _days(first, last):
        in_window.setdefault(_month(day), []).append(day)
    known_out = {}
    known_principal = {}
    for item in items:
        when = item.get("date")
        if not isinstance(when, date):
            continue
        if item.get("consumes") == "operating_out":
            key = _month(when)
            known_out[key] = known_out.get(key, 0.0) + item["amount"]
        elif item.get("consumes") == "principal":
            key = _month(when)
            known_principal[key] = known_principal.get(key, 0.0) + abs(item["amount"])
    streams: dict[date, dict[str, float]] = {}
    for month, days in in_window.items():
        year, mon = int(month[:4]), int(month[5:])
        share = len(days) / monthrange(year, mon)[1]
        budget = {group: value * share for group, value in rates.items()}
        if "operating_out" in budget:
            budget["operating_out"] = min(0.0, budget["operating_out"] - known_out.get(month, 0.0))
        if principal:
            budget["principal"] = -max(0.0, principal * share - known_principal.get(month, 0.0))
        spread = {key: _spread(value, len(days)) for key, value in budget.items()}
        for index, day in enumerate(days):
            streams[day] = {key: parts[index] for key, parts in spread.items()}
    return streams


def _spread(total: float, count: int) -> list[float]:
    """``total`` over ``count`` days in whole agorot; the remainder goes to the first days,
    so the days of a month add up to its budget exactly."""
    cents = round(total * 100)
    sign = -1 if cents < 0 else 1
    base, remainder = divmod(abs(cents), count)
    return [sign * (base + (1 if i < remainder else 0)) / 100 for i in range(count)]


STREAM_LABELS = dict(
    RUN_RATE_GROUPS,
    principal="החזרי קרן — הלוואות (חציון 3 חודשים)",
    income="הכנסה לפי התקציב",
)
STREAM_SOURCE = {"income": "plan.budgetLines"}
STREAM_CERTAINTY = {"principal": SCHEDULED, "income": SCHEDULED}


def _week(start: date, end: date, items: list[dict], streams: dict[date, dict[str, float]]) -> dict:
    week_items = [dict(item) for item in items if start <= item["date"] <= end]
    sums: dict[str, float] = {}
    for day, values in streams.items():
        if start <= day <= end:
            for key, value in values.items():
                sums[key] = sums.get(key, 0.0) + value
    for key, value in sums.items():
        if round(value, 2):
            week_items.append({
                "date": None, "label": STREAM_LABELS[key], "amount": _r(value),
                "certainty": STREAM_CERTAINTY.get(key, ESTIMATE),
                "source": STREAM_SOURCE.get(key, "cash_statement"), "stream": key,
            })
    for item in week_items:
        item.pop("consumes", None)
        if isinstance(item.get("date"), date):
            item["date"] = item["date"].isoformat()
    week_items.sort(key=lambda item: (item["date"] is None, item["date"] or "", item["amount"]))
    inflow = _r(sum(i["amount"] for i in week_items if i["amount"] > 0))
    outflow = _r(sum(i["amount"] for i in week_items if i["amount"] < 0))
    return {"start": start.isoformat(), "end": end.isoformat(), "in": inflow, "out": outflow,
            "net": _r(inflow + outflow), "items": week_items}


def _walk(weeks: list[dict], opening: float | None) -> None:
    closing = opening
    for week in weeks:
        closing = None if closing is None or week.get("net") is None else _r(closing + week["net"])
        week["closing"] = closing
        week["headroom"] = None if closing is None or week["limit"] is None else _r(week["limit"] + closing)


def first_breach(weeks: list[dict], opening: float | None = None) -> dict | None:
    for index, week in enumerate(weeks):
        if week["headroom"] is None or week["headroom"] >= 0:
            continue
        outflows = sorted((i for i in week["items"] if i["amount"] < 0), key=lambda i: i["amount"])
        reasons = []
        if index == 0 and opening is not None and week["limit"] is not None and opening + week["limit"] < 0:
            reasons.append(f"כבר בפתיחה: יתרה {opening:,.0f} ₪ מול מסגרת {week['limit']:,.0f} ₪")
        reasons += [f"{item['label']}: {item['amount']:,.0f} ₪" for item in outflows[:TOP_REASONS]]
        return {"week_start": week["start"], "week_end": week["end"], "headroom": week["headroom"],
                "reasons": reasons}
    return None


def _apply_unknown(week: dict, unknown: list[tuple[date, str]], start: date, end: date, first: date) -> None:
    keys = [key for day, key in unknown if start <= day <= end and day >= first]
    if not keys:
        week["unknown"] = []
        return
    week["unknown"] = [forecast_rules.UNKNOWN_HE[key] for key in dict.fromkeys(keys)]
    week["in"] = week["out"] = week["net"] = None


def build_entity_forecast(view: dict, *, plan: dict | None, organization_id: int, label: str | None,
                          today: date, weeks: int = WEEKS, apply_budget_rules: bool = True) -> dict:
    liquidity = view.get("liquidity") or {}
    position = liquidity.get("position") or {}
    opening = _num(position.get("balance"))
    as_of = _date(position.get("as_of")) if opening is not None else None
    windows = week_windows(today, weeks)
    first = as_of + timedelta(days=1) if as_of else windows[0][0]
    last = windows[-1][1]
    items = _dated_items(view, plan, organization_id, first, last)
    rates = run_rate(view, today)
    use_rules = apply_budget_rules and forecast_rules.rules_active(plan)
    unknown: list[tuple[date, str]] = []
    if use_rules:
        rates = {key: value for key, value in rates.items() if key not in ("operating_in", "operating_out")}
        lines = forecast_rules.load_lines(plan)
        ruled, ruled_unknown = forecast_rules.supplier_and_payroll(plan, lines, first, last)
        loans, loan_unknown = forecast_rules.loan_items(plan, organization_id, first, last)
        cheques, cheque_unknown = forecast_rules.discounted_cheque_items(plan, organization_id, first, last)
        items = items + ruled + loans + cheques
        unknown = ruled_unknown + loan_unknown + cheque_unknown
        income_days, income_unknown = forecast_rules.income_for_window(lines, first, last)
        unknown += [(day, "income") for day in income_unknown]
    else:
        income_days = {}
    streams = _daily_streams(rates, _principal(view, today), items, first, last)
    for day, amount in income_days.items():
        streams.setdefault(day, {})["income"] = amount
    facilities = _facilities(plan, organization_id, liquidity.get("upcoming") or [])
    out_weeks = []
    for index, (start, end) in enumerate(windows):
        week = _week(first if index == 0 and first < start else start, end, items, streams)
        week["start"] = start.isoformat()
        # A limit copied from evidence is already in ``facilities`` and ends with
        # them. Using it again as the fallback would keep an expired facility alive.
        fallback = None if position.get("limit_source") == "plan.liquidityEvidence" else _num(position.get("limit"))
        week["limit"] = _limit(facilities, fallback, start, end)
        _apply_unknown(week, unknown, start, end, first)
        out_weeks.append(week)
    _walk(out_weeks, opening)
    missing = []
    if opening is None:
        missing.append("opening_balance")
    if out_weeks[0]["limit"] is None:
        missing.append("facility_limit")
    if not rates and not use_rules:
        missing.append("run_rate")
    if any(week.get("unknown") for week in out_weeks):
        missing.append("forecast_rules")
    return {
        "label": label,
        "status": "ready" if opening is not None else ("partial" if rates or items else "unknown"),
        "opening": {
            "amount": opening, "as_of": as_of.isoformat() if as_of else None,
            "source": position.get("balance_source"), "rule": forecast_rules.RULES["opening"],
        },
        "run_rate": rates,
        "rules": {**forecast_rules.RULES, "active": use_rules},
        "weeks": out_weeks,
        "first_breach": first_breach(out_weeks, opening),
        "overdue": overdue(view, plan, organization_id, today, as_of, first),
        "missing": missing,
        "provider_calls": 0,
    }


def combine(entities: list[dict]) -> dict:
    """Sum of the entities, week by week. A total any entity does not know stays unknown."""
    if not entities:
        return {"weeks": [], "first_breach": None, "missing": [], "provider_calls": 0}
    weeks = []
    for index, base in enumerate(entities[0]["weeks"]):
        parts = [entity["weeks"][index] for entity in entities]

        def total(key):
            values = [part[key] for part in parts]
            return None if any(v is None for v in values) else _r(sum(values))

        weeks.append({
            "start": base["start"], "end": base["end"],
            "in": total("in"), "out": total("out"), "net": total("net"),
            "closing": total("closing"), "limit": total("limit"), "headroom": total("headroom"),
            "items": [dict(item, entity=entity["label"]) for entity, part in zip(entities, parts) for item in part["items"]],
        })
    openings = [entity["opening"]["amount"] for entity in entities]
    opening = None if any(v is None for v in openings) else _r(sum(openings))
    as_ofs = [entity["opening"].get("as_of") for entity in entities if entity["opening"].get("as_of")]
    missing = sorted({key for entity in entities for key in entity["missing"]})
    return {"weeks": weeks, "opening": opening, "opening_as_of": max(as_ofs) if as_ofs else None,
            "first_breach": first_breach(weeks, opening), "missing": missing, "provider_calls": 0}


def overlay_budget_rules(combined: dict, plan: dict | None) -> dict:
    """Put the group's budget rules on the combined forecast once.

    Each entity keeps its own run-rate. Operating run-rate items are removed here
    and replaced by the budget rules, so the group budget is not added on top of
    the sum and is not counted once per entity.
    """
    if not isinstance(combined, dict) or not forecast_rules.rules_active(plan):
        return combined
    weeks = combined.get("weeks") or []
    if not weeks:
        return combined
    as_of = _date(combined.get("opening_as_of"))
    first = as_of + timedelta(days=1) if as_of else _date(weeks[0]["start"])
    last = _date(weeks[-1]["end"])
    if first is None or last is None or first > last:
        return combined
    lines = forecast_rules.load_lines(plan)
    extra, unknown = forecast_rules.supplier_and_payroll(plan, lines, first, last)
    income_days, income_unknown = forecast_rules.income_for_window(lines, first, last)
    unknown = unknown + [(day, "income") for day in income_unknown]
    new_weeks = []
    for week in weeks:
        start, end = _date(week["start"]), _date(week["end"])
        kept = [item for item in week.get("items") or [] if item.get("stream") not in ("operating_in", "operating_out")]
        added = []
        for item in extra:
            when = item["date"] if isinstance(item["date"], date) else _date(item["date"])
            if when and start and end and start <= when <= end and when >= first:
                added.append({**item, "date": when.isoformat()})
        income = _r(sum(amount for day, amount in income_days.items() if start and end and start <= day <= end))
        if income:
            added.append({
                "date": None, "label": STREAM_LABELS["income"], "amount": income,
                "certainty": SCHEDULED, "source": "plan.budgetLines",
                "rule": forecast_rules.RULES["income"], "stream": "income",
            })
        keys = [key for day, key in unknown if start and end and start <= day <= end and day >= first]
        items = kept + added
        nxt = dict(week, items=items)
        if keys or week.get("net") is None:
            nxt["in"] = nxt["out"] = nxt["net"] = None
            nxt["unknown"] = [forecast_rules.UNKNOWN_HE[key] for key in dict.fromkeys(keys)]
        else:
            inflow = _r(sum(item["amount"] for item in items if item.get("amount") and item["amount"] > 0))
            outflow = _r(sum(item["amount"] for item in items if item.get("amount") and item["amount"] < 0))
            nxt["in"], nxt["out"], nxt["net"] = inflow, outflow, _r(inflow + outflow)
            nxt["unknown"] = []
        new_weeks.append(nxt)
    opening = combined.get("opening")
    opening_amount = opening.get("amount") if isinstance(opening, dict) else opening
    _walk(new_weeks, opening_amount)
    missing = list(combined.get("missing") or [])
    if any(week.get("unknown") for week in new_weeks) and "forecast_rules" not in missing:
        missing.append("forecast_rules")
    return {
        **combined, "weeks": new_weeks, "missing": missing,
        "first_breach": first_breach(new_weeks, opening_amount),
        "rules": {**forecast_rules.RULES, "active": True}, "provider_calls": 0,
    }
