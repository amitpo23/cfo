"""Dispatch local bank reconciliation matches to the official accounting source.

The CFO app is the hub: Open Finance supplies bank/card movements, SUMIT remains
the official accounting system. This service makes that boundary explicit by
tracking unsupported writeback explicitly. A method discovered on a connector
does not authorize official posting; that requires a reviewed approval adapter.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from ..models import BankTransaction, Bill, Expense, Invoice, Payment
from . import bank_reconciliation
from .sync_engine import get_connector_for_org


TERMINAL_DISPATCH_STATUSES = {"confirmed"}


async def dispatch_reconciliation_to_sumit(
    db: Session,
    organization_id: int,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Run/persist local matching and dispatch matched rows to SUMIT if possible.

    If the SUMIT connector does not expose a write-back method, rows are marked
    `unsupported` instead of pretending the official accounting action happened.
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

    # A dynamically present connector method does not grant authority to post.
    # Wire a reviewed immutable-intent adapter before enabling this branch.
    return _mark_all(db, rows, "approval_required",
        "Official writeback requires an approved execution adapter and independent readback",
        dry_run=dry_run, local=local, source=source)


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
        if row.reconciliation_dispatch_status in TERMINAL_DISPATCH_STATUSES:
            items.append(_item(row, status=row.reconciliation_dispatch_status, skipped=True))
            continue
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
        "failed": sum(i["status"] == "failed" for i in items),
        "unsupported": sum(i["status"] == "unsupported" for i in items),
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


def _load_entity(db: Session, row: BankTransaction) -> dict[str, Any]:
    model_by_type = {
        "invoice": Invoice,
        "bill": Bill,
        "expense": Expense,
        "payment": Payment,
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
    return {
        "type": row.matched_entity_type,
        "id": entity.id,
        "external_id": getattr(entity, "external_id", None),
        "source": getattr(entity, "source", None),
        "amount": float(getattr(entity, "total", None) or getattr(entity, "amount", 0) or 0),
        "sumit_expense_id": getattr(entity, "sumit_expense_id", None),
    }


def _external_id_from_result(result: Any) -> str | None:
    if isinstance(result, dict):
        for key in ("id", "ID", "reconciliation_id", "ReconciliationID"):
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
