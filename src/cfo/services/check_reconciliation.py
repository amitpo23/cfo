"""
Check reconciliation — match written checks to cleared deposits (המחאה).

Tracks checks through their lifecycle:
1. Issued → stored as payment with check_number
2. Deposited → scanned/uploaded with clearing date
3. Cleared → matched to bank statement
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Optional

from sqlalchemy.orm import Session

from ..models import BankTransaction, Payment


class CheckReconciliationService:
    """Manage check clearing and reconciliation."""

    def __init__(self, db: Session, organization_id: int):
        self.db = db
        self.organization_id = organization_id

    def record_check_deposit(
        self,
        check_number: str,
        amount: float,
        payer_name: str,
        deposit_date: date,
        image_base64: Optional[str] = None,
    ) -> dict[str, Any]:
        """Record a check received and deposited (not yet cleared).

        Args:
            check_number: Check/cheque number
            amount: Check amount
            payer_name: Who issued the check
            deposit_date: When deposited to bank
            image_base64: Front/back image (optional)

        Returns:
            Check record metadata
        """
        # Create as special BankTransaction with metadata
        txn = BankTransaction(
            organization_id=self.organization_id,
            source="check_deposit",
            external_id=f"CHK-{check_number}",
            transaction_date=deposit_date,
            description=f"Check from {payer_name} (#{check_number})",
            amount=amount,
            currency="ILS",
            raw_data={
                "check_number": check_number,
                "payer_name": payer_name,
                "image": image_base64,
                "status": "deposited",  # Not yet cleared
                "deposit_date": deposit_date.isoformat(),
            },
        )
        self.db.add(txn)
        self.db.commit()
        self.db.refresh(txn)

        return {
            "id": txn.id,
            "check_number": check_number,
            "amount": amount,
            "payer": payer_name,
            "deposit_date": deposit_date.isoformat(),
            "status": "deposited",
        }

    def match_check_to_clearing(
        self,
        check_txn_id: int,
        bank_statement_txn_id: int,
    ) -> dict[str, Any]:
        """Link a deposited check to its bank clearing (match to actual deposit)."""
        check_txn = (
            self.db.query(BankTransaction)
            .filter(
                BankTransaction.organization_id == self.organization_id,
                BankTransaction.id == check_txn_id,
            )
            .first()
        )
        if not check_txn:
            raise ValueError(f"Check transaction {check_txn_id} not found")

        bank_txn = (
            self.db.query(BankTransaction)
            .filter(
                BankTransaction.organization_id == self.organization_id,
                BankTransaction.id == bank_statement_txn_id,
            )
            .first()
        )
        if not bank_txn:
            raise ValueError(f"Bank transaction {bank_statement_txn_id} not found")

        # Verify amounts match (within tolerance)
        if abs(float(check_txn.amount) - float(bank_txn.amount)) > 0.01:
            raise ValueError("Check and bank amounts do not match")

        # Mark check as cleared
        raw = check_txn.raw_data or {}
        raw["status"] = "cleared"
        raw["cleared_date"] = bank_txn.transaction_date.isoformat()
        raw["bank_txn_id"] = bank_statement_txn_id
        check_txn.raw_data = raw

        # Link both to each other
        check_txn.matched_entity_type = "bank_transaction"
        check_txn.matched_entity_id = bank_statement_txn_id
        check_txn.is_reconciled = True

        self.db.commit()

        return {
            "check_id": check_txn_id,
            "bank_txn_id": bank_statement_txn_id,
            "status": "cleared",
            "cleared_date": bank_txn.transaction_date.isoformat(),
        }

    def list_pending_checks(self, limit: int = 100) -> list[dict[str, Any]]:
        """List checks deposited but not yet cleared."""
        txns = (
            self.db.query(BankTransaction)
            .filter(
                BankTransaction.organization_id == self.organization_id,
                BankTransaction.source == "check_deposit",
                BankTransaction.is_reconciled.is_(False),
            )
            .order_by(BankTransaction.transaction_date.desc())
            .limit(limit)
            .all()
        )
        return [self._serialize(t) for t in txns]

    def get_check_aging(self) -> dict[str, Any]:
        """Report of checks by clearing age (days since deposit)."""
        txns = self.db.query(BankTransaction).filter(
            BankTransaction.organization_id == self.organization_id,
            BankTransaction.source == "check_deposit",
        ).all()

        aging = {
            "0_7_days": {"count": 0, "amount": 0.0},
            "8_14_days": {"count": 0, "amount": 0.0},
            "15_30_days": {"count": 0, "amount": 0.0},
            "30plus_days": {"count": 0, "amount": 0.0},
        }

        for txn in txns:
            if not txn.transaction_date:
                continue
            raw = txn.raw_data or {}
            if raw.get("status") == "cleared":
                continue  # Skip cleared checks

            days_pending = (date.today() - txn.transaction_date).days
            amount = float(txn.amount)

            if days_pending <= 7:
                aging["0_7_days"]["count"] += 1
                aging["0_7_days"]["amount"] += amount
            elif days_pending <= 14:
                aging["8_14_days"]["count"] += 1
                aging["8_14_days"]["amount"] += amount
            elif days_pending <= 30:
                aging["15_30_days"]["count"] += 1
                aging["15_30_days"]["amount"] += amount
            else:
                aging["30plus_days"]["count"] += 1
                aging["30plus_days"]["amount"] += amount

        return aging

    @staticmethod
    def _serialize(txn: BankTransaction) -> dict[str, Any]:
        raw = txn.raw_data or {}
        return {
            "id": txn.id,
            "check_number": raw.get("check_number"),
            "payer": raw.get("payer_name"),
            "amount": float(txn.amount),
            "deposit_date": txn.transaction_date.isoformat() if txn.transaction_date else None,
            "cleared_date": raw.get("cleared_date"),
            "status": raw.get("status", "deposited"),
            "days_pending": (date.today() - txn.transaction_date).days if txn.transaction_date else None,
        }
