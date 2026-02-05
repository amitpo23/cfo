"""
Dashboard service: computes real-time financial metrics from the local DB.
Powers the CFO overview, P&L, AR aging, AP, and cash flow projections.
"""
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Optional

from sqlalchemy import and_, func, case, extract
from sqlalchemy.orm import Session

from ..models import (
    Account,
    AccountType,
    Alert,
    AlertStatus,
    BankTransaction,
    Bill,
    BillStatus,
    Contact,
    Invoice,
    InvoiceStatus,
    Payment,
    SyncRun,
    Transaction,
    TransactionType,
    Budget,
)


class DashboardService:
    def __init__(self, db: Session, organization_id: int):
        self.db = db
        self.org_id = organization_id

    # ===== Overview =====

    def get_overview(self) -> dict:
        today = date.today()
        month_start = today.replace(day=1)

        cash_balance, cash_by_account = self._get_cash_balance()
        month_revenue = self._get_month_revenue(month_start, today)
        month_expenses = self._get_month_expenses(month_start, today)
        month_gross_profit = month_revenue - month_expenses
        month_net_profit = month_gross_profit  # simplified; COGS not separated yet

        # Runway
        avg_monthly_burn = self._get_average_monthly_burn(months=3)
        runway_months = None
        if avg_monthly_burn > 0:
            runway_months = round(float(cash_balance / Decimal(str(avg_monthly_burn))), 1)

        # AR
        ar_total, ar_overdue = self._get_ar_summary()

        # AP
        ap_total, ap_due_7, ap_due_30 = self._get_ap_summary()

        # Alerts
        alerts = self._get_active_alerts(limit=5)

        # Last sync
        last_sync = self._get_last_sync_time()

        return {
            "cash_balance": float(cash_balance),
            "cash_by_account": cash_by_account,
            "month_revenue": float(month_revenue),
            "month_expenses": float(month_expenses),
            "month_gross_profit": float(month_gross_profit),
            "month_net_profit": float(month_net_profit),
            "runway_months": runway_months,
            "ar_total": float(ar_total),
            "ar_overdue": float(ar_overdue),
            "ap_total": float(ap_total),
            "ap_due_7_days": float(ap_due_7),
            "ap_due_30_days": float(ap_due_30),
            "alerts": alerts,
            "last_sync": last_sync,
        }

    # ===== Cash Balance =====

    def _get_cash_balance(self) -> tuple:
        """Total cash from bank accounts + aggregate by account."""
        bank_accounts = self.db.query(Account).filter(
            Account.organization_id == self.org_id,
            Account.account_type.in_([AccountType.BANK, AccountType.ASSET]),
        ).all()

        total = Decimal("0")
        by_account = []
        for acct in bank_accounts:
            balance = acct.balance or Decimal("0")
            total += balance
            by_account.append({
                "id": acct.id,
                "name": acct.name,
                "balance": float(balance),
                "currency": acct.currency,
            })

        # Also compute from transactions if no bank accounts
        if not bank_accounts:
            total = self._compute_balance_from_transactions()
            by_account = [{"id": 0, "name": "Computed Balance", "balance": float(total), "currency": "ILS"}]

        return total, by_account

    def _compute_balance_from_transactions(self) -> Decimal:
        income = self.db.query(func.sum(Transaction.amount)).filter(
            Transaction.organization_id == self.org_id,
            Transaction.transaction_type == TransactionType.INCOME,
        ).scalar() or Decimal("0")

        expenses = self.db.query(func.sum(Transaction.amount)).filter(
            Transaction.organization_id == self.org_id,
            Transaction.transaction_type == TransactionType.EXPENSE,
        ).scalar() or Decimal("0")

        return income - expenses

    # ===== Revenue & Expenses =====

    def _get_month_revenue(self, start: date, end: date) -> Decimal:
        # From invoices marked as paid this month
        paid = self.db.query(func.sum(Invoice.paid_amount)).filter(
            Invoice.organization_id == self.org_id,
            Invoice.status.in_([InvoiceStatus.PAID, InvoiceStatus.PARTIALLY_PAID]),
            Invoice.issue_date >= start,
            Invoice.issue_date <= end,
        ).scalar() or Decimal("0")

        # Also from income transactions
        tx_income = self.db.query(func.sum(Transaction.amount)).filter(
            Transaction.organization_id == self.org_id,
            Transaction.transaction_type == TransactionType.INCOME,
            Transaction.transaction_date >= datetime.combine(start, datetime.min.time()),
            Transaction.transaction_date <= datetime.combine(end, datetime.max.time()),
        ).scalar() or Decimal("0")

        # Use whichever is larger to avoid double-counting
        return max(paid, tx_income)

    def _get_month_expenses(self, start: date, end: date) -> Decimal:
        # From bills
        bill_expenses = self.db.query(func.sum(Bill.paid_amount)).filter(
            Bill.organization_id == self.org_id,
            Bill.status.in_([BillStatus.PAID, BillStatus.PARTIALLY_PAID]),
            Bill.issue_date >= start,
            Bill.issue_date <= end,
        ).scalar() or Decimal("0")

        # From expense transactions
        tx_expenses = self.db.query(func.sum(Transaction.amount)).filter(
            Transaction.organization_id == self.org_id,
            Transaction.transaction_type == TransactionType.EXPENSE,
            Transaction.transaction_date >= datetime.combine(start, datetime.min.time()),
            Transaction.transaction_date <= datetime.combine(end, datetime.max.time()),
        ).scalar() or Decimal("0")

        return max(bill_expenses, tx_expenses)

    # ===== Runway =====

    def _get_average_monthly_burn(self, months: int = 3) -> float:
        end = date.today()
        start = end - timedelta(days=months * 30)

        expenses = self.db.query(func.sum(Transaction.amount)).filter(
            Transaction.organization_id == self.org_id,
            Transaction.transaction_type == TransactionType.EXPENSE,
            Transaction.transaction_date >= datetime.combine(start, datetime.min.time()),
            Transaction.transaction_date <= datetime.combine(end, datetime.max.time()),
        ).scalar() or Decimal("0")

        income = self.db.query(func.sum(Transaction.amount)).filter(
            Transaction.organization_id == self.org_id,
            Transaction.transaction_type == TransactionType.INCOME,
            Transaction.transaction_date >= datetime.combine(start, datetime.min.time()),
            Transaction.transaction_date <= datetime.combine(end, datetime.max.time()),
        ).scalar() or Decimal("0")

        net_burn = float(expenses - income)
        if net_burn <= 0:
            return 0  # Not burning cash
        return net_burn / months

    # ===== AR =====

    def _get_ar_summary(self) -> tuple:
        """Returns (total_outstanding, overdue_amount)."""
        today = date.today()

        total = self.db.query(func.sum(Invoice.balance)).filter(
            Invoice.organization_id == self.org_id,
            Invoice.status.in_([
                InvoiceStatus.SENT, InvoiceStatus.OVERDUE, InvoiceStatus.PARTIALLY_PAID,
            ]),
        ).scalar() or Decimal("0")

        overdue = self.db.query(func.sum(Invoice.balance)).filter(
            Invoice.organization_id == self.org_id,
            Invoice.status.in_([
                InvoiceStatus.SENT, InvoiceStatus.OVERDUE, InvoiceStatus.PARTIALLY_PAID,
            ]),
            Invoice.due_date < today,
        ).scalar() or Decimal("0")

        return total, overdue

    def get_ar_aging(self) -> dict:
        """AR aging buckets: 0-30, 31-60, 61-90, 90+."""
        today = date.today()

        open_invoices = self.db.query(Invoice).filter(
            Invoice.organization_id == self.org_id,
            Invoice.status.in_([
                InvoiceStatus.SENT, InvoiceStatus.OVERDUE, InvoiceStatus.PARTIALLY_PAID,
            ]),
            Invoice.balance > 0,
        ).all()

        buckets = {
            "0_30": Decimal("0"),
            "31_60": Decimal("0"),
            "61_90": Decimal("0"),
            "90_plus": Decimal("0"),
        }
        bucket_counts = {"0_30": 0, "31_60": 0, "61_90": 0, "90_plus": 0}
        invoice_list = []

        for inv in open_invoices:
            days_overdue = 0
            if inv.due_date:
                days_overdue = max(0, (today - inv.due_date).days)

            # Get contact name
            contact_name = None
            if inv.contact_id:
                contact = self.db.query(Contact).get(inv.contact_id)
                if contact:
                    contact_name = contact.name

            if days_overdue <= 30:
                buckets["0_30"] += inv.balance
                bucket_counts["0_30"] += 1
            elif days_overdue <= 60:
                buckets["31_60"] += inv.balance
                bucket_counts["31_60"] += 1
            elif days_overdue <= 90:
                buckets["61_90"] += inv.balance
                bucket_counts["61_90"] += 1
            else:
                buckets["90_plus"] += inv.balance
                bucket_counts["90_plus"] += 1

            invoice_list.append({
                "id": inv.id,
                "invoice_number": inv.invoice_number,
                "customer": contact_name,
                "amount": float(inv.total),
                "balance": float(inv.balance),
                "due_date": inv.due_date.isoformat() if inv.due_date else None,
                "days_overdue": days_overdue,
                "status": inv.status.value if inv.status else "unknown",
            })

        total = sum(buckets.values())

        return {
            "bucket_0_30": float(buckets["0_30"]),
            "bucket_31_60": float(buckets["31_60"]),
            "bucket_61_90": float(buckets["61_90"]),
            "bucket_90_plus": float(buckets["90_plus"]),
            "total": float(total),
            "count": len(invoice_list),
            "invoices": sorted(invoice_list, key=lambda x: x["days_overdue"], reverse=True),
        }

    # ===== AP =====

    def _get_ap_summary(self) -> tuple:
        """Returns (total_outstanding, due_in_7_days, due_in_30_days)."""
        today = date.today()

        total = self.db.query(func.sum(Bill.balance)).filter(
            Bill.organization_id == self.org_id,
            Bill.status.in_([
                BillStatus.RECEIVED, BillStatus.APPROVED,
                BillStatus.OVERDUE, BillStatus.PARTIALLY_PAID,
            ]),
        ).scalar() or Decimal("0")

        due_7 = self.db.query(func.sum(Bill.balance)).filter(
            Bill.organization_id == self.org_id,
            Bill.status.in_([
                BillStatus.RECEIVED, BillStatus.APPROVED,
                BillStatus.OVERDUE, BillStatus.PARTIALLY_PAID,
            ]),
            Bill.due_date <= today + timedelta(days=7),
        ).scalar() or Decimal("0")

        due_30 = self.db.query(func.sum(Bill.balance)).filter(
            Bill.organization_id == self.org_id,
            Bill.status.in_([
                BillStatus.RECEIVED, BillStatus.APPROVED,
                BillStatus.OVERDUE, BillStatus.PARTIALLY_PAID,
            ]),
            Bill.due_date <= today + timedelta(days=30),
        ).scalar() or Decimal("0")

        return total, due_7, due_30

    def get_ap_bills(self, days_ahead: int = 30) -> list:
        """List of unpaid bills, sorted by due date."""
        today = date.today()

        bills = self.db.query(Bill).filter(
            Bill.organization_id == self.org_id,
            Bill.status.in_([
                BillStatus.RECEIVED, BillStatus.APPROVED,
                BillStatus.OVERDUE, BillStatus.PARTIALLY_PAID,
            ]),
            Bill.balance > 0,
        ).order_by(Bill.due_date.asc()).all()

        result = []
        for bill in bills:
            vendor_name = None
            if bill.vendor_id:
                vendor = self.db.query(Contact).get(bill.vendor_id)
                if vendor:
                    vendor_name = vendor.name

            days_until_due = None
            if bill.due_date:
                days_until_due = (bill.due_date - today).days

            result.append({
                "id": bill.id,
                "bill_number": bill.bill_number,
                "vendor": vendor_name,
                "amount": float(bill.total),
                "balance": float(bill.balance),
                "due_date": bill.due_date.isoformat() if bill.due_date else None,
                "days_until_due": days_until_due,
                "is_critical": bill.is_critical,
                "can_delay": bill.can_delay,
                "status": bill.status.value if bill.status else "unknown",
            })

        return result

    # ===== P&L =====

    def get_pnl(self, months: int = 6) -> list:
        """Monthly P&L for the past N months."""
        today = date.today()
        result = []

        for i in range(months - 1, -1, -1):
            if today.month - i <= 0:
                m = today.month - i + 12
                y = today.year - 1
            else:
                m = today.month - i
                y = today.year

            month_start = date(y, m, 1)
            if m == 12:
                month_end = date(y + 1, 1, 1) - timedelta(days=1)
            else:
                month_end = date(y, m + 1, 1) - timedelta(days=1)

            revenue = float(self._get_month_revenue(month_start, month_end))
            expenses = float(self._get_month_expenses(month_start, month_end))
            cogs = expenses * 0.3  # simplified estimate
            gross_profit = revenue - cogs
            opex = expenses - cogs
            net_profit = revenue - expenses

            # Category breakdown from transactions
            categories = self._get_expense_categories(month_start, month_end)

            result.append({
                "month": month_start.strftime("%Y-%m"),
                "revenue": revenue,
                "cogs": cogs,
                "gross_profit": gross_profit,
                "opex": opex,
                "net_profit": net_profit,
                "categories": categories,
            })

        return result

    def _get_expense_categories(self, start: date, end: date) -> dict:
        rows = self.db.query(
            Transaction.category,
            func.sum(Transaction.amount),
        ).filter(
            Transaction.organization_id == self.org_id,
            Transaction.transaction_type == TransactionType.EXPENSE,
            Transaction.transaction_date >= datetime.combine(start, datetime.min.time()),
            Transaction.transaction_date <= datetime.combine(end, datetime.max.time()),
        ).group_by(Transaction.category).all()

        return {cat or "uncategorized": float(amt) for cat, amt in rows}

    # ===== Cash Flow Projection =====

    def get_cashflow_projection(self, weeks: int = 12, scenario: str = "base") -> list:
        """
        Project cash flow for the next N weeks based on:
        - Open invoices (expected collections by due date)
        - Open bills (expected payments)
        - Historical average for recurring items
        """
        today = date.today()
        cash_balance, _ = self._get_cash_balance()
        cumulative = float(cash_balance)

        # Scenario multipliers
        scenarios = {
            "conservative": {"ar_prob": 0.65, "ar_delay": 21},
            "base": {"ar_prob": 0.85, "ar_delay": 7},
            "aggressive": {"ar_prob": 0.95, "ar_delay": 0},
        }
        s = scenarios.get(scenario, scenarios["base"])

        # Load open invoices
        open_invoices = self.db.query(Invoice).filter(
            Invoice.organization_id == self.org_id,
            Invoice.status.in_([
                InvoiceStatus.SENT, InvoiceStatus.OVERDUE, InvoiceStatus.PARTIALLY_PAID,
            ]),
            Invoice.balance > 0,
        ).all()

        # Load open bills
        open_bills = self.db.query(Bill).filter(
            Bill.organization_id == self.org_id,
            Bill.status.in_([
                BillStatus.RECEIVED, BillStatus.APPROVED,
                BillStatus.OVERDUE, BillStatus.PARTIALLY_PAID,
            ]),
            Bill.balance > 0,
        ).all()

        result = []
        for w in range(weeks):
            week_start = today + timedelta(weeks=w)
            week_end = week_start + timedelta(days=6)

            # Expected inflows from invoices due this week
            inflows = 0.0
            for inv in open_invoices:
                expected_date = inv.due_date
                if expected_date:
                    expected_date = expected_date + timedelta(days=s["ar_delay"])
                    if week_start <= expected_date <= week_end:
                        inflows += float(inv.balance) * s["ar_prob"]

            # Expected outflows from bills due this week
            outflows = 0.0
            for bill in open_bills:
                if bill.due_date and week_start <= bill.due_date <= week_end:
                    outflows += float(bill.balance)

            net = inflows - outflows
            cumulative += net

            result.append({
                "week": week_start.isoformat(),
                "expected_inflows": round(inflows, 2),
                "expected_outflows": round(outflows, 2),
                "net_flow": round(net, 2),
                "cumulative_balance": round(cumulative, 2),
            })

        return result

    # ===== Budget vs Actuals =====

    def get_budget_variance(self, year: int, month: int) -> list:
        budgets = self.db.query(Budget).filter(
            Budget.organization_id == self.org_id,
            Budget.year == year,
            Budget.month == month,
        ).all()

        month_start = date(year, month, 1)
        if month == 12:
            month_end = date(year + 1, 1, 1) - timedelta(days=1)
        else:
            month_end = date(year, month + 1, 1) - timedelta(days=1)

        result = []
        for b in budgets:
            # Compute actual from transactions
            actual = self.db.query(func.sum(Transaction.amount)).filter(
                Transaction.organization_id == self.org_id,
                Transaction.transaction_type == TransactionType.EXPENSE,
                Transaction.category == b.category_name,
                Transaction.transaction_date >= datetime.combine(month_start, datetime.min.time()),
                Transaction.transaction_date <= datetime.combine(month_end, datetime.max.time()),
            ).scalar() or Decimal("0")

            budgeted = b.budgeted_amount or Decimal("0")
            variance = float(budgeted - actual)
            variance_pct = (variance / float(budgeted) * 100) if budgeted else 0

            result.append({
                "id": b.id,
                "category": b.category_name,
                "budgeted": float(budgeted),
                "actual": float(actual),
                "variance": variance,
                "variance_pct": round(variance_pct, 1),
                "over_budget": actual > budgeted,
            })

        return result

    # ===== Alerts =====

    def _get_active_alerts(self, limit: int = 10) -> list:
        alerts = self.db.query(Alert).filter(
            Alert.organization_id == self.org_id,
            Alert.status == AlertStatus.ACTIVE,
        ).order_by(Alert.created_at.desc()).limit(limit).all()

        return [
            {
                "id": a.id,
                "type": a.alert_type,
                "severity": a.severity.value if a.severity else "info",
                "title": a.title,
                "message": a.message,
                "entity_type": a.entity_type,
                "entity_id": a.entity_id,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in alerts
        ]

    # ===== Last Sync =====

    def _get_last_sync_time(self) -> Optional[str]:
        last_run = self.db.query(SyncRun).filter(
            SyncRun.organization_id == self.org_id,
        ).order_by(SyncRun.finished_at.desc()).first()

        if last_run and last_run.finished_at:
            return last_run.finished_at.isoformat()
        return None
