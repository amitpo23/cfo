"""
דשבורד מנהלים מאוחד — מרכז את כל מדדי מצב העסק לתצוגה אחת.
Executive dashboard: aggregates the 8 business-health panels, each isolated so
a failure in one never breaks the whole dashboard.
"""
import logging
from datetime import date
from typing import Callable, Dict, Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


class ExecutiveDashboardService:
    def __init__(self, db: Session, organization_id: int = 1):
        self.db = db
        self.organization_id = organization_id

    def _safe(self, name: str, fn: Callable) -> Dict:
        """מריץ פאנל ומחזיר תוצאה או שגיאה מבודדת."""
        try:
            return {"ok": True, "data": fn()}
        except Exception as exc:  # פאנל בודד לא מפיל את הדשבורד
            logger.exception("dashboard panel %s failed", name)
            return {"ok": False, "error": str(exc)}

    def build(
        self,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> Dict:
        end = end_date or date.today()
        start = start_date or end.replace(month=1, day=1)
        org = self.organization_id

        return {
            "period": {"start": start.isoformat(), "end": end.isoformat()},
            "panels": {
                "profit_loss": self._safe("profit_loss", lambda: self._profit_loss(start, end)),
                "bank_reconciliation": self._safe("bank_reconciliation", lambda: self._reconciliation(start, end)),
                "expense_overruns": self._safe("expense_overruns", lambda: self._overruns()),
                "budget_vs_actual": self._safe("budget_vs_actual", lambda: self._budget(end)),
                "profitability": self._safe("profitability", lambda: self._profitability(start, end)),
                "profitability_improvement": self._safe("profitability_improvement", lambda: self._improvement()),
                "fees": self._safe("fees", lambda: self._fees(start, end)),
                "ai_opportunities": self._safe("ai_opportunities", lambda: self._ai_opportunities()),
            },
        }

    # 1. רווח והפסד
    def _profit_loss(self, start, end):
        from .financial_reports_service import FinancialReportsService
        pl = FinancialReportsService(self.db).generate_profit_loss(
            self.organization_id, start, end, compare_previous=False
        )
        return {
            "total_revenue": float(pl.total_revenue or 0),
            "total_expenses": float(pl.total_expenses or 0),
            "gross_profit": float(pl.gross_profit or 0),
            "operating_income": float(pl.operating_income or 0),
            "net_income": float(pl.net_income or 0),
            "net_margin": float(pl.net_margin or 0),
        }

    # 2. פערי התאמת בנקים
    def _reconciliation(self, start, end):
        from .financial_control_service import FinancialControlService
        overview = FinancialControlService(
            self.db, organization_id=self.organization_id
        ).get_control_overview(start, end)
        return overview.get("control", overview)

    # 3. הוצאות שחרגו (חריגות תקציב)
    def _overruns(self):
        from .budget_service import BudgetService
        alerts = BudgetService(self.db, organization_id=self.organization_id).get_budget_alerts(80)
        return [vars(a) for a in alerts]

    # 4. ביצוע מול תקציב
    def _budget(self, end):
        from .budget_service import BudgetService
        summary = BudgetService(
            self.db, organization_id=self.organization_id
        ).get_budget_vs_actual(end.year, end.month)
        return {
            "total_budget": summary.total_budget,
            "total_actual": summary.total_actual,
            "total_variance": summary.total_variance,
            "variance_percentage": summary.variance_percentage,
            "categories": [vars(c) for c in summary.categories],
        }

    # 5. בדיקת רווחיות
    def _profitability(self, start, end):
        from .cost_analysis_service import CostAnalysisService
        from .cost_analysis_service import ProfitabilityDimension
        analysis = CostAnalysisService(
            self.db, organization_id=self.organization_id
        ).analyze_profitability(ProfitabilityDimension.CUSTOMER, start, end)
        return vars(analysis)

    # 6. בדיקת שיפור רווחיות
    def _improvement(self):
        from .ai_analytics_service import AdvancedAIService
        insights = AdvancedAIService(
            self.db, organization_id=self.organization_id
        ).generate_insights(focus_areas=["cost_saving", "revenue_opportunity"])
        return [vars(i) for i in insights]

    # 7. דוח עמלות
    def _fees(self, start, end):
        from .fees_service import FeesService
        return FeesService(
            self.db, organization_id=self.organization_id
        ).get_fees_report(start, end)

    # 8. מיפוי מקום לשיפור באמצעות AI
    def _ai_opportunities(self):
        from .ai_analytics_service import AdvancedAIService
        ai = AdvancedAIService(self.db, organization_id=self.organization_id)
        risks = ai.assess_financial_risks()
        insights = ai.generate_insights()
        return {
            "risks": [vars(r) for r in risks],
            "insights": [vars(i) for i in insights],
        }
