"""Dispatch local bank reconciliation matches to the official accounting source.

The CFO app is the hub: Open Finance supplies bank/card movements, SUMIT remains
the official accounting system. This service makes that boundary explicit by
tracking whether a local match was actually sent to SUMIT, failed, or is not
supported by the current connector.

Writing to SUMIT (a customer remark, see sumit_connector.post_bank_reconciliation)
is an external, irreversible action, so it is gated through
IrreversibleActionService — the same durable propose/approve/execute control
plane used by /api/open-finance/payments — instead of being fired directly.
Each eligible bank transaction gets its own `sumit_writeback` action request
(idempotency key `sumit-writeback:{org_id}:banktxn:{row.id}`), proposed by the
calling `actor`. An owner must separately approve it (POST
/api/approvals/{id}/approve) before a later dispatch run will actually call
SUMIT for that row — "zero autonomy on irreversible actions" per AGENTS.md.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy.orm import Session

from ..models import BankTransaction, Bill, Expense, Invoice, User
from . import bank_reconciliation
from .irreversible_action_service import IrreversibleActionService
from .sync_engine import get_connector_for_org


TERMINAL_DISPATCH_STATUSES = {"confirmed"}

# Action-request statuses that are terminal for our purposes (no further work
# happens on subsequent dispatch runs for that row).
_ACTION_DONE_STATUSES = {"executed", "verified"}
_ACTION_FAILED_STATUSES = {"failed", "verification_failed"}


async def dispatch_reconciliation_to_sumit(
    db: Session,
    organization_id: int,
    *,
    dry_run: bool = False,
    actor: Optional[User] = None,
) -> dict[str, Any]:
    """Run/persist local matching and dispatch matched rows to SUMIT if possible.

    If the SUMIT connector does not expose a write-back method, rows are marked
    `unsupported` instead of pretending the official accounting action happened.
    Rows whose matched document has no linked Contact are `unsupported` too —
    there is nothing in SUMIT to write a remark against (honest-null).

    Rows that DO have a contact go through the approval control plane: the
    first dispatch run proposes a `sumit_writeback` IrreversibleActionRequest
    and marks the row `pending_approval`; only once an owner approves it does
    a later dispatch run actually call SUMIT and mark the row `confirmed`
    (or `unsupported`/`failed` if rejected or if the call errors).
    """
    local = bank_reconciliation.reconcile_organization(db, organization_id, persist=True)
    matched_ids = [m["bank_txn_id"] for m in local["matches"]]
    if not matched_ids:
        return {
            "local_reconciliation": local,
            "dry_run": dry_run,
            "dispatched": 0,
            "confirmed": 0,
            "failed": 0,
            "unsupported": 0,
            "pending_approval": 0,
            "items": [],
        }

    rows = (
        db.query(BankTransaction)
        .filter(
            BankTransaction.organization_id == organization_id,
            BankTransaction.id.in_(matched_ids),
        )
        .all()
    )

    try:
        connector, _conn_id, source = get_connector_for_org(db, organization_id, "sumit")
    except Exception as exc:  # noqa: BLE001
        return _mark_all(
            db, rows, "failed", f"SUMIT not configured: {exc}", dry_run=dry_run,
            local=local,
        )

    post = getattr(connector, "post_bank_reconciliation", None)
    if not callable(post):
        return _mark_all(
            db, rows, "unsupported",
            "SUMIT connector has no bank reconciliation write-back endpoint configured",
            dry_run=dry_run,
            local=local,
            source=source,
        )

    action_service = IrreversibleActionService(db, organization_id) if actor is not None else None

    items: list[dict[str, Any]] = []
    for row in rows:
        if row.reconciliation_dispatch_status in TERMINAL_DISPATCH_STATUSES:
            items.append(_item(row, status=row.reconciliation_dispatch_status, skipped=True))
            continue

        payload = _build_payload(db, row)
        if dry_run:
            items.append({"bank_transaction_id": row.id, "status": "pending", "payload": payload})
            continue

        contact_external_id = (payload.get("matched_entity") or {}).get("contact_external_id")
        if not contact_external_id:
            row.reconciliation_dispatch_status = "unsupported"
            row.reconciliation_error = (
                "SUMIT bank-reconciliation write-back requires a contact linked "
                "to the matched document (no contact_external_id on the matched entity)"
            )
            items.append(_item(row, status="unsupported", error=row.reconciliation_error))
            continue

        if action_service is None:
            row.reconciliation_dispatch_status = "unsupported"
            row.reconciliation_error = (
                "SUMIT bank-reconciliation write-back requires an authenticated "
                "actor to propose the action for owner approval (zero-autonomy control plane)"
            )
            items.append(_item(row, status="unsupported", error=row.reconciliation_error))
            continue

        items.append(
            await _dispatch_one_via_control_plane(
                row, payload, actor=actor, action_service=action_service, post=post,
            )
        )

    if not dry_run:
        db.commit()

    return {
        "local_reconciliation": local,
        "dry_run": dry_run,
        "dispatched": sum(1 for i in items if i["status"] in {"confirmed", "pending"}),
        "confirmed": sum(1 for i in items if i["status"] == "confirmed"),
        "failed": sum(1 for i in items if i["status"] == "failed"),
        "unsupported": sum(1 for i in items if i["status"] == "unsupported"),
        "pending_approval": sum(1 for i in items if i["status"] == "pending_approval"),
        "items": items,
    }


async def _dispatch_one_via_control_plane(
    row: BankTransaction,
    payload: dict[str, Any],
    *,
    actor: User,
    action_service: IrreversibleActionService,
    post: Any,
) -> dict[str, Any]:
    """Propose/advance the `sumit_writeback` action for one bank transaction row.

    Idempotent: re-running this for the same row is safe at any stage — the
    idempotency key ties back to the same IrreversibleActionRequest, so a
    second dispatch run for a still-`proposed` row is a no-op, and a row whose
    action was already `executed`/`verified` is never re-sent to SUMIT.
    """
    idempotency_key = f"sumit-writeback:{row.organization_id}:banktxn:{row.id}"
    try:
        action = action_service.propose(
            proposed_by=actor,
            action_type="sumit_writeback",
            payload=payload,
            idempotency_key=idempotency_key,
            description=f"SUMIT bank-reconciliation write-back for bank transaction #{row.id}",
        )
    except Exception as exc:  # noqa: BLE001
        row.reconciliation_dispatch_status = "failed"
        row.reconciliation_error = f"{type(exc).__name__}: {exc}"
        return _item(row, status="failed", error=row.reconciliation_error)

    if action.status == "proposed":
        row.reconciliation_dispatch_status = "pending_approval"
        row.reconciliation_error = f"ממתין לאישור בעלים (IrreversibleActionRequest #{action.id})."
        return _item(row, status="pending_approval", approval_request_id=action.id)

    if action.status == "rejected":
        row.reconciliation_dispatch_status = "unsupported"
        row.reconciliation_error = action.error or "SUMIT write-back was rejected by the owner"
        return _item(
            row, status="unsupported", approval_request_id=action.id, error=row.reconciliation_error,
        )

    if action.status in _ACTION_DONE_STATUSES:
        # Already executed in a prior dispatch run — idempotent, never re-call SUMIT.
        row.reconciliation_dispatch_status = "confirmed"
        row.reconciliation_dispatched_at = row.reconciliation_dispatched_at or datetime.now(timezone.utc)
        row.external_reconciliation_id = action.provider_reference
        row.reconciliation_error = None
        return _item(row, status="confirmed", approval_request_id=action.id, skipped=True)

    if action.status in _ACTION_FAILED_STATUSES:
        row.reconciliation_dispatch_status = "failed"
        row.reconciliation_error = action.error or "SUMIT write-back failed"
        return _item(
            row, status="failed", approval_request_id=action.id, error=row.reconciliation_error,
        )

    if action.status != "approved":
        # Any other/unknown status: fail closed rather than silently succeed.
        row.reconciliation_dispatch_status = "failed"
        row.reconciliation_error = f"Unexpected sumit_writeback action status: {action.status}"
        return _item(
            row, status="failed", approval_request_id=action.id, error=row.reconciliation_error,
        )

    try:
        claimed = action_service.claim_approved_for_execution(
            action.id, action_type="sumit_writeback", submitted_payload=payload,
        )
        result = await post(claimed.payload)
        external_id = _external_id_from_result(result)
        action_service.mark_executed(
            action.id,
            provider_reference=external_id or f"remark:{claimed.id}",
            execution_result=result if isinstance(result, dict) else {"result": result},
        )
        row.reconciliation_dispatch_status = "confirmed"
        row.reconciliation_dispatched_at = datetime.now(timezone.utc)
        row.external_reconciliation_id = external_id
        row.reconciliation_error = None
        return _item(row, status="confirmed", approval_request_id=action.id, result=result)
    except NotImplementedError as exc:
        action_service.mark_failed(action.id, error=str(exc))
        row.reconciliation_dispatch_status = "unsupported"
        row.reconciliation_error = str(exc) or "SUMIT reconciliation write-back is not implemented"
        return _item(
            row, status="unsupported", approval_request_id=action.id, error=row.reconciliation_error,
        )
    except Exception as exc:  # noqa: BLE001
        current = action_service.get(action.id)
        if current is not None and current.status in {"executing", "executed"}:
            action_service.mark_failed(action.id, error=f"{type(exc).__name__}: {exc}")
        row.reconciliation_dispatch_status = "failed"
        row.reconciliation_error = f"{type(exc).__name__}: {exc}"
        return _item(
            row, status="failed", approval_request_id=action.id, error=row.reconciliation_error,
        )


def _mark_all(
    db: Session,
    rows: list[BankTransaction],
    status: str,
    error: str,
    *,
    dry_run: bool,
    local: dict[str, Any],
    source: str = "sumit",
) -> dict[str, Any]:
    items = []
    for row in rows:
        if not dry_run:
            row.reconciliation_dispatch_status = status
            row.reconciliation_error = error
        items.append(_item(row, status=status, error=error, source=source))
    if not dry_run:
        db.commit()
    return {
        "local_reconciliation": local,
        "dry_run": dry_run,
        "dispatched": 0,
        "confirmed": 0,
        "failed": len(items) if status == "failed" else 0,
        "unsupported": len(items) if status == "unsupported" else 0,
        "pending_approval": 0,
        "items": items,
    }


def _build_payload(db: Session, row: BankTransaction) -> dict[str, Any]:
    entity = _load_entity(db, row)
    return {
        "bank_transaction": {
            "id": row.id,
            "external_id": row.external_id,
            "source": row.source,
            "date": row.transaction_date.isoformat() if row.transaction_date else None,
            "amount": float(row.amount),
            "currency": row.currency,
            "description": row.description,
            "raw_data": row.raw_data,
        },
        "matched_entity": entity,
    }


_CONTACT_ATTR_BY_TYPE = {
    "invoice": "contact",
    "bill": "vendor",
    "expense": "supplier",
}

_DOCUMENT_NUMBER_ATTR_BY_TYPE = {
    "invoice": "invoice_number",
    "bill": "bill_number",
    "expense": "invoice_number",
}


def _load_entity(db: Session, row: BankTransaction) -> dict[str, Any]:
    model_by_type = {
        "invoice": Invoice,
        "bill": Bill,
        "expense": Expense,
    }
    model = model_by_type.get(row.matched_entity_type or "")
    if not model or not row.matched_entity_id:
        return {"type": row.matched_entity_type, "id": row.matched_entity_id}
    entity = db.query(model).filter(
        model.organization_id == row.organization_id,
        model.id == row.matched_entity_id,
    ).first()
    if entity is None:
        return {"type": row.matched_entity_type, "id": row.matched_entity_id, "missing": True}

    contact_attr = _CONTACT_ATTR_BY_TYPE.get(row.matched_entity_type or "")
    contact = getattr(entity, contact_attr, None) if contact_attr else None
    document_number_attr = _DOCUMENT_NUMBER_ATTR_BY_TYPE.get(row.matched_entity_type or "")

    return {
        "type": row.matched_entity_type,
        "id": entity.id,
        "external_id": getattr(entity, "external_id", None),
        "source": getattr(entity, "source", None),
        "amount": float(getattr(entity, "total", None) or getattr(entity, "amount", 0) or 0),
        "sumit_expense_id": getattr(entity, "sumit_expense_id", None),
        # Contact behind the matched document — the only thing SUMIT lets us
        # write a remark against. None when the document has no linked
        # Contact yet (honest-null, resolved downstream as `unsupported`).
        "contact_external_id": getattr(contact, "external_id", None) if contact else None,
        "document_number": getattr(entity, document_number_attr, None) if document_number_attr else None,
    }


def _external_id_from_result(result: Any) -> str | None:
    if isinstance(result, dict):
        for key in ("id", "ID", "reconciliation_id", "ReconciliationID", "RemarkID"):
            if result.get(key):
                return str(result[key])
    return None


def _item(row: BankTransaction, *, status: str, **extra: Any) -> dict[str, Any]:
    return {
        "bank_transaction_id": row.id,
        "matched_entity_type": row.matched_entity_type,
        "matched_entity_id": row.matched_entity_id,
        "status": status,
        **extra,
    }
