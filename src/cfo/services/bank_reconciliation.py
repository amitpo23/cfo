"""
Bank reconciliation — match bank/card transactions to accounting documents.

Inflow transactions (money in) are matched to **invoices** (AR); outflow
transactions (money out) are matched to **bills** (AP) and **expenses**. Matching
scores amount equality, date proximity and name-token overlap, then greedily
assigns the best unique match per bank transaction.

`reconcile()` is a pure function over lightweight records so it is trivially
testable. `reconcile_organization()` wraps it: it loads ORM rows for an org,
runs the matcher, and writes `matched_entity_type` / `matched_entity_id` /
`is_reconciled` back onto the `BankTransaction` rows.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Any, Optional


@dataclass
class BankTxnLite:
    id: Any
    amount: float            # signed: + inflow, - outflow
    date: date
    description: str = ""
    is_provisional: bool = False


@dataclass
class DocLite:
    id: Any
    entity_type: str         # "invoice" | "bill" | "expense"
    amount: float            # positive magnitude
    date: Optional[date] = None
    name: str = ""


@dataclass
class Match:
    bank_txn_id: Any
    entity_type: str
    entity_id: Any
    score: float
    amount: float


def reconcile(
    bank_txns: list[BankTxnLite],
    invoices: list[DocLite],
    bills: list[DocLite],
    expenses: Optional[list[DocLite]] = None,
    *,
    amount_tol: float = 0.02,
    date_window: int = 7,
    min_score: float = 0.5,
) -> dict[str, Any]:
    """Return {matches, unmatched_txns, unmatched_docs}."""
    inflow_pool = list(invoices)
    outflow_pool = list(bills) + list(expenses or [])
    used: set[tuple[str, Any]] = set()
    matches: list[Match] = []
    unmatched_txns: list[Any] = []

    # Process larger amounts first — they are the least ambiguous.
    for txn in sorted(bank_txns, key=lambda t: abs(t.amount), reverse=True):
        pool = inflow_pool if txn.amount > 0 else outflow_pool
        best: Optional[tuple[float, DocLite]] = None
        for doc in pool:
            if (doc.entity_type, doc.id) in used:
                continue
            score = _score(txn, doc, amount_tol=amount_tol, date_window=date_window)
            if score is None:
                continue
            if best is None or score > best[0]:
                best = (score, doc)
        if best and best[0] >= min_score:
            score, doc = best
            used.add((doc.entity_type, doc.id))
            matches.append(Match(txn.id, doc.entity_type, doc.id, round(score, 3), abs(txn.amount)))
        else:
            unmatched_txns.append(txn.id)

    unmatched_docs = [
        {"entity_type": d.entity_type, "entity_id": d.id, "amount": d.amount}
        for d in (inflow_pool + outflow_pool)
        if (d.entity_type, d.id) not in used
    ]
    txn_by_id = {t.id: t for t in bank_txns}
    return {
        "matches": [m.__dict__ for m in matches],
        "unmatched_txns": unmatched_txns,
        # Additive alongside unmatched_txns (kept as a bare list[int] for
        # existing consumers — financial_synthesis.py, BankInsightsDashboard.tsx's
        # number[] typing). Carries is_provisional so the UI can flag Open
        # Finance data as unverified without a breaking shape change.
        "unmatched_txn_details": [
            {"id": tid, "is_provisional": txn_by_id[tid].is_provisional}
            for tid in unmatched_txns
        ],
        "unmatched_docs": unmatched_docs,
        "matched_count": len(matches),
        "txn_count": len(bank_txns),
    }


def _score(txn: BankTxnLite, doc: DocLite, *, amount_tol: float, date_window: int) -> Optional[float]:
    """Return a 0..1 match score, or None if the amount gate fails."""
    txn_amount = abs(txn.amount)
    if doc.amount <= 0:
        return None
    # Amount gate: must be within tolerance (relative or 1 agora absolute).
    diff = abs(txn_amount - doc.amount)
    if diff > max(amount_tol * doc.amount, 0.01):
        return None
    amount_score = 1.0 - min(diff / doc.amount, 1.0) if doc.amount else 0.0

    # Date proximity (within window) contributes up to 0.3.
    date_score = 0.0
    if doc.date and txn.date:
        days = abs((txn.date - doc.date).days)
        if days <= date_window:
            date_score = 0.3 * (1.0 - days / date_window)
        else:
            date_score = -0.2  # outside the window — penalize but don't disqualify

    # Name-token overlap contributes up to 0.3.
    name_score = 0.3 * _token_overlap(txn.description, doc.name)

    return max(0.0, min(1.0, 0.4 * amount_score + date_score + name_score + 0.3))


def _token_overlap(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    inter = ta & tb
    return len(inter) / max(len(ta), len(tb))


def _tokens(text: str) -> set[str]:
    if not text:
        return set()
    return {w for w in re.split(r"[^\wא-ת]+", text.lower()) if len(w) >= 2}


# ---------------------------------------------------------------------- #
# DB wrapper
# ---------------------------------------------------------------------- #
def reconcile_organization(db, organization_id: int, *, persist: bool = True) -> dict[str, Any]:
    """Load org rows, reconcile, and (optionally) persist matches."""
    from ..models import BankTransaction, Invoice, Bill, Expense

    bank_rows = (
        db.query(BankTransaction)
        .filter(BankTransaction.organization_id == organization_id)
        .all()
    )
    bank_txns = [
        BankTxnLite(
            id=r.id, amount=float(r.amount), date=r.transaction_date,
            description=r.description or "", is_provisional=bool(r.is_provisional),
        )
        for r in bank_rows
        if r.transaction_date is not None
    ]

    invoices = [
        DocLite(id=r.id, entity_type="invoice", amount=float(r.total or 0),
                date=r.issue_date or r.due_date, name=_contact_name(r))
        for r in db.query(Invoice).filter(Invoice.organization_id == organization_id).all()
    ]
    bills = [
        DocLite(id=r.id, entity_type="bill", amount=float(r.total or 0),
                date=getattr(r, "issue_date", None) or getattr(r, "due_date", None),
                name=_vendor_name(r))
        for r in db.query(Bill).filter(Bill.organization_id == organization_id).all()
    ]
    expenses = [
        DocLite(id=r.id, entity_type="expense", amount=float(getattr(r, "amount", 0) or 0),
                date=getattr(r, "expense_date", None) or getattr(r, "date", None),
                name=getattr(r, "supplier_name", "") or getattr(r, "description", "") or "")
        for r in db.query(Expense).filter(Expense.organization_id == organization_id).all()
    ]

    result = reconcile(bank_txns, invoices, bills, expenses)

    if persist and result["matches"]:
        by_id = {r.id: r for r in bank_rows}
        for m in result["matches"]:
            row = by_id.get(m["bank_txn_id"])
            if row is not None:
                row.matched_entity_type = m["entity_type"]
                row.matched_entity_id = m["entity_id"]
                row.is_reconciled = True
        db.commit()
    return result


def _contact_name(invoice) -> str:
    contact = getattr(invoice, "contact", None)
    return getattr(contact, "name", "") if contact else ""


def _vendor_name(bill) -> str:
    vendor = getattr(bill, "vendor", None)
    return getattr(vendor, "name", "") if vendor else ""
