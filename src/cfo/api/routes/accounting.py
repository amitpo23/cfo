"""
Accounting API routes
Handles customers, documents, invoices, and general accounting operations
"""
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from typing import List, Optional
from datetime import date
from sqlalchemy.orm import Session

from ...database import get_db_session
from ...integrations.sumit_integration import SumitIntegration
from ...integrations.sumit_models import (
    CustomerRequest, CustomerResponse, CustomerRemarkRequest,
    DocumentRequest, DocumentResponse, SendDocumentRequest,
    DocumentListRequest, ExpenseRequest, DebtReportRequest,
    IncomeItemRequest, IncomeItemResponse,
    BankAccountVerification, ExchangeRateRequest, ExchangeRateResponse,
    SettingsUpdate, DocumentNumberRequest,
    BooksBatchRequest,
)
from ...services.irreversible_action_service import (
    ActionAuthorizationError,
    ActionConflictError,
    ActionStateError,
    ActionValidationError,
    IrreversibleActionService,
)
from ..dependencies import (
    get_current_org_id,
    get_current_user,
    get_sumit_integration,
    require_admin,
    sumit_for_org,
)

router = APIRouter()


@router.post("/books/batches")
async def create_books_batch(
    request: BooksBatchRequest,
    approval_id: Optional[int] = Header(
        None,
        alias="X-Rezef-Approval-Id",
    ),
    org_id: int = Depends(get_current_org_id),
    db: Session = Depends(get_db_session),
    _admin=Depends(require_admin),
):
    """Create one approved, open SUMIT books batch exactly once.

    SUMIT's published API has no readback/close operation for this resource.
    The durable action therefore stops at ``executed`` and reports that portal
    verification is still required.
    """
    if approval_id is None:
        raise HTTPException(
            status_code=409,
            detail="An approved X-Rezef-Approval-Id is required",
        )

    submitted_payload = request.model_dump(mode="json", exclude_none=True)
    action_service = IrreversibleActionService(db, org_id)
    try:
        action_service.validate_approved_intent(
            approval_id,
            action_type="sumit_writeback",
            submitted_payload=submitted_payload,
        )
    except (ActionConflictError, ActionStateError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ActionAuthorizationError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ActionValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    sumit = sumit_for_org(db, org_id)
    if sumit is None:
        raise HTTPException(
            status_code=400,
            detail="SUMIT API key not configured for this organization",
        )

    try:
        action = action_service.claim_approved_for_execution(
            approval_id,
            action_type="sumit_writeback",
            submitted_payload=submitted_payload,
        )
    except (ActionConflictError, ActionStateError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ActionAuthorizationError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ActionValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    persisted_request = BooksBatchRequest.model_validate(action.payload)
    try:
        async with sumit:
            result = await sumit.create_books_batch(persisted_request)
    except Exception as exc:
        action_service.mark_failed(
            approval_id,
            error=f"SUMIT books batch failed: {type(exc).__name__}",
        )
        raise HTTPException(
            status_code=502,
            detail="SUMIT did not confirm books batch creation",
        ) from exc

    action_service.mark_executed(
        approval_id,
        provider_reference=result.batch_url,
        execution_result={
            "BatchURL": result.batch_url,
            "batch_closed": False,
            "verification": "SUMIT portal required",
        },
    )
    return {
        "approval_request_id": approval_id,
        "approval_status": "executed_unverified",
        "batch_url": result.batch_url,
        "batch_closed": False,
        "verification_required": (
            "Verify open/closed status in the SUMIT batches portal"
        ),
    }


# ==================== Customers ====================

@router.post("/customers", response_model=CustomerResponse)
async def create_customer(
    customer: CustomerRequest,
    sumit: SumitIntegration = Depends(get_sumit_integration),
    current_user: dict = Depends(get_current_user)
):
    """Create a new customer"""
    async with sumit:
        return await sumit.create_customer(customer)


@router.put("/customers/{customer_id}", response_model=CustomerResponse)
async def update_customer(
    customer_id: str,
    customer: CustomerRequest,
    sumit: SumitIntegration = Depends(get_sumit_integration),
    current_user: dict = Depends(get_current_user)
):
    """Update existing customer"""
    async with sumit:
        return await sumit.update_customer(customer_id, customer)


@router.get("/customers/{customer_id}/url")
async def get_customer_details_url(
    customer_id: str,
    sumit: SumitIntegration = Depends(get_sumit_integration),
    current_user: dict = Depends(get_current_user)
):
    """Get URL to customer details page"""
    async with sumit:
        url = await sumit.get_customer_details_url(customer_id)
        return {"url": url}


@router.post("/customers/remarks")
async def create_customer_remark(
    remark: CustomerRemarkRequest,
    sumit: SumitIntegration = Depends(get_sumit_integration),
    current_user: dict = Depends(get_current_user)
):
    """Add remark to customer"""
    async with sumit:
        return await sumit.create_customer_remark(remark)


@router.get("/customers/{customer_id}/debt")
async def get_customer_debt(
    customer_id: str,
    sumit: SumitIntegration = Depends(get_sumit_integration),
    current_user: dict = Depends(get_current_user)
):
    """Get customer debt information"""
    async with sumit:
        return await sumit.get_debt(customer_id)


# ==================== Documents ====================

@router.post("/documents", response_model=DocumentResponse)
async def create_document(
    document: DocumentRequest,
    sumit: SumitIntegration = Depends(get_sumit_integration),
    current_user: dict = Depends(get_current_user)
):
    """Create a new document (invoice, receipt, quote, etc.)"""
    async with sumit:
        return await sumit.create_document(document)


@router.get("/documents/{document_id}", response_model=DocumentResponse)
async def get_document(
    document_id: str,
    sumit: SumitIntegration = Depends(get_sumit_integration),
    current_user: dict = Depends(get_current_user)
):
    """Get document details"""
    async with sumit:
        return await sumit.get_document_details(document_id)


@router.get("/documents", response_model=List[DocumentResponse])
async def list_documents(
    customer_id: Optional[str] = Query(None),
    document_type: Optional[str] = Query(None),
    from_date: Optional[date] = Query(None),
    to_date: Optional[date] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(100, le=1000),
    offset: int = Query(0, ge=0),
    sumit: SumitIntegration = Depends(get_sumit_integration),
    current_user: dict = Depends(get_current_user)
):
    """List documents with filters"""
    request = DocumentListRequest(
        customer_id=customer_id,
        document_type=document_type,
        from_date=from_date,
        to_date=to_date,
        status=status,
        limit=limit,
        offset=offset
    )
    async with sumit:
        return await sumit.list_documents(request)


@router.post("/documents/send")
async def send_document(
    request: SendDocumentRequest,
    sumit: SumitIntegration = Depends(get_sumit_integration),
    current_user: dict = Depends(get_current_user)
):
    """Send document by email"""
    async with sumit:
        return await sumit.send_document(request)


@router.get("/documents/{document_id}/pdf")
async def get_document_pdf(
    document_id: str,
    sumit: SumitIntegration = Depends(get_sumit_integration),
    current_user: dict = Depends(get_current_user)
):
    """Get document PDF"""
    from fastapi.responses import Response
    
    async with sumit:
        pdf_content = await sumit.get_document_pdf(document_id)
        return Response(
            content=pdf_content,
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename=document_{document_id}.pdf"}
        )


@router.post("/documents/{document_id}/cancel")
async def cancel_document(
    document_id: str,
    sumit: SumitIntegration = Depends(get_sumit_integration),
    current_user: dict = Depends(get_current_user)
):
    """Cancel a document"""
    async with sumit:
        return await sumit.cancel_document(document_id)


@router.post("/documents/{document_id}/move-to-books")
async def move_document_to_books(
    document_id: str,
    sumit: SumitIntegration = Depends(get_sumit_integration),
    current_user: dict = Depends(get_current_user)
):
    """Move document to accounting books"""
    async with sumit:
        return await sumit.move_document_to_books(document_id)


# ==================== Expenses ====================

@router.post("/expenses")
async def add_expense(
    expense: ExpenseRequest,
    sumit: SumitIntegration = Depends(get_sumit_integration),
    current_user: dict = Depends(get_current_user)
):
    """Add expense transaction"""
    async with sumit:
        return await sumit.add_expense(expense)


# ==================== Reports ====================

@router.post("/reports/debt")
async def get_debt_report(
    request: DebtReportRequest,
    sumit: SumitIntegration = Depends(get_sumit_integration),
    current_user: dict = Depends(get_current_user)
):
    """Get debt report"""
    async with sumit:
        return await sumit.get_debt_report(request)


# ==================== Income Items ====================

@router.post("/income-items", response_model=IncomeItemResponse)
async def create_income_item(
    item: IncomeItemRequest,
    sumit: SumitIntegration = Depends(get_sumit_integration),
    current_user: dict = Depends(get_current_user)
):
    """Create income item"""
    async with sumit:
        return await sumit.create_income_item(item)


@router.get("/income-items", response_model=List[IncomeItemResponse])
async def list_income_items(
    sumit: SumitIntegration = Depends(get_sumit_integration),
    current_user: dict = Depends(get_current_user)
):
    """List all income items"""
    async with sumit:
        return await sumit.list_income_items()


# ==================== General ====================

@router.post("/verify-bank-account")
async def verify_bank_account(
    verification: BankAccountVerification,
    sumit: SumitIntegration = Depends(get_sumit_integration),
    current_user: dict = Depends(get_current_user)
):
    """Verify bank account details"""
    async with sumit:
        return await sumit.verify_bank_account(verification)


@router.get("/vat-rate")
async def get_vat_rate(
    date_param: Optional[date] = Query(None, alias="date"),
    sumit: SumitIntegration = Depends(get_sumit_integration),
    current_user: dict = Depends(get_current_user)
):
    """Get VAT rate for a specific date"""
    async with sumit:
        vat_rate = await sumit.get_vat_rate(date_param)
        return {"vat_rate": float(vat_rate)}


@router.post("/exchange-rate", response_model=ExchangeRateResponse)
async def get_exchange_rate(
    request: ExchangeRateRequest,
    sumit: SumitIntegration = Depends(get_sumit_integration),
    current_user: dict = Depends(get_current_user)
):
    """Get exchange rate"""
    async with sumit:
        return await sumit.get_exchange_rate(request)


@router.put("/settings")
async def update_settings(
    settings: SettingsUpdate,
    sumit: SumitIntegration = Depends(get_sumit_integration),
    current_user: dict = Depends(get_current_user)
):
    """Update system settings"""
    async with sumit:
        return await sumit.update_settings(settings)


@router.get("/documents/next-number/{document_type}")
async def get_next_document_number(
    document_type: str,
    sumit: SumitIntegration = Depends(get_sumit_integration),
    current_user: dict = Depends(get_current_user)
):
    """Get next document number for a document type"""
    async with sumit:
        next_number = await sumit.get_next_document_number(document_type)
        return {"document_type": document_type, "next_number": next_number}


@router.post("/documents/next-number")
async def set_next_document_number(
    request: DocumentNumberRequest,
    sumit: SumitIntegration = Depends(get_sumit_integration),
    current_user: dict = Depends(get_current_user)
):
    """Set next document number"""
    async with sumit:
        return await sumit.set_next_document_number(request)


@router.get("/balance")
async def get_balance(
    sumit: SumitIntegration = Depends(get_sumit_integration),
    current_user: dict = Depends(get_current_user),
):
    """Get account balance information"""
    async with sumit:
        return await sumit.get_balance()
