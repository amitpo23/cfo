"""שירות בדיקות שפיות (invariants) פר-ארגון — "מספר על המסך = אמת מאומתת".

ראה docs/REZEF_DATA_INTEGRITY_PLAN.md סעיף ג. כל בדיקה עצמאית, מוגבלת
ל-organization_id, ומחזירה {name, passed, details}. run_checks מרכז את
כולן לתוצאה אחת שנחשפת ב-GET /api/data-quality וכ-badge ב-overview,
ונשמרת יומית ב-daily-close (cron).
"""
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func

_CURRENCY_WHITELIST = {"ILS", "USD", "EUR"}
_STALE_AFTER = timedelta(hours=48)


def _bills_nonnegative(db, org_id: int) -> dict[str, Any]:
    """עקביות סימנים ב-bills: total שלילי לגיטימי (זיכוי ספק, מ-13/07) —
    אות הזיהום הוא חוסר-עקביות בין סימן ה-total לסימן ה-tax."""
    from ..models import Bill

    count = 0
    for b in db.query(Bill).filter(Bill.organization_id == org_id).all():
        total = float(b.total or 0)
        tax = float(b.tax or 0)
        if total != 0 and tax != 0 and (total > 0) != (tax > 0):
            count += 1
    return {
        "name": "bills_nonnegative",
        "passed": count == 0,
        "details": ("סימני total/tax עקביים בכל ה-bills (שלילי = זיכוי ספק)" if count == 0
                    else f"{count} bills עם סימן total מנוגד לסימן tax"),
    }


def _no_paid_invoice_with_open_balance(db, org_id: int) -> dict[str, Any]:
    from ..models import Invoice, InvoiceStatus

    count = db.query(Invoice.id).filter(
        Invoice.organization_id == org_id,
        Invoice.status == InvoiceStatus.PAID,
        Invoice.balance > 0,
    ).count()
    return {
        "name": "no_paid_invoice_with_open_balance",
        "passed": count == 0,
        "details": "אין חשבוניות PAID עם יתרה פתוחה" if count == 0
        else f"{count} חשבוניות PAID עם balance>0",
    }


def _invoice_balance_consistency(db, org_id: int) -> dict[str, Any]:
    from ..models import Invoice

    rows = db.query(Invoice).filter(Invoice.organization_id == org_id).all()
    bad = [
        r for r in rows
        if abs(float(r.balance or 0) - (float(r.total or 0) - float(r.paid_amount or 0))) > 0.01
    ]
    count = len(bad)
    return {
        "name": "invoice_balance_consistency",
        "passed": count == 0,
        "details": "balance=total-paid בכל החשבוניות" if count == 0
        else f"{count} חשבוניות עם אי-התאמת balance/total/paid",
    }


def _currency_whitelist(db, org_id: int) -> dict[str, Any]:
    from ..models import Invoice, Bill, Account

    bad_currencies: set[str] = set()
    for model in (Invoice, Bill, Account):
        rows = (
            db.query(model.currency)
            .filter(model.organization_id == org_id, model.currency.isnot(None))
            .distinct()
            .all()
        )
        for (currency,) in rows:
            if currency and currency.upper() not in _CURRENCY_WHITELIST:
                bad_currencies.add(currency)
    return {
        "name": "currency_whitelist",
        "passed": len(bad_currencies) == 0,
        "details": "כל המטבעות ברשימה הלבנה (ILS/USD/EUR)" if not bad_currencies
        else f"מטבעות לא מוכרים: {sorted(bad_currencies)}",
    }


def _of_balance_freshness(db, org_id: int) -> dict[str, Any]:
    """טריות יתרות Open Finance — עד 48h. אם אין חשבונות OF כלל, הבדיקה לא
    רלוונטית (עדיין passed=True, לא "issue")."""
    from ..models import Account

    of_accounts = db.query(Account).filter(
        Account.organization_id == org_id, Account.source == "open_finance",
    ).all()
    if not of_accounts:
        return {"name": "of_balance_freshness", "passed": True, "details": "אין חשבונות Open Finance"}

    now = datetime.utcnow()
    # טריות = מתי *אנחנו* סנכרנו לאחרונה (updated_at), לא referenceDate של
    # הבנק: יתרת הלוואה מתעדכנת אצל הבנק אחת לתקופה, וזה תקין — הבעיה שהבדיקה
    # תופסת היא סנכרון שלנו שהפסיק לרוץ.
    stale = [
        a for a in of_accounts
        if not (a.updated_at or a.balance_as_of)
        or (now - (a.updated_at or a.balance_as_of)) > _STALE_AFTER
    ]
    return {
        "name": "of_balance_freshness",
        "passed": len(stale) == 0,
        "details": "כל היתרות טריות (<=48h)" if not stale
        else f"{len(stale)} חשבונות Open Finance עם יתרה לא טרייה (>48h)",
    }


def _duplicate_external_ids(db, org_id: int) -> dict[str, Any]:
    from ..models import Invoice, Bill, Expense, BankTransaction

    dup_summary: dict[str, int] = {}
    for label, model in (
        ("invoices", Invoice), ("bills", Bill),
        ("expenses", Expense), ("bank_transactions", BankTransaction),
    ):
        rows = (
            db.query(model.external_id, func.count(model.id))
            .filter(model.organization_id == org_id, model.external_id.isnot(None))
            .group_by(model.external_id)
            .having(func.count(model.id) > 1)
            .all()
        )
        if rows:
            dup_summary[label] = len(rows)
    return {
        "name": "duplicate_external_ids",
        "passed": len(dup_summary) == 0,
        "details": "אין external_id כפול" if not dup_summary else f"כפילויות: {dup_summary}",
    }


def _empty_draft_expenses_count(db, org_id: int) -> dict[str, Any]:
    """אינפורמטיבי בלבד — טיוטות-הוצאה ריקות (סרוקות אך לא מתויגות/מתויקות).
    לעולם passed=True — לא invariant, רק מספר לעקוב אחריו."""
    from ..models import Expense

    count = db.query(Expense.id).filter(
        Expense.organization_id == org_id,
        Expense.status == "pending",
        (Expense.total.is_(None)) | (Expense.total == 0),
    ).count()
    return {
        "name": "empty_draft_expenses_count",
        "passed": True,
        "details": f"{count} טיוטות הוצאה ריקות (אינפורמטיבי, לא נחסם תיוק)",
    }


_CHECKS = (
    _bills_nonnegative,
    _no_paid_invoice_with_open_balance,
    _invoice_balance_consistency,
    _currency_whitelist,
    _of_balance_freshness,
    _duplicate_external_ids,
    _empty_draft_expenses_count,
)


def run_checks(db, org_id: int) -> dict[str, Any]:
    """מריץ את כל בדיקות השפיות עבור org אחד ומחזיר תוצאה מרוכזת."""
    checks = [fn(db, org_id) for fn in _CHECKS]
    issues_count = sum(1 for c in checks if not c["passed"])
    return {
        "status": "ok" if issues_count == 0 else "issues",
        "checks": checks,
        "issues_count": issues_count,
        "checked_at": datetime.utcnow().isoformat(),
    }
