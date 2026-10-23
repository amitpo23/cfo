"""Which Open Finance bank rows are money that actually moved.

The bank sends most movements twice: first as ``PENDING`` and then, a day or
two later, as ``BOOKED``, often with a different description. It also sends
"חיובים עתידיים" rows: a PENDING forecast of next month's card charge that is
never booked as such (the real charge arrives as its own BOOKED row).

Rules used by every cash-flow total (``cashflow_selection``) and by /d/:

* An Open Finance row counts only when ``raw_data['status'] == 'BOOKED'``.
* PENDING rows are reported separately and never added to the totals.
  "חיובים עתידיים" PENDING rows are left out of that list too.
* A row on a card account (``raw_account_type == 'CARD'``) or with
  ``raw_data['type'] == 'CARD'`` never enters cash flow. The checking account
  already carries the monthly card charge; card rows are only a merchant
  breakdown of that charge.
* Rows from other sources (reviewed local import, manual) are unchanged.

This module reads rows only. It does not call any provider.
"""
from __future__ import annotations

from collections import OrderedDict
from datetime import date, timedelta
from decimal import Decimal

OPEN_FINANCE = "open_finance"
BOOKED = "BOOKED"
PENDING = "PENDING"
CARD = "CARD"
FUTURE_CARD_CHARGE_PREFIX = "חיובים עתידיים"
# A BOOKED row supersedes a PENDING row with the same entryReference and amount
# when the two dates are this close. Loan repayments reuse one reference every
# month, so the reference alone is not enough.
SUPERSEDE_MAX_DAYS = 5


def raw(row) -> dict:
    data = getattr(row, "raw_data", None)
    return data if isinstance(data, dict) else {}


def bank_status(row) -> str | None:
    value = raw(row).get("status")
    if value is None:
        return None
    text = str(value).strip().upper()
    return text or None


def entry_reference(row) -> str | None:
    value = raw(row).get("entryReference")
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def is_open_finance(row) -> bool:
    return getattr(row, "source", None) == OPEN_FINANCE


def is_future_card_charge(row) -> bool:
    description = (getattr(row, "description", None) or "").strip()
    return description.startswith(FUTURE_CARD_CHARGE_PREFIX)


def is_card_account(account) -> bool:
    if account is None:
        return False
    return str(getattr(account, "raw_account_type", "") or "").strip().upper() == CARD


def is_card_row(row, card_account_ids: set[int] | frozenset = frozenset()) -> bool:
    if getattr(row, "account_id", None) in card_account_ids:
        return True
    return str(raw(row).get("type") or "").strip().upper() == CARD


def card_account_ids(db, organization_id: int) -> set[int]:
    from ..models import Account
    from .read_memo import remember

    def load() -> frozenset[int]:
        rows = (
            db.query(Account.id, Account.raw_account_type)
            .filter(Account.organization_id == organization_id)
            .all()
        )
        return frozenset(aid for aid, raw_type in rows if str(raw_type or "").strip().upper() == CARD)

    return set(remember(db, ("card_account_ids", organization_id), load))


def counts_in_cash_flow(row, card_ids: set[int] | frozenset = frozenset()) -> bool:
    """True when the row is money that moved in a cash account."""
    if is_card_row(row, card_ids):
        return False
    if not is_open_finance(row):
        return True
    if getattr(row, "superseded_by_id", None) is not None and bank_status(row) == PENDING:
        return False
    return bank_status(row) == BOOKED


def is_reported_pending(row, card_ids: set[int] | frozenset = frozenset()) -> bool:
    """PENDING checking rows shown next to the totals, not inside them."""
    if not is_open_finance(row) or is_card_row(row, card_ids):
        return False
    if bank_status(row) != PENDING:
        return False
    if getattr(row, "superseded_by_id", None) is not None:
        return False
    return not is_future_card_charge(row)


def _money(value) -> float:
    return float(Decimal(str(value or 0)).quantize(Decimal("0.01")))


def pending_summary(db, organization_id: int, start: date, end: date) -> dict:
    """PENDING rows per month for display. Never part of any total."""
    from .bank_coverage import window_rows

    card_ids = card_account_ids(db, organization_id)
    rows = [row for row in window_rows(db, organization_id, start, end) if row.source == OPEN_FINANCE]
    months: "OrderedDict[str, dict]" = OrderedDict()
    future = 0
    count = 0
    for row in rows:
        if is_card_row(row, card_ids) or bank_status(row) != PENDING:
            continue
        if row.superseded_by_id is not None:
            continue
        if is_future_card_charge(row):
            future += 1
            continue
        count += 1
        key = row.transaction_date.strftime("%Y-%m")
        bucket = months.setdefault(key, {"month": key, "inflows": 0.0, "outflows": 0.0, "count": 0})
        amount = _money(row.amount)
        if amount > 0:
            bucket["inflows"] = round(bucket["inflows"] + amount, 2)
        elif amount < 0:
            bucket["outflows"] = round(bucket["outflows"] - amount, 2)
        bucket["count"] += 1
    return {
        "count": count,
        "months": list(months.values()),
        "excluded_future_card_charges": future,
        "message": (
            f"{count} תנועות ממתינות (PENDING) מוצגות בנפרד ואינן נכללות בסכומים."
            if count else None
        ),
    }


def card_breakdown(db, organization_id: int, start: date, end: date, *, top: int = 15) -> dict:
    """Merchant breakdown of card accounts. Detail only: never a cash-flow total."""
    from .bank_coverage import window_rows

    card_ids = card_account_ids(db, organization_id)
    months: "OrderedDict[str, dict]" = OrderedDict()
    for row in window_rows(db, organization_id, start, end):
        if row.source != OPEN_FINANCE:
            continue
        if not is_card_row(row, card_ids) or bank_status(row) != BOOKED:
            continue
        key = row.transaction_date.strftime("%Y-%m")
        bucket = months.setdefault(key, {"month": key, "total": 0.0, "merchants": {}})
        amount = -_money(row.amount)  # card purchases are negative on the card account
        merchant = (
            str(raw(row).get("merchantName") or "").strip()
            or (row.description or "").strip()
            or "לא ידוע"
        )
        bucket["total"] = round(bucket["total"] + amount, 2)
        bucket["merchants"][merchant] = round(bucket["merchants"].get(merchant, 0.0) + amount, 2)
    out = []
    for bucket in months.values():
        ranked = sorted(bucket["merchants"].items(), key=lambda kv: -abs(kv[1]))
        shown = [{"merchant": name, "amount": amount} for name, amount in ranked[:top]]
        rest = round(sum(amount for _, amount in ranked[top:]), 2)
        if ranked[top:]:
            shown.append({"merchant": "אחר", "amount": rest})
        out.append({"month": bucket["month"], "total": bucket["total"], "merchants": shown})
    return {
        "role": "detail",
        "months": out,
        "message": (
            "פירוט רכישות בכרטיסי האשראי לפי בית עסק. החיוב החודשי כבר נספר בתזרים העו״ש, "
            "ולכן הסכומים כאן אינם מתווספים לתזרים."
        ),
    }


def supersede_pending(db, booked_row) -> int:
    """Point PENDING twins of a BOOKED row at it. Returns how many were marked.

    Twins share organization, account, entryReference and amount, and are at
    most ``SUPERSEDE_MAX_DAYS`` apart. Each PENDING row is matched at most once.
    Called by the Open Finance sync when a BOOKED row is created or updated.
    """
    from ..models import BankTransaction

    if bank_status(booked_row) != BOOKED or booked_row.id is None:
        return 0
    reference = entry_reference(booked_row)
    if not reference or booked_row.transaction_date is None:
        return 0
    lo = booked_row.transaction_date - timedelta(days=SUPERSEDE_MAX_DAYS)
    hi = booked_row.transaction_date + timedelta(days=SUPERSEDE_MAX_DAYS)
    candidates = (
        db.query(BankTransaction)
        .filter(
            BankTransaction.organization_id == booked_row.organization_id,
            BankTransaction.source == OPEN_FINANCE,
            BankTransaction.id != booked_row.id,
            BankTransaction.superseded_by_id.is_(None),
            BankTransaction.transaction_date >= lo,
            BankTransaction.transaction_date <= hi,
        )
        .all()
    )
    already = (
        db.query(BankTransaction.id)
        .filter(BankTransaction.superseded_by_id == booked_row.id)
        .first()
    )
    if already is not None:
        return 0
    target = _money(booked_row.amount)
    for row in sorted(candidates, key=lambda r: (abs((r.transaction_date - booked_row.transaction_date).days), r.id)):
        if bank_status(row) != PENDING or row.superseded_by_id is not None:
            continue
        if booked_row.account_id is not None and row.account_id not in (None, booked_row.account_id):
            continue
        if entry_reference(row) != reference or _money(row.amount) != target:
            continue
        row.superseded_by_id = booked_row.id
        db.flush()
        return 1
    return 0


def supersede_by_booked_twin(db, pending_row) -> int:
    """A PENDING row that arrives after its BOOKED twin is marked at once."""
    from ..models import BankTransaction

    if bank_status(pending_row) != PENDING or pending_row.superseded_by_id is not None:
        return 0
    reference = entry_reference(pending_row)
    if not reference or pending_row.transaction_date is None:
        return 0
    lo = pending_row.transaction_date - timedelta(days=SUPERSEDE_MAX_DAYS)
    hi = pending_row.transaction_date + timedelta(days=SUPERSEDE_MAX_DAYS)
    rows = (
        db.query(BankTransaction)
        .filter(
            BankTransaction.organization_id == pending_row.organization_id,
            BankTransaction.source == OPEN_FINANCE,
            BankTransaction.transaction_date >= lo,
            BankTransaction.transaction_date <= hi,
        )
        .all()
    )
    taken = {r.superseded_by_id for r in rows if r.superseded_by_id is not None}
    target = _money(pending_row.amount)
    for row in sorted(rows, key=lambda r: (abs((r.transaction_date - pending_row.transaction_date).days), r.id)):
        if row is pending_row or row.id in taken or bank_status(row) != BOOKED:
            continue
        if pending_row.account_id is not None and row.account_id not in (None, pending_row.account_id):
            continue
        if entry_reference(row) != reference or _money(row.amount) != target:
            continue
        pending_row.superseded_by_id = row.id
        db.flush()
        return 1
    return 0


def balance_reconciliation(db, organization_id: int, account_id: int, start: date, end: date) -> list[dict]:
    """Per month: Σ BOOKED amounts vs the change in the bank's end-of-day balance.

    The bank reports ``balancePerEndDay`` on each BOOKED row. Opening is the
    last reported balance before the month, closing the last one inside it.
    ``diff`` is ``opening + booked_net - closing`` and is 0 when the BOOKED rows
    are complete and nothing is counted twice. Months without a reported
    balance on both sides return ``diff = None``.
    """
    from ..models import BankTransaction

    rows = (
        db.query(BankTransaction)
        .filter(
            BankTransaction.organization_id == organization_id,
            BankTransaction.account_id == account_id,
            BankTransaction.source == OPEN_FINANCE,
            BankTransaction.transaction_date <= end,
        )
        .order_by(BankTransaction.transaction_date, BankTransaction.id)
        .all()
    )
    booked = [r for r in rows if bank_status(r) == BOOKED]
    eod: dict[date, float] = {}
    for r in booked:
        value = raw(r).get("balancePerEndDay")
        if value is not None:
            try:
                eod[r.transaction_date] = float(value)
            except (TypeError, ValueError):
                continue
    out = []
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        first = date(year, month, 1)
        nxt = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
        last = min(nxt - timedelta(days=1), end)
        before = [d for d in eod if d < first]
        inside = [d for d in eod if first <= d <= last]
        net = round(sum(float(r.amount or 0) for r in booked if first <= r.transaction_date <= last), 2)
        opening = eod[max(before)] if before else None
        closing = eod[max(inside)] if inside else None
        diff = None
        if opening is not None and closing is not None:
            diff = round(opening + net - closing, 2)
        out.append({"month": f"{year}-{month:02d}", "opening": opening, "booked_net": net,
                    "closing": closing, "diff": diff})
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return out
