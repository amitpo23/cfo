"""
Scheduled jobs endpoint, invoked by Vercel Cron.

Not behind user auth — protected by CRON_SECRET instead (Vercel sends
"Authorization: Bearer <CRON_SECRET>" automatically when the env var is set).
"""
import asyncio
import logging
import zlib
from dataclasses import replace
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from datetime import date, datetime, timedelta

from ...config import settings
from ...database import get_db_session
from ...models import (
    BankConnection,
    IntegrationConnection,
    Organization,
    SyncCheckpoint,
)
from ...services.sync_engine import SOURCE_CHECKPOINT_ENTITY, SyncEngine, SyncSkipped, get_connector_for_org
from ...services.client_automation_service import (
    mark_client_loop_result,
    repair_missing_client_roster,
    roster_sync_targets,
    run_post_sync_tasks,
)
from ...services.collection_service import CollectionService, dispatch_reminders
from ...services.email_sender import send_email_smtp
# Kept as a module-level import (unused directly here now that the daily-close
# route delegates to morning_cycle_service.run_daily_close_step) purely so
# `cfo.api.routes.cron.ensure_shaam_renewal_reminder` still exists as an
# attribute for tests/test_shaam_reminder.py's monkeypatch target; the actual
# call now happens inside run_daily_close_step via its own import.
from ...services.shaam_reminder import ensure_shaam_renewal_reminder
from ..dependencies import sumit_for_org
from ...integrations.sumit_models import SMSRequest

logger = logging.getLogger(__name__)

router = APIRouter()

EXPENSE_ENRICHMENT_CHECKPOINT = "expense_supplier_enrichment"
EXPENSE_OCR_CHECKPOINT = "expense_ocr_pipeline"
OPEN_FINANCE_SYNC_ATTEMPT_CHECKPOINT = "scheduled_sync_attempt"
OPEN_FINANCE_DAILY_ATTEMPT_LIMIT = 2
CHANNEL_PUSH_BUDGET_PROVIDER = "notifications"
CHANNEL_PUSH_BUDGET_SCOPE = "channel-push"
COLLECTION_BUDGET_SCOPE = "collection-reminders"
_OF_SYNCABLE_CONNECTION_STATUSES = frozenset({
    "ACTIVE",
    "CONNECTED",
    "COMPLETED",
})


def _verify_cron_secret(authorization: str = Header(None)):
    if not settings.cron_secret:
        raise HTTPException(status_code=503, detail="CRON_SECRET is not configured")
    if authorization != f"Bearer {settings.cron_secret}":
        raise HTTPException(status_code=401, detail="Invalid cron credentials")


def _of_consent_gate(db: Session, org_id: int) -> Optional[dict]:
    """Fail closed when a locally tracked consent journey is not usable yet.

    Organizations predating `BankConnection` keep their legacy behavior when
    no local journey row exists. Once a journey is tracked, only an explicitly
    usable provider status permits the daily sync. This gate runs before the
    budget checkpoint and before a provider connector is built.
    """
    rows = (
        db.query(BankConnection)
        .filter(
            BankConnection.organization_id == org_id,
            BankConnection.source == "open_finance",
        )
        .all()
    )
    if not rows:
        return None
    statuses = sorted({
        str(row.status or "UNKNOWN").upper()
        for row in rows
    })
    if any(status in _OF_SYNCABLE_CONNECTION_STATUSES for status in statuses):
        return None
    return {
        "organization_id": org_id,
        "source": "open_finance",
        "skipped": "consent_pending",
        "connection_statuses": statuses,
    }


# 25/08/2026 (הנחיית בעלים, ממצא בדיקה חיה על אליהב כהן/org2): ריצת
# sync מלאה אחת לארגון עושה עד 9 קריאות רשת אמיתיות מול תקציב **גלובלי**
# (כל הארגונים יחד) של 10/דקה. כשכמה ארגוני-SUMIT רצים ברצף תוך שניות —
# כל אחד תוך אותה דקת-UTC — הם מתחרים על אותו חלון ורוב הקריאות נחסמות
# fail-closed. המתנה בין ארגוני-sumit עוקבים כך שכל אחד נופל בדקה
# משלו ומקבל את מלוא ה-10/דקה. ~65 שניות (מעט מעל דקה) כדי לוודא בפועל
# מעבר לחלון-דקה חדש, לא רק תיאורטית. לא חל על Open Finance (תקציב נפרד).
SUMIT_INTER_ORG_STAGGER_SECONDS = 65


async def _run_sync_targets(db: Session, targets: set) -> list:
    """Shared sync loop for a set of (org_id, source) targets. Used by both the
    SUMIT (hourly) and Open Finance (daily-budgeted) cron routes so each keeps
    its own call-frequency policy while sharing the run/automation/roster
    bookkeeping (RSF-020: split cron paths, one engine loop)."""
    results = []
    sumit_targets_started = 0
    for org_id, source in sorted(targets):
        if source == "sumit":
            if sumit_targets_started > 0:
                await asyncio.sleep(SUMIT_INTER_ORG_STAGGER_SECONDS)
            sumit_targets_started += 1
        try:
            connector, conn_id, resolved = get_connector_for_org(db, org_id, source)
        except ValueError as exc:
            results.append({"organization_id": org_id, "source": source, "error": str(exc)})
            continue

        try:
            engine = SyncEngine(db, connector, org_id, resolved, conn_id)
            run = await engine.run_full_sync()
            if isinstance(run, SyncSkipped):
                # Another process already holds the cross-run lock for this
                # org/source -- not an error, just don't double-sync.
                results.append({
                    "organization_id": org_id, "source": resolved,
                    "skipped": run.reason, "error_summary": run.error_summary,
                })
                continue
            result = {
                "organization_id": org_id,
                "source": resolved,
                "status": run.status.value if run.status else None,
                "counts": run.counts,
            }
            result["automation"] = await run_post_sync_tasks(
                db, org_id, sources=[resolved], resume_onboarding=True
            )
            if resolved == "sumit":
                # משיכת הוצאות ממתינות — בלעדיה טבלת ההוצאות מפגרת אחרי SUMIT
                # (אודיט תאימות 2026-07-05: פיגור ~43 מסמכים). כשל כאן נרשם
                # בתוצאה ולא מפיל את הארגון/הריצה.
                try:
                    from ...services.expense_filing_service import ExpenseFilingService
                    result["expenses_pull"] = await ExpenseFilingService(
                        db, org_id
                    ).sync_pending_from_sumit()
                except Exception as exc:
                    logger.warning("Expense pull failed for org %s: %s", org_id, exc)
                    result["expenses_pull"] = {"error": str(exc)}
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

    return results


def _resolve_sumit_key(db: Session, org_id: int) -> Optional[str]:
    """המפתח שהארגון באמת ישתמש בו — מאותו מקור בדיוק כמו
    `sync_engine.get_connector_for_org`, הנתיב שהסנכרון עובר בו.

    **תיקון רגרסיה (18/08/2026).** הגרסה הראשונה קראה
    `organizations.api_credentials`, שהוא `null` בפרוד לכל הארגונים —
    אישורי SUMIT יושבים מוצפנים ב-
    `integration_connections.credentials_encrypted`. לכן השער החזיר
    `None`, נכשל-סגור כמתוכנן, ודילג על **כל ארגון שאינו org1** (שרק לו
    יש נפילה לאישורי סביבה). נמדד למחרת: org2 ו-org5 לא סונכרנו.

    שער שפותר מפתח ממקור שונה מזה שהריצה משתמשת בו אינו מגן — הוא או
    חוסם את הכול או חוסם כלום.
    """
    from ...services.credentials_vault import decrypt_credentials

    conn = db.query(IntegrationConnection).filter(
        IntegrationConnection.organization_id == org_id,
        IntegrationConnection.source == "sumit",
        IntegrationConnection.status == "active",
    ).order_by(IntegrationConnection.id).first()

    creds: dict = {}
    if conn and conn.credentials_encrypted:
        try:
            creds = decrypt_credentials(conn.credentials_encrypted) or {}
        except Exception:  # pragma: no cover - אישורים פגומים
            creds = {}
    if not creds:
        org = db.query(Organization).filter(Organization.id == org_id).first()
        creds = (org.api_credentials if org and org.api_credentials else {}) or {}

    # אישורי סביבה שייכים לארגון 1 בלבד — נפילה רחבה יותר הייתה שולחת
    # קריאות של תיק אחד בשם תיק אחר.
    env_allowed = org_id == 1
    return creds.get("api_key") or (settings.sumit_api_key if env_allowed else None)


def _per_key_daily_gate(db: Session, org_id: int) -> Optional[dict]:
    """שער ריצת-הסנכרון היומית **לכל מפתח** (הנחיית הבעלים, 17/08/2026).

    `_daily_budget_gate` חוסם לפי (ארגון, מקור). אבל `SUMIT_OFFICE_API_KEY`
    הוא הגדרה גלובלית אחת המשרתת את כל הארגונים — ולכן N ארגונים יכולים
    כל אחד לעבור את השער הקיים ולשרוף את **אותו** מפתח. המכסה בתשלום היא
    50, ולכן זה בדיוק המסלול שגרם לחיוב.

    השער כאן נתבע פר טביעת-אצבע של המפתח, אטומית בין instances.
    """
    from ...services.sumit_request_budget import (
        SumitRequestBudgetError,
        claim_daily_sync_run,
    )

    api_key = _resolve_sumit_key(db, org_id)
    try:
        claim_daily_sync_run(api_key, organization_id=org_id)
    except SumitRequestBudgetError as exc:
        return {
            "organization_id": org_id, "source": "sumit",
            "status": "skipped", "reason": str(exc),
        }
    return None


def _daily_budget_gate(db: Session, org_id: int, source: str) -> Optional[dict]:
    """Return a skip-result dict if this org/source already had a successful
    full sync within the configured interval, else None to proceed.

    Hard cost protection (owner directive 2026-07-17): BOTH providers are
    code-gated to one successful full sync per org per ~day — Open Finance
    because of its ~500/month call budget (RSF-025), SUMIT because API
    overage is billed to the client company's own payment method (the
    ILS 62.23/day incident). The cron schedule alone is not a guarantee."""
    interval_hours = (
        settings.sumit_sync_min_interval_hours
        if source == "sumit"
        else settings.of_sync_min_interval_hours
    )
    cp = db.query(SyncCheckpoint).filter(
        SyncCheckpoint.organization_id == org_id,
        SyncCheckpoint.source == source,
        SyncCheckpoint.entity_type == SOURCE_CHECKPOINT_ENTITY,
    ).first()
    if not cp or not cp.last_success_at:
        return None
    next_eligible = cp.last_success_at + timedelta(hours=interval_hours)
    if datetime.utcnow() < next_eligible:
        return {
            "organization_id": org_id,
            "source": source,
            "skipped": "daily_budget",
            "last_success_at": cp.last_success_at.isoformat(),
            "next_eligible_at": next_eligible.isoformat(),
        }
    return None


def _claim_daily_counter_slots(
    *,
    provider: str,
    scope_key: str,
    organization_id: int,
    limit_value: int,
    requested: int = 1,
) -> dict:
    """Atomically reserve up to ``requested`` slots in the existing counter.

    A separate short-lived session makes the claim durable before any outbound
    work starts. Any inability to prove the claim fails closed and reserves no
    slots in the caller's view.
    """
    from ...database import SessionLocal
    from ...services.sumit_request_budget import (
        SumitRequestLimiter,
        _db_now,
        _utc_windows,
    )

    requested = max(0, requested)
    allowed = min(requested, max(0, limit_value))
    if allowed == 0:
        return {
            "claimed": 0,
            "requested": requested,
            "skipped": "daily_budget",
        }

    budget_db = SessionLocal()
    try:
        claimed = 0
        with budget_db.begin():
            now = _db_now(budget_db)
            _, day_start, _ = _utc_windows(now)
            for _ in range(allowed):
                if not SumitRequestLimiter._claim_window(
                    budget_db,
                    provider=provider,
                    scope_key=scope_key,
                    organization_id=organization_id,
                    window_kind="day",
                    window_start=day_start,
                    limit_value=limit_value,
                    now=now,
                ):
                    break
                claimed += 1
        return {
            "claimed": claimed,
            "requested": requested,
            "skipped": None if claimed == requested else "daily_budget",
        }
    except Exception as exc:  # fail closed: no durable proof means no outbound call
        budget_db.rollback()
        logger.error(
            "Durable daily counter unavailable for %s org %s: %s",
            scope_key,
            organization_id,
            exc,
        )
        return {
            "claimed": 0,
            "requested": requested,
            "skipped": "budget_unavailable",
        }
    finally:
        budget_db.close()


def _claim_open_finance_sync_attempt(db: Session, org_id: int) -> Optional[dict]:
    """Claim a durable OF attempt before connector construction/provider I/O."""
    now = datetime.utcnow()
    checkpoint = db.query(SyncCheckpoint).filter(
        SyncCheckpoint.organization_id == org_id,
        SyncCheckpoint.source == "open_finance",
        SyncCheckpoint.entity_type == OPEN_FINANCE_SYNC_ATTEMPT_CHECKPOINT,
    ).first()
    if checkpoint and checkpoint.cooldown_until and checkpoint.cooldown_until > now:
        return {
            "organization_id": org_id,
            "source": "open_finance",
            "skipped": "failure_cooldown",
            "retry_at": checkpoint.cooldown_until.isoformat(),
        }

    budget = _claim_daily_counter_slots(
        provider="open_finance",
        scope_key=f"sync-attempt:org:{org_id}",
        organization_id=org_id,
        limit_value=OPEN_FINANCE_DAILY_ATTEMPT_LIMIT,
        requested=1,
    )
    if budget.get("claimed") == 1:
        return None
    reason = budget.get("skipped")
    return {
        "organization_id": org_id,
        "source": "open_finance",
        "skipped": (
            "budget_unavailable"
            if reason == "budget_unavailable"
            else "daily_attempt_budget"
        ),
        "attempt_limit": OPEN_FINANCE_DAILY_ATTEMPT_LIMIT,
    }


def _record_open_finance_sync_attempt(db: Session, result: dict) -> None:
    """Persist a failure cooldown; a successful run clears prior failures."""
    if result.get("skipped"):
        return
    status = str(result.get("status") or "").lower()
    failed = bool(result.get("error")) or status != "completed"
    org_id = result["organization_id"]
    checkpoint = db.query(SyncCheckpoint).filter(
        SyncCheckpoint.organization_id == org_id,
        SyncCheckpoint.source == "open_finance",
        SyncCheckpoint.entity_type == OPEN_FINANCE_SYNC_ATTEMPT_CHECKPOINT,
    ).first()
    if checkpoint is None:
        checkpoint = SyncCheckpoint(
            organization_id=org_id,
            source="open_finance",
            entity_type=OPEN_FINANCE_SYNC_ATTEMPT_CHECKPOINT,
        )
        db.add(checkpoint)
    now = datetime.utcnow()
    if failed:
        checkpoint.consecutive_failures = (
            checkpoint.consecutive_failures or 0
        ) + 1
        checkpoint.cooldown_until = now + timedelta(
            hours=settings.sync_circuit_open_hours,
        )
    else:
        checkpoint.consecutive_failures = 0
        checkpoint.cooldown_until = None
        checkpoint.last_success_at = now
    try:
        db.commit()
    except IntegrityError:
        # Concurrent first attempts can race on the checkpoint's unique key.
        # The durable attempt counter is already consumed; preserve fail-closed
        # behavior and let the winning transaction own the cooldown row.
        db.rollback()
        logger.warning(
            "Concurrent Open Finance attempt checkpoint for org %s",
            org_id,
        )


def _limit_reminder_deliveries(planned: list, claimed_slots: int) -> list:
    """Return reminder copies containing at most ``claimed_slots`` channels."""
    limited = []
    remaining = max(0, claimed_slots)
    for reminder in planned:
        phone = None
        email = None
        if reminder.phone and remaining:
            phone = reminder.phone
            remaining -= 1
        if reminder.email and remaining:
            email = reminder.email
            remaining -= 1
        if phone or email:
            limited.append(replace(reminder, phone=phone, email=email))
        if remaining == 0:
            break
    return limited


def _claim_channel_push_budget(org_id: int) -> Optional[dict]:
    budget = _claim_daily_counter_slots(
        provider=CHANNEL_PUSH_BUDGET_PROVIDER,
        scope_key=f"{CHANNEL_PUSH_BUDGET_SCOPE}:org:{org_id}",
        organization_id=org_id,
        limit_value=settings.channel_push_daily_limit,
        requested=1,
    )
    if budget.get("claimed") == 1:
        return None
    return {
        "organization_id": org_id,
        "skipped": (
            "budget_unavailable"
            if budget.get("skipped") == "budget_unavailable"
            else "daily_push_budget"
        ),
        "daily_limit": settings.channel_push_daily_limit,
    }


def _claim_periodic_provider_budget(
    db: Session,
    *,
    org_id: int,
    source: str,
    entity_type: str,
    interval_hours: int,
) -> Optional[dict]:
    """Atomically claim a provider-backed periodic operation.

    Unlike ``_daily_budget_gate`` (which follows a completed full sync), this
    gate starts its 20-hour cooldown *before* the first provider call. A failed
    or rate-limited enrichment therefore cannot be hammered by a repeated cron
    invocation. PostgreSQL uses a non-blocking transaction advisory lock;
    SQLite remains a deterministic single-process path for tests.
    """
    now = datetime.utcnow()
    bind = db.get_bind()
    dialect = getattr(getattr(bind, "dialect", None), "name", "sqlite")
    if dialect == "postgresql":
        operation_hash = (
            zlib.crc32(f"{source}:{entity_type}".encode("utf-8"))
            & 0x7FFFFFFF
        )
        acquired = db.execute(
            text("SELECT pg_try_advisory_xact_lock(:org_id, :operation_hash)"),
            {"org_id": org_id, "operation_hash": operation_hash},
        ).scalar()
        if not acquired:
            db.rollback()
            return {
                "organization_id": org_id,
                "source": source,
                "skipped": "locked",
            }

    checkpoint = db.query(SyncCheckpoint).filter(
        SyncCheckpoint.organization_id == org_id,
        SyncCheckpoint.source == source,
        SyncCheckpoint.entity_type == entity_type,
    ).first()
    if checkpoint and checkpoint.cooldown_until and checkpoint.cooldown_until > now:
        db.commit()  # releases the transaction-scoped advisory lock
        return {
            "organization_id": org_id,
            "source": source,
            "skipped": "daily_budget",
        }

    if checkpoint is None:
        checkpoint = SyncCheckpoint(
            organization_id=org_id,
            source=source,
            entity_type=entity_type,
        )
        db.add(checkpoint)
    checkpoint.cooldown_until = now + timedelta(hours=interval_hours)
    try:
        db.commit()
    except IntegrityError:
        # A concurrent first-ever claim may win the unique key between our
        # SELECT and INSERT. Fail closed: this invocation performs no API call.
        db.rollback()
        return {
            "organization_id": org_id,
            "source": source,
            "skipped": "locked",
        }
    return None


def _finish_periodic_provider_attempt(
    db: Session,
    *,
    org_id: int,
    source: str,
    entity_type: str,
    success: bool,
) -> None:
    checkpoint = db.query(SyncCheckpoint).filter(
        SyncCheckpoint.organization_id == org_id,
        SyncCheckpoint.source == source,
        SyncCheckpoint.entity_type == entity_type,
    ).first()
    if checkpoint is None:
        return
    if success:
        checkpoint.last_success_at = datetime.utcnow()
        checkpoint.consecutive_failures = 0
    else:
        checkpoint.consecutive_failures = (
            checkpoint.consecutive_failures or 0
        ) + 1
    db.commit()


# Backward-compatible alias (existing tests/callers).
_of_budget_gate = _daily_budget_gate


@router.get("/cron/sync-sumit", dependencies=[Depends(_verify_cron_secret)])
async def scheduled_sync_sumit(db: Session = Depends(get_db_session)):
    """Daily: run a sync for every organization with an active SUMIT integration.

    Open Finance is intentionally excluded here -- see /cron/sync-open-finance,
    which enforces its own daily call budget (RSF-020/021).
    """
    repaired_roster = repair_missing_client_roster(db)
    targets = {
        (conn.organization_id, conn.source)
        for conn in db.query(IntegrationConnection).filter(
            IntegrationConnection.status == "active",
            IntegrationConnection.source == "sumit",
        ).all()
    }
    targets.update((org_id, src) for org_id, src in roster_sync_targets(db) if src == "sumit")
    if settings.sumit_api_key:
        targets.add((1, "sumit"))

    # Hard daily budget (owner directive 2026-07-17): SUMIT API overage is
    # billed to the client's own card — gate in code, not just in the schedule.
    results = []
    to_run = set()
    for org_id, source in sorted(targets):
        gated = _daily_budget_gate(db, org_id, source)
        if gated:
            results.append(gated)
            continue
        # שער שני, בלתי-תלוי: ריצה אחת ביום **למפתח**. הראשון חוסם לפי
        # ארגון ולכן אינו רואה שני ארגונים החולקים את מפתח המשרד.
        key_gated = _per_key_daily_gate(db, org_id)
        if key_gated:
            results.append(key_gated)
            continue
        to_run.add((org_id, source))

    results.extend(await _run_sync_targets(db, to_run))
    return {"synced": len(results), "repaired_roster": repaired_roster, "results": results}


@router.get("/cron/refresh-sumit-quota", dependencies=[Depends(_verify_cron_secret)])
async def scheduled_refresh_sumit_quota(db: Session = Depends(get_db_session)):
    """W2.1 (אישור בעלים 20/08/2026): רענון יומי של מכסת הפעולות-בתשלום.

    קריאת `listquotas` **חינמית** אחת ליום לכל ארגון עם SUMIT פעיל
    (≈30 בחודש). בלי מדידה טרייה — כל פעולה בתשלום חסומה fail-closed,
    ולכן זה ה-cron שמחזיק את הזמינות של `getpdf`/`getdetails`/יצירת
    מסמכים. שער עמיד: רענון אחד ליום פר-ארגון גם אם ה-cron נורה פעמיים.
    """
    from ...database import SessionLocal
    from ...services.sumit_quota import refresh_quota_measurement
    from ...services.sumit_request_budget import (
        SumitRequestBudgetError,
        SumitRequestLimiter,
        _utc_windows,
    )
    from datetime import datetime, timezone

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
        api_key = _resolve_sumit_key(db, org_id)
        if not api_key:
            results.append({
                "organization_id": org_id, "status": "skipped",
                "reason": "no_sumit_key",
            })
            continue
        # שער עמיד: רענון מכסה אחד ליום פר-ארגון (scope נפרד משאר החלונות).
        now = datetime.now(timezone.utc)
        _, day_start, _ = _utc_windows(now)
        budget_db = SessionLocal()
        try:
            with budget_db.begin():
                claimed = SumitRequestLimiter._claim_window(
                    budget_db,
                    scope_key=f"quota-refresh:org:{org_id}",
                    organization_id=org_id,
                    window_kind="day",
                    window_start=day_start,
                    limit_value=1,
                    now=now,
                )
        finally:
            budget_db.close()
        if not claimed:
            results.append({
                "organization_id": org_id, "status": "skipped",
                "reason": "already_refreshed_today",
            })
            continue

        from ...services.sync_engine import get_connector_for_org
        try:
            connector, _conn_id, _source = get_connector_for_org(
                db, org_id, preferred_source="sumit",
            )
            integration = await connector._get_client()
            try:
                snapshot = await refresh_quota_measurement(db, org_id, integration)
            finally:
                await integration.client.aclose()
            if snapshot is None:
                results.append({
                    "organization_id": org_id, "status": "no_measurement",
                    "reason": "listquotas response had no paid-actions row",
                })
            else:
                results.append({
                    "organization_id": org_id, "status": "ok",
                    "snapshot": snapshot.as_dict(),
                })
        except SumitRequestBudgetError as exc:
            results.append({
                "organization_id": org_id, "status": "skipped",
                "reason": str(exc),
            })
        except Exception as exc:  # honest-null: כשל נרשם, לא מוסתר
            results.append({
                "organization_id": org_id, "status": "error",
                "reason": str(exc)[:300],
            })
    return {"refreshed": len(targets), "results": results}


@router.get("/cron/sync-open-finance", dependencies=[Depends(_verify_cron_secret)])
async def scheduled_sync_open_finance(db: Session = Depends(get_db_session)):
    """Daily: run a sync for every organization with an active Open Finance
    integration, gated to at most one successful full sync per org per
    OF_SYNC_MIN_INTERVAL_HOURS (default 20h) to stay well inside the ~500/month
    call budget (RSF-025)."""
    targets = {
        (conn.organization_id, conn.source)
        for conn in db.query(IntegrationConnection).filter(
            IntegrationConnection.status == "active",
            IntegrationConnection.source == "open_finance",
        ).all()
    }
    targets.update((org_id, src) for org_id, src in roster_sync_targets(db) if src == "open_finance")

    results = []
    to_run = set()
    for org_id, source in sorted(targets):
        consent_gated = _of_consent_gate(db, org_id)
        if consent_gated:
            results.append(consent_gated)
            continue
        gated = _of_budget_gate(db, org_id, source)
        if gated:
            results.append(gated)
            continue
        attempt_gated = _claim_open_finance_sync_attempt(db, org_id)
        if attempt_gated:
            results.append(attempt_gated)
            continue
        to_run.add((org_id, source))

    attempt_results = await _run_sync_targets(db, to_run)
    for result in attempt_results:
        _record_open_finance_sync_attempt(db, result)
    results.extend(attempt_results)
    return {"synced": len(results), "results": results}


@router.get("/cron/sync", dependencies=[Depends(_verify_cron_secret)])
async def scheduled_sync(db: Session = Depends(get_db_session)):
    """Legacy alias, kept for backward compatibility with existing Vercel Cron
    config during rollout -- SUMIT-only (see /cron/sync-sumit). Open Finance
    moved to its own daily-budgeted /cron/sync-open-finance (RSF-020/021)."""
    return await scheduled_sync_sumit(db)


@router.get("/cron/enrich-expenses", dependencies=[Depends(_verify_cron_secret)])
async def scheduled_enrich_expenses(db: Session = Depends(get_db_session)):
    """העשרה יומית של הוצאות (שם ספק + ח.פ) מ-SUMIT, באצווה חסומת-קצב.

    ה-DB claim מתבצע לפני בניית הקונקטור וחוסם ניסיון נוסף ל-20 שעות, גם
    אם הניסיון הראשון נכשל או הגיע ל-rate-limit.
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
        if settings.sumit_enrichment_daily_action_limit == 0:
            results.append({
                "organization_id": org_id,
                "source": "sumit",
                "skipped": "disabled_by_cost_budget",
            })
            continue
        gated = _claim_periodic_provider_budget(
            db,
            org_id=org_id,
            source="sumit",
            entity_type=EXPENSE_ENRICHMENT_CHECKPOINT,
            interval_hours=settings.sumit_sync_min_interval_hours,
        )
        if gated:
            results.append(gated)
            continue
        try:
            res = await ExpenseFilingService(db, organization_id=org_id).resolve_supplier_names(
                limit=settings.sumit_enrichment_daily_action_limit,
                delay=0.4,
            )
            _finish_periodic_provider_attempt(
                db,
                org_id=org_id,
                source="sumit",
                entity_type=EXPENSE_ENRICHMENT_CHECKPOINT,
                success=not bool(res.get("rate_limited")),
            )
            results.append({"organization_id": org_id, **res})
        except Exception as exc:
            logger.warning("Expense enrichment failed for org %s: %s", org_id, exc)
            db.rollback()
            _finish_periodic_provider_attempt(
                db,
                org_id=org_id,
                source="sumit",
                entity_type=EXPENSE_ENRICHMENT_CHECKPOINT,
                success=False,
            )
            results.append({"organization_id": org_id, "error": str(exc)})
    return {"enriched_orgs": len(results), "results": results}


@router.get("/cron/process-ocr", dependencies=[Depends(_verify_cron_secret)])
async def scheduled_process_ocr(db: Session = Depends(get_db_session)):
    """Daily OCR processing after provider sync/enrichment (02:45 UTC).
    
    Stops before SUMIT when OCR_LLM_ENABLED is false. When enabled, each org
    claims a 20-hour provider budget before getpdf and processes at most the
    configured OCR_DAILY_DOCUMENT_LIMIT (hard-capped at 25).
    """
    from ...services.expense_ocr_scheduler import ExpenseOCRScheduler

    if not settings.ocr_llm_enabled:
        return {
            "status": "skipped",
            "skipped": "ocr_llm_disabled",
            "orgs_processed": 0,
            "results": [],
        }
    if settings.ocr_daily_document_limit == 0:
        return {
            "status": "skipped",
            "skipped": "disabled_by_cost_budget",
            "orgs_processed": 0,
            "results": [],
        }

    targets = {
        conn.organization_id
        for conn in db.query(IntegrationConnection).filter(
            IntegrationConnection.status == "active",
            IntegrationConnection.source == "sumit",
        ).all()
    }
    scheduler = ExpenseOCRScheduler(db)
    results = []
    totals = {"scanned": 0, "filed": 0, "flagged": 0, "errors": 0}
    for org_id in sorted(targets):
        gated = _claim_periodic_provider_budget(
            db,
            org_id=org_id,
            source="sumit",
            entity_type=EXPENSE_OCR_CHECKPOINT,
            interval_hours=settings.sumit_sync_min_interval_hours,
        )
        if gated:
            results.append(gated)
            continue
        try:
            org_result = await scheduler.run_scheduled_ocr(
                org_id,
                limit=settings.ocr_daily_document_limit,
                auto_file=True,
            )
            rate_limited = any(
                item.get("status") == "rate_limited"
                for item in org_result.get("results", [])
            )
            _finish_periodic_provider_attempt(
                db,
                org_id=org_id,
                source="sumit",
                entity_type=EXPENSE_OCR_CHECKPOINT,
                success=not rate_limited and not bool(org_result.get("errors")),
            )
            org_result["organization_id"] = org_id
            results.append(org_result)
            for key in totals:
                totals[key] += org_result.get(key, 0)
        except Exception as exc:
            logger.error("Scheduled OCR failed for org %s: %s", org_id, exc)
            db.rollback()
            _finish_periodic_provider_attempt(
                db,
                org_id=org_id,
                source="sumit",
                entity_type=EXPENSE_OCR_CHECKPOINT,
                success=False,
            )
            results.append({"organization_id": org_id, "error": str(exc)})

    return {
        "orgs_processed": len(targets),
        "total_scanned": totals["scanned"],
        "total_filed": totals["filed"],
        "total_flagged": totals["flagged"],
        "total_errors": totals["errors"],
        "results": results,
    }


@router.get("/cron/collection-reminders", dependencies=[Depends(_verify_cron_secret)])
async def run_collection_reminders(db: Session = Depends(get_db_session)):
    orgs = db.query(Organization).filter(
        Organization.collection_reminders_enabled.is_(True)
    ).all()

    totals = {
        "sms_sent": 0,
        "email_sent": 0,
        "failed": 0,
        "skipped_no_sumit": 0,
        "delivery_attempts": 0,
        "budget_skipped": 0,
    }
    errors = []
    budgets = []
    for org in orgs:
        try:
            planned = CollectionService(db, org.id).plan_reminders(date.today())
            if not planned:
                continue
            delivery_count = sum(
                int(bool(reminder.phone)) + int(bool(reminder.email))
                for reminder in planned
            )
            requested = min(
                delivery_count,
                settings.collection_reminder_batch_limit,
            )
            budget = _claim_daily_counter_slots(
                provider=CHANNEL_PUSH_BUDGET_PROVIDER,
                scope_key=f"{COLLECTION_BUDGET_SCOPE}:org:{org.id}",
                organization_id=org.id,
                limit_value=settings.collection_reminder_batch_limit,
                requested=requested,
            )
            claimed = int(budget.get("claimed") or 0)
            totals["delivery_attempts"] += claimed
            totals["budget_skipped"] += max(0, delivery_count - claimed)
            budgets.append({
                "organization_id": org.id,
                "planned_deliveries": delivery_count,
                "claimed": claimed,
                "skipped": max(0, delivery_count - claimed),
                "reason": budget.get("skipped"),
            })
            if claimed == 0:
                if budget.get("skipped") == "budget_unavailable":
                    logger.error(
                        "Collection reminder budget unavailable for org %s",
                        org.id,
                    )
                continue
            planned = _limit_reminder_deliveries(planned, claimed)
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

    return {
        "status": "ok",
        "orgs": len(orgs),
        "summary": totals,
        "budgets": budgets,
        "errors": errors,
    }


@router.get("/cron/daily-close", dependencies=[Depends(_verify_cron_secret)])
def run_daily_close(db: Session = Depends(get_db_session)):
    """נקודת קצה ותיקה שאינה מתוזמנת בנפרד ב-vercel.json. מחזור הבוקר
    המתוזמן ב-03:45 UTC מפעיל את אותו צעד אחרי סנכרוני הספקים וסריקת הפערים.
    מריץ data_quality.run_checks ושומר תמונת-מצב יומית (daily_snapshots) לכל
    ארגון פעיל — הבסיס למגמות ולדשבורד (docs/REZEF_DATA_INTEGRITY_PLAN.md
    סעיף ג2). אידמפוטנטי (UPSERT לפי org+snapshot_date). כשל בארגון אחד
    מבודד ולא מפיל את הריצה עבור האחרים.

    PR4 (bookkeeper daily-cycle plan): thin wrapper only now — the actual
    snapshot logic lives in morning_cycle_service.run_daily_close_step so
    both this legacy route and the fuller /cron/bookkeeper-morning cycle
    share one implementation. This route calls it with no
    parity/credit/reconcile/expense-queue inputs (honest-null: it alone has
    no other steps' data to offer), same as before it existed as its own
    function."""
    from ...services.morning_cycle_service import run_daily_close_step

    today = date.today()
    orgs = db.query(Organization).filter(Organization.is_active.is_(True)).all()
    results = []
    errors = []
    for org in orgs:
        try:
            step_result = run_daily_close_step(db, org.id, today)
            results.append({
                "organization_id": org.id, "status": "ok",
                "data_quality": step_result["data_quality"],
                "issues_count": step_result["issues_count"],
            })
        except Exception as exc:
            logger.error("Daily close failed for org %s: %s", org.id, exc)
            db.rollback()
            errors.append({"org": org.id, "error": str(exc)})

    return {"status": "ok", "orgs": len(orgs), "snapshots": len(results),
            "results": results, "errors": errors}


@router.get("/cron/bookkeeper-morning", dependencies=[Depends(_verify_cron_secret)])
def run_bookkeeper_morning(
    db: Session = Depends(get_db_session),
    org_id: Optional[int] = None,
    force: bool = False,
):
    """יומי (03:45 UTC — 06:45 קיץ/05:45 חורף בישראל): מחזור-
    הבוקר המלא של מנהל החשבונות (PR4 של תוכנית מחזור-הבוקר) — parity,
    bank_anomalies, reconcile, expense_queue, credit_line, daily_close,
    debtors, בסדר-תלות אחד (ר' morning_cycle_service). ללא קריאות API
    חדשות ל-SUMIT/Open Finance — קורא רק את מה שכבר סונכרן.

    ?org_id=<int> מריץ ארגון בודד בלבד (לבדיקה/תיקון ידני); בלעדיו — כל
    הארגונים הפעילים. ?force=true עוקף את שער האידמפוטנטיות (מריץ מחדש גם
    אם המחזור כבר הושלם היום לארגון זה)."""
    from ...services.morning_cycle_service import run_all_organizations, run_morning_cycle

    # זריעת אינדקס הידע — צעד גלובלי אחד, לפני הלולאה הפר-ארגונית. הידע
    # מקצועי ולא נתוני לקוח, ולכן אינו מוכפל פר ארגון.
    #
    # למה כאן: ה-KB משתנה רק בפריסה, וקריאת 25 קבצים היא זולה. בלי זריעה
    # `kb_index.search` נופל תמיד חזרה לקבצים והאינדקס הוא משקל מת.
    #
    # כשל כאן **אינו** מפיל את המחזור: האחזור עדיין עובד דרך הקבצים.
    kb_seed: dict = {}
    try:
        from ...services import kb_index as _kb_index
        kb_seed = _kb_index.reindex(db)
    except Exception as exc:  # pragma: no cover - נתיב עמידות
        logger.warning("KB reindex skipped: %s", exc)
        db.rollback()
        kb_seed = {"error": str(exc)}

    today = date.today()
    if org_id is not None:
        try:
            result = run_morning_cycle(db, org_id, today, force=force)
            return {"status": "ok", "orgs": 1, "results": [result],
                    "errors": [], "kb_index": kb_seed}
        except Exception as exc:
            logger.error("Bookkeeper morning cycle failed for org %s: %s", org_id, exc)
            db.rollback()
            return {"status": "ok", "orgs": 1, "results": [],
                    "errors": [{"organization_id": org_id, "error": str(exc)}]}

    outcome = run_all_organizations(db, today, force=force)
    outcome["kb_index"] = kb_seed
    return outcome


@router.get("/cron/bank-gap-scan", dependencies=[Depends(_verify_cron_secret)])
def run_bank_gap_scan(db: Session = Depends(get_db_session)):
    """יומי (03:15 UTC — אחרי sync-open-finance של 02:00): סורק לכל ארגון
    פעיל תנועות בנק יוצאות חדשות ללא מסמך הנה"ח, ויוצר CfoInsight
    (insight_type="missing_document") לכל תנועה חדשה. כשל בארגון אחד
    מבודד (rollback + נרשם ב-errors) ולא מפיל את הריצה עבור האחרים —
    ראה services/bank_expense_gap.scan_and_alert."""
    from ...services.bank_expense_gap import scan_and_alert

    orgs = db.query(Organization).filter(Organization.is_active.is_(True)).all()
    totals = {"created": 0, "skipped_existing": 0, "scanned": 0}
    errors = []
    for org in orgs:
        try:
            result = scan_and_alert(db, org.id)
            for k in totals:
                totals[k] += result.get(k, 0)
        except Exception as exc:
            logger.error("Bank gap scan failed for org %s: %s", org.id, exc)
            db.rollback()
            errors.append({"org": org.id, "error": str(exc)})

    return {"status": "ok", "orgs": len(orgs), "summary": totals, "errors": errors}


@router.get("/cron/channel-alerts", dependencies=[Depends(_verify_cron_secret)])
async def run_channel_alerts(db: Session = Depends(get_db_session)):
    """דוחף לערוצי השיחה המקושרים (Telegram/WhatsApp) את ה-
    CfoInsight החדשים בסיכון high/critical, פר ארגון פעיל.

    דדופ אמיתי: הסינון הוא לפי created_at ביחס ל-last_push_at המקסימלי בין
    זהויות הערוץ המאומתות/לא-מבוטלות/opted-in של הארגון (אותה קבוצה בדיוק
    ש-channel_notifier.recipients_for מחזירה, ו-push_to_organization מעדכן
    לה last_push_at רק בשליחה שהצליחה בפועל) — כך שתובנה שכבר נדחפה בהצלחה
    לא תיבחר שוב בהרצה הבאה. אם אף זהות מעולם לא קיבלה push (last_push_at
    כולן None — כולל ארגון חדש לגמרי), אין בסיס היסטורי להשוואה; הנפילה
    לחלון 24 שעות אחורה (ולא "כל ההיסטוריה") מונעת הצפה בהרצה הראשונה של
    ארגון ותיק עם עשרות תובנות ישנות."""
    from ...models import CfoInsight
    from ...services.channel_notifier import push_to_organization, recipients_for

    orgs = db.query(Organization).filter(Organization.is_active.is_(True)).all()
    total_pushed = 0
    total_insights = 0
    budget_skipped = 0
    results = []

    for org in orgs:
        try:
            identities = recipients_for(db, org.id)
            if not identities:
                continue

            last_pushes = [i.last_push_at for i in identities if i.last_push_at]
            query = db.query(CfoInsight).filter(
                CfoInsight.organization_id == org.id,
                CfoInsight.status == "active",
                CfoInsight.severity.in_(("high", "critical")),
            )
            if last_pushes:
                query = query.filter(CfoInsight.created_at > max(last_pushes))
            else:
                query = query.filter(CfoInsight.created_at >= datetime.utcnow() - timedelta(hours=24))
            insights = query.order_by(CfoInsight.created_at.asc()).all()

            if not insights:
                continue

            total_insights += len(insights)
            severity = "critical" if any(i.severity == "critical" for i in insights) else "high"

            lines = [f"⚠️ {len(insights)} התרעות חדשות:"]
            for insight in insights[:5]:
                lines.append(f"- [{insight.severity}] {insight.title}")
            if len(insights) > 5:
                lines.append(f"ועוד {len(insights) - 5}")
            text = "\n".join(lines)

            budget_gated = _claim_channel_push_budget(org.id)
            if budget_gated:
                budget_skipped += 1
                results.append(budget_gated)
                logger.warning(
                    "Channel alert skipped for org %s: %s",
                    org.id,
                    budget_gated["skipped"],
                )
                continue
            result = await push_to_organization(db, org.id, text, severity=severity)
            if result.get("sent"):
                total_pushed += 1
            results.append({
                "organization_id": org.id,
                "status": result.get("status"),
                "sent": result.get("sent", 0),
            })
        except Exception as exc:
            logger.error("Channel alert push failed for org %s: %s", org.id, exc)
            db.rollback()
            results.append({"organization_id": org.id, "error": str(exc)})

    return {
        "organizations": len(orgs),
        "pushed": total_pushed,
        "insights": total_insights,
        "budget_skipped": budget_skipped,
        "results": results,
    }


@router.get("/cron/roster-health", dependencies=[Depends(_verify_cron_secret)])
async def scheduled_roster_health(db: Session = Depends(get_db_session)):
    """יומי: מוודא שכל תיק בפנקס המשרד באמת משתתף בלולאת הסנכרון.

    `scheduled_sync_sumit` בונה את היעדים מ-`IntegrationConnection.status ==
    "active"`. חיבור שעבר ל-`paused`/`inactive` מפיל את הארגון מה-cron
    **בשקט** — אין ריצה כושלת, פשוט אין ריצה. באודיט 05/08/2026 נמצא ש-org 2
    נשר ב-17/07 ו-org 3 ב-06/07, שבועות בלי שאיש ידע.

    השער הזה קורא בלבד ואינו מחייה חיבורים — החייאה היא החלטת בעלים.
    """
    from ...services.channel_notifier import push_to_organization, recipients_for
    from ...services.roster_coverage import (
        coverage_alert_lines,
        persist_coverage_findings,
        roster_coverage_report,
    )

    # ארגון המשרד. `roster_coverage_report` מקבל פרמטר, אבל היעד של ה-push
    # חייב להיות אותו ארגון שעליו דיווחנו — לכן מוגדר פעם אחת ומשותף לשניהם.
    office_org_id = 1

    report = roster_coverage_report(db, office_organization_id=office_org_id)
    lines = coverage_alert_lines(report)

    # עקבה ב-DB **לפני** ה-push. הדחיפה היא לערוץ שיחה, וכל הערוצים
    # ריקים בפרוד — כלומר עד היום הבקרה חישבה ממצא מדויק וזרקה אותו.
    # CfoInsight נראה ב-UI בלי תלות בטלגרם/וואטסאפ. כשל בשמירה אינו
    # מפיל את הבקרה.
    try:
        coverage = persist_coverage_findings(db)
    except Exception as exc:  # pragma: no cover - נתיב עמידות
        logger.error("Coverage persistence failed: %s", exc)
        db.rollback()
        coverage = {"error": str(exc)}

    pushed = False
    push_budget = {"status": "not_needed"}
    if lines:
        recipients = recipients_for(db, office_org_id)
        if not recipients:
            push_budget = {"skipped": "no_recipients"}
        else:
            budget_gated = _claim_channel_push_budget(office_org_id)
            if budget_gated:
                push_budget = budget_gated
                logger.warning(
                    "Roster health push skipped for org %s: %s",
                    office_org_id,
                    budget_gated["skipped"],
                )
            else:
                push_budget = {
                    "organization_id": office_org_id,
                    "claimed": 1,
                    "daily_limit": settings.channel_push_daily_limit,
                }
                try:
                    result = await push_to_organization(
                        db, office_org_id, "\n".join(lines), severity="high",
                    )
                    pushed = bool(result.get("sent"))
                    push_budget["status"] = result.get("status")
                except Exception as exc:  # ההתרעה לא מפילה את הבקרה
                    logger.error("Roster health push failed: %s", exc)
                    db.rollback()
                    push_budget["status"] = "error"
                    push_budget["error"] = str(exc)

    return {"report": report, "alerted": pushed, "alert_lines": lines,
            "coverage": coverage, "push_budget": push_budget}
