"""
Alert engine: evaluates rules and creates alerts.
Runs after each sync or on-demand.
"""
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import (
    Alert,
    AlertRule,
    AlertSeverity,
    AlertStatus,
    Bill,
    BillStatus,
    Invoice,
    InvoiceStatus,
    Transaction,
    TransactionType,
)


class AlertEngine:
    """Evaluates alert rules against current data and creates Alert records."""

    def __init__(self, db: Session, organization_id: int):
        self.db = db
        self.org_id = organization_id

    def evaluate_all(self) -> list:
        """Run all active alert rules. Returns list of newly created alerts."""
        rules = self.db.query(AlertRule).filter(
            AlertRule.organization_id == self.org_id,
            AlertRule.is_active == True,
        ).all()

        new_alerts = []

        # Also run built-in rules even if no AlertRule records exist
        new_alerts.extend(self._check_overdue_invoices())
        new_alerts.extend(self._check_bills_due_soon())
        new_alerts.extend(self._check_large_transactions())

        for rule in rules:
            if rule.rule_type == "low_cash_threshold":
                new_alerts.extend(self._check_low_cash(rule.config))
            elif rule.rule_type == "spend_spike":
                new_alerts.extend(self._check_spend_spike(rule.config))

        self.db.commit()
        return new_alerts

    def _check_overdue_invoices(self, days_threshold: int = 30) -> list:
        """Flag invoices overdue by more than N days."""
        today = date.today()
        cutoff = today - timedelta(days=days_threshold)

        overdue = self.db.query(Invoice).filter(
            Invoice.organization_id == self.org_id,
            Invoice.status.in_([InvoiceStatus.SENT, InvoiceStatus.OVERDUE, InvoiceStatus.PARTIALLY_PAID]),
            Invoice.due_date < cutoff,
            Invoice.balance > 0,
        ).all()

        alerts = []
        for inv in overdue:
            # Check if alert already exists
            existing = self.db.query(Alert).filter(
                Alert.organization_id == self.org_id,
                Alert.alert_type == "overdue_invoice",
                Alert.entity_type == "invoice",
                Alert.entity_id == inv.id,
                Alert.status == AlertStatus.ACTIVE,
            ).first()

            if existing:
                continue

            days_late = (today - inv.due_date).days
            alert = Alert(
                organization_id=self.org_id,
                alert_type="overdue_invoice",
                severity=AlertSeverity.WARNING if days_late < 60 else AlertSeverity.CRITICAL,
                entity_type="invoice",
                entity_id=inv.id,
                title=f"Invoice #{inv.invoice_number or inv.id} is {days_late} days overdue",
                message=f"Balance: {inv.balance} {inv.currency}. Due: {inv.due_date}",
            )
            self.db.add(alert)
            alerts.append(alert)

        return alerts

    def _check_bills_due_soon(self, days_ahead: int = 7) -> list:
        """Flag bills due in the next N days."""
        today = date.today()
        cutoff = today + timedelta(days=days_ahead)

        upcoming = self.db.query(Bill).filter(
            Bill.organization_id == self.org_id,
            Bill.status.in_([BillStatus.RECEIVED, BillStatus.APPROVED]),
            Bill.due_date >= today,
            Bill.due_date <= cutoff,
            Bill.balance > 0,
        ).all()

        alerts = []
        for bill in upcoming:
            existing = self.db.query(Alert).filter(
                Alert.organization_id == self.org_id,
                Alert.alert_type == "bill_due_soon",
                Alert.entity_type == "bill",
                Alert.entity_id == bill.id,
                Alert.status == AlertStatus.ACTIVE,
            ).first()

            if existing:
                continue

            days_until = (bill.due_date - today).days
            alert = Alert(
                organization_id=self.org_id,
                alert_type="bill_due_soon",
                severity=AlertSeverity.INFO if days_until > 3 else AlertSeverity.WARNING,
                entity_type="bill",
                entity_id=bill.id,
                title=f"Bill #{bill.bill_number or bill.id} due in {days_until} days",
                message=f"Amount: {bill.balance} {bill.currency}. Due: {bill.due_date}",
            )
            self.db.add(alert)
            alerts.append(alert)

        return alerts

    def _check_large_transactions(self, threshold: float = 10000) -> list:
        """Flag transactions above threshold that haven't been alerted."""
        recent = self.db.query(Transaction).filter(
            Transaction.organization_id == self.org_id,
            Transaction.amount >= Decimal(str(threshold)),
            Transaction.transaction_date >= datetime.utcnow() - timedelta(days=7),
        ).all()

        alerts = []
        for tx in recent:
            existing = self.db.query(Alert).filter(
                Alert.organization_id == self.org_id,
                Alert.alert_type == "large_transaction",
                Alert.entity_type == "transaction",
                Alert.entity_id == tx.id,
            ).first()

            if existing:
                continue

            alert = Alert(
                organization_id=self.org_id,
                alert_type="large_transaction",
                severity=AlertSeverity.INFO,
                entity_type="transaction",
                entity_id=tx.id,
                title=f"Large {tx.transaction_type.value}: {tx.amount}",
                message=tx.description,
            )
            self.db.add(alert)
            alerts.append(alert)

        return alerts

    def _check_low_cash(self, config: dict) -> list:
        """Check if cash balance is below threshold."""
        threshold = config.get("threshold", 50000)

        # Compute cash balance
        from .dashboard_service import DashboardService
        dashboard = DashboardService(self.db, self.org_id)
        cash, _ = dashboard._get_cash_balance()

        if float(cash) >= threshold:
            return []

        existing = self.db.query(Alert).filter(
            Alert.organization_id == self.org_id,
            Alert.alert_type == "low_cash",
            Alert.status == AlertStatus.ACTIVE,
        ).first()

        if existing:
            return []

        alert = Alert(
            organization_id=self.org_id,
            alert_type="low_cash",
            severity=AlertSeverity.CRITICAL,
            title=f"Cash balance below threshold: {cash:,.0f}",
            message=f"Current balance: {cash:,.2f}. Threshold: {threshold:,.0f}",
        )
        self.db.add(alert)
        return [alert]

    def _check_spend_spike(self, config: dict) -> list:
        """Check if current month spending exceeds 3-month average by threshold %."""
        threshold_pct = config.get("threshold_pct", 30)
        today = date.today()
        month_start = today.replace(day=1)

        # Current month expenses
        current = self.db.query(func.sum(Transaction.amount)).filter(
            Transaction.organization_id == self.org_id,
            Transaction.transaction_type == TransactionType.EXPENSE,
            Transaction.transaction_date >= datetime.combine(month_start, datetime.min.time()),
        ).scalar() or Decimal("0")

        # 3-month average
        three_months_ago = today - timedelta(days=90)
        past_total = self.db.query(func.sum(Transaction.amount)).filter(
            Transaction.organization_id == self.org_id,
            Transaction.transaction_type == TransactionType.EXPENSE,
            Transaction.transaction_date >= datetime.combine(three_months_ago, datetime.min.time()),
            Transaction.transaction_date < datetime.combine(month_start, datetime.min.time()),
        ).scalar() or Decimal("0")

        avg_monthly = float(past_total) / 3 if past_total else 0

        if avg_monthly == 0 or float(current) <= avg_monthly * (1 + threshold_pct / 100):
            return []

        existing = self.db.query(Alert).filter(
            Alert.organization_id == self.org_id,
            Alert.alert_type == "spend_spike",
            Alert.status == AlertStatus.ACTIVE,
        ).first()

        if existing:
            return []

        spike_pct = ((float(current) - avg_monthly) / avg_monthly) * 100
        alert = Alert(
            organization_id=self.org_id,
            alert_type="spend_spike",
            severity=AlertSeverity.WARNING,
            title=f"Spending spike: {spike_pct:.0f}% above 3-month average",
            message=f"Current month: {current:,.0f}. 3-month avg: {avg_monthly:,.0f}",
        )
        self.db.add(alert)
        return [alert]
