"""Budget, booked bank, and filed books for one grain and date range.

No provider call. A month budget is not divided into a day or a week unless
that line's driver says so, and it is not multiplied by the number of months
in a quarter or a year. A month that has not started stays out of the
comparison. A missing figure stays null.
"""
from __future__ import annotations

from calendar import monthrange
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from ..bank_status import counts_in_cash_flow
from ..vat_utils import bill_counts, expense_counts, invoice_counts
from .books_pnl import _net
from .budget_fill import counts_in_total

_MONEY = Decimal("0.01")
GRAINS = ("day", "week", "month", "quarter", "year")
_DAY_TOKENS = ("per_day", "daily", "ליום", "/30", "÷30", "grain:day")
_WEEK_TOKENS = ("per_week", "weekly", "לשבוע", "grain:week")


def explicit_allocation(formula: str | None) -> str | None:
    """``day`` or ``week`` when the driver itself names that split."""
    text = (formula or "").casefold()
    if any(token.casefold() in text for token in _DAY_TOKENS):
        return "day"
    if any(token.casefold() in text for token in _WEEK_TOKENS):
        return "week"
    return None


def iter_buckets(grain: str, start: date, end: date):
    if grain == "day":
        day = start
        while day <= end:
            yield day.isoformat(), day, day
            day += timedelta(days=1)
        return
    if grain == "week":
        day = start
        while day <= end:
            hi = min(day + timedelta(days=6), end)
            yield f"{day.isoformat()}–{hi.isoformat()}", day, hi
            day = hi + timedelta(days=1)
        return
    if grain == "quarter":
        quarter_month = ((start.month - 1) // 3) * 3 + 1
        cursor = date(start.year, quarter_month, 1)
        while cursor <= end:
            last_month = cursor.month + 2
            last = date(cursor.year, last_month, monthrange(cursor.year, last_month)[1])
            lo = max(cursor, start)
            hi = min(last, end)
            yield f"{cursor.year}-Q{(cursor.month - 1) // 3 + 1}", lo, hi
            cursor = date(cursor.year + 1, 1, 1) if cursor.month >= 10 else date(cursor.year, cursor.month + 3, 1)
        return
    if grain == "year":
        cursor = date(start.year, 1, 1)
        while cursor <= end:
            last = date(cursor.year, 12, 31)
            lo = max(cursor, start)
            hi = min(last, end)
            yield str(cursor.year), lo, hi
            cursor = date(cursor.year + 1, 1, 1)
        return
    cursor = date(start.year, start.month, 1)
    while cursor <= end:
        last = date(cursor.year, cursor.month, monthrange(cursor.year, cursor.month)[1])
        lo = max(cursor, start)
        hi = min(last, end)
        yield f"{cursor.year:04d}-{cursor.month:02d}", lo, hi
        cursor = date(cursor.year + 1, 1, 1) if cursor.month == 12 else date(cursor.year, cursor.month + 1, 1)


def compare_period(db, organization_id: int, plan: dict | None, *, grain: str, start: date, end: date,
                   as_of: date | None = None) -> dict:
    if grain not in GRAINS:
        raise ValueError("grain")
    if end < start:
        raise ValueError("range")
    plan = plan if isinstance(plan, dict) else {}
    as_of = as_of or date.today()
    bank_rows = _booked_rows(db, organization_id, start, end)
    bank_known = _org_has_bank(db, organization_id)
    books_rows = _books_rows(db, organization_id, start, end)
    periods = []
    for label, lo, hi in iter_buckets(grain, start, end):
        budget = _budget_span(plan, lo, hi, as_of=as_of) if grain in {"quarter", "year"} else _budget_bucket(plan, grain, lo, hi, as_of=as_of)
        bank = _bank_bucket(bank_rows, lo, hi, bank_known, include_lines=grain == "day", as_of=as_of)
        books = _books_bucket(books_rows, lo, hi, as_of=as_of)
        periods.append({
            "label": label,
            "start": lo.isoformat(),
            "end": hi.isoformat(),
            "elapsed": lo <= as_of,
            "budget": budget,
            "bank": bank,
            "books": books,
            "variance": _variance(budget, books, bank),
        })
    return {
        "grain": grain,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "as_of": as_of.isoformat(),
        "provider_calls": 0,
        "periods": periods,
        "totals": _totals(periods),
        "profit": [
            {"label": period["label"], "books": period["books"]["net"], "bank": period["bank"]["net"], "budget": period["budget"]["net"]}
            for period in periods
        ],
        "note_he": (
            "תקציב מתוך שורות התקציב השמורות, רק לחודשים שמולאו ושכבר התחילו. "
            "חודש אחד לא מוכפל במספר החודשים ברבעון. בנק הוא תנועות BOOKED בלבד. "
            "ספרים הם מסמכים שכבר תויקו ברצף, בלי משיכת SUMIT. חסר אינו 0."
        ),
    }


def _q(value: Decimal) -> float:
    return float(value.quantize(_MONEY, rounding=ROUND_HALF_UP))


def _figure(amount: Decimal | None, *, source: str, as_of: str | None, missing_label: str | None) -> dict:
    return {
        "amount": None if amount is None else _q(amount),
        "source": source,
        "as_of": as_of,
        "missing_label": missing_label if amount is None else None,
    }


def _months_touched(lo: date, hi: date) -> list[str]:
    keys = []
    cursor = date(lo.year, lo.month, 1)
    last = date(hi.year, hi.month, 1)
    while cursor <= last:
        keys.append(f"{cursor.year:04d}-{cursor.month:02d}")
        cursor = date(cursor.year + 1, 1, 1) if cursor.month == 12 else date(cursor.year, cursor.month + 1, 1)
    return keys


def _line_amount(line: dict, cell) -> Decimal | None:
    if not isinstance(cell, dict):
        return None
    stored = dict(cell)
    if stored.get("amount") is None and stored.get("quantity") is not None and stored.get("rate") is not None:
        try:
            stored["amount"] = Decimal(str(stored["quantity"])) * Decimal(str(stored["rate"]))
        except (ArithmeticError, ValueError, TypeError):
            return None
    return counts_in_total(line, stored)


def _month_lines(plan: dict, month: str) -> list[dict]:
    found = []
    for line in plan.get("budgetLines") or []:
        if not isinstance(line, dict):
            continue
        kind = line.get("kind")
        if kind not in {"revenue", "income", "cost", "expense"}:
            continue
        amount = _line_amount(line, (line.get("months") or {}).get(month))
        side = "revenue" if kind in {"revenue", "income"} else "cost"
        found.append({
            "side": side,
            "amount": amount,
            "allocation": explicit_allocation(line.get("driver_formula")),
            "source": line.get("source"),
        })
    return found


def _side_sum(lines: list[dict], side: str) -> Decimal | None:
    amounts = [line["amount"] for line in lines if line["side"] == side and line["amount"] is not None]
    if not amounts:
        return None
    return sum(amounts, Decimal("0"))


def _context(plan: dict, months: list[str]) -> list[dict]:
    rows = []
    for month in months:
        lines = _month_lines(plan, month)
        revenue = _side_sum(lines, "revenue")
        costs = _side_sum(lines, "cost")
        rows.append({
            "month": month,
            "revenue": None if revenue is None else _q(revenue),
            "costs": None if costs is None else _q(costs),
            "net": None if revenue is None or costs is None else _q(revenue - costs),
            "source": "plan.budgetLines",
        })
    return rows


def _covers_full_month(lo: date, hi: date) -> bool:
    last = monthrange(lo.year, lo.month)[1]
    return lo.day == 1 and hi == date(lo.year, lo.month, last) and lo.year == hi.year and lo.month == hi.month


def _overlap_days(month: str, lo: date, hi: date) -> int:
    year, month_no = int(month[:4]), int(month[5:])
    month_lo = date(year, month_no, 1)
    month_hi = date(year, month_no, monthrange(year, month_no)[1])
    start = max(lo, month_lo)
    finish = min(hi, month_hi)
    if finish < start:
        return 0
    return (finish - start).days + 1


def _budget_bucket(plan: dict, grain: str, lo: date, hi: date, as_of: date | None = None) -> dict:
    months = _months_touched(lo, hi)
    context = _context(plan, months)
    source = "plan.budgetLines"
    as_of_source = next((line.get("source") for line in (plan.get("budgetLines") or []) if isinstance(line, dict) and line.get("source")), None)
    as_of_text = as_of.isoformat() if as_of is not None else as_of_source
    if grain == "month" and _covers_full_month(lo, hi):
        lines = _month_lines(plan, months[0])
        revenue = _side_sum(lines, "revenue")
        costs = _side_sum(lines, "cost")
        net = None if revenue is None or costs is None else revenue - costs
        missing = None if net is not None else "אין תקציב מלא לחודש (הכנסה או הוצאה חסרה). לא הוזן 0."
        return {
            "revenue": _figure(revenue, source=source, as_of=as_of_text, missing_label="אין תקציב הכנסות לחודש. לא הוזן 0."),
            "costs": _figure(costs, source=source, as_of=as_of_text, missing_label="אין תקציב הוצאות לחודש. לא הוזן 0."),
            "net": _figure(net, source=source, as_of=as_of_text, missing_label=missing),
            "month_context": context,
        }
    revenue = costs = Decimal("0")
    revenue_known = costs_known = True
    saw_revenue = saw_cost = False
    for month in months:
        lines = _month_lines(plan, month)
        days = _overlap_days(month, lo, hi)
        length = monthrange(int(month[:4]), int(month[5:]))[1]
        for line in lines:
            if line["amount"] is None:
                continue
            mode = line["allocation"]
            applies = (grain == "day" and mode == "day") or (grain == "week" and mode in {"day", "week"})
            if not applies:
                if line["side"] == "revenue":
                    revenue_known = False
                else:
                    costs_known = False
                continue
            share = (line["amount"] * Decimal(days) / Decimal(length)).quantize(_MONEY, rounding=ROUND_HALF_UP)
            if line["side"] == "revenue":
                revenue += share
                saw_revenue = True
            else:
                costs += share
                saw_cost = True
    if not saw_revenue:
        revenue_known = False
    if not saw_cost:
        costs_known = False
    label = (
        "תקציב היום לא ידוע: התקציב חודשי ואין דרייבר שמפצל אותו לימים. תקציב החודש מוצג כהקשר."
        if grain == "day" else
        "תקציב השבוע לא ידוע: התקציב חודשי ואין דרייבר שמפצל אותו. תקציב החודש מוצג כהקשר."
        if grain == "week" else
        "תקציב הטווח החלקי לא ידוע בלי דרייבר שמפצל את החודש. תקציב החודש מוצג כהקשר."
    )
    revenue_amount = revenue if revenue_known else None
    costs_amount = costs if costs_known else None
    net = None if revenue_amount is None or costs_amount is None else revenue_amount - costs_amount
    return {
        "revenue": _figure(revenue_amount, source=source, as_of=as_of_text, missing_label=label),
        "costs": _figure(costs_amount, source=source, as_of=as_of_text, missing_label=label),
        "net": _figure(net, source=source, as_of=as_of_text, missing_label=label),
        "month_context": context,
    }


def _partial_sides(lines: list[dict], days: int, length: int) -> tuple[Decimal | None, Decimal | None]:
    """A clipped month keeps a share only when the driver names a daily split."""
    revenue = costs = Decimal("0")
    revenue_known = costs_known = True
    saw = False
    for line in lines:
        if line["amount"] is None:
            continue
        saw = True
        if line["allocation"] != "day":
            if line["side"] == "revenue":
                revenue_known = False
            else:
                costs_known = False
            continue
        share = (line["amount"] * Decimal(days) / Decimal(length)).quantize(_MONEY, rounding=ROUND_HALF_UP)
        if line["side"] == "revenue":
            revenue += share
        else:
            costs += share
    if not saw or (not revenue_known and not costs_known):
        return None, None
    return (revenue if revenue_known else None), (costs if costs_known else None)


def _budget_span(plan: dict, lo: date, hi: date, *, as_of: date) -> dict:
    """Sum explicit months inside the span. Never multiply one month by the span length.

    A month that starts after ``as_of`` is reported under ``ahead`` and is not
    part of the comparison amount.
    """
    months = _months_touched(lo, hi)
    context = _context(plan, months)
    source = "plan.budgetLines"
    as_of_source = next(
        (line.get("source") for line in (plan.get("budgetLines") or []) if isinstance(line, dict) and line.get("source")),
        None,
    )
    revenue = costs = ahead_revenue = ahead_costs = Decimal("0")
    revenue_known = costs_known = ahead_revenue_known = ahead_costs_known = False
    filled: list[str] = []
    missing: list[str] = []
    ahead_months: list[str] = []
    for month in months:
        year, mon = int(month[:4]), int(month[5:])
        month_lo = date(year, mon, 1)
        month_hi = date(year, mon, monthrange(year, mon)[1])
        overlap_lo = max(lo, month_lo)
        overlap_hi = min(hi, month_hi)
        if overlap_hi < overlap_lo:
            continue
        lines = _month_lines(plan, month)
        future = month_lo > as_of
        full = overlap_lo == month_lo and overlap_hi == month_hi
        if not full:
            if future:
                ahead_months.append(month)
                continue
            days = (overlap_hi - overlap_lo).days + 1
            side_rev, side_cost = _partial_sides(lines, days, monthrange(year, mon)[1])
        else:
            side_rev = _side_sum(lines, "revenue")
            side_cost = _side_sum(lines, "cost")
        if future:
            ahead_months.append(month)
            if side_rev is not None:
                ahead_revenue += side_rev
                ahead_revenue_known = True
            if side_cost is not None:
                ahead_costs += side_cost
                ahead_costs_known = True
            continue
        if side_rev is None and side_cost is None:
            missing.append(month)
            continue
        if side_rev is not None:
            revenue += side_rev
            revenue_known = True
        if side_cost is not None:
            costs += side_cost
            costs_known = True
        if side_rev is not None and side_cost is not None:
            filled.append(month)
        else:
            missing.append(month)
    gap = "אין תקציב לחודשים שכבר התחילו. לא הוזן 0 ולא הוכפל חודש שמולא."
    ahead_gap = "אין תקציב לחודשים שעוד לא התחילו. לא הוזן 0."
    net = None if not revenue_known or not costs_known else revenue - costs
    ahead_net = None if not ahead_revenue_known or not ahead_costs_known else ahead_revenue - ahead_costs
    return {
        "revenue": _figure(revenue if revenue_known else None, source=source, as_of=as_of_source, missing_label=gap),
        "costs": _figure(costs if costs_known else None, source=source, as_of=as_of_source, missing_label=gap),
        "net": _figure(net, source=source, as_of=as_of_source, missing_label=gap),
        "month_context": context,
        "months_filled": filled,
        "months_missing": missing,
        "months_ahead": ahead_months,
        "ahead": {
            "revenue": _figure(ahead_revenue if ahead_revenue_known else None, source=source, as_of=as_of_source, missing_label=ahead_gap),
            "costs": _figure(ahead_costs if ahead_costs_known else None, source=source, as_of=as_of_source, missing_label=ahead_gap),
            "net": _figure(ahead_net, source=source, as_of=as_of_source, missing_label=ahead_gap),
            "months": ahead_months,
        },
    }


def _sum_known(figures: list[dict], *, gap_is_missing: bool) -> dict:
    total = Decimal("0")
    known = False
    missing = False
    source = None
    as_of = None
    for figure in figures:
        if figure.get("amount") is None:
            missing = True
            source = source or figure.get("source")
            as_of = as_of or figure.get("as_of")
            continue
        total += Decimal(str(figure["amount"]))
        known = True
        source = source or figure.get("source")
        as_of = as_of or figure.get("as_of")
    if not known or (missing and gap_is_missing):
        return _figure(None, source=source or "plan.budgetLines", as_of=as_of, missing_label="חסר בחלק מהטווח. לא הוזן 0.")
    return _figure(total, source=source or "plan.budgetLines", as_of=as_of, missing_label=None)


def _totals(periods: list[dict]) -> dict:
    elapsed = [period for period in periods if period.get("elapsed")]
    budget_periods = elapsed or []
    return {
        "budget": {
            "revenue": _sum_known([period["budget"]["revenue"] for period in budget_periods], gap_is_missing=False),
            "costs": _sum_known([period["budget"]["costs"] for period in budget_periods], gap_is_missing=False),
            "net": _sum_known([period["budget"]["net"] for period in budget_periods], gap_is_missing=False),
        },
        "books": {
            "revenue": _sum_known([period["books"]["revenue"] for period in elapsed], gap_is_missing=True),
            "costs": _sum_known([period["books"]["costs"] for period in elapsed], gap_is_missing=True),
            "net": _sum_known([period["books"]["net"] for period in elapsed], gap_is_missing=True),
        },
        "bank": {
            "in": _sum_known([period["bank"]["in"] for period in elapsed], gap_is_missing=True),
            "out": _sum_known([period["bank"]["out"] for period in elapsed], gap_is_missing=True),
            "net": _sum_known([period["bank"]["net"] for period in elapsed], gap_is_missing=True),
        },
    }


def _org_has_bank(db, organization_id: int) -> bool:
    from ...models import BankTransaction
    return db.query(BankTransaction.id).filter(BankTransaction.organization_id == organization_id).first() is not None


def _booked_rows(db, organization_id: int, start: date, end: date) -> list:
    from ...models import BankTransaction
    rows = db.query(BankTransaction).filter(
        BankTransaction.organization_id == organization_id,
        BankTransaction.transaction_date >= start,
        BankTransaction.transaction_date <= end,
    ).all()
    return [row for row in rows if counts_in_cash_flow(row)]


def _bank_bucket(rows: list, lo: date, hi: date, bank_known: bool, *, include_lines: bool, as_of: date | None = None) -> dict:
    chosen = [row for row in rows if row.transaction_date and lo <= row.transaction_date <= hi]
    source = "bank.BOOKED"
    stamp = as_of.isoformat() if as_of is not None else None
    if not bank_known or not chosen:
        empty = _figure(None, source=source, as_of=stamp, missing_label="אין תנועות BOOKED בטווח. לא הוזן 0.")
        return {"in": empty, "out": empty, "net": empty, "count": len(chosen), "lines": []}
    incoming = sum((Decimal(str(row.amount)) for row in chosen if row.amount is not None and Decimal(str(row.amount)) > 0), Decimal("0"))
    outgoing = sum((abs(Decimal(str(row.amount))) for row in chosen if row.amount is not None and Decimal(str(row.amount)) < 0), Decimal("0"))
    movement_as_of = max((row.transaction_date for row in chosen), default=None)
    as_of_text = movement_as_of.isoformat() if movement_as_of else stamp
    lines = []
    if include_lines:
        for row in sorted(chosen, key=lambda item: (item.transaction_date, item.id))[:100]:
            lines.append({
                "date": row.transaction_date.isoformat(),
                "amount": None if row.amount is None else float(row.amount),
                "description": row.description,
                "account_id": row.account_id,
            })
    return {
        "in": _figure(incoming, source=source, as_of=as_of_text, missing_label=None),
        "out": _figure(outgoing, source=source, as_of=as_of_text, missing_label=None),
        "net": _figure(incoming - outgoing, source=source, as_of=as_of_text, missing_label=None),
        "count": len(chosen),
        "lines": lines,
    }


def _books_rows(db, organization_id: int, start: date, end: date) -> list[dict]:
    from ...models import Bill, Expense, Invoice
    found = []
    for row in db.query(Invoice).filter(
        Invoice.organization_id == organization_id,
        Invoice.issue_date >= start,
        Invoice.issue_date <= end,
    ).all():
        if row.issue_date is None or not invoice_counts(row.status):
            continue
        found.append({"date": row.issue_date, "side": "revenue", "net": _net(row, "subtotal", "total", "tax")})
    for row in db.query(Bill).filter(
        Bill.organization_id == organization_id,
        Bill.issue_date >= start,
        Bill.issue_date <= end,
    ).all():
        if row.issue_date is None or not bill_counts(row.status):
            continue
        found.append({"date": row.issue_date, "side": "cost", "net": _net(row, "subtotal", "total", "tax")})
    for row in db.query(Expense).filter(
        Expense.organization_id == organization_id,
        Expense.expense_date >= start,
        Expense.expense_date <= end,
    ).all():
        if row.expense_date is None or not expense_counts(row.status):
            continue
        found.append({"date": row.expense_date, "side": "cost", "net": _net(row, "amount", "total", "vat_amount")})
    return found


def _books_bucket(rows: list[dict], lo: date, hi: date, as_of: date | None = None) -> dict:
    chosen = [row for row in rows if lo <= row["date"] <= hi]
    source = "books.local_documents"
    stamp = as_of.isoformat() if as_of is not None else None
    if not chosen:
        empty = _figure(None, source=source, as_of=stamp, missing_label="אין מסמכי ספרים בטווח. לא הוזן 0.")
        return {"revenue": empty, "costs": empty, "net": empty}
    revenue_rows = [row["net"] for row in chosen if row["side"] == "revenue"]
    cost_rows = [row["net"] for row in chosen if row["side"] == "cost"]
    revenue = sum(revenue_rows, Decimal("0")) if revenue_rows else None
    costs = sum(cost_rows, Decimal("0")) if cost_rows else None
    as_of = max(row["date"] for row in chosen).isoformat()
    net = None if revenue is None or costs is None else revenue - costs
    return {
        "revenue": _figure(revenue, source=source, as_of=as_of, missing_label="אין הכנסות בספרים בטווח. לא הוזן 0."),
        "costs": _figure(costs, source=source, as_of=as_of, missing_label="אין הוצאות בספרים בטווח. לא הוזן 0."),
        "net": _figure(net, source=source, as_of=as_of, missing_label="הנטו בספרים לא ידוע כי צד אחד חסר."),
    }


def _variance(budget: dict, books: dict, bank: dict) -> dict:
    def gap(actual, planned, label):
        left = actual.get("amount")
        right = planned.get("amount")
        if left is None or right is None:
            return _figure(None, source="variance", as_of=actual.get("as_of") or planned.get("as_of"), missing_label=label)
        return _figure(Decimal(str(left)) - Decimal(str(right)), source="variance", as_of=actual.get("as_of"), missing_label=None)
    return {
        "books_vs_budget": gap(books["net"], budget["net"], "הסטייה מול הספרים לא ידועה כי תקציב או ביצוע חסר."),
        "bank_vs_budget": gap(bank["net"], budget["net"], "הסטייה מול הבנק לא ידועה כי תקציב או תנועה חסר."),
    }
