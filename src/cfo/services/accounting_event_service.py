"""Read-only accounting event plane.

This layer normalizes existing Rezef records into one explainable stream without
becoming a new source of truth. SUMIT / Open Finance / Rezef tables remain the
owned data; these events are derived projections for command-center workflows,
reconciliation workbenches, month-close checks and CFO explanations.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Optional

from sqlalchemy.orm import Session

from ..models import BankTransaction, Bill, Expense, Invoice, Payment

DISCLAIMER = "אירועים נגזרים מנתוני רצף והאינטגרציות — לא ספר רשמי עצמאי."


@dataclass
class AccountingEvent:
    event_id: str
    organization_id: int
    event_type: str
    event_date: Optional[date]
    source: str
    source_ref: str
    status: str
    amount: float
    currency: str
    title: str
    counterparty: Optional[str] = None
    evidence: Optional[dict[str, Any]] = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "organization_id": self.organization_id,
            "event_type": self.event_type,
            "event_date": self.event_date.isoformat() if self.event_date else None,
            "source": self.source,
            "source_ref": self.source_ref,
            "status": self.status,
            "amount": round(self.amount, 2),
            "currency": self.currency,
            "title": self.title,
            "counterparty": self.counterparty,
            "evidence": self.evidence or {},
            "derived": True,
        }


def _amount(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _status(value: Any) -> str:
    if hasattr(value, "value"):
        return str(value.value)
    return str(value or "unknown")


def _date_from_datetime(value: Optional[datetime]) -> Optional[date]:
    if value is None:
        return None
    return value.date()


def _in_period(value: Optional[date], start: Optional[date], end: Optional[date]) -> bool:
    if value is None:
        return True
    if start is not None and value < start:
        return False
    if end is not None and value > end:
        return False
    return True


def build_events(
    db: Session,
    organization_id: int,
    *,
    start: Optional[date] = None,
    end: Optional[date] = None,
    event_type: Optional[str] = None,
    limit: int = 500,
) -> dict[str, Any]:
    events: list[AccountingEvent] = []

    if event_type in (None, "invoice"):
        for inv in db.query(Invoice).filter(Invoice.organization_id == organization_id).all():
            event_date = inv.issue_date or inv.due_date or _date_from_datetime(inv.created_at)
            if not _in_period(event_date, start, end):
                continue
            events.append(AccountingEvent(
                event_id=f"invoice:{inv.id}",
                organization_id=organization_id,
                event_type="invoice",
                event_date=event_date,
                source=inv.source or "manual",
                source_ref=f"invoice:{inv.id}",
                status=_status(inv.status),
                amount=_amount(inv.total),
                currency=inv.currency or "ILS",
                title=f"חשבונית {inv.invoice_number or inv.id}",
                counterparty=inv.contact.name if inv.contact else None,
                evidence={
                    "invoice_id": inv.id,
                    "external_id": inv.external_id,
                    "balance": _amount(inv.balance),
                    "allocation_number": inv.allocation_number,
                },
            ))

    if event_type in (None, "bill"):
        for bill in db.query(Bill).filter(Bill.organization_id == organization_id).all():
            event_date = bill.issue_date or bill.due_date or _date_from_datetime(bill.created_at)
            if not _in_period(event_date, start, end):
                continue
            events.append(AccountingEvent(
                event_id=f"bill:{bill.id}",
                organization_id=organization_id,
                event_type="bill",
                event_date=event_date,
                source=bill.source or "manual",
                source_ref=f"bill:{bill.id}",
                status=_status(bill.status),
                amount=_amount(bill.total),
                currency=bill.currency or "ILS",
                title=f"חשבון ספק {bill.bill_number or bill.id}",
                counterparty=bill.vendor.name if bill.vendor else None,
                evidence={
                    "bill_id": bill.id,
                    "external_id": bill.external_id,
                    "balance": _amount(bill.balance),
                    "is_critical": bool(bill.is_critical),
                    "can_delay": bool(bill.can_delay),
                },
            ))

    if event_type in (None, "payment"):
        for payment in db.query(Payment).filter(Payment.organization_id == organization_id).all():
            if not _in_period(payment.payment_date, start, end):
                continue
            direction = "customer_receipt" if payment.invoice_id else "supplier_payment" if payment.bill_id else "unlinked_payment"
            events.append(AccountingEvent(
                event_id=f"payment:{payment.id}",
                organization_id=organization_id,
                event_type="payment",
                event_date=payment.payment_date,
                source=payment.source or "manual",
                source_ref=f"payment:{payment.id}",
                status=direction,
                amount=_amount(payment.amount),
                currency=payment.currency or "ILS",
                title="תקבול/תשלום",
                evidence={
                    "payment_id": payment.id,
                    "invoice_id": payment.invoice_id,
                    "bill_id": payment.bill_id,
                    "method": payment.method,
                    "reference": payment.reference,
                },
            ))

    if event_type in (None, "expense"):
        for expense in db.query(Expense).filter(Expense.organization_id == organization_id).all():
            if not _in_period(expense.expense_date, start, end):
                continue
            events.append(AccountingEvent(
                event_id=f"expense:{expense.id}",
                organization_id=organization_id,
                event_type="expense",
                event_date=expense.expense_date,
                source=expense.source or "manual",
                source_ref=f"expense:{expense.id}",
                status=expense.status or "pending",
                amount=_amount(expense.total or (_amount(expense.amount) + _amount(expense.vat_amount))),
                currency="ILS",
                title=f"הוצאה — {expense.supplier_name}",
                counterparty=expense.supplier_name,
                evidence={
                    "expense_id": expense.id,
                    "sumit_expense_id": expense.sumit_expense_id,
                    "supplier_tax_id": expense.supplier_tax_id,
                    "category": expense.category,
                    "filing_error": expense.filing_error,
                },
            ))

    if event_type in (None, "bank_transaction"):
        for tx in db.query(BankTransaction).filter(BankTransaction.organization_id == organization_id).all():
            if not _in_period(tx.transaction_date, start, end):
                continue
            events.append(AccountingEvent(
                event_id=f"bank_transaction:{tx.id}",
                organization_id=organization_id,
                event_type="bank_transaction",
                event_date=tx.transaction_date,
                source=tx.source or "manual",
                source_ref=f"bank_transaction:{tx.id}",
                status="reconciled" if tx.is_reconciled else "unreconciled",
                amount=_amount(tx.amount),
                currency=tx.currency or "ILS",
                title=tx.description or f"תנועת בנק {tx.id}",
                evidence={
                    "bank_transaction_id": tx.id,
                    "external_id": tx.external_id,
                    "matched_entity_type": tx.matched_entity_type,
                    "matched_entity_id": tx.matched_entity_id,
                    "dispatch_status": tx.reconciliation_dispatch_status,
                    "dispatch_error": tx.reconciliation_error,
                },
            ))

    events.sort(key=lambda item: (item.event_date or date.min, item.event_id), reverse=True)
    limited = events[:max(min(limit, 1000), 1)]
    by_type: dict[str, int] = {}
    for event in events:
        by_type[event.event_type] = by_type.get(event.event_type, 0) + 1

    return {
        "organization_id": organization_id,
        "derived": True,
        "disclaimer": DISCLAIMER,
        "count": len(limited),
        "total_available": len(events),
        "by_type": by_type,
        "events": [event.as_dict() for event in limited],
    }
