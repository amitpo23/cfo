"""
Scheduled jobs endpoint, invoked by Vercel Cron.

Not behind user auth — protected by CRON_SECRET instead (Vercel sends
"Authorization: Bearer <CRON_SECRET>" automatically when the env var is set).
"""
import logging

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from datetime import date

from ...config import settings
from ...database import get_db_session
from ...models import IntegrationConnection, Organization
from ...services.sync_engine import SyncEngine, get_connector_for_org
from ...services.client_automation_service import (
    mark_client_loop_result,
    repair_missing_client_roster,
    roster_sync_targets,
    run_post_sync_tasks,
)
from ...services.collection_service import CollectionService, dispatch_reminders
from ...services.email_sender import send_email_smtp
from ..dependencies import sumit_for_org
from ...integrations.sumit_models import SMSRequest

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
    repaired_roster = repair_missing_client_roster(db)
    # Org/source pairs from configured connections, plus the default org's
    # env-credential SUMIT fallback.
    targets = {
        (conn.organization_id, conn.source)
        for conn in db.query(IntegrationConnection).filter(
            IntegrationConnection.status == "active",
        ).all()
    }
    targets.update(roster_sync_targets(db))
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
            result = {
                "organization_id": org_id,
                "source": resolved,
                "status": run.status.value if run.status else None,
                "counts": run.counts,
            }
            result["automation"] = await run_post_sync_tasks(
                db, org_id, sources=[resolved], resume_onboarding=True
            )
            mark_client_loop_result(
                db,
                organization_id=org_id,
                source=resolved,
                ok=True,
                summary={
                    "sync_run_id": run.id,
                    "status": run.status.value if run.status else None,
                    "counts": run.counts,
                },
            )
            db.commit()
            results.append(result)
        except Exception as exc:
            logger.error("Scheduled sync failed for org %s source %s: %s", org_id, source, exc)
            mark_client_loop_result(
                db,
                organization_id=org_id,
                source=source,
                ok=False,
                error=str(exc),
            )
            db.commit()
            results.append({"organization_id": org_id, "source": source, "error": str(exc)})
        finally:
            try:
                await connector.close()
            except Exception:
                pass

    return {"synced": len(results), "repaired_roster": repaired_roster, "results": results}


@router.get("/cron/enrich-expenses", dependencies=[Depends(_verify_cron_secret)])
async def scheduled_enrich_expenses(db: Session = Depends(get_db_session)):
    """העשרה מתמשכת של הוצאות (שם ספק + ח.פ) מ-SUMIT, באצווה חסומת-קצב.

    רץ אצווה מוגבלת בכל הפעלה ונעצר בעדינות ב-rate-limit; קריאות חוזרות
    משלימות בהדרגה את כל ההוצאות בלי לחרוג מהמכסה של SUMIT.
    """
    from ...services.expense_filing_service import ExpenseFilingService

    targets = {
        conn.organization_id
        for conn in db.query(IntegrationConnection).filter(
            IntegrationConnection.status == "active",
            IntegrationConnection.source == "sumit",
        ).all()
    }
    if settings.sumit_api_key:
        targets.add(1)

    results = []
    for org_id in sorted(targets):
        try:
            res = await ExpenseFilingService(db, organization_id=org_id).resolve_supplier_names(
                limit=200, delay=0.4
            )
            results.append({"organization_id": org_id, **res})
        except Exception as exc:
            logger.warning("Expense enrichment failed for org %s: %s", org_id, exc)
            results.append({"organization_id": org_id, "error": str(exc)})
    return {"enriched_orgs": len(results), "results": results}


@router.get("/cron/process-ocr", dependencies=[Depends(_verify_cron_secret)])
async def scheduled_process_ocr(db: Session = Depends(get_db_session)):
    """Automatic OCR processing of pending SUMIT draft expenses.
    
    Runs for all organizations with active SUMIT, processing up to 50 drafts per org.
    Only files expenses with confidence >= 0.7 to minimize errors.
    """
    from ...services.expense_ocr_scheduler import ExpenseOCRScheduler

    scheduler = ExpenseOCRScheduler(db)
    try:
        result = await scheduler.run_all_organizations(limit=50, auto_file=True)
        logger.info(
            "OCR scheduler: processed %s orgs, filed %s total",
            result.get("orgs_processed", 0),
            result.get("total_filed", 0),
        )
        return result
    except Exception as exc:
        logger.error("OCR scheduler failed: %s", exc)
        return {"error": str(exc)}


@router.get("/cron/collection-reminders", dependencies=[Depends(_verify_cron_secret)])
async def run_collection_reminders(db: Session = Depends(get_db_session)):
    orgs = db.query(Organization).filter(
        Organization.collection_reminders_enabled.is_(True)
    ).all()

    totals = {"sms_sent": 0, "email_sent": 0, "failed": 0, "skipped_no_sumit": 0}
    errors = []
    for org in orgs:
        try:
            planned = CollectionService(db, org.id).plan_reminders(date.today())
            if not planned:
                continue
            sumit = sumit_for_org(db, org.id)

            async def email_sender(to, subject, body):
                return await send_email_smtp(to, subject, body, settings)

            if sumit is None:
                # אין SUMIT לארגון — מייל בלבד (SMS ידלג כי אין שולח)
                async def sms_sender(phone, message):
                    return False
                totals["skipped_no_sumit"] += 1
            else:
                async def sms_sender(phone, message, _s=org.collection_sms_sender, _c=sumit):
                    return bool(await _c.send_sms(SMSRequest(
                        phone_number=phone, message=message, sender_name=_s)))

            summary = await dispatch_reminders(
                db, org.id, planned, sms_sender, email_sender,
                sms_sender_name=org.collection_sms_sender)
            for k in ("sms_sent", "email_sent", "failed"):
                totals[k] += summary.get(k, 0)
        except Exception as exc:
            logger.error("Collection reminders failed for org %s: %s", org.id, exc)
            db.rollback()
            errors.append({"org": org.id, "error": str(exc)})

    return {"status": "ok", "orgs": len(orgs), "summary": totals, "errors": errors}
