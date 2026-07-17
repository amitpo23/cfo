"""תזכורת מחזורית לחידוש חיבור רשות המסים (שע"מ).

חוק מרכז-הידע (docs/SUMIT_KNOWLEDGE_BASE.md, סעיף 5+12): החיבור לרשות
המסים (שע"מ) פג כל 3 חודשים וצריך חידוש ידני. בלעדיו: אין מספרי הקצאה
לחשבוניות (חובה מעל ₪5,000) ואין אפשרות לשידור דיווח מקוון לרשות.

השירות יוצר CfoInsight אחד לכל רבעון קלנדרי, עם dedup לפי fingerprint
ייחודי פר-ארגון-רבעון — קריאה חוזרת באותו רבעון לא יוצרת שורה כפולה
(אותו דפוס בדיוק כמו bank_expense_gap.scan_and_alert).
"""
from __future__ import annotations

from datetime import date
from typing import Optional


def _quarter_tag(d: date) -> str:
    """תג רבעון קלנדרי בפורמט "YYYY-Qn" (Q1=ינואר-מרץ וכו')."""
    q = (d.month - 1) // 3 + 1
    return f"{d.year}-Q{q}"


def ensure_shaam_renewal_reminder(db, org_id: int, *, today: Optional[date] = None) -> dict:
    """יוצר (אם עוד לא נוצר ברבעון הנוכחי) תזכורת CfoInsight לחידוש חיבור שע"מ.

    dedup: fingerprint ייחודי פר-ארגון-רבעון (shaam_renewal:{org}:{YYYY-Qn}).
    קריאה חוזרת באותו רבעון לא יוצרת שורה נוספת; מעבר לרבעון חדש -> insight חדש.
    """
    from ..models import CfoInsight

    today = today or date.today()
    quarter = _quarter_tag(today)
    fingerprint = f"shaam_renewal:{org_id}:{quarter}"

    existing = db.query(CfoInsight).filter(
        CfoInsight.organization_id == org_id,
        CfoInsight.fingerprint == fingerprint,
    ).first()
    if existing:
        return {"created": False, "quarter": quarter, "insight_id": existing.id}

    insight = CfoInsight(
        organization_id=org_id,
        fingerprint=fingerprint,
        insight_type="shaam_renewal",
        severity="high",
        title="חידוש חיבור רשות המסים — החיבור פג כל 3 חודשים",
        message=(
            "החיבור לרשות המסים (שע\"מ) דרך רצף פג כל 3 חודשים. בלעדיו אין "
            "מספרי הקצאה לחשבוניות ואין אפשרות לדיווח מקוון לרשות. "
            f"רבעון נוכחי: {quarter}."
        ),
        evidence={"quarter": quarter},
        recommended_action="גש למסך /accounting/shaamstatus וחדש את החיבור לרשות המסים.",
        status="active",
    )
    db.add(insight)
    db.commit()
    return {"created": True, "quarter": quarter, "insight_id": insight.id}
