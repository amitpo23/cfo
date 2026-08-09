"""מסד הבקרה — מי קיים, ואיפה יושבים הנתונים שלו.

שלב 1 של `docs/superpowers/plans/2026-08-08-db-per-tenant-plan.md`.

מסד הבקרה מחזיק `users`, `organizations` ומיפוי ארגון→DSN. הזהות אינה
נשמרת בשום מסד של עוסק: משתמש אינו "שייך" למסד — הוא **מורשה** אליו,
וההרשאה נבדקת פעם אחת כאן (הבהרת בעלים 09/08/2026).

ה-DSN מוצפן באותו מנגנון שמצפין כבר קרדנשלים של SUMIT ו-Open Finance,
כי הוא סוד באותה רמה — הוא נושא שם משתמש וסיסמה למסד של לקוח.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy.orm import Session

from ..models import TenantDatabase
from . import tenant_routing
from .credentials_vault import decrypt_credentials, encrypt_credentials

_DSN_KEY = "dsn"


class RoutingLoadError(RuntimeError):
    """טעינת הניתוב נכשלה — ולכן לא הופעלה כלל.

    fail-closed במכוון: אילו הטעינה הייתה מדלגת על שורה פגומה, הארגון
    היה נופל **בשקט** למסד המשותף. אחרי סיבוב מפתח הצפנה זה מחזיר את כל
    העוסקים למסד אחד בלי שאיש יידע — דליפת נתונים בין תיקי לקוחות בלי
    אף סימן. (Codex QA 09/08)
    """


def register_tenant_database(
    db: Session,
    organization_id: int,
    dsn: str,
    *,
    provider: str = "neon",
    notes: str | None = None,
) -> TenantDatabase:
    """רושם (או מחליף) את המסד הייעודי של ארגון.

    רישום חוזר מעדכן את השורה הקיימת ואינו מייצר כפילות — לארגון יש
    מסד אחד לכל היותר (unique על `organization_id`).
    """
    row = (
        db.query(TenantDatabase)
        .filter(TenantDatabase.organization_id == organization_id)
        .first()
    )
    blob = encrypt_credentials({_DSN_KEY: dsn})

    if row is None:
        row = TenantDatabase(
            organization_id=organization_id,
            dsn_encrypted=blob,
            provider=provider,
            status="active",
            notes=notes,
        )
        db.add(row)
    else:
        row.dsn_encrypted = blob
        row.provider = provider
        row.status = "active"
        if notes is not None:
            row.notes = notes
        row.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(row)
    return row


def dsn_for_organization(db: Session, organization_id: int) -> Optional[str]:
    """ה-DSN המפוענח, או None כשהארגון טרם פוצל.

    honest-null: אין שורה = None. לא מוחזר DSN של המסד המשותף כברירת
    מחדל, כדי שקורא לא יטעה לחשוב שהארגון מפוצל.
    """
    row = (
        db.query(TenantDatabase)
        .filter(TenantDatabase.organization_id == organization_id)
        .first()
    )
    if row is None:
        return None
    return decrypt_credentials(row.dsn_encrypted).get(_DSN_KEY) or None


def load_routing_from_control_plane(db: Session) -> list[int]:
    """טוען את הניתוב ממסד הבקרה אל `tenant_routing`, ומחזיר את
    הארגונים שהופעלו.

    רק שורות `active` מנותבות. שורה שסומנה `inactive` — למשל אחרי
    rollback של פיצול — מחזירה את התנועה למסד המשותף בלי שהרשומה
    תימחק, כך שהמידע ההיסטורי נשמר.
    """
    rows = db.query(TenantDatabase).filter(TenantDatabase.status == "active").all()

    # מפענחים הכול **לפני** שנוגעים בניתוב הקיים. שורה פגומה עוצרת את
    # הטעינה כשהמצב הישן עדיין בתוקף, במקום להשאיר מפה חלקית.
    resolved: list[tuple[int, str]] = []
    broken: list[int] = []
    for row in rows:
        dsn = decrypt_credentials(row.dsn_encrypted).get(_DSN_KEY)
        if not dsn:
            broken.append(row.organization_id)
        else:
            resolved.append((row.organization_id, dsn))

    if broken:
        raise RoutingLoadError(
            "לא ניתן לפענוח DSN עבור הארגונים: "
            f"{', '.join(str(org_id) for org_id in broken)}. "
            "הניתוב לא הופעל — בדוק את מפתח ההצפנה. "
            "המשך בלי הארגונים האלה היה מפיל אותם בשקט למסד המשותף."
        )

    tenant_routing.reset_routing()
    for organization_id, dsn in resolved:
        tenant_routing.register_tenant_dsn(organization_id, dsn)

    return sorted(organization_id for organization_id, _ in resolved)


def tenant_database_rows(db: Session) -> list[dict[str, Any]]:
    """רשימה לתצוגה ולאכיפת "הכול או כלום".

    **ה-DSN לעולם אינו מוחזר כאן** — הרשימה מגיעה למסכי אדמין וללוגים,
    ושם סוד לא אמור להופיע.
    """
    return [
        {
            "organization_id": row.organization_id,
            "provider": row.provider,
            "status": row.status,
            "schema_revision": row.schema_revision,
            "last_verified_at": row.last_verified_at,
            "notes": row.notes,
        }
        for row in db.query(TenantDatabase).order_by(TenantDatabase.organization_id).all()
    ]
