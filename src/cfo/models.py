"""
Data models for the CFO system
"""
from datetime import datetime, date, timezone
from decimal import Decimal
from typing import Optional, List
from enum import Enum
from pydantic import BaseModel, Field, EmailStr, field_validator
from sqlalchemy import (
    Column, Integer, String, Numeric, DateTime, Date,
    ForeignKey, Enum as SQLEnum, Boolean, Text, JSON,
    Index, Float, UniqueConstraint, CheckConstraint, func, true, false
)
from sqlalchemy import text
from sqlalchemy.orm import declarative_base, relationship

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
    # Source charts can contain control/system accounts whose debit/credit
    # nature cannot be inferred safely from the source classification alone
    # (for example VAT current accounts and tax institutions).
    OTHER = "other"


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

    # --- PR5 (bookkeeper daily-cycle plan) morning-brief delivery opt-ins --- #
    # Email is on by default (it's free); SMS costs money per message, so it
    # stays opt-in and — per morning_brief_service — is only ever sent when
    # the brief is red, one line, regardless of this flag being on.
    # Server defaults keep raw SQL/additive paths aligned with the original
    # Alembic migration's NOT NULL contract; service code still treats legacy
    # NULL rows conservatively during a staged repair.
    morning_brief_email_enabled = Column(
        Boolean, default=True, nullable=False, server_default=true(),
    )
    morning_brief_recipients = Column(String(500), nullable=True)
    morning_brief_sms_enabled = Column(
        Boolean, default=False, nullable=False, server_default=false(),
    )

    # --- חבילה H (התאמת בעלות אוטומטית) --- #
    # חותמת שהבעלים (מנהל המערכת היחיד — אין "אדמין ארגון") הכריע ידנית מי
    # חשבון העסק הראשי, דרך POST /admin/moshko/ownership-review/{id}/resolve.
    # NULL = לא הוכרע — account_ownership.ownership_status ממשיך להתאים
    # אוטומטית (tax_id ↔ Account.owner_national_id ↔ SUMIT CorporateNumber);
    # ערך = ההתאמה נעולה ידנית ולא חוזרת לתור ההכרעה.
    ownership_reviewed_at = Column(DateTime, nullable=True)

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

    # --- הקשחת login (W6.7) --- #
    # מונה כישלונות רצופים; 5 כישלונות → נעילה זמנית (locked_until).
    # הצלחה מאפסת. נשמר במסד ולא בזיכרון — serverless לא שומר state.
    failed_login_attempts = Column(
        Integer, nullable=False, default=0, server_default="0",
    )
    locked_until = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    organization = relationship("Organization", back_populates="users")


class PasswordResetToken(Base):
    """טוקן חד-פעמי לאיפוס סיסמה — נשמר רק sha256 של הטוקן, לעולם לא הטוקן עצמו.

    תוקף 30 דקות; ``used_at`` אוכף חד-פעמיות. מי שמחזיק את המסד אינו
    יכול לשחזר ממנו קישור איפוס עובד.
    """
    __tablename__ = "password_reset_tokens"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    token_hash = Column(String(64), nullable=False, unique=True, index=True)
    expires_at = Column(DateTime, nullable=False)
    used_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class RevokedToken(Base):
    """denylist של JWT — לפי claim ‏jti — לטוקנים שבוטלו ב-logout.

    ``expires_at`` (ה-exp של הטוקן) מאפשר ניקוי הזדמנותי: אחרי שהטוקן
    ממילא פג, אין טעם להחזיק את הרשומה. טוקנים ישנים בלי jti אינם
    ניתנים לביטול — הם פגים מעצמם (תאימות לאחור מכוונת).
    """
    __tablename__ = "revoked_tokens"

    id = Column(Integer, primary_key=True)
    jti = Column(String(64), nullable=False, unique=True, index=True)
    revoked_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    expires_at = Column(DateTime, nullable=True)


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


class OrganizationMembership(Base):
    """חברות של אדם בארגון, עם תפקיד — אחד לכל צירוף.

    `User.organization_id` הוא FK יחיד, ולכן אדם יכול היה להשתייך לארגון
    אחד בלבד. זה שגוי במציאות שהמערכת משרתת: בעל עסק יכול להיות ADMIN
    בחברה שלו ו-VIEWER בחברה של שותף, ומנהלת חשבונות עובדת על עשרות תיקים.

    הטבלה יושבת ב**מסד הבקרה** (ראו `docs/adr/0001`): היא זו שמכריעה
    לאיזה מסד ארגוני מותר לפנות, ולכן אינה יכולה לשבת בתוכו.

    `users.organization_id` **לא נמחק** — הוא מקור ה-backfill ונשאר
    fallback לקריאה עד שכל הקוראים יעברו.

    חברות נוצרת בהזמנה או ב-bootstrap מפורש בלבד. אין נתיב שיוצר אותה
    מהתאמת מייל, דומיין או נתון מ-SUMIT: Google מאמת אדם, לא בעלות על
    עסק. `tests/test_organization_membership.py` שומר על כך מבנית.
    """
    __tablename__ = "organization_memberships"

    id = Column(Integer, primary_key=True)
    organization_id = Column(
        Integer, ForeignKey("organizations.id"), nullable=False,
    )
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    role = Column(SQLEnum(UserRole), nullable=False, default=UserRole.USER)
    # invited = הוזמן וטרם התקבל · active = פעיל · suspended = מושהה זמנית
    # · revoked = בוטל. רק `active` מקנה גישה.
    status = Column(String(20), nullable=False, default="invited")
    invited_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    verified_at = Column(DateTime(timezone=True), nullable=True)
    # גישה זמנית (למשל רו"ח חיצוני לתקופת ביקורת). נבדק בזמן השאילתה ולא
    # במשימת ניקוי — כדי שפקיעה תיכנס לתוקף מיד ולא בהרצה הבאה של cron.
    expires_at = Column(DateTime(timezone=True), nullable=True)
    revoked_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc), nullable=False,
    )

    __table_args__ = (
        UniqueConstraint(
            "user_id", "organization_id", name="uq_membership_user_org",
        ),
        # `SUPER_ADMIN` הוא תפקיד פלטפורמה, לא תפקיד בתוך ארגון. חברות
        # כזו הייתה מאפשרת למנהל ארגון להעניק סמכות-על בתיק שלו ולעקוף
        # את ההפרדה בין מפעיל מערכת לבעל עסק. האילוץ יושב במסד ולא רק
        # בשירות, כדי שגם כתיבה ישירה תיחסם.
        CheckConstraint(
            "role != 'SUPER_ADMIN'", name="ck_membership_role_not_super_admin",
        ),
        Index("ix_membership_user_status", "user_id", "status"),
        Index("ix_membership_org_status", "organization_id", "status"),
    )


class OrganizationSigningAuthority(Base):
    """Business-owner/signatory authority, separate from application RBAC.

    ADMIN and SUPER_ADMIN describe application access.  This row answers the
    different question: who may approve an irreversible business action for
    this organization, and for which action types.
    """
    __tablename__ = "organization_signing_authorities"

    id = Column(Integer, primary_key=True)
    organization_id = Column(
        Integer, ForeignKey("organizations.id"), nullable=False,
    )
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    authority_type = Column(
        String(30), nullable=False, default="authorized_signer",
    )  # owner | authorized_signer
    action_types = Column(JSON, nullable=False, default=lambda: ["*"])
    is_active = Column(Boolean, nullable=False, default=True)
    granted_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    revoked_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    revoked_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "user_id",
            name="uq_signing_authority_org_user",
        ),
        Index(
            "ix_signing_authority_org_active",
            "organization_id",
            "is_active",
        ),
    )


class PolicyGrant(Base):
    """Organization-scoped policy overlay for one role or one user.

    Application RBAC remains the broad baseline.  These rows add explicit
    denies and the financial boundaries that a role alone cannot express.
    A grant can target exactly one user or one organization role, never both.
    """
    __tablename__ = "policy_grants"

    id = Column(Integer, primary_key=True)
    organization_id = Column(
        Integer, ForeignKey("organizations.id"), nullable=False,
    )
    action = Column(String(80), nullable=False)
    effect = Column(String(10), nullable=False, default="allow")
    role = Column(SQLEnum(UserRole), nullable=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    max_amount = Column(Numeric(18, 2), nullable=True)
    daily_limit_amount = Column(Numeric(18, 2), nullable=True)
    monthly_limit_amount = Column(Numeric(18, 2), nullable=True)
    currency = Column(String(3), nullable=False, default="ILS")
    allowed_bank_accounts = Column(JSON, nullable=True)
    allowed_counterparties = Column(JSON, nullable=True)
    allowed_document_types = Column(JSON, nullable=True)
    allowed_channels = Column(JSON, nullable=True)

    valid_from = Column(DateTime(timezone=True), nullable=True)
    valid_until = Column(DateTime(timezone=True), nullable=True)
    requires_step_up = Column(Boolean, nullable=False, default=False)
    required_approvals = Column(Integer, nullable=False, default=1)
    separation_of_duties = Column(Boolean, nullable=False, default=False)
    requires_reason = Column(Boolean, nullable=False, default=False)
    is_active = Column(Boolean, nullable=False, default=True)

    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    revoked_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    revoked_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "effect IN ('allow', 'deny')", name="ck_policy_grant_effect",
        ),
        CheckConstraint(
            "((role IS NOT NULL AND user_id IS NULL) OR "
            "(role IS NULL AND user_id IS NOT NULL))",
            name="ck_policy_grant_single_subject",
        ),
        CheckConstraint(
            "required_approvals >= 1", name="ck_policy_required_approvals",
        ),
        CheckConstraint(
            "max_amount IS NULL OR max_amount > 0",
            name="ck_policy_max_amount_positive",
        ),
        CheckConstraint(
            "daily_limit_amount IS NULL OR daily_limit_amount > 0",
            name="ck_policy_daily_limit_positive",
        ),
        CheckConstraint(
            "monthly_limit_amount IS NULL OR monthly_limit_amount > 0",
            name="ck_policy_monthly_limit_positive",
        ),
        Index("ix_policy_grant_org_action_active", "organization_id", "action", "is_active"),
        Index("ix_policy_grant_org_user", "organization_id", "user_id"),
    )


class IrreversibleActionRequest(Base):
    """Durable proposal/approval/execution evidence for an external action.

    The row stores the exact payload that was reviewed. Execution is claimed
    atomically by the service; provider acceptance and independent readback
    are separate states so an HTTP 200 can never masquerade as verification.
    """
    __tablename__ = "irreversible_action_requests"

    id = Column(Integer, primary_key=True)
    organization_id = Column(
        Integer, ForeignKey("organizations.id"), nullable=False,
    )
    action_type = Column(String(50), nullable=False)
    description = Column(Text, nullable=True)
    payload = Column(JSON, nullable=False)
    payload_sha256 = Column(String(64), nullable=False)
    idempotency_key = Column(String(160), nullable=False)
    origin_channel = Column(
        String(30), nullable=False, default="internal", server_default="internal",
    )

    status = Column(String(24), nullable=False, default="proposed")
    proposed_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    approved_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    approver_role = Column(String(30), nullable=True)
    approved_by_authority_id = Column(
        Integer,
        ForeignKey("organization_signing_authorities.id"),
        nullable=True,
    )
    approver_authority_type = Column(String(30), nullable=True)

    provider_reference = Column(String(255), nullable=True)
    execution_result = Column(JSON, nullable=True)
    verification_evidence = Column(JSON, nullable=True)
    error = Column(Text, nullable=True)

    # Sanitized policy decisions are retained as evidence.  They contain the
    # outcome/reason and requirements, not account allow-lists or secrets.
    policy_proposed_decision = Column(JSON, nullable=True)
    policy_approved_decision = Column(JSON, nullable=True)
    policy_execution_decision = Column(JSON, nullable=True)

    proposed_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    approved_at = Column(DateTime(timezone=True), nullable=True)
    rejected_at = Column(DateTime(timezone=True), nullable=True)
    execution_started_at = Column(DateTime(timezone=True), nullable=True)
    executed_at = Column(DateTime(timezone=True), nullable=True)
    verified_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "idempotency_key",
            name="uq_irreversible_action_org_idempotency",
        ),
        Index(
            "ix_irreversible_action_org_status",
            "organization_id",
            "status",
        ),
    )


class IrreversibleActionApproval(Base):
    """One distinct signatory approval for an immutable action request."""
    __tablename__ = "irreversible_action_approvals"

    id = Column(Integer, primary_key=True)
    organization_id = Column(
        Integer, ForeignKey("organizations.id"), nullable=False,
    )
    request_id = Column(
        Integer, ForeignKey("irreversible_action_requests.id"), nullable=False,
    )
    approved_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    authority_id = Column(
        Integer, ForeignKey("organization_signing_authorities.id"), nullable=False,
    )
    authority_type = Column(String(30), nullable=False)
    policy_decision = Column(JSON, nullable=False)
    approved_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint(
            "request_id", "approved_by_user_id",
            name="uq_action_approval_request_user",
        ),
        Index("ix_action_approval_org_request", "organization_id", "request_id"),
    )


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
    # Open Finance consent connection that owns this account.  This is kept
    # separate from IntegrationConnection.id: the latter is Rezef's encrypted
    # org-level connector configuration, while this value is the provider's
    # opaque per-bank consent id.  NULL for manual/SUMIT accounts and for old
    # observations that predate the mapping (honest-null; never guessed).
    open_finance_connection_id = Column(String(255), nullable=True)
    # Source chart-of-accounts provenance.  These columns intentionally live on
    # Account (the existing connector chart data plane), not ExpenseCategory and
    # not a parallel ledger-account table.
    source_account_code = Column(String(100), nullable=True)
    source_name = Column(String(255), nullable=True)
    source_classification = Column(String(50), nullable=True)
    sort_code = Column(String(50), nullable=True)
    vat_key = Column(String(50), nullable=True)
    tax_id = Column(String(20), nullable=True)
    withholding_rate = Column(Numeric(precision=7, scale=4), nullable=True)
    withholding_valid_until = Column(Date, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    is_historical = Column(Boolean, nullable=False, default=False)
    source_status_code = Column(String(10), nullable=True)
    row_hash = Column(String(64), nullable=True)
    source_file_hash = Column(String(64), nullable=True)
    observed_at = Column(DateTime(timezone=True), nullable=True)
    synced_at = Column(DateTime(timezone=True), nullable=True)
    # Filled only by the later SUMIT readback; offline source importers preserve it.
    sumit_account_code = Column(String(100), nullable=True)
    # חותמת טריות ליתרה — referenceDate של רשומת ה-balance שנבחרה מ-Open
    # Finance (closingBooked/expected/interimAvailable, האחרון מבין הזמינים).
    # NULL לחשבונות שלא הגיעו מ-OF (SUMIT מסונתז, ידני).
    balance_as_of = Column(DateTime, nullable=True)
    # סוג החשבון הגולמי מהספק (CHECKING/SAVINGS/LOAN/CARD) — נשמר בנפרד מ-
    # account_type המנורמל כי LOAN ו-CARD שניהם ממופים ל-AccountType.LIABILITY,
    # אבל הדשבורד צריך להציג "הלוואות" ו"חוב כרטיס" בנפרד (סעיף ד בתוכנית).
    raw_account_type = Column(String(20), nullable=True)
    # מסגרת אשראי בנקאית (מסגרת חח"ד/אשראי) — מ-creditLimit של Open Finance,
    # שדה top-level על ה-Account שקיים לכל סוג חשבון (כולל CHECKING עם מסגרת
    # חריגה, לא רק LOAN). NULL = לא ידוע (הספק לא החזיר את השדה) — לעולם לא
    # נגזר מ-interimAvailable (זמין-לשימוש, לא מסגרת).
    credit_limit = Column(Numeric(precision=14, scale=2), nullable=True)
    # בעלות מדויקת (חבילה H) — Open Finance מחזיר ownerInfo.{nationalId,
    # fullName} על כל Account (docs/OPEN_FINANCE_KNOWLEDGE_BASE.md:248).
    # nationalId מנורמל לספרות בלבד ע"י account_ownership.normalize_israeli_id
    # לפני שמירה. NULL = הספק לא סיפק ownerInfo (honest-null), לא ניחוש.
    # מתמלא בסנכרון היומי הרגיל — אין קריאת API ייעודית בשביל זה.
    owner_national_id = Column(String(20), nullable=True, index=True)
    owner_name = Column(String(255), nullable=True)
    # עקיפה ידנית של הבעלים (מנהל המערכת היחיד): מסמן איזה חשבון הוא חשבון
    # העסק כשההתאמה האוטומטית (account_ownership.ownership_status) לא
    # מתלכדת. NULL/False = לא נבחר. ר' גם Organization.ownership_reviewed_at.
    is_primary_business_account = Column(Boolean, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    organization = relationship("Organization", back_populates="accounts")
    transactions = relationship("Transaction", back_populates="account")

    __table_args__ = (
        Index("ix_account_org_ext_source", "organization_id", "external_id", "source", unique=True),
        Index(
            "ix_account_org_of_connection",
            "organization_id", "open_finance_connection_id",
        ),
        UniqueConstraint(
            "organization_id",
            "source_account_code",
            name="uq_account_org_source_account_code",
        ),
    )


class AccountImportChange(Base):
    """Immutable audit evidence for source chart changes detected on re-import."""

    __tablename__ = "account_import_changes"

    id = Column(Integer, primary_key=True)
    organization_id = Column(
        Integer, ForeignKey("organizations.id"), nullable=False, index=True
    )
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False, index=True)
    source_account_code = Column(String(100), nullable=False)
    source_file_hash = Column(String(64), nullable=False)
    old_row_hash = Column(String(64), nullable=True)
    new_row_hash = Column(String(64), nullable=False)
    changes = Column(JSON, nullable=False)
    changed_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    organization = relationship("Organization")
    account = relationship("Account")


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

    # W6.4 (21/08/2026): לטבלה לא היה אף אינדקס — אפילו לא organization_id.
    __table_args__ = (
        Index("ix_transaction_org", "organization_id"),
    )


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


class ProviderRequestBudget(Base):
    """Atomic cross-instance provider request counter for one UTC window."""
    __tablename__ = "provider_request_budgets"

    id = Column(Integer, primary_key=True)
    provider = Column(String(30), nullable=False)
    # "global" protects provider/IP burst limits; "org:<id>" protects the
    # customer's paid daily allowance.  A string avoids NULL uniqueness traps.
    scope_key = Column(String(80), nullable=False)
    organization_id = Column(Integer, nullable=True)
    window_kind = Column(String(20), nullable=False)
    window_start = Column(DateTime(timezone=True), nullable=False)
    used = Column(Integer, nullable=False, default=0)
    limit_value = Column(Integer, nullable=False)
    updated_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc), nullable=False,
    )

    __table_args__ = (
        UniqueConstraint(
            "provider", "scope_key", "window_kind", "window_start",
            name="uq_provider_budget_window",
        ),
        CheckConstraint("used >= 0", name="ck_provider_budget_used_nonnegative"),
        CheckConstraint("limit_value >= 0", name="ck_provider_budget_limit_nonnegative"),
        Index(
            "ix_provider_budget_provider_window",
            "provider", "window_kind", "window_start",
        ),
    )


class SumitQuotaMeasurement(Base):
    """W2.1 — מדידת מכסת הפעולות-בתשלום כפי שנקראה מ-SUMIT (`listquotas`).

    שורה לכל רענון; הטרייה ביותר פר-ארגון היא המדידה המחייבת. אין שורה
    טרייה (26h) ⇒ פעולות בתשלום חסומות — fail-closed, לא ניחוש.
    """
    __tablename__ = "sumit_quota_measurements"

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False)
    environment = Column(String(10), nullable=False)  # test | live
    used = Column(Integer, nullable=False)
    limit_value = Column(Integer, nullable=False)
    measured_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    __table_args__ = (
        Index(
            "ix_sumit_quota_measurements_org_measured",
            "organization_id", "measured_at",
        ),
    )


class SyncCheckpoint(Base):
    """Per (org, source, entity_type) sync-call-protection state (M1a).

    Tracks the watermark used to compute `updated_since` for the next run,
    a resumable cursor when a run stops early (page cap), and the
    backoff/circuit-breaker state that keeps a broken/rate-limited provider
    from being hammered every cron tick.

    entity_type also carries a source-level sentinel row, "__source__", used
    for state that isn't per-entity: the manual-refresh cooldown and the
    Open-Finance daily-full-sync budget gate. Naive UTC datetimes throughout
    (matches this file's existing `datetime.utcnow` convention) so SQLite
    comparisons never mix naive/aware.
    """
    __tablename__ = "sync_checkpoints"

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False)
    source = Column(String(50), nullable=False)  # sumit, open_finance
    entity_type = Column(String(50), nullable=False)  # invoices, bills, ... or "__source__"
    last_success_at = Column(DateTime, nullable=True)
    cursor = Column(String(500), nullable=True)  # resume cursor when a run stopped at the page cap
    cooldown_until = Column(DateTime, nullable=True)  # manual-refresh cooldown (source-level row)
    consecutive_failures = Column(Integer, default=0, nullable=False)
    circuit_open_until = Column(DateTime, nullable=True)  # skip syncing this entity until then
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    organization = relationship("Organization")

    __table_args__ = (
        UniqueConstraint(
            "organization_id", "source", "entity_type",
            name="uq_sync_checkpoint_org_source_entity",
        ),
    )


class DailySnapshot(Base):
    """תמונת-מצב יומית פר-org — נשמרת ע"י cron/daily-close (docs/
    REZEF_DATA_INTEGRITY_PLAN.md סעיף ג2). הבסיס למגמות (מזומן/AR/AP/רווח
    לאורך זמן) בלי לחשב מחדש היסטוריה בכל בקשה."""
    __tablename__ = "daily_snapshots"

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False)
    snapshot_date = Column(Date, nullable=False)
    cash_balance = Column(Numeric(precision=14, scale=2), nullable=True)
    ar_total = Column(Numeric(precision=14, scale=2), nullable=True)
    ap_total = Column(Numeric(precision=14, scale=2), nullable=True)
    month_net_profit = Column(Numeric(precision=14, scale=2), nullable=True)
    undocumented_total = Column(Numeric(precision=14, scale=2), nullable=True)
    data_quality_issues = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # --- PR4 (bookkeeper morning-cycle orchestrator) additions --- #
    # כולם nullable — honest-null: מולאים רק כשהצעד המתאים במחזור-הבוקר
    # רץ בפועל (למשל /cron/daily-close הישן, שרץ לבדו, לא ממלא אותם).
    unreconciled_count = Column(Integer, nullable=True)
    open_expense_drafts = Column(Integer, nullable=True)
    exceptions_over_48h = Column(Integer, nullable=True)
    # ok | mismatch | stale | unknown
    # "unknown" = שום בדיקה מהותית לא השוותה דבר (ר' parity_service). הוא
    # נשמר ככל הכרעה אחרת — ריצה שלא הוכיחה כלום חייבת להותיר עקבה מדידה,
    # אחרת אין מגמה ואי-אפשר לדעת מתי הפער נסגר.
    parity_status = Column(String(20), nullable=True)
    credit_headroom = Column(Numeric(precision=14, scale=2), nullable=True)
    credit_breach_date = Column(Date, nullable=True)
    cycle_status = Column(String(10), nullable=True)  # green | yellow | red
    days_to_next_deadline = Column(Integer, nullable=True)
    open_items = Column(JSON, nullable=True)

    organization = relationship("Organization")

    __table_args__ = (
        UniqueConstraint(
            "organization_id", "snapshot_date",
            name="uq_daily_snapshot_org_date",
        ),
    )


class MorningBrief(Base):
    """PR5 of the bookkeeper daily-cycle plan — the persisted 08:00 morning
    brief. One row per (organization, brief_date); `payload` holds the full
    composed brief dict from morning_brief_service.compose_brief so the brief
    can be re-rendered/re-served without recomputation, and
    `delivered_channels` tracks per-channel delivery timestamps for
    idempotency (a channel already delivered today is skipped unless forced).
    """
    __tablename__ = "morning_briefs"

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False)
    brief_date = Column(Date, nullable=False)
    payload = Column(JSON, nullable=True)
    status = Column(String(10), nullable=True)  # green | yellow | red
    delivered_channels = Column(JSON, default=dict)  # {"email": "2026-07-21T05:02:11Z", ...}
    created_at = Column(DateTime, default=datetime.utcnow)

    organization = relationship("Organization")

    __table_args__ = (
        UniqueConstraint(
            "organization_id", "brief_date",
            name="uq_morning_brief_org_date",
        ),
    )


class OfSnapshotCache(Base):
    """Per (org, resource) cached JSON payload from a live Open Finance read
    (RSF-030 — read paths must not trigger live Open Finance calls).

    Backs `services/of_snapshot_service.get_or_fetch`: pages/routes that used
    to proxy LIVE to Open Finance on every view now serve this row when it's
    fresh (< max_age_hours), fetch live exactly once when it's stale/missing
    and upsert here, and fall back to the (marked) stale row instead of
    failing the page when a live re-fetch errors. `resource` is a free-form
    key (e.g. "payments", "monthly_report", "connection:<id>") so unrelated
    endpoints/sub-resources for the same org never collide.
    """
    __tablename__ = "of_snapshot_cache"

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False)
    # 100 not 50: BankConnection.connection_id is String(255) (opaque
    # provider id, no documented length cap), and resource keys like
    # "connection:<connection_id>" or "bank-branches:<bank_code>" embed it —
    # Postgres enforces the VARCHAR bound (unlike SQLite, which silently
    # truncates/ignores it in tests), so this must have real headroom.
    resource = Column(String(100), nullable=False)
    payload = Column(JSON, nullable=True)
    fetched_at = Column(DateTime, nullable=True)

    organization = relationship("Organization")

    __table_args__ = (
        UniqueConstraint(
            "organization_id", "resource",
            name="uq_of_snapshot_cache_org_resource",
        ),
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
    # W6.4 (21/08/2026): NOT NULL + server_default — INSERT שעוקף את ה-ORM
    # (סנכרון bulk, SQL ידני) לא ישאיר NULL שמאפס SUM בשקט.
    subtotal = Column(Numeric(precision=12, scale=2), default=0, nullable=False, server_default=text("0"))
    tax = Column(Numeric(precision=12, scale=2), default=0, nullable=False, server_default=text("0"))
    total = Column(Numeric(precision=12, scale=2), default=0, nullable=False, server_default=text("0"))
    paid_amount = Column(Numeric(precision=12, scale=2), default=0, nullable=False, server_default=text("0"))
    balance = Column(Numeric(precision=12, scale=2), default=0, nullable=False, server_default=text("0"))  # total - paid
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
    # W6.4 (21/08/2026): NOT NULL + server_default — INSERT שעוקף את ה-ORM
    # (סנכרון bulk, SQL ידני) לא ישאיר NULL שמאפס SUM בשקט.
    subtotal = Column(Numeric(precision=12, scale=2), default=0, nullable=False, server_default=text("0"))
    tax = Column(Numeric(precision=12, scale=2), default=0, nullable=False, server_default=text("0"))
    total = Column(Numeric(precision=12, scale=2), default=0, nullable=False, server_default=text("0"))
    paid_amount = Column(Numeric(precision=12, scale=2), default=0, nullable=False, server_default=text("0"))
    balance = Column(Numeric(precision=12, scale=2), default=0, nullable=False, server_default=text("0"))
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
        # W6.4: שיוך תשלומים ו-aging סרקו את הטבלה בלי אינדקס.
        Index("ix_payment_invoice", "invoice_id"),
        Index("ix_payment_bill", "bill_id"),
        Index("ix_payment_org_date", "organization_id", "payment_date"),
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


class CollectionCase(Base):
    """מקרה גבייה ידני — מעקב אחר לקוח שלא שילם (נפרד מהתזכורות האוטומטיות ב-
    CollectionReminder): ניסיונות (שיחה/מייל וכו') שנרשמים ידנית ע"י המשתמש, עם
    התקדמות סטטוס open -> promised -> paid, או escalated."""
    __tablename__ = "collection_cases"

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False)
    contact_id = Column(Integer, ForeignKey("contacts.id"), nullable=True)
    invoice_ids = Column(JSON, nullable=True)   # [invoice_id, ...]
    status = Column(String(20), default="open")  # open | promised | paid | escalated
    attempts = Column(JSON, nullable=True)       # [{"date": iso, "channel", "outcome", "notes"}]
    promise_date = Column(Date, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        Index("ix_collcase_org_contact", "organization_id", "contact_id"),
        Index("ix_collcase_org_status", "organization_id", "status"),
    )


class ChatMessage(Base):
    """הודעה בשיחת הצ'אטבוט (AI, שלב 9). role='assistant' רשומות שהציעו פעולת
    כתיבה (issue_document וכו') נושאות pending_action — הכלי לא בוצע, רק
    הוצע; ה-executed הופך True רק דרך אישור מפורש (ai_chat_service.confirm_action),
    שקורא בדיוק את tool/input שנשמרו כאן, לא נתון שהגיע מהלקוח."""
    __tablename__ = "ai_chat_messages"

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    session_id = Column(String(64), nullable=False)
    role = Column(String(20), nullable=False)  # user | assistant
    content = Column(Text, nullable=False)
    pending_action = Column(JSON, nullable=True)  # {"tool": str, "input": dict, "description": str}
    executed = Column(Boolean, default=False)
    # Durable confirmation state.  NULL remains a supported legacy value:
    # pending_action + executed=False + action_status=NULL is interpreted as
    # "pending" so an additive migration never strands existing proposals.
    action_status = Column(String(20), nullable=True)  # pending | executing | executed | cancelled | unknown
    action_claimed_at = Column(DateTime(timezone=True), nullable=True)
    action_completed_at = Column(DateTime(timezone=True), nullable=True)
    action_error = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        Index("ix_aichat_org_session", "organization_id", "session_id"),
        Index("ix_aichat_org_action_status", "organization_id", "action_status"),
    )


class LLMUsage(Base):
    """One immutable usage observation for one provider LLM request."""
    __tablename__ = "llm_usage"

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    session_id = Column(String(128), nullable=True)
    provider = Column(String(30), nullable=False)
    model = Column(String(120), nullable=False)
    input_tokens = Column(Integer, nullable=False, default=0)
    output_tokens = Column(Integer, nullable=False, default=0)
    cache_read_input_tokens = Column(Integer, nullable=True)
    cache_creation_input_tokens = Column(Integer, nullable=True)
    cost_usd = Column(Numeric(18, 8), nullable=True)
    purpose = Column(String(20), nullable=False)  # chat | vision | ocr
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        Index("ix_llm_usage_org_created", "organization_id", "created_at"),
        Index("ix_llm_usage_session", "session_id"),
    )


class MoshkoToolCall(Base):
    """Auditable execution of a Moshko tool (read and confirmed write)."""
    __tablename__ = "moshko_tool_calls"

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    session_id = Column(String(128), nullable=False)
    message_id = Column(Integer, ForeignKey("ai_chat_messages.id"), nullable=True)
    tool_name = Column(String(100), nullable=False)
    target_system = Column(String(30), nullable=False)
    arguments = Column(JSON, nullable=False, default=dict)
    succeeded = Column(Boolean, nullable=False)
    error = Column(Text, nullable=True)
    duration_ms = Column(Integer, nullable=False, default=0)
    result_size_bytes = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        Index("ix_moshko_tool_calls_org_created", "organization_id", "created_at"),
        Index("ix_moshko_tool_calls_session", "session_id"),
        Index("ix_moshko_tool_calls_target_success", "target_system", "succeeded"),
    )


class MoshkoFeedback(Base):
    """User-reported quality evidence and its human-reviewed correction.

    Question/answer snapshots are immutable evidence.  A correction is never
    global training data: promotion creates an approved, organization-scoped
    ``MoshkoMemory`` row and keeps the link for idempotency and audit.
    """
    __tablename__ = "moshko_feedback"

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    message_id = Column(Integer, ForeignKey("ai_chat_messages.id"), nullable=False)
    session_id = Column(String(64), nullable=False)
    channel = Column(String(20), nullable=False, default="web")
    category = Column(String(20), nullable=False)  # helpful | inaccurate | unknown | unsafe
    comment = Column(Text, nullable=True)
    question = Column(Text, nullable=True)
    answer = Column(Text, nullable=False)
    status = Column(String(20), nullable=False, default="open")
    correction = Column(Text, nullable=True)
    reviewed_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    promoted_memory_id = Column(Integer, ForeignKey("moshko_memory.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", "message_id", name="uq_moshko_feedback_user_message"),
        CheckConstraint(
            "category IN ('helpful','inaccurate','unknown','unsafe')",
            name="ck_moshko_feedback_category",
        ),
        CheckConstraint(
            "status IN ('open','reviewed','resolved','dismissed')",
            name="ck_moshko_feedback_status",
        ),
        Index("ix_moshko_feedback_org_status_created", "organization_id", "status", "created_at"),
        Index("ix_moshko_feedback_category_created", "category", "created_at"),
    )


class MoshkoGap(Base):
    """W1.1 — תור הכישלונות/פערי-היכולת של מושקו.

    כל כישלון — כלי שנפל, תשובת ויתור של המודל, או דגל משתמש — הופך
    שורה שהבעלים יכול לענות עליה: התשובה מקודמת לזיכרון מאושר
    (`MoshkoMemory`) או נפתחת כדרישת-יכולת. לעולם לא נכתב מתוך מסלול
    השיחה בצורה שמפילה אותה (best-effort בלבד).
    """
    __tablename__ = "moshko_gaps"

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    session_id = Column(String(128), nullable=False)
    message_id = Column(Integer, ForeignKey("ai_chat_messages.id"), nullable=True)
    question = Column(Text, nullable=True)
    answer = Column(Text, nullable=True)
    gap_kind = Column(String(30), nullable=False)  # tool_failed | model_gave_up | user_flagged
    tool_name = Column(String(100), nullable=True)
    error = Column(Text, nullable=True)
    status = Column(String(20), nullable=False, default="open")  # open | answered | dismissed
    resolution = Column(Text, nullable=True)
    promoted_memory_id = Column(Integer, ForeignKey("moshko_memory.id"), nullable=True)
    resolved_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    resolved_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    # W1.5 — regression runner: כשהשורה מקודמת לזיכרון (promoted_memory_id
    # לא-ריק) היא *הופכת* למקרה רגרסיה — אין טבלה נפרדת. שתי העמודות האלה
    # הן תוצאת ההרצה האחרונה בלבד; ריצה חדשה דורסת אותן.
    regression_status = Column(String(10), nullable=True)  # passed | failed
    regression_checked_at = Column(DateTime, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "gap_kind IN ('tool_failed','model_gave_up','user_flagged')",
            name="ck_moshko_gaps_kind",
        ),
        CheckConstraint(
            "status IN ('open','answered','dismissed')",
            name="ck_moshko_gaps_status",
        ),
        CheckConstraint(
            "regression_status IN ('passed','failed')",
            name="ck_moshko_gaps_regression_status",
        ),
        Index("ix_moshko_gaps_org_status_created", "organization_id", "status", "created_at"),
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
    # כרטיס באינדקס החשבונות של הארגון שאליו ההוצאה מתויקת. זה מה
    # שמחבר הוצאה שנכנסה ממודול העסק לאינדקס המיובא (חשבשבת/SUMIT),
    # ומאפשר להפיק דוחות מול אותם כרטיסים שההנה"ח עבדה מולם.
    # `category` נשאר תיאור חופשי; זה הקישור המבני.
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=True)
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
    # מע"מ תשומות *הנתבע* בפועל, אחרי שער-המסמך (israeli_tax_rules.claimable_vat)
    # — לעולם לא vat_amount (זה נשאר "raw", המע"מ שעל גבי המסמך, בכל שאר
    # המערכת). NULL = טרם הוכרע (honest-null) -> תור הכרעה, לא ניחוש; רק
    # financial_synthesis.select_vat_documents קורא את השדה הזה לצורך דיווח.
    vat_claimable = Column(Numeric(precision=12, scale=2), nullable=True)
    # סוג המסמך שמאחורי ההוצאה: "tax_invoice" (חשבונית מס — תשומות אפשריות),
    # "receipt" (קבלה בלבד — 0 תשומות תמיד), "unknown"/NULL (לא הוכרע).
    doc_kind = Column(String(20), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    organization = relationship("Organization")
    supplier = relationship("Contact")

    __table_args__ = (
        Index("ix_expense_org_status", "organization_id", "status"),
        # W6.4: ייחודי כשיש external_id (partial) — היה לא-unique בכלל.
        Index(
            "ix_expense_org_ext", "organization_id", "external_id", "source",
            unique=True,
            postgresql_where=text("external_id IS NOT NULL"),
            sqlite_where=text("external_id IS NOT NULL"),
        ),
    )


class VehicleProfile(Base):
    """פרופיל רכב — עיקר-השימוש הוא עובדה **פר-רכב**, לא פר-עסק (KB02 §1).
    בלי פרופיל תואם, ניכוי מע"מ תשומות רכב חייב להישאר None (הכרעה) —
    israeli_tax_rules.claimable_vat אינו מנחש 2/3 מול 1/4."""
    __tablename__ = "vehicle_profiles"

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    label = Column(String(120), nullable=False)  # שם/כינוי לזיהוי הרכב (מספר רישוי/דגם)
    vehicle_kind = Column(String(20), nullable=False, default="private")
    # private | commercial | taxi | rental | driving_school | dealer_stock — חריגי תקנה 14
    primarily_business = Column(Boolean, nullable=True)  # None = לא ידוע -> הכרעה
    attached_to_employee_with_use_value = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    organization = relationship("Organization")


class ExpenseCategory(Base):
    """קטגוריית הוצאה מותאמת אישית לארגון ("כרטיס") — משלימה את הקטגוריות
    המובנות (VALID_CATEGORIES ב-expense_classifier.py). המשתמש פותח כרטיסים
    לפי הצורך שלו; keywords (אופציונלי) מזינים את המסווג האוטומטי וגוברים
    על מילות המפתח המובנות."""
    __tablename__ = "expense_categories"

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    key = Column(String(100), nullable=False)  # slug, ייחודי בתוך הארגון
    name_he = Column(String(255), nullable=False)
    keywords = Column(JSON, nullable=True)  # list[str], אופציונלי — לסיווג אוטומטי
    created_at = Column(DateTime, default=datetime.utcnow)

    organization = relationship("Organization")

    __table_args__ = (
        Index("ix_expensecat_org_key", "organization_id", "key", unique=True),
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
    # Open Finance data is provisional/unverified until the consent journey
    # (OPEN_FINANCE_USER_ID + real bank consent) is fully live — see the
    # principle documented in PRODUCT_AUDIT_AND_ROADMAP.md's preamble.
    is_provisional = Column(Boolean, default=False)
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
        # W6.4: 15K פקודות נסרקו מלא בכל סינון תקופה (OPENFRMT/דוחות).
        Index("ix_je_org_entry_date", "organization_id", "entry_date"),
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


class VehicleDeductionProfile(Base):
    """Real per-vehicle, per-tax-year inputs for the Israeli vehicle-expense
    higher-of deduction rule (תקנות מס הכנסה (ניכוי הוצאות רכב) התשנ"ה-1995).

    These are facts about the vehicle/tax-year, not about any single receipt —
    odometer readings and שווי שימוש come from the vehicle's registration and
    the Tax Authority's own price-group table, not from any expense line-item.
    See services/expense_deduction_service.py for the calculator that reads
    these and never fabricates a deduction when a required field is missing.
    """
    __tablename__ = "vehicle_deduction_profiles"

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False)
    tax_year = Column(Integer, nullable=False)
    vehicle_label = Column(String(100), nullable=True)  # e.g. license plate, free text
    running_costs_annual = Column(Numeric(precision=12, scale=2), nullable=True)
    use_value_monthly = Column(Numeric(precision=12, scale=2), nullable=True)  # שווי שימוש
    odometer_start = Column(Numeric(precision=10, scale=1), nullable=True)
    odometer_end = Column(Numeric(precision=10, scale=1), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    organization = relationship("Organization")

    __table_args__ = (
        UniqueConstraint("organization_id", "tax_year", "vehicle_label", name="uq_vehicle_deduction_profile"),
    )


class HomeOfficeProfile(Base):
    """Real home-office area inputs for the proportional home-office/internet
    deduction rule. One active profile per organization."""
    __tablename__ = "home_office_profiles"

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, unique=True)
    office_sqm = Column(Numeric(precision=8, scale=2), nullable=False)
    total_home_sqm = Column(Numeric(precision=8, scale=2), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

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


class FilingCrosscheck(Base):
    """הקלדת ערכי מע"מ (תשומות/עסקאות) מתוך ספרי SUMIT (תיק ההנה"ח בפורטל
    המשרד) לתקופת דיווח נתונה — ההרגל השלישי של האימות המשולש: הצלבה
    *מוקלטת* מול המקור החיצוני האמיתי, במקום "הצלבה ידנית" סתמית שאינה
    נבדקת בפועל (ראה docs/audits/2026-07-13-eliav-pcn-three-way-reconciliation.md,
    ממצא 6 — הפער בין דוח 1,966 ל-37,884 בתיק לא היה מתגלה בלי הצלבה חיצונית).

    ייחודי פר (ארגון, תקופה, בסיס) — הקלדה חוזרת לאותה תקופה מעדכנת (upsert),
    לא יוצרת שורה כפולה.
    """
    __tablename__ = "filing_crosschecks"

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False)
    period = Column(String(20), nullable=False)   # לדוגמה "2026-05" או "2026-05_2026-06"
    basis = Column(String(20), nullable=False)    # "document" | "captured"
    books_input_vat = Column(Numeric(precision=12, scale=2), nullable=False)
    books_output_vat = Column(Numeric(precision=12, scale=2), nullable=True)
    source = Column(String(50), default="manual")  # מקור ההקלדה (ידני כרגע; API עתידי)
    noted_by = Column(String(255), nullable=True)  # מי הקליד (שם/מייל חופשי)
    created_at = Column(DateTime, default=datetime.utcnow)

    organization = relationship("Organization")

    __table_args__ = (
        UniqueConstraint("organization_id", "period", "basis",
                          name="uq_filing_crosscheck_period_basis"),
    )


class ChannelIdentity(Base):
    """זהות ערוץ שיחה חיצוני (טלגרם, ולעתיד וואטסאפ) המקושרת למשתמש+ארגון
    ברצף. הקישור מתבצע אך ורק דרך קוד חד-פעמי שהונפק למשתמש מאומת JWT
    (ChannelLinkCode) — אין זיהוי לפי מספר טלפון, אפס סיסמאות בצ'אט (הכרעה 6,
    docs/superpowers/plans/2026-07-26-conversational-channels-personas.md)."""
    __tablename__ = "channel_identities"

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    provider = Column(String(20), nullable=False)  # "telegram"
    external_id = Column(String(64), nullable=False)  # chat_id/user_id של הערוץ, כמחרוזת
    display_name = Column(String(120), nullable=True)
    default_persona = Column(String(20), default="cfo")
    verified_at = Column(DateTime, nullable=True)
    revoked_at = Column(DateTime, nullable=True)
    created_at = Column(
        DateTime, default=datetime.utcnow, nullable=False, server_default=func.now(),
    )

    # --- package B (2026-07-27 moshko-full-bot plan) — proactive push opt-in --- #
    # Nullable, default True, same pattern as Organization.morning_brief_email_enabled
    # above: a Python-side default= never reaches a raw-SQL backfill, so NULL must be
    # read as "not explicitly disabled" (channel_notifier.recipients_for does this via
    # push_enabled.isnot(False), not push_enabled.is_(True)).
    push_enabled = Column(Boolean, nullable=True, default=True)
    last_push_at = Column(DateTime, nullable=True)
    # Updated for every inbound WhatsApp event before routing. This is the
    # authoritative Meta 24-hour service-window clock; chat history cannot
    # substitute because media/persona/interactive messages may not create a
    # ChatMessage row.
    last_inbound_at = Column(DateTime(timezone=True), nullable=True)

    organization = relationship("Organization")

    __table_args__ = (
        UniqueConstraint("provider", "external_id", name="uq_channel_identity_provider_external"),
    )


class ChannelLinkCode(Base):
    """קוד קישור חד-פעמי (TTL 15 דקות) שמנפיק משתמש מאומת JWT באפליקציה,
    להקלדה בערוץ החיצוני (למשל /start <קוד> בטלגרם). ה-DB שומר רק hash
    (sha256) — הקוד הגלוי מוחזר פעם אחת בתשובת ה-API ולעולם לא נשמר בבירור."""
    __tablename__ = "channel_link_codes"

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    code_hash = Column(String(64), nullable=False, index=True)
    expires_at = Column(DateTime, nullable=False)
    used_at = Column(DateTime, nullable=True)
    created_at = Column(
        DateTime, default=datetime.utcnow, nullable=False, server_default=func.now(),
    )


class MoshkoMemory(Base):
    """זיכרון-לומד של מושקו — הפניית עיצוב Hermes Agent (שני scope בדיוק:
    עסק/משתמש), הזרקה קפואה לפרומפט (לא retrieval, אין vector DB), עם
    תקרת-תווים שכופה אוצרות (docs/superpowers/plans/
    2026-07-27b-moshko-memory-and-whatsapp.md, חבילה E). user_id=NULL =
    עובדה על העסק, גלויה לכל משתמשי הארגון; user_id מוגדר = זיכרון אישי,
    גלוי רק לבעליו. אין קשר ל-CfoMemory (org-only, ללא user_id, לא מגיע
    ל-LLM) — זו טבלה חדשה ונפרדת, לא מיחזור."""
    __tablename__ = "moshko_memory"

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    content = Column(Text, nullable=False)
    category = Column(String(30), nullable=True)  # preference | business_fact | correction | convention
    source = Column(String(50), nullable=True)  # conversation | admin | inferred
    approved_at = Column(DateTime, nullable=True)
    approved_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_used_at = Column(DateTime, nullable=True)

    organization = relationship("Organization")

    __table_args__ = (
        Index("ix_moshko_memory_org_user", "organization_id", "user_id"),
    )


class ChannelProcessedUpdate(Base):
    """Dedupe עדכוני webhook נכנסים לפי (provider, update_id) — מונע ריצה
    כפולה (ולכן עלות LLM כפולה) כשהערוץ החיצוני משדר retry על אותו עדכון
    (הכרעה 7). שורה קיימת = "כבר טופל", מוחזר 200 מיידי בלי לגעת ב-LLM."""
    __tablename__ = "channel_processed_updates"

    id = Column(Integer, primary_key=True)
    provider = Column(String(20), nullable=False)
    update_id = Column(String(64), nullable=False)
    created_at = Column(
        DateTime, default=datetime.utcnow, nullable=False, server_default=func.now(),
    )

    __table_args__ = (
        UniqueConstraint("provider", "update_id", name="uq_channel_processed_update"),
    )


class TenantDatabase(Base):
    """מיפוי ארגון → מסד ייעודי משלו (תוכנית ה-DB פר-ארגון, שלב 1).

    הטבלה יושבת במסד הבקרה, שהוא היחיד שיודע מי קיים. ארגון בלי שורה
    כאן — או עם שורה שאינה `active` — ממשיך לעבוד מול המסד המשותף, וכך
    הפיצול נעשה ארגון-אחד-בכל-פעם עם rollback לכל אחד בנפרד.

    `dsn_encrypted` הוא סוד ברמת קרדנשל ספק: הוא נושא שם משתמש וסיסמה
    למסד של לקוח. הוא מוצפן באותו מנגנון של `credentials_vault` ואינו
    מוחזר לעולם ברשימות תצוגה.
    """
    __tablename__ = "tenant_databases"

    id = Column(Integer, primary_key=True)
    organization_id = Column(
        Integer, ForeignKey("organizations.id"), nullable=False, unique=True
    )
    dsn_encrypted = Column(Text, nullable=False)
    provider = Column(String(30), nullable=False, default="neon")
    # active = מנותב; inactive = הופסק (למשל אחרי rollback) והתנועה חוזרת
    # למסד המשותף בלי שהרשומה נמחקת.
    status = Column(String(20), nullable=False, default="active")
    schema_revision = Column(String(64), nullable=True)
    last_verified_at = Column(DateTime, nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class KbChunk(Base):
    """אינדקס מרכז הידע — קטע אחד לכל סעיף במסמך KB רשום.

    **למה ב-DB ולא רק בקבצים.** `kb_loader.kb_search` סורק קבצי markdown
    בכל בקשה עם regex. ה-DB נותן אחזור אינדקסי (טריגרמים), ומאפשר גם
    תצוגה — לשאול "מה מושקו יודע" בלי לקרוא את הדיסק.

    **הרישום נשאר `kb_loader.KB_CENTERS`.** הטבלה נזרעת ממנו ואינה רישום
    שני — רישום כפול הוא בדיוק איך שמסמכים 07–11 נעשו בלתי-נראים.

    **אין embedding.** ל-Anthropic אין API של embeddings, וספק נוסף הוא
    עלות שלא אושרה. `content` נבדק לקסיקלית (`pg_trgm`; ל-PostgreSQL אין
    תצורת חיפוש-טקסט לעברית — אומת מול פרוד). עמודת embedding ריקה בלי
    כותב הייתה נקראת כיכולת קיימת, ולכן אינה כאן.

    **גלובלי ולא פר-ארגון בכוונה:** זהו ידע מקצועי (דיני מס, נהלים),
    לא נתוני לקוח. אין כאן `organization_id` — הוספתו הייתה מרמזת על
    בידוד שאינו רלוונטי ומכפילה את אותו תוכן פר ארגון.
    """
    __tablename__ = "kb_chunks"

    id = Column(Integer, primary_key=True)
    center_key = Column(String(64), nullable=False)
    filename = Column(String(255), nullable=False)
    section_index = Column(Integer, nullable=False)
    heading = Column(Text, nullable=False)
    content = Column(Text, nullable=False)
    title_he = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        # ייחודי פר (מרכז, קובץ, סעיף) — כך שזריעה חוזרת היא upsert ולא
        # שכפול. בלעדיו האינדקס היה גדל בכל פריסה וכל חיפוש היה מחזיר את
        # אותה פסקה שוב ושוב.
        UniqueConstraint(
            "center_key", "filename", "section_index",
            name="uq_kb_chunk_center_file_section",
        ),
        Index("ix_kb_chunk_center_file", "center_key", "filename"),
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

    @field_validator("password")
    @classmethod
    def _password_min_length(cls, value: str) -> str:
        """אורך מינימלי של 8 תווים — נאכף בסכימה, לא רק בנקודת קצה אחת."""
        if len(value) < 8:
            raise ValueError("הסיסמה חייבת להכיל לפחות 8 תווים")
        return value


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
