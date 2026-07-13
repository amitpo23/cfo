"""אימות משולש לדיווחי מס — כלל מחייב (הנחיית בעלים, 13/07/2026):
כל פלט דיווח לרשויות עובר לפחות שלוש בדיקות בלתי-תלויות לפני הפקה.
דיווח שגוי אינו רק הפסד כספי — הוא עבירה על החוק.

שלוש הבדיקות:
1. reconciliation — קובץ ה-PCN874 מסתכם 1:1 מול דוח המע"מ באותם פרמטרים.
2. independent_recomputation — סכימה עצמאית של מסמכי הגלם בשאילתות ישירות
   (נתיב קוד נפרד מ-select_vat_documents) + בדיקות שפיות: תקרת שיעור מע"מ
   פר-מסמך, אין external_id כפול, סימני זיכוי עקביים.
3. completeness_and_cross_source — כנות: קבלות שממתינות לתיוק בתקופה (המע"מ
   שלהן לא כלול!), והנחיה להצלבה מול ספרי SUMIT (שאינה אוטומטית — נאמר
   במפורש במקום לשתוק).

סטטוס כולל: pass / warn / fail. כשל אינו חוסם הורדה טכנית אך ה-UI מציג
אותו באדום ליד כפתורי ההפקה — לעולם לא הפקה שקטה.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional

# תקרת שיעור מע"מ פר-מסמך לבדיקת שפיות: השיעור החוקי (18% נכון ל-2025-2026)
# + מרווח עיגול. מסמך שחורג — דגל אדום (נתון שגוי או פיצול לא נכון).
MAX_VAT_RATE = 0.185

# שער טריות סנכרון (ממצא אודיט אליהב 2026-07-13, ממצא 5): מעל כמות שעות זו
# מאז הסנכרון המוצלח האחרון של SUMIT — הדוח נגזר מנתונים ישנים בלי אזהרה.
# 26 שעות = מרווח סביר מעבר ל-24 (כדי לא להתריע שווא על ריצה יומית שגרתית).
STALE_SYNC_HOURS = 26


def _independent_sums(db, org_id: int, start: date, end: date, basis: str) -> dict[str, float]:
    """חישוב עצמאי בשאילתות אגרגציה ישירות — במתכוון לא דרך select_vat_documents."""
    from ..models import Invoice, Bill, Expense, InvoiceStatus, BillStatus

    # עסקאות: תמיד לפי תאריך מסמך; קבלות (סוגי raw '2'/'5' legacy/'receipt')
    # מוחרגות; זיכוי מנורמל (credit_note) נכלל בסימנו.
    receipt_types = ("2", "5", "receipt")
    output_vat = 0.0
    for inv in db.query(Invoice).filter(
        Invoice.organization_id == org_id,
        Invoice.issue_date >= start, Invoice.issue_date <= end,
        Invoice.status.notin_([InvoiceStatus.DRAFT, InvoiceStatus.VOID, InvoiceStatus.CANCELLED]),
    ).all():
        raw = inv.raw_data if isinstance(inv.raw_data, dict) else {}
        dt = str(raw.get("document_type") or "")
        if dt in receipt_types and dt != "credit_note":
            continue
        output_vat += float(inv.tax or 0)

    # תשומות: bills לפי הבסיס הנבחר + expenses שאינן כפולות-Bill.
    bill_ext_ids = set()
    input_vat = 0.0
    for b in db.query(Bill).filter(Bill.organization_id == org_id).all():
        if b.status in (BillStatus.DRAFT, BillStatus.VOID):
            continue
        doc_d = b.issue_date or b.due_date
        sel = (b.created_at.date() if (basis == "captured" and b.created_at) else doc_d)
        if not sel or not (start <= sel <= end):
            continue
        if b.external_id:
            bill_ext_ids.add(str(b.external_id))
        input_vat += float(b.tax or 0)
    for e in db.query(Expense).filter(Expense.organization_id == org_id).all():
        if str(getattr(e, "status", "") or "").lower() == "error":
            continue
        if e.external_id and str(e.external_id) in bill_ext_ids:
            continue
        doc_d = e.expense_date
        sel = (e.created_at.date() if (basis == "captured" and e.created_at) else doc_d)
        if not sel or not (start <= sel <= end):
            continue
        input_vat += float(e.vat_amount or 0)

    return {"output_vat": round(output_vat, 2), "input_vat": round(input_vat, 2)}


def _sanity_issues(report: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    seen: dict[str, int] = {}
    for d in report.get("documents", []):
        vat = float(d.get("vat") or 0)
        sub = float(d.get("amount") or 0)
        if abs(vat) > abs(sub) * MAX_VAT_RATE + 0.02 and abs(vat) > 1:
            issues.append(f"מסמך {d.get('number')}: מע\"מ {vat} חורג מהשיעור החוקי ביחס לנטו {sub}")
        if vat != 0 and sub != 0 and (vat > 0) != (sub > 0):
            issues.append(f"מסמך {d.get('number')}: סימן המע\"מ ({vat}) מנוגד לסימן הנטו ({sub})")
        key = f"{d.get('type')}:{d.get('number')}"
        if d.get("number"):
            seen[key] = seen.get(key, 0) + 1
    issues += [f"מסמך כפול בדוח: {k} (×{n})" for k, n in seen.items() if n > 1]
    return issues


def _sync_freshness(db, org_id: int) -> dict[str, Any]:
    """מועד הסנכרון המוצלח האחרון של SUMIT לארגון — כדי לחסום/להתריע על הפקת
    דוח רגולטורי מנתונים ישנים (ראו dashboard_service._get_last_sync_by_source
    לשימוש קיים דומה בטבלת SyncRun)."""
    from ..models import SyncRun, SyncStatus

    succeeded = [SyncStatus.COMPLETED, SyncStatus.PARTIAL]
    last_run = db.query(SyncRun).filter(
        SyncRun.organization_id == org_id,
        SyncRun.source == "sumit",
        SyncRun.status.in_(succeeded),
        SyncRun.finished_at.isnot(None),
    ).order_by(SyncRun.finished_at.desc()).first()

    if not last_run or not last_run.finished_at:
        return {
            "stale": True, "last_sync_at": None, "hours_since": None,
            "message": (
                "⚠️ אזהרה חמורה: מעולם לא בוצע סנכרון SUMIT מוצלח לארגון זה — "
                "אין להגיש דיווח על בסיס נתונים שלא סונכרנו מעולם."
            ),
        }

    hours = (datetime.utcnow() - last_run.finished_at).total_seconds() / 3600.0
    last_sync_iso = last_run.finished_at.isoformat()
    if hours <= STALE_SYNC_HOURS:
        return {"stale": False, "last_sync_at": last_sync_iso,
                "hours_since": round(hours, 1), "message": None}

    age = f"{hours / 24:.1f} ימים" if hours >= 48 else f"{hours:.1f} שעות"
    return {
        "stale": True, "last_sync_at": last_sync_iso, "hours_since": round(hours, 1),
        "message": (
            f"⚠️ הנתונים בני {age} — סנכרון SUMIT אחרון: "
            f"{last_run.finished_at.date().isoformat()}; אין להגיש בלי רענון."
        ),
    }


def _pending_drafts(db, org_id: int, start: date, end: date) -> int:
    """קבלות שהועלו ל-SUMIT וטרם תויקו — סונכרנו כרשומות הוצאה בסכום 0.
    המע"מ שלהן לא כלול בשום דוח עד תיוק."""
    from ..models import Expense

    n = 0
    for e in db.query(Expense).filter(Expense.organization_id == org_id).all():
        total = float(getattr(e, "total", 0) or 0) or float(getattr(e, "amount", 0) or 0)
        if total != 0:
            continue
        d = e.expense_date or (e.created_at.date() if e.created_at else None)
        if d and start <= d <= end:
            n += 1
    return n


def verify_filing(db, org_id: int, year: int, month: int, *,
                  months: int = 1, basis: str = "document") -> dict[str, Any]:
    """מריץ את שלוש הבדיקות ומחזיר תוצאה מפורטת + סטטוס כולל."""
    from . import financial_synthesis, pcn874
    from .daily_reports_service import vat_report_period

    report = vat_report_period(db, org_id, year, month, months=months, basis=basis)
    pb = financial_synthesis.period_bounds(year, month, months)
    start, end = pb["start"], pb["end"]
    checks: list[dict[str, Any]] = []

    # --- בדיקה 1: תיאום דוח ↔ קובץ PCN874 ---
    pcn = pcn874.build_pcn874(db, org_id, year, month, months=months, basis=basis)
    p_sum = pcn.get("summary", {})
    diff_out = abs(float(p_sum.get("output_vat", 0)) - float(report["output_vat"]))
    diff_in = abs(float(p_sum.get("input_vat", 0)) - float(report["input_vat"]))
    checks.append({
        "name": "reconciliation",
        "label": "תיאום דוח ↔ קובץ PCN874",
        "passed": diff_out <= 0.01 and diff_in <= 0.01,
        "details": ("הקובץ מסתכם 1:1 מול הדוח" if diff_out <= 0.01 and diff_in <= 0.01
                    else f"פער: עסקאות ₪{diff_out:.2f}, תשומות ₪{diff_in:.2f}"),
    })

    # --- בדיקה 2: חישוב עצמאי + שפיות ---
    indep = _independent_sums(db, org_id, start, end, basis)
    diff_out2 = abs(indep["output_vat"] - float(report["output_vat"]))
    diff_in2 = abs(indep["input_vat"] - float(report["input_vat"]))
    sanity = _sanity_issues(report)
    ok2 = diff_out2 <= 0.05 and diff_in2 <= 0.05 and not sanity
    details2 = []
    if diff_out2 > 0.05 or diff_in2 > 0.05:
        details2.append(f"סטייה מחישוב עצמאי: עסקאות ₪{diff_out2:.2f}, תשומות ₪{diff_in2:.2f}")
    details2 += sanity
    checks.append({
        "name": "independent_recomputation",
        "label": "חישוב עצמאי ובדיקות שפיות",
        "passed": ok2,
        "details": "חישוב עצמאי תואם; כל בדיקות השפיות עברו" if ok2 else "; ".join(details2),
    })

    # --- בדיקה 3: שלמות והצלבה חיצונית ---
    drafts = _pending_drafts(db, org_id, start, end)
    freshness = _sync_freshness(db, org_id)
    # אזהרה (לא כשל) כשיש טיוטות ממתינות ו/או כשהסנכרון האחרון ישן/לא קיים —
    # הדוח נכון למה שקלוט, אבל ייתכן שהוא חסר/מיושן. ראו ממצא אודיט אליהב
    # 2026-07-13 (ממצא 5): PCN הופק מנתונים בני 3 שבועות בלי שום אזהרה.
    checks.append({
        "name": "completeness_and_cross_source",
        "label": "שלמות קליטה והצלבה חיצונית",
        "passed": None if (drafts > 0 or freshness["stale"]) else True,
        "details": (
            (f"⚠️ {drafts} קבלות ממתינות לתיוק בתקופה — המע\"מ שלהן אינו כלול בדוח. " if drafts else "אין קבלות ממתינות לתיוק בתקופה. ")
            + (freshness["message"] + " " if freshness["message"] else "")
            + "הצלבה מול ספרי SUMIT (מסך דיווח מע\"מ בתיק ההנה\"ח) — ידנית; ודא התאמה לפני שידור."
        ),
        "pending_drafts": drafts,
        "last_sync_sumit": freshness["last_sync_at"],
        "sync_age_hours": freshness["hours_since"],
    })

    failed = any(c["passed"] is False for c in checks)
    warned = any(c["passed"] is None for c in checks)
    return {
        "status": "fail" if failed else ("warn" if warned else "pass"),
        "checks": checks,
        "period": report["period"],
        "basis": basis,
    }
