"""
Cash Flow & Forecasting API Routes
נתיבי API לתזרים מזומנים ותחזיות
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import List, Optional, Dict
from datetime import datetime, date, timedelta
from pydantic import BaseModel, Field
from decimal import Decimal

from ..dependencies import get_current_user, get_current_org_id, get_db
from ...services.cash_flow_service import CashFlowService, CashFlowCategory
from ...services.forecasting_service import ForecastingService
from ...services.live_forecast_service import LiveForecastService
from ...services.live_cash_flow_service import LiveCashFlowService

router = APIRouter()


# ============= Pydantic Models =============

# CashFlowItemResponse / CashFlowStatementResponse הוסרו יחד עם /statement
# (מבוסס CashFlowService על Transaction הקפואה; לא נצרך ע"י frontend/מושקו).

# MonthlyCashFlowResponse / DailyCashPositionResponse / BurnRateResponse הוסרו:
# /monthly, /daily, /burn-rate מוגשים כעת ע"י LiveCashFlowService, שמחזיר
# payload עשיר-honest-null (as_of/data_sources/message) בלי response_model
# קשיח — אותה מוסכמה כמו /forecast/live-monthly ו-/by-category.

class LiquidityRatiosResponse(BaseModel):
    """יחסי נזילות"""
    current_ratio: float
    quick_ratio: float
    cash_ratio: float
    working_capital: float
    current_assets: float
    current_liabilities: float


# ForecastResultResponse / CashFlowForecastResponse / ScenarioAnalysisResponse
# / TrendAnalysisResponse הוסרו עם משפחת ה-ML forecast המתה
# (/forecast/revenue, /forecast/expenses, /forecast/cash-flow,
# /forecast/scenarios, /forecast/trends, /forecast/ml/ensemble,
# /forecast/accuracy) — ForecastingService מבוסס Transaction הקפואה, לא
# נצרך ע"י frontend/מושקו. ForecastingService עצמו נשאר (עדיין משרת
# /forecast/budget-variance ו-/forecast/ratios).


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


# ============= Cash Flow Endpoints =============

@router.get("/monthly")
async def get_monthly_cash_flow(
    months: int = Query(12, ge=1, le=36, description="מספר חודשים"),
    db = Depends(get_db),
    current_user: dict = Depends(get_current_user),
    org_id: int = Depends(get_current_org_id),
):
    """
    תזרים מזומנים חודשי — ספרים חיים (BankTransaction), לא Transaction
    הקפואה. honest-null + as_of, כמו LiveForecastService.
    """
    return LiveCashFlowService(db, org_id).monthly_cash_flow(months=months)


@router.get("/daily")
async def get_daily_cash_position(
    days: int = Query(30, ge=1, le=90, description="מספר ימים"),
    db = Depends(get_db),
    current_user: dict = Depends(get_current_user),
    org_id: int = Depends(get_current_org_id),
):
    """
    מצב מזומנים יומי — ספרים חיים (BankTransaction + יתרת Account חיה),
    לא Transaction הקפואה.
    """
    return LiveCashFlowService(db, org_id).daily_cash_position(days=days)


@router.get("/burn-rate")
async def get_burn_rate(
    months: int = Query(3, ge=1, le=12, description="תקופת חישוב"),
    db = Depends(get_db),
    current_user: dict = Depends(get_current_user),
    org_id: int = Depends(get_current_org_id),
):
    """
    קצב שריפת מזומנים — ספרים חיים (BankTransaction + יתרת Account חיה),
    עם תוספת צפי גבייה/תשלום מ-AR/AP פתוחים ב-30 הימים הקרובים.
    """
    return LiveCashFlowService(db, org_id).burn_rate(months=months)


@router.get("/by-category")
async def get_cash_flow_by_category(
    start_date: date = Query(..., description="תאריך התחלה"),
    end_date: date = Query(..., description="תאריך סיום"),
    db = Depends(get_db),
    current_user: dict = Depends(get_current_user),
    org_id: int = Depends(get_current_org_id),
):
    """
    תזרים מזומנים לפי קטגוריות — ספרים חיים (BankTransaction). honest-null
    כש-BankTransaction.category_id אינו מאוכלס (המצב בפועל כיום).
    """
    return LiveCashFlowService(db, org_id).by_category(start_date=start_date, end_date=end_date)


@router.get("/liquidity-ratios", response_model=LiquidityRatiosResponse)
async def get_liquidity_ratios(
    db = Depends(get_db),
    current_user: dict = Depends(get_current_user),
    org_id: int = Depends(get_current_org_id),
):
    """
    יחסי נזילות
    Get liquidity ratios
    """
    service = CashFlowService(db)
    organization_id = org_id
    data = service.get_liquidity_ratios(organization_id)

    return LiquidityRatiosResponse(**data)


@router.get("/receivables-aging")
async def get_receivables_aging(
    db = Depends(get_db),
    current_user: dict = Depends(get_current_user),
    org_id: int = Depends(get_current_org_id),
):
    """
    גיול חובות לקוחות
    Get accounts receivable aging report
    """
    service = CashFlowService(db)
    organization_id = org_id
    return service.get_receivables_aging(organization_id)


@router.get("/payables-aging")
async def get_payables_aging(
    db = Depends(get_db),
    current_user: dict = Depends(get_current_user),
    org_id: int = Depends(get_current_org_id),
):
    """
    גיול חובות לספקים
    Get accounts payable aging report
    """
    service = CashFlowService(db)
    organization_id = org_id
    return service.get_payables_aging(organization_id)


# ============= Live-books Forecast (no ML, no Transaction) =============

@router.get("/forecast/live-monthly")
async def get_live_monthly_forecast(
    periods: int = Query(6, ge=1, le=24, description="מספר חודשים לתחזית"),
    db = Depends(get_db),
    current_user: dict = Depends(get_current_user),
    org_id: int = Depends(get_current_org_id),
):
    """
    תחזית תזרים חודשית מבוססת ספרים חיים — חשבוניות/חשבונות-ספק פתוחים
    (AR/AP לפי due_date) + בסיס הוצאות חוזרות (ממוצע היסטורי). לא טבלת
    Transaction הקפואה. פירוק גלוי לכל חודש, honest-null כשאין נתונים.
    """
    service = LiveForecastService(db, org_id)
    return service.monthly_forecast(periods=periods)


# ============= Forecasting Endpoints =============

@router.post("/forecast/budget-variance", response_model=List[BudgetVarianceResponse])
async def analyze_budget_variance(
    request: BudgetRequest,
    db = Depends(get_db),
    current_user: dict = Depends(get_current_user),
    org_id: int = Depends(get_current_org_id),
):
    """
    ניתוח סטיות תקציב
    Analyze budget variance
    """
    service = ForecastingService(db)
    organization_id = org_id
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


@router.get("/forecast/ratios")
async def forecast_financial_ratios(
    periods: int = Query(12, ge=1, le=24, description="מספר תקופות לתחזית"),
    db = Depends(get_db),
    current_user: dict = Depends(get_current_user),
    org_id: int = Depends(get_current_org_id),
):
    """
    תחזית יחסים פיננסיים
    Forecast financial ratios
    """
    service = ForecastingService(db)
    organization_id = org_id
    return service.calculate_financial_ratios_forecast(organization_id, periods)
