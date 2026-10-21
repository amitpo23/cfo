"""
Bank reconciliation — match bank/card transactions to accounting documents.

Inflow transactions (money in) are matched to **invoices** (AR); outflow
transactions (money out) are matched to **bills** (AP) and **expenses**. Matching
scores amount equality, date proximity and name-token overlap as review
candidates. None of these heuristics is a confirmed business relationship.

`reconcile()` is a pure function over lightweight records so it is trivially
testable. `reconcile_organization()` wraps it: it loads ORM rows for an org,
runs the matcher and returns candidates. Only explicit reviewed decisions can
set a local reconciliation; local reconciliation never proves SUMIT writeback.
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
    """Return candidates; heuristic similarity is never a confirmed match."""
    inflow_pool = list(invoices)
    outflow_pool = list(bills) + list(expenses or [])
    matches: list[Match] = []

    # Process larger amounts first — they are the least ambiguous.
    for txn in sorted(bank_txns, key=lambda t: abs(t.amount), reverse=True):
        pool = inflow_pool if txn.amount > 0 else outflow_pool
        for doc in pool:
            score = _score(txn, doc, amount_tol=amount_tol, date_window=date_window)
            if score is None:
                continue
            if score >= min_score:
                matches.append(Match(txn.id, doc.entity_type, doc.id, round(score, 3), abs(txn.amount)))

    unmatched_docs = [
        {"entity_type": d.entity_type, "entity_id": d.id, "amount": d.amount}
        for d in (inflow_pool + outflow_pool)
    ]
    txn_by_id = {t.id: t for t in bank_txns}
    return {
        "matches": [],
        "candidates": [{**m.__dict__, "status": "candidate", "reason": "provisional_bank" if txn_by_id[m.bank_txn_id].is_provisional else "identity_review_required"} for m in matches],
        "unmatched_txns": [t.id for t in bank_txns],
        # Additive alongside unmatched_txns (kept as a bare list[int] for
        # existing consumers — financial_synthesis.py, BankInsightsDashboard.tsx's
        # number[] typing). Carries is_provisional so the UI can flag Open
        # Finance data as unverified without a breaking shape change.
        "unmatched_txn_details": [
            {"id": tid, "is_provisional": txn_by_id[tid].is_provisional}
            for tid in [t.id for t in bank_txns]
        ],
        "unmatched_docs": unmatched_docs,
        "matched_count": 0,
        "candidate_count": len(matches),
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

    return max(0.0, min(1.0, 0.4 * amount_score + date_score + name_score))


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
def load_docs_for_org(db, organization_id: int) -> tuple[list[DocLite], list[DocLite], list[DocLite]]:
    """טעינת Invoice/Bill/Expense של ארגון והמרתם ל-DocLite — צומת יחיד,
    כדי ש-manual_reconciliation.suggest_matches לא ישכפל את ההמרה הזו
    (הממצא של 24-25/08/2026: השכפול-שלא-קרה הוא בדיוק מה שהשאיר את
    suggest_matches שבור — NameError על משתנים שלא היו קיימים בכלל)."""
    from ..models import Invoice, Bill, Expense

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
    return invoices, bills, expenses


def reconcile_organization(db, organization_id: int, *, persist: bool = True) -> dict[str, Any]:
    """Load org rows, reconcile, and (optionally) persist matches."""
    from ..models import BankTransaction, Payment

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
        if r.transaction_date is not None and not r.is_reconciled
    ]

    invoices, bills, expenses = load_docs_for_org(db, organization_id)

    # Existing receipt observations are candidates too, so a partial receipt
    # can be reviewed against its actual amount rather than the invoice total.
    payments = [DocLite(id=p.id, entity_type="payment", amount=float(p.amount),
                       date=p.payment_date, name="")
                for p in db.query(Payment).filter(Payment.organization_id == organization_id,
                                                 Payment.bill_id.is_(None)).all()]
    result = reconcile(bank_txns, invoices + payments, bills, expenses)
    # Preserve explicit/manual decisions; rerunning the heuristic must not
    # overwrite them. No provider call and no mutation in this read computation.
    result["matches"] = [{"bank_txn_id":r.id,"entity_type":r.matched_entity_type,
                          "entity_id":r.matched_entity_id,"score":None,"amount":abs(float(r.amount)),
                          "status":"confirmed_local"}
                         for r in bank_rows if r.is_reconciled and not r.is_provisional]
    result["matched_count"] = len(result["matches"])
    result["txn_count"] = len(bank_rows)

    return result


def unreconciled_bank_count(
    db, organization_id: int, *, start_date: Optional[date] = None, end_date: Optional[date] = None
) -> int:
    """Count BankTransaction rows not yet reconciled (`is_reconciled` False),
    optionally bounded to a [start_date, end_date] window. Promoted out of
    financial_control_service._unreconciled_bank_count (PR4 — bookkeeper
    morning-cycle orchestrator needs the same count with no date bound; that
    method now delegates here so the two never drift)."""
    from ..models import BankTransaction

    query = db.query(BankTransaction).filter(
        BankTransaction.organization_id == organization_id,
        BankTransaction.is_reconciled == False,  # noqa: E712
    )
    if start_date is not None:
        query = query.filter(BankTransaction.transaction_date >= start_date)
    if end_date is not None:
        query = query.filter(BankTransaction.transaction_date <= end_date)
    return query.count()


def _contact_name(invoice) -> str:
    contact = getattr(invoice, "contact", None)
    return getattr(contact, "name", "") if contact else ""


def _vendor_name(bill) -> str:
    vendor = getattr(bill, "vendor", None)
    return getattr(vendor, "name", "") if vendor else ""
