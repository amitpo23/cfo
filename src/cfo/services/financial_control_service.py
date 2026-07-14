"""
Unified financial control service.

Combines SUMIT-synced accounting data, bank/Open Finance transactions, budget
tracking, and reconciliation suggestions into one control layer for dashboards
and workflows.
"""
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from difflib import SequenceMatcher
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import (
    Account,
    AccountType,
    BankTransaction,
    Bill,
    Invoice,
    InvoiceStatus,
    Payment,
    Transaction,
    TransactionType,
)


@dataclass
class ReconciliationCandidate:
    entity_type: str
    entity_id: int
    description: str
    amount: float
    date: Optional[str]
    score: float
    reasons: list[str]


@dataclass
class ReconciliationSuggestion:
    bank_transaction_id: int
    transaction_date: str
    description: str
    amount: float
    currency: str
    candidates: list[ReconciliationCandidate]


class FinancialControlService:
    """High-level CFO control layer for monitoring and reconciliation."""

    def __init__(self, db: Session, organization_id: int = 1):
        self.db = db
        self.organization_id = organization_id

    def get_control_overview(
        self,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> dict:
        today = date.today()
        start_date = start_date or date(today.year, today.month, 1)
        end_date = end_date or today

        cash_balance = self._cash_balance()
        income, expenses = self._transaction_totals(start_date, end_date)
        bank_inflow, bank_outflow = self._bank_totals(start_date, end_date)
        overdue_invoices = self._overdue_invoice_total(today)
        upcoming_bills = self._upcoming_bill_total(today)
        unreconciled_count = self._unreconciled_bank_count(start_date, end_date)

        return {
            "period": {
                "from": start_date.isoformat(),
                "to": end_date.isoformat(),
            },
            "cash": {
                "bank_account_balance": float(cash_balance),
                "bank_inflow": float(bank_inflow),
                "bank_outflow": float(bank_outflow),
                "net_bank_flow": float(bank_inflow - bank_outflow),
            },
            "books": {
                "income": float(income),
                "expenses": float(expenses),
                "net_profit": float(income - expenses),
            },
            "control": {
                "unreconciled_bank_transactions": unreconciled_count,
                "overdue_invoices_amount": float(overdue_invoices),
                "upcoming_bills_amount_14d": float(upcoming_bills),
                "reconciliation_health": self._health_score(unreconciled_count),
            },
            "next_actions": self._next_actions(
                unreconciled_count=unreconciled_count,
                overdue_invoices=overdue_invoices,
                upcoming_bills=upcoming_bills,
            ),
        }

    def suggest_bank_reconciliations(
        self,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        limit: int = 50,
        amount_tolerance: float = 1.0,
        date_tolerance_days: int = 7,
    ) -> list[dict]:
        today = date.today()
        start_date = start_date or (today - timedelta(days=60))
        end_date = end_date or today

        bank_transactions = self.db.query(BankTransaction).filter(
            BankTransaction.organization_id == self.organization_id,
            BankTransaction.transaction_date >= start_date,
            BankTransaction.transaction_date <= end_date,
            BankTransaction.is_reconciled == False,  # noqa: E712
        ).order_by(BankTransaction.transaction_date.desc()).limit(limit).all()

        suggestions = []
        for bank_tx in bank_transactions:
            candidates = self._candidate_matches(
                bank_tx,
                amount_tolerance=Decimal(str(amount_tolerance)),
                date_tolerance_days=date_tolerance_days,
            )
            suggestions.append(
                asdict(
                    ReconciliationSuggestion(
                        bank_transaction_id=bank_tx.id,
                        transaction_date=bank_tx.transaction_date.isoformat(),
                        description=bank_tx.description or "",
                        amount=float(bank_tx.amount),
                        currency=bank_tx.currency,
                        candidates=candidates[:5],
                    )
                )
            )
        return suggestions

    def apply_bank_reconciliation(
        self,
        bank_transaction_id: int,
        entity_type: str,
        entity_id: int,
    ) -> dict:
        entity_models = {
            "invoice": Invoice,
            "bill": Bill,
            "payment": Payment,
            "transaction": Transaction,
        }
        if entity_type not in entity_models:
            raise ValueError(f"entity_type must be one of: {', '.join(sorted(entity_models))}")

        bank_tx = self.db.query(BankTransaction).filter(
            BankTransaction.organization_id == self.organization_id,
            BankTransaction.id == bank_transaction_id,
        ).first()
        if not bank_tx:
            raise ValueError("Bank transaction not found")

        model = entity_models[entity_type]
        entity = self.db.query(model).filter(
            model.organization_id == self.organization_id,
            model.id == entity_id,
        ).first()
        if not entity:
            raise ValueError(f"{entity_type} {entity_id} not found")

        bank_tx.matched_entity_type = entity_type
        bank_tx.matched_entity_id = entity_id
        bank_tx.is_reconciled = True
        self.db.commit()
        self.db.refresh(bank_tx)

        return {
            "bank_transaction_id": bank_tx.id,
            "matched_entity_type": bank_tx.matched_entity_type,
            "matched_entity_id": bank_tx.matched_entity_id,
            "is_reconciled": bank_tx.is_reconciled,
        }

    def get_expense_control(
        self,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        limit: int = 12,
    ) -> dict:
        today = date.today()
        start_date = start_date or date(today.year, today.month, 1)
        end_date = end_date or today

        rows = self.db.query(
            Transaction.category,
            func.sum(Transaction.amount).label("total"),
            func.count(Transaction.id).label("count"),
        ).filter(
            Transaction.organization_id == self.organization_id,
            Transaction.transaction_type == TransactionType.EXPENSE,
            Transaction.transaction_date >= datetime.combine(start_date, datetime.min.time()),
            Transaction.transaction_date <= datetime.combine(end_date, datetime.max.time()),
        ).group_by(Transaction.category).order_by(func.sum(Transaction.amount).desc()).limit(limit).all()

        categories = [
            {
                "category": row.category or "uncategorized",
                "amount": float(row.total or 0),
                "transaction_count": row.count,
            }
            for row in rows
        ]

        return {
            "period": {"from": start_date.isoformat(), "to": end_date.isoformat()},
            "total_expenses": sum(item["amount"] for item in categories),
            "categories": categories,
        }

    def _candidate_matches(
        self,
        bank_tx: BankTransaction,
        amount_tolerance: Decimal,
        date_tolerance_days: int,
    ) -> list[ReconciliationCandidate]:
        target_amount = abs(Decimal(bank_tx.amount or 0))
        signed_amount = Decimal(bank_tx.amount or 0)
        tx_date = bank_tx.transaction_date
        window_start = tx_date - timedelta(days=date_tolerance_days)
        window_end = tx_date + timedelta(days=date_tolerance_days)

        candidates: list[ReconciliationCandidate] = []

        if signed_amount > 0:
            invoices = self.db.query(Invoice).filter(
                Invoice.organization_id == self.organization_id,
                Invoice.issue_date <= window_end,
                Invoice.total >= target_amount - amount_tolerance,
                Invoice.total <= target_amount + amount_tolerance,
            ).limit(20).all()
            for invoice in invoices:
                candidates.append(self._score_candidate(
                    bank_tx,
                    "invoice",
                    invoice.id,
                    invoice.invoice_number or "Invoice",
                    Decimal(invoice.total or 0),
                    invoice.issue_date,
                ))

        if signed_amount < 0:
            bills = self.db.query(Bill).filter(
                Bill.organization_id == self.organization_id,
                Bill.issue_date <= window_end,
                Bill.total >= target_amount - amount_tolerance,
                Bill.total <= target_amount + amount_tolerance,
            ).limit(20).all()
            for bill in bills:
                candidates.append(self._score_candidate(
                    bank_tx,
                    "bill",
                    bill.id,
                    bill.bill_number or "Bill",
                    Decimal(bill.total or 0),
                    bill.issue_date,
                ))

        payments = self.db.query(Payment).filter(
            Payment.organization_id == self.organization_id,
            Payment.payment_date >= window_start,
            Payment.payment_date <= window_end,
            Payment.amount >= target_amount - amount_tolerance,
            Payment.amount <= target_amount + amount_tolerance,
        ).limit(20).all()
        for payment in payments:
            candidates.append(self._score_candidate(
                bank_tx,
                "payment",
                payment.id,
                payment.reference or payment.method or "Payment",
                Decimal(payment.amount or 0),
                payment.payment_date,
            ))

        ledger_type = TransactionType.INCOME if signed_amount > 0 else TransactionType.EXPENSE
        ledger_transactions = self.db.query(Transaction).filter(
            Transaction.organization_id == self.organization_id,
            Transaction.transaction_type == ledger_type,
            Transaction.transaction_date >= datetime.combine(window_start, datetime.min.time()),
            Transaction.transaction_date <= datetime.combine(window_end, datetime.max.time()),
            Transaction.amount >= target_amount - amount_tolerance,
            Transaction.amount <= target_amount + amount_tolerance,
        ).limit(20).all()
        for tx in ledger_transactions:
            candidates.append(self._score_candidate(
                bank_tx,
                "transaction",
                tx.id,
                tx.description or tx.category or "Transaction",
                Decimal(tx.amount or 0),
                tx.transaction_date.date(),
            ))

        return sorted(candidates, key=lambda item: item.score, reverse=True)

    def _score_candidate(
        self,
        bank_tx: BankTransaction,
        entity_type: str,
        entity_id: int,
        description: str,
        amount: Decimal,
        match_date: Optional[date],
    ) -> ReconciliationCandidate:
        reasons = []
        score = 0.0

        bank_amount = abs(Decimal(bank_tx.amount or 0))
        amount_delta = abs(bank_amount - abs(amount))
        if amount_delta == 0:
            score += 0.55
            reasons.append("exact_amount")
        elif amount_delta <= Decimal("1.00"):
            score += 0.45
            reasons.append("amount_within_1_ils")

        if match_date:
            days_delta = abs((bank_tx.transaction_date - match_date).days)
            if days_delta == 0:
                score += 0.25
                reasons.append("same_date")
            elif days_delta <= 3:
                score += 0.18
                reasons.append("date_within_3_days")
            elif days_delta <= 7:
                score += 0.10
                reasons.append("date_within_7_days")

        text_score = SequenceMatcher(
            None,
            (bank_tx.description or "").lower(),
            (description or "").lower(),
        ).ratio()
        if text_score >= 0.45:
            score += min(text_score * 0.20, 0.20)
            reasons.append("description_similarity")

        return ReconciliationCandidate(
            entity_type=entity_type,
            entity_id=entity_id,
            description=description,
            amount=float(amount),
            date=match_date.isoformat() if match_date else None,
            score=round(min(score, 1.0), 3),
            reasons=reasons,
        )

    def _cash_balance(self) -> Decimal:
        total = self.db.query(func.sum(Account.balance)).filter(
            Account.organization_id == self.organization_id,
            Account.account_type == AccountType.BANK,
        ).scalar()
        return Decimal(total or 0)

    def _transaction_totals(self, start_date: date, end_date: date) -> tuple[Decimal, Decimal]:
        rows = self.db.query(
            Transaction.transaction_type,
            func.sum(Transaction.amount),
        ).filter(
            Transaction.organization_id == self.organization_id,
            Transaction.transaction_date >= datetime.combine(start_date, datetime.min.time()),
            Transaction.transaction_date <= datetime.combine(end_date, datetime.max.time()),
        ).group_by(Transaction.transaction_type).all()

        income = Decimal("0")
        expenses = Decimal("0")
        for tx_type, total in rows:
            if tx_type == TransactionType.INCOME:
                income = Decimal(total or 0)
            elif tx_type == TransactionType.EXPENSE:
                expenses = Decimal(total or 0)
        return income, expenses

    def _bank_totals(self, start_date: date, end_date: date) -> tuple[Decimal, Decimal]:
        rows = self.db.query(BankTransaction.amount).filter(
            BankTransaction.organization_id == self.organization_id,
            BankTransaction.transaction_date >= start_date,
            BankTransaction.transaction_date <= end_date,
        ).all()
        inflow = sum((Decimal(row.amount) for row in rows if row.amount and row.amount > 0), Decimal("0"))
        outflow = sum((abs(Decimal(row.amount)) for row in rows if row.amount and row.amount < 0), Decimal("0"))
        return inflow, outflow

    def _overdue_invoice_total(self, today: date) -> Decimal:
        # מחריגים טיוטה/מבוטלת — מסמך שאינו סופי אינו חוב אמיתי (ראה vat_utils.invoice_counts).
        total = self.db.query(func.sum(Invoice.balance)).filter(
            Invoice.organization_id == self.organization_id,
            Invoice.due_date < today,
            Invoice.balance > 0,
            Invoice.status.notin_([InvoiceStatus.DRAFT, InvoiceStatus.VOID, InvoiceStatus.CANCELLED]),
        ).scalar()
        return Decimal(total or 0)

    def _upcoming_bill_total(self, today: date) -> Decimal:
        total = self.db.query(func.sum(Bill.balance)).filter(
            Bill.organization_id == self.organization_id,
            Bill.due_date >= today,
            Bill.due_date <= today + timedelta(days=14),
            Bill.balance > 0,
        ).scalar()
        return Decimal(total or 0)

    def _unreconciled_bank_count(self, start_date: date, end_date: date) -> int:
        return self.db.query(BankTransaction).filter(
            BankTransaction.organization_id == self.organization_id,
            BankTransaction.transaction_date >= start_date,
            BankTransaction.transaction_date <= end_date,
            BankTransaction.is_reconciled == False,  # noqa: E712
        ).count()

    @staticmethod
    def _health_score(unreconciled_count: int) -> str:
        if unreconciled_count == 0:
            return "excellent"
        if unreconciled_count <= 10:
            return "good"
        if unreconciled_count <= 50:
            return "needs_attention"
        return "critical"

    @staticmethod
    def _next_actions(
        unreconciled_count: int,
        overdue_invoices: Decimal,
        upcoming_bills: Decimal,
    ) -> list[dict]:
        actions = []
        if unreconciled_count:
            actions.append({
                "type": "reconciliation",
                "priority": "high" if unreconciled_count > 50 else "medium",
                "message": f"Review {unreconciled_count} unreconciled bank transactions",
            })
        if overdue_invoices > 0:
            actions.append({
                "type": "collections",
                "priority": "high",
                "message": f"Collect overdue invoices totaling {float(overdue_invoices):,.2f} ILS",
            })
        if upcoming_bills > 0:
            actions.append({
                "type": "payables",
                "priority": "medium",
                "message": f"Plan upcoming bills totaling {float(upcoming_bills):,.2f} ILS",
            })
        return actions
