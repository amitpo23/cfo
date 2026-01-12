"""
Pydantic models for SUMIT API requests and responses
"""
from pydantic import BaseModel, Field, EmailStr
from typing import Optional, List, Dict, Any, Literal
from datetime import datetime, date
from decimal import Decimal


# ==================== Base Models ====================

class SumitResponse(BaseModel):
    """Base response model for SUMIT API"""
    success: bool
    error: Optional[str] = None
    data: Optional[Any] = None


# ==================== Customer Models ====================

class CustomerAddress(BaseModel):
    """Customer address information"""
    street: Optional[str] = None
    city: Optional[str] = None
    zip_code: Optional[str] = None
    country: Optional[str] = None


class CustomerRequest(BaseModel):
    """Create/Update customer request"""
    name: str
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    tax_id: Optional[str] = None
    address: Optional[CustomerAddress] = None
    notes: Optional[str] = None
    customer_type: Optional[Literal["individual", "company"]] = "individual"


class CustomerResponse(BaseModel):
    """Customer response"""
    customer_id: str
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    tax_id: Optional[str] = None
    balance: Optional[Decimal] = None
    created_at: Optional[datetime] = None


class CustomerRemarkRequest(BaseModel):
    """Customer remark request"""
    customer_id: str
    remark: str


# ==================== Document Models ====================

class DocumentItem(BaseModel):
    """Document line item"""
    description: str
    quantity: Decimal = Field(default=Decimal("1"))
    price: Decimal
    vat_rate: Optional[Decimal] = None
    discount: Optional[Decimal] = None
    item_id: Optional[str] = None


class DocumentRequest(BaseModel):
    """Create document request"""
    customer_id: str
    document_type: Literal["invoice", "receipt", "quote", "credit_note", "proforma"]
    items: List[DocumentItem]
    issue_date: Optional[date] = None
    due_date: Optional[date] = None
    notes: Optional[str] = None
    currency: Optional[str] = "ILS"
    language: Optional[str] = "he"


class DocumentResponse(BaseModel):
    """Document response"""
    document_id: str
    document_number: str
    document_type: str
    customer_id: str
    total_amount: Decimal
    vat_amount: Decimal
    status: str
    issue_date: date
    due_date: Optional[date] = None
    pdf_url: Optional[str] = None


class SendDocumentRequest(BaseModel):
    """Send document by email"""
    document_id: str
    recipient_email: Optional[EmailStr] = None
    cc_emails: Optional[List[EmailStr]] = None
    subject: Optional[str] = None
    message: Optional[str] = None


class DocumentListRequest(BaseModel):
    """List documents request"""
    customer_id: Optional[str] = None
    document_type: Optional[str] = None
    from_date: Optional[date] = None
    to_date: Optional[date] = None
    status: Optional[str] = None
    limit: Optional[int] = 100
    offset: Optional[int] = 0


class ExpenseRequest(BaseModel):
    """Add expense request"""
    supplier_name: str
    amount: Decimal
    vat_amount: Optional[Decimal] = None
    expense_date: date
    category: Optional[str] = None
    notes: Optional[str] = None
    receipt_file: Optional[str] = None  # Base64 encoded


class DebtReportRequest(BaseModel):
    """Debt report request"""
    customer_id: Optional[str] = None
    as_of_date: Optional[date] = None
    include_paid: bool = False


# ==================== Payment Models ====================

class PaymentMethodCard(BaseModel):
    """Credit card payment method"""
    card_number: str
    expiry_month: str
    expiry_year: str
    cvv: str
    holder_name: str


class ChargeRequest(BaseModel):
    """Charge customer request"""
    customer_id: Optional[str] = None
    amount: Decimal
    currency: str = "ILS"
    description: Optional[str] = None
    payment_method: Optional[str] = None  # Card token or payment method ID
    card: Optional[PaymentMethodCard] = None
    installments: Optional[int] = 1
    document_id: Optional[str] = None


class PaymentResponse(BaseModel):
    """Payment response"""
    payment_id: str
    transaction_id: str
    amount: Decimal
    currency: str
    status: Literal["pending", "completed", "failed", "refunded"]
    created_at: datetime
    authorization_number: Optional[str] = None
    last_4_digits: Optional[str] = None


class PaymentMethodResponse(BaseModel):
    """Payment method details"""
    payment_method_id: str
    type: str
    last_4_digits: Optional[str] = None
    expiry_date: Optional[str] = None
    is_default: bool


# ==================== Transaction Models ====================

class TransactionRequest(BaseModel):
    """Create transaction request"""
    amount: Decimal
    currency: str = "ILS"
    description: str
    success_url: Optional[str] = None
    failure_url: Optional[str] = None
    customer_id: Optional[str] = None


class TransactionResponse(BaseModel):
    """Transaction response"""
    transaction_id: str
    status: str
    amount: Decimal
    currency: str
    created_at: datetime
    redirect_url: Optional[str] = None


# ==================== CRM Models ====================

class EntityField(BaseModel):
    """CRM entity field"""
    field_name: str
    field_value: Any


class EntityRequest(BaseModel):
    """Create/Update CRM entity"""
    folder_id: str
    fields: List[EntityField]
    entity_id: Optional[str] = None


class EntityResponse(BaseModel):
    """CRM entity response"""
    entity_id: str
    folder_id: str
    fields: Dict[str, Any]
    created_at: datetime
    updated_at: datetime


class FolderResponse(BaseModel):
    """CRM folder response"""
    folder_id: str
    folder_name: str
    field_definitions: List[Dict[str, Any]]


# ==================== Income Item Models ====================

class IncomeItemRequest(BaseModel):
    """Create income item request"""
    name: str
    description: Optional[str] = None
    price: Decimal
    currency: str = "ILS"
    vat_rate: Optional[Decimal] = None
    category: Optional[str] = None


class IncomeItemResponse(BaseModel):
    """Income item response"""
    item_id: str
    name: str
    description: Optional[str] = None
    price: Decimal
    currency: str
    vat_rate: Optional[Decimal] = None


# ==================== Recurring Payment Models ====================

class RecurringPaymentRequest(BaseModel):
    """Create/Update recurring payment"""
    customer_id: str
    amount: Decimal
    currency: str = "ILS"
    frequency: Literal["daily", "weekly", "monthly", "yearly"]
    start_date: date
    end_date: Optional[date] = None
    payment_method_id: str
    description: Optional[str] = None


class RecurringPaymentResponse(BaseModel):
    """Recurring payment response"""
    recurring_id: str
    customer_id: str
    amount: Decimal
    currency: str
    frequency: str
    status: str
    next_charge_date: Optional[date] = None


# ==================== Communication Models ====================

class SMSRequest(BaseModel):
    """Send SMS request"""
    phone_number: str
    message: str
    sender_name: Optional[str] = None


class SMSResponse(BaseModel):
    """SMS response"""
    message_id: str
    status: str
    sent_at: datetime


class EmailListRequest(BaseModel):
    """Add to email list request"""
    list_id: str
    email: EmailStr
    name: Optional[str] = None
    custom_fields: Optional[Dict[str, str]] = None


class FaxRequest(BaseModel):
    """Send fax request"""
    fax_number: str
    document_url: Optional[str] = None
    document_content: Optional[str] = None  # Base64 encoded


# ==================== Billing Models ====================

class BillingTransactionRequest(BaseModel):
    """Load billing transactions"""
    from_date: date
    to_date: date
    terminal_id: Optional[str] = None


class BillingTransaction(BaseModel):
    """Billing transaction details"""
    transaction_id: str
    amount: Decimal
    date: date
    card_last_4: str
    status: str
    authorization_number: Optional[str] = None


# ==================== Vault Models ====================

class TokenizeCardRequest(BaseModel):
    """Tokenize card request"""
    card_number: str
    expiry_month: str
    expiry_year: str
    cvv: str
    holder_name: str
    customer_id: Optional[str] = None


class TokenResponse(BaseModel):
    """Card token response"""
    token: str
    last_4_digits: str
    expiry_date: str
    card_brand: str


# ==================== General Models ====================

class BankAccountVerification(BaseModel):
    """Bank account verification request"""
    account_number: str
    branch_number: str
    bank_number: str


class ExchangeRateRequest(BaseModel):
    """Exchange rate request"""
    from_currency: str
    to_currency: str
    date: Optional[date] = None


class ExchangeRateResponse(BaseModel):
    """Exchange rate response"""
    from_currency: str
    to_currency: str
    rate: Decimal
    date: date


class SettingsUpdate(BaseModel):
    """Update settings request"""
    settings: Dict[str, Any]


class DocumentNumberRequest(BaseModel):
    """Document number request"""
    document_type: str
    next_number: Optional[int] = None


# ==================== Ticket Models ====================

class TicketRequest(BaseModel):
    """Create customer service ticket"""
    subject: str
    description: str
    customer_id: Optional[str] = None
    priority: Optional[Literal["low", "medium", "high", "urgent"]] = "medium"
    category: Optional[str] = None


class TicketResponse(BaseModel):
    """Ticket response"""
    ticket_id: str
    subject: str
    status: str
    created_at: datetime


# ==================== Company Models ====================

class CompanyRequest(BaseModel):
    """Create/Update company request"""
    name: str
    tax_id: str
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    address: Optional[CustomerAddress] = None
    industry: Optional[str] = None


class CompanyResponse(BaseModel):
    """Company response"""
    company_id: str
    name: str
    tax_id: str
    created_at: datetime


# ==================== User Models ====================

class UserPermission(BaseModel):
    """User permission"""
    permission_name: str
    granted: bool


class UserRequest(BaseModel):
    """Create user request"""
    email: EmailStr
    name: str
    role: str
    permissions: Optional[List[str]] = None


class UserResponse(BaseModel):
    """User response"""
    user_id: str
    email: str
    name: str
    role: str
    created_at: datetime


# ==================== Stock Models ====================

class StockItemResponse(BaseModel):
    """Stock item response"""
    item_id: str
    name: str
    quantity: Decimal
    unit: str
    last_updated: datetime
