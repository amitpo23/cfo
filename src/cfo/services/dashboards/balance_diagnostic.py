"""What Rezef has stored for each organization's checking balance.

Read-only. No SUMIT call and no Open Finance call. The numbers are the rows
already in the database. A balance Open Finance refreshed but this process
never imported is not here — the notes say which gates would have skipped it.
"""
from __future__ import annotations

from datetime import date

from ...config import settings
from ...models import Account, AccountType, Organization
from .liquidity import checking_snapshot


def _account_row(account: Account) -> dict:
    as_of = account.balance_as_of.date().isoformat() if account.balance_as_of else None
    return {
        "name": account.name,
        "source": account.source,
        "raw_account_type": account.raw_account_type,
        "balance": None if account.balance is None else round(float(account.balance), 2),
        "as_of": as_of,
        "credit_limit": None if account.credit_limit is None else round(float(account.credit_limit), 2),
        "available_limit": None if account.available_limit is None else round(float(account.available_limit), 2),
    }


def diagnose_org(db, organization_id: int, *, today: date | None = None) -> dict:
    today = today or date.today()
    org = db.get(Organization, organization_id)
    snap = checking_snapshot(db, organization_id, today=today)
    accounts = (
        db.query(Account)
        .filter(Account.organization_id == organization_id, Account.account_type == AccountType.BANK)
        .order_by(Account.id)
        .all()
    )
    allowlist = settings.open_finance_scheduled_sync_org_id_set
    return {
        "organization_id": organization_id,
        "name": org.name if org is not None else None,
        "as_of_today": today.isoformat(),
        "snapshot_balance": snap["balance"],
        "snapshot_as_of": snap["as_of"],
        "snapshot_source": "checking_snapshot",
        "transactions_through": snap["transactions_through"],
        "transactions_missing_after": snap["transactions_missing_after"],
        "stale_balances": snap["stale_balances"],
        "status": snap["status"],
        "accounts": [_account_row(account) for account in accounts],
        "scheduled_open_finance_enabled": bool(settings.open_finance_scheduled_sync_enabled),
        "scheduled_open_finance_includes_org": organization_id in allowlist if allowlist else False,
        "import_notes_he": [
            "המספר הוא מה ששמור בטבלת החשבונות. אין כאן קריאה ל-Open Finance או ל-SUMIT.",
            "רענון הלילה של Open Finance רץ רק כשהדגל דולק, או כשהארגון ברשימת הארגונים המתוזמנת. בלי אחד מהם הרענון מדולג.",
            "גם ארגון שברשימה מדלג אם הסנכרון האחרון צעיר מ-20 שעות.",
            "היתרה השמורה היא closingBooked. יתרה זמינה (interimAvailable) נשמרת בנפרד כמסגרת פנויה ולא מחליפה את יתרת העו״ש.",
            "אם תאריך התנועה האחרון מוקדם מתאריך היתרה, התנועות לא עודכנו עד אותו יום. היתרה לא מחושבת מחדש מהתנועות.",
        ],
        "provider_calls": 0,
    }


def diagnose_all(db, *, today: date | None = None) -> dict:
    org_ids = [row[0] for row in db.query(Account.organization_id).distinct().all()]
    return {
        "organizations": [diagnose_org(db, org_id, today=today) for org_id in org_ids],
        "provider_calls": 0,
    }
