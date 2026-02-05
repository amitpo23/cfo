"""
Sync engine: orchestrates data ingestion from accounting connectors.
- Tracks each run in SyncRun table
- Idempotent upserts by external_id + source
- Payload hash for change detection
- Cursor-based resumption
- Reconciliation checks
"""
import hashlib
import json
import logging
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from ..models import (
    Account,
    AccountType,
    Alert,
    AlertSeverity,
    BankTransaction,
    Bill,
    BillStatus,
    Contact,
    ContactType,
    IntegrationConnection,
    Invoice,
    InvoiceStatus,
    JournalEntry,
    Payment,
    SyncRun,
    SyncStatus,
)
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


def _hash_payload(data: dict) -> str:
    """SHA-256 hash of JSON-serialized payload for change detection."""
    serialized = json.dumps(data, sort_keys=True, default=str)
    return hashlib.sha256(serialized.encode()).hexdigest()


class SyncEngine:
    """
    Orchestrates sync from an AccountingConnector into the local DB.
    Each run is logged in the SyncRun table.
    """

    def __init__(
        self,
        db: Session,
        connector: AccountingConnector,
        organization_id: int,
        source: str,
        connection_id: Optional[int] = None,
    ):
        self.db = db
        self.connector = connector
        self.org_id = organization_id
        self.source = source
        self.connection_id = connection_id

    async def run_full_sync(
        self,
        entity_types: Optional[list] = None,
    ) -> SyncRun:
        """
        Execute a full or partial sync.
        entity_types: list of types to sync, e.g. ["accounts","customers","invoices"]
                      None = sync all.
        """
        all_types = [
            "accounts", "customers", "vendors",
            "invoices", "bills", "payments",
            "bank_transactions", "journal_entries",
        ]
        types_to_sync = entity_types or all_types

        # Create SyncRun record
        sync_run = SyncRun(
            organization_id=self.org_id,
            connection_id=self.connection_id,
            source=self.source,
            sync_type="full" if not entity_types else "partial",
            entity_types=",".join(types_to_sync),
            status=SyncStatus.RUNNING,
            started_at=datetime.utcnow(),
            counts={},
        )
        self.db.add(sync_run)
        self.db.commit()
        self.db.refresh(sync_run)

        counts = {}
        errors = []

        for entity_type in types_to_sync:
            try:
                result = await self._sync_entity_type(entity_type)
                counts[entity_type] = result
            except Exception as e:
                logger.error("Sync failed for %s: %s", entity_type, e)
                errors.append({
                    "entity_type": entity_type,
                    "error": str(e),
                })
                counts[entity_type] = {"error": str(e)}

        # Update SyncRun
        has_errors = len(errors) > 0
        sync_run.status = SyncStatus.PARTIAL if has_errors else SyncStatus.COMPLETED
        if all(isinstance(c, dict) and "error" in c for c in counts.values()):
            sync_run.status = SyncStatus.FAILED
        sync_run.finished_at = datetime.utcnow()
        sync_run.counts = counts
        if errors:
            sync_run.error_summary = f"{len(errors)} entity types had errors"
            sync_run.error_details = errors

        # Update last_synced_at on connection
        if self.connection_id:
            conn = self.db.query(IntegrationConnection).get(self.connection_id)
            if conn:
                conn.last_synced_at = datetime.utcnow()

        self.db.commit()
        self.db.refresh(sync_run)

        return sync_run

    async def _sync_entity_type(self, entity_type: str) -> dict:
        """Sync a single entity type with pagination."""
        fetch_method = {
            "accounts": self.connector.fetch_accounts,
            "customers": self.connector.fetch_customers,
            "vendors": self.connector.fetch_vendors,
            "invoices": self.connector.fetch_invoices,
            "bills": self.connector.fetch_bills,
            "payments": self.connector.fetch_payments,
            "bank_transactions": self.connector.fetch_bank_transactions,
            "journal_entries": self.connector.fetch_journal_entries,
        }.get(entity_type)

        if not fetch_method:
            return {"error": f"Unknown entity type: {entity_type}"}

        upsert_method = {
            "accounts": self._upsert_account,
            "customers": self._upsert_customer,
            "vendors": self._upsert_vendor,
            "invoices": self._upsert_invoice,
            "bills": self._upsert_bill,
            "payments": self._upsert_payment,
            "bank_transactions": self._upsert_bank_transaction,
            "journal_entries": self._upsert_journal_entry,
        }[entity_type]

        created = 0
        updated = 0
        skipped = 0
        cursor = None

        while True:
            result: FetchResult = await fetch_method(cursor=cursor)

            for item in result.items:
                action = upsert_method(item)
                if action == "created":
                    created += 1
                elif action == "updated":
                    updated += 1
                else:
                    skipped += 1

            self.db.commit()

            if not result.has_more:
                break
            cursor = result.next_cursor

        return {"created": created, "updated": updated, "skipped": skipped}

    # ---- Upsert methods ----

    def _upsert_account(self, item: NormalizedAccount) -> str:
        existing = self.db.query(Account).filter(
            Account.organization_id == self.org_id,
            Account.external_id == item.external_id,
        ).first()

        account_type_map = {
            "asset": AccountType.ASSET,
            "liability": AccountType.LIABILITY,
            "equity": AccountType.EQUITY,
            "revenue": AccountType.REVENUE,
            "expense": AccountType.EXPENSE,
            "bank": AccountType.BANK,
            "accounts_receivable": AccountType.ACCOUNTS_RECEIVABLE,
            "accounts_payable": AccountType.ACCOUNTS_PAYABLE,
        }
        acct_type = account_type_map.get(item.account_type, AccountType.ASSET)

        if existing:
            existing.name = item.name
            existing.account_type = acct_type
            existing.balance = item.balance
            existing.currency = item.currency
            existing.updated_at = datetime.utcnow()
            return "updated"

        account = Account(
            organization_id=self.org_id,
            external_id=item.external_id,
            name=item.name,
            account_type=acct_type,
            balance=item.balance,
            currency=item.currency,
        )
        self.db.add(account)
        return "created"

    def _upsert_customer(self, item: NormalizedContact) -> str:
        return self._upsert_contact(item, ContactType.CUSTOMER)

    def _upsert_vendor(self, item: NormalizedContact) -> str:
        return self._upsert_contact(item, ContactType.VENDOR)

    def _upsert_contact(self, item: NormalizedContact, default_type: ContactType) -> str:
        payload_hash = _hash_payload(item.raw_data) if item.raw_data else None

        existing = self.db.query(Contact).filter(
            Contact.organization_id == self.org_id,
            Contact.external_id == item.external_id,
            Contact.source == self.source,
        ).first()

        if existing:
            if payload_hash and existing.payload_hash == payload_hash:
                return "skipped"
            existing.name = item.name
            existing.email = item.email
            existing.phone = item.phone
            existing.tax_id = item.tax_id
            existing.address = item.address
            existing.currency = item.currency
            existing.is_active = item.is_active
            existing.raw_data = item.raw_data
            existing.payload_hash = payload_hash
            existing.updated_at = datetime.utcnow()
            return "updated"

        contact_type_map = {
            "customer": ContactType.CUSTOMER,
            "vendor": ContactType.VENDOR,
            "both": ContactType.BOTH,
        }

        contact = Contact(
            organization_id=self.org_id,
            external_id=item.external_id,
            source=self.source,
            contact_type=contact_type_map.get(item.contact_type, default_type),
            name=item.name,
            email=item.email,
            phone=item.phone,
            tax_id=item.tax_id,
            address=item.address,
            currency=item.currency,
            is_active=item.is_active,
            raw_data=item.raw_data,
            payload_hash=payload_hash,
        )
        self.db.add(contact)
        return "created"

    def _upsert_invoice(self, item: NormalizedInvoice) -> str:
        payload_hash = _hash_payload(item.raw_data) if item.raw_data else None

        existing = self.db.query(Invoice).filter(
            Invoice.organization_id == self.org_id,
            Invoice.external_id == item.external_id,
            Invoice.source == self.source,
        ).first()

        # Resolve contact
        contact_id = None
        if item.contact_external_id:
            contact = self.db.query(Contact).filter(
                Contact.organization_id == self.org_id,
                Contact.external_id == item.contact_external_id,
                Contact.source == self.source,
            ).first()
            if contact:
                contact_id = contact.id

        status_map = {
            "draft": InvoiceStatus.DRAFT,
            "sent": InvoiceStatus.SENT,
            "paid": InvoiceStatus.PAID,
            "partially_paid": InvoiceStatus.PARTIALLY_PAID,
            "overdue": InvoiceStatus.OVERDUE,
            "void": InvoiceStatus.VOID,
            "cancelled": InvoiceStatus.CANCELLED,
        }
        status = status_map.get(item.status, InvoiceStatus.DRAFT)

        if existing:
            if payload_hash and existing.payload_hash == payload_hash:
                return "skipped"
            existing.contact_id = contact_id or existing.contact_id
            existing.invoice_number = item.invoice_number or existing.invoice_number
            existing.issue_date = item.issue_date
            existing.due_date = item.due_date
            existing.status = status
            existing.currency = item.currency
            existing.subtotal = item.subtotal
            existing.tax = item.tax
            existing.total = item.total
            existing.paid_amount = item.paid_amount
            existing.balance = item.balance
            existing.line_items = item.line_items
            existing.raw_data = item.raw_data
            existing.payload_hash = payload_hash
            existing.updated_at = datetime.utcnow()
            return "updated"

        invoice = Invoice(
            organization_id=self.org_id,
            external_id=item.external_id,
            source=self.source,
            contact_id=contact_id,
            invoice_number=item.invoice_number,
            issue_date=item.issue_date,
            due_date=item.due_date,
            status=status,
            currency=item.currency,
            subtotal=item.subtotal,
            tax=item.tax,
            total=item.total,
            paid_amount=item.paid_amount,
            balance=item.balance,
            line_items=item.line_items,
            raw_data=item.raw_data,
            payload_hash=payload_hash,
        )
        self.db.add(invoice)
        return "created"

    def _upsert_bill(self, item: NormalizedBill) -> str:
        payload_hash = _hash_payload(item.raw_data) if item.raw_data else None

        existing = self.db.query(Bill).filter(
            Bill.organization_id == self.org_id,
            Bill.external_id == item.external_id,
            Bill.source == self.source,
        ).first()

        # Resolve vendor
        vendor_id = None
        if item.vendor_external_id:
            vendor = self.db.query(Contact).filter(
                Contact.organization_id == self.org_id,
                Contact.external_id == item.vendor_external_id,
                Contact.source == self.source,
            ).first()
            if vendor:
                vendor_id = vendor.id

        status_map = {
            "draft": BillStatus.DRAFT,
            "received": BillStatus.RECEIVED,
            "approved": BillStatus.APPROVED,
            "paid": BillStatus.PAID,
            "partially_paid": BillStatus.PARTIALLY_PAID,
            "overdue": BillStatus.OVERDUE,
            "void": BillStatus.VOID,
        }
        status = status_map.get(item.status, BillStatus.RECEIVED)

        if existing:
            if payload_hash and existing.payload_hash == payload_hash:
                return "skipped"
            existing.vendor_id = vendor_id or existing.vendor_id
            existing.bill_number = item.bill_number or existing.bill_number
            existing.issue_date = item.issue_date
            existing.due_date = item.due_date
            existing.status = status
            existing.currency = item.currency
            existing.subtotal = item.subtotal
            existing.tax = item.tax
            existing.total = item.total
            existing.paid_amount = item.paid_amount
            existing.balance = item.balance
            existing.line_items = item.line_items
            existing.raw_data = item.raw_data
            existing.payload_hash = payload_hash
            existing.updated_at = datetime.utcnow()
            return "updated"

        bill = Bill(
            organization_id=self.org_id,
            external_id=item.external_id,
            source=self.source,
            vendor_id=vendor_id,
            bill_number=item.bill_number,
            issue_date=item.issue_date,
            due_date=item.due_date,
            status=status,
            currency=item.currency,
            subtotal=item.subtotal,
            tax=item.tax,
            total=item.total,
            paid_amount=item.paid_amount,
            balance=item.balance,
            line_items=item.line_items,
            raw_data=item.raw_data,
            payload_hash=payload_hash,
        )
        self.db.add(bill)
        return "created"

    def _upsert_payment(self, item: NormalizedPayment) -> str:
        payload_hash = _hash_payload(item.raw_data) if item.raw_data else None

        existing = self.db.query(Payment).filter(
            Payment.organization_id == self.org_id,
            Payment.external_id == item.external_id,
            Payment.source == self.source,
        ).first()

        if existing:
            if payload_hash and existing.payload_hash == payload_hash:
                return "skipped"
            existing.payment_date = item.payment_date or existing.payment_date
            existing.amount = item.amount
            existing.currency = item.currency
            existing.method = item.method
            existing.reference = item.reference
            existing.raw_data = item.raw_data
            existing.payload_hash = payload_hash
            return "updated"

        # Resolve invoice/bill references
        invoice_id = None
        bill_id = None
        contact_id = None

        if item.invoice_external_id:
            inv = self.db.query(Invoice).filter(
                Invoice.organization_id == self.org_id,
                Invoice.external_id == item.invoice_external_id,
                Invoice.source == self.source,
            ).first()
            if inv:
                invoice_id = inv.id

        if item.contact_external_id:
            c = self.db.query(Contact).filter(
                Contact.organization_id == self.org_id,
                Contact.external_id == item.contact_external_id,
                Contact.source == self.source,
            ).first()
            if c:
                contact_id = c.id

        payment = Payment(
            organization_id=self.org_id,
            external_id=item.external_id,
            source=self.source,
            invoice_id=invoice_id,
            bill_id=bill_id,
            contact_id=contact_id,
            payment_date=item.payment_date,
            amount=item.amount,
            currency=item.currency,
            method=item.method,
            reference=item.reference,
            raw_data=item.raw_data,
            payload_hash=payload_hash,
        )
        self.db.add(payment)
        return "created"

    def _upsert_bank_transaction(self, item: NormalizedBankTransaction) -> str:
        payload_hash = _hash_payload(item.raw_data) if item.raw_data else None

        existing = self.db.query(BankTransaction).filter(
            BankTransaction.organization_id == self.org_id,
            BankTransaction.external_id == item.external_id,
            BankTransaction.source == self.source,
        ).first()

        if existing:
            if payload_hash and existing.payload_hash == payload_hash:
                return "skipped"
            existing.transaction_date = item.transaction_date or existing.transaction_date
            existing.description = item.description
            existing.amount = item.amount
            existing.currency = item.currency
            existing.raw_data = item.raw_data
            existing.payload_hash = payload_hash
            return "updated"

        # Resolve account
        account_id = None
        if item.account_external_id:
            acct = self.db.query(Account).filter(
                Account.organization_id == self.org_id,
                Account.external_id == item.account_external_id,
            ).first()
            if acct:
                account_id = acct.id

        bank_tx = BankTransaction(
            organization_id=self.org_id,
            external_id=item.external_id,
            source=self.source,
            account_id=account_id,
            transaction_date=item.transaction_date,
            description=item.description,
            amount=item.amount,
            currency=item.currency,
            raw_data=item.raw_data,
            payload_hash=payload_hash,
        )
        self.db.add(bank_tx)
        return "created"

    def _upsert_journal_entry(self, item: NormalizedJournalEntry) -> str:
        payload_hash = _hash_payload(item.raw_data) if item.raw_data else None

        existing = self.db.query(JournalEntry).filter(
            JournalEntry.organization_id == self.org_id,
            JournalEntry.external_id == item.external_id,
            JournalEntry.source == self.source,
        ).first()

        if existing:
            if payload_hash and existing.payload_hash == payload_hash:
                return "skipped"
            existing.entry_date = item.entry_date or existing.entry_date
            existing.memo = item.memo
            existing.lines = item.lines
            existing.raw_data = item.raw_data
            existing.payload_hash = payload_hash
            return "updated"

        entry = JournalEntry(
            organization_id=self.org_id,
            external_id=item.external_id,
            source=self.source,
            entry_date=item.entry_date,
            memo=item.memo,
            lines=item.lines,
            raw_data=item.raw_data,
            payload_hash=payload_hash,
        )
        self.db.add(entry)
        return "created"


def get_connector_for_org(db: Session, organization_id: int) -> tuple:
    """
    Factory: returns (connector, connection_id, source) for the org's active integration.
    """
    from ..models import Organization

    org = db.query(Organization).get(organization_id)
    if not org:
        raise ValueError(f"Organization {organization_id} not found")

    # Check IntegrationConnection first
    conn = db.query(IntegrationConnection).filter(
        IntegrationConnection.organization_id == organization_id,
        IntegrationConnection.status == "active",
    ).first()

    if conn:
        source = conn.source
        creds = json.loads(conn.credentials_encrypted) if conn.credentials_encrypted else {}
    else:
        # Fall back to org-level credentials
        source = org.integration_type.value if org.integration_type else "manual"
        creds = org.api_credentials or {}

    if source == "sumit":
        from .sumit_connector import SumitConnector
        from ..config import settings
        api_key = creds.get("api_key") or settings.sumit_api_key
        company_id = creds.get("company_id") or settings.sumit_company_id
        if not api_key:
            raise ValueError("SUMIT API key not configured")
        connector = SumitConnector(api_key=api_key, company_id=company_id)
        return connector, conn.id if conn else None, source

    raise ValueError(f"No connector available for source: {source}")
