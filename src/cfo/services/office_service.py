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

from datetime import datetime
from typing import Any, Optional

from ..models import (
    Organization, IntegrationConnection, IntegrationType, SumitCompany,
)
from .credentials_vault import encrypt_credentials, decrypt_credentials
from .financial_synthesis import synthesize_organization


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
        client_org = db.query(Organization).get(existing.target_organization_id)
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
        existing.updated_at = datetime.utcnow()
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
    return {
        "id": roster.id,
        "company_id": roster.company_id,
        "name": roster.name,
        "target_organization_id": roster.target_organization_id,
        "has_open_finance": bool(open_finance),
        "used_office_key": used_office_key,
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
        sources = [
            c.source for c in db.query(IntegrationConnection).filter(
                IntegrationConnection.organization_id == r.target_organization_id,
                IntegrationConnection.status == "active",
            ).all()
        ] if r.target_organization_id else []
        out.append({
            "id": r.id,
            "company_id": r.company_id,
            "name": r.name,
            "status": r.status,
            "target_organization_id": r.target_organization_id,
            "connections": sources,
            "last_synced_at": r.last_synced_at.isoformat() if r.last_synced_at else None,
        })
    return out


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
        conn.updated_at = datetime.utcnow()
    else:
        db.add(IntegrationConnection(
            organization_id=org_id,
            source=source,
            status="active",
            credentials_encrypted=encrypt_credentials(credentials),
            config={},
        ))
