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


def _trial_balance_balanced(db, org_id: int) -> dict[str, Any]:
    """W6.5: איזון חובה=זכות נבדק שוטף — לא רק כשמדפיסים מאזן.

    מאזן לא-מאוזן שמתגלה בהדפסת דוח הוא מאזן שהיה שבור שבועות.
    """
    from .ledger_service import trial_balance

    try:
        tb = trial_balance(db, org_id)
    except Exception as exc:  # noqa: BLE001 — כשל חישוב הוא כשל בדיקה
        return {"name": "trial_balance_balanced", "passed": False,
                "details": f"חישוב מאזן הבוחן נכשל: {exc}"}
    balanced = bool(tb.get("balanced", False))
    entry_count = tb.get("entry_count", 0)
    if entry_count == 0:
        return {"name": "trial_balance_balanced", "passed": True,
                "details": "אין פקודות יומן — אין מה לאזן"}
    diff = abs(float(tb.get("total_debit", 0)) - float(tb.get("total_credit", 0)))
    return {
        "name": "trial_balance_balanced",
        "passed": balanced,
        "details": (
            f"חובה {tb.get('total_debit')} מול זכות {tb.get('total_credit')}"
            + ("" if balanced else f" — פער {diff:,.2f}")
        ),
    }


def _document_number_continuity(db, org_id: int) -> dict[str, Any]:
    """W6.5: רצף מספור חשבוניות (הוראות ניהול פנקסים) — פער במספור הוא
    חשיפה ישירה מול רשות המסים. נבדקים רק מספרים ספרתיים טהורים."""
    from ..models import Invoice, InvoiceStatus

    rows = (
        db.query(Invoice.invoice_number)
        .filter(
            Invoice.organization_id == org_id,
            Invoice.status.notin_((InvoiceStatus.DRAFT, InvoiceStatus.CANCELLED)),
            Invoice.invoice_number.isnot(None),
        )
        .all()
    )
    numbers = sorted({int(r[0]) for r in rows if str(r[0]).isdigit()})
    if len(numbers) < 2:
        return {"name": "document_number_continuity", "passed": True,
                "details": "אין מספיק מסמכים ממוספרים לבדיקת רצף"}
    gaps: list[str] = []
    for prev, curr in zip(numbers, numbers[1:]):
        if curr - prev > 1:
            missing = list(range(prev + 1, min(curr, prev + 4)))
            gaps.append(",".join(map(str, missing)) + ("..." if curr - prev > 4 else ""))
        if len(gaps) >= 5:
            break
    if not gaps:
        return {"name": "document_number_continuity", "passed": True,
                "details": f"רצף תקין ({numbers[0]}–{numbers[-1]})"}
    return {
        "name": "document_number_continuity",
        "passed": False,
        "details": f"פערי מספור: חסרים {'; '.join(gaps)}",
    }


def _near_duplicate_bills(db, org_id: int) -> dict[str, Any]:
    """W6.5: כפילות-כמעט בלי external_id — אותו ספק+סכום+תאריך פעמיים.

    בדיוק התרחיש שניפח ₪150K בעבר (duplicate_gate) — הבדיקה הקיימת
    (external_id) עיוורת להזנה ידנית כפולה.
    """
    from ..models import Bill

    dupes = (
        db.query(Bill.vendor_id, Bill.total, Bill.issue_date, func.count(Bill.id))
        .filter(Bill.organization_id == org_id, Bill.vendor_id.isnot(None))
        .group_by(Bill.vendor_id, Bill.total, Bill.issue_date)
        .having(func.count(Bill.id) > 1)
        .all()
    )
    if not dupes:
        return {"name": "near_duplicate_bills", "passed": True,
                "details": "אין חשבונות ספק כפולים (ספק+סכום+תאריך)"}
    sample = "; ".join(
        f"ספק {v} סכום {t} בתאריך {d} ×{n}" for v, t, d, n in dupes[:3]
    )
    return {
        "name": "near_duplicate_bills",
        "passed": False,
        "details": f"{len(dupes)} קבוצות כפילות-כמעט: {sample}",
    }


_CHECKS = (
    _bills_nonnegative,
    _no_paid_invoice_with_open_balance,
    _invoice_balance_consistency,
    _currency_whitelist,
    _of_balance_freshness,
    _duplicate_external_ids,
    _empty_draft_expenses_count,
    # W6.5 (21/08/2026) — בקרות ספרים שוטפות:
    _trial_balance_balanced,
    _document_number_continuity,
    _near_duplicate_bills,
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
