"""
Sync engine: orchestrates data ingestion from accounting connectors.
- Tracks each run in SyncRun table
- Idempotent upserts by external_id + source
- Payload hash for change detection
- Cursor-based resumption
- Reconciliation checks
"""
import asyncio
import hashlib
import json
import logging
import random
import re
import zlib
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from ..config import settings
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
    SyncCheckpoint,
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

from .credentials_vault import decrypt_credentials

logger = logging.getLogger(__name__)

# Sentinel entity_type for source-level (not per-entity) SyncCheckpoint state:
# the manual-refresh cooldown and the Open-Finance daily-full-sync budget gate.
SOURCE_CHECKPOINT_ENTITY = "__source__"

# Error classification for the call-protection circuit breaker (RSF-026/027).
# Matches connector error strings like "SUMIT API error 403: ..." or
# "Open Finance API error 401: ..." (see sumit_integration.py / open_finance_client.py),
# plus generic auth/quota/IP-block keywords. Anchored to "api error <code>" (not a
# bare \b403\b) so a 403 appearing inside payload text/IDs can't false-positive.
_API_ERROR_CODE_RE = re.compile(r"api error\s+(\d{3})", re.IGNORECASE)
_BREAKING_KEYWORDS_RE = re.compile(
    r"\bunauthorized\b|\bforbidden\b|\bquota\b|\bobligo\b|ip[-_ ]?block",
    re.IGNORECASE,
)
_TRANSIENT_KEYWORDS_RE = re.compile(
    r"\btimeout\b|\btimed out\b|connection reset",
    re.IGNORECASE,
)


def _classify_error(exc: Optional[BaseException], message: str) -> str:
    """Classify a fetch failure as "breaking" (auth/quota/IP-block -- never
    retry, open the circuit), "transient" (5xx -- retry with backoff), or
    "other" (leave to the existing per-run error aggregation, no special
    handling)."""
    status_code = getattr(exc, "status_code", None)
    if status_code is None:
        m = _API_ERROR_CODE_RE.search(message or "")
        if m:
            status_code = int(m.group(1))

    if status_code in (401, 403):
        return "breaking"
    if status_code is not None and 500 <= status_code < 600:
        return "transient"

    if _BREAKING_KEYWORDS_RE.search(message or ""):
        return "breaking"
    if _TRANSIENT_KEYWORDS_RE.search(message or ""):
        return "transient"
    return "other"


def _hash_payload(data: dict) -> str:
    """SHA-256 hash of JSON-serialized payload for change detection."""
    serialized = json.dumps(data, sort_keys=True, default=str)
    return hashlib.sha256(serialized.encode()).hexdigest()


class SyncSkipped:
    """Lightweight stand-in for a SyncRun, returned by run_full_sync when the
    cross-run advisory lock is held by another process. Deliberately NOT a
    SyncRun row (no id, no persisted status) so it can't be mistaken for a
    real completed/failed/partial run by /api/integration/status or anything
    else that reads the latest SyncRun for health signals."""

    def __init__(self, reason: str):
        self.id = None
        self.status = None
        self.counts = {}
        self.error_summary = f"skipped: {reason}"
        self.error_details = None
        self.started_at = None
        self.finished_at = None
        self.locked = True
        self.reason = reason


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

    # ---- Cross-run advisory lock (RSF-024) ----
    # Prevents two overlapping sync runs for the same (org, source) -- e.g. a
    # slow cron invocation still running when the next hourly tick fires, or a
    # manual "Refresh" click racing the scheduler. Postgres-only (session-level
    # pg_try_advisory_lock, explicitly released in a finally); on SQLite (all
    # tests, and any deploy without Postgres) there's no cross-process lock
    # primitive available, so we always proceed -- this must never block a
    # single-process/test environment.
    #
    # Deliberately NOT pg_advisory_xact_lock: that releases at transaction end,
    # and run_full_sync commits multiple times per run (SyncRun creation, each
    # page) -- an xact-scoped lock would let a second run in immediately after
    # the first commit. Also non-blocking (pg_try_, not pg_) so a serverless
    # cron invocation skips instantly instead of hanging behind another run.
    def _dialect_name(self) -> str:
        bind = self.db.get_bind() if hasattr(self.db, "get_bind") else getattr(self.db, "bind", None)
        return getattr(getattr(bind, "dialect", None), "name", "sqlite")

    def _lock_keys(self) -> tuple:
        source_hash = zlib.crc32(self.source.encode("utf-8")) & 0x7FFFFFFF
        return self.org_id, source_hash

    def _acquire_lock(self) -> bool:
        if self._dialect_name() != "postgresql":
            return True
        k1, k2 = self._lock_keys()
        acquired = self.db.execute(
            text("SELECT pg_try_advisory_lock(:k1, :k2)"), {"k1": k1, "k2": k2}
        ).scalar()
        return bool(acquired)

    def _release_lock(self) -> None:
        if self._dialect_name() != "postgresql":
            return
        k1, k2 = self._lock_keys()
        try:
            self.db.execute(text("SELECT pg_advisory_unlock(:k1, :k2)"), {"k1": k1, "k2": k2})
        except Exception as e:
            logger.warning("Failed to release sync advisory lock for org %s source %s: %s",
                            self.org_id, self.source, e)

    async def run_full_sync(
        self,
        entity_types: Optional[list] = None,
        updated_since: Optional[datetime] = None,
    ):
        """
        Execute a full or partial sync.
        entity_types: list of types to sync, e.g. ["accounts","customers","invoices"]
                      None = sync all.
        updated_since: if given, used as the watermark for every entity type in
                       this run (overrides the per-entity SyncCheckpoint watermark --
                       e.g. a webhook-triggered delta-sync for a known changed window).
                       If None (the common case), each entity type computes its own
                       watermark from SyncCheckpoint.last_success_at minus the
                       configured overlap window.

        Returns a SyncRun row, or a SyncSkipped stand-in if another run currently
        holds the cross-run lock for this (org, source).
        """
        if not self._acquire_lock():
            logger.info("Sync skipped for org %s source %s: lock held by another run",
                        self.org_id, self.source)
            return SyncSkipped("locked")

        try:
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
                started_at=datetime.now(timezone.utc),
                counts={},
            )
            self.db.add(sync_run)
            self.db.commit()
            self.db.refresh(sync_run)

            counts = {}
            errors = []
            any_partial = False

            for entity_type in types_to_sync:
                try:
                    result = await self._sync_entity_type(entity_type, updated_since=updated_since)
                    counts[entity_type] = result
                    if isinstance(result, dict) and result.get("status") == "PARTIAL":
                        any_partial = True
                except Exception as e:
                    logger.error("Sync failed for %s: %s", entity_type, e)
                    errors.append({
                        "entity_type": entity_type,
                        "error": str(e),
                    })
                    counts[entity_type] = {"error": str(e)}

            # Self-heal any invoice/bill left with a null contact_id/vendor_id from
            # before fetch_customers() was fixed to derive real customers from
            # documents instead of SUMIT's incomplete get_debt_report() (2026-07-04).
            # Cheap (indexed WHERE ... IS NULL scan) and safe to run every sync.
            try:
                counts["contact_backfill"] = {
                    **self.backfill_invoice_contacts(),
                    **self.backfill_bill_vendors(),
                }
            except Exception as e:
                logger.error("Contact backfill failed: %s", e)

            # Update SyncRun
            has_errors = len(errors) > 0
            sync_run.status = SyncStatus.PARTIAL if (has_errors or any_partial) else SyncStatus.COMPLETED
            if all(isinstance(c, dict) and "error" in c for c in counts.values()):
                sync_run.status = SyncStatus.FAILED
            sync_run.finished_at = datetime.now(timezone.utc)
            sync_run.counts = counts
            if errors:
                sync_run.error_summary = f"{len(errors)} entity types had errors"
                sync_run.error_details = errors

            # Update last_synced_at on connection
            if self.connection_id:
                conn = self.db.get(IntegrationConnection, self.connection_id)
                if conn:
                    conn.last_synced_at = datetime.now(timezone.utc)

            self.db.commit()
            self.db.refresh(sync_run)

            # Mark the source-level checkpoint's watermark only for a genuinely
            # successful, unfiltered full sync -- used by the Open Finance daily
            # budget gate (cron.py) to allow at most one such sync per interval.
            # A PARTIAL/FAILED run, or an explicit entity_types/updated_since
            # subset, must not count against (or reset) that budget.
            if not entity_types and updated_since is None and sync_run.status == SyncStatus.COMPLETED:
                self._touch_source_checkpoint()

            return sync_run
        finally:
            self._release_lock()

    def backfill_invoice_contacts(self) -> dict:
        """Re-resolve contact_id for existing invoices left null because their
        real customer wasn't in the Contact table yet when the invoice was
        synced (root cause: fetch_customers() used to derive customers from
        SUMIT's incomplete get_debt_report() instead of real documents --
        fixed 2026-07-04, see sumit_connector.py). A normal re-sync doesn't
        self-heal this: _upsert_invoice's payload_hash short-circuit skips an
        invoice whose underlying SUMIT document hasn't changed, so it never
        reaches the contact_id assignment even after the Contact row exists.
        Pure local-DB repair — no SUMIT calls, safe to run repeatedly.
        """
        fixed = 0
        candidates = self.db.query(Invoice).filter(
            Invoice.organization_id == self.org_id,
            Invoice.source == self.source,
            Invoice.contact_id.is_(None),
        ).all()
        for inv in candidates:
            cust_id = (inv.raw_data or {}).get("customer_id")
            if not cust_id:
                continue
            contact = self.db.query(Contact).filter(
                Contact.organization_id == self.org_id,
                Contact.external_id == str(cust_id),
                Contact.source == self.source,
            ).first()
            if contact:
                inv.contact_id = contact.id
                fixed += 1
        if fixed:
            self.db.commit()
        return {"invoices_fixed": fixed}

    def backfill_bill_vendors(self) -> dict:
        """Same repair as backfill_invoice_contacts, for Bill.vendor_id."""
        fixed = 0
        candidates = self.db.query(Bill).filter(
            Bill.organization_id == self.org_id,
            Bill.source == self.source,
            Bill.vendor_id.is_(None),
        ).all()
        for bill in candidates:
            vendor_id_raw = (bill.raw_data or {}).get("vendor_id") or (bill.raw_data or {}).get("customer_id")
            if not vendor_id_raw:
                continue
            vendor = self.db.query(Contact).filter(
                Contact.organization_id == self.org_id,
                Contact.external_id == str(vendor_id_raw),
                Contact.source == self.source,
            ).first()
            if vendor:
                bill.vendor_id = vendor.id
                fixed += 1
        if fixed:
            self.db.commit()
        return {"bills_fixed": fixed}

    # ---- SyncCheckpoint helpers (watermark / cursor / circuit breaker) ----

    def _get_or_create_checkpoint(self, entity_type: str) -> SyncCheckpoint:
        cp = self.db.query(SyncCheckpoint).filter(
            SyncCheckpoint.organization_id == self.org_id,
            SyncCheckpoint.source == self.source,
            SyncCheckpoint.entity_type == entity_type,
        ).first()
        if not cp:
            cp = SyncCheckpoint(
                organization_id=self.org_id, source=self.source, entity_type=entity_type,
            )
            self.db.add(cp)
            self.db.commit()
            self.db.refresh(cp)
        return cp

    def _touch_source_checkpoint(self) -> None:
        cp = self._get_or_create_checkpoint(SOURCE_CHECKPOINT_ENTITY)
        cp.last_success_at = datetime.utcnow()
        self.db.commit()

    @staticmethod
    def _circuit_is_open(cp: SyncCheckpoint) -> bool:
        return bool(cp.circuit_open_until and cp.circuit_open_until > datetime.utcnow())

    @staticmethod
    def _compute_watermark(cp: SyncCheckpoint) -> Optional[datetime]:
        if not cp.last_success_at:
            return None
        return cp.last_success_at - timedelta(days=settings.sync_overlap_days)

    def _record_entity_failure(self, cp: SyncCheckpoint, exc: BaseException) -> None:
        classification = _classify_error(exc, str(exc))
        if classification == "breaking":
            cp.consecutive_failures = (cp.consecutive_failures or 0) + 1
            cp.circuit_open_until = datetime.utcnow() + timedelta(hours=settings.sync_circuit_open_hours)
            logger.warning(
                "Circuit opened for org %s source %s entity %s until %s (failure #%s): %s",
                self.org_id, self.source, cp.entity_type, cp.circuit_open_until,
                cp.consecutive_failures, exc,
            )
        self.db.commit()

    async def _fetch_with_retry(self, fetch_method, updated_since, cursor) -> FetchResult:
        """Call a connector fetch_* method, retrying transient 5xx failures at
        most twice with jittered backoff (RSF-026). Auth/quota/IP-block ("breaking")
        and any other failure are surfaced immediately with zero retries -- SUMIT's
        hard 403 rate-limit must never be hammered (RSF-027)."""
        attempt = 0
        while True:
            try:
                result: FetchResult = await fetch_method(updated_since=updated_since, cursor=cursor)
            except Exception as exc:
                classification = _classify_error(exc, str(exc))
                if classification == "transient" and attempt < 2:
                    await self._retry_sleep(attempt, getattr(exc, "retry_after", None))
                    attempt += 1
                    continue
                raise

            if result.error:
                classification = _classify_error(None, result.error)
                if classification == "transient" and attempt < 2:
                    await self._retry_sleep(attempt, getattr(result, "retry_after", None))
                    attempt += 1
                    continue

            return result

    @staticmethod
    async def _retry_sleep(attempt: int, retry_after: Optional[float]) -> None:
        if retry_after:
            delay = float(retry_after)
        else:
            base = settings.sync_retry_base_delay_seconds
            delay = base * (2 ** attempt) + random.uniform(0, base)
        await asyncio.sleep(delay)

    async def _sync_entity_type(
        self,
        entity_type: str,
        updated_since: Optional[datetime] = None,
    ) -> dict:
        """Sync a single entity type with pagination, watermarking, a page cap,
        and circuit-breaker protection (RSF-022/023/025/026)."""
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

        cp = self._get_or_create_checkpoint(entity_type)

        if self._circuit_is_open(cp):
            return {
                "skipped_circuit_open": True,
                "circuit_open_until": cp.circuit_open_until.isoformat(),
                "consecutive_failures": cp.consecutive_failures,
            }

        effective_since = updated_since if updated_since is not None else self._compute_watermark(cp)

        created = 0
        updated = 0
        skipped = 0
        cursor = cp.cursor  # resume from a previous page-capped run, if any
        pages = 0
        page_capped = False
        max_pages = settings.sync_max_pages_per_entity

        try:
            while True:
                pages += 1
                if pages > max_pages:
                    page_capped = True
                    break

                result = await self._fetch_with_retry(fetch_method, effective_since, cursor)
                if result.error:
                    # The connector already logged the underlying exception; raising
                    # here routes it into run_full_sync's existing error aggregation
                    # (errors list / error_summary / SyncStatus.PARTIAL) instead of
                    # silently reporting 0 created/updated/skipped as if it succeeded.
                    raise RuntimeError(result.error)

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
        except Exception as exc:
            self._record_entity_failure(cp, exc)
            raise

        # Success (a page-capped stop is not a failure -- it's an intentional,
        # resumable early exit so one entity type can't loop unbounded against a
        # live API for an entire hour).
        cp.consecutive_failures = 0
        cp.circuit_open_until = None
        if page_capped:
            cp.cursor = cursor
        else:
            cp.cursor = None
            cp.last_success_at = datetime.utcnow()
        self.db.commit()

        out = {"created": created, "updated": updated, "skipped": skipped}
        if page_capped:
            out["status"] = "PARTIAL"
            out["reason"] = "page_cap_exceeded"
        return out

    # ---- Upsert methods ----

    def _upsert_account(self, item: NormalizedAccount) -> str:
        existing = self.db.query(Account).filter(
            Account.organization_id == self.org_id,
            Account.external_id == item.external_id,
            Account.source == self.source,
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
            existing.updated_at = datetime.now(timezone.utc)
            return "updated"

        account = Account(
            organization_id=self.org_id,
            external_id=item.external_id,
            source=self.source,
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
            existing.updated_at = datetime.now(timezone.utc)
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
            existing.allocation_number = item.allocation_number or existing.allocation_number
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
            existing.updated_at = datetime.now(timezone.utc)
            return "updated"

        invoice = Invoice(
            organization_id=self.org_id,
            external_id=item.external_id,
            source=self.source,
            contact_id=contact_id,
            invoice_number=item.invoice_number,
            allocation_number=item.allocation_number,
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
            existing.updated_at = datetime.now(timezone.utc)
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
            is_provisional=(self.source == "open_finance"),
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


def get_connector_for_org(
    db: Session,
    organization_id: int,
    preferred_source: Optional[str] = None,
) -> tuple:
    """
    Factory: returns (connector, connection_id, source) for the org's active integration.
    """
    from ..models import Organization

    org = db.get(Organization, organization_id)
    if not org:
        raise ValueError(f"Organization {organization_id} not found")

    # Check IntegrationConnection first
    conn_query = db.query(IntegrationConnection).filter(
        IntegrationConnection.organization_id == organization_id,
        IntegrationConnection.status == "active",
    )
    if preferred_source:
        conn_query = conn_query.filter(IntegrationConnection.source == preferred_source)
    # Deterministic pick when several sources are active and no preference
    # was given: oldest connection wins instead of arbitrary DB order.
    conn = conn_query.order_by(IntegrationConnection.id).first()

    if conn:
        source = conn.source
        creds = decrypt_credentials(conn.credentials_encrypted)
    else:
        # Fall back to org-level credentials
        source = preferred_source or (org.integration_type.value if org.integration_type else "manual")
        creds = org.api_credentials or {}

    # Env credentials belong to the default organization only — other
    # tenants must configure their own via /integration/{source}/configure.
    env_allowed = organization_id == 1

    if source == "sumit":
        from .sumit_connector import SumitConnector
        from ..config import settings
        api_key = creds.get("api_key") or (settings.sumit_api_key if env_allowed else None)
        company_id = creds.get("company_id") or (settings.sumit_company_id if env_allowed else None)
        if not api_key:
            from .data_sync_service import SumitNotConfiguredError
            raise SumitNotConfiguredError("SUMIT API key not configured")
        connector = SumitConnector(api_key=api_key, company_id=company_id)
        return connector, conn.id if conn else None, source

    if source == "open_finance":
        from .open_finance_connector import OpenFinanceConnector
        from ..config import settings

        client_id = creds.get("client_id") or (settings.open_finance_client_id if env_allowed else None)
        client_secret = creds.get("client_secret") or (settings.open_finance_client_secret if env_allowed else None)
        user_id = creds.get("user_id") or (settings.open_finance_user_id if env_allowed else None)
        api_base_url = creds.get("api_base_url") or settings.open_finance_api_base_url
        oauth_url = creds.get("oauth_url") or settings.open_finance_oauth_url

        missing = [
            name for name, value in {
                "OPEN_FINANCE_CLIENT_ID": client_id,
                "OPEN_FINANCE_CLIENT_SECRET": client_secret,
                "OPEN_FINANCE_USER_ID": user_id,
            }.items()
            if not value
        ]
        if missing:
            raise ValueError(f"Open Finance credentials not configured: {', '.join(missing)}")

        connector = OpenFinanceConnector(
            client_id=client_id,
            client_secret=client_secret,
            user_id=user_id,
            api_base_url=api_base_url,
            oauth_url=oauth_url,
        )
        return connector, conn.id if conn else None, source

    raise ValueError(f"No connector available for source: {source}")
