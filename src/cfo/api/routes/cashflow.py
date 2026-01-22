"""
Cash Flow & Forecasting API Routes
נתיבי API לתזרים מזומנים ותחזיות
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import List, Optional, Dict, Any
from datetime import datetime, date, timedelta
from pydantic import BaseModel, Field
from decimal import Decimal

from ..dependencies import get_current_user, get_db
from ...services.cash_flow_service import CashFlowService, CashFlowCategory
from ...services.forecasting_service import ForecastingService, ForecastMethod
from ...services.ml_models import EnsembleForecaster

router = APIRouter()


# ============= Pydantic Models =============

class CashFlowItemResponse(BaseModel):
    """פריט תזרים מזומנים"""
    category: str
    name: str
    name_he: str
    amount: float
    is_inflow: bool


class CashFlowStatementResponse(BaseModel):
    """דוח תזרים מזומנים"""
    period_start: datetime
    period_end: datetime
    opening_balance: float
    closing_balance: float
    operating_items: List[CashFlowItemResponse]
    operating_total: float
    investing_items: List[CashFlowItemResponse]
    investing_total: float
    financing_items: List[CashFlowItemResponse]
    financing_total: float
    net_cash_flow: float


class MonthlyCashFlowResponse(BaseModel):
    """תזרים מזומנים חודשי"""
    month: str
    month_name: str
    inflows: float
    outflows: float
    net_flow: float
    cumulative: float


class DailyCashPositionResponse(BaseModel):
    """מצב מזומנים יומי"""
    date: str
    inflows: float
    outflows: float
    net_flow: float
    closing_balance: float


class BurnRateResponse(BaseModel):
    """קצב שריפת מזומנים"""
    monthly_burn_rate: float
    monthly_income: float
    net_monthly_burn: float
    current_balance: float
    runway_months: float
    analysis_period_months: int


class LiquidityRatiosResponse(BaseModel):
    """יחסי נזילות"""
    current_ratio: float
    quick_ratio: float
    cash_ratio: float
    working_capital: float
    current_assets: float
    current_liabilities: float


class ForecastResultResponse(BaseModel):
    """תוצאת תחזית"""
    date: str
    predicted_value: float
    lower_bound: float
    upper_bound: float
    confidence: float


class CashFlowForecastResponse(BaseModel):
    """תחזית תזרים מזומנים"""
    date: str
    projected_inflows: float
    projected_outflows: float
    projected_net_flow: float
    projected_balance: float
    confidence: float


class ScenarioAnalysisResponse(BaseModel):
    """ניתוח תרחישים"""
    expected: List[CashFlowForecastResponse]
    optimistic: List[CashFlowForecastResponse]
    pessimistic: List[CashFlowForecastResponse]


class BudgetVarianceResponse(BaseModel):
    """סטיית תקציב"""
    category: str
    budgeted: float
    actual: float
    variance: float
    variance_percent: float
    is_favorable: bool


class BudgetRequest(BaseModel):
    """בקשת תקציב"""
    budget: Dict[str, float] = Field(
        ..., 
        example={"sales": 100000, "salaries": 50000, "rent": 10000}
    )
    start_date: date
    end_date: date


class TrendAnalysisResponse(BaseModel):
    """ניתוח מגמות"""
    revenue: Dict[str, Any]
    expenses: Dict[str, Any]
    seasonality: Dict[str, Any]
    profit_margin_trend: List[float]


# ============= Cash Flow Endpoints =============

@router.get("/statement", response_model=CashFlowStatementResponse)
async def get_cash_flow_statement(
    start_date: date = Query(..., description="תאריך התחלה"),
    end_date: date = Query(..., description="תאריך סיום"),
    db = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    דוח תזרים מזומנים
    Get cash flow statement for a period
    """
    service = CashFlowService(db)
    organization_id = current_user.get('organization_id', 1)
    
    statement = service.get_cash_flow_statement(
        organization_id=organization_id,
        start_date=datetime.combine(start_date, datetime.min.time()),
        end_date=datetime.combine(end_date, datetime.max.time())
    )
    
    return CashFlowStatementResponse(
        period_start=statement.period_start,
        period_end=statement.period_end,
        opening_balance=float(statement.opening_balance),
        closing_balance=float(statement.closing_balance),
        operating_items=[
            CashFlowItemResponse(
                category=item.category.value,
                name=item.name,
                name_he=item.name_he,
                amount=float(item.amount),
                is_inflow=item.is_inflow
            ) for item in statement.operating_items
        ],
        operating_total=float(statement.operating_total),
        investing_items=[
            CashFlowItemResponse(
                category=item.category.value,
                name=item.name,
                name_he=item.name_he,
                amount=float(item.amount),
                is_inflow=item.is_inflow
            ) for item in statement.investing_items
        ],
        investing_total=float(statement.investing_total),
        financing_items=[
            CashFlowItemResponse(
                category=item.category.value,
                name=item.name,
                name_he=item.name_he,
                amount=float(item.amount),
                is_inflow=item.is_inflow
            ) for item in statement.financing_items
        ],
        financing_total=float(statement.financing_total),
        net_cash_flow=float(statement.net_cash_flow)
    )


@router.get("/monthly", response_model=List[MonthlyCashFlowResponse])
async def get_monthly_cash_flow(
    months: int = Query(12, ge=1, le=36, description="מספר חודשים"),
    db = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    תזרים מזומנים חודשי
    Get monthly cash flow analysis
    """
    service = CashFlowService(db)
    organization_id = current_user.get('organization_id', 1)
    
    data = service.get_monthly_cash_flow(organization_id, months)
    
    return [MonthlyCashFlowResponse(**item) for item in data]


@router.get("/daily", response_model=List[DailyCashPositionResponse])
async def get_daily_cash_position(
    days: int = Query(30, ge=1, le=90, description="מספר ימים"),
    db = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    מצב מזומנים יומי
    Get daily cash position
    """
    service = CashFlowService(db)
    organization_id = current_user.get('organization_id', 1)
    
    data = service.get_daily_cash_position(organization_id, days)
    
    return [DailyCashPositionResponse(**item) for item in data]


@router.get("/burn-rate", response_model=BurnRateResponse)
async def get_burn_rate(
    months: int = Query(3, ge=1, le=12, description="תקופת חישוב"),
    db = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    קצב שריפת מזומנים
    Calculate cash burn rate
    """
    service = CashFlowService(db)
    organization_id = current_user.get('organization_id', 1)
    
    data = service.get_cash_burn_rate(organization_id, months)
    
    return BurnRateResponse(**data)


@router.get("/by-category")
async def get_cash_flow_by_category(
    start_date: date = Query(..., description="תאריך התחלה"),
    end_date: date = Query(..., description="תאריך סיום"),
    db = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    תזרים מזומנים לפי קטגוריות
    Get cash flow breakdown by category
    """
    service = CashFlowService(db)
    organization_id = current_user.get('organization_id', 1)
    
    data = service.get_cash_flow_by_category(
        organization_id,
        datetime.combine(start_date, datetime.min.time()),
        datetime.combine(end_date, datetime.max.time())
    )
    
    # המרה לפורמט JSON-friendly
    result = {}
    for category, values in data.items():
        result[category] = {
            'inflows': float(values['inflows']),
            'outflows': float(values['outflows']),
            'net': float(values['inflows'] - values['outflows'])
        }
    
    return result


@router.get("/liquidity-ratios", response_model=LiquidityRatiosResponse)
async def get_liquidity_ratios(
    db = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    יחסי נזילות
    Get liquidity ratios
    """
    service = CashFlowService(db)
    organization_id = current_user.get('organization_id', 1)
    
    data = service.get_liquidity_ratios(organization_id)
    
    return LiquidityRatiosResponse(**data)


@router.get("/receivables-aging")
async def get_receivables_aging(
    db = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    גיול חובות לקוחות
    Get accounts receivable aging report
    """
    service = CashFlowService(db)
    organization_id = current_user.get('organization_id', 1)
    
    return service.get_receivables_aging(organization_id)


@router.get("/payables-aging")
async def get_payables_aging(
    db = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    גיול חובות לספקים
    Get accounts payable aging report
    """
    service = CashFlowService(db)
    organization_id = current_user.get('organization_id', 1)
    
    return service.get_payables_aging(organization_id)


# ============= Forecasting Endpoints =============

@router.get("/forecast/revenue", response_model=List[ForecastResultResponse])
async def forecast_revenue(
    periods: int = Query(12, ge=1, le=24, description="מספר תקופות לתחזית"),
    method: str = Query("exponential_smoothing", description="שיטת תחזית"),
    db = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    תחזית הכנסות
    Forecast revenue
    """
    service = ForecastingService(db)
    organization_id = current_user.get('organization_id', 1)
    
    try:
        forecast_method = ForecastMethod(method)
    except ValueError:
        forecast_method = ForecastMethod.EXPONENTIAL_SMOOTHING
    
    results = service.forecast_revenue(organization_id, periods, forecast_method)
    
    return [
        ForecastResultResponse(
            date=r.date.strftime('%Y-%m'),
            predicted_value=r.predicted_value,
            lower_bound=r.lower_bound,
            upper_bound=r.upper_bound,
            confidence=r.confidence
        ) for r in results
    ]


@router.get("/forecast/expenses", response_model=List[ForecastResultResponse])
async def forecast_expenses(
    periods: int = Query(12, ge=1, le=24, description="מספר תקופות לתחזית"),
    method: str = Query("exponential_smoothing", description="שיטת תחזית"),
    db = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    תחזית הוצאות
    Forecast expenses
    """
    service = ForecastingService(db)
    organization_id = current_user.get('organization_id', 1)
    
    try:
        forecast_method = ForecastMethod(method)
    except ValueError:
        forecast_method = ForecastMethod.EXPONENTIAL_SMOOTHING
    
    results = service.forecast_expenses(organization_id, periods, forecast_method)
    
    return [
        ForecastResultResponse(
            date=r.date.strftime('%Y-%m'),
            predicted_value=r.predicted_value,
            lower_bound=r.lower_bound,
            upper_bound=r.upper_bound,
            confidence=r.confidence
        ) for r in results
    ]


@router.get("/forecast/cash-flow", response_model=List[CashFlowForecastResponse])
async def forecast_cash_flow(
    periods: int = Query(12, ge=1, le=24, description="מספר תקופות לתחזית"),
    current_balance: float = Query(0, description="יתרה נוכחית"),
    db = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    תחזית תזרים מזומנים
    Forecast cash flow
    """
    service = ForecastingService(db)
    organization_id = current_user.get('organization_id', 1)
    
    results = service.forecast_cash_flow(organization_id, periods, current_balance)
    
    return [CashFlowForecastResponse(**r) for r in results]


@router.get("/forecast/scenarios")
async def get_scenario_analysis(
    periods: int = Query(12, ge=1, le=24, description="מספר תקופות לתחזית"),
    current_balance: float = Query(0, description="יתרה נוכחית"),
    db = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    ניתוח תרחישים
    Get scenario analysis (best/worst/expected)
    """
    service = ForecastingService(db)
    organization_id = current_user.get('organization_id', 1)
    
    return service.get_scenario_analysis(organization_id, periods, current_balance)


@router.post("/forecast/budget-variance", response_model=List[BudgetVarianceResponse])
async def analyze_budget_variance(
    request: BudgetRequest,
    db = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    ניתוח סטיות תקציב
    Analyze budget variance
    """
    service = ForecastingService(db)
    organization_id = current_user.get('organization_id', 1)
    
    results = service.analyze_budget_variance(
        organization_id,
        request.budget,
        datetime.combine(request.start_date, datetime.min.time()),
        datetime.combine(request.end_date, datetime.max.time())
    )
    
    return [
        BudgetVarianceResponse(
            category=r.category,
            budgeted=r.budgeted,
            actual=r.actual,
            variance=r.variance,
            variance_percent=r.variance_percent,
            is_favorable=r.is_favorable
        ) for r in results
    ]


@router.get("/forecast/trends", response_model=TrendAnalysisResponse)
async def detect_trends(
    months: int = Query(12, ge=3, le=36, description="תקופת ניתוח"),
    db = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    זיהוי מגמות
    Detect financial trends
    """
    service = ForecastingService(db)
    organization_id = current_user.get('organization_id', 1)
    
    return service.detect_trends(organization_id, months)


@router.get("/forecast/ratios")
async def forecast_financial_ratios(
    periods: int = Query(12, ge=1, le=24, description="מספר תקופות לתחזית"),
    db = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    תחזית יחסים פיננסיים
    Forecast financial ratios
    """
    service = ForecastingService(db)
    organization_id = current_user.get('organization_id', 1)
    
    return service.calculate_financial_ratios_forecast(organization_id, periods)


@router.get("/forecast/accuracy")
async def evaluate_forecast_accuracy(
    test_months: int = Query(3, ge=1, le=6, description="חודשי מבחן"),
    db = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    הערכת דיוק תחזית
    Evaluate forecast accuracy
    """
    service = ForecastingService(db)
    organization_id = current_user.get('organization_id', 1)
    
    metrics = service.evaluate_forecast_accuracy(organization_id, test_months)
    
    return {
        'mae': metrics.mae,
        'mape': metrics.mape,
        'rmse': metrics.rmse,
        'r2': metrics.r2
    }


# ============= ML Forecasting Endpoints =============

@router.get("/forecast/ml/ensemble")
async def get_ml_ensemble_forecast(
    periods: int = Query(12, ge=1, le=24, description="מספר תקופות לתחזית"),
    db = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    תחזית ML משולבת
    Get ensemble ML forecast (LSTM + Prophet + XGBoost)
    """
    forecasting_service = ForecastingService(db)
    organization_id = current_user.get('organization_id', 1)
    
    # שליפת נתונים היסטוריים
    historical = forecasting_service._get_monthly_revenue(organization_id, 24)
    
    if len(historical) < 12:
        raise HTTPException(
            status_code=400,
            detail="אין מספיק נתונים היסטוריים לתחזית ML (נדרשים לפחות 12 חודשים)"
        )
    
    dates = [h['date'] for h in historical]
    values = [h['amount'] for h in historical]
    
    # יצירת תחזית משולבת
    ensemble = EnsembleForecaster()
    ensemble.train_all(dates, values)
    
    return ensemble.forecast(dates, values, periods)
