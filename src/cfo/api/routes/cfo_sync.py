"""
Sync API routes.
/api/sync/* for triggering sync, viewing runs, testing connections.
"""
from typing import Optional

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session

from ...database import get_db_session
from ...models import SyncRun, SyncStatus, IntegrationConnection
from ...services.sync_engine import SyncEngine, get_connector_for_org
from ...services.alert_engine import AlertEngine

router = APIRouter()

DEFAULT_ORG_ID = 1


@router.post("/integration/test")
async def test_connection(
    org_id: int = Query(DEFAULT_ORG_ID),
    db: Session = Depends(get_db_session),
):
    """Test the accounting API connection."""
    try:
        connector, conn_id, source = get_connector_for_org(db, org_id)
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
    org_id: int = Query(DEFAULT_ORG_ID),
    db: Session = Depends(get_db_session),
):
    """
    Trigger a sync run.
    entity_types: optional comma-separated list of entity types to sync.
    If omitted, syncs all entities.
    """
    try:
        connector, conn_id, source = get_connector_for_org(db, org_id)
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
    org_id: int = Query(DEFAULT_ORG_ID),
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
    db: Session = Depends(get_db_session),
):
    """Get details of a specific sync run."""
    run = db.query(SyncRun).get(run_id)
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
