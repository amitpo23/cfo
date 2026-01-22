"""
Financial Forecasting Service
שירות תחזיות פיננסיות
"""
from typing import List, Optional, Dict, Any, Tuple
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum
from dataclasses import dataclass
import numpy as np
from sqlalchemy.orm import Session
from sqlalchemy import and_, func

from ..models import Transaction, TransactionType


class ForecastMethod(str, Enum):
    """שיטות תחזית"""
    EXPONENTIAL_SMOOTHING = "exponential_smoothing"
    MOVING_AVERAGE = "moving_average"
    LINEAR_REGRESSION = "linear_regression"
    SEASONAL = "seasonal"
    ENSEMBLE = "ensemble"


@dataclass
class ForecastResult:
    """תוצאת תחזית"""
    date: datetime
    predicted_value: float
    lower_bound: float  # גבול תחתון
    upper_bound: float  # גבול עליון
    confidence: float  # רמת ביטחון 0-1


@dataclass
class ForecastMetrics:
    """מטריקות דיוק תחזית"""
    mae: float  # Mean Absolute Error
    mape: float  # Mean Absolute Percentage Error
    rmse: float  # Root Mean Squared Error
    r2: float  # R-squared


@dataclass
class BudgetVariance:
    """סטיית תקציב"""
    category: str
    budgeted: float
    actual: float
    variance: float
    variance_percent: float
    is_favorable: bool


class ForecastingService:
    """
    שירות תחזיות פיננסיות
    מספק תחזיות הכנסות, הוצאות ותזרים מזומנים
    """
    
    def __init__(self, db: Session):
        self.db = db
    
    # ============= Main Forecasting Methods =============
    
    def forecast_revenue(
        self,
        organization_id: int,
        periods: int = 12,
        method: ForecastMethod = ForecastMethod.EXPONENTIAL_SMOOTHING
    ) -> List[ForecastResult]:
        """
        תחזית הכנסות
        Revenue forecasting
        """
        # שליפת נתונים היסטוריים
        historical = self._get_monthly_revenue(organization_id, months=24)
        
        if len(historical) < 3:
            # אין מספיק נתונים - תחזית בסיסית
            return self._generate_basic_forecast(historical, periods)
        
        values = [h['amount'] for h in historical]
        dates = [h['date'] for h in historical]
        
        if method == ForecastMethod.EXPONENTIAL_SMOOTHING:
            predictions = self._exponential_smoothing(values, periods)
        elif method == ForecastMethod.MOVING_AVERAGE:
            predictions = self._moving_average(values, periods)
        elif method == ForecastMethod.LINEAR_REGRESSION:
            predictions = self._linear_regression(values, periods)
        elif method == ForecastMethod.SEASONAL:
            predictions = self._seasonal_forecast(values, periods)
        else:
            predictions = self._ensemble_forecast(values, periods)
        
        # יצירת תוצאות עם תאריכים עתידיים
        results = []
        last_date = dates[-1] if dates else datetime.now()
        
        for i, pred in enumerate(predictions):
            forecast_date = self._add_months(last_date, i + 1)
            std_dev = self._calculate_std_dev(values) if values else pred * 0.1
            
            results.append(ForecastResult(
                date=forecast_date,
                predicted_value=pred,
                lower_bound=max(0, pred - 1.96 * std_dev),
                upper_bound=pred + 1.96 * std_dev,
                confidence=0.95
            ))
        
        return results
    
    def forecast_expenses(
        self,
        organization_id: int,
        periods: int = 12,
        method: ForecastMethod = ForecastMethod.EXPONENTIAL_SMOOTHING
    ) -> List[ForecastResult]:
        """
        תחזית הוצאות
        Expense forecasting
        """
        historical = self._get_monthly_expenses(organization_id, months=24)
        
        if len(historical) < 3:
            return self._generate_basic_forecast(historical, periods)
        
        values = [h['amount'] for h in historical]
        dates = [h['date'] for h in historical]
        
        if method == ForecastMethod.EXPONENTIAL_SMOOTHING:
            predictions = self._exponential_smoothing(values, periods)
        elif method == ForecastMethod.MOVING_AVERAGE:
            predictions = self._moving_average(values, periods)
        elif method == ForecastMethod.LINEAR_REGRESSION:
            predictions = self._linear_regression(values, periods)
        elif method == ForecastMethod.SEASONAL:
            predictions = self._seasonal_forecast(values, periods)
        else:
            predictions = self._ensemble_forecast(values, periods)
        
        results = []
        last_date = dates[-1] if dates else datetime.now()
        
        for i, pred in enumerate(predictions):
            forecast_date = self._add_months(last_date, i + 1)
            std_dev = self._calculate_std_dev(values) if values else pred * 0.1
            
            results.append(ForecastResult(
                date=forecast_date,
                predicted_value=pred,
                lower_bound=max(0, pred - 1.96 * std_dev),
                upper_bound=pred + 1.96 * std_dev,
                confidence=0.95
            ))
        
        return results
    
    def forecast_cash_flow(
        self,
        organization_id: int,
        periods: int = 12,
        current_balance: float = 0
    ) -> List[Dict[str, Any]]:
        """
        תחזית תזרים מזומנים
        Cash flow forecasting
        """
        revenue_forecast = self.forecast_revenue(organization_id, periods)
        expense_forecast = self.forecast_expenses(organization_id, periods)
        
        results = []
        running_balance = current_balance
        
        for i in range(periods):
            inflow = revenue_forecast[i].predicted_value
            outflow = expense_forecast[i].predicted_value
            net_flow = inflow - outflow
            running_balance += net_flow
            
            results.append({
                'date': revenue_forecast[i].date.strftime('%Y-%m'),
                'projected_inflows': inflow,
                'projected_outflows': outflow,
                'projected_net_flow': net_flow,
                'projected_balance': running_balance,
                'inflow_lower': revenue_forecast[i].lower_bound,
                'inflow_upper': revenue_forecast[i].upper_bound,
                'outflow_lower': expense_forecast[i].lower_bound,
                'outflow_upper': expense_forecast[i].upper_bound,
                'confidence': 0.95
            })
        
        return results
    
    def get_scenario_analysis(
        self,
        organization_id: int,
        periods: int = 12,
        current_balance: float = 0
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        ניתוח תרחישים
        Best/Worst/Expected case analysis
        """
        base_forecast = self.forecast_cash_flow(organization_id, periods, current_balance)
        
        # תרחיש אופטימי - +20% הכנסות, -10% הוצאות
        optimistic = []
        balance = current_balance
        for f in base_forecast:
            inflow = f['projected_inflows'] * 1.2
            outflow = f['projected_outflows'] * 0.9
            net = inflow - outflow
            balance += net
            optimistic.append({
                'date': f['date'],
                'projected_inflows': inflow,
                'projected_outflows': outflow,
                'projected_net_flow': net,
                'projected_balance': balance
            })
        
        # תרחיש פסימי - -20% הכנסות, +15% הוצאות
        pessimistic = []
        balance = current_balance
        for f in base_forecast:
            inflow = f['projected_inflows'] * 0.8
            outflow = f['projected_outflows'] * 1.15
            net = inflow - outflow
            balance += net
            pessimistic.append({
                'date': f['date'],
                'projected_inflows': inflow,
                'projected_outflows': outflow,
                'projected_net_flow': net,
                'projected_balance': balance
            })
        
        return {
            'expected': base_forecast,
            'optimistic': optimistic,
            'pessimistic': pessimistic
        }
    
    # ============= Budget Analysis =============
    
    def analyze_budget_variance(
        self,
        organization_id: int,
        budget: Dict[str, float],
        start_date: datetime,
        end_date: datetime
    ) -> List[BudgetVariance]:
        """
        ניתוח סטיות תקציב
        Budget variance analysis
        """
        # שליפת נתונים בפועל לפי קטגוריה
        actual_data = self.db.query(
            Transaction.category,
            func.sum(Transaction.amount).label('total')
        ).filter(
            and_(
                Transaction.organization_id == organization_id,
                Transaction.transaction_date >= start_date,
                Transaction.transaction_date <= end_date
            )
        ).group_by(Transaction.category).all()
        
        actual_by_category = {row.category or 'other': float(row.total) for row in actual_data}
        
        variances = []
        for category, budgeted in budget.items():
            actual = actual_by_category.get(category, 0)
            variance = actual - budgeted
            variance_pct = (variance / budgeted * 100) if budgeted != 0 else 0
            
            # לקטגוריות הכנסה - עודף חיובי הוא טוב
            # לקטגוריות הוצאה - עודף שלילי הוא טוב
            is_income = category in ['sales', 'services', 'interest_income', 'revenue']
            is_favorable = (variance > 0) if is_income else (variance < 0)
            
            variances.append(BudgetVariance(
                category=category,
                budgeted=budgeted,
                actual=actual,
                variance=variance,
                variance_percent=variance_pct,
                is_favorable=is_favorable
            ))
        
        return variances
    
    def forecast_budget_achievement(
        self,
        organization_id: int,
        annual_budget: Dict[str, float],
        months_elapsed: int
    ) -> Dict[str, Any]:
        """
        תחזית השגת תקציב שנתי
        Forecast budget achievement
        """
        # חישוב ביצוע יחסי
        start_of_year = datetime.now().replace(month=1, day=1)
        today = datetime.now()
        
        actual = {}
        for category in annual_budget.keys():
            total = self.db.query(func.sum(Transaction.amount)).filter(
                and_(
                    Transaction.organization_id == organization_id,
                    Transaction.category == category,
                    Transaction.transaction_date >= start_of_year,
                    Transaction.transaction_date <= today
                )
            ).scalar() or 0
            actual[category] = float(total)
        
        results = {}
        for category, budget in annual_budget.items():
            actual_val = actual.get(category, 0)
            expected_to_date = budget * months_elapsed / 12
            
            # תחזית לסוף השנה
            if months_elapsed > 0:
                monthly_rate = actual_val / months_elapsed
                projected_annual = monthly_rate * 12
            else:
                projected_annual = 0
            
            results[category] = {
                'budgeted': budget,
                'actual_to_date': actual_val,
                'expected_to_date': expected_to_date,
                'variance_to_date': actual_val - expected_to_date,
                'projected_annual': projected_annual,
                'projected_variance': projected_annual - budget,
                'achievement_rate': (projected_annual / budget * 100) if budget > 0 else 0
            }
        
        return results
    
    # ============= Trend Analysis =============
    
    def detect_trends(
        self,
        organization_id: int,
        months: int = 12
    ) -> Dict[str, Any]:
        """
        זיהוי מגמות
        Trend detection and analysis
        """
        revenue_data = self._get_monthly_revenue(organization_id, months)
        expense_data = self._get_monthly_expenses(organization_id, months)
        
        revenue_values = [d['amount'] for d in revenue_data]
        expense_values = [d['amount'] for d in expense_data]
        
        revenue_trend = self._calculate_trend(revenue_values)
        expense_trend = self._calculate_trend(expense_values)
        
        # חישוב צמיחה
        if len(revenue_values) >= 2 and revenue_values[0] > 0:
            revenue_growth = ((revenue_values[-1] - revenue_values[0]) / revenue_values[0]) * 100
        else:
            revenue_growth = 0
        
        if len(expense_values) >= 2 and expense_values[0] > 0:
            expense_growth = ((expense_values[-1] - expense_values[0]) / expense_values[0]) * 100
        else:
            expense_growth = 0
        
        # זיהוי עונתיות
        seasonality = self._detect_seasonality(revenue_values)
        
        return {
            'revenue': {
                'trend': revenue_trend,
                'growth_rate': revenue_growth,
                'average': np.mean(revenue_values) if revenue_values else 0,
                'volatility': np.std(revenue_values) if revenue_values else 0
            },
            'expenses': {
                'trend': expense_trend,
                'growth_rate': expense_growth,
                'average': np.mean(expense_values) if expense_values else 0,
                'volatility': np.std(expense_values) if expense_values else 0
            },
            'seasonality': seasonality,
            'profit_margin_trend': self._calculate_profit_margin_trend(revenue_values, expense_values)
        }
    
    def calculate_financial_ratios_forecast(
        self,
        organization_id: int,
        periods: int = 12
    ) -> List[Dict[str, Any]]:
        """
        תחזית יחסים פיננסיים
        Financial ratios forecast
        """
        revenue_forecast = self.forecast_revenue(organization_id, periods)
        expense_forecast = self.forecast_expenses(organization_id, periods)
        
        results = []
        for i in range(periods):
            revenue = revenue_forecast[i].predicted_value
            expenses = expense_forecast[i].predicted_value
            
            gross_profit = revenue - (expenses * 0.6)  # הנחה: 60% עלות מכר
            net_profit = revenue - expenses
            
            results.append({
                'date': revenue_forecast[i].date.strftime('%Y-%m'),
                'projected_revenue': revenue,
                'projected_expenses': expenses,
                'gross_profit_margin': (gross_profit / revenue * 100) if revenue > 0 else 0,
                'net_profit_margin': (net_profit / revenue * 100) if revenue > 0 else 0,
                'expense_ratio': (expenses / revenue * 100) if revenue > 0 else 0
            })
        
        return results
    
    # ============= Evaluation Methods =============
    
    def evaluate_forecast_accuracy(
        self,
        organization_id: int,
        test_months: int = 3
    ) -> ForecastMetrics:
        """
        הערכת דיוק תחזית
        Evaluate forecast accuracy using historical data
        """
        # שליפת נתונים
        all_data = self._get_monthly_revenue(organization_id, months=24)
        
        if len(all_data) < test_months + 6:
            return ForecastMetrics(mae=0, mape=0, rmse=0, r2=0)
        
        # חלוקה לאימון ומבחן
        train_data = all_data[:-test_months]
        test_data = all_data[-test_months:]
        
        train_values = [d['amount'] for d in train_data]
        actual_values = [d['amount'] for d in test_data]
        
        # תחזית על תקופת המבחן
        predictions = self._exponential_smoothing(train_values, test_months)
        
        # חישוב מטריקות
        actual = np.array(actual_values)
        predicted = np.array(predictions)
        
        mae = np.mean(np.abs(actual - predicted))
        mape = np.mean(np.abs((actual - predicted) / actual)) * 100 if np.all(actual != 0) else 0
        rmse = np.sqrt(np.mean((actual - predicted) ** 2))
        
        # R-squared
        ss_res = np.sum((actual - predicted) ** 2)
        ss_tot = np.sum((actual - np.mean(actual)) ** 2)
        r2 = 1 - (ss_res / ss_tot) if ss_tot != 0 else 0
        
        return ForecastMetrics(
            mae=float(mae),
            mape=float(mape),
            rmse=float(rmse),
            r2=float(r2)
        )
    
    # ============= Private Forecasting Methods =============
    
    def _exponential_smoothing(
        self,
        data: List[float],
        periods: int,
        alpha: float = 0.3
    ) -> List[float]:
        """
        החלקה מעריכית
        Single Exponential Smoothing
        """
        if not data:
            return [0] * periods
        
        # חישוב רמה אחרונה
        level = data[0]
        for val in data[1:]:
            level = alpha * val + (1 - alpha) * level
        
        # תחזית
        return [level] * periods
    
    def _double_exponential_smoothing(
        self,
        data: List[float],
        periods: int,
        alpha: float = 0.3,
        beta: float = 0.1
    ) -> List[float]:
        """
        החלקה מעריכית כפולה (Holt)
        Double Exponential Smoothing for trends
        """
        if len(data) < 2:
            return self._exponential_smoothing(data, periods, alpha)
        
        # אתחול
        level = data[0]
        trend = data[1] - data[0]
        
        for val in data[1:]:
            last_level = level
            level = alpha * val + (1 - alpha) * (level + trend)
            trend = beta * (level - last_level) + (1 - beta) * trend
        
        # תחזית
        forecasts = []
        for i in range(1, periods + 1):
            forecasts.append(level + i * trend)
        
        return forecasts
    
    def _moving_average(
        self,
        data: List[float],
        periods: int,
        window: int = 3
    ) -> List[float]:
        """
        ממוצע נע
        Moving Average forecast
        """
        if not data:
            return [0] * periods
        
        # חישוב ממוצע נע אחרון
        window = min(window, len(data))
        avg = np.mean(data[-window:])
        
        return [float(avg)] * periods
    
    def _linear_regression(
        self,
        data: List[float],
        periods: int
    ) -> List[float]:
        """
        רגרסיה לינארית
        Linear Regression forecast
        """
        if len(data) < 2:
            return [data[0] if data else 0] * periods
        
        x = np.arange(len(data))
        y = np.array(data)
        
        # חישוב מקדמים
        n = len(data)
        sum_x = np.sum(x)
        sum_y = np.sum(y)
        sum_xy = np.sum(x * y)
        sum_xx = np.sum(x * x)
        
        slope = (n * sum_xy - sum_x * sum_y) / (n * sum_xx - sum_x ** 2) if (n * sum_xx - sum_x ** 2) != 0 else 0
        intercept = (sum_y - slope * sum_x) / n
        
        # תחזית
        forecasts = []
        for i in range(periods):
            future_x = len(data) + i
            forecasts.append(max(0, intercept + slope * future_x))
        
        return forecasts
    
    def _seasonal_forecast(
        self,
        data: List[float],
        periods: int,
        season_length: int = 12
    ) -> List[float]:
        """
        תחזית עונתית
        Seasonal forecast
        """
        if len(data) < season_length:
            return self._exponential_smoothing(data, periods)
        
        # חישוב אינדקסים עונתיים
        seasonal_indices = []
        for i in range(season_length):
            values_at_season = [data[j] for j in range(i, len(data), season_length)]
            seasonal_indices.append(np.mean(values_at_season) if values_at_season else 1)
        
        overall_mean = np.mean(data)
        seasonal_factors = [s / overall_mean if overall_mean > 0 else 1 for s in seasonal_indices]
        
        # בסיס תחזית (ממוצע או טרנד)
        base_forecast = self._double_exponential_smoothing(data, periods)
        
        # החלת עונתיות
        forecasts = []
        for i, base in enumerate(base_forecast):
            season_idx = (len(data) + i) % season_length
            forecasts.append(base * seasonal_factors[season_idx])
        
        return forecasts
    
    def _ensemble_forecast(
        self,
        data: List[float],
        periods: int
    ) -> List[float]:
        """
        תחזית משולבת
        Ensemble forecast combining multiple methods
        """
        exp_smooth = self._exponential_smoothing(data, periods)
        double_exp = self._double_exponential_smoothing(data, periods)
        moving_avg = self._moving_average(data, periods)
        linear = self._linear_regression(data, periods)
        
        # משקולות (ניתן לכייל בהתבסס על דיוק היסטורי)
        weights = [0.3, 0.3, 0.2, 0.2]
        
        forecasts = []
        for i in range(periods):
            combined = (
                weights[0] * exp_smooth[i] +
                weights[1] * double_exp[i] +
                weights[2] * moving_avg[i] +
                weights[3] * linear[i]
            )
            forecasts.append(combined)
        
        return forecasts
    
    def _generate_basic_forecast(
        self,
        historical: List[Dict[str, Any]],
        periods: int
    ) -> List[ForecastResult]:
        """תחזית בסיסית כשאין מספיק נתונים"""
        avg = np.mean([h['amount'] for h in historical]) if historical else 0
        last_date = historical[-1]['date'] if historical else datetime.now()
        
        results = []
        for i in range(periods):
            forecast_date = self._add_months(last_date, i + 1)
            results.append(ForecastResult(
                date=forecast_date,
                predicted_value=float(avg),
                lower_bound=float(avg * 0.8),
                upper_bound=float(avg * 1.2),
                confidence=0.5  # רמת ביטחון נמוכה
            ))
        
        return results
    
    # ============= Data Retrieval Methods =============
    
    def _get_monthly_revenue(
        self,
        organization_id: int,
        months: int
    ) -> List[Dict[str, Any]]:
        """שליפת הכנסות חודשיות"""
        end_date = datetime.now()
        start_date = self._add_months(end_date, -months)
        
        results = self.db.query(
            func.date_trunc('month', Transaction.transaction_date).label('month'),
            func.sum(Transaction.amount).label('total')
        ).filter(
            and_(
                Transaction.organization_id == organization_id,
                Transaction.transaction_type == TransactionType.INCOME,
                Transaction.transaction_date >= start_date,
                Transaction.transaction_date <= end_date
            )
        ).group_by(func.date_trunc('month', Transaction.transaction_date)).order_by('month').all()
        
        return [{'date': r.month, 'amount': float(r.total)} for r in results]
    
    def _get_monthly_expenses(
        self,
        organization_id: int,
        months: int
    ) -> List[Dict[str, Any]]:
        """שליפת הוצאות חודשיות"""
        end_date = datetime.now()
        start_date = self._add_months(end_date, -months)
        
        results = self.db.query(
            func.date_trunc('month', Transaction.transaction_date).label('month'),
            func.sum(Transaction.amount).label('total')
        ).filter(
            and_(
                Transaction.organization_id == organization_id,
                Transaction.transaction_type == TransactionType.EXPENSE,
                Transaction.transaction_date >= start_date,
                Transaction.transaction_date <= end_date
            )
        ).group_by(func.date_trunc('month', Transaction.transaction_date)).order_by('month').all()
        
        return [{'date': r.month, 'amount': float(r.total)} for r in results]
    
    # ============= Utility Methods =============
    
    def _add_months(self, date: datetime, months: int) -> datetime:
        """הוספת חודשים לתאריך"""
        month = date.month + months
        year = date.year + (month - 1) // 12
        month = (month - 1) % 12 + 1
        day = min(date.day, [31, 29 if year % 4 == 0 else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1])
        return date.replace(year=year, month=month, day=day)
    
    def _calculate_std_dev(self, values: List[float]) -> float:
        """חישוב סטיית תקן"""
        return float(np.std(values)) if values else 0
    
    def _calculate_trend(self, values: List[float]) -> str:
        """זיהוי מגמה"""
        if len(values) < 3:
            return "insufficient_data"
        
        # רגרסיה לינארית פשוטה
        x = np.arange(len(values))
        slope = np.polyfit(x, values, 1)[0]
        
        threshold = np.mean(values) * 0.02  # 2% מהממוצע
        
        if slope > threshold:
            return "increasing"
        elif slope < -threshold:
            return "decreasing"
        else:
            return "stable"
    
    def _detect_seasonality(self, values: List[float]) -> Dict[str, Any]:
        """זיהוי עונתיות"""
        if len(values) < 12:
            return {'detected': False, 'pattern': None}
        
        # בדיקה פשוטה - השוואת רבעונים
        quarterly_avgs = []
        for q in range(4):
            q_values = [values[i] for i in range(q, len(values), 4) if i < len(values)]
            quarterly_avgs.append(np.mean(q_values) if q_values else 0)
        
        variance = np.var(quarterly_avgs)
        mean_val = np.mean(values)
        
        if variance > (mean_val * 0.1) ** 2:  # סף עונתיות
            peak_quarter = quarterly_avgs.index(max(quarterly_avgs)) + 1
            low_quarter = quarterly_avgs.index(min(quarterly_avgs)) + 1
            return {
                'detected': True,
                'peak_quarter': peak_quarter,
                'low_quarter': low_quarter,
                'quarterly_pattern': quarterly_avgs
            }
        
        return {'detected': False, 'pattern': None}
    
    def _calculate_profit_margin_trend(
        self,
        revenue: List[float],
        expenses: List[float]
    ) -> List[float]:
        """חישוב מגמת שולי רווח"""
        margins = []
        for r, e in zip(revenue, expenses):
            if r > 0:
                margins.append(((r - e) / r) * 100)
            else:
                margins.append(0)
        return margins
