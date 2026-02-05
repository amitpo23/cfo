"""
SUMIT accounting connector implementation.
Maps SUMIT API responses to normalized data models.
"""
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Optional
import logging

from .connector_base import (
    AccountingConnector,
    FetchResult,
    NormalizedAccount,
    NormalizedBankTransaction,
    NormalizedBill,
    NormalizedContact,
    NormalizedInvoice,
    NormalizedJournalEntry,
    NormalizedPayment,
)

logger = logging.getLogger(__name__)


class SumitConnector(AccountingConnector):
    """
    Connector for SUMIT accounting system.
    Wraps the existing SumitIntegration and normalizes results.
    """

    def __init__(self, api_key: str, company_id: str):
        self.api_key = api_key
        self.company_id = company_id
        self._client = None

    async def _get_client(self):
        if self._client is None:
            from ..integrations.sumit_integration import SumitIntegration
            self._client = SumitIntegration(
                api_key=self.api_key,
                company_id=self.company_id,
            )
        return self._client

    async def test_connection(self) -> bool:
        try:
            client = await self._get_client()
            async with client:
                result = await client.test_connection()
                return bool(result)
        except Exception as e:
            logger.error("SUMIT connection test failed: %s", e)
            return False

    async def fetch_accounts(
        self,
        updated_since: Optional[datetime] = None,
        cursor: Optional[str] = None,
        page_size: int = 100,
    ) -> FetchResult:
        """SUMIT doesn't have a separate chart of accounts API.
        We synthesize accounts from document types and bank info."""
        # Return default accounts structure
        accounts = [
            NormalizedAccount(
                external_id="sumit_bank",
                name="Bank Account",
                account_type="bank",
                currency="ILS",
            ),
            NormalizedAccount(
                external_id="sumit_ar",
                name="Accounts Receivable",
                account_type="accounts_receivable",
                currency="ILS",
            ),
            NormalizedAccount(
                external_id="sumit_ap",
                name="Accounts Payable",
                account_type="accounts_payable",
                currency="ILS",
            ),
            NormalizedAccount(
                external_id="sumit_revenue",
                name="Revenue",
                account_type="revenue",
                currency="ILS",
            ),
            NormalizedAccount(
                external_id="sumit_expense",
                name="Expenses",
                account_type="expense",
                currency="ILS",
            ),
        ]
        return FetchResult(items=accounts, has_more=False)

    async def fetch_customers(
        self,
        updated_since: Optional[datetime] = None,
        cursor: Optional[str] = None,
        page_size: int = 100,
    ) -> FetchResult:
        try:
            client = await self._get_client()
            async with client:
                # Use SUMIT's debt report to get customer list
                from ..integrations.sumit_models import DebtReportRequest
                debts = await client.get_debt_report(DebtReportRequest())

                contacts = []
                seen_ids = set()
                for debt in debts:
                    cust_id = str(debt.get("customer_id", debt.get("id", "")))
                    if not cust_id or cust_id in seen_ids:
                        continue
                    seen_ids.add(cust_id)

                    contacts.append(NormalizedContact(
                        external_id=cust_id,
                        contact_type="customer",
                        name=debt.get("customer_name", "Unknown"),
                        email=debt.get("email"),
                        phone=debt.get("phone"),
                        raw_data=debt,
                    ))

                return FetchResult(items=contacts, has_more=False)
        except Exception as e:
            logger.error("Failed to fetch customers from SUMIT: %s", e)
            return FetchResult(items=[], has_more=False)

    async def fetch_vendors(
        self,
        updated_since: Optional[datetime] = None,
        cursor: Optional[str] = None,
        page_size: int = 100,
    ) -> FetchResult:
        # SUMIT doesn't have a dedicated vendors endpoint
        # Vendors will be created from expense documents
        return FetchResult(items=[], has_more=False)

    async def fetch_invoices(
        self,
        updated_since: Optional[datetime] = None,
        cursor: Optional[str] = None,
        page_size: int = 100,
    ) -> FetchResult:
        try:
            client = await self._get_client()
            async with client:
                from ..integrations.sumit_models import DocumentListRequest

                from_date = (
                    updated_since.date()
                    if updated_since
                    else date.today() - timedelta(days=365)
                )

                request = DocumentListRequest(
                    from_date=from_date,
                    to_date=date.today(),
                    document_types=["invoice", "tax_invoice", "receipt", "credit_invoice"],
                )
                documents = await client.list_documents(request)

                invoices = []
                for doc in documents:
                    status = self._map_document_status(doc)
                    total = Decimal(str(doc.total or 0))
                    paid = Decimal(str(getattr(doc, "paid_amount", 0) or 0))

                    invoices.append(NormalizedInvoice(
                        external_id=str(doc.id),
                        contact_external_id=str(doc.customer_id) if doc.customer_id else None,
                        invoice_number=getattr(doc, "document_number", None),
                        issue_date=doc.date if isinstance(doc.date, date) else None,
                        due_date=getattr(doc, "due_date", None),
                        status=status,
                        currency=getattr(doc, "currency", "ILS") or "ILS",
                        subtotal=Decimal(str(getattr(doc, "subtotal", total))),
                        tax=Decimal(str(getattr(doc, "vat_amount", 0) or 0)),
                        total=total,
                        paid_amount=paid,
                        balance=total - paid,
                        raw_data=doc.__dict__ if hasattr(doc, "__dict__") else {},
                    ))

                return FetchResult(items=invoices, has_more=False)
        except Exception as e:
            logger.error("Failed to fetch invoices from SUMIT: %s", e)
            return FetchResult(items=[], has_more=False)

    async def fetch_bills(
        self,
        updated_since: Optional[datetime] = None,
        cursor: Optional[str] = None,
        page_size: int = 100,
    ) -> FetchResult:
        try:
            client = await self._get_client()
            async with client:
                from ..integrations.sumit_models import DocumentListRequest

                from_date = (
                    updated_since.date()
                    if updated_since
                    else date.today() - timedelta(days=365)
                )

                request = DocumentListRequest(
                    from_date=from_date,
                    to_date=date.today(),
                    document_types=["expense", "expense_invoice"],
                )
                documents = await client.list_documents(request)

                bills = []
                for doc in documents:
                    total = Decimal(str(doc.total or 0))
                    paid = Decimal(str(getattr(doc, "paid_amount", 0) or 0))

                    bills.append(NormalizedBill(
                        external_id=str(doc.id),
                        vendor_external_id=str(doc.customer_id) if doc.customer_id else None,
                        bill_number=getattr(doc, "document_number", None),
                        issue_date=doc.date if isinstance(doc.date, date) else None,
                        due_date=getattr(doc, "due_date", None),
                        status="received",
                        currency=getattr(doc, "currency", "ILS") or "ILS",
                        subtotal=Decimal(str(getattr(doc, "subtotal", total))),
                        tax=Decimal(str(getattr(doc, "vat_amount", 0) or 0)),
                        total=total,
                        paid_amount=paid,
                        balance=total - paid,
                        raw_data=doc.__dict__ if hasattr(doc, "__dict__") else {},
                    ))

                return FetchResult(items=bills, has_more=False)
        except Exception as e:
            logger.error("Failed to fetch bills from SUMIT: %s", e)
            return FetchResult(items=[], has_more=False)

    async def fetch_payments(
        self,
        updated_since: Optional[datetime] = None,
        cursor: Optional[str] = None,
        page_size: int = 100,
    ) -> FetchResult:
        try:
            client = await self._get_client()
            async with client:
                from_date = (
                    updated_since.date()
                    if updated_since
                    else date.today() - timedelta(days=365)
                )

                raw_payments = await client.list_payments(
                    from_date=from_date,
                    to_date=date.today(),
                )

                payments = []
                for p in raw_payments:
                    payments.append(NormalizedPayment(
                        external_id=str(p.id),
                        contact_external_id=str(getattr(p, "customer_id", None)),
                        payment_date=p.date if isinstance(p.date, date) else None,
                        amount=Decimal(str(p.amount or 0)),
                        currency=getattr(p, "currency", "ILS") or "ILS",
                        method=getattr(p, "payment_method", None),
                        reference=getattr(p, "reference", None),
                        raw_data=p.__dict__ if hasattr(p, "__dict__") else {},
                    ))

                return FetchResult(items=payments, has_more=False)
        except Exception as e:
            logger.error("Failed to fetch payments from SUMIT: %s", e)
            return FetchResult(items=[], has_more=False)

    async def fetch_bank_transactions(
        self,
        updated_since: Optional[datetime] = None,
        cursor: Optional[str] = None,
        page_size: int = 100,
    ) -> FetchResult:
        try:
            client = await self._get_client()
            async with client:
                from ..integrations.sumit_models import BillingTransactionRequest

                from_date = (
                    updated_since.date()
                    if updated_since
                    else date.today() - timedelta(days=90)
                )

                request = BillingTransactionRequest(
                    from_date=from_date,
                    to_date=date.today(),
                )
                raw_txs = await client.load_billing_transactions(request)

                transactions = []
                for tx in raw_txs:
                    transactions.append(NormalizedBankTransaction(
                        external_id=str(tx.id),
                        transaction_date=tx.date if isinstance(tx.date, date) else None,
                        description=getattr(tx, "description", f"Card {getattr(tx, 'card_last_digits', 'XXXX')}"),
                        amount=Decimal(str(tx.amount or 0)),
                        currency=getattr(tx, "currency", "ILS") or "ILS",
                        raw_data=tx.__dict__ if hasattr(tx, "__dict__") else {},
                    ))

                return FetchResult(items=transactions, has_more=False)
        except Exception as e:
            logger.error("Failed to fetch bank transactions from SUMIT: %s", e)
            return FetchResult(items=[], has_more=False)

    async def fetch_journal_entries(
        self,
        updated_since: Optional[datetime] = None,
        cursor: Optional[str] = None,
        page_size: int = 100,
    ) -> FetchResult:
        # SUMIT doesn't expose journal entries directly
        return FetchResult(items=[], has_more=False)

    async def close(self):
        if self._client:
            try:
                await self._client.__aexit__(None, None, None)
            except Exception:
                pass
            self._client = None

    @staticmethod
    def _map_document_status(doc) -> str:
        """Map SUMIT document status to normalized invoice status."""
        raw_status = getattr(doc, "status", "").lower()
        doc_type = getattr(doc, "document_type", "").lower()

        if raw_status in ("paid", "closed"):
            return "paid"
        if raw_status in ("cancelled", "canceled"):
            return "cancelled"
        if raw_status == "void":
            return "void"
        if raw_status == "draft":
            return "draft"

        # Check if overdue based on due_date
        due = getattr(doc, "due_date", None)
        if due and isinstance(due, date) and due < date.today():
            return "overdue"

        if doc_type in ("receipt",):
            return "paid"

        return "sent"
