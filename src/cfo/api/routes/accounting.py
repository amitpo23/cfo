"""
Accounting API routes
Handles customers, documents, invoices, and general accounting operations
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import List, Optional
from datetime import date

from ...integrations.sumit_integration import SumitIntegration
from ...integrations.sumit_models import (
    CustomerRequest, CustomerResponse, CustomerRemarkRequest,
    DocumentRequest, DocumentResponse, SendDocumentRequest,
    DocumentListRequest, ExpenseRequest, DebtReportRequest,
    IncomeItemRequest, IncomeItemResponse,
    BankAccountVerification, ExchangeRateRequest, ExchangeRateResponse,
    SettingsUpdate, DocumentNumberRequest
)
from ..dependencies import get_current_user, get_sumit_integration

router = APIRouter()


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
    current_user: dict = Depends(get_current_user)
):
    """Get account balance information"""
    async with sumit:
        return await sumit.get_balance()
