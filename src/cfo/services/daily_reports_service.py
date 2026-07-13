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


def vat_report_period(db, organization_id: int, year: int, month: int, *,
                      months: int = 1, basis: str = "document") -> dict[str, Any]:
    """דוח מע"מ תקופתי — חודשי (months=1) או דו-חודשי (months=2), לפי בסיס
    מסמך (basis="document", ברירת מחדל) או בסיס קליטה (basis="captured").

    Uses the single canonical document selection (financial_synthesis.
    select_vat_documents) so this never diverges from compute_vat_position or from
    pcn874.build_pcn874 run with the same parameters. Returns a per-month breakdown
    within the period plus the full list of included documents (for the UI to render
    a drill-down).

    בסיס קליטה משפיע רק על צד התשומות (bills/expenses לפי created_at) — עסקאות
    (invoices) תמיד מדווחות לפי תאריך המסמך, כנדרש רגולטורית.
    """
    from . import financial_synthesis

    pb = financial_synthesis.period_bounds(year, month, months)
    start, end = pb["start"], pb["end"]
    sel = financial_synthesis.select_vat_documents(db, organization_id, start=start, end=end,
                                                    basis=basis)

    output_vat = round(sum(r["vat"] for r in sel["sales"]), 2)
    input_vat = round(sum(r["vat"] for r in sel["inputs"]), 2)
    net_vat = round(output_vat - input_vat, 2)

    def _bucket_month(rec, is_sale: bool) -> Optional[int]:
        if is_sale or basis == "document":
            d = rec["doc_date"]
        else:
            d = rec["captured_date"] or rec["doc_date"]
        return d.month if d else None

    breakdown = []
    for m in pb["months"]:
        m_sales = [r for r in sel["sales"] if _bucket_month(r, True) == m]
        m_inputs = [r for r in sel["inputs"] if _bucket_month(r, False) == m]
        m_out = round(sum(r["vat"] for r in m_sales), 2)
        m_in = round(sum(r["vat"] for r in m_inputs), 2)
        breakdown.append({
            "period": f"{year}-{m:02d}",
            "output_vat": m_out, "input_vat": m_in, "net_vat": round(m_out - m_in, 2),
            "sales_documents": len(m_sales), "purchase_documents": len(m_inputs),
        })

    def _doc_out(r: dict) -> dict[str, Any]:
        return {
            "type": r["type"], "number": r["number"],
            "doc_date": r["doc_date"].isoformat() if r["doc_date"] else None,
            "captured_date": r["captured_date"].isoformat() if r["captured_date"] else None,
            "counterparty": r["counterparty"],
            "amount": round(r["subtotal"], 2), "vat": round(r["vat"], 2),
        }

    documents = [_doc_out(r) for r in sel["sales"]] + [_doc_out(r) for r in sel["inputs"]]

    period_label = (f"{year}-{pb['anchor_month']:02d}" if months == 1 else
                    f"{year}-{pb['anchor_month']:02d}_{year}-{pb['end_month']:02d}")

    # כנות בסיס-קליטה (ממצא אודיט אליהב 2026-07-13, ממצא 4): "captured" משתמש
    # ב-created_at המקומי — אצל ארגון שסונכרן רטרואקטיבית (batch sync) הוא מציין
    # את מועד הסנכרון לרצף, לא את מועד הקליטה האמיתי ב-SUMIT. אין נתון טוב יותר
    # בלי API, אז לא משנים לוגיקה — רק חושפים את המגבלה במפורש במקום לשתוק.
    basis_note = (
        "מועד הקליטה = מועד הקליטה ברצף; בארגון שסונכרן רטרואקטיבית ייתכן פער "
        "מול מועד הקליטה ב-SUMIT." if basis == "captured" else None
    )

    return {
        "period": period_label,
        "months": months,
        "basis": basis,
        "basis_note": basis_note,
        "due_date": pb["due_date"].isoformat(),
        "output_vat": output_vat,
        "input_vat": input_vat,
        "net_vat": net_vat,
        "direction": "לתשלום" if net_vat >= 0 else "להחזר",
        "amount_to_report": abs(net_vat),
        "sales_documents": len(sel["sales"]),
        "purchase_documents": len(sel["inputs"]),
        "breakdown": breakdown,
        "documents": documents,
        "derived": True,
        "disclaimer": DISCLAIMER,
    }


def vat_report(db, organization_id: int, year: int, month: int) -> dict[str, Any]:
    """דוח מע"מ חודשי — עטיפה דקה מעל vat_report_period (months=1, basis=document)
    לתאימות לאחור עם צרכנים קיימים. להרחבות (דו-חודשי / בסיס קליטה) קרא
    ל-vat_report_period ישירות."""
    return vat_report_period(db, organization_id, year, month, months=1, basis="document")


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
            c = db.get(Contact, bill.vendor_id)
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
