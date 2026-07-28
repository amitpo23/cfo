"""Accounts-payable planning backed by persisted bills and payments.

No provider executor is wired here. Returning a synthetic payment reference
would make an unperformed transfer look real, so execution fails closed until
an approved ``IrreversibleActionRequest`` is consumed by a concrete provider
adapter and verified through provider readback.
"""
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy.orm import Session

from ..models import Bill, BillStatus, Payment


class PaymentExecutionUnavailable(RuntimeError):
    """Raised when no real, approval-aware payment adapter is connected."""


def _enum_value(value):
    return value.value if hasattr(value, "value") else value


class PaymentOrchestrationService:
    def __init__(self, db: Session, organization_id: int):
        self.db = db
        self.organization_id = organization_id

    def _bill(self, bill_id: int) -> Bill:
        bill = self.db.query(Bill).filter(
            Bill.id == bill_id,
            Bill.organization_id == self.organization_id,
        ).first()
        if bill is None:
            raise ValueError(f"Bill {bill_id} not found")
        return bill

    def suggest_payments(
        self,
        urgency: str = "normal",
        max_amount: Optional[Decimal] = None,
    ) -> dict[str, Any]:
        if urgency not in {"urgent", "normal", "all"}:
            raise ValueError("urgency must be urgent, normal, or all")
        if max_amount is not None and max_amount < 0:
            raise ValueError("max_amount cannot be negative")

        today = date.today()
        horizon = today if urgency == "urgent" else today + timedelta(days=7)
        query = self.db.query(Bill).filter(
            Bill.organization_id == self.organization_id,
            Bill.status.in_([
                BillStatus.RECEIVED,
                BillStatus.APPROVED,
                BillStatus.PARTIALLY_PAID,
                BillStatus.OVERDUE,
            ]),
        )
        bills = query.order_by(Bill.due_date.asc(), Bill.id.asc()).all()

        suggested: list[dict[str, Any]] = []
        total = Decimal("0")
        excluded_missing_amount = 0
        for bill in bills:
            due_now = bill.due_date is not None and bill.due_date <= horizon
            if urgency != "all" and not (due_now or bool(bill.is_critical)):
                continue
            if bill.balance is None:
                excluded_missing_amount += 1
                continue
            amount = Decimal(bill.balance)
            if amount <= 0:
                continue
            if max_amount is not None and total + amount > max_amount:
                continue

            suggested.append({
                "bill_id": bill.id,
                "bill_number": bill.bill_number,
                "vendor": bill.vendor.name if bill.vendor else None,
                "due_date": bill.due_date.isoformat() if bill.due_date else None,
                "amount": float(amount),
                "currency": bill.currency,
                "is_critical": bool(bill.is_critical),
                "can_delay": bool(bill.can_delay),
                "source": bill.source,
            })
            total += amount

        return {
            "suggested": suggested,
            "total_amount": float(total),
            "currency_note": "Amounts retain each bill currency; total is only comparable when currencies match.",
            "excluded_missing_amount": excluded_missing_amount,
            "as_of": today.isoformat(),
            "urgency": urgency,
        }

    def execute_payment(
        self,
        bill_id: int,
        method: str,
        amount: Optional[Decimal] = None,
        scheduled_date: Optional[date] = None,
    ) -> dict[str, Any]:
        raise PaymentExecutionUnavailable(
            "payment execution is not wired to an approved provider adapter; "
            "create and approve an irreversible action request first",
        )

    def get_payment_status(self, bill_id: int) -> dict[str, Any]:
        bill = self._bill(bill_id)
        payments = self.db.query(Payment).filter(
            Payment.organization_id == self.organization_id,
            Payment.bill_id == bill.id,
        ).order_by(Payment.payment_date.asc(), Payment.id.asc()).all()

        return {
            "bill_id": bill.id,
            "bill_number": bill.bill_number,
            "vendor": bill.vendor.name if bill.vendor else None,
            "currency": bill.currency,
            "original_amount": (
                float(bill.total) if bill.total is not None else None
            ),
            "total_paid": (
                float(bill.paid_amount) if bill.paid_amount is not None else None
            ),
            "remaining_balance": (
                float(bill.balance) if bill.balance is not None else None
            ),
            "status": _enum_value(bill.status),
            "source": bill.source,
            "payments": [
                {
                    "id": payment.id,
                    "payment_date": payment.payment_date.isoformat(),
                    "amount": float(payment.amount),
                    "currency": payment.currency,
                    "method": payment.method,
                    "reference": payment.reference,
                    "source": payment.source,
                }
                for payment in payments
            ],
        }
