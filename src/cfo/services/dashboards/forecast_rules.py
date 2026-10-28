"""Cash rules for the 13-week forecast and the monthly cash lines.

The forecast starts at the known cash position. Supplier payments are שוטף 30
(the last day of the month after the supply month). Payroll is the plan's
payroll definition, else the budget's payroll categories. Expected income is
the budget's revenue lines. A bridge loan or cheque-discounting balance is a
short loan: it is repaid on its maturity date and a receipt of the same amount
is recorded that day. A term loan's stated instalment is that instalment only.

A missing input stays None and is named. Nothing here writes 0 in its place.
No database and no provider calls.
"""
from __future__ import annotations

from calendar import monthrange
from datetime import date, timedelta

from .budget import REVENUE_KEYS
from .plan_budget import PlanBudgetError, validate_budget_lines

PAYROLL_DAY = 1
SUPPLIER_CATEGORIES = frozenset({"cost_of_goods", "materials"})
PAYROLL_CATEGORIES = frozenset({"salaries", "direct_labor"})
SHORT_LOAN_KINDS = frozenset({"bridge", "cheque_discounting", "check_discounting"})
SCHEDULED = "scheduled"
CERTAIN = "certain"

UNKNOWN_HE = {
    "income": "ההכנסה הצפויה לא ידועה: אין הכנסה מוגדרת בתקציב לחודש הזה. לא הוזן 0.",
    "payroll": "השכר לא ידוע: אין הגדרת שכר בתקציב. לא הוזן 0.",
    "suppliers": "תשלום הספקים לא ידוע: אין תקציב ספקים לחודש האספקה. לא הוזן 0.",
    "short_loan": "הלוואה קצרה בלי יתרה ידועה. לא הוזן 0.",
    "loan_payment": "החזר הלוואה בלי סכום. לא הוזן 0.",
}

RULES = {
    "opening": "today_position",
    "suppliers": "shotef_30",
    "payroll": "budget_payroll_definition",
    "income": "budget_income",
    "short_loans": "close_on_maturity_against_receipt",
}


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


def _month_key(day: date) -> str:
    return f"{day.year}-{day.month:02d}"


def _add_month(year: int, month: int, step: int = 1) -> tuple[int, int]:
    month += step
    while month > 12:
        month -= 12
        year += 1
    while month < 1:
        month += 12
        year -= 1
    return year, month


def shotef_30(year: int, month: int) -> date:
    """שוטף 30: the last day of the month after the supply month."""
    year, month = _add_month(year, month, 1)
    return date(year, month, monthrange(year, month)[1])


def previous_month(year: int, month: int) -> tuple[int, int]:
    return _add_month(year, month, -1)


def rules_active(plan: dict | None) -> bool:
    """The explicit rules apply when the plan carries a budget or a payroll definition."""
    if not isinstance(plan, dict):
        return False
    if "budgetLines" in plan:
        return True
    payroll = plan.get("payroll")
    return isinstance(payroll, list) and len(payroll) > 0


def load_lines(plan: dict | None) -> list[dict] | None:
    """Validated budget lines, or None when the plan has none or they are invalid."""
    if not isinstance(plan, dict) or "budgetLines" not in plan:
        return None
    try:
        return validate_budget_lines(plan) or []
    except PlanBudgetError:
        return None


def _category_sum(lines: list[dict] | None, month: str, categories: frozenset[str]) -> float | None:
    if lines is None:
        return None
    found = False
    total = 0.0
    for line in lines:
        if line.get("category") not in categories:
            continue
        cell = (line.get("months") or {}).get(month)
        if not isinstance(cell, dict) or cell.get("amount") is None:
            continue
        found = True
        total += float(cell["amount"])
    return round(total, 2) if found else None


def income_amount(lines: list[dict] | None, month: str) -> float | None:
    return _category_sum(lines, month, REVENUE_KEYS)


def supplier_amount(lines: list[dict] | None, supply_month: str) -> float | None:
    return _category_sum(lines, supply_month, SUPPLIER_CATEGORIES)


def payroll_amount(plan: dict | None, lines: list[dict] | None, month: str) -> tuple[float | None, str | None]:
    """The month's payroll and its source. The payroll definition wins over salary lines."""
    payroll = plan.get("payroll") if isinstance(plan, dict) else None
    if isinstance(payroll, list) and payroll:
        amounts = []
        for row in payroll:
            if not isinstance(row, dict):
                return None, None
            amount = _num(row.get("monthly"))
            if amount is None:
                return None, None
            amounts.append(amount)
        return round(sum(amounts), 2), "plan.payroll"
    amount = _category_sum(lines, month, PAYROLL_CATEGORIES)
    return (amount, "plan.budgetLines") if amount is not None else (None, None)


def _spread(total: float, count: int) -> list[float]:
    cents = round(total * 100)
    sign = -1 if cents < 0 else 1
    base, remainder = divmod(abs(cents), count)
    return [sign * (base + (1 if i < remainder else 0)) / 100 for i in range(count)]


def _days(first: date, last: date):
    day = first
    while day <= last:
        yield day
        day += timedelta(days=1)


def income_for_window(lines: list[dict] | None, first: date, last: date) -> tuple[dict[date, float], list[date]]:
    """Budget income on each day of the window, and the days whose month has no income line."""
    by_month: dict[str, list[date]] = {}
    for day in _days(first, last):
        by_month.setdefault(_month_key(day), []).append(day)
    amounts: dict[date, float] = {}
    unknown: list[date] = []
    for month, days in by_month.items():
        amount = income_amount(lines, month)
        if amount is None:
            unknown.extend(days)
            continue
        year, mon = int(month[:4]), int(month[5:])
        parts = _spread(amount * len(days) / monthrange(year, mon)[1], len(days))
        for day, part in zip(days, parts):
            amounts[day] = part
    return amounts, unknown


def _same_org(item: dict, organization_id: int | None) -> bool:
    org = item.get("organizationId")
    return organization_id is None or org in (None, organization_id)


def _evidence_loans(plan: dict | None, organization_id: int | None) -> list[dict]:
    raw = (plan or {}).get("liquidityEvidence") if isinstance(plan, dict) else None
    loans = (raw or {}).get("loans") if isinstance(raw, dict) else None
    if not isinstance(loans, list):
        return []
    return [loan for loan in loans if isinstance(loan, dict) and _same_org(loan, organization_id)]


def loan_items(plan: dict | None, organization_id: int | None, first: date, last: date) -> tuple[list[dict], list[tuple[date, str]]]:
    """Short-loan close (repayment and the receipt against it) and a stated instalment."""
    items: list[dict] = []
    unknown: list[tuple[date, str]] = []
    for loan in _evidence_loans(plan, organization_id):
        label = loan.get("label") or "הלוואה"
        kind = str(loan.get("kind") or "")
        maturity = _date(loan.get("maturity"))
        balance = _num(loan.get("balance"))
        if kind in SHORT_LOAN_KINDS and maturity and first <= maturity <= last:
            if balance is None:
                unknown.append((maturity, "short_loan"))
            else:
                amount = round(abs(balance), 2)
                source = "plan.liquidityEvidence"
                items.append({
                    "date": maturity, "label": f"{label} · פירעון הלוואה קצרה",
                    "amount": -amount, "certainty": CERTAIN, "source": source,
                    "rule": RULES["short_loans"],
                })
                items.append({
                    "date": maturity, "label": f"{label} · תקבול שסוגר את ההלוואה הקצרה",
                    "amount": amount, "certainty": CERTAIN, "source": source,
                    "rule": RULES["short_loans"],
                })
        payment_day = _date(loan.get("paymentDate"))
        payment = _num(loan.get("paymentAmount"))
        if payment_day and first <= payment_day <= last:
            if payment is None:
                unknown.append((payment_day, "loan_payment"))
            elif payment != 0:
                items.append({
                    "date": payment_day, "label": f"{label} · החזר לפי ראיית הבעלים",
                    "amount": -round(abs(payment), 2), "certainty": SCHEDULED,
                    "source": "plan.liquidityEvidence", "rule": "owner_loan_payment",
                    "consumes": "principal",
                })
    return items, unknown


def supplier_and_payroll(plan: dict | None, lines: list[dict] | None, first: date, last: date) -> tuple[list[dict], list[tuple[date, str]]]:
    items: list[dict] = []
    unknown: list[tuple[date, str]] = []
    seen_payroll: set[str] = set()
    seen_supplier: set[str] = set()
    for day in _days(first, last):
        if day.day == PAYROLL_DAY and _month_key(day) not in seen_payroll:
            seen_payroll.add(_month_key(day))
            amount, source = payroll_amount(plan, lines, _month_key(day))
            if amount is None:
                unknown.append((day, "payroll"))
            else:
                items.append({
                    "date": day, "label": "שכר לפי הגדרת התקציב",
                    "amount": -round(abs(amount), 2), "certainty": SCHEDULED,
                    "source": source, "rule": RULES["payroll"],
                })
        if day == date(day.year, day.month, monthrange(day.year, day.month)[1]) and _month_key(day) not in seen_supplier:
            seen_supplier.add(_month_key(day))
            supply_year, supply_month = previous_month(day.year, day.month)
            supply = f"{supply_year}-{supply_month:02d}"
            amount = supplier_amount(lines, supply)
            if amount is None:
                unknown.append((day, "suppliers"))
            else:
                items.append({
                    "date": day, "label": f"ספקים שוטף 30 (אספקה {supply})",
                    "amount": -round(abs(amount), 2), "certainty": SCHEDULED,
                    "source": "plan.budgetLines", "rule": RULES["suppliers"],
                })
    return items, unknown


def _cell(amount: float | None, *, source: str | None, rule: str, label: str, **extra) -> dict:
    cell = {"amount": None if amount is None else round(amount, 2), "source": source, "rule": rule}
    if amount is None:
        cell["label"] = label
    cell.update(extra)
    return cell


def monthly_table(plan: dict | None, months: list[str]) -> dict | None:
    """Per cash-month income, payroll and supplier payment. None when the rules do not apply."""
    if not rules_active(plan):
        return None
    lines = load_lines(plan)
    out = {}
    for month in months:
        year, mon = int(month[:4]), int(month[5:])
        income = income_amount(lines, month)
        payroll, payroll_source = payroll_amount(plan, lines, month)
        supply_year, supply_month = previous_month(year, mon)
        supply = f"{supply_year}-{supply_month:02d}"
        suppliers = supplier_amount(lines, supply)
        due = shotef_30(supply_year, supply_month)
        out[month] = {
            "income": _cell(income, source="plan.budgetLines" if income is not None else None,
                            rule=RULES["income"], label=UNKNOWN_HE["income"]),
            "payroll": _cell(
                None if payroll is None else -abs(payroll),
                source=payroll_source, rule=RULES["payroll"], label=UNKNOWN_HE["payroll"],
                pay_date=f"{year}-{mon:02d}-{PAYROLL_DAY:02d}",
            ),
            "suppliers": _cell(
                None if suppliers is None else -abs(suppliers),
                source="plan.budgetLines" if suppliers is not None else None,
                rule=RULES["suppliers"], label=UNKNOWN_HE["suppliers"],
                supply_month=supply, due=due.isoformat(),
            ),
        }
    return {"months": out, "rules": RULES, "provider_calls": 0}
