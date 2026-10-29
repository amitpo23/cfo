"""
Cash Flow & Forecasting API Routes
נתיבי API לתזרים מזומנים ותחזיות
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import List, Optional, Dict
from datetime import datetime, date, timedelta
from pydantic import BaseModel, Field
from decimal import Decimal

from ..dependencies import get_current_user, get_current_org_id, get_db, get_super_admin
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

class CheckingLiquidity(BaseModel):
    """יתרת עו״ש לשימוש. חסר נשאר null."""
    balance: Optional[float] = None
    as_of: Optional[str] = None
    status: Optional[str] = None
    label_he: Optional[str] = None
    last_booked: Optional[float] = None
    last_booked_as_of: Optional[str] = None


class CreditFacilityLiquidity(BaseModel):
    """מסגרת, ניצול, פנוי וחריגה. null אינו 0."""
    limit: Optional[float] = None
    used: Optional[float] = None
    headroom: Optional[float] = None
    breach: Optional[bool] = None
    overrun: Optional[float] = None
    overrun_status: Optional[str] = None
    overrun_label: Optional[str] = None
    available_limit: Optional[float] = None
    available_as_of: Optional[str] = None
    note_he: Optional[str] = None


class LiquidityRatiosResponse(BaseModel):
    """יחסי נזילות מיתרת העו״ש החיה. חסר אינו 0."""
    current_ratio: Optional[float] = None
    quick_ratio: Optional[float] = None
    cash_ratio: Optional[float] = None
    working_capital: Optional[float] = None
    current_assets: Optional[float] = None
    current_liabilities: Optional[float] = None
    missing_label: Optional[str] = None
    checking: CheckingLiquidity
    facility: CreditFacilityLiquidity
    credit_line_status: Optional[str] = None
    credit_line_reason: Optional[str] = None
    provider_calls: int = 0


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

@router.get("/period")
async def get_period_compare(
    grain: str = Query("month", pattern="^(day|week|month|quarter|year)$"),
    start: date = Query(...),
    end: date = Query(...),
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
    org_id: int = Depends(get_current_org_id),
):
    """Budget, booked bank, and filed books for the org. No SUMIT or Open Finance call."""
    from ...services.dashboards.period_compare import compare_period
    from ...services.dashboards.view_model import MAX_RANGE_DAYS
    if end < start:
        raise HTTPException(422, "תאריך הסיום מוקדם מתאריך ההתחלה")
    if (end - start).days > MAX_RANGE_DAYS:
        raise HTTPException(422, "טווח התאריכים ארוך מ-366 ימים")
    from ...models import ClientDashboard
    from ...services.dashboards.view_model import plan_payload
    dashboard = (
        db.query(ClientDashboard)
        .filter(ClientDashboard.primary_organization_id == org_id)
        .order_by(ClientDashboard.id)
        .first()
    )
    plan = plan_payload(db, dashboard.id) if dashboard is not None else None
    payload = compare_period(db, org_id, plan, grain=grain, start=start, end=end)
    payload["dashboard_slug"] = dashboard.slug if dashboard is not None else None
    return payload


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
    יתרת עו״ש, מסגרת אשראי ויחסים.

    המקור הוא checking_snapshot אחרי סנכרון החשבונות שכבר שמור. אין קריאת
    Open Finance מכאן. יתרה לא ידועה או ישנה אינה יחס 0 ואינה runway 0.
    """
    from ...services.dashboards.cashflow_liquidity import cashflow_liquidity_surface
    surface = cashflow_liquidity_surface(db, org_id)
    ratios = surface["ratios"]
    return LiquidityRatiosResponse(
        current_ratio=ratios["current_ratio"],
        quick_ratio=ratios["quick_ratio"],
        cash_ratio=ratios["cash_ratio"],
        working_capital=ratios["working_capital"],
        current_assets=ratios["current_assets"],
        current_liabilities=ratios["current_liabilities"],
        missing_label=ratios["missing_label"],
        checking=surface["checking"],
        facility=surface["facility"],
        credit_line_status=surface["credit_line_status"],
        credit_line_reason=surface["credit_line_reason"],
        provider_calls=0,
    )


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

@router.get("/balance-diagnostic")
async def cash_balance_diagnostic(
    db=Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """Stored checking balance, its date, and the last transaction date. No provider call."""
    from ...services.dashboards.balance_diagnostic import diagnose_org
    return diagnose_org(db, org_id)


@router.get("/balance-diagnostic/all")
async def cash_balance_diagnostic_all(
    db=Depends(get_db),
    _admin=Depends(get_super_admin),
):
    """Every organization that has an account row. No provider call."""
    from ...services.dashboards.balance_diagnostic import diagnose_all
    return diagnose_all(db)


@router.get("/weekly")
async def weekly_forecast(
    db=Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """The same 13-week forecast the client dashboard uses, for this organization."""
    from datetime import date as date_cls
    from ...services.dashboards.budget_fill import dashboard_for_org
    from ...services.dashboards.liquidity import checking_snapshot
    from ...services.dashboards.view_model import build_view, plan_payload
    today = date_cls.today()
    dashboard = dashboard_for_org(db, org_id)
    plan = plan_payload(db, dashboard.id) if dashboard is not None else None
    view = build_view(db, org_id, date_cls(today.year, 1, 1), today, plan=plan)
    return {
        "snapshot": checking_snapshot(db, org_id, today=today),
        "forecast": view.get("cash_forecast"),
        "funding_need": (view.get("cash_forecast") or {}).get("funding_need"),
        "provider_calls": 0,
    }


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
