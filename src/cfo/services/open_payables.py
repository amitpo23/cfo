"""Open supplier bills after a confirmed settlement.

A tax invoice stays on ``Bill`` with its original balance when the bank match
or the journal does not rewrite that column. The open list reads the links
that already exist: a reconciled bank row matched to the bill or to its
payment, an accounting ``Payment.bill_id``, or a journal entry that names the
bill. The same settlement is often stored twice, so the cover is the largest
of those readings, not their sum.
"""
from __future__ import annotations

from decimal import Decimal

_CLOSED = frozenset({"draft", "void", "paid"})


def _d(value) -> Decimal:
    try:
        return Decimal(str(value or 0))
    except Exception:
        return Decimal("0")


def _status(bill) -> str:
    return str(getattr(getattr(bill, "status", None), "value", bill.status) or "").lower()


def remaining_of(bill, cover: dict[int, Decimal]) -> Decimal | None:
    """Unpaid amount still to show. ``None`` means the bill has left the open list."""
    if _status(bill) in _CLOSED:
        return None
    total = _d(getattr(bill, "total", None))
    paid = _d(getattr(bill, "paid_amount", None))
    balance = _d(getattr(bill, "balance", None))
    if total <= 0:
        total = balance + paid
    covered = max(paid, cover.get(bill.id, Decimal("0")))
    remaining = total - covered
    if balance > 0 and balance < remaining:
        remaining = balance
    if remaining <= Decimal("0.01"):
        return None
    return remaining.quantize(Decimal("0.01"))


def confirmed_cover(db, organization_id: int) -> dict[int, Decimal]:
    """Settled amount per bill id, from links already stored. No provider call."""
    from ..models import BankTransaction, Bill, JournalEntry, Payment
    from .payment_evidence import accounting_payment_parts, is_accounting_payment

    payment_sum: dict[int, Decimal] = {}
    payments = db.query(Payment).filter(
        Payment.organization_id == organization_id,
        Payment.bill_id.isnot(None),
    ).all()
    payments_by_id = {row.id: row for row in payments}
    for pay in payments:
        raw = pay.raw_data or {}
        if raw.get("source_entity_type") == "billing_payment":
            continue
        if not is_accounting_payment(pay):
            continue
        amount = sum((_d(part.amount) for part in accounting_payment_parts(pay)), Decimal("0"))
        if amount > 0:
            payment_sum[pay.bill_id] = payment_sum.get(pay.bill_id, Decimal("0")) + amount

    bank_direct: dict[int, Decimal] = {}
    bank_via: dict[int, Decimal] = {}
    banks = db.query(BankTransaction).filter(
        BankTransaction.organization_id == organization_id,
        BankTransaction.is_reconciled.is_(True),
        BankTransaction.superseded_by_id.is_(None),
        BankTransaction.matched_entity_type.in_(("bill", "payment")),
        BankTransaction.matched_entity_id.isnot(None),
    ).all()
    for row in banks:
        if row.is_provisional:
            continue
        amount = abs(_d(row.amount))
        if amount <= 0:
            continue
        if row.matched_entity_type == "bill":
            bank_direct[row.matched_entity_id] = bank_direct.get(row.matched_entity_id, Decimal("0")) + amount
            continue
        pay = payments_by_id.get(row.matched_entity_id)
        if pay is None or pay.organization_id != organization_id or not pay.bill_id:
            continue
        bank_via[pay.bill_id] = bank_via.get(pay.bill_id, Decimal("0")) + amount

    journal_sum = _journal_cover(db, organization_id)
    cover: dict[int, Decimal] = {}
    for bill_id in set(payment_sum) | set(bank_direct) | set(bank_via) | set(journal_sum):
        cash = payment_sum.get(bill_id, Decimal("0"))
        direct = bank_direct.get(bill_id, Decimal("0"))
        via = bank_via.get(bill_id, Decimal("0"))
        if cash <= 0:
            cash = direct if direct >= via else via
        elif direct > cash:
            cash = direct
        books = journal_sum.get(bill_id, Decimal("0"))
        if books > cash:
            cash = books
        if cash > 0:
            cover[bill_id] = cash
    return cover


def _entry_credit(entry) -> Decimal:
    credit = Decimal("0")
    for line in entry.lines or []:
        if isinstance(line, dict):
            credit += _d(line.get("credit"))
    return credit


def _journal_cover(db, organization_id: int) -> dict[int, Decimal]:
    from ..models import Bill, JournalEntry

    bills = db.query(Bill).filter(Bill.organization_id == organization_id).all()
    known = {bill.id: bill for bill in bills}
    by_external: dict[str, list[int]] = {}
    number_counts: dict[str, int] = {}
    for bill in bills:
        if bill.external_id:
            by_external.setdefault(str(bill.external_id), []).append(bill.id)
        number = (bill.bill_number or "").strip()
        if number:
            number_counts[number] = number_counts.get(number, 0) + 1
    unique_numbers = {
        (bill.bill_number or "").strip(): bill.id
        for bill in bills
        if (bill.bill_number or "").strip() and number_counts[(bill.bill_number or "").strip()] == 1
    }
    cover: dict[int, Decimal] = {}
    entries = db.query(JournalEntry).filter(JournalEntry.organization_id == organization_id).all()
    for entry in entries:
        raw = entry.raw_data or {}
        targets: set[int] = set()
        named = raw.get("bill_id", raw.get("settles_bill_id"))
        if isinstance(named, str) and named.isdigit():
            named = int(named)
        if isinstance(named, int) and named in known:
            targets.add(named)
        external = str(raw.get("document_external_id") or raw.get("document_id") or "").strip()
        if external and len(by_external.get(external, [])) == 1:
            targets.add(by_external[external][0])
        reference = str(raw.get("reference") or "").strip()
        if reference and reference in unique_numbers:
            targets.add(unique_numbers[reference])
        for line in entry.lines or []:
            if isinstance(line, dict) and line.get("bill_id") in known:
                targets.add(line["bill_id"])
        if len(targets) != 1:
            continue
        bill_id = next(iter(targets))
        credit = _entry_credit(entry)
        if credit <= 0 and (raw.get("bill_id") is not None or raw.get("settles_bill_id") is not None):
            bill = known[bill_id]
            credit = _d(bill.total) or _d(bill.balance)
        if credit <= 0:
            continue
        cover[bill_id] = cover.get(bill_id, Decimal("0")) + credit
    return cover
