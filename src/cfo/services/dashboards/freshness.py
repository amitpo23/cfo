"""Sources and freshness of one organization (the Eliav tool's "מקורות ורעננות").

One row per bank account and per books source (invoices, bills, expenses, journal
by source): the last transaction / document date, the last sync or import time,
the row count and a stale flag. Grouped queries, so the cost does not grow with
the number of rows. No provider calls. Reads only.

Age of a source:

* a live feed (``open_finance``, ``sumit``): days since the last successful sync;
  no sync time is ``stale``;
* an imported source (``reviewed_local_import``, ``hashavshevet_mdb``, manual,
  anything else): days since the last row date;
* no rows at all: ``unknown``, never "fresh".

One set of thresholds for every source, defined only in ``FRESHNESS_THRESHOLDS``:
up to ``FRESH_MAX_DAYS`` is fresh, up to ``AGING_MAX_DAYS`` is aging, older is
stale. A 10-12 day old import is therefore stale, not "עדכני".
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import func

from ...models import (
    Account, BankTransaction, Bill, Expense, IntegrationConnection, Invoice, JournalEntry, SyncRun, SyncStatus,
)

FRESH_MAX_DAYS = 3
AGING_MAX_DAYS = 7
# Ordered (status, max age in days). The single source of the labels' meaning.
FRESHNESS_THRESHOLDS = (("fresh", FRESH_MAX_DAYS), ("aging", AGING_MAX_DAYS))
LIVE_SOURCES = {"open_finance", "sumit"}
SOURCE_LABELS = {
    "open_finance": "Open Finance — חיבור בנק חי",
    "sumit": "SUMIT — סנכרון",
    "reviewed_local_import": "יבוא מקומי שנבדק",
    "hashavshevet_mdb": "יבוא חשבשבת",
    "sumit_portal_export": "ייצוא פורטל SUMIT",
    "manual": "הזנה ידנית",
}
KIND_LABELS = {
    "bank": "תנועות בנק",
    "invoices": "חשבוניות",
    "bills": "חשבוניות ספק",
    "expenses": "הוצאות",
    "journal": "יומן",
}
STATUS_LABELS = {"fresh": "עדכני", "aging": "מתיישן", "stale": "לא עדכני", "unknown": "לא ידוע"}


def age_status(age_days: int) -> str:
    """fresh / aging / stale for an age in days, from ``FRESHNESS_THRESHOLDS``."""
    for status, max_days in FRESHNESS_THRESHOLDS:
        if age_days <= max_days:
            return status
    return "stale"


def freshness_rule() -> str:
    return (
        f"עדכני: עד {FRESH_MAX_DAYS} ימים. מתיישן: עד {AGING_MAX_DAYS} ימים. "
        f"לא עדכני: מעל {AGING_MAX_DAYS} ימים. "
        "חיבור חי (Open Finance, SUMIT) נמדד מהסנכרון המוצלח האחרון; "
        "מקור מיובא נמדד מהתנועה האחרונה."
    )


def _day(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _iso(value):
    return value.isoformat() if value is not None else None


def _status(source: str | None, last_data: date | None, last_sync, today: date) -> tuple[str, int | None]:
    if last_data is None:
        return "unknown", None
    if (source or "") in LIVE_SOURCES:
        synced = _day(last_sync)
        if synced is None:
            return "stale", None
        age = (today - synced).days
        return age_status(age), age
    age = (today - last_data).days
    return age_status(age), age


def _last_syncs(db, organization_id: int) -> dict:
    """Last successful sync per source: the connection's time or a completed run."""
    out: dict[str, datetime] = {}
    for source, synced in db.query(IntegrationConnection.source, IntegrationConnection.last_synced_at).filter(
        IntegrationConnection.organization_id == organization_id,
    ):
        if synced is not None and (out.get(source) is None or synced > out[source]):
            out[source] = synced
    for source, finished in db.query(SyncRun.source, func.max(SyncRun.finished_at)).filter(
        SyncRun.organization_id == organization_id,
        SyncRun.status.in_([SyncStatus.COMPLETED, SyncStatus.PARTIAL]),
    ).group_by(SyncRun.source):
        if finished is not None and (out.get(source) is None or finished > out[source]):
            out[source] = finished
    return out


def build_freshness(db, organization_id: int, *, today: date | None = None) -> dict:
    today = today or date.today()
    syncs = _last_syncs(db, organization_id)
    accounts = {
        row.id: row for row in db.query(Account).filter(Account.organization_id == organization_id).all()
    }
    items = []
    bank = (
        db.query(
            BankTransaction.account_id, BankTransaction.source,
            func.max(BankTransaction.transaction_date), func.count(BankTransaction.id),
            func.max(BankTransaction.created_at),
        )
        .filter(BankTransaction.organization_id == organization_id)
        .group_by(BankTransaction.account_id, BankTransaction.source)
        .all()
    )
    for account_id, source, last, count, imported in bank:
        account = accounts.get(account_id)
        source = source or (account.source if account is not None else None) or "manual"
        last_sync = syncs.get(source) if source in LIVE_SOURCES else imported
        status, age = _status(source, _day(last), last_sync, today)
        items.append({
            "kind": "bank",
            "kind_label": KIND_LABELS["bank"],
            "account_id": account_id,
            "label": account.name if account is not None else "ללא חשבון",
            "source": source,
            "source_label": SOURCE_LABELS.get(source, source),
            "last_date": _iso(_day(last)),
            "last_sync": _iso(last_sync),
            "rows": int(count),
            "age_days": age,
            "status": status,
            "status_label": STATUS_LABELS[status],
        })
    documents = (
        ("invoices", Invoice, Invoice.issue_date),
        ("bills", Bill, Bill.issue_date),
        ("expenses", Expense, Expense.expense_date),
        ("journal", JournalEntry, JournalEntry.entry_date),
    )
    for kind, model, column in documents:
        rows = (
            db.query(model.source, func.max(column), func.count(model.id), func.max(model.created_at))
            .filter(model.organization_id == organization_id)
            .group_by(model.source)
            .all()
        )
        for source, last, count, imported in rows:
            source = source or "manual"
            last_sync = syncs.get(source) if source in LIVE_SOURCES else imported
            status, age = _status(source, _day(last), last_sync, today)
            items.append({
                "kind": kind,
                "kind_label": KIND_LABELS[kind],
                "account_id": None,
                "label": KIND_LABELS[kind],
                "source": source,
                "source_label": SOURCE_LABELS.get(source, source),
                "last_date": _iso(_day(last)),
                "last_sync": _iso(last_sync),
                "rows": int(count),
                "age_days": age,
                "status": status,
                "status_label": STATUS_LABELS[status],
            })
    items.sort(key=lambda item: (list(KIND_LABELS).index(item["kind"]), item["label"] or "", item["source"]))
    return {
        "status": "ready" if items else "unknown",
        "today": today.isoformat(),
        "items": items,
        "stale_count": sum(1 for item in items if item["status"] == "stale"),
        "aging_count": sum(1 for item in items if item["status"] == "aging"),
        "rule": freshness_rule(),
        "provider_calls": 0,
    }


def redact_public(section: dict | None) -> dict | None:
    if not isinstance(section, dict):
        return section
    copied = dict(section)
    copied["items"] = [
        {key: value for key, value in item.items() if key != "account_id"}
        for item in section.get("items") or [] if isinstance(item, dict)
    ]
    return copied
