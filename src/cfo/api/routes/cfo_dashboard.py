"""
CFO Dashboard API routes.
/api/dashboard/* endpoints for overview, cashflow, P&L.
"""
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ...database import get_db_session
from ..dependencies import get_current_org_id
from ...services.dashboard_service import DashboardService
from ...services.financial_control_service import FinancialControlService

router = APIRouter()

# Default org ID for single-tenant mode


class ReconciliationApplyRequest(BaseModel):
    bank_transaction_id: int = Field(..., ge=1)
    entity_type: str
    entity_id: int = Field(..., ge=1)


@router.get("/dashboard/overview")
async def get_overview(
    org_id: int = Depends(get_current_org_id),
    db: Session = Depends(get_db_session),
):
    """CFO overview: cash, revenue, expenses, runway, AR/AP, alerts."""
    svc = DashboardService(db, org_id)
    return svc.get_overview()


@router.get("/dashboard/cashflow")
async def get_cashflow(
    weeks: int = Query(12, ge=1, le=52),
    scenario: str = Query("base"),
    org_id: int = Depends(get_current_org_id),
    db: Session = Depends(get_db_session),
):
    """Cash flow projection for next N weeks with scenario support."""
    svc = DashboardService(db, org_id)
    return svc.get_cashflow_projection(weeks=weeks, scenario=scenario)


@router.get("/dashboard/pnl")
async def get_pnl(
    months: int = Query(6, ge=1, le=24),
    org_id: int = Depends(get_current_org_id),
    db: Session = Depends(get_db_session),
):
    """Monthly P&L for the past N months."""
    svc = DashboardService(db, org_id)
    return svc.get_pnl(months=months)


@router.get("/ar/aging")
async def get_ar_aging(
    org_id: int = Depends(get_current_org_id),
    db: Session = Depends(get_db_session),
):
    """AR aging report with bucket breakdown and invoice list."""
    svc = DashboardService(db, org_id)
    return svc.get_ar_aging()


@router.get("/ar/invoices")
async def get_ar_invoices(
    status: Optional[str] = None,
    org_id: int = Depends(get_current_org_id),
    db: Session = Depends(get_db_session),
):
    """List invoices with optional status filter."""
    from ...models import Invoice, InvoiceStatus, Contact

    query = db.query(Invoice).filter(Invoice.organization_id == org_id)

    if status:
        try:
            query = query.filter(Invoice.status == InvoiceStatus(status))
        except ValueError:
            pass

    invoices = query.order_by(Invoice.due_date.desc()).limit(200).all()

    result = []
    for inv in invoices:
        contact_name = None
        if inv.contact_id:
            contact = db.get(Contact, inv.contact_id)
            if contact:
                contact_name = contact.name

        result.append({
            "id": inv.id,
            "invoice_number": inv.invoice_number,
            "customer": contact_name,
            "issue_date": inv.issue_date.isoformat() if inv.issue_date else None,
            "due_date": inv.due_date.isoformat() if inv.due_date else None,
            "status": inv.status.value if inv.status else None,
            "total": float(inv.total or 0),
            "paid_amount": float(inv.paid_amount or 0),
            "balance": float(inv.balance or 0),
            "currency": inv.currency,
        })

    return result


@router.get("/ap/bills")
async def get_ap_bills(
    days_ahead: int = Query(30, ge=1),
    org_id: int = Depends(get_current_org_id),
    db: Session = Depends(get_db_session),
):
    """List unpaid bills sorted by due date."""
    svc = DashboardService(db, org_id)
    return svc.get_ap_bills(days_ahead=days_ahead)


@router.get("/budget/variance")
async def get_budget_variance(
    year: int = Query(None),
    month: int = Query(None),
    org_id: int = Depends(get_current_org_id),
    db: Session = Depends(get_db_session),
):
    """Budget vs actual variance report."""
    if not year:
        year = date.today().year
    if not month:
        month = date.today().month
    svc = DashboardService(db, org_id)
    return svc.get_budget_variance(year, month)


@router.get("/control/overview")
async def get_financial_control_overview(
    org_id: int = Depends(get_current_org_id),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    db: Session = Depends(get_db_session),
):
    """Unified CFO control overview across books, bank data, and budget."""
    svc = FinancialControlService(db, org_id)
    return svc.get_control_overview(start_date=start_date, end_date=end_date)


@router.get("/control/reconciliation/suggestions")
async def get_reconciliation_suggestions(
    org_id: int = Depends(get_current_org_id),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    amount_tolerance: float = Query(1.0, ge=0),
    date_tolerance_days: int = Query(7, ge=0, le=60),
    db: Session = Depends(get_db_session),
):
    """Suggest matches between bank transactions and SUMIT/book records."""
    svc = FinancialControlService(db, org_id)
    return svc.suggest_bank_reconciliations(
        start_date=start_date,
        end_date=end_date,
        limit=limit,
        amount_tolerance=amount_tolerance,
        date_tolerance_days=date_tolerance_days,
    )


@router.post("/control/reconciliation/apply")
async def apply_reconciliation(
    request: ReconciliationApplyRequest,
    org_id: int = Depends(get_current_org_id),
    db: Session = Depends(get_db_session),
):
    """Mark a bank transaction as reconciled with a chosen accounting entity."""
    svc = FinancialControlService(db, org_id)
    try:
        return svc.apply_bank_reconciliation(
            bank_transaction_id=request.bank_transaction_id,
            entity_type=request.entity_type,
            entity_id=request.entity_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/control/expenses")
async def get_expense_control(
    org_id: int = Depends(get_current_org_id),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    limit: int = Query(12, ge=1, le=50),
    db: Session = Depends(get_db_session),
):
    """Expense control by category for dashboards and budget review."""
    svc = FinancialControlService(db, org_id)
    return svc.get_expense_control(
        start_date=start_date,
        end_date=end_date,
        limit=limit,
    )
