"""
Manual bank reconciliation — user-driven match override and feedback loop.

Allows users to manually match/unmatch bank transactions to documents when
auto-matching fails or is incorrect. Also enables learning: user corrections
feed back into classifier confidence and pattern memory.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy.orm import Session

from ..models import BankTransaction, Invoice, Bill, Expense


class ManualReconciliationService:
    def __init__(self, db: Session, organization_id: int):
        self.db = db
        self.organization_id = organization_id

    def match_transaction(
        self,
        bank_txn_id: int,
        entity_type: str,  # "invoice" | "bill" | "expense"
        entity_id: int,
    ) -> dict[str, Any]:
        """Manually match a bank transaction to a document."""
        if entity_type not in ("invoice", "bill", "expense"):
            raise ValueError(f"Invalid entity_type: {entity_type}")

        txn = self._load_transaction(bank_txn_id)
        if not txn:
            raise ValueError(f"Bank transaction {bank_txn_id} not found")

        # Validate entity exists
        entity = self._load_entity(entity_type, entity_id)
        if not entity:
            raise ValueError(f"{entity_type} {entity_id} not found")

        # Check amount tolerance (warn if mismatch but allow override)
        entity_amount = float(getattr(entity, "total", 0) or getattr(entity, "amount", 0) or 0)
        txn_amount = abs(float(txn.amount))
        amount_mismatch = abs(txn_amount - entity_amount) > max(0.02 * entity_amount, 0.01)

        # Perform match
        txn.matched_entity_type = entity_type
        txn.matched_entity_id = entity_id
        txn.is_reconciled = True
        # Reset dispatch status for manual matches (will need re-dispatch if configured)
        txn.reconciliation_dispatch_status = "not_sent"
        txn.reconciliation_error = None
        self.db.commit()

        return {
            "bank_txn_id": bank_txn_id,
            "matched_entity_type": entity_type,
            "matched_entity_id": entity_id,
            "amount_mismatch": amount_mismatch,
            "status": "matched",
        }

    def unmatch_transaction(self, bank_txn_id: int) -> dict[str, Any]:
        """Manually unmatch a bank transaction (revert to unreconciled)."""
        txn = self._load_transaction(bank_txn_id)
        if not txn:
            raise ValueError(f"Bank transaction {bank_txn_id} not found")

        txn.matched_entity_type = None
        txn.matched_entity_id = None
        txn.is_reconciled = False
        txn.reconciliation_dispatch_status = "not_sent"
        txn.reconciliation_error = None
        self.db.commit()

        return {
            "bank_txn_id": bank_txn_id,
            "status": "unmatched",
        }

    def record_classifier_feedback(
        self,
        entity_id: int,
        entity_type: str,
        corrected_category: str,
        feedback_text: Optional[str] = None,
    ) -> dict[str, Any]:
        """Record classifier feedback when user corrects an auto-classified expense.
        
        This feeds learning: classifier should increase confidence for this supplier×category
        and decrease for previous guess.
        """
        if entity_type != "expense":
            raise ValueError("Feedback only supported for expenses")

        exp = (
            self.db.query(Expense)
            .filter(
                Expense.organization_id == self.organization_id,
                Expense.id == entity_id,
            )
            .first()
        )
        if not exp:
            raise ValueError(f"Expense {entity_id} not found")

        old_category = exp.category
        exp.category = corrected_category

        # Store feedback metadata (for learning later)
        if not exp.classifier_feedback:
            exp.classifier_feedback = []
        exp.classifier_feedback.append({
            "timestamp": datetime.utcnow().isoformat(),
            "old_category": old_category,
            "new_category": corrected_category,
            "supplier": exp.supplier_name,
            "feedback_text": feedback_text,
        })

        self.db.commit()
        return {
            "expense_id": entity_id,
            "old_category": old_category,
            "new_category": corrected_category,
            "status": "feedback_recorded",
        }

    def list_unmatched_transactions(self, limit: int = 100) -> list[dict[str, Any]]:
        """List unmatched bank transactions for manual review."""
        txns = (
            self.db.query(BankTransaction)
            .filter(
                BankTransaction.organization_id == self.organization_id,
                BankTransaction.is_reconciled.is_(False),
            )
            .order_by(BankTransaction.transaction_date.desc())
            .limit(limit)
            .all()
        )
        return [
            {
                "id": t.id,
                "date": t.transaction_date.isoformat() if t.transaction_date else None,
                "description": t.description,
                "amount": float(t.amount),
                "currency": t.currency,
            }
            for t in txns
        ]

    def suggest_matches(self, bank_txn_id: int, limit: int = 5) -> list[dict[str, Any]]:
        """Suggest potential matches for a transaction (top N candidates by score)."""
        from .bank_reconciliation import BankTxnLite, DocLite, _score

        txn = self._load_transaction(bank_txn_id)
        if not txn or not txn.transaction_date:
            return []

        # Reuse bank_reconciliation scoring
        txn_lite = BankTxnLite(
            id=txn.id,
            amount=float(txn.amount),
            date=txn.transaction_date,
            description=txn.description or "",
        )

        pool = invoices + bills + expenses
        candidates = []

        for doc_type, doc_list in [("invoice", invoices), ("bill", bills), ("expense", expenses)]:
            for doc in doc_list:
                score = _score(txn_lite, doc, amount_tol=0.02, date_window=7)
                if score and score >= 0.3:  # Lower threshold for suggestions
                    candidates.append({
                        "entity_type": doc_type,
                        "entity_id": doc.id,
                        "score": round(score, 3),
                        "amount": doc.amount,
                        "date": doc.date.isoformat() if doc.date else None,
                        "name": doc.name,
                    })

        candidates.sort(key=lambda c: c["score"], reverse=True)
        return candidates[:limit]

    # ---------- helpers ----------

    def _load_transaction(self, txn_id: int) -> Optional[BankTransaction]:
        return (
            self.db.query(BankTransaction)
            .filter(
                BankTransaction.organization_id == self.organization_id,
                BankTransaction.id == txn_id,
            )
            .first()
        )

    def _load_entity(self, entity_type: str, entity_id: int):
        model_by_type = {
            "invoice": Invoice,
            "bill": Bill,
            "expense": Expense,
        }
        model = model_by_type.get(entity_type)
        if not model:
            return None
        return (
            self.db.query(model)
            .filter(
                model.organization_id == self.organization_id,
                model.id == entity_id,
            )
            .first()
        )
