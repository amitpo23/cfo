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
   במפורש במקום לשתוק). כולל גם (P0 2026-07): מועמדי-כפילות ברמת ודאות
   גבוהה (duplicate_gate, ח.פ+אסמכתא זהים) בתקופה — כשל אם נמצאו; ואזהרת
   יחס מע"מ (input_vat/סך-הוצאות מתחת ל-3% עם 10+ מסמכים — חשד למפתחות
   שהוזנו ללא פיצול מע"מ).

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

# שער יחס מע"מ (ממצא עומר ועודד): 6.7K מתוך 731K = 0.9% — סימן ברור למפתחות
# הוצאה שהוזנו ללא פיצול מע"מ (VAT=0 בטעות). 3% הוא סף שפיות גס, לא שיעור
# מע"מ תקני — נועד רק לתפוס מקרי קיצון בבירור לא-סבירים, לא לאמת את השיעור.
MIN_SANE_VAT_RATIO = 0.03
MIN_DOCS_FOR_VAT_RATIO_CHECK = 10


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
    from .vat_utils import expense_counts

    for e in db.query(Expense).filter(Expense.organization_id == org_id).all():
        # יישור לקריטריון הקנוני של הדוח (select_vat_documents): רק הוצאות
        # "filed" נספרות. תיקון תואם P0 2026-07: לפני שער הכפילויות, "error"
        # היה היוצא-מן-הכלל היחיד — כעת "pending"/"duplicate"/"review" גם הן
        # לא-סופיות ובלי התיקון היו מנופחות בחישוב העצמאי בזמן שהדוח (שמסתמך
        # על expense_counts) מדלג עליהן, ומייצרות פער-שווא שמפיל בדיקה 2.
        if not expense_counts(getattr(e, "status", None)):
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
    """מועד המשיכה המוצלחת האחרונה של מסמכי SUMIT (invoices/bills) לארגון.

    מקור האמת: SyncCheckpoint.last_success_at פר-ישות — לא SyncRun. ריצה
    שעתית נרשמת COMPLETED גם כשה-circuit breaker דילג על כל הישויות (אומת
    חי 13/07: org 1 עם ריצות "COMPLETED" בזמן שה-checkpoints שלו ללא הצלחה
    ובמעגל פתוח בגלל חסימת ה-obligo) — כך שסינון לפי ריצות מפספס בדיוק את
    המצב שהשער נועד לתפוס. fallback ל-SyncRun רק כשאין checkpoints (ארגון
    מלפני M1)."""
    from ..models import SyncRun, SyncStatus

    circuit_until = None
    last_success = None
    try:
        from ..models import SyncCheckpoint

        cps = db.query(SyncCheckpoint).filter(
            SyncCheckpoint.organization_id == org_id,
            SyncCheckpoint.source == "sumit",
            SyncCheckpoint.entity_type.in_(["invoices", "bills"]),
        ).all()
        if cps:
            successes = [cp.last_success_at for cp in cps if cp.last_success_at]
            last_success = max(successes) if successes else None
            opens = [cp.circuit_open_until for cp in cps
                     if cp.circuit_open_until and cp.circuit_open_until > datetime.utcnow()]
            circuit_until = max(opens) if opens else None
            if last_success is None:
                msg = ("⚠️ אזהרה חמורה: משיכת המסמכים מ-SUMIT מעולם לא הצליחה "
                       "לארגון זה (checkpoints ללא הצלחה)")
                if circuit_until:
                    msg += f"; הסנכרון מושהה עד {circuit_until.isoformat()} בגלל חסימת API"
                return {"stale": True, "last_sync_at": None, "hours_since": None,
                        "circuit_open_until": circuit_until.isoformat() if circuit_until else None,
                        "message": msg + " — אין להגיש בלי רענון."}
    except Exception:  # טבלת checkpoints לא קיימת (סביבה ישנה) — fallback לריצות
        pass

    if last_success is None:
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
        last_success = last_run.finished_at

    hours = (datetime.utcnow() - last_success).total_seconds() / 3600.0
    last_sync_iso = last_success.isoformat()
    if hours <= STALE_SYNC_HOURS:
        return {"stale": False, "last_sync_at": last_sync_iso,
                "hours_since": round(hours, 1), "message": None}

    age = f"{hours / 24:.1f} ימים" if hours >= 48 else f"{hours:.1f} שעות"
    return {
        "stale": True, "last_sync_at": last_sync_iso, "hours_since": round(hours, 1),
        "message": (
            f"⚠️ הנתונים בני {age} — משיכת מסמכי SUMIT אחרונה: "
            f"{last_success.date().isoformat()}; אין להגיש בלי רענון."
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


def _period_documents(db, org_id: int, start: date, end: date, basis: str,
                      *, filed_expenses_only: bool = False) -> list[tuple]:
    """כל מסמכי Bill+Expense (לא-בטלים) של הארגון בתקופת הדיווח, כ-tuples
    (source, id, tax_id, reference, amount, doc_date, external_id) — קלט
    משותף לבדיקת כפילויות וליחס המע"מ.

    filed_expenses_only: ברירת מחדל False (כולל pending/review/duplicate) —
    כך שער הכפילויות תופס גם כפילות שעדיין לא תויקה. יחס המע"מ חייב True:
    report["input_vat"] (המונה) סופר רק expenses "filed" (expense_counts) —
    לכלול גם לא-סופיות במכנה (סך-ההוצאות) מייצר יחס-שווא נמוך מדי ומאבחן לא
    נכון "מפתחות ללא מע\"מ" כשההסבר האמיתי הוא סתם "עוד לא תויק"."""
    from ..models import Bill, BillStatus, Expense
    from .vat_utils import expense_counts

    items: list[tuple] = []
    for b in db.query(Bill).filter(Bill.organization_id == org_id).all():
        if b.status in (BillStatus.DRAFT, BillStatus.VOID):
            continue
        doc_d = b.issue_date or b.due_date
        sel = (b.created_at.date() if (basis == "captured" and b.created_at) else doc_d)
        if not sel or not (start <= sel <= end):
            continue
        tax_id = b.vendor.tax_id if b.vendor else None
        items.append(("bill", b.id, tax_id, b.bill_number, float(b.total or 0), doc_d,
                      b.external_id))
    for e in db.query(Expense).filter(Expense.organization_id == org_id).all():
        status = getattr(e, "status", None)
        if str(status or "").lower() == "error":
            continue
        if filed_expenses_only and not expense_counts(status):
            continue
        doc_d = e.expense_date
        sel = (e.created_at.date() if (basis == "captured" and e.created_at) else doc_d)
        if not sel or not (start <= sel <= end):
            continue
        items.append(("expense", e.id, e.supplier_tax_id, e.invoice_number,
                      float(e.total or 0), doc_d, e.external_id))
    return items


def _duplicate_high_pairs(db, org_id: int, start: date, end: date, basis: str) -> list[dict]:
    """מפעיל את שער הכפילויות (duplicate_gate) על כל מסמך בתקופת הדיווח מול
    *כלל* מסמכי הארגון (משני הצדדים — Bill+Expense, גם מול מסמכים מחוץ
    לתקופה — זו בדיוק תבנית הכפילות שנתפסה: מנה שנסגרה חופפת למנה שנפתחה
    בתקופה מאוחרת יותר). מחזיר זוגות HIGH ייחודיים (בלי כפילות דיווח פר-זוג)."""
    from .duplicate_gate import find_duplicate_candidates

    items = _period_documents(db, org_id, start, end, basis)
    seen_pairs: set[frozenset] = set()
    pairs: list[dict] = []
    for source, id_, tax_id, ref, amount, doc_date, ext_id in items:
        candidates = find_duplicate_candidates(
            db, org_id, supplier_tax_id=tax_id, reference=ref,
            amount=amount, doc_date=doc_date, exclude_id=id_, exclude_source=source,
            external_id=ext_id,
        )
        for c in candidates:
            if c["confidence"] != "HIGH":
                continue
            if c["source"] == source and c["id"] == id_:
                continue  # self-match guard
            key = frozenset({(source, id_), (c["source"], c["id"])})
            if key in seen_pairs:
                continue
            seen_pairs.add(key)
            pairs.append({
                "a": {"source": source, "id": id_},
                "b": {"source": c["source"], "id": c["id"]},
                "reference": ref,
                "amount": amount,
            })
    return pairs


def _vat_ratio_warning(db, org_id: int, start: date, end: date, basis: str,
                       input_vat: float) -> Optional[dict[str, Any]]:
    """יחס input_vat/סך-הוצאות התקופה מתחת ל-3% עם 10+ מסמכים -> חשד למפתחות
    שהוזנו ללא פיצול מע"מ (ממצא עומר ועודד: ₪6.7K מתוך ₪731K = 0.9%).

    filed_expenses_only=True: המונה (input_vat) סופר רק expenses "filed" —
    המכנה (סך-ההוצאות) חייב לספור אותה אוכלוסייה בדיוק, אחרת הוצאות
    שטרם תויקו מנפחות את המכנה ומדליפות אזהרה שגויה על תקופה שבאמת רק
    ממתינה לתיוק (ולא "מפתח ללא מע\"מ")."""
    items = _period_documents(db, org_id, start, end, basis, filed_expenses_only=True)
    doc_count = len(items)
    total_amount = sum(amount for _src, _id, _tax, _ref, amount, _d, _ext in items)
    if doc_count < MIN_DOCS_FOR_VAT_RATIO_CHECK or total_amount <= 0:
        return None
    ratio = input_vat / total_amount
    if ratio >= MIN_SANE_VAT_RATIO:
        return None
    return {
        "ratio": round(ratio, 4),
        "doc_count": doc_count,
        "total_amount": round(total_amount, 2),
        "input_vat": round(input_vat, 2),
    }


def _find_crosscheck(db, org_id: int, period: str, basis: str):
    """שליפת רשומת ההצלבה המוקלטת (FilingCrosscheck) לתקופה+בסיס נתונים,
    אם קיימת. ``period`` חייב להיות בפורמט הקנוני מ-financial_synthesis.
    period_label -- אותו מקור בדיוק שמייצר routes/daily_reports.py בעת
    ה-upsert -- אחרת ההצלבה "נעלמת" בשקט (ראה advisor: סיכון פורמט כפול)."""
    from ..models import FilingCrosscheck

    return db.query(FilingCrosscheck).filter(
        FilingCrosscheck.organization_id == org_id,
        FilingCrosscheck.period == period,
        FilingCrosscheck.basis == basis,
    ).first()


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
    crosscheck = _find_crosscheck(db, org_id, report["period"], basis)
    # אזהרה (לא כשל) כשיש טיוטות ממתינות ו/או כשהסנכרון האחרון ישן/לא קיים —
    # הדוח נכון למה שקלוט, אבל ייתכן שהוא חסר/מיושן. ראו ממצא אודיט אליהב
    # 2026-07-13 (ממצא 5): PCN הופק מנתונים בני 3 שבועות בלי שום אזהרה.
    #
    # כשקיימת רשומת FilingCrosscheck (הרגל שלישי: הצלבה *מוקלטת* מול ספרי
    # SUMIT, ולא סתם הנחיה) — ההצלבה עצמה קובעת את passed: פער ≤ ₪1 = ✓,
    # פער גדול = ✗ עם הפער בש"ח. בלי רשומה — ההתנהגות הקיימת (אין כשל, רק
    # אזהרה אם יש טיוטות/סנכרון ישן, עם הנחיה ידנית).
    crosscheck_info = None
    if crosscheck is not None:
        diff_in = abs(float(crosscheck.books_input_vat) - float(report["input_vat"]))
        diff_out = None
        if crosscheck.books_output_vat is not None:
            diff_out = abs(float(crosscheck.books_output_vat) - float(report["output_vat"]))
        max_diff = diff_in if diff_out is None else max(diff_in, diff_out)
        passed3 = max_diff <= 1.0
        if passed3:
            cross_sentence = (
                f"הוצלב מול ספרי SUMIT (הוקלד ב-{crosscheck.created_at.date().isoformat()}) "
                "— התאמה."
            )
        else:
            gap_parts = [f"תשומות ₪{diff_in:.2f}"]
            if diff_out is not None:
                gap_parts.append(f"עסקאות ₪{diff_out:.2f}")
            cross_sentence = (
                f"⚠️ פער מול ספרי SUMIT (הוקלד ב-{crosscheck.created_at.date().isoformat()}): "
                + "; ".join(gap_parts)
            )
        crosscheck_info = {
            "present": True,
            "recorded_at": crosscheck.created_at.isoformat(),
            "books_input_vat": float(crosscheck.books_input_vat),
            "books_output_vat": (float(crosscheck.books_output_vat)
                                 if crosscheck.books_output_vat is not None else None),
            "diff_input_vat": round(diff_in, 2),
            "diff_output_vat": round(diff_out, 2) if diff_out is not None else None,
        }
    else:
        passed3 = None if (drafts > 0 or freshness["stale"]) else True
        cross_sentence = (
            "הצלבה מול ספרי SUMIT (מסך דיווח מע\"מ בתיק ההנה\"ח) — ידנית; ודא התאמה לפני שידור."
        )
        crosscheck_info = {"present": False}

    # --- שער כפילויות (P0, 2026-07): מועמדי-כפילות HIGH בתקופת הדיווח ---
    # ממצא: מנה 4 חפפה 14 שורות למנה 2 הסגורה, כמעט כפל-ספירה של ₪150K. אם
    # נמצא זוג HIGH — הבדיקה נכשלת (לא אזהרה): אסור להגיש דיווח שיכול לכלול
    # ספירה כפולה.
    dup_pairs = _duplicate_high_pairs(db, org_id, start, end, basis)
    dup_details = None
    if dup_pairs:
        passed3 = False
        parts = [f"{p['a']['source']} #{p['a']['id']} ↔ {p['b']['source']} #{p['b']['id']} (₪{p['amount']:.2f})"
                 for p in dup_pairs[:10]]
        dup_details = (
            f"⚠️ נמצאו {len(dup_pairs)} מועמדי-כפילות ברמת ודאות גבוהה (ח.פ+אסמכתא תואמים) "
            f"בתקופת הדיווח: " + "; ".join(parts)
        )

    # --- שער יחס מע"מ: אזהרה על מפתחות ללא מע"מ (ממצא עומר ועודד) ---
    # ₪6.7K מתוך ₪731K = 0.9% — סימן ברור להוצאות שהוזנו עם VAT=0 בטעות.
    # אזהרה בלבד (לא כשל) — אלא אם כן כבר נכשל בגלל כפילויות.
    vat_ratio = _vat_ratio_warning(db, org_id, start, end, basis, float(report["input_vat"]))
    vat_ratio_details = None
    if vat_ratio is not None:
        vat_ratio_details = (
            f"⚠️ חשד למפתחות ללא מע\"מ: יחס תשומות/סך-הוצאות בתקופה "
            f"{vat_ratio['ratio']*100:.1f}% (₪{vat_ratio['input_vat']:.2f} מתוך "
            f"₪{vat_ratio['total_amount']:.2f} על {vat_ratio['doc_count']} מסמכים) — "
            f"נמוך משמעותית מ-{MIN_SANE_VAT_RATIO*100:.0f}% הצפוי."
        )
        if passed3 is True:  # כשל בכפילויות גובר; אזהרה לא מורידה כשל, רק True->None
            passed3 = None

    checks.append({
        "name": "completeness_and_cross_source",
        "label": "שלמות קליטה והצלבה חיצונית",
        "passed": passed3,
        "details": (
            (f"⚠️ {drafts} קבלות ממתינות לתיוק בתקופה — המע\"מ שלהן אינו כלול בדוח. " if drafts else "אין קבלות ממתינות לתיוק בתקופה. ")
            + (freshness["message"] + " " if freshness["message"] else "")
            + cross_sentence
            + (" " + dup_details if dup_details else "")
            + (" " + vat_ratio_details if vat_ratio_details else "")
        ),
        "pending_drafts": drafts,
        "last_sync_sumit": freshness["last_sync_at"],
        "sync_age_hours": freshness["hours_since"],
        "crosscheck": crosscheck_info,
        "duplicate_candidates": dup_pairs,
        "vat_ratio_warning": vat_ratio,
    })

    failed = any(c["passed"] is False for c in checks)
    warned = any(c["passed"] is None for c in checks)
    return {
        "status": "fail" if failed else ("warn" if warned else "pass"),
        "checks": checks,
        "period": report["period"],
        "basis": basis,
    }
