"""
Scheduled jobs endpoint, invoked by Vercel Cron.

Not behind user auth — protected by CRON_SECRET instead (Vercel sends
"Authorization: Bearer <CRON_SECRET>" automatically when the env var is set).
"""
import logging

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from ...config import settings
from ...database import get_db_session
from ...models import IntegrationConnection
from ...services.sync_engine import SyncEngine, get_connector_for_org

logger = logging.getLogger(__name__)

router = APIRouter()


def _verify_cron_secret(authorization: str = Header(None)):
    if not settings.cron_secret:
        raise HTTPException(status_code=503, detail="CRON_SECRET is not configured")
    if authorization != f"Bearer {settings.cron_secret}":
        raise HTTPException(status_code=401, detail="Invalid cron credentials")


@router.get("/cron/sync", dependencies=[Depends(_verify_cron_secret)])
async def scheduled_sync(db: Session = Depends(get_db_session)):
    """Run a sync for every organization with an active integration."""
    # Org/source pairs from configured connections, plus the default org's
    # env-credential SUMIT fallback.
    targets = {
        (conn.organization_id, conn.source)
        for conn in db.query(IntegrationConnection).filter(
            IntegrationConnection.status == "active",
        ).all()
    }
    if settings.sumit_api_key:
        targets.add((1, "sumit"))

    results = []
    for org_id, source in sorted(targets):
        try:
            connector, conn_id, resolved = get_connector_for_org(db, org_id, source)
        except ValueError as exc:
            results.append({"organization_id": org_id, "source": source, "error": str(exc)})
            continue

        try:
            engine = SyncEngine(db, connector, org_id, resolved, conn_id)
            run = await engine.run_full_sync()
            results.append({
                "organization_id": org_id,
                "source": resolved,
                "status": run.status.value if run.status else None,
                "counts": run.counts,
            })
        except Exception as exc:
            logger.error("Scheduled sync failed for org %s source %s: %s", org_id, source, exc)
            results.append({"organization_id": org_id, "source": source, "error": str(exc)})
        finally:
            try:
                await connector.close()
            except Exception:
                pass

        # Refresh insights after each org sync; never fail the cron over it.
        try:
            from ...services.cfo_brain_service import CFOBrainService
            CFOBrainService(db, org_id).run_analysis()
        except Exception as exc:
            logger.warning("Brain analysis failed for org %s: %s", org_id, exc)

    return {"synced": len(results), "results": results}
