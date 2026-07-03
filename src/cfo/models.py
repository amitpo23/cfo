"""
Data models for the CFO system
"""
from datetime import datetime, date, timezone
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
    OPEN_FINANCE = "open_finance"
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
    collection_reminders_enabled = Column(Boolean, default=False, nullable=False)
    collection_sms_sender = Column(String(20), nullable=True)

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
    # Provenance — distinguishes SUMIT synthesized accounts from real Open Finance
    # bank accounts so the two sources coexist without external_id collisions.
    source = Column(String(50), default="manual")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    organization = relationship("Organization", back_populates="accounts")
    transactions = relationship("Transaction", back_populates="account")

    __table_args__ = (
        Index("ix_account_org_ext_source", "organization_id", "external_id", "source", unique=True),
    )


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


class BankConnection(Base):
    """A bank/card consent link established through Open Finance (one per bank).

    Tracks the consent-journey lifecycle so the UI can launch `connect_url`, show
    status, and trigger refreshes. The org-level API credentials live in
    `IntegrationConnection`; this row is the per-bank consent state under it.
    """
    __tablename__ = "bank_connections"

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False)
    source = Column(String(50), default="open_finance")
    connection_id = Column(String(255), nullable=True)  # Open Finance connection id
    provider_id = Column(String(100), nullable=True)    # providerFriendlyId (bank)
    bank_name = Column(String(255), nullable=True)
    status = Column(String(40), default="INACTIVE")     # Open Finance connection status
    connect_url = Column(Text, nullable=True)           # hosted consent journey link
    psu_id = Column(String(64), nullable=True)
    expiry_date = Column(DateTime, nullable=True)
    accounts_count = Column(Integer, nullable=True)
    transactions_count = Column(Integer, nullable=True)
    last_refresh_at = Column(DateTime, nullable=True)
    last_error = Column(Text, nullable=True)
    raw_data = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    organization = relationship("Organization")

    __table_args__ = (
        Index("ix_bankconn_org_conn", "organization_id", "connection_id", unique=True),
        Index("ix_bankconn_org_status", "organization_id", "status"),
    )


class OpenFinancePayment(Base):
    """A payment initiated/tracked through the Open Finance PIS surface.

    Distinct from the SUMIT-billing ``Payment`` model — this mirrors Open
    Finance's Payment resource (``paymentId`` + status lifecycle). Rows are
    upserted from the Payment Status Change webhook, which carries
    ``{paymentId, paymentStatus, userId, orgId, ...}`` but no amount/currency
    (those are populated later from ``GET /payments/{id}/status``), so amount and
    currency are nullable. The unique ``(organization_id, external_payment_id)``
    constraint makes webhook delivery idempotent.
    """
    __tablename__ = "open_finance_payments"

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    external_payment_id = Column(String(255), nullable=False, index=True)  # Open Finance paymentId
    status = Column(String(40), nullable=True)  # Payment.status enum (ACCC, RJCT, PENDING, ...)
    amount = Column(Numeric(precision=14, scale=2), nullable=True)
    currency = Column(String(10), nullable=True)
    raw_data = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    organization = relationship("Organization")

    __table_args__ = (
        Index("ix_ofpayment_org_ext", "organization_id", "external_payment_id", unique=True),
    )


class SumitCompany(Base):
    """A SUMIT company file (תיק חברה) managed by an accounting office.

    Supports the multi-company "ניהול משרד" model: one office organization can
    manage many SUMIT company files. Each file syncs into a `target_organization`
    (its own tenant by default), enabling cross-company (רוחבי) synthesis rollups.
    """
    __tablename__ = "sumit_companies"

    id = Column(Integer, primary_key=True)
    # The managing office organization.
    office_organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False)
    # SUMIT company id (e.g. 844329067).
    company_id = Column(String(50), nullable=False)
    name = Column(String(255), nullable=True)
    status = Column(String(20), default="active")  # active, inactive
    # Where this file's books/bank data land (defaults to the office org).
    target_organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=True)
    last_synced_at = Column(DateTime, nullable=True)
    raw_data = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    office_organization = relationship("Organization", foreign_keys=[office_organization_id])

    __table_args__ = (
        Index("ix_sumitco_office_company", "office_organization_id", "company_id", unique=True),
    )


class Employee(Base):
    """An employee for the payroll module (org-scoped)."""
    __tablename__ = "employees"

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False)
    name = Column(String(255), nullable=False)
    tax_id = Column(String(20), nullable=True)             # תעודת זהות
    email = Column(String(255), nullable=True)
    phone = Column(String(50), nullable=True)
    gross_salary = Column(Numeric(precision=12, scale=2), default=0)   # monthly gross
    credit_points = Column(Numeric(precision=4, scale=2), default=2.25)  # נקודות זיכוי
    pension_pct = Column(Numeric(precision=4, scale=2), default=6.0)
    start_date = Column(Date, nullable=True)
    # Bank details for salary payment via Masav.
    bank_code = Column(String(2), nullable=True)
    bank_branch = Column(String(3), nullable=True)
    bank_account_number = Column(String(20), nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    organization = relationship("Organization")
    payslips = relationship("Payslip", back_populates="employee")

    __table_args__ = (
        Index("ix_employee_org", "organization_id", "is_active"),
    )


class Payslip(Base):
    """A generated payslip (תלוש שכר) for an employee for a given month."""
    __tablename__ = "payslips"

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False)
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=False)
    year = Column(Integer, nullable=False)
    month = Column(Integer, nullable=False)
    gross = Column(Numeric(precision=12, scale=2), default=0)
    income_tax = Column(Numeric(precision=12, scale=2), default=0)
    ni_employee = Column(Numeric(precision=12, scale=2), default=0)
    health_tax = Column(Numeric(precision=12, scale=2), default=0)
    pension_employee = Column(Numeric(precision=12, scale=2), default=0)
    net = Column(Numeric(precision=12, scale=2), default=0)
    employer_ni = Column(Numeric(precision=12, scale=2), default=0)
    employer_pension = Column(Numeric(precision=12, scale=2), default=0)
    employer_severance = Column(Numeric(precision=12, scale=2), default=0)
    employer_cost = Column(Numeric(precision=12, scale=2), default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

    organization = relationship("Organization")
    employee = relationship("Employee", back_populates="payslips")

    __table_args__ = (
        Index("ix_payslip_unique", "organization_id", "employee_id", "year", "month", unique=True),
        Index("ix_payslip_period", "organization_id", "year", "month"),
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


class OnboardingTask(Base):
    """One codified data-mapping step in a business's onboarding checklist.

    When a business connects an integration, a fixed list of ingestion steps
    (onboarding_service.ONBOARDING_STEPS) is materialized as one row per step. The
    pipeline runs them in order and re-runs incomplete/failed steps until the whole
    checklist completes — i.e. every part of the business's data is mapped AND
    reconciled against the source. Persisted so progress survives restarts and the
    same checklist runs identically for every new business.
    """
    __tablename__ = "onboarding_tasks"

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False)
    source = Column(String(50), nullable=False)  # sumit, open_finance
    step = Column(String(64), nullable=False)  # codified step key
    seq = Column(Integer, default=0)  # run/display order
    status = Column(String(20), default="pending")  # pending, running, completed, failed, skipped
    result = Column(JSON, default={})  # counts/totals/reconciliation for the step
    error = Column(Text, nullable=True)
    attempts = Column(Integer, default=0)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    organization = relationship("Organization")

    __table_args__ = (
        Index("ix_onboarding_org_source_step", "organization_id", "source", "step", unique=True),
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
    # שיעור ניכוי מס במקור לספק (0 = יש אישור ניכוי/פטור; 0.30 ספק ללא אישור, 0.20 קבלן).
    # ברירת מחדל 0 — דיווח 856 כולל רק ספקים שסומנו במפורש כחייבי ניכוי.
    withholding_rate = Column(Numeric(precision=5, scale=4), default=0)
    address = Column(Text, nullable=True)
    currency = Column(String(10), default="ILS")
    # Bank account details for Masav (מס"ב) supplier payments
    bank_code = Column(String(2), nullable=True)            # קוד בנק
    bank_branch = Column(String(3), nullable=True)          # מספר סניף
    bank_account_number = Column(String(20), nullable=True) # מספר חשבון
    bank_account_holder = Column(String(255), nullable=True)  # שם בעל החשבון (אם שונה משם הספק)
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
    # מספר הקצאה (חשבונית ישראל) — SUMIT מפיק מול רשות המסים; נמשך מ-AssignmentNumber.
    allocation_number = Column(String(50), nullable=True)
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


class CollectionReminder(Base):
    """תיעוד תזכורת גבייה שנשלחה — מצב להסלמה ומניעת ספאם."""
    __tablename__ = "collection_reminders"

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False)
    contact_id = Column(Integer, ForeignKey("contacts.id"), nullable=True)
    invoice_numbers = Column(String(500), nullable=True)
    reminder_type = Column(String(20), nullable=False)   # first | second | final
    channel = Column(String(20), nullable=False)         # sms | email
    amount = Column(Numeric(precision=12, scale=2), default=0)
    days_overdue = Column(Integer, default=0)
    status = Column(String(20), default="sent")          # sent | failed
    error = Column(Text, nullable=True)
    sent_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        Index("ix_collreminder_org_contact", "organization_id", "contact_id"),
    )


class InventoryItem(Base):
    """Inventory / stock item — מלאי"""
    __tablename__ = "inventory_items"

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False)
    external_id = Column(String(255), nullable=True)  # SUMIT item ID
    source = Column(String(50), default="manual")
    sku = Column(String(100), nullable=True)          # מק"ט
    name = Column(String(255), nullable=False)        # שם הפריט
    quantity = Column(Numeric(precision=12, scale=2), default=0)    # כמות במלאי
    unit = Column(String(50), default="unit")         # יחידת מידה
    unit_cost = Column(Numeric(precision=12, scale=2), default=0)   # עלות ליחידה
    unit_price = Column(Numeric(precision=12, scale=2), default=0)  # מחיר מכירה
    reorder_level = Column(Numeric(precision=12, scale=2), default=0)  # סף התראת מלאי נמוך
    is_active = Column(Boolean, default=True)
    raw_data = Column(JSON, nullable=True)
    last_updated = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)

    organization = relationship("Organization")

    __table_args__ = (
        Index("ix_inventory_org_ext", "organization_id", "external_id", "source", unique=True),
    )


class Expense(Base):
    """הוצאה לתיוק — supplier expense to be filed in SUMIT"""
    __tablename__ = "expenses"

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False)
    external_id = Column(String(255), nullable=True)   # SUMIT document ID (when pulled)
    source = Column(String(50), default="manual")
    supplier_id = Column(Integer, ForeignKey("contacts.id"), nullable=True)
    supplier_name = Column(String(255), nullable=False)
    supplier_tax_id = Column(String(20), nullable=True)  # ח.פ/עוסק של הספק (נדרש ל-PCN874)
    sumit_item_name = Column(String(255), nullable=True)  # שם פריט ההוצאה ב-SUMIT — אות הסיווג האמין
    amount = Column(Numeric(precision=12, scale=2), nullable=False, default=0)  # before VAT
    vat_amount = Column(Numeric(precision=12, scale=2), default=0)
    total = Column(Numeric(precision=12, scale=2), default=0)
    expense_date = Column(Date, nullable=False)
    category = Column(String(100), nullable=True)
    description = Column(Text, nullable=True)
    receipt_file = Column(Text, nullable=True)         # base64 receipt (optional)
    invoice_number = Column(String(100), nullable=True)
    status = Column(String(20), default="pending")     # pending, filed, error
    sumit_expense_id = Column(String(255), nullable=True)
    filing_error = Column(Text, nullable=True)
    classifier_feedback = Column(JSON, nullable=True)  # learning feedback: [{"timestamp": "...", "old_category": "...", "new_category": "...", "supplier": "...", "feedback_text": "..."}]
    raw_data = Column(JSON, nullable=True)
    # % of this expense recognized as tax-deductible (e.g. partial vehicle/phone/home
    # office use). NULL = fully recognized (unchanged historical behavior) — never a
    # fabricated default; real Israeli deduction rules need per-case inputs (odometer
    # readings, use-value tables) this system doesn't have, so nothing auto-computes it.
    deduction_percent = Column(Numeric(precision=5, scale=2), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    organization = relationship("Organization")
    supplier = relationship("Contact")

    __table_args__ = (
        Index("ix_expense_org_status", "organization_id", "status"),
        Index("ix_expense_org_ext", "organization_id", "external_id", "source"),
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
    reconciliation_dispatch_status = Column(String(30), default="not_sent")
    reconciliation_dispatched_at = Column(DateTime, nullable=True)
    external_reconciliation_id = Column(String(255), nullable=True)
    reconciliation_error = Column(Text, nullable=True)
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
    meta = Column("metadata", JSON, nullable=True)  # extra context
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


class LedgerOpeningBalance(Base):
    """Opening balance per account for the derived ledger (carry-forward).

    One row per (org, account_code) effective `as_of`. Stored as signed debit/credit;
    the ledger injects a single balanced opening entry (auto-plugging any residual to
    the equity account) so the trial balance stays balanced. See ledger_service.
    """
    __tablename__ = "ledger_opening_balances"

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False)
    account_code = Column(String(10), nullable=False)
    as_of = Column(Date, nullable=False)
    debit = Column(Numeric(precision=14, scale=2), default=0)
    credit = Column(Numeric(precision=14, scale=2), default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    organization = relationship("Organization")

    __table_args__ = (
        UniqueConstraint("organization_id", "account_code", name="uq_opening_balance"),
    )


class CashflowAgreement(Base):
    """Persisted agreement for the agreement-based cash-flow service.

    The service keeps rich dataclasses in memory; this table is their durable store
    (one JSON blob per agreement) so agreements survive restarts. See
    services/agreement_cashflow_service.py.
    """
    __tablename__ = "cashflow_agreements"

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False)
    agreement_id = Column(String(50), nullable=False)
    data = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    organization = relationship("Organization")

    __table_args__ = (
        UniqueConstraint("organization_id", "agreement_id", name="uq_cashflow_agreement"),
    )


class CashflowEntry(Base):
    """Persisted cash-flow entry (income/expense, actual/forecast) for the service."""
    __tablename__ = "cashflow_entries"

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False)
    entry_id = Column(String(50), nullable=False)
    data = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    organization = relationship("Organization")

    __table_args__ = (
        UniqueConstraint("organization_id", "entry_id", name="uq_cashflow_entry"),
    )


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


class CfoMemory(Base):
    """Persistent internal memory for CFO analysis facts and learned state"""
    __tablename__ = "cfo_memory"

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False)
    memory_key = Column(String(255), nullable=False)
    memory_type = Column(String(100), nullable=False)  # metric, connection, preference, benchmark
    value = Column(JSON, nullable=False)
    source = Column(String(100), nullable=True)
    confidence = Column(Float, default=1.0)
    last_seen_at = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    organization = relationship("Organization")

    __table_args__ = (
        UniqueConstraint("organization_id", "memory_key", name="uq_cfo_memory_key"),
        Index("ix_cfo_memory_org_type", "organization_id", "memory_type"),
    )


class CfoInsight(Base):
    """Actionable insight generated by the CFO brain"""
    __tablename__ = "cfo_insights"

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False)
    fingerprint = Column(String(255), nullable=False)
    insight_type = Column(String(100), nullable=False)
    severity = Column(String(20), default="info")  # info, low, medium, high, critical
    title = Column(String(500), nullable=False)
    message = Column(Text, nullable=True)
    evidence = Column(JSON, nullable=True)
    recommended_action = Column(Text, nullable=True)
    status = Column(String(20), default="active")  # active, acknowledged, resolved
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    resolved_at = Column(DateTime, nullable=True)

    organization = relationship("Organization")

    __table_args__ = (
        UniqueConstraint("organization_id", "fingerprint", name="uq_cfo_insight_fingerprint"),
        Index("ix_cfo_insight_org_status", "organization_id", "status"),
    )


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
    registration_code: Optional[str] = None
    selected_plan: Optional[str] = None
    annual_revenue: Optional[str] = None
    annual_report_requested: Optional[bool] = None
    payment_template: Optional[str] = None
    checkout_session_id: Optional[str] = None
    payment_status: Optional[str] = None


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


class GoogleLogin(BaseModel):
    """Google Sign-In token exchange"""
    id_token: str
    registration_code: Optional[str] = None
    selected_plan: Optional[str] = None
    annual_revenue: Optional[str] = None
    annual_report_requested: Optional[bool] = None
    payment_template: Optional[str] = None
    checkout_session_id: Optional[str] = None
    payment_status: Optional[str] = None


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
