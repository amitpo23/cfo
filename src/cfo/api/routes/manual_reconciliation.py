"""
Manual bank reconciliation routes — user-driven override and feedback.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..dependencies import get_db, get_current_org_id
from ...services.manual_reconciliation import ManualReconciliationService

router = APIRouter(prefix="/reconcile-manual", tags=["Manual Reconciliation"])


class MatchRequest(BaseModel):
    bank_txn_id: int
    entity_type: str  # "invoice" | "bill" | "expense"
    entity_id: int


class FeedbackRequest(BaseModel):
    expense_id: int
    corrected_category: str
    feedback_text: Optional[str] = None


@router.post("/match")
async def match_transaction(
    request: MatchRequest,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """Manually match a bank transaction to a document."""
    service = ManualReconciliationService(db, organization_id=org_id)
    try:
        return {"status": "success", "data": service.match_transaction(
            request.bank_txn_id,
            request.entity_type,
            request.entity_id,
        )}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/unmatch")
async def unmatch_transaction(
    bank_txn_id: int,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """Manually unmatch a bank transaction."""
    service = ManualReconciliationService(db, organization_id=org_id)
    try:
        return {"status": "success", "data": service.unmatch_transaction(bank_txn_id)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/unmatched")
async def list_unmatched(
    limit: int = 100,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """List unmatched bank transactions for review."""
    service = ManualReconciliationService(db, organization_id=org_id)
    return {"status": "success", "data": service.list_unmatched_transactions(limit)}


@router.get("/match-suggestions/{bank_txn_id}")
async def suggest_matches(
    bank_txn_id: int,
    limit: int = 5,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """Get suggested matches for a bank transaction."""
    service = ManualReconciliationService(db, organization_id=org_id)
    try:
        return {"status": "success", "data": service.suggest_matches(bank_txn_id, limit)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/feedback")
async def record_feedback(
    request: FeedbackRequest,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """Record classifier feedback for learning."""
    service = ManualReconciliationService(db, organization_id=org_id)
    try:
        return {"status": "success", "data": service.record_classifier_feedback(
            request.expense_id,
            "expense",
            request.corrected_category,
            request.feedback_text,
        )}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
