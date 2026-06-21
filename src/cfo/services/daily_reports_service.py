"""Daily-cumulative intra-month reports (דוחות מצטברים-יומיים תוך-חודשיים).

Derived from synced SUMIT documents (invoices/bills/expenses/payments) — the same
document-actual basis as the shadow ledger. Gives the accountant and client a live,
day-by-day cumulative picture *during* the month, plus AR/AP aging and supplier
breakdown as of a date.

All output carries `derived: True`. These complement, not replace, SUMIT's books.
"""
from __future__ import annotations

from calendar import monthrange
from datetime import date, timedelta
from typing import Any, Optional

DISCLAIMER = "נגזר מהמסמכים — לבדיקת רו\"ח."


def _f(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _doc_date(r) -> Optional[date]:
    return getattr(r, "issue_date", None) or getattr(r, "due_date", None)


def _month_bounds(year: int, month: int) -> tuple[date, date]:
    return date(year, month, 1), date(year, month, monthrange(year, month)[1])


def cumulative_pl(db, organization_id: int, year: int, month: int) -> dict[str, Any]:
    """Day-by-day cumulative revenue/expense/profit within the month."""
    from ..models import Invoice, Bill, Expense, InvoiceStatus, BillStatus

    start, end = _month_bounds(year, month)
    skip_inv = {InvoiceStatus.DRAFT, InvoiceStatus.VOID, InvoiceStatus.CANCELLED}
    skip_bill = {BillStatus.DRAFT, BillStatus.VOID}

    # Bucket net amounts by day-of-month.
    rev_by_day: dict[int, float] = {}
    exp_by_day: dict[int, float] = {}

    for inv in db.query(Invoice).filter(Invoice.organization_id == organization_id).all():
        if inv.status in skip_inv:
            continue
        d = _doc_date(inv)
        if d and start <= d <= end:
            rev_by_day[d.day] = rev_by_day.get(d.day, 0.0) + _f(inv.subtotal)

    for bill in db.query(Bill).filter(Bill.organization_id == organization_id).all():
        if bill.status in skip_bill:
            continue
        d = _doc_date(bill)
        if d and start <= d <= end:
            exp_by_day[d.day] = exp_by_day.get(d.day, 0.0) + _f(bill.subtotal)

    for exp in db.query(Expense).filter(Expense.organization_id == organization_id).all():
        if str(getattr(exp, "status", "") or "").lower() == "error":
            continue
        d = getattr(exp, "expense_date", None)
        if d and start <= d <= end:
            exp_by_day[d.day] = exp_by_day.get(d.day, 0.0) + _f(exp.amount)

    days = []
    rev_cum = exp_cum = 0.0
    last_day = end.day
    for day in range(1, last_day + 1):
        rev_cum += rev_by_day.get(day, 0.0)
        exp_cum += exp_by_day.get(day, 0.0)
        days.append({
            "date": date(year, month, day).isoformat(),
            "revenue_cum": round(rev_cum, 2),
            "expense_cum": round(exp_cum, 2),
            "profit_cum": round(rev_cum - exp_cum, 2),
        })
    return {
        "period": f"{year}-{month:02d}",
        "days": days,
        "totals": {"revenue": round(rev_cum, 2), "expense": round(exp_cum, 2),
                   "profit": round(rev_cum - exp_cum, 2)},
        "derived": True,
        "disclaimer": DISCLAIMER,
    }


def _aging_buckets(rows, balance_attr: str, as_of: date) -> dict[str, Any]:
    buckets = {"current": 0.0, "1_30": 0.0, "31_60": 0.0, "61_90": 0.0, "90_plus": 0.0}
    items = []
    for r in rows:
        bal = _f(getattr(r, balance_attr, 0))
        if bal <= 0:
            continue
        due = getattr(r, "due_date", None) or _doc_date(r)
        overdue_days = (as_of - due).days if due else 0
        if overdue_days <= 0:
            key = "current"
        elif overdue_days <= 30:
            key = "1_30"
        elif overdue_days <= 60:
            key = "31_60"
        elif overdue_days <= 90:
            key = "61_90"
        else:
            key = "90_plus"
        buckets[key] += bal
        items.append({"due_date": due.isoformat() if due else None,
                      "overdue_days": max(0, overdue_days), "balance": round(bal, 2),
                      "bucket": key})
    return {
        "as_of": as_of.isoformat(),
        "buckets": {k: round(v, 2) for k, v in buckets.items()},
        "total": round(sum(buckets.values()), 2),
        "items": items,
        "derived": True,
        "disclaimer": DISCLAIMER,
    }


def ar_aging(db, organization_id: int, as_of: Optional[date] = None) -> dict[str, Any]:
    """גיול חובות לקוחות — unpaid invoice balances by overdue bucket."""
    from ..models import Invoice, InvoiceStatus
    as_of = as_of or date.today()
    rows = [r for r in db.query(Invoice).filter(Invoice.organization_id == organization_id).all()
            if r.status not in {InvoiceStatus.DRAFT, InvoiceStatus.VOID, InvoiceStatus.CANCELLED, InvoiceStatus.PAID}]
    return _aging_buckets(rows, "balance", as_of)


def ap_aging(db, organization_id: int, as_of: Optional[date] = None) -> dict[str, Any]:
    """גיול התחייבויות לספקים — unpaid bill balances by overdue bucket."""
    from ..models import Bill, BillStatus
    as_of = as_of or date.today()
    rows = [r for r in db.query(Bill).filter(Bill.organization_id == organization_id).all()
            if r.status not in {BillStatus.DRAFT, BillStatus.VOID, BillStatus.PAID}]
    return _aging_buckets(rows, "balance", as_of)


def vat_report(db, organization_id: int, year: int, month: int) -> dict[str, Any]:
    """דוח מע"מ תקופתי — output/input from the canonical VAT position + counts.

    Uses the single canonical source (financial_synthesis.compute_vat_position) so it
    never diverges from the synthesis dashboard. Period-scoped to the month.
    """
    from . import financial_synthesis
    from ..models import Invoice, Bill, Expense, InvoiceStatus, BillStatus

    start, end = _month_bounds(year, month)
    pos = financial_synthesis.compute_vat_position(db, organization_id, start=start, end=end)

    def _count(rows, date_fn, skip):
        return sum(1 for r in rows
                   if getattr(r, "status", None) not in skip
                   and (d := date_fn(r)) and start <= d <= end)

    inv = db.query(Invoice).filter(Invoice.organization_id == organization_id).all()
    bills = db.query(Bill).filter(Bill.organization_id == organization_id).all()
    exps = db.query(Expense).filter(Expense.organization_id == organization_id).all()
    sales_docs = _count(inv, _doc_date, {InvoiceStatus.DRAFT, InvoiceStatus.VOID, InvoiceStatus.CANCELLED})
    purchase_docs = (_count(bills, _doc_date, {BillStatus.DRAFT, BillStatus.VOID})
                     + sum(1 for e in exps if (d := getattr(e, "expense_date", None))
                           and start <= d <= end
                           and str(getattr(e, "status", "") or "").lower() != "error"))

    due_day = date(year + (1 if month == 12 else 0), 1 if month == 12 else month + 1, 15)
    return {
        "period": f"{year}-{month:02d}",
        "due_date": due_day.isoformat(),
        "output_vat": pos["output_vat"],
        "input_vat": pos["input_vat"],
        "net_vat": pos["net_vat"],
        "direction": pos["direction"],
        "amount_to_report": abs(pos["net_vat"]),
        "sales_documents": sales_docs,
        "purchase_documents": purchase_docs,
        "derived": True,
        "disclaimer": DISCLAIMER + " מע\"מ נגזר 18% (ה-API של SUMIT אינו חושף פירוק VAT).",
    }


def supplier_breakdown(db, organization_id: int, year: int, month: int) -> dict[str, Any]:
    """ספקים — spend by supplier within the month (bills + filed expenses)."""
    from ..models import Bill, Expense, Contact, BillStatus

    start, end = _month_bounds(year, month)
    totals: dict[str, float] = {}

    for bill in db.query(Bill).filter(Bill.organization_id == organization_id).all():
        if bill.status in {BillStatus.DRAFT, BillStatus.VOID}:
            continue
        d = _doc_date(bill)
        if not (d and start <= d <= end):
            continue
        name = "ספק"
        if bill.vendor_id:
            c = db.query(Contact).get(bill.vendor_id)
            if c:
                name = c.name or name
        totals[name] = totals.get(name, 0.0) + _f(bill.total)

    for exp in db.query(Expense).filter(Expense.organization_id == organization_id).all():
        d = getattr(exp, "expense_date", None)
        if not (d and start <= d <= end):
            continue
        if str(getattr(exp, "status", "") or "").lower() == "error":
            continue
        name = exp.supplier_name or "ספק"
        totals[name] = totals.get(name, 0.0) + _f(exp.total)

    suppliers = sorted(
        ({"supplier": k, "total": round(v, 2)} for k, v in totals.items()),
        key=lambda x: x["total"], reverse=True,
    )
    return {
        "period": f"{year}-{month:02d}",
        "suppliers": suppliers,
        "total": round(sum(s["total"] for s in suppliers), 2),
        "derived": True,
        "disclaimer": DISCLAIMER,
    }
