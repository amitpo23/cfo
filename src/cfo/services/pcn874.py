"""PCN874 detailed-VAT file builder (דוח מפורט מע"מ — מבנה אחיד).

Builds the fixed-width PCN874 text file the Israeli Tax Authority expects, from the
real document tables (invoices = sales, bills/expenses = inputs) — the same
document-actual basis as the rest of the engine.

IMPORTANT — DRAFT STRUCTURE: the record types (O/S1/L/X) and field order follow the
published מבנה-אחיד, but exact byte offsets evolve by spec version. Output is marked
a draft to validate against the current official spec before submission; it is NOT a
guaranteed-conformant file. The numbers themselves reconcile to the canonical VAT
position (tested), so it is correct as data even where the layout needs verification.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Optional

DISCLAIMER = "טיוטת PCN874 — מבנה לאימות מול מפרט רשות המסים העדכני לפני הגשה."

# Record-type codes (מבנה אחיד).
REC_HEADER = "O"
REC_SALE_TAXABLE = "S1"
REC_INPUT = "L"
REC_TRAILER = "X"


def _num(value, width: int) -> str:
    """Zero-padded, right-aligned non-negative integer (agorot-rounded shekels)."""
    n = int(round(abs(float(value or 0))))
    return str(n).rjust(width, "0")[:width]


def _txt(value, width: int) -> str:
    return (str(value or "")[:width]).ljust(width)


def _vat_id(value, width: int = 9) -> str:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    return digits.rjust(width, "0")[-width:] if digits else "0" * width


def _yyyymmdd(d: Optional[date]) -> str:
    return d.strftime("%Y%m%d") if d else "00000000"


def build_pcn874(db, organization_id: int, year: int, month: int, *,
                 company_vat_id: str = "000000000",
                 gen_date: Optional[date] = None) -> dict[str, Any]:
    """Build the PCN874 file content + a reconciling summary for the period."""
    from calendar import monthrange
    from ..models import Invoice, Bill, Expense, InvoiceStatus, BillStatus

    start = date(year, month, 1)
    end = date(year, month, monthrange(year, month)[1])

    def _f(v) -> float:
        try:
            return float(v or 0)
        except (TypeError, ValueError):
            return 0.0

    def _in(d) -> bool:
        return d is not None and start <= d <= end

    # Sales (output VAT) from invoices.
    sale_lines, total_sales, total_output_vat = [], 0.0, 0.0
    inv_rows = db.query(Invoice).filter(Invoice.organization_id == organization_id).all()
    for inv in inv_rows:
        if inv.status in {InvoiceStatus.DRAFT, InvoiceStatus.VOID, InvoiceStatus.CANCELLED}:
            continue
        d = inv.issue_date or inv.due_date
        if not _in(d):
            continue
        subtotal, vat = _f(inv.subtotal), _f(inv.tax)
        total_sales += subtotal
        total_output_vat += vat
        sale_lines.append(
            REC_SALE_TAXABLE
            + _vat_id(getattr(inv, "allocation_number", None) or "")
            + _yyyymmdd(d)
            + _txt(inv.invoice_number, 9)
            + _num(subtotal, 11) + _num(vat, 9)
        )

    # Inputs (input VAT) from bills + filed expenses.
    input_lines, total_inputs, total_input_vat = [], 0.0, 0.0
    for bill in db.query(Bill).filter(Bill.organization_id == organization_id).all():
        if bill.status in {BillStatus.DRAFT, BillStatus.VOID}:
            continue
        d = bill.issue_date or bill.due_date
        if not _in(d):
            continue
        subtotal, vat = _f(bill.subtotal), _f(bill.tax)
        total_inputs += subtotal
        total_input_vat += vat
        input_lines.append(
            REC_INPUT + _vat_id(None) + _yyyymmdd(d) + _txt(bill.bill_number, 9)
            + _num(subtotal, 11) + _num(vat, 9)
        )
    for exp in db.query(Expense).filter(Expense.organization_id == organization_id).all():
        if str(getattr(exp, "status", "") or "").lower() == "error":
            continue
        d = getattr(exp, "expense_date", None)
        if not _in(d):
            continue
        net, vat = _f(exp.amount), _f(exp.vat_amount)
        total_inputs += net
        total_input_vat += vat
        input_lines.append(
            REC_INPUT + _vat_id(getattr(exp, "supplier_tax_id", None))
            + _yyyymmdd(d) + _txt(getattr(exp, "invoice_number", None), 9)
            + _num(net, 11) + _num(vat, 9)
        )

    header = (
        REC_HEADER + _vat_id(company_vat_id) + f"{year}{month:02d}"
        + _yyyymmdd(gen_date or start)
        + _num(total_sales, 11) + _num(total_output_vat, 9)
        + _num(total_inputs, 11) + _num(total_input_vat, 9)
    )
    detail = sale_lines + input_lines
    trailer = REC_TRAILER + _num(len(detail), 9)
    content = "\r\n".join([header] + detail + [trailer])

    net_vat = round(total_output_vat - total_input_vat, 2)
    return {
        "filename": f"PCN874_{_vat_id(company_vat_id)}_{year}{month:02d}.txt",
        "period": f"{year}-{month:02d}",
        "content": content,
        "record_count": len(detail),
        "summary": {
            "sales": round(total_sales, 2),
            "output_vat": round(total_output_vat, 2),
            "inputs": round(total_inputs, 2),
            "input_vat": round(total_input_vat, 2),
            "net_vat": net_vat,
            "direction": "לתשלום" if net_vat >= 0 else "להחזר",
        },
        "draft": True,
        "disclaimer": DISCLAIMER,
    }
