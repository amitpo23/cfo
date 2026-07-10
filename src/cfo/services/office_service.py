"""
Accounting-office management — multi-company (ניהול משרד).

An office (one Organization) manages many client files (תיקים). Each client file is
its own Organization tenant with its **own** encrypted credentials in
`IntegrationConnection` (separate SUMIT api_key/company_id, and optionally Open
Finance), so every client authenticates independently. A `SumitCompany` row is the
office's roster entry linking the office to each client tenant.

This module provides the office-manager capabilities:
  * register_client   — provision a client file with its own authentication
  * list_clients      — the office roster + per-client status
  * office_rollup     — cross-company (רוחבי) synthesis across all client files
Sync execution itself runs through the existing async SyncEngine in the routes.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from ..models import (
    Organization, IntegrationConnection, IntegrationType, SumitCompany,
    SyncRun, User,
)
from .credentials_vault import encrypt_credentials, decrypt_credentials
from .client_automation_service import (
    enqueue_client_automation, mark_client_loop_result, run_post_sync_tasks,
)
from .financial_synthesis import synthesize_organization
from .sync_engine import SyncEngine, get_connector_for_org


OFFICE_DEFAULT_COMPANY = "__office_default__"


def set_office_credentials(
    db,
    office_organization_id: int,
    *,
    sumit_api_key: Optional[str] = None,
    open_finance: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Store the office-level default credentials (used by every client file unless
    the client overrides them). One SUMIT key serves all company files — each file
    just supplies its own CompanyID."""
    if sumit_api_key:
        _upsert_integration(db, office_organization_id, "sumit", {"api_key": sumit_api_key})
    if open_finance:
        _upsert_integration(db, office_organization_id, "open_finance", open_finance)
    db.commit()
    return get_office_credentials_status(db, office_organization_id)


def get_office_credentials_status(db, office_organization_id: int) -> dict[str, Any]:
    sumit = _office_default(db, office_organization_id, "sumit")
    of = _office_default(db, office_organization_id, "open_finance")
    return {
        "sumit_key_configured": bool(sumit.get("api_key")),
        "open_finance_configured": bool(of.get("client_id")),
    }


def _office_default(db, office_organization_id: int, source: str) -> dict[str, Any]:
    conn = (
        db.query(IntegrationConnection)
        .filter(
            IntegrationConnection.organization_id == office_organization_id,
            IntegrationConnection.source == source,
            IntegrationConnection.status == "active",
        )
        .first()
    )
    if conn and conn.credentials_encrypted:
        return decrypt_credentials(conn.credentials_encrypted) or {}
    return {}


def register_client(
    db,
    office_organization_id: int,
    *,
    name: str,
    sumit_company_id: str,
    sumit_api_key: Optional[str] = None,
    business_type: Optional[str] = None,
    tax_id: Optional[str] = None,
    open_finance: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Provision a client file: its own tenant org + its own encrypted credentials.

    `sumit_api_key` is optional — if omitted, the office-level default key is used
    with this client's CompanyID (one office key serves all files). Pass a key to
    override for a client that has its own separate SUMIT account.
    `open_finance` (optional): {client_id, client_secret, user_id}; falls back to the
    office default when omitted. Re-registering the same company_id updates in place.
    """
    used_office_key = False
    if not sumit_api_key:
        sumit_api_key = _office_default(db, office_organization_id, "sumit").get("api_key")
        used_office_key = True
    if not sumit_api_key:
        raise ValueError(
            "No SUMIT API key: set an office default key first, or provide one per client"
        )
    if not open_finance:
        office_of = _office_default(db, office_organization_id, "open_finance")
        open_finance = office_of or None

    existing = (
        db.query(SumitCompany)
        .filter(
            SumitCompany.office_organization_id == office_organization_id,
            SumitCompany.company_id == str(sumit_company_id),
        )
        .first()
    )

    if existing and existing.target_organization_id:
        client_org = db.get(Organization, existing.target_organization_id)
    else:
        client_org = Organization(
            name=name,
            business_type=business_type,
            tax_id=tax_id,
            integration_type=IntegrationType.SUMIT,
            is_active=True,
        )
        db.add(client_org)
        db.flush()  # assign id
    if not client_org:
        client_org = Organization(
            name=name,
            business_type=business_type,
            tax_id=tax_id,
            integration_type=IntegrationType.SUMIT,
            is_active=True,
        )
        db.add(client_org)
        db.flush()
    else:
        client_org.name = name
        if business_type is not None:
            client_org.business_type = business_type
        if tax_id is not None:
            client_org.tax_id = tax_id
        client_org.integration_type = IntegrationType.SUMIT
        client_org.is_active = True

    # SUMIT credentials — scoped to the client tenant, encrypted.
    _upsert_integration(
        db, client_org.id, "sumit",
        {"api_key": sumit_api_key, "company_id": str(sumit_company_id)},
    )
    if open_finance:
        _upsert_integration(db, client_org.id, "open_finance", open_finance)

    if existing:
        existing.name = name
        existing.status = "active"
        existing.target_organization_id = client_org.id
        existing.updated_at = datetime.now(timezone.utc)
        roster = existing
    else:
        roster = SumitCompany(
            office_organization_id=office_organization_id,
            company_id=str(sumit_company_id),
            name=name,
            status="active",
            target_organization_id=client_org.id,
        )
        db.add(roster)

    db.commit()
    db.refresh(roster)
    automation = enqueue_client_automation(
        db,
        office_organization_id=office_organization_id,
        client_company_id=roster.company_id,
        target_organization_id=client_org.id,
    )
    return {
        "id": roster.id,
        "company_id": roster.company_id,
        "name": roster.name,
        "target_organization_id": roster.target_organization_id,
        "has_open_finance": bool(open_finance),
        "used_office_key": used_office_key,
        "automation": automation,
    }


def list_clients(db, office_organization_id: int) -> list[dict[str, Any]]:
    rows = (
        db.query(SumitCompany)
        .filter(SumitCompany.office_organization_id == office_organization_id)
        .order_by(SumitCompany.created_at.desc())
        .all()
    )
    out = []
    for r in rows:
        connections = db.query(IntegrationConnection).filter(
                IntegrationConnection.organization_id == r.target_organization_id,
            ).all() if r.target_organization_id else []
        sources = [c.source for c in connections if c.status == "active"]
        connection_statuses = {c.source: c.status for c in connections}
        onboarding = _onboarding_summary(db, r.target_organization_id)
        last_sync = db.query(SyncRun).filter(
            SyncRun.organization_id == r.target_organization_id,
        ).order_by(SyncRun.created_at.desc()).first() if r.target_organization_id else None
        users_count = db.query(User).filter(
            User.organization_id == r.target_organization_id,
        ).count() if r.target_organization_id else 0
        out.append({
            "id": r.id,
            "company_id": r.company_id,
            "name": r.name,
            "status": r.status,
            "target_organization_id": r.target_organization_id,
            "organization_id": r.target_organization_id,
            "connections": sources,
            "connection_statuses": connection_statuses,
            "automation": (r.raw_data or {}).get("automation", {}),
            "onboarding": onboarding,
            "last_synced_at": r.last_synced_at.isoformat() if r.last_synced_at else None,
            "users_count": users_count,
            "last_sync": {
                "id": last_sync.id,
                "source": last_sync.source,
                "status": last_sync.status.value if last_sync.status else None,
                "started_at": last_sync.started_at.isoformat() if last_sync.started_at else None,
                "finished_at": last_sync.finished_at.isoformat() if last_sync.finished_at else None,
                "error_summary": last_sync.error_summary,
                "counts": last_sync.counts,
            } if last_sync else None,
        })
    return out


async def run_client_sync(
    db, office_organization_id: int, *, client_id: int,
    entity_types: Optional[str] = None,
) -> dict[str, Any]:
    """Run an on-demand sync for one client file in this office's roster —
    the same path POST /api/office/clients/{id}/sync uses (mirrored here so
    the AI chat office tool can reuse it directly; see ai_chat_tools.py).

    `client_id` is a SumitCompany roster row id, scoped to this office —
    never a bare organization_id, so one office can only trigger syncs for
    client files it actually registered.
    """
    client = db.query(SumitCompany).filter(
        SumitCompany.id == client_id,
        SumitCompany.office_organization_id == office_organization_id,
    ).first()
    if not client or not client.target_organization_id:
        raise ValueError(f"Client file {client_id} not found")

    target_org_id = client.target_organization_id
    # get_connector_for_org raises ValueError on its own when the client file
    # has no active integration connection — let it propagate unchanged.
    connector, conn_id, source = get_connector_for_org(db, target_org_id, None)

    engine = SyncEngine(db, connector, target_org_id, source, conn_id)
    types = [t.strip() for t in entity_types.split(",")] if entity_types else None
    try:
        sync_run = await engine.run_full_sync(entity_types=types)
    finally:
        await connector.close()

    automation = await run_post_sync_tasks(
        db, target_org_id, sources=[source], resume_onboarding=True
    )
    mark_client_loop_result(
        db,
        organization_id=target_org_id,
        source=source,
        ok=sync_run.status.value in {"completed", "partial"},
        summary={
            "sync_run_id": sync_run.id,
            "status": sync_run.status.value,
            "counts": sync_run.counts,
            "error_summary": sync_run.error_summary,
        },
        error=sync_run.error_summary,
    )
    client.last_synced_at = datetime.now(timezone.utc)
    db.commit()
    return {
        "company_id": client.company_id,
        "sync_run_id": sync_run.id,
        "status": sync_run.status.value,
        "counts": sync_run.counts,
        "automation": automation,
    }


def office_rollup(db, office_organization_id: int) -> dict[str, Any]:
    """Cross-company synthesis: aggregate required actions + VAT across all files."""
    clients = (
        db.query(SumitCompany)
        .filter(
            SumitCompany.office_organization_id == office_organization_id,
            SumitCompany.status == "active",
        )
        .all()
    )

    per_client: list[dict] = []
    totals = {
        "clients": 0, "required_actions": 0,
        "output_vat": 0.0, "input_vat": 0.0, "net_vat": 0.0,
        "actions_by_type": {},
    }
    for c in clients:
        if not c.target_organization_id:
            continue
        report = synthesize_organization(db, c.target_organization_id)
        vat = report["vat_summary"]
        per_client.append({
            "company_id": c.company_id,
            "name": c.name,
            "required_actions": report["action_count"],
            "net_vat": vat["net_vat"],
            "reconciliation": report["reconciliation"],
        })
        totals["clients"] += 1
        totals["required_actions"] += report["action_count"]
        totals["output_vat"] += vat["output_vat"]
        totals["input_vat"] += vat["input_vat"]
        for action in report["required_actions"]:
            totals["actions_by_type"][action["type"]] = (
                totals["actions_by_type"].get(action["type"], 0) + 1
            )

    totals["net_vat"] = round(totals["output_vat"] - totals["input_vat"], 2)
    totals["output_vat"] = round(totals["output_vat"], 2)
    totals["input_vat"] = round(totals["input_vat"], 2)
    return {"totals": totals, "clients": per_client}


def get_client_org_ids(db, office_organization_id: int) -> list[int]:
    rows = db.query(SumitCompany).filter(
        SumitCompany.office_organization_id == office_organization_id,
        SumitCompany.status == "active",
    ).all()
    return [r.target_organization_id for r in rows if r.target_organization_id]


def _onboarding_summary(db, org_id: Optional[int]) -> dict[str, Any]:
    if not org_id:
        return {"complete": False, "sources": {}}
    from ..models import OnboardingTask

    rows = db.query(OnboardingTask).filter(
        OnboardingTask.organization_id == org_id,
    ).all()
    by_source: dict[str, dict[str, Any]] = {}
    for row in rows:
        item = by_source.setdefault(row.source, {
            "total": 0,
            "completed": 0,
            "failed": 0,
            "running": 0,
            "pending": 0,
        })
        item["total"] += 1
        if row.status in item:
            item[row.status] += 1
    for item in by_source.values():
        item["complete"] = bool(item["total"]) and item["completed"] == item["total"]
    return {
        "complete": bool(by_source) and all(item["complete"] for item in by_source.values()),
        "sources": by_source,
    }


# ---------------------------------------------------------------------- #
def _upsert_integration(db, org_id: int, source: str, credentials: dict) -> None:
    conn = (
        db.query(IntegrationConnection)
        .filter(
            IntegrationConnection.organization_id == org_id,
            IntegrationConnection.source == source,
        )
        .first()
    )
    if conn:
        conn.status = "active"
        conn.credentials_encrypted = encrypt_credentials(credentials)
        conn.updated_at = datetime.now(timezone.utc)
    else:
        db.add(IntegrationConnection(
            organization_id=org_id,
            source=source,
            status="active",
            credentials_encrypted=encrypt_credentials(credentials),
            config={},
        ))
