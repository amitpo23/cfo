"""
Self-invoice support — internal transactions marked as self-invoices (חשבונית עצמית).

A self-invoice is an internal document created by the company for itself:
- Owner drawings (משיכות בעלים)
- Internal transfers between projects/departments
- Personal expenses reimbursements
- Loan/advance repayments

These bypass normal supplier reconciliation and are tracked separately.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy.orm import Session

from ..models import Expense, Invoice


class SelfInvoiceService:
    """Manage self-invoices and internal transfers."""

    def __init__(self, db: Session, organization_id: int):
        self.db = db
        self.organization_id = organization_id

    def create_self_invoice(
        self,
        self_invoice_type: str,  # "owner_drawing" | "internal_transfer" | "reimbursement" | "loan_repay"
        amount: Decimal,
        vat_amount: Decimal = Decimal("0"),
        date_issued: Optional[date] = None,
        description: str = "",
        reference_number: Optional[str] = None,
    ) -> dict[str, Any]:
        """Create a self-invoice (internal transaction).

        Args:
            self_invoice_type: Type of self-invoice
            amount: Net amount (before VAT)
            vat_amount: VAT amount (if applicable)
            date_issued: Issue date (default today)
            description: Purpose/description
            reference_number: Optional reference (check#, transfer#, etc)

        Returns:
            Created invoice metadata
        """
        valid_types = {"owner_drawing", "internal_transfer", "reimbursement", "loan_repay"}
        if self_invoice_type not in valid_types:
            raise ValueError(f"Invalid self_invoice_type. Must be one of {valid_types}")

        # Self-invoices are stored as Invoice records with special marker
        inv = Invoice(
            organization_id=self.organization_id,
            source="self",  # Marker: this is an internal/self document
            issue_date=date_issued or date.today(),
            total=float(amount + vat_amount),
            balance=0,  # Self-invoices are immediately "paid"
            status="paid",  # Self-invoices don't need payment tracking
            notes=description or f"Self-invoice: {self_invoice_type}",
            raw_data={
                "self_invoice_type": self_invoice_type,
                "net_amount": float(amount),
                "vat_amount": float(vat_amount),
                "reference_number": reference_number,
                "created_at": date.today().isoformat(),
            },
        )
        self.db.add(inv)
        self.db.commit()
        self.db.refresh(inv)

        return {
            "id": inv.id,
            "type": self_invoice_type,
            "amount": float(amount),
            "vat_amount": float(vat_amount),
            "total": float(amount + vat_amount),
            "date": inv.issue_date.isoformat(),
            "status": "created",
        }

    def create_owner_drawing(
        self,
        amount: Decimal,
        description: str = "Owner drawing",
        check_number: Optional[str] = None,
    ) -> dict[str, Any]:
        """Convenience method: owner drawing (משיכה בעלים)."""
        return self.create_self_invoice(
            "owner_drawing",
            amount,
            vat_amount=Decimal("0"),
            description=description,
            reference_number=check_number,
        )

    def create_internal_transfer(
        self,
        amount: Decimal,
        from_account: str,
        to_account: str,
        description: Optional[str] = None,
    ) -> dict[str, Any]:
        """Convenience method: internal transfer between accounts."""
        desc = description or f"Transfer from {from_account} to {to_account}"
        return self.create_self_invoice(
            "internal_transfer",
            amount,
            vat_amount=Decimal("0"),
            description=desc,
            reference_number=f"{from_account}→{to_account}",
        )

    def create_reimbursement(
        self,
        amount: Decimal,
        employee_name: str,
        reason: str,
    ) -> dict[str, Any]:
        """Convenience method: employee reimbursement (החזר הוצאה)."""
        return self.create_self_invoice(
            "reimbursement",
            amount,
            vat_amount=Decimal("0"),
            description=f"Reimbursement to {employee_name}: {reason}",
        )

    def create_loan_repayment(
        self,
        amount: Decimal,
        creditor_name: str,
        loan_description: str,
    ) -> dict[str, Any]:
        """Convenience method: loan repayment (החזר הלוואה)."""
        return self.create_self_invoice(
            "loan_repay",
            amount,
            vat_amount=Decimal("0"),
            description=f"Repayment to {creditor_name}: {loan_description}",
        )

    def list_self_invoices(
        self,
        self_invoice_type: Optional[str] = None,
        from_date: Optional[date] = None,
        to_date: Optional[date] = None,
    ) -> list[dict[str, Any]]:
        """List all self-invoices for the organization."""
        q = self.db.query(Invoice).filter(
            Invoice.organization_id == self.organization_id,
            Invoice.source == "self",
        )

        if self_invoice_type:
            q = q.filter(
                Invoice.raw_data["self_invoice_type"].astext == self_invoice_type
            )
        if from_date:
            q = q.filter(Invoice.issue_date >= from_date)
        if to_date:
            q = q.filter(Invoice.issue_date <= to_date)

        q = q.order_by(Invoice.issue_date.desc())
        return [self._serialize(inv) for inv in q.all()]

    def get_self_invoice_summary(
        self,
        from_date: Optional[date] = None,
        to_date: Optional[date] = None,
    ) -> dict[str, Any]:
        """Summary of self-invoices by type."""
        invoices = self.list_self_invoices(from_date=from_date, to_date=to_date)

        summary = {
            "owner_drawing": {"count": 0, "total": 0.0},
            "internal_transfer": {"count": 0, "total": 0.0},
            "reimbursement": {"count": 0, "total": 0.0},
            "loan_repay": {"count": 0, "total": 0.0},
        }

        for inv in invoices:
            inv_type = inv.get("type")
            if inv_type in summary:
                summary[inv_type]["count"] += 1
                summary[inv_type]["total"] += inv.get("total", 0)

        return summary

    @staticmethod
    def _serialize(inv: Invoice) -> dict[str, Any]:
        raw = inv.raw_data or {}
        return {
            "id": inv.id,
            "type": raw.get("self_invoice_type", "unknown"),
            "amount": raw.get("net_amount", float(inv.total or 0)),
            "vat_amount": raw.get("vat_amount", 0.0),
            "total": float(inv.total or 0),
            "date": inv.issue_date.isoformat() if inv.issue_date else None,
            "description": inv.notes,
            "reference": raw.get("reference_number"),
        }
