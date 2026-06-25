"""
Advanced features routes — Phase 9 integration.
Includes: email intake, self-invoices, check reconciliation, AR/AP aging, ML training.
"""
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..dependencies import get_db, get_current_org_id
from ...services.expense_intake_email import EmailExpenseIntakeService
from ...services.self_invoice_service import SelfInvoiceService
from ...services.check_reconciliation import CheckReconciliationService
from ...services.ar_ap_aging import ARAPAgingService
from ...services.classifier_ml_training import ClassifierMLTrainingService

router = APIRouter(prefix="/advanced", tags=["Advanced Features"])


# ==================== Email Expense Intake ====================

class EmailIntakeRequest(BaseModel):
    imap_host: str
    imap_port: int = 993
    email_address: str
    email_password: str


@router.post("/email-intake/poll")
async def poll_email_inbox(
    request: EmailIntakeRequest,
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """Poll IMAP inbox for expense submissions with attachments."""
    service = EmailExpenseIntakeService(
        db,
        org_id,
        request.imap_host,
        request.imap_port,
        request.email_address,
        request.email_password,
    )
    try:
        result = await service.poll_inbox(limit=limit)
        return {"status": "success", "data": result}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# ==================== Self-Invoices ====================

class SelfInvoiceRequest(BaseModel):
    invoice_type: str  # owner_drawing, internal_transfer, reimbursement, loan_repay
    amount: float
    vat_amount: float = 0
    date_issued: Optional[date] = None
    description: str = ""
    reference_number: Optional[str] = None


@router.post("/self-invoices")
async def create_self_invoice(
    request: SelfInvoiceRequest,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """Create a self-invoice (internal transaction)."""
    from decimal import Decimal
    service = SelfInvoiceService(db, org_id)
    try:
        result = service.create_self_invoice(
            request.invoice_type,
            Decimal(str(request.amount)),
            Decimal(str(request.vat_amount)),
            request.date_issued,
            request.description,
            request.reference_number,
        )
        return {"status": "success", "data": result}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/self-invoices")
async def list_self_invoices(
    invoice_type: Optional[str] = None,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """List self-invoices."""
    service = SelfInvoiceService(db, org_id)
    return {"status": "success", "data": service.list_self_invoices(invoice_type, from_date, to_date)}


@router.get("/self-invoices/summary")
async def self_invoice_summary(
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """Summary of self-invoices by type."""
    service = SelfInvoiceService(db, org_id)
    return {"status": "success", "data": service.get_self_invoice_summary(from_date, to_date)}


# ==================== Check Reconciliation ====================

class CheckDepositRequest(BaseModel):
    check_number: str
    amount: float
    payer_name: str
    deposit_date: date
    image_base64: Optional[str] = None


@router.post("/checks/deposit")
async def record_check_deposit(
    request: CheckDepositRequest,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """Record a check deposit."""
    service = CheckReconciliationService(db, org_id)
    result = service.record_check_deposit(
        request.check_number,
        request.amount,
        request.payer_name,
        request.deposit_date,
        request.image_base64,
    )
    return {"status": "success", "data": result}


@router.post("/checks/clear")
async def match_check_to_clearing(
    check_txn_id: int,
    bank_txn_id: int,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """Link a deposited check to its bank clearing."""
    service = CheckReconciliationService(db, org_id)
    try:
        result = service.match_check_to_clearing(check_txn_id, bank_txn_id)
        return {"status": "success", "data": result}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/checks/pending")
async def list_pending_checks(
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """List checks deposited but not yet cleared."""
    service = CheckReconciliationService(db, org_id)
    return {"status": "success", "data": service.list_pending_checks(limit)}


@router.get("/checks/aging")
async def check_aging_report(
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """Report of checks by clearing age."""
    service = CheckReconciliationService(db, org_id)
    return {"status": "success", "data": service.get_check_aging()}


# ==================== AR/AP Aging ====================

@router.get("/ar-aging")
async def ar_aging_report(
    as_of_date: Optional[date] = None,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """Accounts Receivable aging report."""
    service = ARAPAgingService(db, org_id)
    return {"status": "success", "data": service.ar_aging_report(as_of_date)}


@router.get("/ap-aging")
async def ap_aging_report(
    as_of_date: Optional[date] = None,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """Accounts Payable aging report."""
    service = ARAPAgingService(db, org_id)
    return {"status": "success", "data": service.ap_aging_report(as_of_date)}


@router.get("/ar-ap-summary")
async def ar_ap_summary(
    as_of_date: Optional[date] = None,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """Combined AR/AP summary and net working capital."""
    service = ARAPAgingService(db, org_id)
    return {"status": "success", "data": service.ar_ap_summary(as_of_date)}


# ==================== ML Classifier Training ====================

@router.get("/classifier/feedback-analysis")
async def analyze_classifier_feedback(
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """Analyze classifier feedback patterns."""
    service = ClassifierMLTrainingService(db, org_id)
    return {"status": "success", "data": service.analyze_feedback()}


@router.get("/classifier/training-data")
async def export_training_data(
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """Export feedback as training data for ML models."""
    service = ClassifierMLTrainingService(db, org_id)
    return {"status": "success", "data": service.export_training_data()}


@router.get("/classifier/retraining-recommendation")
async def retraining_recommendation(
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """Get recommendation on when to retrain classifier."""
    service = ClassifierMLTrainingService(db, org_id)
    return {"status": "success", "data": service.recommend_classifier_update()}


@router.get("/classifier/updated-keywords")
async def get_updated_keywords(
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """Get keyword recommendations from user feedback."""
    service = ClassifierMLTrainingService(db, org_id)
    return {"status": "success", "data": service.generate_updated_keywords()}
