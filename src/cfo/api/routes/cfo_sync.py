"""
Sync API routes.
/api/sync/* for triggering sync, viewing runs, testing connections.
"""
import json
from typing import Optional

from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ...database import get_db_session
from ..dependencies import get_current_org_id
from ...models import SyncRun, SyncStatus, IntegrationConnection
from ...config import settings
from ...services.sync_engine import SyncEngine, get_connector_for_org
from ...services.credentials_vault import encrypt_credentials
from ...services.alert_engine import AlertEngine

router = APIRouter()



class OpenFinanceConfigRequest(BaseModel):
    client_id: str = Field(..., min_length=1)
    client_secret: str = Field(..., min_length=1)
    user_id: str = Field(..., min_length=1)
    api_base_url: Optional[str] = None
    oauth_url: Optional[str] = None


class SumitConfigRequest(BaseModel):
    api_key: str = Field(..., min_length=1)
    company_id: Optional[str] = None


def _upsert_connection(db: Session, org_id: int, source: str, credentials: dict, entities: list):
    conn = db.query(IntegrationConnection).filter(
        IntegrationConnection.organization_id == org_id,
        IntegrationConnection.source == source,
    ).first()
    if conn:
        conn.status = "active"
        conn.credentials_encrypted = encrypt_credentials(credentials)
    else:
        conn = IntegrationConnection(
            organization_id=org_id,
            source=source,
            status="active",
            credentials_encrypted=encrypt_credentials(credentials),
            config={"entities": entities},
        )
        db.add(conn)
    db.commit()
    db.refresh(conn)
    return conn


@router.get("/integration/status")
async def integration_status(
    org_id: int = Depends(get_current_org_id),
    db: Session = Depends(get_db_session),
):
    """Return safe configuration status without exposing secret values."""
    connections = {
        conn.source: conn.status
        for conn in db.query(IntegrationConnection).filter(
            IntegrationConnection.organization_id == org_id,
        ).all()
    }

    required = {
        "production_database": ["DATABASE_URL"],
        "security": ["JWT_SECRET_KEY"],
        "sumit": ["SUMIT_API_KEY"],
        "open_finance": [
            "OPEN_FINANCE_CLIENT_ID",
            "OPEN_FINANCE_CLIENT_SECRET",
            "OPEN_FINANCE_USER_ID",
        ],
        "ai": ["OPENAI_API_KEY"],
    }

    # Env credentials only apply to the default organization; every other
    # tenant must configure its own credentials.
    env_allowed = org_id == 1
    configured = {
        "production_database": not settings.database_url.startswith("sqlite:"),
        "security": settings.jwt_secret_key != "CHANGE-THIS-IN-PRODUCTION-USE-LONG-RANDOM-STRING",
        "sumit": connections.get("sumit") == "active" or (env_allowed and bool(settings.sumit_api_key)),
        "open_finance": connections.get("open_finance") == "active" or (env_allowed and all([
            settings.open_finance_client_id,
            settings.open_finance_client_secret,
            settings.open_finance_user_id,
        ])),
        "ai": bool(settings.openai_api_key),
    }

    return {
        "organization_id": org_id,
        "configured": configured,
        "missing": {
            key: [] if value else required[key]
            for key, value in configured.items()
        },
        "connections": connections,
        "notes": {
            "production_database": (
                "Persistent database is configured."
                if configured["production_database"]
                else "SQLite on Vercel is temporary. Set DATABASE_URL for persistent data."
            ),
            "sumit": "Required for invoices, receipts, customers, payments, and accounting sync.",
            "open_finance": "Required for bank/card transactions and reconciliation.",
            "ai": "Optional; enables AI insights and smarter classification.",
        },
    }


@router.post("/integration/open-finance/configure")
async def configure_open_finance(
    request: OpenFinanceConfigRequest,
    org_id: int = Depends(get_current_org_id),
    db: Session = Depends(get_db_session),
):
    """
    Store Open Finance credentials for the organization.

    The secret is intentionally never returned in the response. In production,
    replace this JSON storage with encryption/KMS before exposing broadly.
    """
    credentials = {
        "client_id": request.client_id,
        "client_secret": request.client_secret,
        "user_id": request.user_id,
    }
    if request.api_base_url:
        credentials["api_base_url"] = request.api_base_url
    if request.oauth_url:
        credentials["oauth_url"] = request.oauth_url

    conn = _upsert_connection(db, org_id, "open_finance", credentials, ["accounts", "bank_transactions"])

    return {
        "id": conn.id,
        "organization_id": org_id,
        "source": conn.source,
        "status": conn.status,
        "configured": True,
    }


@router.post("/integration/sumit/configure")
async def configure_sumit(
    request: SumitConfigRequest,
    org_id: int = Depends(get_current_org_id),
    db: Session = Depends(get_db_session),
):
    """Store per-organization SUMIT credentials (never returned in responses)."""
    credentials = {"api_key": request.api_key}
    if request.company_id:
        credentials["company_id"] = request.company_id

    conn = _upsert_connection(
        db, org_id, "sumit", credentials,
        ["customers", "invoices", "bills", "payments", "bank_transactions"],
    )

    return {
        "id": conn.id,
        "organization_id": org_id,
        "source": conn.source,
        "status": conn.status,
        "configured": True,
    }


@router.post("/integration/test")
async def test_connection(
    org_id: int = Depends(get_current_org_id),
    source: Optional[str] = Query(None, description="Optional integration source, e.g. open_finance or sumit"),
    db: Session = Depends(get_db_session),
):
    """Test the accounting API connection."""
    try:
        connector, conn_id, source = get_connector_for_org(db, org_id, source)
        result = await connector.test_connection()
        await connector.close()
        return {
            "success": result,
            "source": source,
            "message": "Connection successful" if result else "Connection failed",
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        return {"success": False, "message": str(e)}


@router.post("/sync/run")
async def trigger_sync(
    entity_types: Optional[str] = Query(None, description="Comma-separated: invoices,bills,payments"),
    org_id: int = Depends(get_current_org_id),
    source: Optional[str] = Query(None, description="Optional integration source, e.g. open_finance or sumit"),
    db: Session = Depends(get_db_session),
):
    """
    Trigger a sync run.
    entity_types: optional comma-separated list of entity types to sync.
    If omitted, syncs all entities.
    """
    try:
        connector, conn_id, source = get_connector_for_org(db, org_id, source)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    engine = SyncEngine(db, connector, org_id, source, conn_id)

    types = None
    if entity_types:
        types = [t.strip() for t in entity_types.split(",")]

    try:
        sync_run = await engine.run_full_sync(entity_types=types)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Sync failed: {e}")
    finally:
        await connector.close()

    # Run alert engine after sync
    try:
        alert_engine = AlertEngine(db, org_id)
        alert_engine.evaluate_all()
    except Exception as e:
        # Don't fail sync because of alert evaluation
        pass

    return {
        "id": sync_run.id,
        "status": sync_run.status.value,
        "started_at": sync_run.started_at.isoformat() if sync_run.started_at else None,
        "finished_at": sync_run.finished_at.isoformat() if sync_run.finished_at else None,
        "counts": sync_run.counts,
        "error_summary": sync_run.error_summary,
    }


@router.get("/sync/runs")
async def list_sync_runs(
    limit: int = Query(20, ge=1, le=100),
    org_id: int = Depends(get_current_org_id),
    db: Session = Depends(get_db_session),
):
    """List recent sync runs."""
    runs = db.query(SyncRun).filter(
        SyncRun.organization_id == org_id,
    ).order_by(SyncRun.created_at.desc()).limit(limit).all()

    return [
        {
            "id": r.id,
            "source": r.source,
            "sync_type": r.sync_type,
            "entity_types": r.entity_types,
            "status": r.status.value if r.status else None,
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "finished_at": r.finished_at.isoformat() if r.finished_at else None,
            "counts": r.counts,
            "error_summary": r.error_summary,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in runs
    ]


@router.get("/sync/runs/{run_id}")
async def get_sync_run(
    run_id: int,
    org_id: int = Depends(get_current_org_id),
    db: Session = Depends(get_db_session),
):
    """Get details of a specific sync run."""
    run = db.query(SyncRun).filter(
        SyncRun.id == run_id, SyncRun.organization_id == org_id,
    ).first()
    if not run:
        raise HTTPException(status_code=404, detail="Sync run not found")

    return {
        "id": run.id,
        "source": run.source,
        "sync_type": run.sync_type,
        "entity_types": run.entity_types,
        "status": run.status.value if run.status else None,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "counts": run.counts,
        "error_summary": run.error_summary,
        "error_details": run.error_details,
        "created_at": run.created_at.isoformat() if run.created_at else None,
    }
