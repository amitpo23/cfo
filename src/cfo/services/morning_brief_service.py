"""Morning-brief composer/renderer/deliverer (PR5 of the bookkeeper daily-cycle
plan) — the 08:00 output of the morning cycle (PR4, morning_cycle_service.py).

Layout mandated by the accountant-brain advisor (docs/bookkeeper_kb; see the
PR5 task spec): FIRST SCREEN is only reds requiring action *today* — bounced
check / failed standing order, projected credit-line breach (+ date), parity
FAIL, a filing deadline <=3 days away with an open drafts queue, and (as a
static, non-computed reminder — no employee flag exists in the data model) a
payroll-window note on days 1-9 of the month, explicitly hedged "אם יש
עובדים". Everything after that is cash, queues, and the top-5 overdue
debtors; green statuses collapse into a single line instead of being
itemized. Every number carries a "נכון ל-" freshness stamp; a missing input
renders "—" with an honest reason — it is never silently treated as 0.

Three entry points:
  compose_brief(db, org_id, today, cycle_result=None) -> dict
      Builds the brief payload. When called as step 8 of
      `morning_cycle_service.run_morning_cycle`, `cycle_result` is the
      in-flight result dict built so far (so the brief reflects this run's
      own numbers even before their commit is queryable elsewhere). When
      called standalone (e.g. re-rendering an existing day, or a later GET),
      `cycle_result` is omitted and the brief is rebuilt from *persisted*
      state only: today's DailySnapshot row + active CfoInsight rows. Either
      way the reds section is always sourced from active CfoInsight rows
      (bank_anomaly / credit_line_breach / parity_mismatch) — those are the
      one source of truth the rest of the pipeline already upserts to,
      regardless of which of the two paths composed this particular brief.
  render_hebrew(brief) -> (subject, text, html)
      Pure formatting — no DB access.
  persist_and_deliver(db, org_id, today, brief, force=False) -> dict
      Upserts the MorningBrief row and delivers over whichever channels are
      configured + not already delivered today (or `force`). Never raises —
      every channel's outcome (sent/skipped/failed/error) is recorded
      per-channel instead.
"""
from __future__ import annotations

import asyncio
import logging
from calendar import monthrange
from datetime import date, datetime
from typing import Any, Optional

logger = logging.getLogger(__name__)

STATUS_EMOJI = {"green": "🟢", "yellow": "🟡", "red": "🔴"}
_UNKNOWN_EMOJI = "⚪"

_DEADLINE_DAYS = (15, 19, 23)
_PAYROLL_WINDOW_END_DAY = 9


def _next_deadline(today: date) -> tuple[date, int]:
    """Same 15th/19th/23rd rule as morning_cycle_service.days_to_next_deadline,
    but also returns the concrete date (that function only returns a day
    count). Deliberately duplicated (small, pure, ~10 lines) rather than
    imported: morning_cycle_service is the caller that wires this module in
    as step 8, so importing it back here would set up a needless coupling
    between the two directions."""
    last_day = monthrange(today.year, today.month)[1]
    for day in _DEADLINE_DAYS:
        target_day = min(day, last_day)
        if today.day <= target_day:
            d = date(today.year, today.month, target_day)
            return d, (d - today).days

    if today.month == 12:
        d = date(today.year + 1, 1, 15)
    else:
        d = date(today.year, today.month + 1, 15)
    return d, (d - today).days


def _debtors_from_scratch(db, organization_id: int, today: date) -> dict[str, Any]:
    """Same read-only AR aging computation as
    morning_cycle_service._step_debtors — recomputed here (cheap: a DB query
    over Invoice/Contact, no external API) when no live `cycle_result` was
    given, so a re-rendered brief still shows real top-overdue debtors."""
    from .ar_ap_aging import ARAPAgingService

    report = ARAPAgingService(db, organization_id).ar_aging_report(as_of_date=today)
    overdue_buckets = ("31_60", "61_90", "90plus")
    overdue: list[dict[str, Any]] = []
    for bucket_name in overdue_buckets:
        overdue.extend(report["aging"][bucket_name]["invoices"])
    top_overdue = sorted(overdue, key=lambda inv: inv["amount"], reverse=True)[:5]
    total_overdue = sum(report["aging"][b]["amount"] for b in overdue_buckets)
    return {"total_overdue": round(total_overdue, 2), "top": top_overdue}


def compose_brief(
    db, organization_id: int, today: date, cycle_result: Optional[dict] = None,
) -> dict[str, Any]:
    from ..models import CfoInsight, DailySnapshot, Organization

    org = db.get(Organization, organization_id)
    org_name = org.name if org else None

    snap = db.query(DailySnapshot).filter(
        DailySnapshot.organization_id == organization_id,
        DailySnapshot.snapshot_date == today,
    ).first()

    live_snapshot_values: Optional[dict] = None
    live_cycle_status: Optional[str] = None
    if cycle_result is not None:
        dc = (cycle_result.get("steps") or {}).get("daily_close") or {}
        if dc.get("status") == "ok":
            live_snapshot_values = dc.get("result", {}).get("snapshot")
        live_cycle_status = cycle_result.get("cycle_status")

    def _field(name: str):
        if live_snapshot_values is not None and name in live_snapshot_values:
            return live_snapshot_values[name]
        if snap is not None:
            return getattr(snap, name, None)
        return None

    def _f(name: str) -> Optional[float]:
        v = _field(name)
        return float(v) if v is not None else None

    def _i(name: str) -> Optional[int]:
        v = _field(name)
        return int(v) if v is not None else None

    cash_balance = _f("cash_balance")
    credit_headroom = _f("credit_headroom")

    credit_breach_date_raw = _field("credit_breach_date")
    if credit_breach_date_raw is None:
        breach_date_str = None
    elif isinstance(credit_breach_date_raw, str):
        breach_date_str = credit_breach_date_raw
    else:
        breach_date_str = credit_breach_date_raw.isoformat()

    unreconciled_count = _i("unreconciled_count")
    open_expense_drafts = _i("open_expense_drafts")
    exceptions_over_48h = _i("exceptions_over_48h")
    parity_status = _field("parity_status")
    cycle_status = live_cycle_status or _field("cycle_status")

    next_deadline_date, computed_days_left = _next_deadline(today)
    days_left = _i("days_to_next_deadline")
    if days_left is None:
        days_left = computed_days_left
    next_date_str = next_deadline_date.isoformat()

    as_of: Optional[str] = None
    missing_reason: Optional[str] = None
    if live_snapshot_values is not None:
        as_of = datetime.utcnow().isoformat() + "Z"
    elif snap is not None and snap.created_at is not None:
        as_of = snap.created_at.isoformat() + "Z"
    else:
        missing_reason = "לא נמצא מחזור-בוקר להיום (DailySnapshot חסר)"

    # ------------------------------------------------------------- #
    # reds — bank anomaly, credit-line breach, parity mismatch, deadline
    # risk, then the static payroll-window reminder. Always sourced from
    # active CfoInsight rows so the two compose paths (live vs. persisted)
    # agree on wording.
    # ------------------------------------------------------------- #
    reds: list[dict[str, Any]] = []
    today_str = today.isoformat()

    bank_insights = db.query(CfoInsight).filter(
        CfoInsight.organization_id == organization_id,
        CfoInsight.insight_type == "bank_anomaly",
        CfoInsight.status == "active",
    ).all()
    for ins in bank_insights:
        evidence = ins.evidence or {}
        if evidence.get("date") == today_str:
            reds.append({
                "type": "bank_anomaly", "severity": ins.severity,
                "title": ins.title, "message": ins.message,
            })

    if breach_date_str is not None:
        breach_insight = db.query(CfoInsight).filter(
            CfoInsight.organization_id == organization_id,
            CfoInsight.insight_type == "credit_line_breach",
            CfoInsight.status == "active",
        ).order_by(CfoInsight.updated_at.desc()).first()
        reds.append({
            "type": "credit_line_breach", "severity": "critical",
            "title": breach_insight.title if breach_insight
            else f"חריגה ממסגרת האשראי הבנקאית — {breach_date_str}",
            "message": breach_insight.message if breach_insight else None,
            "detail": breach_date_str,
        })

    if parity_status == "mismatch":
        parity_insights = db.query(CfoInsight).filter(
            CfoInsight.organization_id == organization_id,
            CfoInsight.insight_type == "parity_mismatch",
            CfoInsight.status == "active",
        ).all()
        if parity_insights:
            for ins in parity_insights:
                reds.append({
                    "type": "parity_mismatch", "severity": "high",
                    "title": ins.title, "message": ins.message,
                })
        else:
            reds.append({
                "type": "parity_mismatch", "severity": "high",
                "title": "אי-התאמת התאמה משולשת יומית", "message": None,
            })

    if days_left is not None and days_left <= 3 and (open_expense_drafts or 0) > 0:
        reds.append({
            "type": "deadline_risk", "severity": "high",
            "title": (
                f"מועד דיווח בעוד {days_left} ימים ({next_date_str}) "
                f"עם {open_expense_drafts} טיוטות פתוחות בתור"
            ),
            "message": None,
        })

    if 1 <= today.day <= _PAYROLL_WINDOW_END_DAY:
        reds.append({
            "type": "payroll_reminder", "severity": "info",
            "title": "חלון תשלום שכר (ימים 1–9 בחודש) — אם יש עובדים",
            "message": None,
        })

    # ------------------------------------------------------------- #
    # debtors — reuse the live step's result when available, else recompute.
    # ------------------------------------------------------------- #
    debtors: Optional[dict[str, Any]] = None
    if cycle_result is not None:
        debtors_step = (cycle_result.get("steps") or {}).get("debtors") or {}
        if debtors_step.get("status") == "ok":
            dres = debtors_step["result"]
            aging_summary = dres.get("aging_summary") or {}
            total_overdue = sum(
                (aging_summary.get(b, {}).get("amount", 0) for b in ("31_60", "61_90", "90plus")),
            )
            debtors = {
                "total_overdue": round(total_overdue, 2),
                "top": dres.get("top_overdue") or [],
            }
    if debtors is None:
        debtors = _debtors_from_scratch(db, organization_id, today)

    # ------------------------------------------------------------- #
    # collapsed greens — one-line summaries for whatever isn't already red.
    # ------------------------------------------------------------- #
    red_types = {r["type"] for r in reds}
    collapsed_greens: list[str] = []
    if parity_status == "ok" and "parity_mismatch" not in red_types:
        collapsed_greens.append("התאמה משולשת: תקינה")
    if "bank_anomaly" not in red_types:
        collapsed_greens.append("בנק: ללא חריגות היום")
    if credit_headroom is not None and "credit_line_breach" not in red_types:
        collapsed_greens.append("מסגרת אשראי: בתוך התחזית")
    if exceptions_over_48h == 0:
        collapsed_greens.append("חריגות מעל 48 שעות: אין")
    if open_expense_drafts is not None and open_expense_drafts <= 20:
        collapsed_greens.append("תור טיוטות: בטווח")

    return {
        "organization_id": organization_id,
        "organization_name": org_name,
        "date": today_str,
        "status": cycle_status or "unknown",
        "reds": reds,
        "cash": {
            "balance": cash_balance,
            "as_of": as_of,
            "credit_headroom": credit_headroom,
            "breach_date": breach_date_str,
            "reason": missing_reason if cash_balance is None else None,
        },
        "queues": {
            "drafts": open_expense_drafts,
            "exceptions_over_48h": exceptions_over_48h,
            "unreconciled": unreconciled_count,
        },
        "debtors": debtors,
        "parity": {"status": parity_status},
        "deadline": {"next_date": next_date_str, "days_left": days_left},
        "freshness": {"as_of": as_of, "reason": missing_reason},
        "collapsed_greens": collapsed_greens,
    }


# ------------------------------------------------------------------- #
# render_hebrew — pure formatting, no DB access.
# ------------------------------------------------------------------- #
def _money(v: Optional[float]) -> str:
    return f"₪{v:,.0f}" if isinstance(v, (int, float)) else "— (אין נתון)"


def _plain(v: Optional[Any]) -> str:
    return "—" if v is None else str(v)


def render_hebrew(brief: dict) -> tuple[str, str, str]:
    status = brief.get("status") or "unknown"
    emoji = STATUS_EMOJI.get(status, _UNKNOWN_EMOJI)
    org_name = brief.get("organization_name") or "—"
    date_str = brief.get("date")
    try:
        dd_mm = date.fromisoformat(date_str).strftime("%d/%m")
    except (TypeError, ValueError):
        dd_mm = date_str or "—"

    subject = f"בריף בוקר · {org_name} · {dd_mm} · {emoji}"

    reds = brief.get("reds") or []
    cash = brief.get("cash") or {}
    queues = brief.get("queues") or {}
    debtors = brief.get("debtors") or {}
    deadline = brief.get("deadline") or {}
    freshness = brief.get("freshness") or {}
    collapsed = brief.get("collapsed_greens") or []
    top = debtors.get("top") or []

    as_of = freshness.get("as_of")
    if as_of:
        as_of_line = f"נכון ל-{as_of}"
    else:
        reason = freshness.get("reason") or "אין נתונים"
        as_of_line = f"נכון ל-— ({reason})"

    headroom_line = (
        _money(cash.get("credit_headroom")) if cash.get("credit_headroom") is not None
        else "— (לא ידועה מסגרת אשראי)"
    )

    # ---- plain text ---- #
    lines = [subject, "", as_of_line, ""]
    if reds:
        lines.append("צריך טיפול היום:")
        for r in reds:
            extra = f" — {r['message']}" if r.get("message") else ""
            lines.append(f"- {r['title']}{extra}")
    else:
        lines.append("אין פריטים אדומים הדורשים טיפול היום.")
    lines.append("")
    lines.append(f"מזומן: {_money(cash.get('balance'))} | מרווח אשראי: {headroom_line}")
    lines.append(
        f"תור טיוטות: {_plain(queues.get('drafts'))} | "
        f"חריגות מעל 48 שעות: {_plain(queues.get('exceptions_over_48h'))} | "
        f"לא מותאם בבנק: {_plain(queues.get('unreconciled'))}"
    )
    lines.append(f"חובות בפיגור (סה\"כ): {_money(debtors.get('total_overdue'))}")
    if top:
        lines.append("5 החייבים הגדולים:")
        for t in top:
            lines.append(
                f"- {t.get('customer', '—')}: {_money(t.get('amount'))} "
                f"({t.get('days_overdue', '—')} ימי איחור)"
            )
    if deadline.get("days_left") is not None:
        lines.append(
            f"מועד דיווח הבא: {deadline.get('next_date')} (בעוד {deadline['days_left']} ימים)"
        )
    if collapsed:
        lines.append(" · ".join(collapsed))
    text = "\n".join(lines)

    # ---- html ---- #
    def _red_li(r: dict) -> str:
        extra = f" — {r['message']}" if r.get("message") else ""
        return f"<li><strong>{r['title']}</strong>{extra}</li>"

    if reds:
        reds_section = (
            '<div style="background:#fdecea;border:1px solid #f5c6cb;border-radius:6px;'
            'padding:12px;margin-bottom:16px;">'
            '<h2 style="color:#c0392b;margin:0 0 8px;">🔴 צריך טיפול היום</h2>'
            f'<ul style="margin:0;padding-inline-start:20px;">{"".join(_red_li(r) for r in reds)}</ul>'
            '</div>'
        )
    else:
        reds_section = (
            '<div style="color:#2e7d32;margin-bottom:16px;">'
            '✅ אין פריטים אדומים הדורשים טיפול היום.</div>'
        )

    greens_section = (
        f'<p style="color:#666;font-size:0.9em;">{" · ".join(collapsed)}</p>' if collapsed else ""
    )

    if top:
        top_rows = "".join(
            "<tr>"
            f"<td style=\"border:1px solid #ddd;padding:6px;\">{t.get('customer', '—')}</td>"
            f"<td style=\"border:1px solid #ddd;padding:6px;\">{_money(t.get('amount'))}</td>"
            f"<td style=\"border:1px solid #ddd;padding:6px;\">{t.get('days_overdue', '—')}</td>"
            "</tr>"
            for t in top
        )
    else:
        top_rows = '<tr><td colspan="3" style="border:1px solid #ddd;padding:6px;">אין חייבים בפיגור</td></tr>'

    html = (
        '<div dir="rtl" lang="he" style="font-family: Arial, sans-serif; direction: rtl; '
        'max-width:640px; margin:0 auto;">'
        f'<h1 style="color:#366092;margin-bottom:4px;">בריף בוקר · {org_name} · {dd_mm} {emoji}</h1>'
        f'<p style="color:#666;margin-top:0;">{as_of_line}</p>'
        f'{reds_section}'
        f'{greens_section}'
        '<h3>מזומן</h3>'
        f'<p>יתרה: {_money(cash.get("balance"))} | מרווח אשראי: {headroom_line}</p>'
        '<h3>תורים</h3>'
        f'<p>טיוטות פתוחות: {_plain(queues.get("drafts"))} | '
        f'חריגות מעל 48 שעות: {_plain(queues.get("exceptions_over_48h"))} | '
        f'לא מותאם בבנק: {_plain(queues.get("unreconciled"))}</p>'
        '<h3>חייבים — 5 הגדולים</h3>'
        '<table style="border-collapse:collapse;width:100%;">'
        '<thead><tr>'
        '<th style="text-align:right;border:1px solid #ddd;padding:6px;background:#366092;color:#fff;">לקוח</th>'
        '<th style="text-align:right;border:1px solid #ddd;padding:6px;background:#366092;color:#fff;">סכום</th>'
        '<th style="text-align:right;border:1px solid #ddd;padding:6px;background:#366092;color:#fff;">ימי איחור</th>'
        '</tr></thead>'
        f'<tbody>{top_rows}</tbody>'
        '</table>'
        '</div>'
    )

    return subject, text, html


# ------------------------------------------------------------------- #
# persist_and_deliver
# ------------------------------------------------------------------- #
def _utcnow_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"


def _deliver_email(db, org, subject: str, text: str, delivered: dict, force: bool) -> dict:
    from ..config import settings as _settings
    from .email_sender import send_email_smtp

    if not force and delivered.get("email"):
        return {"status": "skipped", "reason": "already_delivered_today"}
    if org is None:
        return {"status": "skipped", "reason": "organization_not_found"}
    # Column default is True; NULL (e.g. a row from before this migration
    # backfilled it, or a raw-SQL-inserted row) means "not explicitly
    # disabled" — only an explicit False is an opt-out.
    if org.morning_brief_email_enabled is False:
        return {"status": "skipped", "reason": "org_disabled"}
    if not (_settings.smtp_host and _settings.smtp_from):
        return {"status": "skipped", "reason": "smtp_not_configured"}

    recipients = [r.strip() for r in (org.morning_brief_recipients or "").split(",") if r.strip()]
    if not recipients and org.email:
        recipients = [org.email]
    if not recipients:
        return {"status": "skipped", "reason": "no_recipients"}

    try:
        results = [asyncio.run(send_email_smtp(to, subject, text, _settings)) for to in recipients]
    except Exception as exc:  # noqa: BLE001 — never raise, record instead
        logger.exception("Morning-brief email send failed for org %s", getattr(org, "id", None))
        return {"status": "error", "error": str(exc)}

    if all(results):
        delivered["email"] = _utcnow_iso()
        return {"status": "sent", "recipients": recipients}
    return {"status": "failed", "reason": "send_returned_false", "recipients": recipients}


def _deliver_sms(db, organization_id: int, org, status: str, reds: list, delivered: dict, force: bool) -> dict:
    if not force and delivered.get("sms"):
        return {"status": "skipped", "reason": "already_delivered_today"}
    if status != "red":
        return {"status": "skipped", "reason": "not_red"}
    if org is None or not org.morning_brief_sms_enabled:
        return {"status": "skipped", "reason": "org_disabled"}

    try:
        from ..api.dependencies import sumit_for_org
        from ..integrations.sumit_models import SMSRequest

        sumit = sumit_for_org(db, organization_id)
        phone = org.phone
        if sumit is None or not phone:
            return {"status": "skipped", "reason": "no_sumit_or_phone"}

        first_title = reds[0]["title"] if reds else "בעיה דחופה"
        message = f"בריף בוקר אדום: {len(reds)} פריטים דורשים טיפול. הראשון: {first_title}"
        resp = asyncio.run(sumit.send_sms(SMSRequest(phone_number=phone, message=message)))
    except Exception as exc:  # noqa: BLE001 — never raise, record instead
        logger.exception("Morning-brief SMS send failed for org %s", organization_id)
        return {"status": "error", "error": str(exc)}

    if bool(resp):
        delivered["sms"] = _utcnow_iso()
        return {"status": "sent"}
    return {"status": "failed", "reason": "send_returned_false"}


def persist_and_deliver(
    db, organization_id: int, today: date, brief: dict, *, force: bool = False,
) -> dict[str, Any]:
    """Upsert the MorningBrief row for (organization_id, today) and deliver
    over email/SMS per the org's opt-ins, guarded by per-channel idempotency
    (delivered_channels) unless `force`. Never raises."""
    from ..models import MorningBrief, Organization

    status = brief.get("status") or "unknown"

    row = db.query(MorningBrief).filter(
        MorningBrief.organization_id == organization_id,
        MorningBrief.brief_date == today,
    ).first()
    if row is None:
        row = MorningBrief(
            organization_id=organization_id, brief_date=today,
            payload=brief, status=status, delivered_channels={},
        )
        db.add(row)
    else:
        row.payload = brief
        row.status = status
        if row.delivered_channels is None:
            row.delivered_channels = {}
    db.commit()
    db.refresh(row)

    delivered = dict(row.delivered_channels or {})
    org = db.get(Organization, organization_id)
    subject, text, html = render_hebrew(brief)

    channel_results = {
        "email": _deliver_email(db, org, subject, text, delivered, force),
        "sms": _deliver_sms(db, organization_id, org, status, brief.get("reds") or [], delivered, force),
    }

    row.delivered_channels = delivered
    db.commit()
    db.refresh(row)

    return {
        "organization_id": organization_id,
        "brief_date": today.isoformat(),
        "status": status,
        "channels": channel_results,
        "delivered_channels": dict(row.delivered_channels or {}),
    }
