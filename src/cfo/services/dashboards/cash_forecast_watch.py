"""Daily watch over the 13-week cash forecast of every dashboard.

Owner request 26/10/2026: a cron that runs, checks and acts. For each entity of
each dashboard the watch reads ``cash_forecast`` from the view model (database
only, no provider calls) and keeps one ``CfoInsight`` per finding:

* ``cash_forecast_breach``: the first week the balance is projected below the
  facility floor. Critical within four weeks, high after that.
* ``cash_forecast_overdue``: a maturity or an uncovered check already past,
  with no bank row after it to show the payment.
* ``cash_forecast_facility_drop``: a facility that ends within 60 days.
* ``cash_forecast_missing``: no opening balance, so nothing can be projected.

Findings are gathered for every dashboard first and written once per
organization, so an organization in two dashboards is not flipped back and
forth. An active finding the run no longer produces is resolved.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from ...models import CfoInsight, ClientDashboard
from . import multi_entity, view_model

logger = logging.getLogger(__name__)

WATCH_TYPES = (
    "cash_forecast_breach", "cash_forecast_overdue", "cash_forecast_facility_drop", "cash_forecast_missing",
)
LOOKBACK_DAYS = 200
CRITICAL_WITHIN_DAYS = 28
FACILITY_WITHIN_DAYS = 60


def _day(iso: str) -> str:
    return f"{iso[8:10]}/{iso[5:7]}"


def _week(start: str, end: str) -> str:
    return f"{_day(start)}–{_day(end)}"


def findings(forecast: dict, today: date, label: str | None) -> list[dict]:
    """The insights one entity's forecast calls for. Pure."""
    who = f"{label}: " if label else ""
    out = []
    breach = forecast.get("first_breach")
    if breach:
        start = date.fromisoformat(breach["week_start"])
        out.append({
            "insight_type": "cash_forecast_breach",
            "fingerprint": f"cash_forecast_breach:{breach['week_start']}",
            "severity": "critical" if start <= today + timedelta(days=CRITICAL_WITHIN_DAYS) else "high",
            "title": f"{who}צפויה חריגה מהמסגרת בשבוע {_week(breach['week_start'], breach['week_end'])}",
            "message": f"מרווח צפוי {breach['headroom']:,.0f} ₪. " + "; ".join(breach.get("reasons") or []),
            "recommended_action": "לבדוק מקור מימון או לדחות תשלומים לפני השבוע הזה (לשונית תזרים חזוי).",
            "evidence": breach,
        })
    for item in forecast.get("overdue") or []:
        out.append({
            "insight_type": "cash_forecast_overdue",
            "fingerprint": f"cash_forecast_overdue:{item['date']}:{item.get('label')}",
            "severity": "high",
            "title": f"{who}מועד שעבר: {item.get('label')} ({_day(item['date'])}), {abs(item['amount']):,.0f} ₪",
            "message": item.get("note"),
            "recommended_action": "לברר אם שולם ולעדכן את ראיות הנזילות.",
            "evidence": item,
        })
    weeks = forecast.get("weeks") or []
    for previous, week in zip(weeks, weeks[1:]):
        before, after = previous.get("limit"), week.get("limit")
        if before is None or (after is not None and after >= before):
            continue
        if date.fromisoformat(week["start"]) > today + timedelta(days=FACILITY_WITHIN_DAYS):
            continue
        if after is None:
            title = f"{who}מסגרת של {before:,.0f} ₪ מסתיימת בשבוע {_week(week['start'], week['end'])} ואין מסגרת ידועה במקומה"
        else:
            title = f"{who}מסגרת יורדת מ-{before:,.0f} ל-{after:,.0f} ₪ בשבוע {_week(week['start'], week['end'])}"
        out.append({
            "insight_type": "cash_forecast_facility_drop",
            "fingerprint": f"cash_forecast_facility_drop:{week['start']}",
            "severity": "medium",
            "title": title,
            "message": "תוקף מסגרת מסתיים. בלי חידוש, המרווח יורד מאותו שבוע.",
            "recommended_action": "לתאם חידוש מסגרת עם הבנק.",
            "evidence": {"week_start": week["start"], "limit_before": before, "limit_after": after},
        })
    if "opening_balance" in (forecast.get("missing") or []):
        out.append({
            "insight_type": "cash_forecast_missing",
            "fingerprint": "cash_forecast_missing:opening_balance",
            "severity": "low",
            "title": f"{who}חסרה יתרת פתיחה, התזרים החזוי לא יודע את היתרה",
            "message": "מזינים \"יתרת פתיחה ידנית\" מדף בנק בלשונית נזילות והתחייבויות.",
            "recommended_action": "להזין יתרת פתיחה.",
            "evidence": {"missing": forecast.get("missing")},
        })
    return out


def _save(db, organization_id: int, produced: list[dict], now: datetime) -> dict:
    existing = {
        row.fingerprint: row for row in db.query(CfoInsight).filter(
            CfoInsight.organization_id == organization_id, CfoInsight.insight_type.in_(WATCH_TYPES),
        )
    }
    counts = {"created": 0, "updated": 0, "resolved": 0}
    seen = set()
    for finding in produced:
        seen.add(finding["fingerprint"])
        row = existing.get(finding["fingerprint"])
        if row is None:
            db.add(CfoInsight(organization_id=organization_id, status="active", **finding))
            counts["created"] += 1
            continue
        for key in ("severity", "title", "message", "recommended_action", "evidence"):
            setattr(row, key, finding[key])
        if row.status == "resolved":
            row.status, row.resolved_at = "active", None
        counts["updated"] += 1
    for fingerprint, row in existing.items():
        if fingerprint not in seen and row.status != "resolved":
            row.status, row.resolved_at = "resolved", now
            counts["resolved"] += 1
    return counts


def run_watch(db, today: date, dashboard_ids: list[int] | None = None) -> dict:
    query = db.query(ClientDashboard).filter(ClientDashboard.status != "archived")
    if dashboard_ids is not None:
        query = query.filter(ClientDashboard.id.in_(dashboard_ids))
    by_org: dict[int, dict[str, dict]] = {}
    errors = []
    dashboards = query.all()
    for dashboard in dashboards:
        try:
            plan = view_model.plan_payload(db, dashboard.id)
            view = multi_entity.build_dashboard_view(
                db, dashboard, today - timedelta(days=LOOKBACK_DAYS), today, plan=plan,
            )
            for section in view.get("entities") or []:
                forecast = (section.get("view") or {}).get("cash_forecast")
                if not forecast:
                    continue
                bucket = by_org.setdefault(section["organization_id"], {})
                for finding in findings(forecast, today, section.get("label")):
                    bucket[finding["fingerprint"]] = finding
        except Exception as exc:  # one dashboard must not stop the rest
            logger.error("Cash forecast watch failed for dashboard %s: %s", dashboard.id, exc)
            db.rollback()
            errors.append({"dashboard_id": dashboard.id, "error": str(exc)[:300]})
    now = datetime.utcnow()
    totals = {"created": 0, "updated": 0, "resolved": 0}
    for organization_id, produced in by_org.items():
        for key, value in _save(db, organization_id, list(produced.values()), now).items():
            totals[key] += value
    db.commit()
    return {"status": "ok", "dashboards": len(dashboards), "organizations": len(by_org),
            **totals, "errors": errors, "provider_calls": 0}
