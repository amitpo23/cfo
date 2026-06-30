"""Automation loop for every client organization.

New client files are represented as their own ``Organization`` rows. Their SUMIT
and Open Finance credentials live under that organization in
``IntegrationConnection``; all synced documents, bank transactions, insights and
tasks are also org-scoped. This module is the orchestration layer that makes a new
client immediately join Rezef's automatic work loop.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from sqlalchemy.orm import Session

from ..models import IntegrationConnection, SumitCompany

logger = logging.getLogger(__name__)


def active_sources(db: Session, organization_id: int) -> list[str]:
    """Return active integration sources for one tenant organization."""
    return [
        row.source for row in db.query(IntegrationConnection).filter(
            IntegrationConnection.organization_id == organization_id,
            IntegrationConnection.status == "active",
        ).order_by(IntegrationConnection.source.asc()).all()
    ]


def enqueue_client_automation(
    db: Session,
    *,
    office_organization_id: int,
    client_company_id: str,
    target_organization_id: int,
    sources: Optional[Iterable[str]] = None,
) -> dict[str, Any]:
    """Materialize onboarding tasks and mark the roster row as automation-enabled.

    This does not call external APIs. The next cron run, an on-demand sync, or an
    explicit onboarding run will consume the tasks and pull live data.
    """
    from . import onboarding_service

    selected_sources = sorted(set(sources or active_sources(db, target_organization_id)))
    for source in selected_sources:
        onboarding_service.ensure_tasks(db, target_organization_id, source)

    row = db.query(SumitCompany).filter(
        SumitCompany.office_organization_id == office_organization_id,
        SumitCompany.company_id == str(client_company_id),
    ).first()
    status = {
        "enabled": True,
        "state": "queued",
        "target_organization_id": target_organization_id,
        "sources": selected_sources,
        "queued_at": datetime.now(timezone.utc).isoformat(),
        "loop": "hourly_cron",
    }
    if row:
        raw = dict(row.raw_data or {})
        raw["automation"] = status
        row.raw_data = raw
        row.updated_at = datetime.now(timezone.utc)
    db.commit()
    return status


async def resume_onboarding_for_sources(
    db: Session,
    organization_id: int,
    sources: Optional[Iterable[str]] = None,
) -> dict[str, Any]:
    """Run/resume onboarding checklists for active sources.

    Errors are captured per source because one external provider must not stop the
    rest of the automation loop.
    """
    from . import onboarding_service

    selected_sources = sorted(set(sources or active_sources(db, organization_id)))
    results: dict[str, Any] = {}
    for source in selected_sources:
        try:
            onboarding_service.ensure_tasks(db, organization_id, source)
            results[source] = await onboarding_service.run_onboarding(db, organization_id, source)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Onboarding resume failed for org %s source %s: %s", organization_id, source, exc)
            db.rollback()
            results[source] = {"error": str(exc)}
    return results


async def run_post_sync_tasks(
    db: Session,
    organization_id: int,
    *,
    sources: Optional[Iterable[str]] = None,
    resume_onboarding: bool = True,
) -> dict[str, Any]:
    """Run all local Rezef computations after data has been pulled.

    This is where raw source data becomes the product surface: transactions,
    reconciliation worklists, alerts, CFO insights, and onboarding progress.
    """
    result: dict[str, Any] = {
        "organization_id": organization_id,
        "sources": sorted(set(sources or active_sources(db, organization_id))),
    }

    if "sumit" in result["sources"]:
        try:
            from .data_sync_service import DataSyncService

            result["transactions"] = await DataSyncService(db, organization_id).sync_all()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Transaction sync failed for org %s: %s", organization_id, exc)
            db.rollback()
            result["transactions_error"] = str(exc)

    try:
        from . import financial_synthesis

        result["payment_links"] = financial_synthesis.link_payments_organization(
            db, organization_id, persist=True
        )
        result["synthesis"] = financial_synthesis.synthesize_organization(db, organization_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Financial synthesis failed for org %s: %s", organization_id, exc)
        db.rollback()
        result["synthesis_error"] = str(exc)

    try:
        from .alert_engine import AlertEngine

        result["alerts_created"] = len(AlertEngine(db, organization_id).evaluate_all())
    except Exception as exc:  # noqa: BLE001
        logger.warning("Alert evaluation failed for org %s: %s", organization_id, exc)
        db.rollback()
        result["alerts_error"] = str(exc)

    try:
        from .cfo_brain_service import CFOBrainService

        brain = CFOBrainService(db, organization_id).run_analysis(create_tasks=True)
        result["cfo_brain"] = {
            "insights_generated": brain.get("insights_generated"),
            "tasks_created": brain.get("tasks_created"),
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("CFO brain failed for org %s: %s", organization_id, exc)
        db.rollback()
        result["cfo_brain_error"] = str(exc)

    if resume_onboarding:
        result["onboarding"] = await resume_onboarding_for_sources(
            db, organization_id, result["sources"]
        )

    return result
