"""
CFO Brain service.

Persists internal financial memory, generates actionable insights, and creates
tasks from SUMIT, bank/Open Finance, budget, and reconciliation data.
"""
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..config import settings
from ..models import (
    BankTransaction,
    Budget,
    CfoInsight,
    CfoMemory,
    IntegrationConnection,
    Task,
    TaskStatus,
    Transaction,
    TransactionType,
)
from .financial_control_service import FinancialControlService


class CFOBrainService:
    """Internal CFO reasoning layer backed by persistent database memory."""

    def __init__(self, db: Session, organization_id: int = 1):
        self.db = db
        self.organization_id = organization_id
        self.control = FinancialControlService(db, organization_id)

    def run_analysis(self, create_tasks: bool = True) -> dict:
        """Run a full analysis pass and persist memory + insights."""
        overview = self.control.get_control_overview()
        insights = []

        self._remember("control.overview", "metric", overview, source="financial_control")
        self._remember_connections()

        insights.extend(self._connection_insights())
        insights.extend(self._reconciliation_insights(overview))
        insights.extend(self._collections_insights(overview))
        insights.extend(self._cashflow_insights(overview))
        insights.extend(self._budget_insights())
        insights.extend(self._large_unreconciled_bank_insights())

        persisted = [self._upsert_insight(item) for item in insights]
        tasks_created = 0
        if create_tasks:
            for insight in persisted:
                if insight.severity in {"high", "critical"}:
                    if self._ensure_task_for_insight(insight):
                        tasks_created += 1

        self.db.commit()

        return {
            "organization_id": self.organization_id,
            "analyzed_at": datetime.utcnow().isoformat(),
            "insights_generated": len(persisted),
            "tasks_created": tasks_created,
            "overview": overview,
            "insights": [self._serialize_insight(item) for item in persisted],
        }

    def list_insights(
        self,
        status: str = "active",
        severity: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict]:
        query = self.db.query(CfoInsight).filter(
            CfoInsight.organization_id == self.organization_id,
        )
        if status:
            query = query.filter(CfoInsight.status == status)
        if severity:
            query = query.filter(CfoInsight.severity == severity)

        insights = query.order_by(CfoInsight.updated_at.desc()).limit(limit).all()
        return [self._serialize_insight(item) for item in insights]

    def update_insight_status(self, insight_id: int, status: str) -> dict:
        allowed = {"active", "acknowledged", "resolved"}
        if status not in allowed:
            raise ValueError(f"status must be one of: {', '.join(sorted(allowed))}")

        insight = self.db.query(CfoInsight).filter(
            CfoInsight.organization_id == self.organization_id,
            CfoInsight.id == insight_id,
        ).first()
        if not insight:
            raise ValueError("Insight not found")

        insight.status = status
        insight.updated_at = datetime.utcnow()
        if status == "resolved":
            insight.resolved_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(insight)
        return self._serialize_insight(insight)

    def list_memory(self, memory_type: Optional[str] = None, limit: int = 100) -> list[dict]:
        query = self.db.query(CfoMemory).filter(CfoMemory.organization_id == self.organization_id)
        if memory_type:
            query = query.filter(CfoMemory.memory_type == memory_type)
        rows = query.order_by(CfoMemory.updated_at.desc()).limit(limit).all()
        return [
            {
                "id": row.id,
                "memory_key": row.memory_key,
                "memory_type": row.memory_type,
                "value": row.value,
                "source": row.source,
                "confidence": row.confidence,
                "last_seen_at": row.last_seen_at.isoformat() if row.last_seen_at else None,
                "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            }
            for row in rows
        ]

    def _remember(
        self,
        key: str,
        memory_type: str,
        value: dict,
        source: Optional[str] = None,
        confidence: float = 1.0,
    ) -> CfoMemory:
        existing = self.db.query(CfoMemory).filter(
            CfoMemory.organization_id == self.organization_id,
            CfoMemory.memory_key == key,
        ).first()
        now = datetime.utcnow()
        if existing:
            existing.memory_type = memory_type
            existing.value = value
            existing.source = source
            existing.confidence = confidence
            existing.last_seen_at = now
            existing.updated_at = now
            return existing

        memory = CfoMemory(
            organization_id=self.organization_id,
            memory_key=key,
            memory_type=memory_type,
            value=value,
            source=source,
            confidence=confidence,
            last_seen_at=now,
        )
        self.db.add(memory)
        return memory

    def _remember_connections(self):
        connections = self.db.query(IntegrationConnection).filter(
            IntegrationConnection.organization_id == self.organization_id,
        ).all()
        value = {
            "connections": [
                {
                    "source": conn.source,
                    "status": conn.status,
                    "last_synced_at": conn.last_synced_at.isoformat() if conn.last_synced_at else None,
                }
                for conn in connections
            ]
        }
        self._remember("connections.active", "connection", value, source="integration_connections")

    def _connection_insights(self) -> list[dict]:
        active_sources = {
            row.source for row in self.db.query(IntegrationConnection).filter(
                IntegrationConnection.organization_id == self.organization_id,
                IntegrationConnection.status == "active",
            ).all()
        }
        if settings.sumit_api_key:
            active_sources.add("sumit")
        if all([
            settings.open_finance_client_id,
            settings.open_finance_client_secret,
            settings.open_finance_user_id,
        ]):
            active_sources.add("open_finance")
        insights = []
        if "sumit" not in active_sources:
            insights.append({
                "fingerprint": "connection:sumit:missing",
                "insight_type": "connection",
                "severity": "high",
                "title": "SUMIT connection is not configured",
                "message": "The system needs SUMIT sync to understand invoices, receipts, payments, and accounting documents.",
                "recommended_action": "Configure SUMIT API credentials and run source=sumit sync.",
                "evidence": {"active_sources": sorted(active_sources)},
            })
        if "open_finance" not in active_sources:
            insights.append({
                "fingerprint": "connection:open_finance:missing",
                "insight_type": "connection",
                "severity": "high",
                "title": "Bank/Open Finance connection is not configured",
                "message": "Bank reconciliation and expense control require bank or card transactions.",
                "recommended_action": "Configure Open Finance credentials or import bank/card CSV files.",
                "evidence": {"active_sources": sorted(active_sources)},
            })
        return insights

    def _reconciliation_insights(self, overview: dict) -> list[dict]:
        count = overview["control"]["unreconciled_bank_transactions"]
        if count <= 0:
            return []
        severity = "critical" if count > 100 else "high" if count > 50 else "medium"
        # Severity must stay out of the fingerprint: _upsert_insight matches by
        # fingerprint, so a severity change updates the existing insight
        # instead of leaving a stale one active alongside a new row.
        return [{
            "fingerprint": "reconciliation:unreconciled",
            "insight_type": "reconciliation",
            "severity": severity,
            "title": f"{count} bank transactions need reconciliation",
            "message": "Unmatched bank movements reduce trust in cash, P&L, VAT, and annual report outputs.",
            "recommended_action": "Review /api/control/reconciliation/suggestions and approve suggested matches.",
            "evidence": {"unreconciled_count": count},
        }]

    def _collections_insights(self, overview: dict) -> list[dict]:
        overdue = Decimal(str(overview["control"]["overdue_invoices_amount"]))
        if overdue <= 0:
            return []
        return [{
            "fingerprint": "collections:overdue_invoices",
            "insight_type": "collections",
            "severity": "critical" if overdue > Decimal("50000") else "high",
            "title": "Overdue invoices require collection action",
            "message": f"Open customer balances total {float(overdue):,.2f} ILS.",
            "recommended_action": "Use AR aging and client payment chaser workflow to contact customers.",
            "evidence": {"overdue_invoices_amount": float(overdue)},
        }]

    def _cashflow_insights(self, overview: dict) -> list[dict]:
        cash = Decimal(str(overview["cash"]["bank_account_balance"]))
        net_bank_flow = Decimal(str(overview["cash"]["net_bank_flow"]))
        insights = []
        if cash < Decimal("10000"):
            insights.append({
                "fingerprint": "cash:low_balance",
                "insight_type": "cashflow",
                "severity": "critical",
                "title": "Cash balance is below operating threshold",
                "message": f"Current bank balance is {float(cash):,.2f} ILS.",
                "recommended_action": "Prioritize collections and review upcoming bills before making new commitments.",
                "evidence": overview["cash"],
            })
        if net_bank_flow < 0:
            insights.append({
                "fingerprint": "cash:negative_monthly_flow",
                "insight_type": "cashflow",
                "severity": "medium",
                "title": "Current period bank cash flow is negative",
                "message": f"Net bank movement is {float(net_bank_flow):,.2f} ILS.",
                "recommended_action": "Review expense categories and expected collections for the period.",
                "evidence": overview["cash"],
            })
        return insights

    def _budget_insights(self) -> list[dict]:
        today = date.today()
        month_start = date(today.year, today.month, 1)
        month_end = date(today.year + (today.month // 12), (today.month % 12) + 1, 1)

        budgets = self.db.query(Budget).filter(
            Budget.organization_id == self.organization_id,
            Budget.year == today.year,
            Budget.month == today.month,
        ).all()
        insights = []
        for budget in budgets:
            if not budget.category_name:
                continue
            actual = self.db.query(func.sum(Transaction.amount)).filter(
                Transaction.organization_id == self.organization_id,
                Transaction.transaction_type == TransactionType.EXPENSE,
                Transaction.category == budget.category_name,
                Transaction.transaction_date >= datetime.combine(month_start, datetime.min.time()),
                Transaction.transaction_date < datetime.combine(month_end, datetime.min.time()),
            ).scalar() or Decimal("0")

            budgeted = Decimal(budget.budgeted_amount or 0)
            if budgeted and actual > budgeted * Decimal("1.10"):
                insights.append({
                    "fingerprint": f"budget:over:{today.year}:{today.month}:{budget.category_name}",
                    "insight_type": "budget",
                    "severity": "high",
                    "title": f"Budget overrun in {budget.category_name}",
                    "message": f"Actual spend is {float(actual):,.2f} ILS vs budget {float(budgeted):,.2f} ILS.",
                    "recommended_action": "Review related transactions and update spending controls for this category.",
                    "evidence": {
                        "category": budget.category_name,
                        "actual": float(actual),
                        "budgeted": float(budgeted),
                    },
                })
        return insights

    def _large_unreconciled_bank_insights(self) -> list[dict]:
        since = date.today() - timedelta(days=30)
        rows = self.db.query(BankTransaction).filter(
            BankTransaction.organization_id == self.organization_id,
            BankTransaction.transaction_date >= since,
            BankTransaction.is_reconciled == False,  # noqa: E712
            func.abs(BankTransaction.amount) >= Decimal("10000"),
        ).order_by(func.abs(BankTransaction.amount).desc()).limit(10).all()

        if not rows:
            return []
        return [{
            "fingerprint": "reconciliation:large_unmatched_bank_movements",
            "insight_type": "reconciliation",
            "severity": "high",
            "title": "Large bank movements are still unmatched",
            "message": f"{len(rows)} recent bank transactions above 10,000 ILS are not reconciled.",
            "recommended_action": "Match large movements first; they materially affect management reports.",
            "evidence": {
                "transactions": [
                    {
                        "id": row.id,
                        "date": row.transaction_date.isoformat(),
                        "description": row.description,
                        "amount": float(row.amount),
                    }
                    for row in rows
                ]
            },
        }]

    def _upsert_insight(self, item: dict[str, Any]) -> CfoInsight:
        existing = self.db.query(CfoInsight).filter(
            CfoInsight.organization_id == self.organization_id,
            CfoInsight.fingerprint == item["fingerprint"],
        ).first()
        now = datetime.utcnow()
        if existing:
            existing.insight_type = item["insight_type"]
            existing.severity = item["severity"]
            existing.title = item["title"]
            existing.message = item.get("message")
            existing.evidence = item.get("evidence")
            existing.recommended_action = item.get("recommended_action")
            if existing.status == "resolved":
                existing.status = "active"
                existing.resolved_at = None
            existing.updated_at = now
            return existing

        insight = CfoInsight(
            organization_id=self.organization_id,
            fingerprint=item["fingerprint"],
            insight_type=item["insight_type"],
            severity=item["severity"],
            title=item["title"],
            message=item.get("message"),
            evidence=item.get("evidence"),
            recommended_action=item.get("recommended_action"),
        )
        self.db.add(insight)
        self.db.flush()
        return insight

    def _ensure_task_for_insight(self, insight: CfoInsight) -> bool:
        existing = self.db.query(Task).filter(
            Task.organization_id == self.organization_id,
            Task.entity_type == "cfo_insight",
            Task.entity_id == insight.id,
            Task.status.in_([TaskStatus.OPEN, TaskStatus.IN_PROGRESS]),
        ).first()
        if existing:
            return False

        due_days = 1 if insight.severity == "critical" else 3
        task = Task(
            organization_id=self.organization_id,
            title=insight.title,
            description=insight.recommended_action or insight.message,
            status=TaskStatus.OPEN,
            due_date=date.today() + timedelta(days=due_days),
            entity_type="cfo_insight",
            entity_id=insight.id,
        )
        self.db.add(task)
        return True

    @staticmethod
    def _serialize_insight(insight: CfoInsight) -> dict:
        return {
            "id": insight.id,
            "fingerprint": insight.fingerprint,
            "insight_type": insight.insight_type,
            "severity": insight.severity,
            "title": insight.title,
            "message": insight.message,
            "evidence": insight.evidence,
            "recommended_action": insight.recommended_action,
            "status": insight.status,
            "created_at": insight.created_at.isoformat() if insight.created_at else None,
            "updated_at": insight.updated_at.isoformat() if insight.updated_at else None,
            "resolved_at": insight.resolved_at.isoformat() if insight.resolved_at else None,
        }
