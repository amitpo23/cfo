"""
Accounting-office routes (ניהול משרד) + cross-source synthesis.

/api/office/*    — manage many client files, each with its own authentication,
                   sync them, and roll up cross-company (רוחבי) synthesis.
/api/synthesis/* — per-organization synthesis: required-reconciliations worklist
                   and payment↔document linkage (combines SUMIT books + bank).
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ...database import get_db_session
from ..dependencies import get_current_org_id
from ...models import SumitCompany
from ...services import office_service, financial_synthesis
from ...services.sync_engine import SyncEngine, get_connector_for_org

logger = logging.getLogger(__name__)
router = APIRouter()


# ====================================================================== #
# Office — client files (each with its own authentication)
# ====================================================================== #
class OpenFinanceCreds(BaseModel):
    client_id: str
    client_secret: str
    user_id: str


class RegisterClientRequest(BaseModel):
    name: str = Field(..., min_length=1)
    company_id: str = Field(..., min_length=1, description="SUMIT company id (תיק)")
    # Optional: when omitted, the office-level default key is used with this company_id.
    api_key: Optional[str] = Field(None, description="Override SUMIT API key for this client")
    business_type: Optional[str] = None
    tax_id: Optional[str] = None
    open_finance: Optional[OpenFinanceCreds] = None


class OfficeSettingsRequest(BaseModel):
    sumit_api_key: Optional[str] = Field(None, description="Office-level SUMIT key for all files")
    open_finance: Optional[OpenFinanceCreds] = None


@router.post("/office/settings")
async def set_office_settings(
    body: OfficeSettingsRequest,
    org_id: int = Depends(get_current_org_id),
    db: Session = Depends(get_db_session),
):
    """Set the office-level default credentials (one SUMIT key serves every file)."""
    return office_service.set_office_credentials(
        db, org_id,
        sumit_api_key=body.sumit_api_key,
        open_finance=body.open_finance.dict() if body.open_finance else None,
    )


@router.get("/office/settings")
async def get_office_settings(
    org_id: int = Depends(get_current_org_id),
    db: Session = Depends(get_db_session),
):
    return office_service.get_office_credentials_status(db, org_id)


@router.post("/office/clients")
async def register_client(
    body: RegisterClientRequest,
    org_id: int = Depends(get_current_org_id),
    db: Session = Depends(get_db_session),
):
    """Provision a client file. Uses the office default key unless `api_key` is given."""
    try:
        result = office_service.register_client(
            db, org_id,
            name=body.name,
            sumit_company_id=body.company_id,
            sumit_api_key=body.api_key,
            business_type=body.business_type,
            tax_id=body.tax_id,
            open_finance=body.open_finance.dict() if body.open_finance else None,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return result


@router.get("/office/admin/clients")
async def admin_clients(
    org_id: int = Depends(get_current_org_id),
    db: Session = Depends(get_db_session),
):
    """Admin view — every client file with its connections, sync state and synthesis."""
    roster = office_service.list_clients(db, org_id)
    rollup = office_service.office_rollup(db, org_id)
    by_company = {c["company_id"]: c for c in rollup["clients"]}
    for c in roster:
        synth = by_company.get(c["company_id"], {})
        c["required_actions"] = synth.get("required_actions", 0)
        c["net_vat"] = synth.get("net_vat", 0)
        c["reconciliation"] = synth.get("reconciliation", {})
    return {"totals": rollup["totals"], "clients": roster}


@router.get("/office/clients")
async def list_clients(
    org_id: int = Depends(get_current_org_id),
    db: Session = Depends(get_db_session),
):
    return {"clients": office_service.list_clients(db, org_id)}


@router.get("/office/rollup")
async def office_rollup(
    org_id: int = Depends(get_current_org_id),
    db: Session = Depends(get_db_session),
):
    """Cross-company synthesis across all client files (התאמות נדרשות רוחבי)."""
    return office_service.office_rollup(db, org_id)


@router.get("/office/clients/{client_id}/synthesis")
async def client_synthesis(
    client_id: int,
    org_id: int = Depends(get_current_org_id),
    db: Session = Depends(get_db_session),
):
    client = _client_or_404(db, org_id, client_id)
    return financial_synthesis.synthesize_organization(db, client.target_organization_id)


@router.post("/office/clients/{client_id}/sync")
async def sync_client(
    client_id: int,
    entity_types: Optional[str] = Query(None),
    org_id: int = Depends(get_current_org_id),
    db: Session = Depends(get_db_session),
):
    client = _client_or_404(db, org_id, client_id)
    result = await _run_sync(db, client.target_organization_id, entity_types)
    client.last_synced_at = __import__("datetime").datetime.utcnow()
    db.commit()
    return {"company_id": client.company_id, **result}


@router.post("/office/sync-all")
async def sync_all_clients(
    entity_types: Optional[str] = Query(None),
    org_id: int = Depends(get_current_org_id),
    db: Session = Depends(get_db_session),
):
    """Sync every client file in the office."""
    results = []
    for client in db.query(SumitCompany).filter(
        SumitCompany.office_organization_id == org_id,
        SumitCompany.status == "active",
    ).all():
        if not client.target_organization_id:
            continue
        try:
            res = await _run_sync(db, client.target_organization_id, entity_types)
            client.last_synced_at = __import__("datetime").datetime.utcnow()
            results.append({"company_id": client.company_id, "ok": True, **res})
        except HTTPException as exc:
            results.append({"company_id": client.company_id, "ok": False, "error": exc.detail})
        except Exception as exc:  # noqa: BLE001
            results.append({"company_id": client.company_id, "ok": False, "error": str(exc)})
    db.commit()
    return {"synced": sum(1 for r in results if r.get("ok")), "results": results}


# ====================================================================== #
# Synthesis — current organization
# ====================================================================== #
@router.get("/synthesis/report")
async def synthesis_report(
    org_id: int = Depends(get_current_org_id),
    db: Session = Depends(get_db_session),
):
    """Required-reconciliations worklist + VAT position for this organization."""
    return financial_synthesis.synthesize_organization(db, org_id)


@router.post("/synthesis/link-payments")
async def link_payments(
    persist: bool = Query(True),
    org_id: int = Depends(get_current_org_id),
    db: Session = Depends(get_db_session),
):
    """Link SUMIT payments to their invoices/bills by amount + date + contact."""
    return financial_synthesis.link_payments_organization(db, org_id, persist=persist)


# ---------------------------------------------------------------------- #
def _client_or_404(db, office_org_id: int, client_id: int) -> SumitCompany:
    client = db.query(SumitCompany).filter(
        SumitCompany.id == client_id,
        SumitCompany.office_organization_id == office_org_id,
    ).first()
    if not client or not client.target_organization_id:
        raise HTTPException(404, "Client file not found")
    return client


async def _run_sync(db, target_org_id: int, entity_types: Optional[str]) -> dict[str, Any]:
    try:
        connector, conn_id, source = get_connector_for_org(db, target_org_id, None)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    engine = SyncEngine(db, connector, target_org_id, source, conn_id)
    types = [t.strip() for t in entity_types.split(",")] if entity_types else None
    try:
        sync_run = await engine.run_full_sync(entity_types=types)
    finally:
        await connector.close()
    return {
        "sync_run_id": sync_run.id,
        "status": sync_run.status.value,
        "counts": sync_run.counts,
    }
