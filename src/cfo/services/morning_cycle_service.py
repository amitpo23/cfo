"""Morning-cycle orchestrator (PR4 of the bookkeeper daily-cycle plan).

Runs the accountant's morning order-of-operations for one organization, end
to end, entirely against Rezef's own Postgres data — **zero new SUMIT/Open
Finance API calls** (those happen on their own cron schedules: sync-sumit
01:30 UTC, sync-open-finance 02:00 UTC, enrichment 02:15 UTC and process-ocr
02:45 UTC). This module only reads and reasons over what has already been
synced.

Step order (accountant-judgment, advisor-mandated — see
docs/bookkeeper_kb/00-role-and-daily-order.md, "לא נוגעים במספר לפני שיודעים
שהוא טרי ואמין"):

  1. parity          — is anything even fresh/consistent today? (parity_service)
  2. bank_anomalies   — same-morning bounced-check/failed-standing-order scan
  3. reconcile        — bank <-> books matching, feeds unreconciled_count
  4. expense_queue    — filing-queue counts only (NO OCR — that's its own cron)
  5. credit_line      — overdraft-framework breach/warning check
  6. daily_close      — DailySnapshot upsert (absorbs former cron.run_daily_close)
  7. debtors          — AR aging summary + top-5 overdue (read-only, no send)

Each step runs in its own try/except: a step failure is recorded as
`{"status": "error", "error": ...}` in the result and rolls back the session
so the next step gets a clean transaction — it never blocks later steps
(per-step isolation). `run_all_organizations` adds the same isolation at the
org level (one org's exception never drops another org's run).

Idempotency: DailySnapshot rows are upserted (org, snapshot_date unique);
CfoInsight rows are upserted by fingerprint. Two calls for the same
(org, today) with `force=True` both fully recompute and land on the same
single row, updated in place — never a duplicate. With the default
`force=False`, a second call on the same day for an org whose cycle already
completed today (DailySnapshot.cycle_status already set) is a cheap no-op
(`status: "skipped"`) instead of re-doing bank reconciliation/anomaly scans
that already ran that morning — the same "gate unless forced" shape already
used by cron.py's `_daily_budget_gate` for the sync crons.
"""
from __future__ import annotations

import logging
import time
from calendar import monthrange
from datetime import date, datetime, timedelta
from typing import Any, Optional

from . import bank_anomalies, credit_line_service, parity_service
from .ar_ap_aging import ARAPAgingService
from .bank_reconciliation import reconcile_organization, unreconciled_bank_count

logger = logging.getLogger(__name__)

# Cycle-status thresholds (docs/BOOKKEEPER_ARMY_OPERATING_MODEL.md §2.1 exit
# conditions: filing queue <=20, zero exceptions >48h, freshness green).
OPEN_EXPENSE_DRAFTS_GREEN_MAX = 20
EXCEPTIONS_DEADLINE_RISK_DAYS = 3

# Statuses considered "in the filing queue" for the expense-drafts count —
# everything that is NOT yet a filed, done state.
OPEN_EXPENSE_STATUSES = ("pending", "review", "error", "duplicate")
EXCEPTION_AGE_HOURS = 48

_DEADLINE_DAYS = (15, 19, 23)


def days_to_next_deadline(today: date) -> int:
    """Days from `today` to the nearest of the 15th/19th/23rd of the month,
    inclusive-forward (today being one of those days => 0). Rolls to next
    month's 15th once past the 23rd. Pure function — no DB, no I/O."""
    last_day = monthrange(today.year, today.month)[1]
    for day in _DEADLINE_DAYS:
        target_day = min(day, last_day)
        if today.day <= target_day:
            return (date(today.year, today.month, target_day) - today).days

    if today.month == 12:
        target = date(today.year + 1, 1, 15)
    else:
        target = date(today.year, today.month + 1, 15)
    return (target - today).days


def compute_cycle_status(
    *,
    parity_status: Optional[str],
    open_expense_drafts: Optional[int],
    exceptions_over_48h: Optional[int],
    credit_status: Optional[str],
    days_to_next_deadline: Optional[int],
    bank_anomaly_today: bool,
) -> str:
    """Pure classification of the morning's overall health.

    Note on "freshness ok": `parity_status` already folds in freshness —
    `parity_service.run_daily_parity` reports "stale" precisely when a sync
    source (SUMIT/Open Finance) is stale, so `parity_status == "ok"` already
    implies freshness passed; a separate freshness flag would be redundant.

    red    — credit breach, OR parity mismatch, OR (exceptions_over_48h > 0
             AND days_to_next_deadline <= 3), OR a bank anomaly dated today.
    green  — parity ok AND open_expense_drafts <= 20 AND exceptions_over_48h
             == 0 AND no credit breach AND no bank anomaly today. Requires
             every input to actually be known (honest-null: unknown inputs
             can never be silently treated as "fine").
    yellow — everything else (including any unknown input, and parity
             "stale" specifically — stale data is never "green").
    """
    credit_breach = credit_status == "breach"
    parity_mismatch = parity_status == "mismatch"
    exceptions_deadline_risk = (
        exceptions_over_48h is not None and exceptions_over_48h > 0
        and days_to_next_deadline is not None
        and days_to_next_deadline <= EXCEPTIONS_DEADLINE_RISK_DAYS
    )

    if credit_breach or parity_mismatch or exceptions_deadline_risk or bank_anomaly_today:
        return "red"

    unknown_inputs = (
        parity_status is None or open_expense_drafts is None or exceptions_over_48h is None
    )
    if unknown_inputs:
        return "yellow"

    is_green = (
        parity_status == "ok"
        and open_expense_drafts <= OPEN_EXPENSE_DRAFTS_GREEN_MAX
        and exceptions_over_48h == 0
        and not credit_breach
        and not bank_anomaly_today
    )
    return "green" if is_green else "yellow"


def _run_step(db, fn) -> dict[str, Any]:
    """Execute one morning-cycle step in isolation: never lets an exception
    propagate to later steps, and rolls back so the next step starts with a
    clean session (a raised exception mid-step can otherwise poison the
    session for every subsequent query)."""
    start = time.monotonic()
    try:
        data = fn()
        elapsed_ms = round((time.monotonic() - start) * 1000, 1)
        return {"status": "ok", "elapsed_ms": elapsed_ms, "result": data}
    except Exception as exc:  # noqa: BLE001 — per-step isolation is the point
        db.rollback()
        elapsed_ms = round((time.monotonic() - start) * 1000, 1)
        logger.error("Morning cycle step failed: %s", exc)
        return {"status": "error", "elapsed_ms": elapsed_ms, "error": str(exc)}


def _step_parity(db, org_id: int, today: date) -> dict[str, Any]:
    return parity_service.check_and_alert(db, org_id, today)


def _step_bank_anomalies(db, org_id: int, today: date) -> dict[str, Any]:
    since = today - timedelta(days=3)  # covers weekend gaps
    result = bank_anomalies.scan_and_alert(db, org_id, since=since)
    # Read-only re-scan bounded to `today` itself, purely to answer "was an
    # anomaly found *today*" for cycle_status — scan_and_alert only returns
    # counts, not per-hit dates.
    today_hits = bank_anomalies.scan_bank_anomalies(db, org_id, since=today)
    result["anomaly_today"] = len(today_hits) > 0
    return result


def _step_reconcile(db, org_id: int) -> dict[str, Any]:
    result = reconcile_organization(db, org_id, persist=True)
    result["unreconciled_count"] = unreconciled_bank_count(db, org_id)
    return result


def _step_expense_queue(db, org_id: int, today: date) -> dict[str, Any]:
    from ..models import Expense

    open_drafts = (
        db.query(Expense)
        .filter(
            Expense.organization_id == org_id,
            Expense.status.in_(OPEN_EXPENSE_STATUSES),
        )
        .count()
    )
    cutoff = datetime.utcnow() - timedelta(hours=EXCEPTION_AGE_HOURS)
    exceptions_over_48h = (
        db.query(Expense)
        .filter(
            Expense.organization_id == org_id,
            Expense.status.in_(OPEN_EXPENSE_STATUSES),
            Expense.updated_at < cutoff,
        )
        .count()
    )
    return {"open_expense_drafts": open_drafts, "exceptions_over_48h": exceptions_over_48h}


def _step_credit_line(db, org_id: int) -> dict[str, Any]:
    return credit_line_service.check_and_alert(db, org_id)


def _step_revenue_watch(db, org_id: int, today: date) -> dict[str, Any]:
    from . import revenue_watch

    return revenue_watch.scan_and_alert(db, org_id, today=today)


def _step_action_reaper(db) -> dict[str, Any]:
    from . import action_reaper

    return action_reaper.sweep(db)


def _compute_open_items(db, org_id: int) -> dict[str, Any]:
    """Read-only JSON summary of everything still open for this org, for the
    (future) morning brief: active CfoInsight counts by type/severity, active
    Alert count, open Task count."""
    from sqlalchemy import func

    from ..models import Alert, AlertStatus, CfoInsight, Task, TaskStatus

    insight_rows = (
        db.query(CfoInsight.insight_type, CfoInsight.severity, func.count(CfoInsight.id))
        .filter(CfoInsight.organization_id == org_id, CfoInsight.status == "active")
        .group_by(CfoInsight.insight_type, CfoInsight.severity)
        .all()
    )
    insights_by_type: dict[str, dict[str, int]] = {}
    for insight_type, severity, count in insight_rows:
        insights_by_type.setdefault(insight_type, {})[severity] = count

    active_alerts = (
        db.query(Alert)
        .filter(Alert.organization_id == org_id, Alert.status == AlertStatus.ACTIVE)
        .count()
    )
    open_tasks = (
        db.query(Task)
        .filter(Task.organization_id == org_id, Task.status == TaskStatus.OPEN)
        .count()
    )
    return {
        "insights_by_type": insights_by_type,
        "active_alerts": active_alerts,
        "open_tasks": open_tasks,
    }


def run_daily_close_step(
    db,
    organization_id: int,
    today: date,
    *,
    parity_status: Optional[str] = None,
    unreconciled_count: Optional[int] = None,
    open_expense_drafts: Optional[int] = None,
    exceptions_over_48h: Optional[int] = None,
    credit_headroom: Optional[float] = None,
    credit_breach_date: Optional[date] = None,
    cycle_status: Optional[str] = None,
) -> dict[str, Any]:
    """The former body of `cron.run_daily_close`, now callable per-org for
    both the full morning cycle and the legacy `/cron/daily-close` route
    (which calls this with all the morning-cycle-only kwargs left at their
    None default — honest-null, since that route alone has no parity/credit/
    reconcile/expense-queue data to offer). Deliberately does NOT catch its
    own exceptions: the per-org isolation lives in the *callers* (both
    `run_daily_close` and `run_morning_cycle`/`run_all_organizations`), which
    need this to raise so their own try/except records the org in `errors`.

    `days_to_next_deadline` and `open_items` are self-contained (no other
    step's output needed) so they're always computed here, even when called
    from the legacy route.
    """
    from ..models import DailySnapshot
    from .dashboard_service import DashboardService
    from .data_quality import run_checks
    from .shaam_reminder import ensure_shaam_renewal_reminder

    overview = DashboardService(db, organization_id).get_overview(today=today)
    dq = run_checks(db, organization_id)

    existing = db.query(DailySnapshot).filter(
        DailySnapshot.organization_id == organization_id,
        DailySnapshot.snapshot_date == today,
    ).first()

    values = {
        "cash_balance": overview["cash_balance"],
        "ar_total": overview["ar_total"],
        "ap_total": overview["ap_total"],
        "month_net_profit": overview["month_net_profit"],
        "undocumented_total": overview["undocumented_expenses"]["total"],
        "data_quality_issues": dq["issues_count"],
        "unreconciled_count": unreconciled_count,
        "open_expense_drafts": open_expense_drafts,
        "exceptions_over_48h": exceptions_over_48h,
        "parity_status": parity_status,
        "credit_headroom": credit_headroom,
        "credit_breach_date": credit_breach_date,
        "cycle_status": cycle_status,
        "days_to_next_deadline": days_to_next_deadline(today),
        "open_items": _compute_open_items(db, organization_id),
    }
    if existing:
        for key, value in values.items():
            setattr(existing, key, value)
    else:
        db.add(DailySnapshot(organization_id=organization_id, snapshot_date=today, **values))
    db.commit()

    # Shaam (tax-authority connection) renewal reminder — isolated on
    # purpose: a failure here must never undo the snapshot commit above, and
    # must never block later morning-cycle steps. Preserves the exact
    # cron.run_daily_close behavior of firing regardless of anything except
    # the snapshot section itself raising (in which case this line is never
    # reached — same as before, since it used to run unconditionally after
    # the *snapshot's own* try/except, not after a raise).
    try:
        ensure_shaam_renewal_reminder(db, organization_id, today=today)
    except Exception as exc:
        logger.warning("Shaam reminder failed for org %s: %s", organization_id, exc)
        db.rollback()

    return {
        "organization_id": organization_id,
        "status": "ok",
        "data_quality": dq["status"],
        "issues_count": dq["issues_count"],
        "snapshot": values,
    }


def run_morning_cycle(
    db, organization_id: int, today: date, force: bool = False
) -> dict[str, Any]:
    """Run the full seven-step morning cycle for one organization.

    With `force=False` (default), if this org's morning cycle already fully
    completed today (DailySnapshot.cycle_status already set for org+today),
    this is a cheap no-op — it returns the existing snapshot's summary
    instead of re-running bank reconciliation/anomaly scans that already ran
    this morning. `force=True` always recomputes every step, landing on the
    same single (org, today) row, updated in place.
    """
    from ..models import DailySnapshot

    if not force:
        existing = db.query(DailySnapshot).filter(
            DailySnapshot.organization_id == organization_id,
            DailySnapshot.snapshot_date == today,
            DailySnapshot.cycle_status.isnot(None),
        ).first()
        if existing:
            return {
                "organization_id": organization_id,
                "date": today.isoformat(),
                "status": "skipped",
                "reason": "already_ran_today",
                "cycle_status": existing.cycle_status,
            }

    steps: dict[str, Any] = {}

    steps["parity"] = _run_step(db, lambda: _step_parity(db, organization_id, today))
    steps["bank_anomalies"] = _run_step(
        db, lambda: _step_bank_anomalies(db, organization_id, today)
    )
    steps["reconcile"] = _run_step(db, lambda: _step_reconcile(db, organization_id))
    steps["expense_queue"] = _run_step(
        db, lambda: _step_expense_queue(db, organization_id, today)
    )
    steps["credit_line"] = _run_step(db, lambda: _step_credit_line(db, organization_id))
    # W-proactive (20/08/2026, פער מס' 1): דממת הכנסות — "אין מסמכי הכנסה
    # מאז X" נכנסת ללולאת התובנות היומית במקום להיעלם בשקט.
    steps["revenue_watch"] = _run_step(
        db, lambda: _step_revenue_watch(db, organization_id, today)
    )
    # W6.2 (21/08/2026): פעולות כסף תקועות (executing>15ד'/unknown) עולות
    # לתור הפערים ול-CfoInsight — לא נעלמות יותר בשקט.
    steps["action_reaper"] = _run_step(db, lambda: _step_action_reaper(db))

    def _parity_status() -> Optional[str]:
        s = steps["parity"]
        return s["result"]["status"] if s["status"] == "ok" else None

    def _int_field(step_name: str, field: str) -> Optional[int]:
        s = steps[step_name]
        return s["result"].get(field) if s["status"] == "ok" else None

    def _credit_status() -> Optional[str]:
        s = steps["credit_line"]
        return s["result"].get("status") if s["status"] == "ok" else None

    def _bank_anomaly_today() -> bool:
        s = steps["bank_anomalies"]
        return bool(s["result"].get("anomaly_today")) if s["status"] == "ok" else False

    parity_status = _parity_status()
    unreconciled_count = _int_field("reconcile", "unreconciled_count")
    open_expense_drafts = _int_field("expense_queue", "open_expense_drafts")
    exceptions_over_48h = _int_field("expense_queue", "exceptions_over_48h")
    credit_status = _credit_status()
    credit_result = steps["credit_line"].get("result") or {}
    credit_headroom = credit_result.get("min_headroom")
    credit_breach_date_str = credit_result.get("breach_date")
    credit_breach_date = (
        date.fromisoformat(credit_breach_date_str) if credit_breach_date_str else None
    )
    bank_anomaly_today = _bank_anomaly_today()
    deadline_days = days_to_next_deadline(today)

    cycle_status = compute_cycle_status(
        parity_status=parity_status,
        open_expense_drafts=open_expense_drafts,
        exceptions_over_48h=exceptions_over_48h,
        credit_status=credit_status,
        days_to_next_deadline=deadline_days,
        bank_anomaly_today=bank_anomaly_today,
    )

    steps["daily_close"] = _run_step(
        db,
        lambda: run_daily_close_step(
            db,
            organization_id,
            today,
            parity_status=parity_status,
            unreconciled_count=unreconciled_count,
            open_expense_drafts=open_expense_drafts,
            exceptions_over_48h=exceptions_over_48h,
            credit_headroom=credit_headroom,
            credit_breach_date=credit_breach_date,
            cycle_status=cycle_status,
        ),
    )
    steps["debtors"] = _run_step(db, lambda: _step_debtors(db, organization_id, today))

    cycle_result = {
        "organization_id": organization_id,
        "date": today.isoformat(),
        "status": "ok",
        "cycle_status": cycle_status,
        "steps": steps,
    }
    steps["morning_brief"] = _run_step(
        db, lambda: _step_morning_brief(db, organization_id, today, cycle_result)
    )

    return cycle_result


def _step_morning_brief(db, org_id: int, today: date, cycle_result: dict[str, Any]) -> dict[str, Any]:
    """Step 8 (PR5): compose + persist + (best-effort) deliver the 08:00
    morning brief from this run's own in-flight results. Lazily imported so
    morning_brief_service (which itself does small pure-function work
    independent of this module) never needs to be imported at module load
    time here."""
    from . import morning_brief_service

    brief = morning_brief_service.compose_brief(db, org_id, today, cycle_result=cycle_result)
    delivery = morning_brief_service.persist_and_deliver(db, org_id, today, brief)
    return {"status": brief["status"], "delivery": delivery}


def _step_debtors(db, org_id: int, today: date) -> dict[str, Any]:
    """Read-only AR aging summary + top-5 overdue by amount, for the (future)
    morning brief. Never sends anything — collection reminders are their own
    cron (07:00)."""
    report = ARAPAgingService(db, org_id).ar_aging_report(as_of_date=today)
    overdue: list[dict[str, Any]] = []
    for bucket_name in ("31_60", "61_90", "90plus"):
        overdue.extend(report["aging"][bucket_name]["invoices"])
    top_overdue = sorted(overdue, key=lambda inv: inv["amount"], reverse=True)[:5]

    summary = {
        bucket: {"count": data["count"], "amount": data["amount"]}
        for bucket, data in report["aging"].items()
    }
    return {
        "total_receivable": report["total_receivable"],
        "aging_summary": summary,
        "top_overdue": top_overdue,
    }


def run_all_organizations(db, today: date, force: bool = False) -> dict[str, Any]:
    """Run `run_morning_cycle` for every active organization, isolating one
    org's failure from the rest (same try/except/rollback/continue pattern
    as every other cron loop in this codebase)."""
    from ..models import Organization

    orgs = db.query(Organization).filter(Organization.is_active.is_(True)).all()
    results = []
    errors = []
    for org in orgs:
        start = time.monotonic()
        try:
            result = run_morning_cycle(db, org.id, today, force=force)
            result["elapsed_ms"] = round((time.monotonic() - start) * 1000, 1)
            results.append(result)
        except Exception as exc:
            logger.error("Morning cycle failed for org %s: %s", org.id, exc)
            db.rollback()
            errors.append({
                "organization_id": org.id,
                "error": str(exc),
                "elapsed_ms": round((time.monotonic() - start) * 1000, 1),
            })

    return {"status": "ok", "orgs": len(orgs), "results": results, "errors": errors}
