"""
KPI & Executive Dashboard Service
שירות מדדי ביצוע ודשבורד מנהלים
"""
from datetime import datetime, date, timedelta
from decimal import Decimal
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict, field
from enum import Enum
from sqlalchemy.orm import Session
from sqlalchemy import func, and_

from ..models import Transaction, Account
from ..database import SessionLocal


class KPICategory(str, Enum):
    """קטגוריית KPI"""
    PROFITABILITY = "profitability"
    LIQUIDITY = "liquidity"
    EFFICIENCY = "efficiency"
    LEVERAGE = "leverage"
    GROWTH = "growth"


class TrendDirection(str, Enum):
    """כיוון מגמה"""
    UP = "up"
    DOWN = "down"
    STABLE = "stable"


class KPIStatus(str, Enum):
    """סטטוס KPI"""
    EXCELLENT = "excellent"
    GOOD = "good"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class KPIValue:
    """ערך KPI"""
    kpi_id: str
    name: str
    name_hebrew: str
    category: KPICategory
    value: float
    formatted_value: str
    unit: str
    target: Optional[float]
    target_formatted: Optional[str]
    variance_from_target: Optional[float]
    previous_value: Optional[float]
    change_percentage: float
    trend: TrendDirection
    status: KPIStatus
    description: str
    formula: str
    benchmark_industry: Optional[float]


@dataclass
class KPIDashboard:
    """דשבורד KPIs"""
    as_of_date: str
    period: str
    kpis: List[KPIValue]
    summary: Dict
    alerts: List[Dict]
    trends: List[Dict]


@dataclass
class FinancialSnapshot:
    """תמונת מצב פיננסית"""
    date: str
    revenue_mtd: float
    revenue_ytd: float
    expenses_mtd: float
    expenses_ytd: float
    net_income_mtd: float
    net_income_ytd: float
    cash_balance: float
    receivables: float
    payables: float
    working_capital: float
    burn_rate: float
    runway_months: float


@dataclass
class ExecutiveSummary:
    """סיכום מנהלים"""
    period: str
    generated_at: str
    financial_snapshot: FinancialSnapshot
    key_kpis: List[KPIValue]
    achievements: List[str]
    concerns: List[str]
    action_items: List[Dict]
    comparison_to_budget: Dict
    comparison_to_previous: Dict


# הגדרות KPIs
KPI_DEFINITIONS = {
    # רווחיות
    'gross_margin': {
        'name': 'Gross Margin',
        'name_hebrew': 'מרווח גולמי',
        'category': KPICategory.PROFITABILITY,
        'unit': '%',
        'formula': '(הכנסות - עלות מכר) / הכנסות × 100',
        'description': 'אחוז הרווח הגולמי מההכנסות',
        'target': 40,
        'benchmark': 35,
        'higher_is_better': True
    },
    'net_margin': {
        'name': 'Net Margin',
        'name_hebrew': 'מרווח נקי',
        'category': KPICategory.PROFITABILITY,
        'unit': '%',
        'formula': 'רווח נקי / הכנסות × 100',
        'description': 'אחוז הרווח הנקי מההכנסות',
        'target': 15,
        'benchmark': 10,
        'higher_is_better': True
    },
    'operating_margin': {
        'name': 'Operating Margin',
        'name_hebrew': 'מרווח תפעולי',
        'category': KPICategory.PROFITABILITY,
        'unit': '%',
        'formula': 'רווח תפעולי / הכנסות × 100',
        'description': 'אחוז הרווח התפעולי',
        'target': 20,
        'benchmark': 15,
        'higher_is_better': True
    },
    'ebitda_margin': {
        'name': 'EBITDA Margin',
        'name_hebrew': 'מרווח EBITDA',
        'category': KPICategory.PROFITABILITY,
        'unit': '%',
        'formula': 'EBITDA / הכנסות × 100',
        'description': 'רווח לפני ריבית, מס, פחת והפחתות',
        'target': 25,
        'benchmark': 20,
        'higher_is_better': True
    },
    'roe': {
        'name': 'Return on Equity',
        'name_hebrew': 'תשואה על ההון',
        'category': KPICategory.PROFITABILITY,
        'unit': '%',
        'formula': 'רווח נקי / הון עצמי × 100',
        'description': 'תשואה על ההון העצמי',
        'target': 15,
        'benchmark': 12,
        'higher_is_better': True
    },
    'roa': {
        'name': 'Return on Assets',
        'name_hebrew': 'תשואה על הנכסים',
        'category': KPICategory.PROFITABILITY,
        'unit': '%',
        'formula': 'רווח נקי / סך נכסים × 100',
        'description': 'תשואה על סך הנכסים',
        'target': 10,
        'benchmark': 8,
        'higher_is_better': True
    },
    
    # נזילות
    'current_ratio': {
        'name': 'Current Ratio',
        'name_hebrew': 'יחס שוטף',
        'category': KPICategory.LIQUIDITY,
        'unit': 'x',
        'formula': 'נכסים שוטפים / התחייבויות שוטפות',
        'description': 'יכולת לשלם התחייבויות שוטפות',
        'target': 2.0,
        'benchmark': 1.5,
        'higher_is_better': True
    },
    'quick_ratio': {
        'name': 'Quick Ratio',
        'name_hebrew': 'יחס מהיר',
        'category': KPICategory.LIQUIDITY,
        'unit': 'x',
        'formula': '(נכסים שוטפים - מלאי) / התחייבויות שוטפות',
        'description': 'יכולת לשלם מיידית',
        'target': 1.5,
        'benchmark': 1.0,
        'higher_is_better': True
    },
    'cash_ratio': {
        'name': 'Cash Ratio',
        'name_hebrew': 'יחס מזומנים',
        'category': KPICategory.LIQUIDITY,
        'unit': 'x',
        'formula': 'מזומן / התחייבויות שוטפות',
        'description': 'יכולת לשלם במזומן',
        'target': 0.5,
        'benchmark': 0.3,
        'higher_is_better': True
    },
    
    # יעילות
    'asset_turnover': {
        'name': 'Asset Turnover',
        'name_hebrew': 'מחזור נכסים',
        'category': KPICategory.EFFICIENCY,
        'unit': 'x',
        'formula': 'הכנסות / ממוצע נכסים',
        'description': 'יעילות השימוש בנכסים',
        'target': 2.0,
        'benchmark': 1.5,
        'higher_is_better': True
    },
    'dso': {
        'name': 'Days Sales Outstanding',
        'name_hebrew': 'ימי גבייה',
        'category': KPICategory.EFFICIENCY,
        'unit': 'ימים',
        'formula': '(חייבים / הכנסות) × 365',
        'description': 'זמן ממוצע לגביית חובות',
        'target': 30,
        'benchmark': 45,
        'higher_is_better': False
    },
    'dpo': {
        'name': 'Days Payable Outstanding',
        'name_hebrew': 'ימי תשלום לספקים',
        'category': KPICategory.EFFICIENCY,
        'unit': 'ימים',
        'formula': '(זכאים / רכישות) × 365',
        'description': 'זמן ממוצע לתשלום לספקים',
        'target': 45,
        'benchmark': 30,
        'higher_is_better': True
    },
    'inventory_turnover': {
        'name': 'Inventory Turnover',
        'name_hebrew': 'מחזור מלאי',
        'category': KPICategory.EFFICIENCY,
        'unit': 'x',
        'formula': 'עלות מכר / ממוצע מלאי',
        'description': 'כמה פעמים המלאי מתחלף בשנה',
        'target': 6,
        'benchmark': 4,
        'higher_is_better': True
    },
    
    # מינוף
    'debt_to_equity': {
        'name': 'Debt to Equity',
        'name_hebrew': 'חוב להון',
        'category': KPICategory.LEVERAGE,
        'unit': 'x',
        'formula': 'סך חוב / הון עצמי',
        'description': 'יחס המינוף של החברה',
        'target': 1.0,
        'benchmark': 1.5,
        'higher_is_better': False
    },
    'interest_coverage': {
        'name': 'Interest Coverage',
        'name_hebrew': 'יחס כיסוי ריבית',
        'category': KPICategory.LEVERAGE,
        'unit': 'x',
        'formula': 'EBIT / הוצאות ריבית',
        'description': 'יכולת לשלם ריביות',
        'target': 5,
        'benchmark': 3,
        'higher_is_better': True
    },
    
    # צמיחה
    'revenue_growth': {
        'name': 'Revenue Growth',
        'name_hebrew': 'צמיחה בהכנסות',
        'category': KPICategory.GROWTH,
        'unit': '%',
        'formula': '(הכנסות נוכחי - הכנסות קודם) / הכנסות קודם × 100',
        'description': 'שיעור צמיחת ההכנסות',
        'target': 20,
        'benchmark': 10,
        'higher_is_better': True
    },
    'profit_growth': {
        'name': 'Profit Growth',
        'name_hebrew': 'צמיחה ברווח',
        'category': KPICategory.GROWTH,
        'unit': '%',
        'formula': '(רווח נוכחי - רווח קודם) / רווח קודם × 100',
        'description': 'שיעור צמיחת הרווח',
        'target': 15,
        'benchmark': 8,
        'higher_is_better': True
    },
    'customer_growth': {
        'name': 'Customer Growth',
        'name_hebrew': 'צמיחה בלקוחות',
        'category': KPICategory.GROWTH,
        'unit': '%',
        'formula': '(לקוחות חדשים - לקוחות שעזבו) / לקוחות × 100',
        'description': 'שיעור גידול נטו בלקוחות',
        'target': 10,
        'benchmark': 5,
        'higher_is_better': True
    }
}


class KPIService:
    """
    שירות מדדי ביצוע
    KPI Service
    """
    
    def __init__(self, db: Session, organization_id: int = 1):
        self.db = db
        self.organization_id = organization_id
    
    def get_kpi_dashboard(
        self,
        period: str = 'monthly',
        as_of_date: Optional[date] = None
    ) -> KPIDashboard:
        """
        קבלת דשבורד KPIs
        Get KPI Dashboard
        """
        if not as_of_date:
            as_of_date = date.today()
        
        # חישוב כל ה-KPIs
        kpis = []
        alerts = []
        
        # נתונים פיננסיים (בפרודקשן - מDB)
        financial_data = self._get_financial_data(as_of_date, period)
        previous_data = self._get_financial_data(
            as_of_date - timedelta(days=30 if period == 'monthly' else 365),
            period
        )
        
        for kpi_id, definition in KPI_DEFINITIONS.items():
            value = self._calculate_kpi(kpi_id, financial_data)
            previous_value = self._calculate_kpi(kpi_id, previous_data)
            
            # חישוב שינוי
            if previous_value and previous_value != 0:
                change_pct = ((value - previous_value) / abs(previous_value)) * 100
            else:
                change_pct = 0
            
            # קביעת מגמה
            if change_pct > 2:
                trend = TrendDirection.UP
            elif change_pct < -2:
                trend = TrendDirection.DOWN
            else:
                trend = TrendDirection.STABLE
            
            # קביעת סטטוס
            target = definition.get('target')
            higher_is_better = definition.get('higher_is_better', True)
            
            if target:
                if higher_is_better:
                    if value >= target * 1.1:
                        status = KPIStatus.EXCELLENT
                    elif value >= target:
                        status = KPIStatus.GOOD
                    elif value >= target * 0.8:
                        status = KPIStatus.WARNING
                    else:
                        status = KPIStatus.CRITICAL
                else:
                    if value <= target * 0.9:
                        status = KPIStatus.EXCELLENT
                    elif value <= target:
                        status = KPIStatus.GOOD
                    elif value <= target * 1.2:
                        status = KPIStatus.WARNING
                    else:
                        status = KPIStatus.CRITICAL
            else:
                status = KPIStatus.GOOD
            
            # עיצוב הערך
            if definition['unit'] == '%':
                formatted = f"{value:.1f}%"
                target_formatted = f"{target:.1f}%" if target else None
            elif definition['unit'] == 'x':
                formatted = f"{value:.2f}x"
                target_formatted = f"{target:.2f}x" if target else None
            elif definition['unit'] == 'ימים':
                formatted = f"{value:.0f} ימים"
                target_formatted = f"{target:.0f} ימים" if target else None
            else:
                formatted = f"{value:,.0f}"
                target_formatted = f"{target:,.0f}" if target else None
            
            variance = ((value - target) / target * 100) if target else None
            
            kpi = KPIValue(
                kpi_id=kpi_id,
                name=definition['name'],
                name_hebrew=definition['name_hebrew'],
                category=definition['category'],
                value=value,
                formatted_value=formatted,
                unit=definition['unit'],
                target=target,
                target_formatted=target_formatted,
                variance_from_target=variance,
                previous_value=previous_value,
                change_percentage=change_pct,
                trend=trend,
                status=status,
                description=definition['description'],
                formula=definition['formula'],
                benchmark_industry=definition.get('benchmark')
            )
            kpis.append(kpi)
            
            # יצירת התראות
            if status == KPIStatus.CRITICAL:
                alerts.append({
                    'kpi': kpi_id,
                    'kpi_hebrew': definition['name_hebrew'],
                    'severity': 'critical',
                    'message': f"⚠️ {definition['name_hebrew']} במצב קריטי: {formatted}",
                    'value': value,
                    'target': target
                })
            elif status == KPIStatus.WARNING:
                alerts.append({
                    'kpi': kpi_id,
                    'kpi_hebrew': definition['name_hebrew'],
                    'severity': 'warning',
                    'message': f"⚡ {definition['name_hebrew']} דורש תשומת לב: {formatted}",
                    'value': value,
                    'target': target
                })
        
        # סיכום לפי קטגוריה
        summary = {}
        for category in KPICategory:
            cat_kpis = [k for k in kpis if k.category == category]
            summary[category.value] = {
                'count': len(cat_kpis),
                'excellent': len([k for k in cat_kpis if k.status == KPIStatus.EXCELLENT]),
                'good': len([k for k in cat_kpis if k.status == KPIStatus.GOOD]),
                'warning': len([k for k in cat_kpis if k.status == KPIStatus.WARNING]),
                'critical': len([k for k in cat_kpis if k.status == KPIStatus.CRITICAL])
            }
        
        # מגמות
        trends = [
            {
                'kpi': k.kpi_id,
                'name_hebrew': k.name_hebrew,
                'trend': k.trend.value,
                'change': k.change_percentage
            }
            for k in kpis
            if abs(k.change_percentage) > 5
        ]
        
        return KPIDashboard(
            as_of_date=as_of_date.isoformat(),
            period=period,
            kpis=kpis,
            summary=summary,
            alerts=alerts,
            trends=trends
        )
    
    def get_executive_summary(
        self,
        period: str = 'monthly'
    ) -> ExecutiveSummary:
        """
        סיכום מנהלים
        Executive Summary
        """
        today = date.today()
        
        # תמונת מצב פיננסית
        snapshot = self._get_financial_snapshot(today)
        
        # KPIs מרכזיים
        dashboard = self.get_kpi_dashboard(period, today)
        key_kpis = [
            k for k in dashboard.kpis
            if k.kpi_id in ['gross_margin', 'net_margin', 'current_ratio', 'dso', 'revenue_growth']
        ]
        
        # הישגים
        achievements = [
            f"✅ {k.name_hebrew} עלה ב-{k.change_percentage:.1f}%"
            for k in dashboard.kpis
            if k.change_percentage > 10 and k.status in [KPIStatus.EXCELLENT, KPIStatus.GOOD]
        ]
        
        # חששות
        concerns = [
            f"⚠️ {k.name_hebrew} ירד ב-{abs(k.change_percentage):.1f}%"
            for k in dashboard.kpis
            if k.change_percentage < -10 or k.status == KPIStatus.CRITICAL
        ]
        
        # פעולות נדרשות
        action_items = []
        for alert in dashboard.alerts:
            action_items.append({
                'priority': 'high' if alert['severity'] == 'critical' else 'medium',
                'area': alert['kpi_hebrew'],
                'action': f"לטפל ב{alert['kpi_hebrew']} - ערך נוכחי: {alert['value']:.1f}",
                'deadline': (today + timedelta(days=7 if alert['severity'] == 'critical' else 14)).isoformat()
            })
        
        # השוואה לתקציב
        budget_comparison = {
            'revenue': {'budget': 500000, 'actual': snapshot.revenue_mtd, 'variance': 0},
            'expenses': {'budget': 400000, 'actual': snapshot.expenses_mtd, 'variance': 0}
        }
        budget_comparison['revenue']['variance'] = (
            (budget_comparison['revenue']['actual'] - budget_comparison['revenue']['budget']) 
            / budget_comparison['revenue']['budget'] * 100
        )
        budget_comparison['expenses']['variance'] = (
            (budget_comparison['expenses']['actual'] - budget_comparison['expenses']['budget'])
            / budget_comparison['expenses']['budget'] * 100
        )
        
        # השוואה לתקופה קודמת
        previous_comparison = {
            'revenue_change': 8.5,
            'expenses_change': 5.2,
            'profit_change': 12.3
        }
        
        return ExecutiveSummary(
            period=period,
            generated_at=datetime.now().isoformat(),
            financial_snapshot=snapshot,
            key_kpis=key_kpis,
            achievements=achievements[:5],
            concerns=concerns[:5],
            action_items=action_items[:5],
            comparison_to_budget=budget_comparison,
            comparison_to_previous=previous_comparison
        )
    
    def get_kpi_trend(
        self,
        kpi_id: str,
        months: int = 12
    ) -> List[Dict]:
        """
        מגמת KPI לאורך זמן
        KPI Trend over time
        """
        trend = []
        today = date.today()
        
        for i in range(months - 1, -1, -1):
            month_date = today - timedelta(days=i * 30)
            financial_data = self._get_financial_data(month_date, 'monthly')
            value = self._calculate_kpi(kpi_id, financial_data)
            
            definition = KPI_DEFINITIONS.get(kpi_id, {})
            
            trend.append({
                'month': month_date.strftime('%Y-%m'),
                'value': value,
                'target': definition.get('target'),
                'benchmark': definition.get('benchmark')
            })
        
        return trend
    
    def compare_to_industry(
        self,
        industry: str = 'technology'
    ) -> List[Dict]:
        """
        השוואה לממוצע הענף
        Industry Comparison
        """
        dashboard = self.get_kpi_dashboard()
        comparison = []
        
        for kpi in dashboard.kpis:
            if kpi.benchmark_industry:
                diff = kpi.value - kpi.benchmark_industry
                comparison.append({
                    'kpi': kpi.kpi_id,
                    'name_hebrew': kpi.name_hebrew,
                    'our_value': kpi.value,
                    'industry_average': kpi.benchmark_industry,
                    'difference': diff,
                    'better_than_average': (diff > 0) == KPI_DEFINITIONS[kpi.kpi_id].get('higher_is_better', True)
                })
        
        return comparison
    
    def _calculate_kpi(self, kpi_id: str, data: Dict) -> float:
        """חישוב KPI"""
        try:
            if kpi_id == 'gross_margin':
                return ((data['revenue'] - data['cogs']) / data['revenue'] * 100) if data['revenue'] else 0
            elif kpi_id == 'net_margin':
                return (data['net_income'] / data['revenue'] * 100) if data['revenue'] else 0
            elif kpi_id == 'operating_margin':
                return (data['operating_income'] / data['revenue'] * 100) if data['revenue'] else 0
            elif kpi_id == 'ebitda_margin':
                ebitda = data['operating_income'] + data.get('depreciation', 0)
                return (ebitda / data['revenue'] * 100) if data['revenue'] else 0
            elif kpi_id == 'roe':
                return (data['net_income'] / data['equity'] * 100) if data['equity'] else 0
            elif kpi_id == 'roa':
                return (data['net_income'] / data['total_assets'] * 100) if data['total_assets'] else 0
            elif kpi_id == 'current_ratio':
                return data['current_assets'] / data['current_liabilities'] if data['current_liabilities'] else 0
            elif kpi_id == 'quick_ratio':
                return (data['current_assets'] - data.get('inventory', 0)) / data['current_liabilities'] if data['current_liabilities'] else 0
            elif kpi_id == 'cash_ratio':
                return data['cash'] / data['current_liabilities'] if data['current_liabilities'] else 0
            elif kpi_id == 'asset_turnover':
                return data['revenue'] / data['total_assets'] if data['total_assets'] else 0
            elif kpi_id == 'dso':
                return (data['receivables'] / data['revenue'] * 365) if data['revenue'] else 0
            elif kpi_id == 'dpo':
                return (data['payables'] / data.get('purchases', data['cogs']) * 365) if data.get('purchases', data['cogs']) else 0
            elif kpi_id == 'inventory_turnover':
                return data['cogs'] / data.get('inventory', 1) if data.get('inventory', 1) else 0
            elif kpi_id == 'debt_to_equity':
                return data.get('total_debt', 0) / data['equity'] if data['equity'] else 0
            elif kpi_id == 'interest_coverage':
                return data['operating_income'] / data.get('interest_expense', 1) if data.get('interest_expense', 1) else 10
            elif kpi_id == 'revenue_growth':
                return data.get('revenue_growth', 8.5)
            elif kpi_id == 'profit_growth':
                return data.get('profit_growth', 5.2)
            elif kpi_id == 'customer_growth':
                return data.get('customer_growth', 3.5)
            else:
                return 0
        except (ZeroDivisionError, KeyError):
            return 0
    
    def _period_start(self, as_of_date: date, period: str) -> date:
        if period == "monthly":
            return as_of_date.replace(day=1)
        if period == "quarterly":
            q_start = ((as_of_date.month - 1) // 3) * 3 + 1
            return as_of_date.replace(month=q_start, day=1)
        return as_of_date.replace(month=1, day=1)  # yearly / ytd

    def _balance_snapshot(self) -> Dict:
        """מצב נכסים/התחייבויות נוכחי — מקור אמת משותף עם דוח הבנק."""
        from .balance_snapshot import compute_balance_snapshot
        return compute_balance_snapshot(self.db, self.organization_id)

    def _get_financial_data(self, as_of_date: date, period: str) -> Dict:
        """שליפת נתונים פיננסיים אמיתיים (P&L + מצב מאזני) מהדאטאבייס."""
        from .financial_reports_service import FinancialReportsService

        start = self._period_start(as_of_date, period)
        reports = FinancialReportsService(self.db)
        pl = reports.generate_profit_loss(
            self.organization_id, start, as_of_date, compare_previous=False
        )

        revenue = float(pl.total_revenue or 0)
        cogs = float((pl.total_revenue or 0) - (pl.gross_profit or 0))
        operating_income = float(pl.operating_income or 0)
        net_income = float(pl.net_income or 0)

        bal = self._balance_snapshot()

        # צמיחה מול התקופה הקודמת באותו אורך
        span = max(1, (as_of_date - start).days)
        prev_end = start - timedelta(days=1)
        prev_start = prev_end - timedelta(days=span)
        prev_pl = reports.generate_profit_loss(
            self.organization_id, prev_start, prev_end, compare_previous=False
        )
        prev_rev = float(prev_pl.total_revenue or 0)
        prev_profit = float(prev_pl.net_income or 0)
        revenue_growth = ((revenue - prev_rev) / prev_rev * 100) if prev_rev else 0.0
        profit_growth = ((net_income - prev_profit) / prev_profit * 100) if prev_profit else 0.0

        return {
            "revenue": revenue,
            "cogs": cogs,
            "operating_income": operating_income,
            "net_income": net_income,
            "total_assets": bal["total_assets"],
            "current_assets": bal["current_assets"],
            "current_liabilities": bal["current_liabilities"],
            "equity": bal["equity"],
            "cash": bal["cash"],
            "receivables": bal["receivables"],
            "payables": bal["payables"],
            "inventory": bal["inventory"],
            "depreciation": 0.0,        # אין רישום פחת נפרד
            "total_debt": bal["total_debt"],
            "interest_expense": 0.0,    # אין רישום הוצאות ריבית נפרד
            "purchases": cogs,
            "revenue_growth": revenue_growth,
            "profit_growth": profit_growth,
            "customer_growth": 0.0,     # דורש snapshot היסטורי של לקוחות
        }

    def _get_financial_snapshot(self, as_of_date: date) -> FinancialSnapshot:
        """תמונת מצב פיננסית אמיתית (MTD + YTD)."""
        mtd = self._get_financial_data(as_of_date, "monthly")
        ytd = self._get_financial_data(as_of_date, "yearly")
        expenses_mtd = mtd["revenue"] - mtd["net_income"]
        expenses_ytd = ytd["revenue"] - ytd["net_income"]
        burn_rate = expenses_mtd - mtd["revenue"]  # חיובי = שריפת מזומן
        runway = (mtd["cash"] / burn_rate) if burn_rate > 0 else 999

        return FinancialSnapshot(
            date=as_of_date.isoformat(),
            revenue_mtd=mtd["revenue"],
            revenue_ytd=ytd["revenue"],
            expenses_mtd=expenses_mtd,
            expenses_ytd=expenses_ytd,
            net_income_mtd=mtd["net_income"],
            net_income_ytd=ytd["net_income"],
            cash_balance=mtd["cash"],
            receivables=mtd["receivables"],
            payables=mtd["payables"],
            working_capital=mtd["current_assets"] - mtd["current_liabilities"],
            burn_rate=burn_rate,
            runway_months=runway,
        )
