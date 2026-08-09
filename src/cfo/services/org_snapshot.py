"""תמונת ארגון — "מה מצב התיק הזה", בשאילתה אחת.

הנתונים כבר org-scoped, ולכן אפשר לתשאל תיק בודד כבר היום, בלי לחכות
לפיצול המסדים. הגישה נעשית דרך `tenant_routing.session_for`, ולכן
כשארגון יעבור למסד ייעודי הפונקציה תמשיך לעבוד בלי שינוי — והשדה
`database` יראה מאיפה המספרים הגיעו.

הדגש הוא על **התאמה מול הספקים**: חיבור בסטטוס `active` שלא סונכרן
שבועיים אינו תואם, ולכן זמן הסנכרון האחרון חשוב לא פחות מהסטטוס.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import func

from . import tenant_routing

# מעבר לזה התיק אינו משקף את הספק. 20 שעות הוא שער הסנכרון היומי
# הקשיח של המערכת, ולכן 48 שעות הן כבר שתי ריצות שהוחמצו.
_STALE_HOURS = 48

_PROVIDERS = ("sumit", "open_finance")


def _hours_since(value: Optional[datetime]) -> Optional[float]:
    if value is None:
        return None
    reference = datetime.now(timezone.utc)
    if value.tzinfo is None:
        reference = reference.replace(tzinfo=None)
    return round((reference - value).total_seconds() / 3600, 1)


def org_snapshot(organization_id: int) -> Optional[dict[str, Any]]:
    """תמונת מצב מלאה לארגון אחד, או None אם אינו קיים.

    honest-null לאורך כל הדרך: ספק שאינו מחובר מקבל `None` ולא `0`.
    `0` שעות היה נקרא כ"סונכרן ממש עכשיו" — היפוך מוחלט של המשמעות.
    """
    from ..models import (
        BankTransaction, Bill, Contact, Expense, IntegrationConnection,
        Invoice, Organization,
    )

    with tenant_routing.session_for(organization_id) as db:
        org = db.query(Organization).filter(Organization.id == organization_id).first()
        if org is None:
            return None

        def _count(model) -> int:
            return db.query(model).filter(model.organization_id == organization_id).count()

        # טיוטה בסכום 0 היא חוסר-התאמה מול SUMIT במובן המדויק: המסמך
        # קיים בספק ונמשך לרצף, אבל הסכום לא הגיע — הקבלה הקריאה חיה
        # מאחורי הסשן של הפורטל. כל דוח שנשען על expenses.total מדווח
        # חסר, ולכן זה מדד התאמה ולא רק "איכות נתונים".
        zero_sum = (
            db.query(Expense)
            .filter(
                Expense.organization_id == organization_id,
                func.coalesce(Expense.total, 0) == 0,
            )
            .count()
        )

        data = {
            "expenses": _count(Expense),
            "zero_sum_expenses": zero_sum,
            "invoices": _count(Invoice),
            "bills": _count(Bill),
            "bank_transactions": _count(BankTransaction),
            "contacts": _count(Contact),
        }

        connections = {
            row.source: row
            for row in db.query(IntegrationConnection).filter(
                IntegrationConnection.organization_id == organization_id
            ).all()
        }

        providers: dict[str, Any] = {}
        issues: list[str] = []
        for name in _PROVIDERS:
            row = connections.get(name)
            if row is None:
                providers[name] = {
                    "connected": False, "status": None, "hours_since_sync": None,
                }
                issues.append(f"{name}: אין חיבור")
                continue

            hours = _hours_since(row.last_synced_at)
            providers[name] = {
                "connected": True,
                "status": row.status,
                "hours_since_sync": hours,
                "has_credentials": bool(row.credentials_encrypted),
            }
            if row.status != "active":
                issues.append(f"{name}: חיבור {row.status} — הארגון מחוץ ללולאת הסנכרון")
            elif hours is None:
                issues.append(f"{name}: מעולם לא סונכרן")
            elif hours > _STALE_HOURS:
                issues.append(f"{name}: סונכרן לפני {hours:.0f} שעות")

        if data["zero_sum_expenses"]:
            issues.append(
                f"sumit: {data['zero_sum_expenses']} מסמכים בסכום 0 — "
                "נמשכו מהספק בלי הסכום"
            )

        return {
            "organization_id": organization_id,
            "name": org.name,
            "is_active": org.is_active,
            "database": (
                "dedicated"
                if organization_id in tenant_routing.split_organization_ids()
                else "shared"
            ),
            "data": data,
            "providers": providers,
            "issues": issues,
        }


def list_organizations() -> list[dict[str, Any]]:
    """כל הארגונים עם המספרים הראשיים והדגלים.

    רשימת הארגונים נקראת ממסד הבקרה — הוא היחיד שיודע מי קיים.
    """
    from ..models import Organization

    with tenant_routing.session_for(None) as db:
        ids = [row.id for row in db.query(Organization).order_by(Organization.id).all()]

    snapshots = []
    for organization_id in ids:
        snap = org_snapshot(organization_id)
        if snap is None:
            continue
        snapshots.append(
            {
                "organization_id": snap["organization_id"],
                "name": snap["name"],
                "database": snap["database"],
                "expenses": snap["data"]["expenses"],
                "zero_sum_expenses": snap["data"]["zero_sum_expenses"],
                "bills": snap["data"]["bills"],
                "bank_transactions": snap["data"]["bank_transactions"],
                "issues": snap["issues"],
            }
        )
    return snapshots
