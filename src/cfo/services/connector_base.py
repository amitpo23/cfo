"""
Base connector interface for accounting system integrations.
All connectors (SUMIT, QuickBooks, Xero, etc.) implement this contract.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any, AsyncIterator, Optional
import logging

logger = logging.getLogger(__name__)


@dataclass
class NormalizedContact:
    external_id: str
    contact_type: str  # customer, vendor, both
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    tax_id: Optional[str] = None
    address: Optional[str] = None
    currency: str = "ILS"
    is_active: bool = True
    raw_data: Optional[dict] = None


@dataclass
class NormalizedAccount:
    external_id: str
    name: str
    account_type: str  # asset, liability, equity, revenue, expense, bank
    currency: str = "ILS"
    balance: Decimal = Decimal("0")
    raw_data: Optional[dict] = None


@dataclass
class NormalizedInvoice:
    external_id: str
    contact_external_id: Optional[str] = None
    invoice_number: Optional[str] = None
    issue_date: Optional[date] = None
    due_date: Optional[date] = None
    status: str = "draft"
    currency: str = "ILS"
    subtotal: Decimal = Decimal("0")
    tax: Decimal = Decimal("0")
    total: Decimal = Decimal("0")
    paid_amount: Decimal = Decimal("0")
    balance: Decimal = Decimal("0")
    line_items: Optional[list] = None
    raw_data: Optional[dict] = None


@dataclass
class NormalizedBill:
    external_id: str
    vendor_external_id: Optional[str] = None
    bill_number: Optional[str] = None
    issue_date: Optional[date] = None
    due_date: Optional[date] = None
    status: str = "draft"
    currency: str = "ILS"
    subtotal: Decimal = Decimal("0")
    tax: Decimal = Decimal("0")
    total: Decimal = Decimal("0")
    paid_amount: Decimal = Decimal("0")
    balance: Decimal = Decimal("0")
    line_items: Optional[list] = None
    raw_data: Optional[dict] = None


@dataclass
class NormalizedPayment:
    external_id: str
    invoice_external_id: Optional[str] = None
    bill_external_id: Optional[str] = None
    contact_external_id: Optional[str] = None
    payment_date: Optional[date] = None
    amount: Decimal = Decimal("0")
    currency: str = "ILS"
    method: Optional[str] = None
    reference: Optional[str] = None
    raw_data: Optional[dict] = None


@dataclass
class NormalizedBankTransaction:
    external_id: str
    account_external_id: Optional[str] = None
    transaction_date: Optional[date] = None
    description: Optional[str] = None
    amount: Decimal = Decimal("0")  # positive=inflow, negative=outflow
    currency: str = "ILS"
    raw_data: Optional[dict] = None


@dataclass
class NormalizedJournalEntry:
    external_id: str
    entry_date: Optional[date] = None
    memo: Optional[str] = None
    lines: Optional[list] = None  # [{account_external_id, debit, credit, description}]
    raw_data: Optional[dict] = None


@dataclass
class FetchResult:
    """Result from a paginated fetch operation"""
    items: list = field(default_factory=list)
    has_more: bool = False
    next_cursor: Optional[str] = None
    total_count: Optional[int] = None


class AccountingConnector(ABC):
    """
    Abstract base class for all accounting system connectors.
    Each connector must implement these methods to support
    incremental sync with pagination.
    """

    @abstractmethod
    async def test_connection(self) -> bool:
        """Test the API connection. Returns True if successful."""
        ...

    @abstractmethod
    async def fetch_accounts(
        self,
        updated_since: Optional[datetime] = None,
        cursor: Optional[str] = None,
        page_size: int = 100,
    ) -> FetchResult:
        """Fetch accounts (chart of accounts). Returns FetchResult with NormalizedAccount items."""
        ...

    @abstractmethod
    async def fetch_customers(
        self,
        updated_since: Optional[datetime] = None,
        cursor: Optional[str] = None,
        page_size: int = 100,
    ) -> FetchResult:
        """Fetch customers. Returns FetchResult with NormalizedContact items."""
        ...

    @abstractmethod
    async def fetch_vendors(
        self,
        updated_since: Optional[datetime] = None,
        cursor: Optional[str] = None,
        page_size: int = 100,
    ) -> FetchResult:
        """Fetch vendors. Returns FetchResult with NormalizedContact items."""
        ...

    @abstractmethod
    async def fetch_invoices(
        self,
        updated_since: Optional[datetime] = None,
        cursor: Optional[str] = None,
        page_size: int = 100,
    ) -> FetchResult:
        """Fetch invoices (AR). Returns FetchResult with NormalizedInvoice items."""
        ...

    @abstractmethod
    async def fetch_bills(
        self,
        updated_since: Optional[datetime] = None,
        cursor: Optional[str] = None,
        page_size: int = 100,
    ) -> FetchResult:
        """Fetch bills (AP). Returns FetchResult with NormalizedBill items."""
        ...

    @abstractmethod
    async def fetch_payments(
        self,
        updated_since: Optional[datetime] = None,
        cursor: Optional[str] = None,
        page_size: int = 100,
    ) -> FetchResult:
        """Fetch payments. Returns FetchResult with NormalizedPayment items."""
        ...

    @abstractmethod
    async def fetch_bank_transactions(
        self,
        updated_since: Optional[datetime] = None,
        cursor: Optional[str] = None,
        page_size: int = 100,
    ) -> FetchResult:
        """Fetch bank transactions. Returns FetchResult with NormalizedBankTransaction items."""
        ...

    @abstractmethod
    async def fetch_journal_entries(
        self,
        updated_since: Optional[datetime] = None,
        cursor: Optional[str] = None,
        page_size: int = 100,
    ) -> FetchResult:
        """Fetch journal entries. Returns FetchResult with NormalizedJournalEntry items."""
        ...

    async def close(self):
        """Clean up resources. Override if needed."""
        pass
