"""
Phase 10-12: Payment Orchestration, Forecasting, Compliance & Audit routes.
"""
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..dependencies import get_db, get_current_org_id
from ...services.payment_orchestration import PaymentOrchestrationService
from ...services.forecasting_advanced import AdvancedForecastingService

router = APIRouter(prefix="/advanced", tags=["Phase 10-12: Advanced Services"])


# ==================== PHASE 10: Payment Orchestration ====================

class PaymentSuggestionRequest(BaseModel):
    urgency: str = "normal"
    max_amount: Optional[float] = None


class ExecutePaymentRequest(BaseModel):
    bill_id: int
    method: str
    amount: Optional[float] = None
    scheduled_date: Optional[date] = None


@router.post("/payments/suggest")
async def suggest_payments(
    request: PaymentSuggestionRequest,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """Get intelligent payment suggestions."""
    from decimal import Decimal
    service = PaymentOrchestrationService(db, org_id)
    max_amt = Decimal(str(request.max_amount)) if request.max_amount else None
    result = service.suggest_payments(request.urgency, max_amt)
    return {"status": "success", "data": result}


@router.post("/payments/execute")
async def execute_payment(
    request: ExecutePaymentRequest,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """Execute or schedule a payment."""
    from decimal import Decimal
    service = PaymentOrchestrationService(db, org_id)
    try:
        amt = Decimal(str(request.amount)) if request.amount else None
        result = service.execute_payment(
            request.bill_id,
            request.method,
            amt,
            request.scheduled_date,
        )
        return {"status": "success", "data": result}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/payments/status/{bill_id}")
async def payment_status(
    bill_id: int,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """Get payment status and history."""
    service = PaymentOrchestrationService(db, org_id)
    try:
        result = service.get_payment_status(bill_id)
        return {"status": "success", "data": result}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


# ==================== PHASE 11: Forecasting ====================

class ScenarioRequest(BaseModel):
    name: str
    assumptions: dict


@router.get("/forecast/cash-flow")
async def forecast_cash_flow(
    days_ahead: int = Query(90, ge=1, le=365),
    starting_balance: Optional[float] = None,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """Get cash flow forecast."""
    from decimal import Decimal
    service = AdvancedForecastingService(db, org_id)
    start_bal = Decimal(str(starting_balance)) if starting_balance else None
    result = service.forecast_cash_flow(days_ahead, start_bal)
    return {"status": "success", "data": result}


@router.get("/forecast/budget-vs-actual")
async def budget_vs_actual(
    period: str = Query("monthly", pattern="^(monthly|quarterly|yearly)$"),
    year: int = 2026,
    month: Optional[int] = None,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """Get budget vs actual analysis."""
    service = AdvancedForecastingService(db, org_id)
    result = service.budget_vs_actual(period, year, month)
    return {"status": "success", "data": result}


@router.post("/forecast/scenario-analysis")
async def scenario_analysis(
    scenarios: list[ScenarioRequest],
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """Compare multiple scenarios (what-if analysis)."""
    service = AdvancedForecastingService(db, org_id)
    scenario_dicts = [s.model_dump() for s in scenarios]
    result = service.scenario_analysis(scenario_dicts)
    return {"status": "success", "data": result}


# Phase 12 (Compliance & Audit) was removed 2026-07-04: every method in
# ComplianceAuditService returned hardcoded/fabricated data (a
# compliance_checklist() that unconditionally claimed "100% compliant,
# audit-export ready" regardless of actual state; tax report generators
# that always returned zeros). Real, working equivalents for the two tax
# reports already exist at /api/annual-reports/1301 and /1214
# (annual_report_service.form_1301/form_1214, computed from real data).
# The other four (log-change, trail, export, checklist) had no real
# implementation and zero frontend consumers (confirmed via grep) — see
# docs/PRODUCT_AUDIT_AND_ROADMAP.md P1 #11 and .superpowers/sdd/progress.md.
