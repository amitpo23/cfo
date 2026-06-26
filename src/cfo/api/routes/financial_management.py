"""
Financial Management API Routes
נתיבי API לניהול פיננסי
"""
import io
from datetime import date, datetime
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks, UploadFile, File
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..dependencies import get_db, get_current_org_id, require_admin
from ...models import BankTransaction
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
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """יצירת תקציב חדש"""
    service = BudgetService(db, organization_id=org_id)
    budget = service.create_budget(
        category=request.category,
        planned_amount=request.planned_amount,
        period_start=request.period_start,
        period_end=request.period_end,
        notes=request.notes
    )
    return {"status": "success", "data": budget}


class BudgetBulkItem(BaseModel):
    category: str
    year: int
    month: int
    amount: float


class BudgetBulkRequest(BaseModel):
    items: List[BudgetBulkItem]


@router.post("/budget/bulk")
async def create_budgets_bulk(
    request: BudgetBulkRequest,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """הזנת תקציבים מרובים בבת אחת (טבלת הזנה נוחה)."""
    service = BudgetService(db, organization_id=org_id)
    result = service.bulk_upsert([i.model_dump() for i in request.items])
    return {"status": "success", "data": result}


@router.get("/budget/template")
async def download_budget_template(
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """הורדת תבנית Excel להזנת תקציב."""
    service = BudgetService(db, organization_id=org_id)
    content = service.export_template()
    return StreamingResponse(
        io.BytesIO(content),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=budget_template.xlsx"},
    )


@router.post("/budget/import")
async def import_budget_excel(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """ייבוא תקציב מקובץ Excel."""
    content = await file.read()
    service = BudgetService(db, organization_id=org_id)
    try:
        result = service.import_from_excel(content, default_year=date.today().year)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"status": "success", "data": result}


@router.get("/budget/vs-actual")
async def get_budget_vs_actual(
    year: Optional[int] = None,
    month: Optional[int] = None,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """השוואת תקציב מול ביצוע"""
    service = BudgetService(db, organization_id=org_id)
    summary = service.get_budget_vs_actual(year or date.today().year, month)
    return {"status": "success", "data": vars(summary)}


@router.get("/budget/alerts")
async def get_budget_alerts(
    threshold_pct: float = Query(80, ge=0, le=100),
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """קבלת התראות תקציב"""
    service = BudgetService(db, organization_id=org_id)
    alerts = service.get_budget_alerts(threshold_pct)
    return {"status": "success", "data": [vars(a) for a in alerts]}


@router.post("/budget/scenario")
async def run_scenario_analysis(
    request: ScenarioRequest,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """הרצת ניתוח תרחיש"""
    service = BudgetService(db, organization_id=org_id)
    scenario = service.project_scenario(
        revenue_change_pct=request.revenue_change_pct,
        expense_change_pct=request.expense_change_pct,
    )
    return {"status": "success", "data": scenario}


# ============ AR (Accounts Receivable) Routes ============

@router.get("/ar/aging")
async def get_aging_report(
    as_of_date: Optional[date] = None,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """דוח גיול חובות"""
    service = AccountsReceivableService(db, organization_id=org_id)
    report = service.get_aging_report(as_of_date)
    return {
        "status": "success",
        "data": {
            "as_of_date": report.report_date,
            "total_receivables": report.total_receivables,
            "buckets": {
                "current": report.current_total,
                "days_31_60": report.days_31_60_total,
                "days_61_90": report.days_61_90_total,
                "days_91_120": report.days_91_120_total,
                "over_120": report.over_120_total,
            },
            "weighted_average_days": report.weighted_average_days,
            "customers": [vars(c) for c in report.customers],
            "summary": {
                "risk": report.risk_summary,
                "collection": report.collection_summary,
            },
        }
    }


@router.get("/ar/invoices-status")
async def get_invoices_status(
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """דוח סטטוס חשבוניות אמיתי: שולם / חלקי / לא שולם + סכומים."""
    service = AccountsReceivableService(db, organization_id=org_id)
    return {"status": "success", "data": service.get_invoices_status_report()}


@router.get("/ar/credit-score/{customer_id}")
async def get_customer_credit_score(
    customer_id: str,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """ציון אשראי לקוח"""
    service = AccountsReceivableService(db, organization_id=org_id)
    score = service.get_customer_credit_score(customer_id)
    return {"status": "success", "data": vars(score)}


@router.get("/ar/payment-reminders")
async def generate_payment_reminders(
    min_days_overdue: int = Query(7, ge=1),
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """יצירת תזכורות תשלום"""
    service = AccountsReceivableService(db, organization_id=org_id)
    reminders = service.generate_payment_reminders(min_days_overdue)
    return {"status": "success", "data": [vars(r) for r in reminders]}


@router.get("/ar/collection-forecast")
async def get_collection_forecast(
    days: int = Query(90, ge=30, le=365),
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """תחזית גבייה"""
    service = AccountsReceivableService(db, organization_id=org_id)
    forecast = service.get_collection_forecast(days)
    return {"status": "success", "data": forecast}


# ============ AP (Accounts Payable) Routes ============

@router.get("/ap/pending")
async def get_pending_payments(
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """תשלומים ממתינים"""
    service = AccountsPayableService(db, organization_id=org_id)
    payments = service.get_pending_payments()
    return {"status": "success", "data": [vars(p) for p in payments]}


@router.get("/ap/payment-schedule")
async def get_payment_schedule(
    schedule_date: Optional[date] = None,
    available_cash: float = Query(0, ge=0),
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """לוח תשלומים"""
    service = AccountsPayableService(db, organization_id=org_id)
    schedule = service.create_payment_schedule(
        schedule_date or date.today(), available_cash
    )
    return {
        "status": "success",
        "data": {
            "schedule_date": schedule.schedule_date,
            "total_payments": schedule.total_payments,
            "total_amount": schedule.total_amount,
            "cash_available": schedule.cash_available,
            "cash_after_payments": schedule.cash_after_payments,
            "payments": [vars(p) for p in schedule.payments],
            "recommendations": schedule.recommendations,
        }
    }


@router.get("/ap/bank-reconciliation")
async def run_bank_reconciliation(
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """התאמת בנק — מול תנועות הבנק המיובאות והתשלומים בספרים."""
    bank_rows = (
        db.query(BankTransaction)
        .filter(BankTransaction.organization_id == org_id)
        .all()
    )
    bank_statement = [
        {
            "date": r.transaction_date.isoformat(),
            "description": r.description or "",
            "amount": float(r.amount or 0),
        }
        for r in bank_rows
    ]
    service = AccountsPayableService(db, organization_id=org_id)
    report = service.run_bank_reconciliation(bank_statement)
    return {
        "status": "success",
        "data": {
            "reconciliation_date": report.reconciliation_date,
            "bank_balance": report.bank_balance,
            "book_balance": report.book_balance,
            "difference": report.difference,
            "reconciled_percentage": report.reconciled_percentage,
            "matched_items": [vars(m) for m in report.matched_items],
            "unmatched_bank_items": [vars(m) for m in report.unmatched_bank_items],
            "unmatched_book_items": [vars(m) for m in report.unmatched_book_items],
            "adjustments_needed": report.adjustments_needed,
        }
    }


@router.get("/ap/cash-optimization")
async def optimize_cash_flow(
    available_cash: float = Query(..., gt=0),
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """אופטימיזציית תזרים"""
    service = AccountsPayableService(db, organization_id=org_id)
    result = service.optimize_cash_flow(available_cash)
    return {"status": "success", "data": result}


# ============ KPI Routes ============

@router.get("/kpis")
async def get_kpi_dashboard(
    period_start: Optional[date] = None,
    period_end: Optional[date] = None,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """דשבורד KPI"""
    service = KPIService(db, organization_id=org_id)
    dashboard = service.get_kpi_dashboard(period_start, period_end)
    return {"status": "success", "data": dashboard}


@router.get("/kpis/executive-summary")
async def get_executive_summary(
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """סיכום מנהלים"""
    service = KPIService(db, organization_id=org_id)
    summary = service.get_executive_summary()
    return {"status": "success", "data": vars(summary)}


@router.get("/kpis/benchmark")
async def compare_to_industry(
    industry: Optional[str] = None,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """השוואה לענף"""
    service = KPIService(db, organization_id=org_id)
    comparison = service.compare_to_industry(industry)
    return {"status": "success", "data": comparison}


@router.get("/kpis/trends")
async def get_kpi_trends(
    kpi_names: List[str] = Query(default=['revenue_growth', 'gross_margin', 'net_margin']),
    months: int = Query(12, ge=3, le=36),
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """מגמות KPI"""
    service = KPIService(db, organization_id=org_id)
    trends = {name: service.get_kpi_trend(name, months) for name in kpi_names}
    return {"status": "success", "data": trends}


# ============ Cost Analysis Routes ============

@router.get("/costs/breakdown")
async def get_cost_breakdown(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """פירוט עלויות"""
    service = CostAnalysisService(db, organization_id=org_id)
    breakdown = service.get_cost_breakdown(start_date, end_date)
    return {"status": "success", "data": vars(breakdown)}


@router.get("/costs/profitability")
async def analyze_profitability(
    by: str = Query('customer', regex='^(customer|product|segment)$'),
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """ניתוח רווחיות"""
    service = CostAnalysisService(db, organization_id=org_id)
    analysis = service.analyze_profitability(by)
    return {"status": "success", "data": vars(analysis)}


@router.get("/costs/product/{product_id}")
async def calculate_product_cost(
    product_id: str,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """עלות מוצר"""
    service = CostAnalysisService(db, organization_id=org_id)
    cost = service.calculate_product_cost(product_id)
    return {"status": "success", "data": vars(cost)}


@router.get("/costs/break-even")
async def get_break_even_analysis(
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """ניתוח נקודת איזון"""
    service = CostAnalysisService(db, organization_id=org_id)
    analysis = service.get_break_even_analysis()
    return {"status": "success", "data": analysis}


@router.get("/costs/cogs")
async def get_cogs_analysis(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """ניתוח עלות המכר"""
    service = CostAnalysisService(db, organization_id=org_id)
    cogs = service.analyze_cogs(start_date, end_date)
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
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """דוח מע"מ (לפי חודש תקופת ההתחלה)"""
    service = TaxComplianceService(db, organization_id=org_id)
    report = service.generate_vat_report(
        request.period_start.year,
        request.period_start.month,
    )
    return {"status": "success", "data": vars(report)}


@router.get("/tax/advance")
async def calculate_tax_advance(
    period: str = Query(..., regex='^[0-9]{4}-[0-9]{2}$'),
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """מקדמות מס"""
    year, month = map(int, period.split('-'))

    service = TaxComplianceService(db, organization_id=org_id)
    advance = service.calculate_tax_advance(year, month)
    return {"status": "success", "data": vars(advance)}


@router.get("/tax/withholding")
async def generate_withholding_report(
    period: str = Query(..., regex='^[0-9]{4}-[0-9]{2}$'),
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """דוח ניכויים (חודש)"""
    year, month = map(int, period.split('-'))
    service = TaxComplianceService(db, organization_id=org_id)
    report = service.generate_withholding_report(year, month)
    return {"status": "success", "data": vars(report)}


@router.get("/tax/856")
async def generate_856_report(
    year: int = Query(...),
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """דוח 856 שנתי — ניכויים מספקים (טיוטה)."""
    service = TaxComplianceService(db, organization_id=org_id)
    return {"status": "success", "data": service.generate_856(year)}


@router.post("/contacts/{contact_id}/withholding-rate")
async def set_contact_withholding_rate(
    contact_id: int,
    rate: float = Query(..., ge=0, le=1),
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """קביעת שיעור ניכוי מס במקור לספק (0 = יש אישור; 0.30/0.20 ללא אישור)."""
    from ...models import Contact
    contact = db.query(Contact).filter(
        Contact.id == contact_id, Contact.organization_id == org_id).first()
    if not contact:
        raise HTTPException(status_code=404, detail="ספק לא נמצא")
    contact.withholding_rate = rate
    db.commit()
    return {"status": "success", "contact_id": contact_id, "withholding_rate": rate}


@router.get("/tax/calendar")
async def get_tax_calendar(
    year: int = Query(default=None),
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """לוח שנה מס"""
    service = TaxComplianceService(db, organization_id=org_id)
    calendar = service.get_tax_calendar(year or date.today().year)
    return {"status": "success", "data": vars(calendar)}


@router.get("/tax/planning")
async def get_tax_planning_suggestions(
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """המלצות תכנון מס"""
    service = TaxComplianceService(db, organization_id=org_id)
    suggestions = service.get_tax_planning_suggestions()
    return {"status": "success", "data": suggestions}


# ============ AI Analytics Routes ============

@router.get("/ai/anomalies")
async def detect_anomalies(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    min_confidence: float = Query(0.7, ge=0, le=1),
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """זיהוי אנומליות"""
    service = AdvancedAIService(db, organization_id=org_id)
    anomalies = service.detect_anomalies(start_date, end_date, min_confidence)
    return {"status": "success", "data": [vars(a) for a in anomalies]}


@router.get("/ai/risks")
async def assess_financial_risks(
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """הערכת סיכונים"""
    service = AdvancedAIService(db, organization_id=org_id)
    risks = service.assess_financial_risks()
    return {"status": "success", "data": [vars(r) for r in risks]}


@router.get("/ai/insights")
async def get_ai_insights(
    focus_areas: Optional[List[str]] = Query(None),
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """תובנות AI"""
    service = AdvancedAIService(db, organization_id=org_id)
    insights = service.generate_insights(focus_areas)
    return {"status": "success", "data": [vars(i) for i in insights]}


@router.get("/ai/predict/{metric}")
async def predict_metric(
    metric: str,
    horizon_months: int = Query(6, ge=1, le=24),
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """חיזוי מדד"""
    service = AdvancedAIService(db, organization_id=org_id)
    prediction = service.predict_metric(metric, horizon_months)
    return {"status": "success", "data": vars(prediction)}


@router.get("/ai/recommendations")
async def get_ai_recommendations(
    budget: Optional[float] = None,
    focus: Optional[str] = None,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """המלצות AI"""
    service = AdvancedAIService(db, organization_id=org_id)
    recommendations = service.get_ai_recommendations(budget, focus)
    return {"status": "success", "data": [vars(r) for r in recommendations]}


class AIAnalysisRequest(BaseModel):
    """בקשת ניתוח AI"""
    question: str
    context: Optional[Dict] = None


@router.post("/ai/analyze")
async def get_ai_analysis(
    request: AIAnalysisRequest,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """ניתוח AI"""
    service = AdvancedAIService(db, organization_id=org_id)
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
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """תבניות דוחות"""
    service = ReportBuilderService(db, organization_id=org_id)
    templates = service.get_templates(
        report_type=report_type if report_type else None
    )
    return {"status": "success", "data": [vars(t) for t in templates]}


@router.post("/reports/templates")
async def create_report_template(
    request: ReportTemplateRequest,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """יצירת תבנית"""
    service = ReportBuilderService(db, organization_id=org_id)
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
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """יצירת דוח"""
    service = ReportBuilderService(db, organization_id=org_id)
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
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """תצוגה מקדימה"""
    service = ReportBuilderService(db, organization_id=org_id)
    try:
        preview = service.preview_report(template_id, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"status": "success", "data": preview}


@router.get("/reports/schedules")
async def get_report_schedules(
    template_id: Optional[str] = None,
    active_only: bool = False,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """תזמונים"""
    service = ReportBuilderService(db, organization_id=org_id)
    schedules = service.get_schedules(template_id, active_only)
    return {"status": "success", "data": [vars(s) for s in schedules]}


@router.post("/reports/schedules")
async def create_report_schedule(
    request: ScheduleRequest,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """יצירת תזמון"""
    service = ReportBuilderService(db, organization_id=org_id)
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
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """מחיקת תזמון"""
    service = ReportBuilderService(db, organization_id=org_id)
    success = service.delete_schedule(schedule_id)
    if not success:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return {"status": "success"}


@router.post("/reports/schedules/{schedule_id}/pause")
async def pause_schedule(
    schedule_id: str,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """השהיית תזמון"""
    service = ReportBuilderService(db, organization_id=org_id)
    success = service.pause_schedule(schedule_id)
    if not success:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return {"status": "success"}


@router.post("/reports/schedules/{schedule_id}/resume")
async def resume_schedule(
    schedule_id: str,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """חידוש תזמון"""
    service = ReportBuilderService(db, organization_id=org_id)
    success = service.resume_schedule(schedule_id)
    if not success:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return {"status": "success"}


@router.get("/reports/history")
async def get_execution_history(
    schedule_id: Optional[str] = None,
    template_id: Optional[str] = None,
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """היסטוריית ביצועים"""
    service = ReportBuilderService(db, organization_id=org_id)
    history = service.get_execution_history(schedule_id, template_id, limit)
    return {"status": "success", "data": [vars(e) for e in history]}


@router.post("/reports/run-scheduled")
async def run_scheduled_reports(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """הרצת דוחות מתוזמנים"""
    service = ReportBuilderService(db, organization_id=org_id)
    # בפרודקשן - background task
    executions = await service.run_scheduled_reports()
    return {"status": "success", "data": [vars(e) for e in executions]}


# ============ Collection Reminder Routes ============

from ...integrations.sumit_models import SMSRequest
from ...services.collection_service import CollectionService, dispatch_reminders
from ...services.email_sender import send_email_smtp
from ...config import settings


@router.get("/collection/due")
async def collection_due(
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """תצוגה מקדימה של תזכורות גבייה מתוכננות (ללא שליחה)"""
    planned = CollectionService(db, org_id).plan_reminders(date.today())
    return {"due": [
        {
            "contact_name": p.contact_name,
            "total_amount": p.total_amount,
            "days_overdue": p.days_overdue,
            "reminder_type": p.reminder_type,
            "channels": [c for c in (("sms" if p.phone else None),
                                     ("email" if p.email else None)) if c],
        }
        for p in planned
    ]}


@router.post("/collection/run", dependencies=[Depends(require_admin)])
async def collection_run(
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """הרצה ידנית של תזכורות גבייה (מנהל בלבד)"""
    from ...models import Organization
    from ..dependencies import sumit_for_org
    org = db.get(Organization, org_id)
    if not org or not org.collection_reminders_enabled:
        raise HTTPException(status_code=403,
                            detail="Collection reminders are disabled for this organization")
    planned = CollectionService(db, org_id).plan_reminders(date.today())
    sumit = sumit_for_org(db, org_id)

    async def sms_sender(phone, message):
        if sumit is None:
            return False
        return bool(await sumit.send_sms(SMSRequest(phone_number=phone, message=message)))

    async def email_sender(to, subject, body):
        return await send_email_smtp(to, subject, body, settings)

    summary = await dispatch_reminders(db, org_id, planned, sms_sender, email_sender)
    return {"status": "ok", "summary": summary}
