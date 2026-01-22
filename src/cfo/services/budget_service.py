"""
Budget Management Service
שירות ניהול תקציב ובקרה תקציבית
"""
from datetime import datetime, date
from decimal import Decimal
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict, field
from enum import Enum
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, extract

from ..models import Transaction, Account
from ..database import SessionLocal


class BudgetPeriod(str, Enum):
    """תקופת תקציב"""
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    YEARLY = "yearly"


class BudgetStatus(str, Enum):
    """סטטוס תקציב"""
    ON_TRACK = "on_track"
    WARNING = "warning"
    OVER_BUDGET = "over_budget"
    UNDER_BUDGET = "under_budget"


@dataclass
class BudgetCategory:
    """קטגוריית תקציב"""
    category_id: str
    category_name: str
    category_hebrew: str
    budget_amount: float
    actual_amount: float
    variance: float
    variance_percentage: float
    status: BudgetStatus
    forecast_end_of_period: float
    monthly_breakdown: List[Dict] = field(default_factory=list)


@dataclass
class BudgetSummary:
    """סיכום תקציב"""
    period: str
    period_start: str
    period_end: str
    total_budget: float
    total_actual: float
    total_variance: float
    variance_percentage: float
    status: BudgetStatus
    categories: List[BudgetCategory]
    alerts: List[Dict]


@dataclass
class BudgetAlert:
    """התראת תקציב"""
    alert_id: str
    category: str
    category_hebrew: str
    alert_type: str
    message: str
    severity: str  # low, medium, high, critical
    created_at: str
    budget_amount: float
    actual_amount: float
    variance_percentage: float


@dataclass
class ScenarioAnalysis:
    """ניתוח תרחישים"""
    scenario_name: str
    scenario_type: str  # best, worst, expected
    total_revenue: float
    total_expenses: float
    net_income: float
    cash_flow: float
    assumptions: Dict
    monthly_projections: List[Dict]


# מיפוי קטגוריות לעברית
BUDGET_CATEGORIES_HEBREW = {
    'revenue': 'הכנסות',
    'sales': 'מכירות',
    'services': 'שירותים',
    'salary': 'משכורות',
    'rent': 'שכירות',
    'utilities': 'חשמל/מים/גז',
    'marketing': 'שיווק ופרסום',
    'office': 'הוצאות משרד',
    'travel': 'נסיעות',
    'insurance': 'ביטוח',
    'professional': 'שירותים מקצועיים',
    'software': 'תוכנה ומחשוב',
    'equipment': 'ציוד',
    'maintenance': 'אחזקה',
    'taxes': 'מסים ואגרות',
    'finance': 'הוצאות מימון',
    'other_income': 'הכנסות אחרות',
    'other_expense': 'הוצאות אחרות'
}


class BudgetService:
    """
    שירות ניהול תקציב
    Budget Management Service
    """
    
    def __init__(self, db: Session, organization_id: int = 1):
        self.db = db
        self.organization_id = organization_id
        # אחסון תקציבים (בפרודקשן יהיה בDB)
        self._budgets: Dict[str, Dict] = {}
        self._alerts: List[BudgetAlert] = []
    
    def create_budget(
        self,
        year: int,
        period: BudgetPeriod,
        category_budgets: Dict[str, float],
        name: Optional[str] = None
    ) -> Dict:
        """
        יצירת תקציב חדש
        Create new budget
        """
        budget_id = f"{year}_{period.value}"
        if name:
            budget_id = f"{name}_{budget_id}"
        
        budget = {
            'id': budget_id,
            'name': name or f"תקציב {year}",
            'year': year,
            'period': period.value,
            'categories': category_budgets,
            'created_at': datetime.now().isoformat(),
            'updated_at': datetime.now().isoformat(),
            'status': 'active'
        }
        
        self._budgets[budget_id] = budget
        return budget
    
    def get_budget_vs_actual(
        self,
        year: int,
        month: Optional[int] = None,
        period: BudgetPeriod = BudgetPeriod.MONTHLY
    ) -> BudgetSummary:
        """
        השוואת תקציב מול ביצוע
        Budget vs Actual comparison
        """
        # קביעת טווח תאריכים
        if period == BudgetPeriod.MONTHLY and month:
            start_date = date(year, month, 1)
            if month == 12:
                end_date = date(year + 1, 1, 1)
            else:
                end_date = date(year, month + 1, 1)
            period_name = f"{year}-{month:02d}"
        elif period == BudgetPeriod.QUARTERLY and month:
            quarter = (month - 1) // 3 + 1
            start_month = (quarter - 1) * 3 + 1
            start_date = date(year, start_month, 1)
            end_month = start_month + 3
            if end_month > 12:
                end_date = date(year + 1, 1, 1)
            else:
                end_date = date(year, end_month, 1)
            period_name = f"Q{quarter}/{year}"
        else:
            start_date = date(year, 1, 1)
            end_date = date(year + 1, 1, 1)
            period_name = str(year)
        
        # שליפת נתוני ביצוע מהDB
        actuals = self._get_actual_by_category(start_date, end_date)
        
        # טעינת תקציב
        budget_id = f"{year}_{period.value}"
        budget_data = self._budgets.get(budget_id, {})
        category_budgets = budget_data.get('categories', self._get_default_budget())
        
        # חישוב לפי קטגוריה
        categories = []
        total_budget = 0
        total_actual = 0
        alerts = []
        
        for cat_id, budget_amount in category_budgets.items():
            actual_amount = actuals.get(cat_id, 0)
            variance = budget_amount - actual_amount
            variance_pct = (variance / budget_amount * 100) if budget_amount else 0
            
            # קביעת סטטוס
            if cat_id.startswith('revenue') or cat_id in ['sales', 'services', 'other_income']:
                # הכנסות - רוצים יותר
                if actual_amount >= budget_amount:
                    status = BudgetStatus.ON_TRACK
                elif actual_amount >= budget_amount * 0.8:
                    status = BudgetStatus.WARNING
                else:
                    status = BudgetStatus.UNDER_BUDGET
            else:
                # הוצאות - רוצים פחות
                if actual_amount <= budget_amount:
                    status = BudgetStatus.ON_TRACK
                elif actual_amount <= budget_amount * 1.1:
                    status = BudgetStatus.WARNING
                else:
                    status = BudgetStatus.OVER_BUDGET
            
            # חיזוי סוף תקופה
            days_passed = (datetime.now().date() - start_date).days
            total_days = (end_date - start_date).days
            if days_passed > 0 and total_days > 0:
                daily_rate = actual_amount / days_passed
                forecast = daily_rate * total_days
            else:
                forecast = actual_amount
            
            category = BudgetCategory(
                category_id=cat_id,
                category_name=cat_id,
                category_hebrew=BUDGET_CATEGORIES_HEBREW.get(cat_id, cat_id),
                budget_amount=budget_amount,
                actual_amount=actual_amount,
                variance=variance,
                variance_percentage=variance_pct,
                status=status,
                forecast_end_of_period=forecast
            )
            categories.append(category)
            
            total_budget += budget_amount
            total_actual += actual_amount
            
            # יצירת התראות
            if status == BudgetStatus.OVER_BUDGET:
                alerts.append({
                    'category': cat_id,
                    'category_hebrew': BUDGET_CATEGORIES_HEBREW.get(cat_id, cat_id),
                    'type': 'over_budget',
                    'message': f"חריגה מתקציב ב{abs(variance_pct):.1f}%",
                    'severity': 'high' if abs(variance_pct) > 20 else 'medium'
                })
            elif status == BudgetStatus.UNDER_BUDGET and cat_id in ['sales', 'revenue', 'services']:
                alerts.append({
                    'category': cat_id,
                    'category_hebrew': BUDGET_CATEGORIES_HEBREW.get(cat_id, cat_id),
                    'type': 'under_target',
                    'message': f"הכנסות נמוכות מהיעד ב{abs(variance_pct):.1f}%",
                    'severity': 'high' if abs(variance_pct) > 20 else 'medium'
                })
        
        # סטטוס כללי
        total_variance = total_budget - total_actual
        total_variance_pct = (total_variance / total_budget * 100) if total_budget else 0
        
        if abs(total_variance_pct) <= 5:
            overall_status = BudgetStatus.ON_TRACK
        elif total_variance_pct > 5:
            overall_status = BudgetStatus.UNDER_BUDGET
        else:
            overall_status = BudgetStatus.OVER_BUDGET
        
        return BudgetSummary(
            period=period_name,
            period_start=start_date.isoformat(),
            period_end=end_date.isoformat(),
            total_budget=total_budget,
            total_actual=total_actual,
            total_variance=total_variance,
            variance_percentage=total_variance_pct,
            status=overall_status,
            categories=categories,
            alerts=alerts
        )
    
    def get_budget_alerts(
        self,
        threshold_percentage: float = 10.0
    ) -> List[BudgetAlert]:
        """
        קבלת התראות תקציב
        Get budget alerts
        """
        now = datetime.now()
        summary = self.get_budget_vs_actual(
            year=now.year,
            month=now.month
        )
        
        alerts = []
        for cat in summary.categories:
            if abs(cat.variance_percentage) >= threshold_percentage:
                severity = 'critical' if abs(cat.variance_percentage) >= 30 else \
                          'high' if abs(cat.variance_percentage) >= 20 else \
                          'medium' if abs(cat.variance_percentage) >= 10 else 'low'
                
                alert = BudgetAlert(
                    alert_id=f"{cat.category_id}_{now.strftime('%Y%m')}",
                    category=cat.category_id,
                    category_hebrew=cat.category_hebrew,
                    alert_type='over_budget' if cat.status == BudgetStatus.OVER_BUDGET else 'variance',
                    message=self._generate_alert_message(cat),
                    severity=severity,
                    created_at=now.isoformat(),
                    budget_amount=cat.budget_amount,
                    actual_amount=cat.actual_amount,
                    variance_percentage=cat.variance_percentage
                )
                alerts.append(alert)
        
        return sorted(alerts, key=lambda x: abs(x.variance_percentage), reverse=True)
    
    def run_scenario_analysis(
        self,
        base_year: int,
        scenarios: List[str] = ['best', 'worst', 'expected']
    ) -> List[ScenarioAnalysis]:
        """
        ניתוח תרחישים
        Scenario Analysis
        """
        results = []
        
        # נתונים בסיסיים
        base_summary = self.get_budget_vs_actual(year=base_year)
        
        for scenario in scenarios:
            if scenario == 'best':
                revenue_factor = 1.2
                expense_factor = 0.9
                assumptions = {
                    'revenue_growth': '+20%',
                    'expense_reduction': '-10%',
                    'description': 'תרחיש אופטימי - גידול במכירות וצמצום הוצאות'
                }
            elif scenario == 'worst':
                revenue_factor = 0.8
                expense_factor = 1.15
                assumptions = {
                    'revenue_growth': '-20%',
                    'expense_increase': '+15%',
                    'description': 'תרחיש פסימי - ירידה במכירות ועלייה בהוצאות'
                }
            else:  # expected
                revenue_factor = 1.05
                expense_factor = 1.03
                assumptions = {
                    'revenue_growth': '+5%',
                    'expense_increase': '+3%',
                    'description': 'תרחיש צפוי - צמיחה מתונה'
                }
            
            # חישוב
            revenue_cats = [c for c in base_summary.categories 
                          if c.category_id in ['sales', 'revenue', 'services', 'other_income']]
            expense_cats = [c for c in base_summary.categories 
                          if c.category_id not in ['sales', 'revenue', 'services', 'other_income']]
            
            total_revenue = sum(c.actual_amount for c in revenue_cats) * revenue_factor
            total_expenses = sum(c.actual_amount for c in expense_cats) * expense_factor
            net_income = total_revenue - total_expenses
            
            # תחזית חודשית
            monthly = []
            for month in range(1, 13):
                monthly.append({
                    'month': f"{base_year}-{month:02d}",
                    'revenue': total_revenue / 12,
                    'expenses': total_expenses / 12,
                    'net': net_income / 12
                })
            
            results.append(ScenarioAnalysis(
                scenario_name=f"תרחיש {scenario}",
                scenario_type=scenario,
                total_revenue=total_revenue,
                total_expenses=total_expenses,
                net_income=net_income,
                cash_flow=net_income * 0.8,  # הנחה גסה
                assumptions=assumptions,
                monthly_projections=monthly
            ))
        
        return results
    
    def get_budget_trend(
        self,
        category_id: str,
        months: int = 12
    ) -> List[Dict]:
        """
        מגמת תקציב לאורך זמן
        Budget trend over time
        """
        now = datetime.now()
        trend = []
        
        for i in range(months - 1, -1, -1):
            month = now.month - i
            year = now.year
            while month <= 0:
                month += 12
                year -= 1
            
            summary = self.get_budget_vs_actual(year=year, month=month)
            cat = next((c for c in summary.categories if c.category_id == category_id), None)
            
            if cat:
                trend.append({
                    'period': f"{year}-{month:02d}",
                    'budget': cat.budget_amount,
                    'actual': cat.actual_amount,
                    'variance': cat.variance,
                    'variance_percentage': cat.variance_percentage
                })
        
        return trend
    
    def _get_actual_by_category(
        self,
        start_date: date,
        end_date: date
    ) -> Dict[str, float]:
        """שליפת ביצוע בפועל לפי קטגוריה"""
        try:
            transactions = self.db.query(Transaction).filter(
                Transaction.organization_id == self.organization_id,
                Transaction.date >= start_date,
                Transaction.date < end_date
            ).all()
            
            actuals = {}
            for tx in transactions:
                category = self._categorize_transaction(tx)
                actuals[category] = actuals.get(category, 0) + float(tx.amount)
            
            return actuals
        except Exception:
            return self._get_sample_actuals()
    
    def _categorize_transaction(self, tx: Transaction) -> str:
        """קטגוריזציה של עסקה"""
        description = (tx.description or '').lower()
        
        # מיפוי מילות מפתח לקטגוריות
        keywords = {
            'salary': ['משכורת', 'שכר', 'salary'],
            'rent': ['שכירות', 'rent'],
            'utilities': ['חשמל', 'מים', 'גז', 'ארנונה'],
            'marketing': ['פרסום', 'שיווק', 'marketing', 'google', 'facebook'],
            'software': ['תוכנה', 'software', 'saas', 'subscription'],
            'insurance': ['ביטוח', 'insurance'],
            'professional': ['עו"ד', 'רו"ח', 'יועץ', 'consultant'],
            'office': ['משרד', 'office', 'supplies'],
            'travel': ['נסיעות', 'דלק', 'travel'],
            'sales': ['מכירה', 'הכנסה', 'revenue', 'sale']
        }
        
        for category, words in keywords.items():
            if any(word in description for word in words):
                return category
        
        return 'other_expense' if tx.amount < 0 else 'other_income'
    
    def _get_default_budget(self) -> Dict[str, float]:
        """תקציב ברירת מחדל"""
        return {
            'sales': 500000,
            'services': 200000,
            'other_income': 50000,
            'salary': 180000,
            'rent': 25000,
            'utilities': 5000,
            'marketing': 30000,
            'software': 10000,
            'office': 5000,
            'travel': 8000,
            'insurance': 3000,
            'professional': 15000,
            'other_expense': 20000
        }
    
    def _get_sample_actuals(self) -> Dict[str, float]:
        """נתוני דוגמה"""
        import random
        base = self._get_default_budget()
        return {k: v * random.uniform(0.7, 1.3) for k, v in base.items()}
    
    def _generate_alert_message(self, cat: BudgetCategory) -> str:
        """יצירת הודעת התראה"""
        if cat.status == BudgetStatus.OVER_BUDGET:
            return f"חריגה בקטגוריית {cat.category_hebrew}: ₪{abs(cat.variance):,.0f} מעל התקציב ({abs(cat.variance_percentage):.1f}%)"
        elif cat.status == BudgetStatus.UNDER_BUDGET:
            return f"ביצוע נמוך בקטגוריית {cat.category_hebrew}: ₪{abs(cat.variance):,.0f} מתחת ליעד ({abs(cat.variance_percentage):.1f}%)"
        elif cat.status == BudgetStatus.WARNING:
            return f"אזהרה בקטגוריית {cat.category_hebrew}: מתקרבים לחריגה ({abs(cat.variance_percentage):.1f}%)"
        return ""
    
    def to_dict(self, obj) -> Dict:
        """המרה ל-dict"""
        if hasattr(obj, 'to_dict'):
            return obj.to_dict()
        return asdict(obj)
