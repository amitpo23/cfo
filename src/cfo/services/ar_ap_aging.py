"""
AP/AR Aging Report — analyze outstanding payables and receivables by age.

Segments invoices/bills by days outstanding:
- Current (0-30 days)
- 31-60 days overdue
- 61-90 days overdue
- 90+ days overdue
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from sqlalchemy.orm import Session

from ..models import Invoice, InvoiceStatus, Bill, BillStatus


class ARAPAgingService:
    """Generate AR (accounts receivable) and AP (accounts payable) aging."""

    def __init__(self, db: Session, organization_id: int):
        self.db = db
        self.organization_id = organization_id

    def ar_aging_report(
        self,
        as_of_date: date = None,
    ) -> dict[str, Any]:
        """Accounts Receivable (AR) aging — outstanding invoices."""
        as_of_date = as_of_date or date.today()

        invoices = (
            self.db.query(Invoice)
            .filter(
                Invoice.organization_id == self.organization_id,
                Invoice.status != InvoiceStatus.PAID,
            )
            .all()
        )

        aging = {
            "current": {"count": 0, "amount": 0.0, "invoices": []},
            "31_60": {"count": 0, "amount": 0.0, "invoices": []},
            "61_90": {"count": 0, "amount": 0.0, "invoices": []},
            "90plus": {"count": 0, "amount": 0.0, "invoices": []},
        }

        total_receivable = 0.0

        for inv in invoices:
            if not inv.due_date:
                continue

            balance = float(inv.balance or 0)
            if balance <= 0:
                continue

            days_overdue = (as_of_date - inv.due_date).days
            total_receivable += balance

            bucket = "current" if days_overdue <= 30 else \
                     "31_60" if days_overdue <= 60 else \
                     "61_90" if days_overdue <= 90 else \
                     "90plus"

            aging[bucket]["count"] += 1
            aging[bucket]["amount"] += balance
            aging[bucket]["invoices"].append({
                "id": inv.id,
                "customer": getattr(getattr(inv, "contact", None), "name", "Unknown"),
                "amount": balance,
                "due_date": inv.due_date.isoformat(),
                "days_overdue": days_overdue,
            })

        # Calculate percentages
        for bucket in aging:
            if total_receivable > 0:
                aging[bucket]["percentage"] = round(
                    (aging[bucket]["amount"] / total_receivable) * 100, 2
                )
            else:
                aging[bucket]["percentage"] = 0.0

        return {
            "as_of_date": as_of_date.isoformat(),
            "total_receivable": round(total_receivable, 2),
            "aging": aging,
        }

    def ap_aging_report(
        self,
        as_of_date: date = None,
    ) -> dict[str, Any]:
        """Accounts Payable (AP) aging — outstanding bills."""
        as_of_date = as_of_date or date.today()

        bills = (
            self.db.query(Bill)
            .filter(
                Bill.organization_id == self.organization_id,
                Bill.status != BillStatus.PAID,
            )
            .all()
        )

        aging = {
            "current": {"count": 0, "amount": 0.0, "bills": []},
            "31_60": {"count": 0, "amount": 0.0, "bills": []},
            "61_90": {"count": 0, "amount": 0.0, "bills": []},
            "90plus": {"count": 0, "amount": 0.0, "bills": []},
        }

        total_payable = 0.0

        for bill in bills:
            if not bill.due_date:
                continue

            balance = float(bill.balance or 0)
            if balance <= 0:
                continue

            days_overdue = (as_of_date - bill.due_date).days
            total_payable += balance

            bucket = "current" if days_overdue <= 30 else \
                     "31_60" if days_overdue <= 60 else \
                     "61_90" if days_overdue <= 90 else \
                     "90plus"

            aging[bucket]["count"] += 1
            aging[bucket]["amount"] += balance
            aging[bucket]["bills"].append({
                "id": bill.id,
                "vendor": getattr(getattr(bill, "vendor", None), "name", "Unknown"),
                "amount": balance,
                "due_date": bill.due_date.isoformat(),
                "days_overdue": days_overdue,
            })

        # Calculate percentages
        for bucket in aging:
            if total_payable > 0:
                aging[bucket]["percentage"] = round(
                    (aging[bucket]["amount"] / total_payable) * 100, 2
                )
            else:
                aging[bucket]["percentage"] = 0.0

        return {
            "as_of_date": as_of_date.isoformat(),
            "total_payable": round(total_payable, 2),
            "aging": aging,
        }

    def ar_ap_summary(self, as_of_date: date = None) -> dict[str, Any]:
        """Combined AR/AP summary."""
        ar = self.ar_aging_report(as_of_date)
        ap = self.ap_aging_report(as_of_date)

        return {
            "as_of_date": (as_of_date or date.today()).isoformat(),
            "accounts_receivable": ar,
            "accounts_payable": ap,
            "net_working_capital": round(
                ar["total_receivable"] - ap["total_payable"], 2
            ),
        }
