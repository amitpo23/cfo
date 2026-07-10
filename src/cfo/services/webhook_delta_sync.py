"""
Webhook-driven targeted delta sync (M1b).

Open Finance and SUMIT both support push notifications on entity changes.
This module turns those webhook deliveries into narrowly-scoped SyncEngine
runs (just the entity types affected) instead of relying solely on the
cron-driven full poll, so the local DB catches up quickly after a bank
connection completes or a SUMIT document is created/updated.

Design notes:
- Never raises. A webhook receiver must always be able to ack (200) so the
  sender doesn't retry-storm a payload we can't/won't process; every public
  function here catches its own exceptions and reports them in the result
  dict instead.
- Debounce is a module-level in-process dict keyed by (org_id, source). This
  is intentionally simple: on Vercel's process model each serverless
  invocation may be a fresh process (cold start resets the map), so this
  only suppresses bursts *within* a warm instance. That's an accepted
  trade-off for M1b — the underlying syncs are idempotent (payload_hash
  short-circuits unchanged records), so a missed debounce just costs an
  extra sync, never incorrect data.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Optional

from sqlalchemy.orm import Session

from ..models import BankTransaction, IntegrationConnection, Payment
from .credentials_vault import decrypt_credentials
from .sync_engine import SyncEngine, get_connector_for_org

logger = logging.getLogger(__name__)

# Re-delivery of the same event within this window is treated as a dup burst
# rather than a genuinely new event and is skipped.
DEBOUNCE_SECONDS = 120

# (organization_id, source) -> monotonic timestamp of the last handled event
# that triggered a sync. Module-level by design — see module docstring.
_last_handled: dict[tuple[int, str], float] = {}


def _debounced(org_id: int, source: str) -> bool:
    """Return True (and record the hit) if this (org, source) was handled
    within the debounce window; otherwise record now and return False."""
    key = (org_id, source)
    now = time.monotonic()
    last = _last_handled.get(key)
    if last is not None and (now - last) < DEBOUNCE_SECONDS:
        return True
    _last_handled[key] = now
    return False


def _resolve_of_org(db: Session, payload: dict) -> Optional[int]:
    """Resolve a local organization_id for an Open Finance webhook payload.

    Match the OF ``userId`` against the ``user_id`` stored in an org's
    open_finance IntegrationConnection credentials (mirrors
    ``_resolve_org_from_of_user`` in api/routes/open_finance.py). Falls back
    to organization 1 (this integration's default org) when there's no
    userId or no match — deliberately NOT "the first configured open_finance
    connection": routing an unattributable event to an arbitrary tenant would
    silently run a sync against the wrong org's data.
    """
    of_user_id = payload.get("userId") or payload.get("UserId")
    if of_user_id:
        rows = db.query(IntegrationConnection).filter(
            IntegrationConnection.source == "open_finance",
        ).all()
        for conn in rows:
            creds = decrypt_credentials(conn.credentials_encrypted) or {}
            if creds.get("user_id") and str(creds["user_id"]) == str(of_user_id):
                return conn.organization_id
    return 1


def _resolve_sumit_org(db: Session, payload: dict) -> Optional[int]:
    """Resolve a local organization_id for a SUMIT trigger payload.

    SUMIT trigger deliveries don't carry our organization_id; the only
    cross-reference available is the SUMIT company id, if the payload
    carries one, matched against the org's stored SUMIT credentials. Falls
    back to organization 1 when there's no company id or no match —
    deliberately NOT "the first configured sumit connection" (see
    _resolve_of_org for why an arbitrary-tenant fallback is unsafe).
    """
    company_id = (
        payload.get("CompanyID") or payload.get("companyId") or payload.get("company_id")
    )
    if company_id:
        rows = db.query(IntegrationConnection).filter(
            IntegrationConnection.source == "sumit",
        ).all()
        for conn in rows:
            creds = decrypt_credentials(conn.credentials_encrypted) or {}
            if creds.get("company_id") and str(creds["company_id"]) == str(company_id):
                return conn.organization_id
    return 1


async def _run_targeted_sync(
    db: Session, org_id: int, source: str, entity_types: list[str],
) -> dict:
    connector, connection_id, resolved_source = get_connector_for_org(
        db, org_id, preferred_source=source,
    )
    engine = SyncEngine(db, connector, org_id, resolved_source, connection_id=connection_id)
    sync_run = await engine.run_full_sync(entity_types=entity_types)
    status = sync_run.status
    return {
        "sync_run_id": sync_run.id,
        "status": status.value if hasattr(status, "value") else status,
        "counts": sync_run.counts,
    }


def _record_payment_event(db: Session, org_id: int, payment_id: str, payload: dict) -> bool:
    """Merge a payment-status webhook event into a matching Payment or
    BankTransaction's raw_data (matched by external_id == payment_id, scoped
    to the org). Returns True if a match was found and updated."""
    row = (
        db.query(Payment)
        .filter(Payment.organization_id == org_id, Payment.external_id == str(payment_id))
        .first()
    )
    if row is None:
        row = (
            db.query(BankTransaction)
            .filter(
                BankTransaction.organization_id == org_id,
                BankTransaction.external_id == str(payment_id),
            )
            .first()
        )
    if row is None:
        return False
    row.raw_data = {**(row.raw_data or {}), "webhook_event": payload}
    db.commit()
    return True


async def handle_open_finance_event(db: Session, payload: dict) -> dict:
    """Turn an Open Finance webhook delivery into a targeted delta sync.

    - Connection status COMPLETED/ACTIVE -> targeted sync of accounts +
      bank_transactions for the resolved org.
    - Payment status change -> record against a matching Payment/
      BankTransaction (by external_id), or just log if no match.
    - Anything else / malformed payload -> {"handled": False, "reason": ...}
      without raising.
    """
    if not isinstance(payload, dict) or not payload:
        return {"handled": False, "reason": "empty_or_invalid_payload"}

    try:
        connection_status = payload.get("connectionStatus") or payload.get("ConnectionStatus")
        payment_status = payload.get("paymentStatus") or payload.get("PaymentStatus")

        if connection_status and str(connection_status).upper() in ("COMPLETED", "ACTIVE"):
            org_id = _resolve_of_org(db, payload)
            if org_id is None:
                return {"handled": False, "reason": "unresolvable_org"}
            if _debounced(org_id, "open_finance"):
                return {"handled": False, "reason": "debounced"}
            result = await _run_targeted_sync(
                db, org_id, "open_finance", ["accounts", "bank_transactions"],
            )
            return {"handled": True, "event": "connection_status", "org_id": org_id, **result}

        if payment_status:
            org_id = _resolve_of_org(db, payload)
            payment_id = payload.get("paymentId") or payload.get("PaymentId")
            matched = False
            if org_id is not None and payment_id:
                matched = _record_payment_event(db, org_id, payment_id, payload)
            logger.info(
                "Open Finance payment webhook: org=%s payment_id=%s status=%s matched=%s",
                org_id, payment_id, payment_status, matched,
            )
            return {
                "handled": True, "event": "payment_status", "org_id": org_id,
                "payment_id": payment_id, "status": payment_status, "matched": matched,
            }

        return {"handled": False, "reason": "unrecognized_event_type"}
    except Exception as e:  # noqa: BLE001 - webhook handlers must never raise
        logger.error("handle_open_finance_event failed: %s", e, exc_info=True)
        return {"handled": False, "reason": f"error: {type(e).__name__}: {e}"}


async def handle_sumit_trigger_event(db: Session, payload: dict) -> dict:
    """Turn a SUMIT trigger (subscribe/triggers) delivery into a targeted
    delta sync of invoices/bills/payments for the resolved org.

    SUMIT's trigger payload shape isn't rigidly fixed (make.com/Zapier-
    oriented), so recognition is best-effort: any of a document identifier
    field or a Create/Update/Document-ish TriggerType/Type marks this as a
    document-created/updated event.
    """
    if not isinstance(payload, dict) or not payload:
        return {"handled": False, "reason": "empty_or_invalid_payload"}

    try:
        event_type = (
            payload.get("TriggerType") or payload.get("Type")
            or payload.get("EventType") or payload.get("type") or ""
        )
        entity_id = (
            payload.get("EntityID") or payload.get("DocumentID")
            or payload.get("entity_id") or payload.get("document_id")
        )

        is_document_event = bool(entity_id) or any(
            token in str(event_type) for token in ("Create", "Update", "Document")
        )
        if not is_document_event:
            return {"handled": False, "reason": "unrecognized_event_type"}

        org_id = _resolve_sumit_org(db, payload)
        if org_id is None:
            return {"handled": False, "reason": "unresolvable_org"}
        if _debounced(org_id, "sumit"):
            return {"handled": False, "reason": "debounced"}

        result = await _run_targeted_sync(db, org_id, "sumit", ["invoices", "bills", "payments"])
        return {"handled": True, "event": "document_change", "org_id": org_id, **result}
    except Exception as e:  # noqa: BLE001 - webhook handlers must never raise
        logger.error("handle_sumit_trigger_event failed: %s", e, exc_info=True)
        return {"handled": False, "reason": f"error: {type(e).__name__}: {e}"}
