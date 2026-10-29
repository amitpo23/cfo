"""Budget, booked bank, and filed books for one grain and date range.

No provider call. A month budget is not divided into a day or a week unless
that line's driver says so. A missing figure stays null.
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
GRAINS = ("day", "week", "month")
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
    cursor = date(start.year, start.month, 1)
    while cursor <= end:
        last = date(cursor.year, cursor.month, monthrange(cursor.year, cursor.month)[1])
        lo = max(cursor, start)
        hi = min(last, end)
        yield f"{cursor.year:04d}-{cursor.month:02d}", lo, hi
        cursor = date(cursor.year + 1, 1, 1) if cursor.month == 12 else date(cursor.year, cursor.month + 1, 1)


def compare_period(db, organization_id: int, plan: dict | None, *, grain: str, start: date, end: date) -> dict:
    if grain not in GRAINS:
        raise ValueError("grain")
    if end < start:
        raise ValueError("range")
    plan = plan if isinstance(plan, dict) else {}
    bank_rows = _booked_rows(db, organization_id, start, end)
    bank_known = _org_has_bank(db, organization_id)
    books_rows = _books_rows(db, organization_id, start, end)
    periods = []
    for label, lo, hi in iter_buckets(grain, start, end):
        budget = _budget_bucket(plan, grain, lo, hi)
        bank = _bank_bucket(bank_rows, lo, hi, bank_known, include_lines=grain == "day")
        books = _books_bucket(books_rows, lo, hi)
        periods.append({
            "label": label,
            "start": lo.isoformat(),
            "end": hi.isoformat(),
            "budget": budget,
            "bank": bank,
            "books": books,
            "variance": _variance(budget, books, bank),
        })
    return {
        "grain": grain,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "provider_calls": 0,
        "periods": periods,
        "note_he": (
            "תקציב מתוך שורות התקציב השמורות. בנק הוא תנועות BOOKED בלבד. "
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


def _budget_bucket(plan: dict, grain: str, lo: date, hi: date) -> dict:
    months = _months_touched(lo, hi)
    context = _context(plan, months)
    source = "plan.budgetLines"
    as_of = next((line.get("source") for line in (plan.get("budgetLines") or []) if isinstance(line, dict) and line.get("source")), None)
    if grain == "month" and _covers_full_month(lo, hi):
        lines = _month_lines(plan, months[0])
        revenue = _side_sum(lines, "revenue")
        costs = _side_sum(lines, "cost")
        net = None if revenue is None or costs is None else revenue - costs
        missing = None if net is not None else "אין תקציב מלא לחודש (הכנסה או הוצאה חסרה). לא הוזן 0."
        return {
            "revenue": _figure(revenue, source=source, as_of=as_of, missing_label="אין תקציב הכנסות לחודש. לא הוזן 0."),
            "costs": _figure(costs, source=source, as_of=as_of, missing_label="אין תקציב הוצאות לחודש. לא הוזן 0."),
            "net": _figure(net, source=source, as_of=as_of, missing_label=missing),
            "month_context": context,
        }
    revenue = costs = Decimal("0")
    revenue_known = costs_known = True
    saw_amount = False
    for month in months:
        lines = _month_lines(plan, month)
        days = _overlap_days(month, lo, hi)
        length = monthrange(int(month[:4]), int(month[5:]))[1]
        for line in lines:
            if line["amount"] is None:
                continue
            saw_amount = True
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
            else:
                costs += share
    if not saw_amount:
        revenue_known = costs_known = False
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
        "revenue": _figure(revenue_amount, source=source, as_of=as_of, missing_label=label),
        "costs": _figure(costs_amount, source=source, as_of=as_of, missing_label=label),
        "net": _figure(net, source=source, as_of=as_of, missing_label=label),
        "month_context": context,
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


def _bank_bucket(rows: list, lo: date, hi: date, bank_known: bool, *, include_lines: bool) -> dict:
    chosen = [row for row in rows if row.transaction_date and lo <= row.transaction_date <= hi]
    source = "bank.BOOKED"
    if not bank_known:
        empty = _figure(None, source=source, as_of=None, missing_label="אין תנועות בנק שמורות. לא הוזן 0.")
        return {"in": empty, "out": empty, "net": empty, "count": 0, "lines": []}
    incoming = sum((Decimal(str(row.amount)) for row in chosen if Decimal(str(row.amount)) > 0), Decimal("0"))
    outgoing = sum((abs(Decimal(str(row.amount))) for row in chosen if Decimal(str(row.amount)) < 0), Decimal("0"))
    as_of = max((row.transaction_date for row in chosen), default=None)
    as_of_text = as_of.isoformat() if as_of else None
    lines = []
    if include_lines:
        for row in sorted(chosen, key=lambda item: (item.transaction_date, item.id))[:100]:
            lines.append({
                "date": row.transaction_date.isoformat(),
                "amount": float(row.amount or 0),
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


def _books_bucket(rows: list[dict], lo: date, hi: date) -> dict:
    chosen = [row for row in rows if lo <= row["date"] <= hi]
    source = "books.local_documents"
    if not chosen:
        empty = _figure(None, source=source, as_of=None, missing_label="אין מסמכי ספרים בטווח. לא הוזן 0.")
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
