"""Monthly P&L with one source per month: the books, or classified bank cash.

A month uses the books (SUMIT invoices, bills and expenses already in the
database) only when they cover it. Otherwise the month is computed from the
BOOKED bank rows filed by ``filing`` and divided by 1.18 where the flow carries
VAT, and it is labelled "בסיס מזומן". A month never mixes the two sources.

Coverage of a month:

* ``closed``   the month is in ``plan.booksClosedMonths`` (marked by the office);
* ``complete`` books revenue and books costs are each at least
  ``BOOKS_COVERAGE_MIN`` of the classified bank amounts (ex-VAT);
* ``partial``  there are books, below that threshold;
* ``none``     no books at all.

No provider calls. Reads only.
"""
from __future__ import annotations

from datetime import date, timedelta

from ...models import Bill, Expense, Invoice
from ..bank_coverage import cashflow_row_objects
from ..financial_reports_service import FinancialReportsService
from . import filing

BOOKS_COVERAGE_MIN = 0.8
LEDGER = "ledger"
CASH_BASIS = "cash_basis"
SOURCE_LABELS = {
    LEDGER: "ספרים (הנהלת חשבונות)",
    CASH_BASIS: "בסיס מזומן — תנועות בנק מסווגות, ללא מע״מ",
}
COVERAGE_LABELS = {
    "closed": "ספרים סגורים",
    "complete": "ספרים מלאים",
    "partial": "ספרים חלקיים",
    "none": "אין ספרים",
}
INVOICE_LOOKBACK_DAYS = 150


def month_windows(start: date, end: date):
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        first = date(year, month, 1)
        nxt = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
        last = nxt - timedelta(days=1)
        yield f"{year}-{month:02d}", max(first, start), min(last, end)
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)


def _r(x: float) -> float:
    return round(x + 0.0, 2)


def classified_bank(db, organization_id: int, start: date, end: date, plan: dict | None = None):
    """BOOKED cash rows of the window with their filing result."""
    plan = plan if isinstance(plan, dict) else {}
    rows = cashflow_row_objects(db, organization_id, start, end)
    # The cash flow drops admin-confirmed duplicates; the cash-basis P&L must too.
    from .activity_quality import confirmed_drop_ids
    dropped = confirmed_drop_ids(rows, plan)
    if dropped:
        rows = [row for row in rows if row.id not in dropped]
    inv_rows = (
        db.query(Invoice)
        .filter(
            Invoice.organization_id == organization_id,
            Invoice.issue_date >= start - timedelta(days=INVOICE_LOOKBACK_DAYS),
            Invoice.issue_date <= end,
        )
        .order_by(Invoice.issue_date, Invoice.id)
        .all()
    )
    invoices = [
        {"organization_id": i.organization_id, "number": i.invoice_number,
         "date": i.issue_date.isoformat(), "total": float(i.total or 0)}
        for i in inv_rows if i.issue_date is not None
    ]
    txns = [filing.txn_from_row(r) for r in rows]
    filed = filing.classify_all(
        txns, invoices=invoices,
        decisions=plan.get("statusDecisions") if isinstance(plan.get("statusDecisions"), dict) else None,
        custom_rules=plan.get("statusRules") if isinstance(plan.get("statusRules"), list) else None,
    )
    return [(t, filed[id(t)]) for t in txns]


def cash_basis_month(items, vat_rate: float = filing.VAT_RATE) -> dict:
    """P&L lines of one month from filed BOOKED rows (tool's COMPARISON_ROWS)."""
    by_cat: dict[str, float] = {}
    for t, f in items:
        by_cat[f.category] = by_cat.get(f.category, 0.0) + t.amount
    lines = []
    revenue = costs = 0.0
    for row in filing.PNL_ROWS:
        gross = sum(by_cat.get(c, 0.0) for c in row["cats"])
        value = _r(abs(gross) / (1 + vat_rate if row["vat"] else 1))
        lines.append({"id": row["id"], "label": row["label"], "side": row["side"],
                      "amount": value, "vat_basis": "ex_vat" if row["vat"] else "no_vat"})
        if row["side"] == "revenue":
            revenue += value
        else:
            costs += value
    unresolved_in = _r(sum(by_cat.get(c, 0.0) for c in ("other_in", "bank_journal")))
    unresolved_out = _r(abs(by_cat.get("transfers_out", 0.0)))
    review_out = _r(abs(by_cat.get("cash_withdrawals", 0.0)))
    return {
        "revenue": _r(revenue),
        "costs": _r(costs),
        "net": _r(revenue - costs),
        "lines": lines,
        "unresolved_in": unresolved_in,
        "unresolved_out": unresolved_out,
        "review_out": review_out,
        "blocked": unresolved_out > filing.UNASSIGNED_BLOCK,
        "by_category": {k: _r(v) for k, v in sorted(by_cat.items())},
    }


def _ledger_month(reports: FinancialReportsService, organization_id: int, lo: date, hi: date):
    revenue = {i.category: float(i.amount) for i in reports._ledger_revenue_items(organization_id, lo, hi, lo, hi, False)}
    costs = {i.category: float(i.amount) for i in reports._ledger_expense_items(organization_id, lo, hi, lo, hi, False)}
    return revenue, costs


def _document_months(db, organization_id: int, lo: date, hi: date) -> set[str]:
    """"YYYY-MM" of every invoice, bill or expense dated in the window. Three queries for any window."""
    months: set[str] = set()
    for column, owner in ((Invoice.issue_date, Invoice.organization_id),
                          (Bill.issue_date, Bill.organization_id),
                          (Expense.expense_date, Expense.organization_id)):
        for (day,) in db.query(column).filter(owner == organization_id, column >= lo, column <= hi).distinct():
            if day is not None:
                months.add(f"{day.year:04d}-{day.month:02d}")
    return months


def coverage_of(month: str, ledger_rev: float, ledger_cost: float, has_books: bool,
                bank: dict | None, closed: set[str]) -> str:
    if month in closed:
        return "closed"
    if not has_books:
        return "none"
    bank_rev = bank["revenue"] if bank else 0.0
    bank_cost = bank["costs"] if bank else 0.0
    if ledger_rev + 0.005 >= BOOKS_COVERAGE_MIN * bank_rev and ledger_cost + 0.005 >= BOOKS_COVERAGE_MIN * bank_cost:
        return "complete"
    return "partial"


def monthly_pnl(db, organization_id: int, start: date, end: date, plan: dict | None = None,
                *, filed=None, reports: FinancialReportsService | None = None) -> dict:
    """``filed`` is ``classified_bank`` of the same window when the caller has it already."""
    plan = plan if isinstance(plan, dict) else {}
    closed = {m for m in plan.get("booksClosedMonths") or [] if isinstance(m, str)}
    reports = reports or FinancialReportsService(db, memoize=True)
    if filed is None:
        filed = classified_bank(db, organization_id, start, end, plan)
    documents = _document_months(db, organization_id, start, end)
    months = []
    for key, lo, hi in month_windows(start, end):
        items = [(t, f) for t, f in filed if lo.isoformat() <= t.date <= hi.isoformat()]
        bank = cash_basis_month(items) if items else None
        ledger_rev, ledger_cost = _ledger_month(reports, organization_id, lo, hi)
        has_books = bool(ledger_rev) or bool(ledger_cost) or key in documents
        rev_total, cost_total = sum(ledger_rev.values()), sum(ledger_cost.values())
        coverage = coverage_of(key, rev_total, cost_total, has_books, bank, closed)
        if coverage in ("closed", "complete") and has_books:
            source = LEDGER
            revenue, costs = _r(rev_total), _r(cost_total)
            detail = {"revenue_by_category": {k: _r(v) for k, v in ledger_rev.items()},
                      "costs_by_category": {k: _r(v) for k, v in ledger_cost.items()}}
            blocked = False
        elif bank is not None:
            source = CASH_BASIS
            revenue, costs = bank["revenue"], bank["costs"]
            detail = {k: bank[k] for k in ("lines", "unresolved_in", "unresolved_out", "review_out", "by_category")}
            blocked = bank["blocked"]
        else:
            source = None
            revenue = costs = None
            detail = {}
            blocked = False
        months.append({
            "month": key,
            "period_start": lo.isoformat(),
            "period_end": hi.isoformat(),
            "partial_month": lo.day != 1 or (hi + timedelta(days=1)).day != 1,
            "coverage": coverage,
            "coverage_label": COVERAGE_LABELS[coverage],
            "source": source,
            "source_label": SOURCE_LABELS.get(source) if source else "לא ידוע",
            "books_revenue": _r(rev_total) if has_books else None,
            "books_costs": _r(cost_total) if has_books else None,
            "revenue": revenue,
            "costs": costs,
            "net": None if revenue is None else _r(revenue - costs),
            "blocked": blocked,
            **detail,
        })
    known = [m for m in months if m["source"]]
    sources = {m["source"] for m in known}
    return {
        "months": months,
        "basis": (sources.pop() if len(sources) == 1 else "mixed") if sources else "unknown",
        "total_revenue": _r(sum(m["revenue"] for m in known)) if known else None,
        "total_expenses": _r(sum(m["costs"] for m in known)) if known else None,
        "net": _r(sum(m["net"] for m in known)) if known else None,
        "provider_calls": 0,
    }


def assert_publishable(pnl: dict) -> None:
    """A snapshot never shows a books month whose books are partial."""
    for m in (pnl or {}).get("months") or []:
        if m.get("source") == LEDGER and m.get("coverage") not in ("closed", "complete"):
            raise ValueError(f"month {m.get('month')} uses partial books")
