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
from ...services.compliance_audit import ComplianceAuditService

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


# ==================== PHASE 12: Compliance & Audit ====================

@router.post("/audit/log-change")
async def log_change(
    action: str,
    entity_type: str,
    entity_id: int,
    changes: dict,
    user_id: Optional[int] = None,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """Log a change for audit trail."""
    service = ComplianceAuditService(db, org_id)
    result = service.log_change(user_id, action, entity_type, entity_id, changes)
    return {"status": "success", "data": result}


@router.get("/audit/trail")
async def get_audit_trail(
    entity_type: Optional[str] = None,
    entity_id: Optional[int] = None,
    action: Optional[str] = None,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """Get filtered audit trail."""
    service = ComplianceAuditService(db, org_id)
    result = service.get_audit_trail(entity_type, entity_id, action, from_date, to_date)
    return {"status": "success", "data": result}


@router.get("/tax/report-1301")
async def tax_report_1301(
    year: int = 2026,
    include_audit: bool = False,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """Generate Israeli tax form 1301."""
    service = ComplianceAuditService(db, org_id)
    result = service.generate_tax_report_1301(year, include_audit)
    return {"status": "success", "data": result}


@router.get("/tax/report-1214")
async def tax_report_1214(
    year: int = 2026,
    include_audit: bool = False,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """Generate Israeli tax form 1214."""
    service = ComplianceAuditService(db, org_id)
    result = service.generate_tax_report_1214(year, include_audit)
    return {"status": "success", "data": result}


@router.get("/audit/export")
async def export_for_auditor(
    year: int = 2026,
    format: str = Query("json", pattern="^(json|csv)$"),
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """Export all data for external auditors."""
    service = ComplianceAuditService(db, org_id)
    result = service.export_for_auditor(year, format)
    return {"status": "success", "data": result}


@router.get("/audit/compliance-checklist")
async def compliance_checklist(
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """Get compliance readiness checklist."""
    service = ComplianceAuditService(db, org_id)
    result = service.compliance_checklist()
    return {"status": "success", "data": result}
