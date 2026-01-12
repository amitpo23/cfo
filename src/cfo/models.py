"""
Data models for the CFO system
"""
from datetime import datetime
from decimal import Decimal
from typing import Optional, List
from enum import Enum
from pydantic import BaseModel, Field, EmailStr
from sqlalchemy import Column, Integer, String, Numeric, DateTime, ForeignKey, Enum as SQLEnum, Boolean, Text, JSON
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
    ASSET = "asset"  # נכס
    LIABILITY = "liability"  # התחייבות
    EQUITY = "equity"  # הון עצמי
    REVENUE = "revenue"  # הכנסה
    EXPENSE = "expense"  # הוצאה


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
    net_worth: Decimal  # הון עצמי
    total_income: Decimal
    total_expenses: Decimal
    net_income: Decimal  # רווח נקי
    period_start: datetime
    period_end: datetime
