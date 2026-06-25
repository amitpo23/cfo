"""
Phase 13: Analytics & Business Intelligence Routes
Dashboard, reports, and AI insights
"""
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..dependencies import get_db, get_current_org_id
from ...services.analytics_reporting import AnalyticsReportingService
from ...services.expense_analytics import ExpenseAnalyticsService
from ...services.revenue_analytics import RevenueAnalyticsService
from ...services.ai_intelligence_agent import AIIntelligenceAgent


router = APIRouter(prefix="/analytics", tags=["Phase 13: Analytics & BI"])


# ==================== Pydantic Models ====================

class QuestionRequest(BaseModel):
    question: str


# ==================== Phase 13D: Reporting Routes ====================

@router.get("/reports/daily")
async def get_daily_report(
    report_date: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """Get daily financial report with cumulative P&L"""
    try:
        service = AnalyticsReportingService(db, org_id)
        parsed_date = None
        if report_date:
            parsed_date = date.fromisoformat(report_date)
        report = service.generate_daily_report(parsed_date)
        return {"status": "success", "data": report}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/reports/weekly-budget")
async def get_weekly_budget_report(
    report_date: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """Get weekly budget vs actual report"""
    try:
        service = AnalyticsReportingService(db, org_id)
        parsed_date = None
        if report_date:
            parsed_date = date.fromisoformat(report_date)
        report = service.generate_weekly_budget_report(parsed_date)
        return {"status": "success", "data": report}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/reports/monthly-pl")
async def get_monthly_pl_report(
    report_month: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """Get monthly P&L report"""
    try:
        service = AnalyticsReportingService(db, org_id)
        parsed_month = None
        if report_month:
            parsed_month = date.fromisoformat(report_month)
        report = service.generate_monthly_pl_report(parsed_month)
        return {"status": "success", "data": report}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==================== Phase 13B: Expense Analytics Routes ====================

@router.get("/expenses/summary")
async def get_expense_summary(
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """Get expense summary for period"""
    try:
        service = ExpenseAnalyticsService(db, org_id)
        summary = service.get_expense_summary(days=days)
        return {"status": "success", "data": summary}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/expenses/by-category")
async def analyze_category_spending(
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """Analyze spending by category"""
    try:
        service = ExpenseAnalyticsService(db, org_id)
        analysis = service.analyze_category_spending(days=days)
        return {"status": "success", "data": analysis}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/expenses/by-vendor")
async def analyze_vendor_spending(
    days: int = Query(30, ge=1, le=365),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """Analyze spending by vendor"""
    try:
        service = ExpenseAnalyticsService(db, org_id)
        analysis = service.analyze_vendor_spending(days=days, limit=limit)
        return {"status": "success", "data": analysis}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/expenses/anomalies")
async def detect_anomalies(
    days: int = Query(90, ge=1, le=365),
    sensitivity: float = Query(2.0, ge=1.0, le=5.0),
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """Detect spending anomalies (z-score based)"""
    try:
        service = ExpenseAnalyticsService(db, org_id)
        anomalies = service.detect_spending_anomalies(days=days, sensitivity=sensitivity)
        return {"status": "success", "data": anomalies}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/expenses/trends")
async def analyze_spending_trends(
    days: int = Query(180, ge=1, le=365),
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """Analyze spending trends"""
    try:
        service = ExpenseAnalyticsService(db, org_id)
        trends = service.analyze_spending_trends(days=days)
        return {"status": "success", "data": trends}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/expenses/optimization")
async def get_optimization_opportunities(
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """Get cost optimization opportunities"""
    try:
        service = ExpenseAnalyticsService(db, org_id)
        opportunities = service.get_cost_optimization_opportunities()
        return {"status": "success", "data": opportunities}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/expenses/efficiency")
async def get_efficiency_metrics(
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """Get expense efficiency metrics"""
    try:
        service = ExpenseAnalyticsService(db, org_id)
        metrics = service.get_expense_efficiency_metrics()
        return {"status": "success", "data": metrics}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==================== Phase 13A: Revenue Analytics Routes ====================

@router.get("/revenue/summary")
async def get_revenue_summary(
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """Get revenue summary"""
    try:
        service = RevenueAnalyticsService(db, org_id)
        summary = service.get_revenue_summary(days=days)
        return {"status": "success", "data": summary}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/revenue/by-customer")
async def analyze_revenue_by_customer(
    days: int = Query(90, ge=1, le=365),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """Analyze revenue by customer"""
    try:
        service = RevenueAnalyticsService(db, org_id)
        analysis = service.analyze_revenue_by_customer(days=days, limit=limit)
        return {"status": "success", "data": analysis}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/revenue/by-category")
async def analyze_revenue_by_category(
    days: int = Query(90, ge=1, le=365),
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """Analyze revenue by category"""
    try:
        service = RevenueAnalyticsService(db, org_id)
        analysis = service.analyze_revenue_by_category(days=days)
        return {"status": "success", "data": analysis}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/revenue/by-region")
async def analyze_revenue_by_region(
    days: int = Query(90, ge=1, le=365),
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """Analyze revenue by region"""
    try:
        service = RevenueAnalyticsService(db, org_id)
        analysis = service.analyze_revenue_by_region(days=days)
        return {"status": "success", "data": analysis}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/revenue/concentration")
async def analyze_revenue_concentration(
    days: int = Query(90, ge=1, le=365),
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """Analyze revenue concentration risk"""
    try:
        service = RevenueAnalyticsService(db, org_id)
        analysis = service.analyze_revenue_concentration(days=days)
        return {"status": "success", "data": analysis}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/revenue/profitability")
async def analyze_customer_profitability(
    days: int = Query(90, ge=1, le=365),
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """Analyze customer profitability"""
    try:
        service = RevenueAnalyticsService(db, org_id)
        analysis = service.get_customer_profitability(days=days)
        return {"status": "success", "data": analysis}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/revenue/opportunities")
async def identify_investment_opportunities(
    days: int = Query(90, ge=1, le=365),
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """Identify investment opportunities"""
    try:
        service = RevenueAnalyticsService(db, org_id)
        opportunities = service.identify_investment_opportunities(days=days)
        return {"status": "success", "data": opportunities}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/revenue/trends")
async def analyze_revenue_trends(
    days: int = Query(180, ge=1, le=365),
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """Analyze revenue trends"""
    try:
        service = RevenueAnalyticsService(db, org_id)
        trends = service.analyze_revenue_trends(days=days)
        return {"status": "success", "data": trends}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/revenue/pipeline")
async def get_sales_pipeline_health(
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """Get sales pipeline health"""
    try:
        service = RevenueAnalyticsService(db, org_id)
        health = service.get_sales_pipeline_health()
        return {"status": "success", "data": health}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==================== Phase 13C: AI Intelligence Agent Routes ====================

@router.post("/ai/ask")
async def ask_financial_question(
    request: QuestionRequest,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """Ask AI agent a financial question"""
    try:
        agent = AIIntelligenceAgent(db, org_id)
        answer = agent.answer_financial_question(request.question)
        return {"status": "success", "data": answer}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/ai/insights")
async def get_daily_insights(
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """Get daily automated insights"""
    try:
        agent = AIIntelligenceAgent(db, org_id)
        insights = agent.generate_daily_insights()
        return {"status": "success", "data": insights}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/ai/health-score")
async def get_financial_health_score(
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """Get financial health score (0-100)"""
    try:
        agent = AIIntelligenceAgent(db, org_id)
        score = agent.get_financial_health_score()
        return {"status": "success", "data": score}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/ai/executive-summary")
async def get_executive_summary(
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """Get executive summary for decision makers"""
    try:
        agent = AIIntelligenceAgent(db, org_id)
        summary = agent.get_executive_summary()
        return {"status": "success", "data": summary}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
