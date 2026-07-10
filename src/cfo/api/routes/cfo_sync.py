"""
Sync API routes.
/api/sync/* for triggering sync, viewing runs, testing connections.
"""
import json
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Query, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ...database import get_db_session
from ..dependencies import get_current_org_id
from ...models import SyncRun, SyncStatus, IntegrationConnection, SyncCheckpoint
from ...config import settings
from ...services.sync_engine import SOURCE_CHECKPOINT_ENTITY, SyncEngine, SyncSkipped, get_connector_for_org
from ...services.credentials_vault import encrypt_credentials
from ...services.client_automation_service import run_post_sync_tasks

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


def _kickoff_onboarding(db: Session, org_id: int, source: str, background_tasks) -> None:
    """Materialize the onboarding checklist now and run it in the background."""
    from ...services import onboarding_service
    onboarding_service.ensure_tasks(db, org_id, source)
    background_tasks.add_task(onboarding_service.run_onboarding_bg, org_id, source)


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

    # Env credentials only apply to the default organization; every other
    # tenant must configure its own credentials.
    env_allowed = org_id == 1
    sumit_configured = connections.get("sumit") == "active" or (env_allowed and bool(settings.sumit_api_key))
    open_finance_configured = connections.get("open_finance") == "active" or (env_allowed and all([
        settings.open_finance_client_id,
        settings.open_finance_client_secret,
        settings.open_finance_user_id,
    ]))
    configured = {
        "production_database": not settings.database_url.startswith("sqlite:"),
        "security": settings.jwt_secret_key != "CHANGE-THIS-IN-PRODUCTION-USE-LONG-RANDOM-STRING",
        "sumit": sumit_configured,
        "open_finance": open_finance_configured,
        "ai": bool(settings.openai_api_key),
    }
    missing = {
        "production_database": [] if configured["production_database"] else ["DATABASE_URL"],
        "security": [] if configured["security"] else ["JWT_SECRET_KEY"],
        "sumit": [] if sumit_configured else ["SUMIT_API_KEY"],
        "open_finance": [],
        "ai": [] if configured["ai"] else ["OPENAI_API_KEY"],
    }
    if not open_finance_configured:
        if connections.get("open_finance") == "active":
            missing["open_finance"] = []
        elif env_allowed:
            missing["open_finance"] = [
                name for name, value in {
                    "OPEN_FINANCE_CLIENT_ID": settings.open_finance_client_id,
                    "OPEN_FINANCE_CLIENT_SECRET": settings.open_finance_client_secret,
                    "OPEN_FINANCE_USER_ID": settings.open_finance_user_id,
                }.items()
                if not value
            ]
        else:
            missing["open_finance"] = ["organization_open_finance_credentials"]

    # `connections.sumit` reflects configuration, not live health -- a connector
    # can be "active" (credentials present) while every real API call fails
    # (wrong CompanyID/APIKey). Surface the latest sync run's real error
    # alongside it rather than overwriting connections.sumit, since several
    # dashboards render connections.sumit truthily (checkmark vs. warning) and
    # would misreport an "error" string as connected.
    last_sync_errors = {}
    latest_sumit_run = (
        db.query(SyncRun)
        .filter(SyncRun.organization_id == org_id, SyncRun.source == "sumit")
        .order_by(SyncRun.id.desc())
        .first()
    )
    if latest_sumit_run and latest_sumit_run.error_summary:
        last_sync_errors["sumit"] = latest_sumit_run.error_summary

    return {
        "organization_id": org_id,
        "configured": configured,
        "missing": missing,
        "connections": connections,
        "last_sync_errors": last_sync_errors,
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
    background_tasks: BackgroundTasks,
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
    _kickoff_onboarding(db, org_id, "open_finance", background_tasks)

    return {
        "id": conn.id,
        "organization_id": org_id,
        "source": conn.source,
        "status": conn.status,
        "configured": True,
        "onboarding": "started",
    }


@router.post("/integration/sumit/configure")
async def configure_sumit(
    request: SumitConfigRequest,
    background_tasks: BackgroundTasks,
    org_id: int = Depends(get_current_org_id),
    db: Session = Depends(get_db_session),
):
    """Store per-organization SUMIT credentials (never returned in responses).

    On success we kick off the codified onboarding pipeline so the new business's
    data is mapped + reconciled automatically (see services/onboarding_service.py).
    """
    credentials = {"api_key": request.api_key}
    if request.company_id:
        credentials["company_id"] = request.company_id

    conn = _upsert_connection(
        db, org_id, "sumit", credentials,
        ["customers", "invoices", "bills", "payments", "bank_transactions"],
    )
    _kickoff_onboarding(db, org_id, "sumit", background_tasks)

    return {
        "id": conn.id,
        "organization_id": org_id,
        "source": conn.source,
        "status": conn.status,
        "configured": True,
        "onboarding": "started",
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


def _manual_refresh_cooldown_check(db: Session, org_id: int, source: str) -> Optional[dict]:
    """Return a 429-style payload if a manual refresh for this org/source ran
    too recently, else None (proceed). RSF-029 -- stops a UI "Refresh" button
    (or an impatient user double-clicking it) from hammering the provider on
    top of the scheduled cron sync."""
    cp = db.query(SyncCheckpoint).filter(
        SyncCheckpoint.organization_id == org_id,
        SyncCheckpoint.source == source,
        SyncCheckpoint.entity_type == SOURCE_CHECKPOINT_ENTITY,
    ).first()
    if not cp or not cp.cooldown_until:
        return None
    now = datetime.utcnow()
    if now < cp.cooldown_until:
        return {
            "error": "manual_refresh_cooldown",
            "detail": "A manual sync for this integration was triggered too recently. Please wait before retrying.",
            "retry_after_seconds": int((cp.cooldown_until - now).total_seconds()),
            "cooldown_until": cp.cooldown_until.isoformat(),
        }
    return None


def _start_manual_refresh_cooldown(db: Session, org_id: int, source: str) -> None:
    cp = db.query(SyncCheckpoint).filter(
        SyncCheckpoint.organization_id == org_id,
        SyncCheckpoint.source == source,
        SyncCheckpoint.entity_type == SOURCE_CHECKPOINT_ENTITY,
    ).first()
    if not cp:
        cp = SyncCheckpoint(organization_id=org_id, source=source, entity_type=SOURCE_CHECKPOINT_ENTITY)
        db.add(cp)
    cp.cooldown_until = datetime.utcnow() + timedelta(minutes=settings.manual_refresh_cooldown_minutes)
    db.commit()


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

    cooldown = _manual_refresh_cooldown_check(db, org_id, source)
    if cooldown:
        try:
            await connector.close()
        except Exception:
            pass
        raise HTTPException(status_code=429, detail=cooldown)

    _start_manual_refresh_cooldown(db, org_id, source)

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

    if isinstance(sync_run, SyncSkipped):
        return {
            "id": None,
            "status": "skipped",
            "started_at": None,
            "finished_at": None,
            "counts": {},
            "error_summary": sync_run.error_summary,
            "automation": None,
        }

    automation = None
    try:
        automation = await run_post_sync_tasks(
            db, org_id, sources=[source], resume_onboarding=True
        )
    except Exception as e:
        automation = {"error": str(e)}

    return {
        "id": sync_run.id,
        "status": sync_run.status.value,
        "started_at": sync_run.started_at.isoformat() if sync_run.started_at else None,
        "finished_at": sync_run.finished_at.isoformat() if sync_run.finished_at else None,
        "counts": sync_run.counts,
        "error_summary": sync_run.error_summary,
        "automation": automation,
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
