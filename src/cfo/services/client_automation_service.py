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

from ..config import settings
from ..models import IntegrationConnection, Organization, SumitCompany
from .credentials_vault import decrypt_credentials

logger = logging.getLogger(__name__)


def active_sources(db: Session, organization_id: int) -> list[str]:
    """Return active integration sources for one tenant organization."""
    return [
        row.source for row in db.query(IntegrationConnection).filter(
            IntegrationConnection.organization_id == organization_id,
            IntegrationConnection.status == "active",
        ).order_by(IntegrationConnection.source.asc()).all()
    ]


def repair_missing_client_roster(
    db: Session,
    *,
    office_organization_id: int = 1,
) -> list[dict[str, Any]]:
    """Backfill roster rows for legacy tenants that already have SUMIT credentials.

    New clients go through ``office_service.register_client`` and get a roster row
    immediately. This repair covers older production databases where integrations
    existed before the office roster became the source of truth.
    """
    repaired: list[dict[str, Any]] = []

    def ensure_row(target_org: Organization, company_id: str, source: str) -> None:
        if not company_id:
            return
        existing = db.query(SumitCompany).filter(
            SumitCompany.office_organization_id == office_organization_id,
            SumitCompany.company_id == str(company_id),
        ).first()
        if existing:
            changed = False
            if existing.target_organization_id != target_org.id:
                existing.target_organization_id = target_org.id
                changed = True
            if existing.status != "active":
                existing.status = "active"
                changed = True
            if not existing.name:
                existing.name = target_org.name
                changed = True
            if changed:
                existing.updated_at = datetime.now(timezone.utc)
            return

        db.add(SumitCompany(
            office_organization_id=office_organization_id,
            company_id=str(company_id),
            name=target_org.name,
            status="active",
            target_organization_id=target_org.id,
            raw_data={
                "automation": {
                    "enabled": True,
                    "state": "repaired",
                    "target_organization_id": target_org.id,
                    "sources": active_sources(db, target_org.id) or [source],
                    "queued_at": datetime.now(timezone.utc).isoformat(),
                    "loop": "hourly_cron",
                    "repair_source": "legacy_integration",
                }
            },
        ))
        repaired.append({
            "organization_id": target_org.id,
            "company_id": str(company_id),
            "source": source,
        })

    if settings.sumit_api_key and settings.sumit_company_id:
        default_org = db.query(Organization).filter(Organization.id == office_organization_id).first()
        if default_org:
            ensure_row(default_org, settings.sumit_company_id, "sumit")

    rows = db.query(IntegrationConnection).filter(
        IntegrationConnection.source == "sumit",
        IntegrationConnection.status == "active",
    ).all()
    for conn in rows:
        org = db.query(Organization).filter(Organization.id == conn.organization_id).first()
        if not org:
            continue
        creds = decrypt_credentials(conn.credentials_encrypted) if conn.credentials_encrypted else {}
        ensure_row(org, str(creds.get("company_id") or ""), conn.source)

    if repaired:
        db.commit()
        for item in repaired:
            enqueue_client_automation(
                db,
                office_organization_id=office_organization_id,
                client_company_id=item["company_id"],
                target_organization_id=item["organization_id"],
            )
    return repaired


def roster_sync_targets(db: Session) -> list[tuple[int, str]]:
    """Return org/source pairs that must participate in the Rezef loop.

    The roster is the source of truth for office-managed client files. Cron also
    scans IntegrationConnection directly, but this makes the invariant explicit:
    every active client row with a target tenant is eligible for the automation
    loop as soon as it has active credentials.
    """
    targets: set[tuple[int, str]] = set()
    rows = db.query(SumitCompany).filter(
        SumitCompany.status == "active",
        SumitCompany.target_organization_id.isnot(None),
    ).all()
    for row in rows:
        for source in active_sources(db, row.target_organization_id):
            targets.add((row.target_organization_id, source))
    return sorted(targets)


def mark_client_loop_result(
    db: Session,
    *,
    organization_id: int,
    source: str,
    ok: bool,
    summary: Optional[dict[str, Any]] = None,
    error: Optional[str] = None,
) -> None:
    """Persist the last automation-loop state on the office roster row."""
    rows = db.query(SumitCompany).filter(
        SumitCompany.target_organization_id == organization_id,
    ).all()
    if not rows:
        return

    now = datetime.now(timezone.utc)
    for row in rows:
        raw = dict(row.raw_data or {})
        automation = dict(raw.get("automation") or {})
        source_state = dict((automation.get("sources_state") or {}).get(source) or {})
        source_state.update({
            "state": "completed" if ok else "error",
            "last_run_at": now.isoformat(),
            "summary": summary or {},
            "error": error,
        })
        sources_state = dict(automation.get("sources_state") or {})
        sources_state[source] = source_state
        automation.update({
            "enabled": True,
            "state": "active" if ok else "error",
            "last_run_at": now.isoformat(),
            "loop": "hourly_cron",
            "sources_state": sources_state,
        })
        raw["automation"] = automation
        row.raw_data = raw
        row.updated_at = now
        if ok:
            row.last_synced_at = now


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
