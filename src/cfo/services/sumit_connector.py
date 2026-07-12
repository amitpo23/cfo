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


# SUMIT מחזיר לעיתים קוד מטבע מספרי במקום ISO (אומת חי: 20 מסמכים עם "1"/"2";
# "1" על מסמכי ₪ רגילים, "2" על חיובי $99/$202 — מנויים דולריים).
_SUMIT_CURRENCY_CODES = {"1": "ILS", "2": "USD", "3": "EUR"}


def _normalize_currency(value) -> str:
    v = str(value or "ILS").strip()
    return _SUMIT_CURRENCY_CODES.get(v, v or "ILS")


def _derive_subtotal_tax(doc, total: Decimal) -> tuple[Decimal, Decimal]:
    """Derive (subtotal, tax) for a SUMIT document.

    SUMIT documents are VAT-inclusive. When the document exposes an explicit
    ``vat_amount`` we trust it; otherwise we recover the split deterministically
    via :func:`vat_utils.split_inclusive` instead of zeroing VAT (which would
    silently under-report VAT in the derived ledger / VAT report / P&L).
    """
    raw_vat = getattr(doc, "vat_amount", None)
    if raw_vat is None:
        from .vat_utils import split_inclusive
        doc_day = getattr(doc, "date", None)
        if not isinstance(doc_day, date):
            doc_day = date.today()
        return split_inclusive(total, doc_day)
    tax = Decimal(str(raw_vat or 0))
    raw_subtotal = getattr(doc, "subtotal", None)
    subtotal = Decimal(str(raw_subtotal)) if raw_subtotal is not None else (total - tax)
    return subtotal, tax


class SumitConnector(AccountingConnector):
    """
    Connector for SUMIT accounting system.
    Wraps the existing SumitIntegration and normalizes results.
    """

    def __init__(self, api_key: str, company_id: str):
        self.api_key = api_key
        self.company_id = company_id

    async def _get_client(self):
        # A fresh instance per call: every fetch method wraps the client in
        # `async with`, which closes the underlying httpx client on exit. A
        # cached instance would be closed by the first fetch and break every
        # subsequent one in the same sync run.
        from ..integrations.sumit_integration import SumitIntegration
        return SumitIntegration(
            api_key=self.api_key,
            company_id=self.company_id,
        )

    async def test_connection(self) -> bool:
        try:
            client = await self._get_client()
            async with client:
                result = await client.test_connection()
                return bool(result)
        except Exception as e:
            logger.error("SUMIT connection test failed: %s", e)
            return False

    async def list_stock(self):
        """Passthrough to SUMIT stock list (used by the inventory sync)."""
        client = await self._get_client()
        async with client:
            return await client.list_stock()

    async def add_expense(self, expense_request):
        """Passthrough: file an expense in SUMIT (used by expense filing)."""
        client = await self._get_client()
        async with client:
            return await client.add_expense(expense_request)

    async def list_documents(self, request):
        """Passthrough: list SUMIT documents (used by pending-expense sync)."""
        client = await self._get_client()
        async with client:
            return await client.list_documents(request)

    async def move_document_to_books(self, document_id: str):
        """Passthrough: finalize/approve a SUMIT draft document (file a pending expense)."""
        client = await self._get_client()
        async with client:
            return await client.move_document_to_books(document_id)

    async def cancel_document(self, document_id: str):
        """Passthrough: cancel a SUMIT document (used to replace an auto-scanned draft)."""
        client = await self._get_client()
        async with client:
            return await client.cancel_document(document_id)

    async def get_document_pdf(self, document_id: str) -> bytes:
        """Passthrough: fetch a document's scan/PDF (used by the OCR pipeline)."""
        client = await self._get_client()
        async with client:
            return await client.get_document_pdf(document_id)

    async def get_document_supplier(self, document_id: str):
        """Passthrough: resolve a document's supplier/customer name via getdetails."""
        client = await self._get_client()
        async with client:
            return await client.get_document_supplier(document_id)

    async def get_document_supplier_details(self, document_id: str):
        """Passthrough: resolve supplier name + tax id + VAT for a document."""
        client = await self._get_client()
        async with client:
            return await client.get_document_supplier_details(document_id)

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
        """Derive the customer roster from real invoice documents.

        Previously used SUMIT's get_debt_report() to discover customers — found
        via a live data-parity check (2026-07-04) to be badly incomplete (2
        generic "Unknown"-named debt rows for a company with 15 real, named,
        open invoices), because of a reverse-engineered DebitSource/CreditSource
        payload that only captures a narrow subset of debt (see get_debt_report's
        own docstring). SUMIT has no bulk "list all customers" endpoint (confirmed
        against the swagger spec), but list_documents() already returns the real
        customer_id + customer_name for every document — fetch_invoices() already
        uses the same customer_id as contact_external_id. Deriving customers from
        the same source keeps both in sync and fixes every invoice's contact_id
        silently resolving to None (ledger_service._upsert_invoice only sets
        contact_id when a matching Contact row already exists) whenever a real
        customer never happened to appear in the debt report.
        """
        try:
            client = await self._get_client()
            async with client:
                documents = await self._list_documents_all(client, "0", updated_since)

                contacts = []
                seen_ids = set()
                for doc in documents:
                    cust_id = str(doc.customer_id) if getattr(doc, "customer_id", None) else None
                    if not cust_id or cust_id in seen_ids:
                        continue
                    seen_ids.add(cust_id)

                    contacts.append(NormalizedContact(
                        external_id=cust_id,
                        contact_type="customer",
                        name=getattr(doc, "customer_name", None) or "Unknown",
                        raw_data=doc.__dict__ if hasattr(doc, "__dict__") else {},
                    ))

                return FetchResult(items=contacts, has_more=False)
        except Exception as e:
            logger.error("Failed to fetch customers from SUMIT: %s", e)
            return FetchResult(items=[], has_more=False, error=str(e))

    async def fetch_vendors(
        self,
        updated_since: Optional[datetime] = None,
        cursor: Optional[str] = None,
        page_size: int = 100,
    ) -> FetchResult:
        # SUMIT doesn't have a dedicated vendors endpoint
        # Vendors will be created from expense documents
        return FetchResult(items=[], has_more=False)

    async def _list_documents_all(self, client, type_code: str,
                                  updated_since: Optional[datetime],
                                  page_size: int = 200, max_pages: int = 500):
        """Fetch ALL SUMIT documents of one numeric type, paginating to the end.

        Two correctness fixes over a single capped call:
        - full sync (updated_since=None) reaches back years, not just 365 days, so
          earlier-in-the-year history is not silently dropped;
        - pages are walked until exhausted (SUMIT's default page size caps a single
          call at ~100), de-duplicated by document id, with guards against an
          offset that never advances.
        """
        from ..integrations.sumit_models import DocumentListRequest
        from datetime import timedelta
        # Found live (2026-07-04 data-parity check): this used to be
        # date.today() - timedelta(days=365), contradicting the docstring above
        # -- a real customer whose only invoices were from 2024 (>365 days back)
        # was silently invisible to every full sync. 10 years comfortably covers
        # any realistic business history without an unbounded/undated query.
        from_date = updated_since.date() if updated_since else date.today() - timedelta(days=3650)
        all_docs, seen, offset = [], set(), 0
        for _ in range(max_pages):
            page = await client.list_documents(DocumentListRequest(
                from_date=from_date, to_date=date.today(),
                document_types=[type_code], limit=page_size, offset=offset,
            ))
            if not page:
                break
            before = len(seen)
            for d in page:
                did = str(getattr(d, "id", "") or "")
                if did and did not in seen:
                    seen.add(did)
                    all_docs.append(d)
            offset += len(page)
            if len(seen) == before:  # offset ignored or nothing new — stop
                break
            if len(page) < page_size:  # genuine last (partial) page
                break
        return all_docs

    async def fetch_invoices(
        self,
        updated_since: Optional[datetime] = None,
        cursor: Optional[str] = None,
        page_size: int = 100,
    ) -> FetchResult:
        try:
            client = await self._get_client()
            async with client:
                # SUMIT income documents live under TWO numeric DocumentType codes:
                # 0 = Invoice (חשבונית מס) and 1 = InvoiceAndReceipt (חשבונית מס קבלה).
                # Both are VAT-bearing revenue documents. Live finding (2026-07-06, org
                # 439... / Omer-Oded): a 0-only filter silently dropped ₪124,605 of type-1
                # income. Fetch both, skip drafts, dedupe by document id.
                docs_0 = await self._list_documents_all(client, "0", updated_since)
                docs_1 = await self._list_documents_all(client, "1", updated_since)
                seen_ids: set = set()
                documents = []
                for doc in docs_0 + docs_1:
                    did = str(getattr(doc, "id", "") or "")
                    if did and did in seen_ids:
                        continue
                    seen_ids.add(did)
                    if str(getattr(doc, "status", "") or "").lower() == "draft":
                        continue  # טיוטה — לא נכנסת לספרים
                    documents.append(doc)

                invoices = []
                for doc in documents:
                    status = self._map_document_status(doc)
                    total = Decimal(str(doc.total or 0))
                    paid = Decimal(str(getattr(doc, "paid_amount", 0) or 0))
                    if status == "paid" and paid < total:
                        # SUMIT לא מאכלס paid_amount על מסמכים סגורים; בלי זה
                        # balance=total וחשבונית ששולמה נראית כחוב פתוח (גבייה שגויה).
                        paid = total

                    subtotal, tax = _derive_subtotal_tax(doc, total)
                    invoices.append(NormalizedInvoice(
                        external_id=str(doc.id),
                        contact_external_id=str(doc.customer_id) if doc.customer_id else None,
                        invoice_number=getattr(doc, "document_number", None),
                        allocation_number=getattr(doc, "allocation_number", None),
                        issue_date=doc.date if isinstance(doc.date, date) else None,
                        due_date=getattr(doc, "due_date", None),
                        status=status,
                        currency=_normalize_currency(getattr(doc, "currency", None)),
                        subtotal=subtotal,
                        tax=tax,
                        total=total,
                        paid_amount=paid,
                        balance=total - paid,
                        raw_data=doc.__dict__ if hasattr(doc, "__dict__") else {},
                    ))

                return FetchResult(items=invoices, has_more=False)
        except Exception as e:
            logger.error("Failed to fetch invoices from SUMIT: %s", e)
            return FetchResult(items=[], has_more=False, error=str(e))

    async def fetch_bills(
        self,
        updated_since: Optional[datetime] = None,
        cursor: Optional[str] = None,
        page_size: int = 100,
    ) -> FetchResult:
        try:
            client = await self._get_client()
            async with client:
                # SUMIT expense documents live under TWO numeric DocumentType codes:
                # 15 = ExpenseReceipt (includes filed receipts AND pending scan drafts)
                # and 16 = ExpenseInvoice. Live parity audit (2026-07-05, org 439924597)
                # proved the real books are type 15 (274 docs in 2026) while type 16 is
                # nearly empty — the previous "16"-only filter (23353ca) would silently
                # freeze bill sync. Fetch both, skip drafts, dedupe by document id.
                docs_15 = await self._list_documents_all(client, "15", updated_since)
                docs_16 = await self._list_documents_all(client, "16", updated_since)
                seen_ids: set = set()
                documents = []
                for doc in docs_15 + docs_16:
                    did = str(getattr(doc, "id", "") or "")
                    if did and did in seen_ids:
                        continue
                    seen_ids.add(did)
                    if str(getattr(doc, "status", "") or "").lower() == "draft":
                        continue  # טיוטת סריקה — סכומים ריקים, לא חומר לספרים
                    documents.append(doc)

                bills = []
                for doc in documents:
                    # SUMIT מחזיר total שלילי (מוסכמת "כסף יוצא") לכל מסמכי הוצאה —
                    # אומת חי בפרוד: 730/730 מסמכים שליליים. גוזרים subtotal/tax על
                    # הגולמי (raw_total) כדי לכבד vat_amount מפורש אם קיים, ואז הופכים
                    # שלושתם יחד כך ש-subtotal+tax==total תמיד נשמר גם אחרי ההיפוך.
                    raw_total = Decimal(str(doc.total or 0))
                    raw_subtotal, raw_tax = _derive_subtotal_tax(doc, raw_total)
                    total = -raw_total
                    subtotal = -raw_subtotal
                    tax = -raw_tax

                    raw_paid = Decimal(str(getattr(doc, "paid_amount", 0) or 0))
                    paid = -raw_paid

                    doc_type = str(getattr(doc, "document_type", "") or "")
                    if doc_type == "15":
                        # ExpenseReceipt = חשבונית-מס-קבלה על הוצאה — שולמה מעצם
                        # טבעה (קבלה = אישור תשלום), אף פעם לא "לתשלום" ב-AP.
                        status = "paid"
                        paid = total
                        balance = Decimal("0")
                    else:
                        # type 16 (ExpenseInvoice) או סוג לא ידוע — פתוח עד תשלום מפורש
                        status = "received"
                        balance = total - paid

                    bills.append(NormalizedBill(
                        external_id=str(doc.id),
                        vendor_external_id=str(doc.customer_id) if doc.customer_id else None,
                        bill_number=getattr(doc, "document_number", None),
                        issue_date=doc.date if isinstance(doc.date, date) else None,
                        due_date=getattr(doc, "due_date", None),
                        status=status,
                        currency=_normalize_currency(getattr(doc, "currency", None)),
                        subtotal=subtotal,
                        tax=tax,
                        total=total,
                        paid_amount=paid,
                        balance=balance,
                        raw_data=doc.__dict__ if hasattr(doc, "__dict__") else {},
                    ))

                return FetchResult(items=bills, has_more=False)
        except Exception as e:
            logger.error("Failed to fetch bills from SUMIT: %s", e)
            return FetchResult(items=[], has_more=False, error=str(e))

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

                payments = []

                # (a) Billing-system payments (credit-card charges via /billing/payments).
                try:
                    raw_payments = await client.list_payments(
                        from_date=from_date,
                        to_date=date.today(),
                    )
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
                except Exception as e:
                    logger.warning("list_payments unavailable, continuing: %s", e)

                # (b) Receipt documents (SUMIT numeric DocumentType 5 = Receipt / קבלה):
                # collection events that close invoices. Stored negative; the payment
                # amount is the absolute value. Captured for AR/collection visibility.
                receipts = await self._list_documents_all(client, "5", updated_since)
                for doc in receipts:
                    amount = abs(Decimal(str(doc.total or 0)))
                    if amount == 0:
                        continue
                    payments.append(NormalizedPayment(
                        external_id=str(doc.id),
                        contact_external_id=str(doc.customer_id) if doc.customer_id else None,
                        payment_date=doc.date if isinstance(doc.date, date) else None,
                        amount=amount,
                        currency=_normalize_currency(getattr(doc, "currency", None)),
                        method="receipt",
                        reference=getattr(doc, "document_number", None),
                        raw_data=doc.__dict__ if hasattr(doc, "__dict__") else {},
                    ))

                return FetchResult(items=payments, has_more=False)
        except Exception as e:
            logger.error("Failed to fetch payments from SUMIT: %s", e)
            return FetchResult(items=[], has_more=False, error=str(e))

    async def fetch_bank_transactions(
        self,
        updated_since: Optional[datetime] = None,
        cursor: Optional[str] = None,
        page_size: int = 100,
    ) -> FetchResult:
        # `load_billing_transactions()` (creditguy/billing/load) is permanently
        # unsupported by the real SUMIT API (its own docstring says so) — it
        # fails identically for every org regardless of credential validity.
        # This ran a doomed network call to SUMIT on every hourly sync for every
        # connected org, wasting API quota for zero benefit (bank transactions
        # come from Open Finance instead — see open_finance_connector.py).
        # Returning empty locally, without a request, is behaviourally
        # identical to the old try/except-on-every-call path.
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
        # Each fetch method opens and closes its own client via `async with`.
        return None

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
