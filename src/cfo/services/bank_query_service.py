"""Bank-aware query service (M8 — bank-aware AI chat tools).

Thin, org-scoped read layer over `BankTransaction` / `Account`, mirroring the
existing `_list_expenses` pattern (count/total over the FULL filtered set,
not just the returned page). This module adds three read-only capabilities
that the AI chat tools wrap:

- `query_bank_transactions` — filterable list of bank/card transactions.
- `get_bank_position` — per-account latest-snapshot view (balance + freshness).
- `classify_missing_documents` — outgoing, unmatched transactions bucketed
  into "explained" categories (transfers, cash withdrawals, card settlement,
  standing orders, taxes, bank fees, loans, salary) vs. remaining
  "missing_document" candidates, grouped by normalized merchant/description.

`raw_data` on `BankTransaction` carries the Open Finance payload, notably
`category.main` / `category.sub`, `type` ("CHECKING"/"CARD") and `merchantName`.
Everything here treats `raw_data` as optional/untrusted — a missing key never
raises, it just falls back to "unknown".
"""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import date as date_type
from typing import Any

from sqlalchemy import Integer, func
from sqlalchemy.orm import Session

from ..models import Account, BankTransaction


# --------------------------------------------------------------------- #
# Exclusion taxonomy — keyword lists kept as module constants so they can
# be tuned/extended without touching the classification logic itself.
# --------------------------------------------------------------------- #

CASH_KEYWORDS = ["משיכה מבנקט", "הפק מזומן", "משיכת מזומן", "כספומט"]

TRANSFER_KEYWORDS = [
    "העברה לבנק אחר", "העב' ללקוח אחר", "העברה ללקוח אחר",
    "העברה לפקדון", "פר\"י", "פרי",
]

STANDING_ORDER_KEYWORDS = ["הוראת קבע", "הוראת-קבע"]

TAX_KEYWORDS = ["מס הכנסה", "מע\"מ", "מעמ", "ביטוח לאומי", "רשות המסים"]

BANK_FEE_KEYWORDS = ["עמלת", "עמלות", "דמי ניהול", "ריבית", "החזרת שיק", "תיקון"]

LOAN_KEYWORDS = ["הלוואה", "החזר הלוואה", "משכנתא"]

SALARY_KEYWORDS = ["שכר", "משכורת", "תלוש"]

# category.main/sub values (Open Finance taxonomy) that map to cash withdrawals.
CASH_CATEGORY_VALUES = {"CASH_WITHDRAWALS", "OTHER"}

CARD_SETTLEMENT_CATEGORY_SUB = "CREDIT_CARD_CHECKING"

BUCKET_ORDER = [
    "card_settlement", "cash", "transfers", "standing_orders",
    "taxes", "bank_fees", "loans", "salary",
]


def _parse_date_safe(value):
    if value is None or isinstance(value, date_type):
        return value
    try:
        return date_type.fromisoformat(str(value))
    except (ValueError, TypeError):
        return None


def _raw_get(txn: BankTransaction, *path, default=None):
    """Safe nested lookup into `raw_data` — never raises on missing/odd shapes."""
    node = txn.raw_data
    for key in path:
        if not isinstance(node, dict):
            return default
        node = node.get(key)
    return node if node is not None else default


def _category_main(txn: BankTransaction) -> str | None:
    return _raw_get(txn, "category", "main")


def _category_sub(txn: BankTransaction) -> str | None:
    return _raw_get(txn, "category", "sub")


def _txn_type(txn: BankTransaction) -> str | None:
    return _raw_get(txn, "type") or _raw_get(txn, "raw", "type")


def _merchant_name(txn: BankTransaction) -> str | None:
    return _raw_get(txn, "merchantName")


def _status(txn: BankTransaction) -> str | None:
    return _raw_get(txn, "status")


def _row_dict(txn: BankTransaction) -> dict[str, Any]:
    return {
        "id": txn.id,
        "date": txn.transaction_date.isoformat() if txn.transaction_date else None,
        "amount": float(txn.amount or 0),
        "currency": txn.currency,
        "description": txn.description,
        "type": _txn_type(txn),
        "category_main": _category_main(txn),
        "category_sub": _category_sub(txn),
        "is_reconciled": bool(txn.is_reconciled),
        "is_provisional": bool(txn.is_provisional),
    }


def query_bank_transactions(
    db: Session,
    org_id: int,
    *,
    date_from: str | date_type | None = None,
    date_to: str | date_type | None = None,
    search: str | None = None,
    txn_type: str | None = None,
    direction: str | None = None,
    only_unmatched: bool = False,
    limit: int = 50,
) -> dict[str, Any]:
    """Filterable list of bank/card transactions for one organization.

    Mirrors `_list_expenses`: `count`/`total_amount` are computed over the
    FULL filtered set, `rows` is capped at `limit` (default 50, most recent
    first by transaction_date).
    """
    q = db.query(BankTransaction).filter(BankTransaction.organization_id == org_id)

    parsed_from = _parse_date_safe(date_from)
    if parsed_from:
        q = q.filter(BankTransaction.transaction_date >= parsed_from)
    parsed_to = _parse_date_safe(date_to)
    if parsed_to:
        q = q.filter(BankTransaction.transaction_date <= parsed_to)
    if search:
        q = q.filter(BankTransaction.description.ilike(f"%{search}%"))
    if direction == "in":
        q = q.filter(BankTransaction.amount > 0)
    elif direction == "out":
        q = q.filter(BankTransaction.amount < 0)
    if only_unmatched:
        q = q.filter(BankTransaction.is_reconciled.is_(False))

    # txn_type ("CHECKING"/"CARD") lives inside raw_data JSON — not every
    # backend supports indexing into JSON in SQL, so filter in Python after
    # pulling the (already date/search/direction-narrowed) candidate set.
    all_rows = q.order_by(BankTransaction.transaction_date.desc()).all()
    if txn_type:
        all_rows = [t for t in all_rows if _txn_type(t) == txn_type]

    count = len(all_rows)
    total_amount = round(float(sum(float(t.amount or 0) for t in all_rows)), 2)
    rows = [_row_dict(t) for t in all_rows[:limit]]

    return {
        "count": count,
        "total_amount": total_amount,
        "transactions": rows,
    }


def get_bank_position(db: Session, org_id: int) -> dict[str, Any]:
    """Per-account latest snapshot — balance, last transaction date, counts.

    `is_provisional` presence is surfaced explicitly so callers (and the
    chat model) never present Open-Finance-derived figures as fully
    reconciled fact without the caveat.
    """
    accounts = db.query(Account).filter(Account.organization_id == org_id).all()

    stats_by_account: dict[int, dict[str, Any]] = {}
    rows = (
        db.query(
            BankTransaction.account_id,
            func.max(BankTransaction.transaction_date).label("last_date"),
            func.count(BankTransaction.id).label("txn_count"),
            func.sum(func.cast(BankTransaction.is_provisional, Integer)).label("provisional_count"),
        )
        .filter(BankTransaction.organization_id == org_id)
        .group_by(BankTransaction.account_id)
        .all()
    )
    for r in rows:
        stats_by_account[r.account_id] = {
            "last_transaction_date": r.last_date.isoformat() if r.last_date else None,
            "transaction_count": int(r.txn_count or 0),
            "provisional_count": int(r.provisional_count or 0),
        }

    accounts_out = []
    for acc in accounts:
        stats = stats_by_account.get(acc.id, {
            "last_transaction_date": None, "transaction_count": 0, "provisional_count": 0,
        })
        accounts_out.append({
            "account_id": acc.id,
            "name": acc.name,
            "account_type": getattr(acc.account_type, "value", acc.account_type),
            "external_id": acc.external_id,
            "balance": float(acc.balance) if acc.balance is not None else None,
            "currency": acc.currency,
            "last_transaction_date": stats["last_transaction_date"],
            "transaction_count": stats["transaction_count"],
            "has_provisional_data": stats["provisional_count"] > 0,
        })

    return {"accounts": accounts_out}


# --------------------------------------------------------------------- #
# Missing-document classification
# --------------------------------------------------------------------- #

def _contains_any(text: str, keywords: list[str]) -> bool:
    return any(kw in text for kw in keywords)


def _classify_bucket(txn: BankTransaction) -> str | None:
    """Return an exclusion bucket name for an outgoing transaction, or None
    if it doesn't match any known "explained" category (i.e. it's a
    missing-document candidate)."""
    desc = txn.description or ""
    cat_sub = (_category_sub(txn) or "").upper()
    cat_main = (_category_main(txn) or "").upper()

    if cat_sub == CARD_SETTLEMENT_CATEGORY_SUB.upper():
        return "card_settlement"
    if cat_main in CASH_CATEGORY_VALUES or cat_sub in CASH_CATEGORY_VALUES or _contains_any(desc, CASH_KEYWORDS):
        return "cash"
    if _contains_any(desc, TRANSFER_KEYWORDS):
        return "transfers"
    if _contains_any(desc, STANDING_ORDER_KEYWORDS):
        return "standing_orders"
    if _contains_any(desc, TAX_KEYWORDS):
        return "taxes"
    if _contains_any(desc, BANK_FEE_KEYWORDS):
        return "bank_fees"
    if _contains_any(desc, LOAN_KEYWORDS):
        return "loans"
    if _contains_any(desc, SALARY_KEYWORDS):
        return "salary"
    return None


def _normalize_description(desc: str) -> str:
    """Collapse whitespace/case/digits so the same merchant with a varying
    reference number groups together."""
    text = (desc or "").strip()
    text = re.sub(r"\d+", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip() or "(ללא תיאור)"


def classify_missing_documents(
    db: Session,
    org_id: int,
    *,
    date_from: str | date_type | None = None,
) -> dict[str, Any]:
    """Classify outgoing, unmatched bank transactions into excluded buckets
    vs. missing-document candidates.

    Returns per-bucket summary totals plus, for the missing_document
    residue, the top candidate merchants (grouped by normalized
    description) split by BANK ("CHECKING") vs CARD channel.
    """
    q = db.query(BankTransaction).filter(
        BankTransaction.organization_id == org_id,
        BankTransaction.amount < 0,
        BankTransaction.is_reconciled.is_(False),
    )
    parsed_from = _parse_date_safe(date_from)
    if parsed_from:
        q = q.filter(BankTransaction.transaction_date >= parsed_from)

    rows = q.all()

    buckets: dict[str, dict[str, Any]] = {
        name: {"count": 0, "total": 0.0} for name in BUCKET_ORDER
    }
    candidates: list[BankTransaction] = []

    for t in rows:
        bucket = _classify_bucket(t)
        if bucket is not None:
            buckets[bucket]["count"] += 1
            buckets[bucket]["total"] += abs(float(t.amount or 0))
        else:
            candidates.append(t)

    for b in buckets.values():
        b["total"] = round(b["total"], 2)

    # Group missing-document candidates by normalized description, split by channel.
    groups: dict[tuple[str, str], dict[str, Any]] = defaultdict(
        lambda: {"count": 0, "total": 0.0, "last_date": None}
    )
    for t in candidates:
        channel = "CARD" if _txn_type(t) == "CARD" else "BANK"
        key = (channel, _normalize_description(_merchant_name(t) or t.description or ""))
        g = groups[key]
        g["count"] += 1
        g["total"] += abs(float(t.amount or 0))
        if t.transaction_date and (g["last_date"] is None or t.transaction_date.isoformat() > g["last_date"]):
            g["last_date"] = t.transaction_date.isoformat()

    top_candidates = [
        {
            "channel": channel,
            "merchant": merchant,
            "count": g["count"],
            "total": round(g["total"], 2),
            "last_date": g["last_date"],
        }
        for (channel, merchant), g in groups.items()
    ]
    top_candidates.sort(key=lambda g: g["total"], reverse=True)

    return {
        "excluded": buckets,
        "missing_document": {
            "count": len(candidates),
            "total": round(sum(abs(float(t.amount or 0)) for t in candidates), 2),
            "top_candidates": top_candidates,
        },
    }
