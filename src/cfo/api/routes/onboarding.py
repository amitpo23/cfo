"""Onboarding data-mapping pipeline — status + manual run.

The checklist auto-starts when a business connects an integration; these endpoints let
the UI show progress and let an operator re-run incomplete/failed steps until complete.
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ...database import get_db_session
from ...services import onboarding_service
from ..dependencies import get_current_org_id

router = APIRouter()


@router.get("/onboarding/status")
async def onboarding_status(
    source: str = Query("sumit"),
    org_id: int = Depends(get_current_org_id),
    db: Session = Depends(get_db_session),
):
    """Per-step status of the org's data-mapping checklist."""
    return onboarding_service.status(db, org_id, source)


@router.post("/onboarding/run")
async def onboarding_run(
    source: str = Query("sumit"),
    force: bool = Query(False, description="Re-run completed steps too"),
    org_id: int = Depends(get_current_org_id),
    db: Session = Depends(get_db_session),
):
    """Run (or resume) the checklist until it completes or a step fails."""
    return await onboarding_service.run_onboarding(db, org_id, source, force=force)
