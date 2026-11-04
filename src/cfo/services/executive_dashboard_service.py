"""
דשבורד מנהלים מאוחד — מרכז את כל מדדי מצב העסק לתצוגה אחת.
Executive dashboard: aggregates the 8 business-health panels, each isolated so
a failure in one never breaks the whole dashboard.
"""
import logging
import time
from datetime import date
from typing import Callable, Dict, Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


NO_ACTUAL_HE = "אין ביצוע בפועל לחודש. הסטייה חסרה, לא 100%."


def budget_panel(summary) -> Dict:
    """Budget vs actual. With no actual there is no variance: חסר, not 100%."""
    def row(category) -> Dict:
        found = dict(vars(category))
        if not found.get("actual_amount"):
            found.update(actual_amount=None, variance=None, variance_percentage=None)
        return found

    known = bool(summary.total_actual)
    return {
        "total_budget": summary.total_budget,
        "total_actual": summary.total_actual if known else None,
        "total_variance": summary.total_variance if known else None,
        "variance_percentage": summary.variance_percentage if known else None,
        "missing_label_he": None if known else NO_ACTUAL_HE,
        "categories": [row(c) for c in summary.categories],
    }


class ExecutiveDashboardService:
    def __init__(self, db: Session, organization_id: int = 1):
        self.db = db
        self.organization_id = organization_id
        self._insights_cache = None

    def _safe(self, name: str, fn: Callable) -> Dict:
        """מריץ פאנל ומחזיר תוצאה או שגיאה מבודדת, עם זמן הריצה שלו (לאבחון איטיות)."""
        started = time.perf_counter()
        try:
            result = {"ok": True, "data": fn()}
        except Exception as exc:  # פאנל בודד לא מפיל את הדשבורד
            logger.exception("dashboard panel %s failed", name)
            result = {"ok": False, "error": str(exc)}
        result["elapsed_ms"] = round((time.perf_counter() - started) * 1000)
        return result

    def _insights(self):
        """All insights, computed once per dashboard. Panels 6 and 8 used to compute them separately."""
        if self._insights_cache is None:
            from .ai_analytics_service import AdvancedAIService
            self._insights_cache = AdvancedAIService(
                self.db, organization_id=self.organization_id
            ).generate_insights()
        return self._insights_cache

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
                "checking": self._safe("checking", lambda: self._checking()),
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
        from .dashboards.period_compare import books_pnl_summary
        return books_pnl_summary(self.db, self.organization_id, start, end)

    # עו״ש, מסגרות והלוואות: אותה תמונה כמו בדשבורד וב-/cashflow
    def _checking(self):
        from .dashboards.money_screens import checking_and_loans
        return checking_and_loans(self.db, self.organization_id)

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
        return budget_panel(summary)

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
        focus = {"cost_saving", "revenue_opportunity"}
        return [vars(i) for i in self._insights() if i.insight_type.value in focus]

    # 7. דוח עמלות
    def _fees(self, start, end):
        from .fees_service import FeesService
        return FeesService(
            self.db, organization_id=self.organization_id
        ).get_fees_report(start, end)

    # 8. מיפוי מקום לשיפור באמצעות AI
    def _ai_opportunities(self):
        from .ai_analytics_service import AdvancedAIService
        risks = AdvancedAIService(self.db, organization_id=self.organization_id).assess_financial_risks()
        return {
            "risks": [vars(r) for r in risks],
            "insights": [vars(i) for i in self._insights()],
        }
