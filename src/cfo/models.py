"""
Data models for the CFO system
"""
from datetime import datetime, date
from decimal import Decimal
from typing import Optional, List
from enum import Enum
from pydantic import BaseModel, Field, EmailStr
from sqlalchemy import (
    Column, Integer, String, Numeric, DateTime, Date,
    ForeignKey, Enum as SQLEnum, Boolean, Text, JSON,
    Index, Float, UniqueConstraint
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()


class UserRole(str, Enum):
    """תפקידי משתמש"""
    SUPER_ADMIN = "super_admin"  # מנהל על
    ADMIN = "admin"  # מנהל ארגון
    ACCOUNTANT = "accountant"  # רואה חשבון
    MANAGER = "manager"  # מנהל
    USER = "user"  # משתמש רגיל
    VIEWER = "viewer"  # צופה בלבד


class IntegrationType(str, Enum):
    """סוגי אינטגרציות"""
    SUMIT = "sumit"
    QUICKBOOKS = "quickbooks"
    XERO = "xero"
    MANUAL = "manual"  # ללא אינטגרציה חיצונית


class TransactionType(str, Enum):
    """סוגי עסקאות"""
    INCOME = "income"  # הכנסה
    EXPENSE = "expense"  # הוצאה
    TRANSFER = "transfer"  # העברה


class AccountType(str, Enum):
    """סוגי חשבונות"""
    ASSET = "asset"
    LIABILITY = "liability"
    EQUITY = "equity"
    REVENUE = "revenue"
    EXPENSE = "expense"
    BANK = "bank"
    ACCOUNTS_RECEIVABLE = "accounts_receivable"
    ACCOUNTS_PAYABLE = "accounts_payable"


class ContactType(str, Enum):
    CUSTOMER = "customer"
    VENDOR = "vendor"
    BOTH = "both"


class InvoiceStatus(str, Enum):
    DRAFT = "draft"
    SENT = "sent"
    PAID = "paid"
    PARTIALLY_PAID = "partially_paid"
    OVERDUE = "overdue"
    VOID = "void"
    CANCELLED = "cancelled"


class BillStatus(str, Enum):
    DRAFT = "draft"
    RECEIVED = "received"
    APPROVED = "approved"
    PAID = "paid"
    PARTIALLY_PAID = "partially_paid"
    OVERDUE = "overdue"
    VOID = "void"


class SyncStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    PARTIAL = "partial"


class AlertSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class AlertStatus(str, Enum):
    ACTIVE = "active"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


class TaskStatus(str, Enum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    DONE = "done"


# ============= Multi-Tenant Models =============

class Organization(Base):
    """ארגון/לקוח במערכת"""
    __tablename__ = "organizations"
    
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)  # שם הארגון
    business_type = Column(String, nullable=True)  # סוג העסק (מסעדה, חברת שירותים וכו')
    tax_id = Column(String, nullable=True)  # מספר עוסק מורשה
    phone = Column(String, nullable=True)
    email = Column(String, nullable=True)
    address = Column(Text, nullable=True)
    
    # Integration settings
    integration_type = Column(SQLEnum(IntegrationType), default=IntegrationType.MANUAL)
    api_credentials = Column(JSON, nullable=True)  # {api_key, company_id, etc}
    
    # Settings & Configuration
    settings = Column(JSON, default={})  # הגדרות כלליות
    is_active = Column(Boolean, default=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    users = relationship("User", back_populates="organization")
    accounts = relationship("Account", back_populates="organization")
    transactions = relationship("Transaction", back_populates="organization")


class User(Base):
    """משתמש במערכת"""
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=True)  # NULL = super admin
    
    email = Column(String, unique=True, nullable=False)
    password_hash = Column(String, nullable=False)
    full_name = Column(String, nullable=False)
    phone = Column(String, nullable=True)
    
    role = Column(SQLEnum(UserRole), default=UserRole.USER)
    is_active = Column(Boolean, default=True)
    last_login = Column(DateTime, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    organization = relationship("Organization", back_populates="users")


class AuditLog(Base):
    """לוג פעילות למעקב"""
    __tablename__ = "audit_logs"
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=True)
    
    action = Column(String, nullable=False)  # CREATE, UPDATE, DELETE, LOGIN, etc
    entity_type = Column(String, nullable=True)  # Account, Transaction, User, etc
    entity_id = Column(Integer, nullable=True)
    details = Column(JSON, nullable=True)
    
    ip_address = Column(String, nullable=True)
    user_agent = Column(String, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)


# Database Models
class Account(Base):
    """חשבון"""
    __tablename__ = "accounts"
    
    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False)
    
    name = Column(String, nullable=False)
    account_type = Column(SQLEnum(AccountType), nullable=False)
    balance = Column(Numeric(precision=10, scale=2), default=0)
    currency = Column(String, default="ILS")
    external_id = Column(String, nullable=True)  # ID ממערכת חיצונית
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    organization = relationship("Organization", back_populates="accounts")
    transactions = relationship("Transaction", back_populates="account")


class Transaction(Base):
    """עסקה פינסית"""
    __tablename__ = "transactions"
    
    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False)
    
    transaction_type = Column(SQLEnum(TransactionType), nullable=False)
    amount = Column(Numeric(precision=10, scale=2), nullable=False)
    description = Column(String, nullable=True)
    category = Column(String, nullable=True)
    transaction_date = Column(DateTime, nullable=False)
    external_id = Column(String, nullable=True)  # ID ממערכת חיצונית
    created_at = Column(DateTime, default=datetime.utcnow)
    
    organization = relationship("Organization", back_populates="transactions")
    account = relationship("Account", back_populates="transactions")


# ============= CFO Extended Models =============

class IntegrationConnection(Base):
    """Stores connection config for external accounting systems"""
    __tablename__ = "integration_connections"

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False)
    source = Column(String(50), nullable=False)  # sumit, quickbooks, xero
    status = Column(String(20), default="active")  # active, inactive, error
    credentials_encrypted = Column(Text, nullable=True)  # encrypted JSON blob
    refresh_token = Column(Text, nullable=True)
    token_expires_at = Column(DateTime, nullable=True)
    last_synced_at = Column(DateTime, nullable=True)
    config = Column(JSON, default={})  # sync interval, feature flags, etc.
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    organization = relationship("Organization")

    __table_args__ = (
        Index("ix_integration_org_source", "organization_id", "source", unique=True),
    )


class SyncRun(Base):
    """Tracks each sync execution for auditability and resumption"""
    __tablename__ = "sync_runs"

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False)
    connection_id = Column(Integer, ForeignKey("integration_connections.id"), nullable=True)
    source = Column(String(50), nullable=False)
    sync_type = Column(String(50), default="full")  # full, incremental, entity-specific
    entity_types = Column(String(255), nullable=True)  # comma-separated: invoices,bills,...
    status = Column(SQLEnum(SyncStatus), default=SyncStatus.PENDING)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    cursor = Column(Text, nullable=True)  # JSON cursor for resumption
    counts = Column(JSON, default={})  # {invoices: {created:5, updated:2, skipped:1}, ...}
    error_summary = Column(Text, nullable=True)
    error_details = Column(JSON, nullable=True)  # [{entity_type, external_id, error}, ...]
    created_at = Column(DateTime, default=datetime.utcnow)

    organization = relationship("Organization")

    __table_args__ = (
        Index("ix_syncrun_org_status", "organization_id", "status"),
    )


class Contact(Base):
    """Normalized customer/vendor record"""
    __tablename__ = "contacts"

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False)
    external_id = Column(String(255), nullable=True)
    source = Column(String(50), default="manual")
    contact_type = Column(SQLEnum(ContactType), nullable=False)
    name = Column(String(255), nullable=False)
    email = Column(String(255), nullable=True)
    phone = Column(String(50), nullable=True)
    tax_id = Column(String(50), nullable=True)
    address = Column(Text, nullable=True)
    currency = Column(String(10), default="ILS")
    raw_data = Column(JSON, nullable=True)  # original payload from source
    payload_hash = Column(String(64), nullable=True)  # SHA-256 of raw_data for change detection
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    organization = relationship("Organization")
    invoices = relationship("Invoice", back_populates="contact", foreign_keys="Invoice.contact_id")
    bills = relationship("Bill", back_populates="vendor", foreign_keys="Bill.vendor_id")

    __table_args__ = (
        Index("ix_contact_org_ext", "organization_id", "external_id", "source", unique=True),
    )


class Invoice(Base):
    """Accounts Receivable invoice (money owed TO us)"""
    __tablename__ = "invoices"

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False)
    external_id = Column(String(255), nullable=True)
    source = Column(String(50), default="manual")
    contact_id = Column(Integer, ForeignKey("contacts.id"), nullable=True)
    invoice_number = Column(String(100), nullable=True)
    issue_date = Column(Date, nullable=True)
    due_date = Column(Date, nullable=True)
    status = Column(SQLEnum(InvoiceStatus), default=InvoiceStatus.DRAFT)
    currency = Column(String(10), default="ILS")
    subtotal = Column(Numeric(precision=12, scale=2), default=0)
    tax = Column(Numeric(precision=12, scale=2), default=0)
    total = Column(Numeric(precision=12, scale=2), default=0)
    paid_amount = Column(Numeric(precision=12, scale=2), default=0)
    balance = Column(Numeric(precision=12, scale=2), default=0)  # total - paid
    line_items = Column(JSON, nullable=True)  # [{description, qty, unit_price, total}, ...]
    notes = Column(Text, nullable=True)
    raw_data = Column(JSON, nullable=True)
    payload_hash = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    organization = relationship("Organization")
    contact = relationship("Contact", back_populates="invoices", foreign_keys=[contact_id])
    payments = relationship("Payment", back_populates="invoice", foreign_keys="Payment.invoice_id")

    __table_args__ = (
        Index("ix_invoice_org_ext", "organization_id", "external_id", "source", unique=True),
        Index("ix_invoice_status", "organization_id", "status"),
        Index("ix_invoice_due", "organization_id", "due_date"),
    )


class Bill(Base):
    """Accounts Payable bill (money WE owe)"""
    __tablename__ = "bills"

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False)
    external_id = Column(String(255), nullable=True)
    source = Column(String(50), default="manual")
    vendor_id = Column(Integer, ForeignKey("contacts.id"), nullable=True)
    bill_number = Column(String(100), nullable=True)
    issue_date = Column(Date, nullable=True)
    due_date = Column(Date, nullable=True)
    status = Column(SQLEnum(BillStatus), default=BillStatus.DRAFT)
    currency = Column(String(10), default="ILS")
    subtotal = Column(Numeric(precision=12, scale=2), default=0)
    tax = Column(Numeric(precision=12, scale=2), default=0)
    total = Column(Numeric(precision=12, scale=2), default=0)
    paid_amount = Column(Numeric(precision=12, scale=2), default=0)
    balance = Column(Numeric(precision=12, scale=2), default=0)
    line_items = Column(JSON, nullable=True)
    notes = Column(Text, nullable=True)
    is_critical = Column(Boolean, default=False)
    can_delay = Column(Boolean, default=False)
    raw_data = Column(JSON, nullable=True)
    payload_hash = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    organization = relationship("Organization")
    vendor = relationship("Contact", back_populates="bills", foreign_keys=[vendor_id])
    payments = relationship("Payment", back_populates="bill", foreign_keys="Payment.bill_id")

    __table_args__ = (
        Index("ix_bill_org_ext", "organization_id", "external_id", "source", unique=True),
        Index("ix_bill_status", "organization_id", "status"),
        Index("ix_bill_due", "organization_id", "due_date"),
    )


class Payment(Base):
    """Payment record linked to invoice or bill"""
    __tablename__ = "payments"

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False)
    external_id = Column(String(255), nullable=True)
    source = Column(String(50), default="manual")
    invoice_id = Column(Integer, ForeignKey("invoices.id"), nullable=True)
    bill_id = Column(Integer, ForeignKey("bills.id"), nullable=True)
    contact_id = Column(Integer, ForeignKey("contacts.id"), nullable=True)
    payment_date = Column(Date, nullable=False)
    amount = Column(Numeric(precision=12, scale=2), nullable=False)
    currency = Column(String(10), default="ILS")
    method = Column(String(50), nullable=True)  # credit_card, bank_transfer, cash, check
    reference = Column(String(255), nullable=True)
    raw_data = Column(JSON, nullable=True)
    payload_hash = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    organization = relationship("Organization")
    invoice = relationship("Invoice", back_populates="payments", foreign_keys=[invoice_id])
    bill = relationship("Bill", back_populates="payments", foreign_keys=[bill_id])

    __table_args__ = (
        Index("ix_payment_org_ext", "organization_id", "external_id", "source", unique=True),
    )


class BankTransaction(Base):
    """Bank/credit card transaction for reconciliation"""
    __tablename__ = "bank_transactions"

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False)
    external_id = Column(String(255), nullable=True)
    source = Column(String(50), default="manual")
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=True)
    transaction_date = Column(Date, nullable=False)
    description = Column(String(500), nullable=True)
    amount = Column(Numeric(precision=12, scale=2), nullable=False)  # positive=inflow, negative=outflow
    currency = Column(String(10), default="ILS")
    category_id = Column(Integer, ForeignKey("categories.id"), nullable=True)
    matched_entity_type = Column(String(50), nullable=True)  # invoice, bill, payment
    matched_entity_id = Column(Integer, nullable=True)
    is_reconciled = Column(Boolean, default=False)
    raw_data = Column(JSON, nullable=True)
    payload_hash = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    organization = relationship("Organization")
    account = relationship("Account")
    category = relationship("Category")

    __table_args__ = (
        Index("ix_banktx_org_ext", "organization_id", "external_id", "source", unique=True),
        Index("ix_banktx_date", "organization_id", "transaction_date"),
    )


class JournalEntry(Base):
    """Journal entry from accounting system"""
    __tablename__ = "journal_entries"

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False)
    external_id = Column(String(255), nullable=True)
    source = Column(String(50), default="manual")
    entry_date = Column(Date, nullable=False)
    memo = Column(Text, nullable=True)
    lines = Column(JSON, nullable=True)  # [{account_id, debit, credit, description}, ...]
    raw_data = Column(JSON, nullable=True)
    payload_hash = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    organization = relationship("Organization")

    __table_args__ = (
        Index("ix_je_org_ext", "organization_id", "external_id", "source", unique=True),
    )


class Category(Base):
    """Expense/revenue category for budgeting and reporting"""
    __tablename__ = "categories"

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False)
    name = Column(String(255), nullable=False)
    parent_id = Column(Integer, ForeignKey("categories.id"), nullable=True)
    category_type = Column(String(20), default="expense")  # expense, revenue, cogs
    external_id = Column(String(255), nullable=True)
    mapping_rules = Column(JSON, nullable=True)  # rules for auto-categorization
    created_at = Column(DateTime, default=datetime.utcnow)

    organization = relationship("Organization")
    parent = relationship("Category", remote_side="Category.id")

    __table_args__ = (
        Index("ix_category_org", "organization_id"),
    )


class Budget(Base):
    """Monthly budget by category"""
    __tablename__ = "budgets"

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False)
    category_id = Column(Integer, ForeignKey("categories.id"), nullable=True)
    category_name = Column(String(255), nullable=True)  # fallback if no category link
    year = Column(Integer, nullable=False)
    month = Column(Integer, nullable=False)  # 1-12
    budgeted_amount = Column(Numeric(precision=12, scale=2), nullable=False, default=0)
    actual_amount = Column(Numeric(precision=12, scale=2), default=0)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    organization = relationship("Organization")
    category = relationship("Category")

    __table_args__ = (
        Index("ix_budget_org_period", "organization_id", "year", "month"),
        UniqueConstraint("organization_id", "category_id", "year", "month", name="uq_budget_cat_period"),
    )


class Alert(Base):
    """System alerts generated by rules engine"""
    __tablename__ = "alerts"

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False)
    alert_type = Column(String(100), nullable=False)  # low_cash, large_tx, overdue_invoice, etc.
    severity = Column(SQLEnum(AlertSeverity), default=AlertSeverity.WARNING)
    entity_type = Column(String(50), nullable=True)  # invoice, bill, transaction
    entity_id = Column(Integer, nullable=True)
    title = Column(String(500), nullable=False)
    message = Column(Text, nullable=True)
    status = Column(SQLEnum(AlertStatus), default=AlertStatus.ACTIVE)
    metadata = Column(JSON, nullable=True)  # extra context
    created_at = Column(DateTime, default=datetime.utcnow)
    acknowledged_at = Column(DateTime, nullable=True)
    resolved_at = Column(DateTime, nullable=True)

    organization = relationship("Organization")

    __table_args__ = (
        Index("ix_alert_org_status", "organization_id", "status"),
    )


class Task(Base):
    """User/system tasks linked to financial entities"""
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False)
    title = Column(String(500), nullable=False)
    description = Column(Text, nullable=True)
    status = Column(SQLEnum(TaskStatus), default=TaskStatus.OPEN)
    due_date = Column(Date, nullable=True)
    entity_type = Column(String(50), nullable=True)  # invoice, bill, transaction
    entity_id = Column(Integer, nullable=True)
    alert_id = Column(Integer, ForeignKey("alerts.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    organization = relationship("Organization")
    alert = relationship("Alert")

    __table_args__ = (
        Index("ix_task_org_status", "organization_id", "status"),
    )


class Note(Base):
    """Internal notes attached to any entity"""
    __tablename__ = "notes"

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False)
    entity_type = Column(String(50), nullable=False)  # invoice, bill, contact, etc.
    entity_id = Column(Integer, nullable=False)
    text = Column(Text, nullable=False)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    organization = relationship("Organization")

    __table_args__ = (
        Index("ix_note_entity", "organization_id", "entity_type", "entity_id"),
    )


class CashflowAssumption(Base):
    """Configurable assumptions for cash flow projections"""
    __tablename__ = "cashflow_assumptions"

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False)
    name = Column(String(100), nullable=False)  # e.g. "conservative", "base", "aggressive"
    ar_collection_probability = Column(Float, default=0.85)  # % of AR expected to collect
    ar_average_delay_days = Column(Integer, default=15)  # avg days past due date
    ap_early_payment_discount = Column(Float, default=0.0)
    is_default = Column(Boolean, default=False)
    config = Column(JSON, default={})
    created_at = Column(DateTime, default=datetime.utcnow)

    organization = relationship("Organization")


class AlertRule(Base):
    """Configurable alert rules"""
    __tablename__ = "alert_rules"

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False)
    rule_type = Column(String(100), nullable=False)
    # low_cash_threshold, large_transaction, spend_spike, overdue_invoice, bills_due_soon
    is_active = Column(Boolean, default=True)
    config = Column(JSON, nullable=False)
    # e.g. {"threshold": 10000} for low_cash, {"days": 7} for bills_due_soon
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    organization = relationship("Organization")


# Pydantic Models for API

# ============= Organization Models =============

class OrganizationCreate(BaseModel):
    """יצירת ארגון חדש"""
    name: str
    business_type: Optional[str] = None
    tax_id: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[EmailStr] = None
    address: Optional[str] = None
    integration_type: IntegrationType = IntegrationType.MANUAL
    api_credentials: Optional[dict] = None


class OrganizationUpdate(BaseModel):
    """עדכון ארגון"""
    name: Optional[str] = None
    business_type: Optional[str] = None
    tax_id: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[EmailStr] = None
    address: Optional[str] = None
    integration_type: Optional[IntegrationType] = None
    api_credentials: Optional[dict] = None
    settings: Optional[dict] = None
    is_active: Optional[bool] = None


class OrganizationResponse(BaseModel):
    """תגובה עם פרטי ארגון"""
    id: int
    name: str
    business_type: Optional[str] = None
    tax_id: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    integration_type: IntegrationType
    is_active: bool
    created_at: datetime
    
    model_config = {"from_attributes": True}


# ============= User Models =============

class UserCreate(BaseModel):
    """יצירת משתמש חדש"""
    email: EmailStr
    password: str
    full_name: str
    phone: Optional[str] = None
    role: UserRole = UserRole.USER
    organization_id: Optional[int] = None


class UserUpdate(BaseModel):
    """עדכון משתמש"""
    email: Optional[EmailStr] = None
    full_name: Optional[str] = None
    phone: Optional[str] = None
    role: Optional[UserRole] = None
    is_active: Optional[bool] = None


class UserResponse(BaseModel):
    """תגובה עם פרטי משתמש"""
    id: int
    email: str
    full_name: str
    phone: Optional[str] = None
    role: UserRole
    organization_id: Optional[int] = None
    is_active: bool
    last_login: Optional[datetime] = None
    created_at: datetime
    
    model_config = {"from_attributes": True}


class UserLogin(BaseModel):
    """התחברות למערכת"""
    email: EmailStr
    password: str


class Token(BaseModel):
    """טוקן גישה"""
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


# ============= Account Models =============

class AccountCreate(BaseModel):
    """יצירת חשבון חדש"""
    name: str
    account_type: AccountType
    balance: Decimal = Field(default=Decimal("0"), ge=0)
    currency: str = "ILS"


class AccountResponse(BaseModel):
    """תגובה עם פרטי חשבון"""
    id: int
    organization_id: int
    name: str
    account_type: AccountType
    balance: Decimal
    currency: str
    created_at: datetime
    
    model_config = {"from_attributes": True}


# ============= Transaction Models =============

class TransactionCreate(BaseModel):
    """יצירת עסקה חדשה"""
    account_id: int
    transaction_type: TransactionType
    amount: Decimal = Field(gt=0)
    description: Optional[str] = None
    category: Optional[str] = None
    transaction_date: datetime


class TransactionResponse(BaseModel):
    """תגובה עם פרטי עסקה"""
    id: int
    organization_id: int
    account_id: int
    transaction_type: TransactionType
    amount: Decimal
    description: Optional[str]
    category: Optional[str]
    transaction_date: datetime
    created_at: datetime
    
    model_config = {"from_attributes": True}


class FinancialSummary(BaseModel):
    """סיכום פיננסי"""
    total_assets: Decimal
    total_liabilities: Decimal
    net_worth: Decimal
    total_income: Decimal
    total_expenses: Decimal
    net_income: Decimal
    period_start: datetime
    period_end: datetime


# ============= CFO Pydantic Schemas =============

class SyncRunResponse(BaseModel):
    id: int
    source: str
    sync_type: str
    status: SyncStatus
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    counts: Optional[dict] = None
    error_summary: Optional[str] = None
    created_at: datetime
    model_config = {"from_attributes": True}


class ContactResponse(BaseModel):
    id: int
    external_id: Optional[str] = None
    contact_type: ContactType
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    currency: str
    is_active: bool
    created_at: datetime
    model_config = {"from_attributes": True}


class InvoiceResponse(BaseModel):
    id: int
    external_id: Optional[str] = None
    invoice_number: Optional[str] = None
    contact_id: Optional[int] = None
    issue_date: Optional[date] = None
    due_date: Optional[date] = None
    status: InvoiceStatus
    currency: str
    subtotal: Decimal
    tax: Decimal
    total: Decimal
    paid_amount: Decimal
    balance: Decimal
    notes: Optional[str] = None
    created_at: datetime
    model_config = {"from_attributes": True}


class BillResponse(BaseModel):
    id: int
    external_id: Optional[str] = None
    bill_number: Optional[str] = None
    vendor_id: Optional[int] = None
    issue_date: Optional[date] = None
    due_date: Optional[date] = None
    status: BillStatus
    currency: str
    subtotal: Decimal
    tax: Decimal
    total: Decimal
    paid_amount: Decimal
    balance: Decimal
    is_critical: bool
    can_delay: bool
    notes: Optional[str] = None
    created_at: datetime
    model_config = {"from_attributes": True}


class TaskCreate(BaseModel):
    title: str
    description: Optional[str] = None
    due_date: Optional[date] = None
    entity_type: Optional[str] = None
    entity_id: Optional[int] = None
    alert_id: Optional[int] = None


class TaskUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[TaskStatus] = None
    due_date: Optional[date] = None


class TaskResponse(BaseModel):
    id: int
    title: str
    description: Optional[str] = None
    status: TaskStatus
    due_date: Optional[date] = None
    entity_type: Optional[str] = None
    entity_id: Optional[int] = None
    alert_id: Optional[int] = None
    created_at: datetime
    model_config = {"from_attributes": True}


class AlertResponse(BaseModel):
    id: int
    alert_type: str
    severity: AlertSeverity
    entity_type: Optional[str] = None
    entity_id: Optional[int] = None
    title: str
    message: Optional[str] = None
    status: AlertStatus
    created_at: datetime
    model_config = {"from_attributes": True}


class AlertUpdate(BaseModel):
    status: Optional[AlertStatus] = None


class NoteCreate(BaseModel):
    entity_type: str
    entity_id: int
    text: str


class NoteResponse(BaseModel):
    id: int
    entity_type: str
    entity_id: int
    text: str
    created_at: datetime
    model_config = {"from_attributes": True}


class BudgetCreate(BaseModel):
    category_name: str
    category_id: Optional[int] = None
    year: int
    month: int
    budgeted_amount: Decimal


class BudgetResponse(BaseModel):
    id: int
    category_name: Optional[str] = None
    category_id: Optional[int] = None
    year: int
    month: int
    budgeted_amount: Decimal
    actual_amount: Decimal
    created_at: datetime
    model_config = {"from_attributes": True}


class DashboardOverview(BaseModel):
    cash_balance: float
    cash_by_account: list
    month_revenue: float
    month_expenses: float
    month_gross_profit: float
    month_net_profit: float
    runway_months: Optional[float] = None
    ar_total: float
    ar_overdue: float
    ap_total: float
    ap_due_7_days: float
    ap_due_30_days: float
    alerts: list
    last_sync: Optional[datetime] = None


class CashFlowProjectionResponse(BaseModel):
    week: str
    expected_inflows: float
    expected_outflows: float
    net_flow: float
    cumulative_balance: float


class PnLResponse(BaseModel):
    month: str
    revenue: float
    cogs: float
    gross_profit: float
    opex: float
    net_profit: float
    categories: dict


class ARAgingResponse(BaseModel):
    bucket_0_30: float
    bucket_31_60: float
    bucket_61_90: float
    bucket_90_plus: float
    total: float
    count: int
    invoices: list
