"""Unifying-engine routes (המנוע המאחד). One command surface over all services."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ...database import get_db_session
from ..dependencies import get_current_org_id
from ...services import engine_service, document_anomalies

router = APIRouter()


@router.get("/engine/anomalies")
def engine_anomalies(
    org_id: int = Depends(get_current_org_id),
    db: Session = Depends(get_db_session),
):
    findings = document_anomalies.detect_document_anomalies(db, org_id)
    return {"count": len(findings), "findings": findings}


@router.post("/engine/anomalies/persist")
def engine_anomalies_persist(
    org_id: int = Depends(get_current_org_id),
    db: Session = Depends(get_db_session),
):
    """Detect document anomalies and store them in the insights stream (CfoInsight)."""
    return document_anomalies.persist_anomalies(db, org_id)


@router.get("/engine/status")
def engine_status(
    org_id: int = Depends(get_current_org_id),
    db: Session = Depends(get_db_session),
):
    return engine_service.status(db, org_id)


@router.get("/engine/run")
def engine_run(
    year: Optional[int] = Query(None),
    month: Optional[int] = Query(None),
    org_id: int = Depends(get_current_org_id),
    db: Session = Depends(get_db_session),
):
    return engine_service.run_pipeline(db, org_id, year=year, month=month)
