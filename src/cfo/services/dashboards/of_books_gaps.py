"""Stored Open Finance cash versus the books P&L. No provider call.

A month that exists only on the bank, only in the books, or on both with a
net that differs by more than one shekel is listed. A missing side stays
null and is not shown as zero.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal


def summarize(db, organization_id: int, start: date, end: date) -> dict:
    from .books import classified_bank
    from .books_pnl import BOOKS, books_pnl

    pnl = books_pnl(db, organization_id, start=start, end=end)
    bank_net: dict[str, Decimal] = {}
    bank_seen: set[str] = set()
    for txn, _filed in classified_bank(db, organization_id, start, end, None):
        month = (txn.date or "")[:7]
        if len(month) != 7:
            continue
        bank_seen.add(month)
        if txn.amount is None:
            continue
        bank_net[month] = bank_net.get(month, Decimal("0")) + Decimal(str(txn.amount))
    books_by_month = {month.get("month"): month for month in pnl.get("months") or [] if isinstance(month, dict)}
    rows = []
    for month in sorted(set(books_by_month) | bank_seen):
        books = books_by_month.get(month) or {}
        books_known = books.get("basis") == BOOKS and books.get("net") is not None
        books_amount = Decimal(str(books["net"])) if books_known else None
        has_bank = month in bank_seen
        bank_amount = bank_net.get(month) if has_bank else None
        if books_amount is None and bank_amount is None:
            continue
        gap = None
        if books_amount is not None and bank_amount is not None:
            gap = (books_amount - bank_amount).quantize(Decimal("0.01"))
        if books_amount is None:
            kind = "bank_only"
        elif bank_amount is None:
            kind = "books_only"
        elif abs(gap or 0) > 1:
            kind = "amount_gap"
        else:
            kind = "matched"
        if kind == "matched":
            continue
        rows.append({
            "month": month,
            "kind": kind,
            "books_net": None if books_amount is None else float(books_amount),
            "bank_net": None if bank_amount is None else float(bank_amount.quantize(Decimal("0.01"))),
            "gap": None if gap is None else float(gap),
        })
    return {
        "organization_id": organization_id,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "rows": rows,
        "provider_calls": 0,
        "note_he": "השוואה בין תנועות הבנק השמורות לרווח והפסד מהספרים. אין קריאה ל-Open Finance או ל-SUMIT.",
    }
