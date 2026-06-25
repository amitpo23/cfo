"""
Phase 13D: Analytics Reporting Service
Generates daily, weekly, and monthly financial reports with insights
"""
from datetime import datetime, timedelta, date, timezone
from typing import Dict, List, Optional, Any
from decimal import Decimal
from sqlalchemy.orm import Session
from sqlalchemy import and_, func

from ..models import (
    Organization, Invoice, Bill, BankTransaction, 
    Expense, Contact, Account, Transaction
)


class AnalyticsReportingService:
    """Generate automated financial reports with insights"""

    def __init__(self, db: Session, org_id: int):
        self.db = db
        self.org_id = org_id

    def generate_daily_report(self, report_date: Optional[date] = None) -> Dict[str, Any]:
        """
        Generate daily report with:
        - Today's transactions (income/expense/transfers)
        - Yesterday's comparison
        - Cumulative P&L for current month
        - Cumulative P&L for previous month
        - Key alerts/insights
        """
        if not report_date:
            report_date = date.today()

        yesterday = report_date - timedelta(days=1)
        month_start = report_date.replace(day=1)
        prev_month_start = (month_start - timedelta(days=1)).replace(day=1)
        prev_month_end = month_start - timedelta(days=1)

        return {
            "report_type": "daily",
            "report_date": report_date.isoformat(),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "summary": self._get_daily_summary(report_date),
            "yesterday_comparison": self._get_daily_summary(yesterday),
            "cumulative_pl_current_month": self._get_cumulative_pl(month_start, report_date),
            "cumulative_pl_previous_month": self._get_cumulative_pl(prev_month_start, prev_month_end),
            "cash_position": self._get_cash_position(),
            "ar_ap_summary": self._get_ar_ap_summary(),
            "alerts": self._get_alerts(),
        }

    def generate_weekly_budget_report(self, report_date: Optional[date] = None) -> Dict[str, Any]:
        """
        Generate weekly budget vs actual report
        - Budget for week
        - Actual spending/income
        - Variance analysis
        - Top expenses
        """
        if not report_date:
            report_date = date.today()

        # Calculate week start (Monday)
        week_start = report_date - timedelta(days=report_date.weekday())
        week_end = week_start + timedelta(days=6)

        return {
            "report_type": "weekly_budget",
            "week_start": week_start.isoformat(),
            "week_end": week_end.isoformat(),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "budget_summary": self._get_weekly_budget_summary(week_start, week_end),
            "actual_vs_budget": self._get_actual_vs_budget(week_start, week_end),
            "top_expenses": self._get_top_expenses(week_start, week_end, limit=10),
            "variance_analysis": self._get_variance_analysis(week_start, week_end),
        }

    def generate_monthly_pl_report(self, report_month: Optional[date] = None) -> Dict[str, Any]:
        """
        Generate monthly P&L report
        - Revenue
        - Expenses by category
        - Operating profit
        - Net profit
        - Year-over-year comparison
        """
        if not report_month:
            report_month = date.today().replace(day=1)

        month_end = (report_month.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
        
        # Previous year same month
        try:
            prev_year_month = report_month.replace(year=report_month.year - 1)
            prev_year_month_end = (prev_year_month.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
        except ValueError:
            prev_year_month = None
            prev_year_month_end = None

        return {
            "report_type": "monthly_pl",
            "month": report_month.isoformat(),
            "month_end": month_end.isoformat(),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "revenue": self._get_monthly_revenue(report_month, month_end),
            "expenses": self._get_monthly_expenses(report_month, month_end),
            "operating_profit": self._get_operating_profit(report_month, month_end),
            "net_profit": self._get_net_profit(report_month, month_end),
            "year_over_year": (
                self._get_yoy_comparison(report_month, month_end, prev_year_month, prev_year_month_end)
                if prev_year_month else None
            ),
            "expense_breakdown": self._get_expense_breakdown_by_category(report_month, month_end),
        }

    # ==================== Daily Report Helpers ====================

    def _get_daily_summary(self, report_date: date) -> Dict[str, Any]:
        """Get summary of transactions for a single day"""
        day_start = datetime.combine(report_date, datetime.min.time())
        day_end = datetime.combine(report_date, datetime.max.time())

        # Income transactions
        income = self.db.query(
            func.sum(Invoice.total_amount)
        ).filter(
            Invoice.organization_id == self.org_id,
            Invoice.created_at >= day_start,
            Invoice.created_at <= day_end,
            Invoice.status.in_(["sent", "paid", "partially_paid"])
        ).scalar() or Decimal(0)

        # Expense transactions
        expenses = self.db.query(
            func.sum(Expense.total_amount)
        ).filter(
            Expense.organization_id == self.org_id,
            Expense.created_at >= day_start,
            Expense.created_at <= day_end,
            Expense.status != "draft"
        ).scalar() or Decimal(0)

        # Bills
        bills_paid = self.db.query(
            func.sum(Bill.total_amount)
        ).filter(
            Bill.organization_id == self.org_id,
            Bill.created_at >= day_start,
            Bill.created_at <= day_end,
            Bill.status.in_(["paid", "partially_paid"])
        ).scalar() or Decimal(0)

        return {
            "date": report_date.isoformat(),
            "income": float(income),
            "expenses": float(expenses),
            "bills_paid": float(bills_paid),
            "net_cash_flow": float(income - expenses - bills_paid),
            "transaction_count": self._count_daily_transactions(report_date),
        }

    def _get_cumulative_pl(self, start_date: date, end_date: date) -> Dict[str, Any]:
        """Get cumulative P&L for a date range"""
        start_dt = datetime.combine(start_date, datetime.min.time())
        end_dt = datetime.combine(end_date, datetime.max.time())

        revenue = self.db.query(
            func.sum(Invoice.total_amount)
        ).filter(
            Invoice.organization_id == self.org_id,
            Invoice.created_at >= start_dt,
            Invoice.created_at <= end_dt,
            Invoice.status.in_(["sent", "paid", "partially_paid"])
        ).scalar() or Decimal(0)

        expenses = self.db.query(
            func.sum(Expense.total_amount)
        ).filter(
            Expense.organization_id == self.org_id,
            Expense.created_at >= start_dt,
            Expense.created_at <= end_dt,
            Expense.status != "draft"
        ).scalar() or Decimal(0)

        operating_income = revenue - expenses

        return {
            "period_start": start_date.isoformat(),
            "period_end": end_date.isoformat(),
            "revenue": float(revenue),
            "expenses": float(expenses),
            "operating_income": float(operating_income),
            "margin_percent": float((operating_income / revenue * 100) if revenue > 0 else 0),
        }

    def _get_cash_position(self) -> Dict[str, Any]:
        """Get current cash position summary"""
        # This would query bank accounts and sum balances
        # For now, return structure
        return {
            "total_cash": 0.0,
            "bank_accounts": [],
            "liquidity_ratio": 0.0,
        }

    def _get_ar_ap_summary(self) -> Dict[str, Any]:
        """Get AR/AP summary"""
        overdue_ar = self.db.query(
            func.sum(Invoice.remaining_balance)
        ).filter(
            Invoice.organization_id == self.org_id,
            Invoice.due_date < date.today(),
            Invoice.status.in_(["sent", "partially_paid"])
        ).scalar() or Decimal(0)

        overdue_ap = self.db.query(
            func.sum(Bill.remaining_balance)
        ).filter(
            Bill.organization_id == self.org_id,
            Bill.due_date < date.today(),
            Bill.status.in_(["received", "partially_paid"])
        ).scalar() or Decimal(0)

        return {
            "overdue_receivables": float(overdue_ar),
            "overdue_payables": float(overdue_ap),
            "working_capital_gap": float(overdue_ar - overdue_ap),
        }

    def _get_alerts(self) -> List[Dict[str, Any]]:
        """Generate alerts based on financial conditions"""
        alerts = []

        # Check for overdue AR
        overdue_ar = self.db.query(
            func.sum(Invoice.remaining_balance)
        ).filter(
            Invoice.organization_id == self.org_id,
            Invoice.due_date < date.today(),
            Invoice.status.in_(["sent", "partially_paid"])
        ).scalar() or Decimal(0)

        if overdue_ar > 1000:
            alerts.append({
                "severity": "warning",
                "message": f"Overdue receivables: {float(overdue_ar):.2f}",
                "type": "ar_overdue",
            })

        # Check for overdue AP
        overdue_ap = self.db.query(
            func.sum(Bill.remaining_balance)
        ).filter(
            Bill.organization_id == self.org_id,
            Bill.due_date < date.today(),
            Bill.status.in_(["received", "partially_paid"])
        ).scalar() or Decimal(0)

        if overdue_ap > 1000:
            alerts.append({
                "severity": "critical",
                "message": f"Bills overdue: {float(overdue_ap):.2f}",
                "type": "ap_overdue",
            })

        return alerts

    # ==================== Weekly Budget Helpers ====================

    def _get_weekly_budget_summary(self, start_date: date, end_date: date) -> Dict[str, Any]:
        """Get budget summary for week"""
        # This would query budgets for the organization
        return {
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "budgeted_amount": 0.0,
            "actual_amount": 0.0,
            "variance": 0.0,
        }

    def _get_actual_vs_budget(self, start_date: date, end_date: date) -> Dict[str, Any]:
        """Get actual spending vs budget"""
        start_dt = datetime.combine(start_date, datetime.min.time())
        end_dt = datetime.combine(end_date, datetime.max.time())

        actual_expenses = self.db.query(
            func.sum(Expense.total_amount)
        ).filter(
            Expense.organization_id == self.org_id,
            Expense.created_at >= start_dt,
            Expense.created_at <= end_dt,
            Expense.status != "draft"
        ).scalar() or Decimal(0)

        return {
            "period_start": start_date.isoformat(),
            "period_end": end_date.isoformat(),
            "actual": float(actual_expenses),
            "budget": 0.0,  # Would pull from budget table
            "variance": 0.0,
            "variance_percent": 0.0,
        }

    def _get_top_expenses(self, start_date: date, end_date: date, limit: int = 10) -> List[Dict[str, Any]]:
        """Get top expenses for period"""
        start_dt = datetime.combine(start_date, datetime.min.time())
        end_dt = datetime.combine(end_date, datetime.max.time())

        top_expenses = self.db.query(
            Expense.category,
            func.sum(Expense.total_amount).label("total"),
            func.count(Expense.id).label("count")
        ).filter(
            Expense.organization_id == self.org_id,
            Expense.created_at >= start_dt,
            Expense.created_at <= end_dt,
            Expense.status != "draft"
        ).group_by(
            Expense.category
        ).order_by(
            func.sum(Expense.total_amount).desc()
        ).limit(limit).all()

        return [
            {
                "category": exp.category,
                "total": float(exp.total),
                "count": exp.count,
                "average": float(exp.total / exp.count) if exp.count > 0 else 0,
            }
            for exp in top_expenses
        ]

    def _get_variance_analysis(self, start_date: date, end_date: date) -> Dict[str, Any]:
        """Analyze budget variance"""
        return {
            "favorable_variance": 0.0,
            "unfavorable_variance": 0.0,
            "variance_categories": [],
        }

    # ==================== Monthly P&L Helpers ====================

    def _get_monthly_revenue(self, start_date: date, end_date: date) -> float:
        """Get monthly revenue"""
        start_dt = datetime.combine(start_date, datetime.min.time())
        end_dt = datetime.combine(end_date, datetime.max.time())

        revenue = self.db.query(
            func.sum(Invoice.total_amount)
        ).filter(
            Invoice.organization_id == self.org_id,
            Invoice.created_at >= start_dt,
            Invoice.created_at <= end_dt,
            Invoice.status.in_(["sent", "paid", "partially_paid"])
        ).scalar() or Decimal(0)

        return float(revenue)

    def _get_monthly_expenses(self, start_date: date, end_date: date) -> float:
        """Get monthly expenses"""
        start_dt = datetime.combine(start_date, datetime.min.time())
        end_dt = datetime.combine(end_date, datetime.max.time())

        expenses = self.db.query(
            func.sum(Expense.total_amount)
        ).filter(
            Expense.organization_id == self.org_id,
            Expense.created_at >= start_dt,
            Expense.created_at <= end_dt,
            Expense.status != "draft"
        ).scalar() or Decimal(0)

        return float(expenses)

    def _get_operating_profit(self, start_date: date, end_date: date) -> float:
        """Get operating profit"""
        revenue = self._get_monthly_revenue(start_date, end_date)
        expenses = self._get_monthly_expenses(start_date, end_date)
        return revenue - expenses

    def _get_net_profit(self, start_date: date, end_date: date) -> float:
        """Get net profit (operating profit for now)"""
        return self._get_operating_profit(start_date, end_date)

    def _get_yoy_comparison(
        self,
        curr_start: date,
        curr_end: date,
        prev_start: date,
        prev_end: date
    ) -> Dict[str, Any]:
        """Get year-over-year comparison"""
        curr_revenue = self._get_monthly_revenue(curr_start, curr_end)
        prev_revenue = self._get_monthly_revenue(prev_start, prev_end) if prev_start else 0

        curr_expenses = self._get_monthly_expenses(curr_start, curr_end)
        prev_expenses = self._get_monthly_expenses(prev_start, prev_end) if prev_start else 0

        revenue_growth = (
            ((curr_revenue - prev_revenue) / prev_revenue * 100)
            if prev_revenue > 0 else 0
        )
        expense_growth = (
            ((curr_expenses - prev_expenses) / prev_expenses * 100)
            if prev_expenses > 0 else 0
        )

        return {
            "previous_year_revenue": prev_revenue,
            "current_year_revenue": curr_revenue,
            "revenue_growth_percent": revenue_growth,
            "previous_year_expenses": prev_expenses,
            "current_year_expenses": curr_expenses,
            "expense_growth_percent": expense_growth,
        }

    def _get_expense_breakdown_by_category(self, start_date: date, end_date: date) -> List[Dict[str, Any]]:
        """Get expense breakdown by category"""
        start_dt = datetime.combine(start_date, datetime.min.time())
        end_dt = datetime.combine(end_date, datetime.max.time())

        breakdown = self.db.query(
            Expense.category,
            func.sum(Expense.total_amount).label("total"),
            func.count(Expense.id).label("count")
        ).filter(
            Expense.organization_id == self.org_id,
            Expense.created_at >= start_dt,
            Expense.created_at <= end_dt,
            Expense.status != "draft"
        ).group_by(
            Expense.category
        ).order_by(
            func.sum(Expense.total_amount).desc()
        ).all()

        total_expenses = sum(exp.total for exp in breakdown) or Decimal(1)

        return [
            {
                "category": exp.category,
                "amount": float(exp.total),
                "count": exp.count,
                "percentage": float((exp.total / total_expenses * 100) if total_expenses > 0 else 0),
            }
            for exp in breakdown
        ]

    # ==================== Helper Methods ====================

    def _count_daily_transactions(self, report_date: date) -> int:
        """Count transactions for a day"""
        day_start = datetime.combine(report_date, datetime.min.time())
        day_end = datetime.combine(report_date, datetime.max.time())

        count = self.db.query(func.count(Transaction.id)).filter(
            Transaction.organization_id == self.org_id,
            Transaction.created_at >= day_start,
            Transaction.created_at <= day_end,
        ).scalar() or 0

        return count
