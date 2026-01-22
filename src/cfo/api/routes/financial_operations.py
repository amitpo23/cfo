"""
Financial Operations Routes
נתיבי API לפעולות פיננסיות - חשבוניות, תשלומים, הסכמים
"""
from datetime import date, datetime
from typing import Optional, List
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, Query, Body
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..dependencies import get_db
from ...services.invoice_service import (
    InvoiceService, DocumentType, InvoiceStatus, ExpenseCategory
)
from ...services.payment_request_service import (
    PaymentRequestService, PaymentRequestStatus, PaymentMethod, RecurringFrequency
)
from ...services.agreement_cashflow_service import (
    AgreementCashFlowService, AgreementType, AgreementStatus, BillingCycle, CashFlowType
)

router = APIRouter(prefix="/financial", tags=["Financial Operations"])


# ==================== Pydantic Models ====================

# Invoice Models
class InvoiceItemRequest(BaseModel):
    """פריט בחשבונית"""
    description: str = Field(..., description="תיאור הפריט")
    quantity: float = Field(..., gt=0, description="כמות")
    unit_price: float = Field(..., ge=0, description="מחיר ליחידה")
    vat_rate: float = Field(default=17.0, ge=0, description="שיעור מע\"מ")
    discount: float = Field(default=0, ge=0, description="הנחה")


class CreateInvoiceRequest(BaseModel):
    """יצירת חשבונית"""
    customer_id: str = Field(..., description="מזהה לקוח")
    customer_name: str = Field(..., description="שם לקוח")
    customer_email: Optional[str] = Field(None, description="אימייל")
    customer_address: Optional[str] = Field(None, description="כתובת")
    items: List[InvoiceItemRequest] = Field(..., description="פריטים")
    document_type: str = Field(default="invoice", description="סוג מסמך")
    issue_date: Optional[str] = Field(None, description="תאריך הפקה")
    due_date: Optional[str] = Field(None, description="תאריך לתשלום")
    notes: Optional[str] = Field(None, description="הערות")
    send_to_sumit: bool = Field(default=True, description="שליחה ל-SUMIT")


class ReceivedInvoiceRequest(BaseModel):
    """קליטת חשבונית ספק"""
    vendor_name: str
    vendor_id: Optional[str] = None
    invoice_number: str
    amount: float
    vat_amount: float
    total: float
    issue_date: str
    due_date: str
    description: str
    category: str = "general"
    record_in_sumit: bool = True


# Payment Models
class PaymentRequestModel(BaseModel):
    """בקשת תשלום"""
    customer_id: str
    customer_name: str
    customer_email: str
    customer_phone: Optional[str] = None
    amount: float = Field(..., gt=0)
    description: str
    invoice_id: Optional[str] = None
    allowed_methods: Optional[List[str]] = None
    expires_in_days: int = 30
    installments_allowed: bool = False
    max_installments: int = 12


class ProcessPaymentRequest(BaseModel):
    """עיבוד תשלום"""
    payment_method: str
    card_details: Optional[dict] = None
    installments: int = 1


class StandingOrderRequest(BaseModel):
    """הוראת קבע"""
    customer_id: str
    customer_name: str
    amount: float = Field(..., gt=0)
    frequency: str
    card_details: dict
    description: str
    start_date: Optional[str] = None
    end_date: Optional[str] = None


class PaymentDemandRequest(BaseModel):
    """דרישת תשלום"""
    customer_id: str
    customer_name: str
    amount: float
    due_date: str
    description: str
    related_invoices: Optional[List[str]] = None
    payment_methods: Optional[List[dict]] = None


# Agreement Models
class AgreementRequest(BaseModel):
    """הסכם"""
    customer_id: str
    customer_name: str
    agreement_type: str
    title: str
    total_value: float
    billing_cycle: str
    start_date: str
    end_date: Optional[str] = None
    description: str = ""
    auto_renew: bool = False
    payment_terms_days: int = 30
    milestones: Optional[List[dict]] = None


class CashFlowEntryRequest(BaseModel):
    """רשומת תזרים"""
    amount: float
    date: str
    flow_type: str
    category: str
    description: str
    probability: float = 1.0


class ForecastRequest(BaseModel):
    """בקשת תחזית"""
    historical_months: int = 12
    forecast_months: int = 6
    method: str = "exponential_smoothing"


# ==================== Invoice Endpoints ====================

@router.post("/invoices")
async def create_invoice(
    request: CreateInvoiceRequest,
    db: Session = Depends(get_db)
):
    """יצירת חשבונית"""
    service = InvoiceService(db)
    
    # המרת פריטים
    items = [
        {
            'description': item.description,
            'quantity': item.quantity,
            'unit_price': item.unit_price,
            'vat_rate': item.vat_rate,
            'discount': item.discount
        }
        for item in request.items
    ]
    
    doc_type = DocumentType(request.document_type)
    issue_date = date.fromisoformat(request.issue_date) if request.issue_date else None
    due_date = date.fromisoformat(request.due_date) if request.due_date else None
    
    if request.send_to_sumit:
        invoice = await service.create_and_issue_invoice(
            customer_id=request.customer_id,
            customer_name=request.customer_name,
            customer_email=request.customer_email,
            items=items,
            document_type=doc_type,
            issue_date=issue_date,
            due_date=due_date,
            notes=request.notes,
            send_email=True
        )
    else:
        invoice = await service.create_invoice(
            customer_id=request.customer_id,
            customer_name=request.customer_name,
            customer_email=request.customer_email,
            customer_address=request.customer_address,
            items=items,
            document_type=doc_type,
            issue_date=issue_date,
            due_date=due_date,
            notes=request.notes
        )
    
    return invoice


@router.post("/invoices/{invoice_id}/issue")
async def issue_invoice(
    invoice_id: str,
    send_email: bool = True,
    db: Session = Depends(get_db)
):
    """הפקת חשבונית ב-SUMIT"""
    service = InvoiceService(db)
    return await service.issue_invoice_to_sumit(invoice_id, send_email)


@router.post("/invoices/receive")
async def receive_invoice(
    request: ReceivedInvoiceRequest,
    db: Session = Depends(get_db)
):
    """קליטת חשבונית ספק"""
    service = InvoiceService(db)
    
    invoice = await service.receive_supplier_invoice(
        vendor_name=request.vendor_name,
        vendor_id=request.vendor_id,
        invoice_number=request.invoice_number,
        amount=request.amount,
        vat_amount=request.vat_amount,
        total=request.total,
        issue_date=date.fromisoformat(request.issue_date),
        due_date=date.fromisoformat(request.due_date),
        description=request.description,
        category=ExpenseCategory(request.category)
    )
    
    if request.record_in_sumit:
        await service.record_expense_to_sumit(invoice.received_invoice_id)
    
    return invoice


@router.get("/invoices")
async def list_invoices(
    customer_id: Optional[str] = None,
    status: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """רשימת חשבוניות"""
    service = InvoiceService(db)
    
    status_enum = InvoiceStatus(status) if status else None
    from_dt = date.fromisoformat(from_date) if from_date else None
    to_dt = date.fromisoformat(to_date) if to_date else None
    
    return await service.list_invoices(
        customer_id=customer_id,
        status=status_enum,
        from_date=from_dt,
        to_date=to_dt
    )


@router.get("/invoices/received")
async def list_received_invoices(
    vendor_name: Optional[str] = None,
    category: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """רשימת חשבוניות שהתקבלו"""
    service = InvoiceService(db)
    
    cat_enum = ExpenseCategory(category) if category else None
    from_dt = date.fromisoformat(from_date) if from_date else None
    to_dt = date.fromisoformat(to_date) if to_date else None
    
    return await service.list_received_invoices(
        vendor_name=vendor_name,
        category=cat_enum,
        from_date=from_dt,
        to_date=to_dt
    )


@router.post("/invoices/{invoice_id}/cancel")
async def cancel_invoice(
    invoice_id: str,
    reason: str = "",
    db: Session = Depends(get_db)
):
    """ביטול חשבונית"""
    service = InvoiceService(db)
    return await service.cancel_invoice(invoice_id, reason)


@router.post("/invoices/{invoice_id}/credit-note")
async def create_credit_note(
    invoice_id: str,
    reason: str = "",
    db: Session = Depends(get_db)
):
    """יצירת חשבונית זיכוי"""
    service = InvoiceService(db)
    return await service.create_credit_note(invoice_id, reason)


@router.post("/invoices/sync")
async def sync_invoices(
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """סנכרון חשבוניות מ-SUMIT"""
    service = InvoiceService(db)
    
    from_dt = date.fromisoformat(from_date) if from_date else None
    to_dt = date.fromisoformat(to_date) if to_date else None
    
    return await service.sync_invoices_from_sumit(from_dt, to_dt)


@router.get("/invoices/summary")
async def get_invoice_summary(
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """סיכום חשבוניות"""
    service = InvoiceService(db)
    
    from_dt = date.fromisoformat(from_date) if from_date else None
    to_dt = date.fromisoformat(to_date) if to_date else None
    
    return await service.get_invoice_summary(from_dt, to_dt)


@router.post("/invoices/reminders")
async def send_reminders(
    days_overdue: int = 7,
    db: Session = Depends(get_db)
):
    """שליחת תזכורות לחשבוניות באיחור"""
    service = InvoiceService(db)
    return await service.send_payment_reminders(days_overdue)


# ==================== Payment Request Endpoints ====================

@router.post("/payments/requests")
async def create_payment_request(
    request: PaymentRequestModel,
    db: Session = Depends(get_db)
):
    """יצירת בקשת תשלום"""
    service = PaymentRequestService(db)
    
    allowed = None
    if request.allowed_methods:
        allowed = [PaymentMethod(m) for m in request.allowed_methods]
    
    return await service.create_payment_request(
        customer_id=request.customer_id,
        customer_name=request.customer_name,
        customer_email=request.customer_email,
        amount=request.amount,
        description=request.description,
        customer_phone=request.customer_phone,
        invoice_id=request.invoice_id,
        allowed_methods=allowed,
        expires_in_days=request.expires_in_days,
        installments_allowed=request.installments_allowed,
        max_installments=request.max_installments
    )


@router.post("/payments/requests/{request_id}/send")
async def send_payment_request(
    request_id: str,
    send_email: bool = True,
    send_sms: bool = False,
    db: Session = Depends(get_db)
):
    """שליחת בקשת תשלום"""
    service = PaymentRequestService(db)
    return await service.send_payment_request(request_id, send_email, send_sms)


@router.post("/payments/requests/{request_id}/process")
async def process_payment(
    request_id: str,
    request: ProcessPaymentRequest,
    db: Session = Depends(get_db)
):
    """עיבוד תשלום"""
    service = PaymentRequestService(db)
    return await service.process_payment(
        request_id,
        PaymentMethod(request.payment_method),
        request.card_details,
        request.installments
    )


@router.get("/payments/requests")
async def list_payment_requests(
    customer_id: Optional[str] = None,
    status: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """רשימת בקשות תשלום"""
    service = PaymentRequestService(db)
    status_enum = PaymentRequestStatus(status) if status else None
    return await service.list_payment_requests(customer_id, status_enum)


# ==================== Standing Order Endpoints ====================

@router.post("/payments/standing-orders")
async def create_standing_order(
    request: StandingOrderRequest,
    db: Session = Depends(get_db)
):
    """יצירת הוראת קבע"""
    service = PaymentRequestService(db)
    
    start = date.fromisoformat(request.start_date) if request.start_date else None
    end = date.fromisoformat(request.end_date) if request.end_date else None
    
    return await service.create_standing_order(
        customer_id=request.customer_id,
        customer_name=request.customer_name,
        amount=request.amount,
        frequency=RecurringFrequency(request.frequency),
        card_details=request.card_details,
        description=request.description,
        start_date=start,
        end_date=end
    )


@router.post("/payments/standing-orders/{order_id}/charge")
async def charge_standing_order(
    order_id: str,
    db: Session = Depends(get_db)
):
    """חיוב הוראת קבע"""
    service = PaymentRequestService(db)
    return await service.charge_standing_order(order_id)


@router.delete("/payments/standing-orders/{order_id}")
async def cancel_standing_order(
    order_id: str,
    reason: str = "",
    db: Session = Depends(get_db)
):
    """ביטול הוראת קבע"""
    service = PaymentRequestService(db)
    return await service.cancel_standing_order(order_id, reason)


@router.get("/payments/standing-orders")
async def list_standing_orders(
    customer_id: Optional[str] = None,
    status: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """רשימת הוראות קבע"""
    service = PaymentRequestService(db)
    return await service.list_standing_orders(customer_id, status)


@router.post("/payments/standing-orders/run-scheduled")
async def run_scheduled_charges(
    db: Session = Depends(get_db)
):
    """הרצת חיובים מתוזמנים"""
    service = PaymentRequestService(db)
    return await service.run_scheduled_charges()


# ==================== Payment Demand Endpoints ====================

@router.post("/payments/demands")
async def create_payment_demand(
    request: PaymentDemandRequest,
    db: Session = Depends(get_db)
):
    """יצירת דרישת תשלום"""
    service = PaymentRequestService(db)
    return await service.create_payment_demand(
        customer_id=request.customer_id,
        customer_name=request.customer_name,
        amount=request.amount,
        due_date=date.fromisoformat(request.due_date),
        description=request.description,
        related_invoices=request.related_invoices,
        payment_methods=request.payment_methods
    )


@router.post("/payments/demands/{demand_id}/send")
async def send_payment_demand(
    demand_id: str,
    send_email: bool = True,
    send_sms: bool = False,
    db: Session = Depends(get_db)
):
    """שליחת דרישת תשלום"""
    service = PaymentRequestService(db)
    return await service.send_payment_demand(demand_id, send_email, send_sms)


@router.post("/payments/demands/{demand_id}/mark-paid")
async def mark_demand_paid(
    demand_id: str,
    payment_method: str,
    payment_reference: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """סימון דרישה כשולמה"""
    service = PaymentRequestService(db)
    return await service.mark_demand_paid(
        demand_id,
        PaymentMethod(payment_method),
        payment_reference
    )


@router.get("/payments/demands")
async def list_payment_demands(
    customer_id: Optional[str] = None,
    status: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """רשימת דרישות תשלום"""
    service = PaymentRequestService(db)
    return await service.list_payment_demands(customer_id, status)


# ==================== Agreement Endpoints ====================

@router.post("/agreements")
async def create_agreement(
    request: AgreementRequest,
    db: Session = Depends(get_db)
):
    """יצירת הסכם"""
    service = AgreementCashFlowService(db)
    
    return await service.create_agreement(
        customer_id=request.customer_id,
        customer_name=request.customer_name,
        agreement_type=AgreementType(request.agreement_type),
        title=request.title,
        total_value=request.total_value,
        billing_cycle=BillingCycle(request.billing_cycle),
        start_date=date.fromisoformat(request.start_date),
        end_date=date.fromisoformat(request.end_date) if request.end_date else None,
        description=request.description,
        auto_renew=request.auto_renew,
        payment_terms_days=request.payment_terms_days,
        milestones=request.milestones
    )


@router.put("/agreements/{agreement_id}")
async def update_agreement(
    agreement_id: str,
    updates: dict = Body(...),
    db: Session = Depends(get_db)
):
    """עדכון הסכם"""
    service = AgreementCashFlowService(db)
    return await service.update_agreement(agreement_id, **updates)


@router.delete("/agreements/{agreement_id}")
async def cancel_agreement(
    agreement_id: str,
    reason: str = "",
    db: Session = Depends(get_db)
):
    """ביטול הסכם"""
    service = AgreementCashFlowService(db)
    return await service.cancel_agreement(agreement_id, reason)


@router.get("/agreements")
async def list_agreements(
    customer_id: Optional[str] = None,
    agreement_type: Optional[str] = None,
    status: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """רשימת הסכמים"""
    service = AgreementCashFlowService(db)
    
    type_enum = AgreementType(agreement_type) if agreement_type else None
    status_enum = AgreementStatus(status) if status else None
    
    return await service.list_agreements(customer_id, type_enum, status_enum)


@router.get("/agreements/revenue-summary")
async def get_agreement_revenue_summary(
    db: Session = Depends(get_db)
):
    """סיכום הכנסות מהסכמים"""
    service = AgreementCashFlowService(db)
    return await service.get_agreement_revenue_summary()


# ==================== Cash Flow Endpoints ====================

@router.post("/cashflow/sync-invoices")
async def sync_outstanding_invoices(
    db: Session = Depends(get_db)
):
    """סנכרון חשבוניות פתוחות"""
    service = AgreementCashFlowService(db)
    return await service.sync_outstanding_invoices()


@router.post("/cashflow/expenses")
async def add_expected_expense(
    request: CashFlowEntryRequest,
    db: Session = Depends(get_db)
):
    """הוספת הוצאה צפויה"""
    service = AgreementCashFlowService(db)
    return await service.add_expected_expense(
        amount=request.amount,
        date=date.fromisoformat(request.date),
        category=request.category,
        description=request.description,
        probability=request.probability
    )


@router.post("/cashflow/transactions")
async def record_transaction(
    request: CashFlowEntryRequest,
    db: Session = Depends(get_db)
):
    """רישום עסקה בפועל"""
    service = AgreementCashFlowService(db)
    return await service.record_actual_transaction(
        amount=request.amount,
        date=date.fromisoformat(request.date),
        flow_type=CashFlowType(request.flow_type),
        category=request.category,
        description=request.description
    )


@router.get("/cashflow/projection")
async def get_cash_flow_projection(
    start_date: Optional[str] = None,
    periods: int = 12,
    opening_balance: float = 0.0,
    db: Session = Depends(get_db)
):
    """תחזית תזרים מזומנים"""
    service = AgreementCashFlowService(db)
    
    start = date.fromisoformat(start_date) if start_date else date.today()
    
    return await service.get_cash_flow_projection(start, periods, opening_balance)


@router.get("/cashflow/summary")
async def get_cash_flow_summary(
    start_date: Optional[str] = None,
    periods: int = 12,
    opening_balance: float = 0.0,
    db: Session = Depends(get_db)
):
    """סיכום תזרים מזומנים"""
    service = AgreementCashFlowService(db)
    
    start = date.fromisoformat(start_date) if start_date else date.today()
    
    return await service.get_cash_flow_summary(start, periods, opening_balance)


@router.post("/cashflow/forecast")
async def forecast_cash_flow(
    request: ForecastRequest,
    db: Session = Depends(get_db)
):
    """חיזוי תזרים מזומנים"""
    service = AgreementCashFlowService(db)
    return await service.forecast_cash_flow(
        historical_months=request.historical_months,
        forecast_months=request.forecast_months,
        method=request.method
    )


@router.get("/cashflow/payment-patterns")
async def analyze_payment_patterns(
    customer_id: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """ניתוח דפוסי תשלום"""
    service = AgreementCashFlowService(db)
    return await service.analyze_payment_patterns(customer_id)
