"""
Financial Management API Routes
נתיבי API לניהול פיננסי
"""
from datetime import date, datetime
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..dependencies import get_db
from ...services import (
    BudgetService,
    AccountsReceivableService,
    AccountsPayableService,
    KPIService,
    CostAnalysisService,
    TaxComplianceService,
    AdvancedAIService,
    ReportBuilderService,
    ReportFormat,
    ReportFrequency,
)

router = APIRouter(prefix="/financial", tags=["Financial Management"])


# ============ Budget Management Routes ============

class BudgetCreateRequest(BaseModel):
    """יצירת תקציב"""
    category: str
    planned_amount: float
    period_start: date
    period_end: date
    notes: Optional[str] = None


class ScenarioRequest(BaseModel):
    """בקשת תרחיש"""
    revenue_change_pct: float = 0
    expense_change_pct: float = 0
    name: Optional[str] = None


@router.post("/budget")
async def create_budget(
    request: BudgetCreateRequest,
    db: Session = Depends(get_db)
):
    """יצירת תקציב חדש"""
    service = BudgetService(db)
    budget = service.create_budget(
        category=request.category,
        planned_amount=request.planned_amount,
        period_start=request.period_start,
        period_end=request.period_end,
        notes=request.notes
    )
    return {"status": "success", "data": budget}


@router.get("/budget/vs-actual")
async def get_budget_vs_actual(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    db: Session = Depends(get_db)
):
    """השוואת תקציב מול ביצוע"""
    service = BudgetService(db)
    comparison = service.get_budget_vs_actual(start_date, end_date)
    return {"status": "success", "data": [vars(c) for c in comparison]}


@router.get("/budget/alerts")
async def get_budget_alerts(
    threshold_pct: float = Query(80, ge=0, le=100),
    db: Session = Depends(get_db)
):
    """קבלת התראות תקציב"""
    service = BudgetService(db)
    alerts = service.get_budget_alerts(threshold_pct)
    return {"status": "success", "data": [vars(a) for a in alerts]}


@router.post("/budget/scenario")
async def run_scenario_analysis(
    request: ScenarioRequest,
    db: Session = Depends(get_db)
):
    """הרצת ניתוח תרחיש"""
    service = BudgetService(db)
    scenario = service.run_scenario_analysis(
        revenue_change_pct=request.revenue_change_pct,
        expense_change_pct=request.expense_change_pct
    )
    return {"status": "success", "data": vars(scenario)}


# ============ AR (Accounts Receivable) Routes ============

@router.get("/ar/aging")
async def get_aging_report(
    as_of_date: Optional[date] = None,
    db: Session = Depends(get_db)
):
    """דוח גיול חובות"""
    service = AccountsReceivableService(db)
    report = service.get_aging_report(as_of_date)
    return {
        "status": "success",
        "data": {
            "as_of_date": report.as_of_date,
            "total_receivables": report.total_receivables,
            "buckets": report.buckets,
            "customers": [vars(c) for c in report.customers],
            "summary": report.summary
        }
    }


@router.get("/ar/credit-score/{customer_id}")
async def get_customer_credit_score(
    customer_id: str,
    db: Session = Depends(get_db)
):
    """ציון אשראי לקוח"""
    service = AccountsReceivableService(db)
    score = service.get_customer_credit_score(customer_id)
    return {"status": "success", "data": vars(score)}


@router.get("/ar/payment-reminders")
async def generate_payment_reminders(
    min_days_overdue: int = Query(7, ge=1),
    min_amount: float = Query(100, ge=0),
    db: Session = Depends(get_db)
):
    """יצירת תזכורות תשלום"""
    service = AccountsReceivableService(db)
    reminders = service.generate_payment_reminders(min_days_overdue, min_amount)
    return {"status": "success", "data": [vars(r) for r in reminders]}


@router.get("/ar/collection-forecast")
async def get_collection_forecast(
    days: int = Query(90, ge=30, le=365),
    db: Session = Depends(get_db)
):
    """תחזית גבייה"""
    service = AccountsReceivableService(db)
    forecast = service.get_collection_forecast(days)
    return {"status": "success", "data": forecast}


# ============ AP (Accounts Payable) Routes ============

@router.get("/ap/pending")
async def get_pending_payments(
    db: Session = Depends(get_db)
):
    """תשלומים ממתינים"""
    service = AccountsPayableService(db)
    payments = service.get_pending_payments()
    return {"status": "success", "data": [vars(p) for p in payments]}


@router.get("/ap/payment-schedule")
async def get_payment_schedule(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    db: Session = Depends(get_db)
):
    """לוח תשלומים"""
    service = AccountsPayableService(db)
    schedule = service.create_payment_schedule(start_date, end_date)
    return {
        "status": "success",
        "data": {
            "period_start": schedule.period_start,
            "period_end": schedule.period_end,
            "total_amount": schedule.total_amount,
            "daily_schedule": schedule.daily_schedule,
            "payments_by_priority": schedule.payments_by_priority,
            "cash_flow_impact": schedule.cash_flow_impact
        }
    }


@router.get("/ap/bank-reconciliation")
async def run_bank_reconciliation(
    db: Session = Depends(get_db)
):
    """התאמת בנק"""
    service = AccountsPayableService(db)
    report = service.run_bank_reconciliation()
    return {
        "status": "success",
        "data": {
            "reconciliation_date": report.reconciliation_date,
            "bank_balance": report.bank_balance,
            "book_balance": report.book_balance,
            "difference": report.difference,
            "matched_transactions": report.matched_transactions,
            "unmatched_bank": report.unmatched_bank,
            "unmatched_book": report.unmatched_book,
            "adjustments_needed": report.adjustments_needed
        }
    }


@router.get("/ap/cash-optimization")
async def optimize_cash_flow(
    available_cash: float = Query(..., gt=0),
    db: Session = Depends(get_db)
):
    """אופטימיזציית תזרים"""
    service = AccountsPayableService(db)
    result = service.optimize_cash_flow(available_cash)
    return {"status": "success", "data": result}


# ============ KPI Routes ============

@router.get("/kpis")
async def get_kpi_dashboard(
    period_start: Optional[date] = None,
    period_end: Optional[date] = None,
    db: Session = Depends(get_db)
):
    """דשבורד KPI"""
    service = KPIService(db)
    dashboard = service.get_kpi_dashboard(period_start, period_end)
    return {"status": "success", "data": dashboard}


@router.get("/kpis/executive-summary")
async def get_executive_summary(
    db: Session = Depends(get_db)
):
    """סיכום מנהלים"""
    service = KPIService(db)
    summary = service.get_executive_summary()
    return {"status": "success", "data": vars(summary)}


@router.get("/kpis/benchmark")
async def compare_to_industry(
    industry: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """השוואה לענף"""
    service = KPIService(db)
    comparison = service.compare_to_industry(industry)
    return {"status": "success", "data": comparison}


@router.get("/kpis/trends")
async def get_kpi_trends(
    kpi_names: List[str] = Query(default=['revenue_growth', 'gross_margin', 'net_margin']),
    months: int = Query(12, ge=3, le=36),
    db: Session = Depends(get_db)
):
    """מגמות KPI"""
    service = KPIService(db)
    trends = service.get_kpi_trends(kpi_names, months)
    return {"status": "success", "data": trends}


# ============ Cost Analysis Routes ============

@router.get("/costs/breakdown")
async def get_cost_breakdown(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    db: Session = Depends(get_db)
):
    """פירוט עלויות"""
    service = CostAnalysisService(db)
    breakdown = service.get_cost_breakdown(start_date, end_date)
    return {"status": "success", "data": vars(breakdown)}


@router.get("/costs/profitability")
async def analyze_profitability(
    by: str = Query('customer', regex='^(customer|product|segment)$'),
    db: Session = Depends(get_db)
):
    """ניתוח רווחיות"""
    service = CostAnalysisService(db)
    analysis = service.analyze_profitability(by)
    return {"status": "success", "data": [vars(a) for a in analysis]}


@router.get("/costs/product/{product_id}")
async def calculate_product_cost(
    product_id: str,
    db: Session = Depends(get_db)
):
    """עלות מוצר"""
    service = CostAnalysisService(db)
    cost = service.calculate_product_cost(product_id)
    return {"status": "success", "data": vars(cost)}


@router.get("/costs/break-even")
async def get_break_even_analysis(
    db: Session = Depends(get_db)
):
    """ניתוח נקודת איזון"""
    service = CostAnalysisService(db)
    analysis = service.get_break_even_analysis()
    return {"status": "success", "data": analysis}


@router.get("/costs/cogs")
async def get_cogs_analysis(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    db: Session = Depends(get_db)
):
    """ניתוח עלות המכר"""
    service = CostAnalysisService(db)
    cogs = service.get_cogs_analysis(start_date, end_date)
    return {"status": "success", "data": vars(cogs)}


# ============ Tax Compliance Routes ============

class VATReportRequest(BaseModel):
    """בקשת דוח מע"מ"""
    period_start: date
    period_end: date
    include_details: bool = True


@router.post("/tax/vat-report")
async def generate_vat_report(
    request: VATReportRequest,
    db: Session = Depends(get_db)
):
    """דוח מע"מ"""
    service = TaxComplianceService(db)
    report = service.generate_vat_report(
        request.period_start,
        request.period_end,
        request.include_details
    )
    return {"status": "success", "data": vars(report)}


@router.get("/tax/advance")
async def calculate_tax_advance(
    period: str = Query(..., regex='^[0-9]{4}-[0-9]{2}$'),
    db: Session = Depends(get_db)
):
    """מקדמות מס"""
    year, month = map(int, period.split('-'))
    period_date = date(year, month, 1)
    
    service = TaxComplianceService(db)
    advance = service.calculate_tax_advance(period_date)
    return {"status": "success", "data": vars(advance)}


@router.get("/tax/withholding")
async def generate_withholding_report(
    start_date: date = Query(...),
    end_date: date = Query(...),
    db: Session = Depends(get_db)
):
    """דוח ניכויים"""
    service = TaxComplianceService(db)
    report = service.generate_withholding_report(start_date, end_date)
    return {"status": "success", "data": vars(report)}


@router.get("/tax/calendar")
async def get_tax_calendar(
    year: int = Query(default=None),
    db: Session = Depends(get_db)
):
    """לוח שנה מס"""
    service = TaxComplianceService(db)
    calendar = service.get_tax_calendar(year or date.today().year)
    return {"status": "success", "data": [vars(c) for c in calendar]}


@router.get("/tax/planning")
async def get_tax_planning_suggestions(
    db: Session = Depends(get_db)
):
    """המלצות תכנון מס"""
    service = TaxComplianceService(db)
    suggestions = service.get_tax_planning_suggestions()
    return {"status": "success", "data": suggestions}


# ============ AI Analytics Routes ============

@router.get("/ai/anomalies")
async def detect_anomalies(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    min_confidence: float = Query(0.7, ge=0, le=1),
    db: Session = Depends(get_db)
):
    """זיהוי אנומליות"""
    service = AdvancedAIService(db)
    anomalies = service.detect_anomalies(start_date, end_date, min_confidence)
    return {"status": "success", "data": [vars(a) for a in anomalies]}


@router.get("/ai/risks")
async def assess_financial_risks(
    db: Session = Depends(get_db)
):
    """הערכת סיכונים"""
    service = AdvancedAIService(db)
    risks = service.assess_financial_risks()
    return {"status": "success", "data": [vars(r) for r in risks]}


@router.get("/ai/insights")
async def get_ai_insights(
    focus_areas: Optional[List[str]] = Query(None),
    db: Session = Depends(get_db)
):
    """תובנות AI"""
    service = AdvancedAIService(db)
    insights = service.generate_insights(focus_areas)
    return {"status": "success", "data": [vars(i) for i in insights]}


@router.get("/ai/predict/{metric}")
async def predict_metric(
    metric: str,
    horizon_months: int = Query(6, ge=1, le=24),
    db: Session = Depends(get_db)
):
    """חיזוי מדד"""
    service = AdvancedAIService(db)
    prediction = service.predict_metric(metric, horizon_months)
    return {"status": "success", "data": vars(prediction)}


@router.get("/ai/recommendations")
async def get_ai_recommendations(
    budget: Optional[float] = None,
    focus: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """המלצות AI"""
    service = AdvancedAIService(db)
    recommendations = service.get_ai_recommendations(budget, focus)
    return {"status": "success", "data": [vars(r) for r in recommendations]}


class AIAnalysisRequest(BaseModel):
    """בקשת ניתוח AI"""
    question: str
    context: Optional[Dict] = None


@router.post("/ai/analyze")
async def get_ai_analysis(
    request: AIAnalysisRequest,
    db: Session = Depends(get_db)
):
    """ניתוח AI"""
    service = AdvancedAIService(db)
    analysis = await service.get_ai_analysis(request.question, request.context)
    return {"status": "success", "data": {"analysis": analysis}}


# ============ Report Builder Routes ============

class ReportTemplateRequest(BaseModel):
    """בקשת תבנית דוח"""
    name: str
    report_type: str
    description: str = ''
    columns: List[Dict]
    default_filters: Optional[List[Dict]] = None
    grouping: Optional[List[str]] = None
    sorting: Optional[List[Dict]] = None
    summary_fields: Optional[List[str]] = None
    is_public: bool = False


class ReportGenerateRequest(BaseModel):
    """בקשת יצירת דוח"""
    template_id: str
    format: str = 'excel'
    filters: Optional[List[Dict]] = None
    parameters: Optional[Dict] = None


class ScheduleRequest(BaseModel):
    """בקשת תזמון"""
    template_id: str
    name: str
    frequency: str
    recipients: List[str]
    delivery_method: str = 'email'
    format: str = 'excel'
    filters: Optional[List[Dict]] = None
    parameters: Optional[Dict] = None


@router.get("/reports/templates")
async def get_report_templates(
    report_type: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """תבניות דוחות"""
    service = ReportBuilderService(db)
    templates = service.get_templates(
        report_type=report_type if report_type else None
    )
    return {"status": "success", "data": [vars(t) for t in templates]}


@router.post("/reports/templates")
async def create_report_template(
    request: ReportTemplateRequest,
    db: Session = Depends(get_db)
):
    """יצירת תבנית"""
    service = ReportBuilderService(db)
    template = service.create_template(
        name=request.name,
        report_type=request.report_type,
        columns=request.columns,
        description=request.description,
        default_filters=request.default_filters,
        grouping=request.grouping,
        sorting=request.sorting,
        summary_fields=request.summary_fields,
        is_public=request.is_public
    )
    return {"status": "success", "data": vars(template)}


@router.post("/reports/generate")
async def generate_report(
    request: ReportGenerateRequest,
    db: Session = Depends(get_db)
):
    """יצירת דוח"""
    service = ReportBuilderService(db)
    report = service.generate_report(
        template_id=request.template_id,
        format=ReportFormat(request.format),
        filters=request.filters,
        parameters=request.parameters
    )
    return {"status": "success", "data": vars(report)}


@router.get("/reports/preview/{template_id}")
async def preview_report(
    template_id: str,
    limit: int = Query(100, ge=10, le=1000),
    db: Session = Depends(get_db)
):
    """תצוגה מקדימה"""
    service = ReportBuilderService(db)
    preview = service.preview_report(template_id, limit=limit)
    return {"status": "success", "data": preview}


@router.get("/reports/schedules")
async def get_report_schedules(
    template_id: Optional[str] = None,
    active_only: bool = False,
    db: Session = Depends(get_db)
):
    """תזמונים"""
    service = ReportBuilderService(db)
    schedules = service.get_schedules(template_id, active_only)
    return {"status": "success", "data": [vars(s) for s in schedules]}


@router.post("/reports/schedules")
async def create_report_schedule(
    request: ScheduleRequest,
    db: Session = Depends(get_db)
):
    """יצירת תזמון"""
    service = ReportBuilderService(db)
    schedule = service.create_schedule(
        template_id=request.template_id,
        name=request.name,
        frequency=ReportFrequency(request.frequency),
        recipients=request.recipients,
        format=ReportFormat(request.format),
        filters=request.filters,
        parameters=request.parameters
    )
    return {"status": "success", "data": vars(schedule)}


@router.delete("/reports/schedules/{schedule_id}")
async def delete_report_schedule(
    schedule_id: str,
    db: Session = Depends(get_db)
):
    """מחיקת תזמון"""
    service = ReportBuilderService(db)
    success = service.delete_schedule(schedule_id)
    if not success:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return {"status": "success"}


@router.post("/reports/schedules/{schedule_id}/pause")
async def pause_schedule(
    schedule_id: str,
    db: Session = Depends(get_db)
):
    """השהיית תזמון"""
    service = ReportBuilderService(db)
    success = service.pause_schedule(schedule_id)
    if not success:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return {"status": "success"}


@router.post("/reports/schedules/{schedule_id}/resume")
async def resume_schedule(
    schedule_id: str,
    db: Session = Depends(get_db)
):
    """חידוש תזמון"""
    service = ReportBuilderService(db)
    success = service.resume_schedule(schedule_id)
    if not success:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return {"status": "success"}


@router.get("/reports/history")
async def get_execution_history(
    schedule_id: Optional[str] = None,
    template_id: Optional[str] = None,
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db)
):
    """היסטוריית ביצועים"""
    service = ReportBuilderService(db)
    history = service.get_execution_history(schedule_id, template_id, limit)
    return {"status": "success", "data": [vars(e) for e in history]}


@router.post("/reports/run-scheduled")
async def run_scheduled_reports(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """הרצת דוחות מתוזמנים"""
    service = ReportBuilderService(db)
    # בפרודקשן - background task
    executions = await service.run_scheduled_reports()
    return {"status": "success", "data": [vars(e) for e in executions]}
