"""בקרת כיסוי: מוודאת שכל תיק בפנקס המשרד באמת משתתף בלולאת הסנכרון.

**למה זה קיים.** `scheduled_sync_sumit` בונה את רשימת היעדים מ-
``IntegrationConnection.status == "active"``, ו-``roster_sync_targets``
נשען על ``active_sources()`` שדורש בדיוק אותו תנאי. המשמעות: ברגע שחיבור
עובר ל-``paused`` או ``inactive``, הארגון נושר מה-cron **בשקט** — אין
שגיאה, אין ריצה כושלת, פשוט אין ריצה. אודיט הפרוד של 05/08/2026 מצא שכך
נשרו שני תיקים: org 2 (`paused` מ-17/07) ו-org 3 (`inactive` מ-06/07),
שבועות בלי שאיש ידע.

הדוח הזה הופך שתיקה לאות. הוא **קורא בלבד** ואינו משנה סטטוסים —
החייאת חיבור היא החלטת בעלים, לא פעולה אוטומטית.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..models import (
    Expense,
    IntegrationConnection,
    Invoice,
    Organization,
    SumitCompany,
    SyncRun,
    SyncStatus,
)

# סנכרון SUMIT מתוזמן יומית (01:30). אחרי 48 שעות בלי ריצה מוצלחת משהו
# שבור — זה כבר לא איחור אלא נשירה.
STALE_AFTER_HOURS = 48

# ריצה שנפתחה ולא נסגרה. בפרוד נמצאו ריצות תקועות 26 ו-51 יום.
# אומת (05/08/2026): הן **אינן** חוסמות סנכרון חדש — השער בפועל הוא
# `SyncCheckpoint.last_success_at` ב-`_daily_budget_gate`, ואף קוד אינו
# קורא `SyncStatus.RUNNING`. לכן זו תקלת נראוּת: ריצה כזאת מסתירה את
# הכשל שהפיל אותה ומעוותת כל ספירה לפי סטטוס.
ZOMBIE_AFTER_HOURS = 6


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _hours_since(value: Optional[datetime]) -> Optional[float]:
    if value is None:
        return None
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return round((_now() - value).total_seconds() / 3600.0, 2)


def _data_integrity(db: Session, org_id: int) -> dict[str, int]:
    """ספירות איכות-נתונים שאינן עוצרות cron אבל הורסות כל דוח.

    בפרוד 05/08/2026: 415 טיוטות בסכום 0 (org1 243, org2 16, org5 156),
    1,200 הוצאות בלי ח.פ ספק מתוך 1,491, ו-8 חשבוניות של org 5 בלי איש קשר.
    בלי ח.פ אין אימות מול רשם החברות ואין בסיס תקין ל-PCN874.
    """
    expenses = db.query(Expense).filter(Expense.organization_id == org_id)
    invoices = db.query(Invoice).filter(Invoice.organization_id == org_id)
    return {
        "expenses_total": expenses.count(),
        "expenses_blank_total": expenses.filter(
            or_(Expense.total.is_(None), Expense.total == 0)
        ).count(),
        "expenses_missing_supplier_tax_id": expenses.filter(
            or_(Expense.supplier_tax_id.is_(None), Expense.supplier_tax_id == "")
        ).count(),
        "invoices_total": invoices.count(),
        "invoices_without_contact": invoices.filter(
            Invoice.contact_id.is_(None)
        ).count(),
    }


def roster_coverage_report(
    db: Session,
    *,
    office_organization_id: int = 1,
) -> dict[str, Any]:
    """מחזיר תמונת כיסוי מלאה של פנקס המשרד.

    לכל תיק פעיל: מצב החיבורים, גיל הסנכרון המוצלח האחרון, ו-verdict אחד מ-
    ``ok`` / ``disconnected`` / ``stale`` / ``never_synced``.
    בנוסף: ריצות זומבי, וארגונים שיש להם יותר מרשומת פנקס פעילה אחת —
    כפילות כזאת גורמת ל-``office_rollup`` לספור את הארגון פעמיים.
    """
    roster = (
        db.query(SumitCompany)
        .filter(
            SumitCompany.office_organization_id == office_organization_id,
            SumitCompany.status == "active",
            SumitCompany.target_organization_id.isnot(None),
        )
        .order_by(SumitCompany.id)
        .all()
    )

    seen_targets: dict[int, int] = {}
    for row in roster:
        seen_targets[row.target_organization_id] = (
            seen_targets.get(row.target_organization_id, 0) + 1
        )
    duplicate_target_orgs = sorted(
        org_id for org_id, n in seen_targets.items() if n > 1
    )

    clients: list[dict[str, Any]] = []
    summary = {"total": 0, "ok": 0, "stale": 0, "disconnected": 0, "never_synced": 0}

    for org_id in sorted(seen_targets):
        org = db.query(Organization).filter(Organization.id == org_id).first()
        conns = (
            db.query(IntegrationConnection)
            .filter(IntegrationConnection.organization_id == org_id)
            .order_by(IntegrationConnection.source)
            .all()
        )
        connection_statuses = [f"{c.source}:{c.status}" for c in conns]
        active_sources = [c.source for c in conns if c.status == "active"]

        # הכיסוי נשפט **פר-מקור**. שקלול ברמת הארגון מסתיר את הכשל האמיתי:
        # ל-org 2 בפרוד היה open_finance תקין ו-sumit מושהה, וסנכרון מוצלח
        # *כלשהו* היום הספיק כדי להחזיר "ok" — בדיוק התיק שנשר לא דווח.
        issues: list[str] = []
        sources: list[dict[str, Any]] = []
        verdicts: set[str] = set()

        if not conns:
            issues.append("אין אף חיבור אינטגרציה")
            verdicts.add("disconnected")

        for c in conns:
            src_last_ok = (
                db.query(SyncRun)
                .filter(
                    SyncRun.organization_id == org_id,
                    SyncRun.source == c.source,
                    SyncRun.status == SyncStatus.COMPLETED,
                )
                .order_by(SyncRun.finished_at.desc().nullslast())
                .first()
            )
            src_hours = _hours_since(
                src_last_ok.finished_at if src_last_ok else None
            )

            if c.status != "active":
                src_verdict = "disconnected"
                issues.append(
                    f"חיבור {c.source} במצב {c.status} — הארגון נשמט מה-cron"
                )
            elif src_hours is None:
                src_verdict = "never_synced"
                issues.append(f"{c.source}: אין אף סנכרון מוצלח בהיסטוריה")
            elif src_hours > STALE_AFTER_HOURS:
                src_verdict = "stale"
                issues.append(
                    f"{c.source}: הסנכרון המוצלח האחרון לפני "
                    f"{src_hours:.0f} שעות"
                )
            else:
                src_verdict = "ok"

            verdicts.add(src_verdict)
            sources.append({
                "source": c.source,
                "status": c.status,
                "last_successful_sync": (
                    src_last_ok.finished_at.isoformat()
                    if src_last_ok and src_last_ok.finished_at else None
                ),
                "hours_since_last_ok": src_hours,
                "verdict": src_verdict,
            })

        # החמור מנצח — מקור מת גובר על מקור בריא באותו ארגון.
        for candidate in ("disconnected", "never_synced", "stale", "ok"):
            if candidate in verdicts:
                verdict = candidate
                break
        else:
            verdict = "disconnected"

        # ברמת הארגון מדווחים את המקור הכי מיושן מבין הפעילים, כדי שהמספר
        # יתאר את הכשל ולא את המקור הטרי שמסווה אותו.
        active_hours = [
            s["hours_since_last_ok"] for s in sources
            if s["status"] == "active" and s["hours_since_last_ok"] is not None
        ]
        hours_since_last_ok = max(active_hours) if active_hours else None

        if org_id in duplicate_target_orgs:
            issues.append(
                "יותר מרשומת פנקס פעילה אחת מצביעה לארגון הזה — "
                "office_rollup סופר אותו פעמיים"
            )

        summary["total"] += 1
        summary[verdict] += 1
        clients.append({
            "organization_id": org_id,
            "name": org.name if org else None,
            "connection_statuses": connection_statuses,
            "active_sources": active_sources,
            "sources": sources,
            "data_integrity": _data_integrity(db, org_id),
            "hours_since_last_ok": hours_since_last_ok,
            "verdict": verdict,
            "issues": issues,
        })

    zombie_runs = []
    for run in (
        db.query(SyncRun)
        .filter(SyncRun.status == SyncStatus.RUNNING)
        .order_by(SyncRun.started_at)
        .all()
    ):
        stuck = _hours_since(run.started_at)
        if stuck is not None and stuck > ZOMBIE_AFTER_HOURS:
            zombie_runs.append({
                "sync_run_id": run.id,
                "organization_id": run.organization_id,
                "source": run.source,
                "started_at": run.started_at.isoformat() if run.started_at else None,
                "hours_stuck": stuck,
            })

    healthy = (
        summary["ok"] == summary["total"]
        and not zombie_runs
        and not duplicate_target_orgs
    )

    return {
        "healthy": healthy,
        "summary": summary,
        "clients": clients,
        "zombie_runs": zombie_runs,
        "duplicate_target_orgs": duplicate_target_orgs,
        "thresholds": {
            "stale_after_hours": STALE_AFTER_HOURS,
            "zombie_after_hours": ZOMBIE_AFTER_HOURS,
        },
    }


def coverage_alert_lines(report: dict[str, Any]) -> list[str]:
    """שורות התרעה קריאות לערוצי השיחה. רשימה ריקה = אין מה לדווח."""
    if report.get("healthy"):
        return []

    lines: list[str] = ["⚠️ בקרת כיסוי — תיקים שנשרו מלולאת הסנכרון:"]
    for c in report["clients"]:
        if c["verdict"] == "ok":
            continue
        name = c["name"] or f"org {c['organization_id']}"
        lines.append(f"• {name} ({c['verdict']}): " + "; ".join(c["issues"]))
    for z in report["zombie_runs"]:
        lines.append(
            f"• ריצת סנכרון #{z['sync_run_id']} (org {z['organization_id']}, "
            f"{z['source']}) תקועה {z['hours_stuck']:.0f} שעות"
        )
    for org_id in report["duplicate_target_orgs"]:
        lines.append(
            f"• org {org_id}: יותר מרשומת פנקס פעילה אחת — מע\"מ נספר כפול"
        )
    return lines


# --------------------------------------------------------------------------
# שער לפני קליטה
# --------------------------------------------------------------------------

class IntakeConflict(ValueError):
    """קליטה שהייתה קושרת תיק לארגון של תיק אחר."""


def intake_conflict(
    db: Session,
    *,
    office_organization_id: int,
    company_id: str,
    target_organization_id: Optional[int],
) -> Optional[str]:
    """מחזיר תיאור ההתנגשות, או None כשהקליטה מותרת.

    האינווריאנט: ארגון-דייר שייך לתיק SUMIT **אחד**. הפרתו היא בדיוק מה
    שקרה ל-`may way` — חברה 895072659 נקשרה ל-org 5 שכבר היה שייך ל-
    1999386278, ומאז `office_rollup` סינתז את org 5 פעמיים וספר את המע"מ
    שלו כפול.

    רשומה מושבתת אינה תופסת ארגון: אחרת השבתה הייתה נועלת אותו לנצח.
    """
    if target_organization_id is None:
        return None

    owner = (
        db.query(SumitCompany)
        .filter(
            SumitCompany.office_organization_id == office_organization_id,
            SumitCompany.target_organization_id == target_organization_id,
            SumitCompany.status == "active",
            SumitCompany.company_id != str(company_id),
        )
        .order_by(SumitCompany.id)
        .first()
    )
    if owner is None:
        return None
    return (
        f"ארגון {target_organization_id} כבר שייך לתיק "
        f"{owner.company_id} ({owner.name or 'ללא שם'}); "
        f"קליטת {company_id} לאותו ארגון תגרום לספירה כפולה ב-office_rollup"
    )


def assert_intake_allowed(
    db: Session,
    *,
    office_organization_id: int,
    company_id: str,
    target_organization_id: Optional[int],
) -> None:
    """זורק `IntakeConflict` כשהקליטה הייתה גונבת ארגון של תיק אחר."""
    conflict = intake_conflict(
        db,
        office_organization_id=office_organization_id,
        company_id=company_id,
        target_organization_id=target_organization_id,
    )
    if conflict:
        raise IntakeConflict(f"קליטת {company_id} נחסמה: {conflict}")
