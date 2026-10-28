"""Local provider status for a dashboard, and the confirmation gate in front of a call.

Reading status and creating a workspace never build a SUMIT or Open Finance
client. A confirmed click records the approval and still does not call a
provider: this screen is not a second sync path. The shared monthly ceiling
shown here is the live account cap (50), counted from the local budget row.
"""
from __future__ import annotations

from ...models import AuditLog, BankConnection, IntegrationConnection
from ..sumit_request_budget import LIVE_ACCOUNT_REQUEST_HARD_CAP
from ..sumit_weekly_pull import quota_view
from .service import DashboardError

SUMIT_CONFIRMATION = "משוך מ-SUMIT"
OPEN_FINANCE_CONFIRMATION = "רענן Open Finance"
_CONNECTED_STATUSES = {"active", "env"}
_BANK_CONNECTED = {"ACTIVE", "CONNECTED", "COMPLETED", "VALID"}


def sumit_quota(db) -> dict:
    quota = quota_view(db)
    return {
        "limit": quota.limit,
        "used": quota.used,
        "remaining": quota.remaining,
        "live_shared_cap": LIVE_ACCOUNT_REQUEST_HARD_CAP,
        "shared": True,
    }


def provider_status(db, organization_id: int) -> dict:
    sumit = _connection(db, organization_id, "sumit")
    finance = _connection(db, organization_id, "open_finance")
    banks = (
        db.query(BankConnection)
        .filter_by(organization_id=organization_id)
        .order_by(BankConnection.id)
        .all()
    )
    finance_state = _integration_state(finance)
    finance_state["connected"] = finance_state["connected"] or any(_bank_connected(bank) for bank in banks)
    finance_state["bank_connections"] = len(banks)
    finance_state["last_refresh_at"] = _latest([bank.last_refresh_at for bank in banks])
    return {
        "organization_id": organization_id,
        "sumit": _integration_state(sumit),
        "open_finance": finance_state,
        "sumit_quota": sumit_quota(db),
        "confirmations": {
            "sumit": SUMIT_CONFIRMATION,
            "open_finance": OPEN_FINANCE_CONFIRMATION,
        },
        "provider_calls": 0,
    }


def confirm_sumit(db, user, row, confirmation: str) -> dict:
    if confirmation != SUMIT_CONFIRMATION:
        raise DashboardError(
            400, "confirmation_required", "משיכה מ-SUMIT יוצאת רק אחרי אישור מפורש",
        )
    result = place_sumit_call(db, user, row)
    result["sumit_quota"] = sumit_quota(db)
    result["provider_calls"] = int(result.get("provider_calls") or 0)
    return result


def confirm_open_finance_refresh(db, user, row, confirmation: str) -> dict:
    if confirmation != OPEN_FINANCE_CONFIRMATION:
        raise DashboardError(
            400, "confirmation_required", "רענון Open Finance יוצא רק אחרי אישור מפורש של מנהל",
        )
    result = place_open_finance_refresh(db, user, row)
    result["provider_calls"] = int(result.get("provider_calls") or 0)
    return result


def place_sumit_call(db, user, row) -> dict:
    """Record the approval. Do not construct a SUMIT client."""
    _record(db, user, row, "DASHBOARD_SUMIT_CONFIRMED")
    return {
        "executed": False,
        "provider_calls": 0,
        "message_he": "האישור נקלט. לא יצאה קריאה ל-SUMIT.",
    }


def place_open_finance_refresh(db, user, row) -> dict:
    """Record the approval. Do not construct an Open Finance client."""
    _record(db, user, row, "DASHBOARD_OPEN_FINANCE_REFRESH_CONFIRMED")
    return {
        "executed": False,
        "provider_calls": 0,
        "message_he": "האישור נקלט. לא יצא רענון ל-Open Finance.",
    }


def _record(db, user, row, action: str) -> None:
    db.add(AuditLog(
        user_id=user.id,
        organization_id=row.primary_organization_id,
        action=action,
        entity_type="ClientDashboard",
        entity_id=row.id,
        details={"provider_calls": 0, "executed": False},
    ))
    db.commit()


def _connection(db, organization_id: int, source: str):
    return (
        db.query(IntegrationConnection)
        .filter_by(organization_id=organization_id, source=source)
        .first()
    )


def _integration_state(row) -> dict:
    return {
        "connected": row is not None and (row.status or "").lower() in _CONNECTED_STATUSES,
        "status": row.status if row is not None and row.status else "missing",
        "last_synced_at": row.last_synced_at.isoformat() if row is not None and row.last_synced_at else None,
    }


def _bank_connected(bank) -> bool:
    return (bank.status or "").upper() in _BANK_CONNECTED


def _latest(values) -> str | None:
    present = [value for value in values if value is not None]
    if not present:
        return None
    return max(present).isoformat()
