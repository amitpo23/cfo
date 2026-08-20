"""גלאי דממת הכנסות — "למה אין הכנסות מחודש X?" (פער מס' 1, חקירת 20/08).

עד היום שום גלאי לא שאל את השאלה הזו: המערכת ידעה להתריע על שיק חוזר,
חריגת אשראי ואי-התאמות — אבל עסק שהפסיק להוציא חשבוניות פשוט נעלם בשקט.

ההיגיון:
- מסמך ההכנסה האחרון (Invoice שאינו DRAFT/VOID/CANCELLED) קובע את
  נקודת הייחוס. אין היסטוריה בכלל ⇒ honest-null ("no_history"), לא
  התרעת שווא על עסק חדש.
- דממה מעל SILENCE_DAYS ⇒ CfoInsight מסוג `revenue_silence` עם השאלה
  המפורשת שהבעלים ינסח למושקו. fingerprint פר-חודש-דממה כדי שהתובנה
  תתעדכן ולא תשוכפל.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import CfoInsight, Invoice, InvoiceStatus

# 45 יום — ארוך מגלגול חודשי רגיל (גם עסק שמחייב פעם בחודש לא ייחשב
# דומם), קצר מספיק כדי לתפוס רבעון אבוד לפני שהוא נגמר.
SILENCE_DAYS = 45
CRITICAL_SILENCE_DAYS = 90

_EXCLUDED = (InvoiceStatus.DRAFT, InvoiceStatus.CANCELLED)


def scan_and_alert(db: Session, org_id: int, *, today: date) -> dict[str, Any]:
    last_issue = (
        db.query(func.max(Invoice.issue_date))
        .filter(
            Invoice.organization_id == org_id,
            Invoice.status.notin_(_EXCLUDED),
            Invoice.issue_date.isnot(None),
        )
        .scalar()
    )
    if last_issue is None:
        return {"status": "no_history"}

    days_silent = (today - last_issue).days
    if days_silent < SILENCE_DAYS:
        return {"status": "ok", "last_revenue_date": last_issue.isoformat(),
                "days_silent": days_silent}

    severity = "critical" if days_silent >= CRITICAL_SILENCE_DAYS else "high"
    fingerprint = f"revenue_silence:{org_id}:{last_issue.isoformat()}"
    title = (
        f"אין מסמכי הכנסה מאז {last_issue.strftime('%d/%m/%Y')} "
        f"({days_silent} ימים)"
    )
    message = (
        f"מסמך ההכנסה האחרון הופק ב-{last_issue.strftime('%d/%m/%Y')}. "
        "האם העסק הפסיק לחייב, החיוב נעשה מחוץ למערכת, או שיש חשבוניות "
        "שטרם הופקו? דממת הכנסות מתמשכת פוגעת ישירות בתזרים."
    )
    existing = db.query(CfoInsight).filter(
        CfoInsight.organization_id == org_id,
        CfoInsight.fingerprint == fingerprint,
    ).first()
    if existing is not None:
        existing.severity = severity
        existing.title = title
        existing.message = message
        existing.status = "active"
    else:
        db.add(CfoInsight(
            organization_id=org_id,
            fingerprint=fingerprint,
            insight_type="revenue_silence",
            severity=severity,
            title=title,
            message=message,
            evidence={"last_revenue_date": last_issue.isoformat(),
                      "days_silent": days_silent},
            recommended_action=(
                "לבדוק מול הלקוחות הפעילים אילו חיובים לא הופקו; אם החיוב "
                "נעשה במערכת אחרת — לסנכרן; אם העסק האט — לעדכן תחזית תזרים."
            ),
        ))
    db.commit()
    return {
        "status": "silence",
        "last_revenue_date": last_issue.isoformat(),
        "days_silent": days_silent,
        "severity": severity,
    }
