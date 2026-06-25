"""Phase 11: Advanced forecasting.

שומר על משטח ה-API של ``/advanced/forecast/*`` אך מחשב כל מספר מנתון אמיתי
ב-DB דרך :class:`ForecastingService` ו-:class:`BudgetService`. אין ערכים קשיחים.
"""
import math
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy.orm import Session

from .budget_service import BudgetPeriod, BudgetService
from .forecasting_service import ForecastingService


class AdvancedForecastingService:
    def __init__(self, db: Session, organization_id: int):
        self.db = db
        self.organization_id = organization_id
        self._forecasting = ForecastingService(db)
        self._budget = BudgetService(db, organization_id)

    def forecast_cash_flow(
        self, days_ahead: int = 90, starting_balance: Optional[Decimal] = None
    ) -> dict[str, Any]:
        """תחזית תזרים נגזרת מהתנועות בפועל (אגרגציה חודשית — ראו ForecastingService)."""
        periods = max(1, math.ceil(days_ahead / 30))
        start = float(starting_balance or 0)
        forecast = self._forecasting.forecast_cash_flow(self.organization_id, periods, start)

        balances = [f["projected_balance"] for f in forecast] or [start]
        ending = forecast[-1]["projected_balance"] if forecast else start
        critical_dates = [f["date"] for f in forecast if f["projected_balance"] < 0]

        return {
            "forecast_days": days_ahead,
            "periods": periods,
            "starting_balance": start,
            "ending_balance": ending,
            "min_balance": min(balances),
            "max_balance": max(balances),
            "critical_dates": critical_dates,
            "forecast": forecast,
        }

    def budget_vs_actual(
        self, period: str = "monthly", year: int = 2026, month: Optional[int] = None
    ) -> dict[str, Any]:
        """השוואת תקציב מול ביצוע מתוך רשומות Budget אמיתיות + תנועות בפועל."""
        budget_period = {
            "monthly": BudgetPeriod.MONTHLY,
            "quarterly": BudgetPeriod.QUARTERLY,
            "yearly": BudgetPeriod.YEARLY,
        }.get(period, BudgetPeriod.MONTHLY)

        summary = self._budget.get_budget_vs_actual(year, month, budget_period)

        by_category = {
            (c.category_name or str(c.category_id)): {
                "budget": c.budget_amount,
                "actual": c.actual_amount,
                "variance": c.variance,
                "variance_percent": c.variance_percentage,
                "status": getattr(c.status, "value", c.status),
            }
            for c in summary.categories
        }

        return {
            "period": period,
            "year": year,
            "month": month,
            "total_budget": summary.total_budget,
            "total_actual": summary.total_actual,
            "total_variance": summary.total_variance,
            "total_variance_percent": summary.variance_percentage,
            "by_category": by_category,
        }

    def scenario_analysis(
        self, scenarios: list[dict[str, Any]], periods: int = 12
    ) -> dict[str, Any]:
        """ניתוח תרחישים: בסיס נגזר מהתחזית האמיתית, ומיושמות הנחות המשתמש."""
        base = self._forecasting.forecast_cash_flow(self.organization_id, periods, 0)
        base_revenue = sum(f["projected_inflows"] for f in base)
        base_expenses = sum(f["projected_outflows"] for f in base)

        results = []
        for scenario in scenarios:
            assumptions = scenario.get("assumptions") or {}
            revenue_increase = float(assumptions.get("revenue_increase", 0) or 0)
            expense_cut = float(assumptions.get("expense_cut", 0) or 0)

            est_revenue = base_revenue * (1 + revenue_increase)
            est_expenses = base_expenses * (1 - expense_cut)
            net_income = est_revenue - est_expenses
            net_margin = (net_income / est_revenue * 100) if est_revenue else 0.0

            results.append({
                "scenario": scenario.get("name", ""),
                "estimated_revenue": est_revenue,
                "estimated_expenses": est_expenses,
                "net_income": net_income,
                "net_margin_percent": net_margin,
            })

        recommendation = (
            max(results, key=lambda r: r["net_income"])["scenario"] if results else ""
        )
        return {"scenarios": results, "recommendation": recommendation}
