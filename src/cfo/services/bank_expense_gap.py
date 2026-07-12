"""
מנוע פער בנק-חשבוניות — לכל תנועת בנק יוצאת (amount<0), בודק אם היא הוצאה
אמיתית שדורשת מסמך הנה"ח (חשבונית/הוצאה), מסווג החרגות (סליקת אשראי, מיסים,
שכר, הלוואות, העברות עצמיות, עמלות בנק), ובודק אם קיים כנגדה Bill/Expense
תואם. מייצר דוח פער חודשי (`gap_report`) וסורק יומית תנועות חדשות ללא מסמך
כדי ליצור התרעות (`scan_and_alert` -> CfoInsight, insight_type="missing_document").

יחס למודולים קיימים (ולא כפילות מקרית):
  * `bank_query_service.classify_missing_documents` — כלי בוט קיים (M8) עם
    טקסונומיה אחרת (cash/transfers/standing_orders/...), ה-shape שלו נעול
    ע"י טסטים קיימים (tests/test_ai_chat_tools.py, tests/test_bank_query_service.py).
    כאן יש טקסונומיה חדשה וממוקדת-יעד (card_settlement/tax_payment/salary/
    loan_or_finance/self_transfer/bank_fee/other_excluded/expense_candidate)
    לפי דרישת מנוע הפער — לא נועד להחליף את הכלי הקיים.
  * `financial_synthesis.build_synthesis` — משתמש ב-`reconcile()` (state
    מבוסס-ניקוד, greedy assignment בין כל התנועות למסמכים בבת אחת).
    `has_document` כאן היא בדיקת-קיום פר-תנועה, פשוטה בכוונה (סכום±₪1,
    טווח±7 ימים), כנדרש ע"י ספסיפיקציית המנוע הזה — לא מחליפה את reconcile.

כל הפונקציות פועלות ישירות על שורות ORM (BankTransaction/Bill/Expense/Invoice)
ולא דורשות DB חדש — עקביות עם bank_reconciliation.reconcile_organization
שגם הוא טוען את כל שורות הארגון לפייתון ומתאים שם.
"""
from __future__ import annotations

import calendar
import re
from datetime import date, timedelta
from typing import Any, Optional


# --------------------------------------------------------------------- #
# טקסונומיית סיווג — קטגוריית Open Finance (main/sub) קודם, מילות מפתח
# בתיאור כ-fallback.
# --------------------------------------------------------------------- #
CARD_SETTLEMENT_KEYWORDS = [
    "ישראכרט", "isracard", "ויזה", "cal", "כאל", "מקס", "max",
    "אמריקן אקספרס", "לאומי קארד", "diners",
]
CARD_SETTLEMENT_CATEGORY_SUB = {"CREDIT_CARD_CHECKING", "CREDIT_CARD"}
CARD_SETTLEMENT_CATEGORY_MAIN = {"CREDIT_CARD"}

TAX_KEYWORDS = [
    "מע\"מ", "מעמ", "מס הכנסה", "ביטוח לאומי", "רשות המסים",
    "מקדמות מס", "מקדמת מס",
]
TAX_CATEGORY_MAIN = {"TAXES", "TAX"}

SALARY_KEYWORDS = ["שכר", "משכורת", "תלוש שכר", "תלוש"]
SALARY_CATEGORY_MAIN = {"SALARY"}

LOAN_KEYWORDS = ["הלוואה", "משכנתא", "ריבית והצמדה", "החזר הלוואה", "מסגרת אשראי"]
LOAN_CATEGORY_MAIN = {"LOAN", "LOANS", "FINANCE"}

SELF_TRANSFER_KEYWORDS = [
    "העברה עצמית", "העברה לחשבון אחר על שמי", "הפקדה לחיסכון",
    "הפקדה לפיקדון", "לחיסכון",
]
# "TRANSFER" הכללי בכוונה לא כאן: תשלום לספק בהעברה בנקאית מסווג אצל
# Open Finance גם הוא TRANSFER/BANK_TRANSFER — החרגתו הייתה מעלימה הוצאות
# אמיתיות מהדוח (למשל שכ"ט עו"ד ששולם בהעברה). העברה עצמית מזוהה רק לפי
# תת-קטגוריות חיסכון/פנימי או מילות מפתח מפורשות.
SELF_TRANSFER_CATEGORY_MAIN = {"SAVINGS", "INTERNAL_TRANSFER"}

BANK_FEE_KEYWORDS = ["עמלת", "עמלה ", "עמלות", "דמי ניהול חשבון", "דמי כרטיס"]
BANK_FEE_CATEGORY_MAIN = {"BANK_FEES", "FEES"}

OTHER_EXCLUDED_KEYWORDS = ["משיכת מזומן", "משיכה מבנקט", "כספומט"]
OTHER_EXCLUDED_CATEGORY_MAIN = {"CASH_WITHDRAWALS"}

# טווח וסטיית סכום לבדיקת "יש מסמך" לפי סכום+תאריך (כשאין matched_entity_*).
DATE_WINDOW_DAYS = 7
AMOUNT_TOLERANCE = 1.0

# --------------------------------------------------------------------- #
# suppliers_missing_invoices — העברות גנריות ללא נמען מזוהה. רשימה נפרדת
# מ-TRANSFER_KEYWORDS ב-bank_query_service.py בכוונה: זו לא טקסונומיית
# סיווג (classify_transaction עדיין מחזירה expense_candidate לתנועות אלו —
# ראה test_classify_bank_transfer_stays_expense_candidate), אלא כלל נפרד
# שחל רק אחרי הסיווג, ורק כשאין merchantName (יש merchant -> תמיד הולך
# לרשימת הספקים, גם אם התיאור מכיל את אחת ממילות המפתח): אם התיאור הוא
# נוסח בנקאי גנרי ("העברה לבנק אחר" וכו') — אין לנו שם ספק לקבץ לפיו,
# אז זה הולך ל-unidentified_transfers ולא נספר כ"ספק" בטעות. הזיהוי
# עצמו הוא match מילות-מפתח פרגמטי (לא NLP) — פסוק ל-false positive
# (החמצת קיבוץ ספק אמיתי) על פני false negative (העברה גנרית שנספרת
# כספק עם שם משונה).
GENERIC_TRANSFER_KEYWORDS = [
    "העברה לבנק אחר", "העב' ללקוח אחר", "העברה ללקוח אחר",
    "העברה ב bit", "העברה ב-bit", "העברה בביט",
    "הוראת קבע", "הוראת-קבע",
]


def _normalize_description(desc: Optional[str]) -> str:
    """נרמול תיאור תנועה לשימוש כשם ספק/מפתח קיבוץ: רווחים מרובים -> אחד, strip."""
    return re.sub(r"\s+", " ", (desc or "")).strip()


def _transfer_purpose(txn) -> Optional[str]:
    """"מטרת ההעברה" (purposeDescription) — ההערה שהמעביר כתב בעת ביצוע
    ההעברה. חיה ב-raw_data.description.additionalInfo, שמגיע מהספק לעיתים
    כמחרוזת JSON ולעיתים כאובייקט. זה לרוב המידע היחיד שמזהה את הנמען
    בהעברות "העברה לבנק אחר" (למשל "שכ\"ד", "סייעת לגיא")."""
    raw = getattr(txn, "raw_data", None)
    if not isinstance(raw, dict):
        return None
    desc = raw.get("description")
    if not isinstance(desc, dict):
        return None
    info = desc.get("additionalInfo")
    if isinstance(info, str):
        try:
            import json
            info = json.loads(info)
        except Exception:
            return None
    if not isinstance(info, dict):
        return None
    val = info.get("purposeDescription")
    val = val.strip() if isinstance(val, str) else None
    return val or None


def _is_generic_transfer(desc: Optional[str]) -> bool:
    """תיאור שהוא נוסח בנקאי גנרי ולא מזהה נמען ספציפי — ראה הערה למעלה."""
    return _contains_any(desc, GENERIC_TRANSFER_KEYWORDS)


def _contains_any(text: Optional[str], keywords: list[str]) -> bool:
    t = (text or "").lower()
    return any(kw.lower() in t for kw in keywords)


def _category_field(txn, field: str) -> Optional[str]:
    """שליפה בטוחה של category.main/sub מתוך raw_data — לעולם לא נכשלת על
    מבנה חסר/משונה."""
    raw = getattr(txn, "raw_data", None)
    if not isinstance(raw, dict):
        return None
    cat = raw.get("category")
    if not isinstance(cat, dict):
        return None
    val = cat.get(field)
    return val if isinstance(val, str) else None


def _merchant_name(txn) -> Optional[str]:
    raw = getattr(txn, "raw_data", None)
    if not isinstance(raw, dict):
        return None
    val = raw.get("merchantName")
    return val if isinstance(val, str) else None


def _money(amount: float, currency: str = "ILS") -> str:
    symbol = "₪" if currency == "ILS" else currency
    return f"{amount:,.2f} {symbol}"


def classify_transaction(txn) -> str:
    """מסווג תנועת בנק יוצאת (amount<0) לאחת מהקטגוריות:
    card_settlement, tax_payment, salary, loan_or_finance, self_transfer,
    bank_fee, other_excluded, או ברירת המחדל expense_candidate (הוצאה
    אמיתית שצריכה מסמך). כשאין סיווג ברור — expense_candidate: עדיף
    false-positive שייבדק מאשר החמצת הוצאה בלי מסמך.

    תנועות נכנסות (amount>=0) אינן "הוצאה" מטבען — מוחזר other_excluded
    כדי שקריאה שגויה על תנועת זיכוי לא תיספר בטעות כמועמדת-הוצאה."""
    amount = float(getattr(txn, "amount", 0) or 0)
    if amount >= 0:
        return "other_excluded"

    desc = getattr(txn, "description", None) or ""
    cat_main = (_category_field(txn, "main") or "").upper()
    cat_sub = (_category_field(txn, "sub") or "").upper()

    if (cat_sub in CARD_SETTLEMENT_CATEGORY_SUB or cat_main in CARD_SETTLEMENT_CATEGORY_MAIN
            or _contains_any(desc, CARD_SETTLEMENT_KEYWORDS)):
        return "card_settlement"
    if cat_main in TAX_CATEGORY_MAIN or _contains_any(desc, TAX_KEYWORDS):
        return "tax_payment"
    if cat_main in SALARY_CATEGORY_MAIN or _contains_any(desc, SALARY_KEYWORDS):
        return "salary"
    if cat_main in LOAN_CATEGORY_MAIN or _contains_any(desc, LOAN_KEYWORDS):
        return "loan_or_finance"
    if cat_main in SELF_TRANSFER_CATEGORY_MAIN or _contains_any(desc, SELF_TRANSFER_KEYWORDS):
        return "self_transfer"
    if cat_main in BANK_FEE_CATEGORY_MAIN or _contains_any(desc, BANK_FEE_KEYWORDS):
        return "bank_fee"
    if cat_main in OTHER_EXCLUDED_CATEGORY_MAIN or _contains_any(desc, OTHER_EXCLUDED_KEYWORDS):
        return "other_excluded"
    return "expense_candidate"


# --------------------------------------------------------------------- #
# has_document
# --------------------------------------------------------------------- #
def _vendor_name(bill) -> Optional[str]:
    try:
        return bill.vendor.name if bill.vendor else None
    except Exception:
        return None


def _load_docs(db, org_id: int) -> tuple[list, list]:
    """טעינה חד-פעמית של Bill/Expense של הארגון — מונעת שאילתת full-table
    פר-תנועה בדוח חודשי (מאות תנועות × מאות מסמכים)."""
    from ..models import Bill, Expense

    bills = db.query(Bill).filter(Bill.organization_id == org_id).all()
    expenses = db.query(Expense).filter(Expense.organization_id == org_id).all()
    return bills, expenses


def _find_document_match(db, org_id: int, txn,
                         docs: Optional[tuple[list, list]] = None) -> Optional[dict[str, Any]]:
    """מוצא מסמך תואם לתנועה — ע"פ matched_entity_type/id קודם, ואז לפי
    סכום (±₪1) + טווח תאריכים (±7 ימים). מחזיר {"hint": ...} או None.
    `docs`: תוצאת _load_docs לשימוש חוזר בין תנועות (אופציונלי)."""
    matched_type = getattr(txn, "matched_entity_type", None)
    if matched_type in ("bill", "expense"):
        from ..models import Bill, Expense

        matched_id = getattr(txn, "matched_entity_id", None)
        if matched_type == "bill" and matched_id:
            b = db.get(Bill, matched_id)
            if b:
                return {"hint": b.bill_number or _vendor_name(b)}
        if matched_type == "expense" and matched_id:
            e = db.get(Expense, matched_id)
            if e:
                return {"hint": e.supplier_name}
        # matched_entity_type קיים אך לא הצלחנו לפענח את המסמך עצמו —
        # עדיין נחשב "יש מסמך" (זה מה שההתאמה הקיימת קבעה).
        return {"hint": None}

    txn_date = getattr(txn, "transaction_date", None)
    amount = abs(float(getattr(txn, "amount", 0) or 0))
    if not txn_date or amount <= 0:
        return None

    bills, expenses = docs if docs is not None else _load_docs(db, org_id)

    window_start = txn_date - timedelta(days=DATE_WINDOW_DAYS)
    window_end = txn_date + timedelta(days=DATE_WINDOW_DAYS)

    for b in bills:
        b_date = b.issue_date or b.due_date
        if b_date is None or not (window_start <= b_date <= window_end):
            continue
        if abs(float(b.total or 0) - amount) <= AMOUNT_TOLERANCE:
            return {"hint": b.bill_number or _vendor_name(b)}

    for e in expenses:
        e_date = e.expense_date
        if e_date is None or not (window_start <= e_date <= window_end):
            continue
        e_amount = float(e.total or 0) or float(e.amount or 0)
        if abs(e_amount - amount) <= AMOUNT_TOLERANCE:
            return {"hint": e.supplier_name}

    return None


def has_document(db, org_id: int, txn) -> bool:
    """יש מסמך אם matched_entity_type in ('bill','expense'), או קיים
    Bill/Expense של אותו ארגון בסכום זהה (±₪1) בטווח ±7 ימים מהתנועה."""
    return _find_document_match(db, org_id, txn) is not None


def _find_invoice_match(db, org_id: int, txn) -> Optional[dict[str, Any]]:
    """כמו _find_document_match, אך לצד ההכנסות — Invoice מול תנועת זיכוי."""
    if getattr(txn, "matched_entity_type", None) == "invoice":
        return {"hint": None}

    txn_date = getattr(txn, "transaction_date", None)
    amount = float(getattr(txn, "amount", 0) or 0)
    if not txn_date or amount <= 0:
        return None

    from ..models import Invoice

    window_start = txn_date - timedelta(days=DATE_WINDOW_DAYS)
    window_end = txn_date + timedelta(days=DATE_WINDOW_DAYS)
    for inv in db.query(Invoice).filter(Invoice.organization_id == org_id).all():
        i_date = inv.issue_date or inv.due_date
        if i_date is None or not (window_start <= i_date <= window_end):
            continue
        if abs(float(inv.total or 0) - amount) <= AMOUNT_TOLERANCE:
            return {"hint": inv.invoice_number}
    return None


# --------------------------------------------------------------------- #
# gap_report
# --------------------------------------------------------------------- #
def gap_report(db, org_id: int, year: int, month: int) -> dict[str, Any]:
    """דוח פער חודשי: לכל תנועת expense_candidate — תאריך, תיאור, סכום,
    קטגוריה, has_document, matched_hint. סיכומים: total_bank_outflow,
    excluded_by_class, documented_total, undocumented_total,
    undocumented_count, potential_vat. כולל גם צד הכנסות בסיסי (inflows
    ללא Invoice מותאמת)."""
    from ..models import BankTransaction

    days_in_month = calendar.monthrange(year, month)[1]
    start = date(year, month, 1)
    end = date(year, month, days_in_month)

    rows = (
        db.query(BankTransaction)
        .filter(
            BankTransaction.organization_id == org_id,
            BankTransaction.transaction_date >= start,
            BankTransaction.transaction_date <= end,
        )
        .order_by(BankTransaction.transaction_date)
        .all()
    )

    transactions: list[dict[str, Any]] = []
    total_bank_outflow = 0.0
    excluded_by_class: dict[str, dict[str, Any]] = {}
    documented_total = 0.0
    undocumented_total = 0.0
    undocumented_count = 0
    inflow_undocumented_total = 0.0
    inflow_undocumented_count = 0

    docs = _load_docs(db, org_id)
    for t in rows:
        amount = float(t.amount or 0)
        if amount < 0:
            total_bank_outflow += abs(amount)
            cls = classify_transaction(t)
            if cls != "expense_candidate":
                bucket = excluded_by_class.setdefault(cls, {"count": 0, "total": 0.0})
                bucket["count"] += 1
                bucket["total"] += abs(amount)
                continue

            match = _find_document_match(db, org_id, t, docs=docs)
            has_doc = match is not None
            transactions.append({
                "date": t.transaction_date.isoformat() if t.transaction_date else None,
                "description": t.description,
                "amount": round(abs(amount), 2),
                "category": {"main": _category_field(t, "main"), "sub": _category_field(t, "sub")},
                "has_document": has_doc,
                "matched_hint": match.get("hint") if match else None,
            })
            if has_doc:
                documented_total += abs(amount)
            else:
                undocumented_total += abs(amount)
                undocumented_count += 1
        elif amount > 0:
            if _find_invoice_match(db, org_id, t) is None:
                inflow_undocumented_total += amount
                inflow_undocumented_count += 1

    for bucket in excluded_by_class.values():
        bucket["total"] = round(bucket["total"], 2)

    potential_vat = round(undocumented_total * 0.18 / 1.18, 2)

    return {
        "year": year,
        "month": month,
        "transactions": transactions,
        "totals": {
            "total_bank_outflow": round(total_bank_outflow, 2),
            "excluded_by_class": excluded_by_class,
            "documented_total": round(documented_total, 2),
            "undocumented_total": round(undocumented_total, 2),
            "undocumented_count": undocumented_count,
            "potential_vat": potential_vat,
        },
        "inflows": {
            "undocumented_total": round(inflow_undocumented_total, 2),
            "undocumented_count": inflow_undocumented_count,
        },
    }


# --------------------------------------------------------------------- #
# suppliers_missing_invoices — אגרגציה ברמת ספק (לא תנועה בודדת) של הוצאות
# בבנק/אשראי ללא מסמך תואם, לטווח תאריכים חופשי. בונה על אותו מנוע סיווג
# ומציאת-מסמך כמו gap_report, אבל מקבץ לפי ספק כדי לענות על "מאילו ספקים
# חסרה לי חשבונית".
# --------------------------------------------------------------------- #
def suppliers_missing_invoices(db, org_id: int, date_from: date, date_to: date) -> dict[str, Any]:
    """עוברת על כל BankTransaction יוצא (amount<0) של הארגון בטווח
    [date_from, date_to], מסננת ל-expense_candidate ללא מסמך תואם, ומקבצת
    לפי ספק: merchantName אם קיים, אחרת description מנורמל — אלא אם
    התיאור הוא נוסח-העברה גנרי (ראה GENERIC_TRANSFER_KEYWORDS), ואז
    התנועה הולכת ל-unidentified_transfers (אין בו שם ספק לזהות)."""
    from ..models import BankTransaction

    rows = (
        db.query(BankTransaction)
        .filter(
            BankTransaction.organization_id == org_id,
            BankTransaction.transaction_date >= date_from,
            BankTransaction.transaction_date <= date_to,
            BankTransaction.amount < 0,
        )
        .order_by(BankTransaction.transaction_date)
        .all()
    )

    docs = _load_docs(db, org_id)
    groups: dict[str, dict[str, Any]] = {}
    unidentified_total = 0.0
    unidentified_txns: list[dict[str, Any]] = []

    for t in rows:
        if classify_transaction(t) != "expense_candidate":
            continue
        if _find_document_match(db, org_id, t, docs=docs) is not None:
            continue

        amount = round(abs(float(t.amount or 0)), 2)
        txn_date = t.transaction_date
        merchant = _merchant_name(t)
        desc = t.description

        if merchant:
            name = merchant
        elif _is_generic_transfer(desc):
            unidentified_total += amount
            unidentified_txns.append({
                "date": txn_date.isoformat() if txn_date else None,
                "description": desc,
                "amount": amount,
                # "מטרת ההעברה" — לרוב הרמז היחיד לזהות הנמען.
                "purpose": _transfer_purpose(t),
            })
            continue
        else:
            name = _normalize_description(desc) or "ספק לא ידוע"

        g = groups.setdefault(name, {
            "name": name, "transactions_count": 0, "total": 0.0,
            "first_date": txn_date, "last_date": txn_date, "sample_descriptions": [],
        })
        g["transactions_count"] += 1
        g["total"] += amount
        if txn_date is not None:
            if g["first_date"] is None or txn_date < g["first_date"]:
                g["first_date"] = txn_date
            if g["last_date"] is None or txn_date > g["last_date"]:
                g["last_date"] = txn_date
        if desc and len(g["sample_descriptions"]) < 3 and desc not in g["sample_descriptions"]:
            g["sample_descriptions"].append(desc)

    suppliers = []
    for g in groups.values():
        total = round(g["total"], 2)
        suppliers.append({
            "name": g["name"],
            "transactions_count": g["transactions_count"],
            "total": total,
            "estimated_vat": round(total * 0.18 / 1.18, 2),
            "first_date": g["first_date"].isoformat() if g["first_date"] else None,
            "last_date": g["last_date"].isoformat() if g["last_date"] else None,
            "sample_descriptions": g["sample_descriptions"],
        })
    suppliers.sort(key=lambda s: s["total"], reverse=True)

    total_all = round(sum(s["total"] for s in suppliers), 2)

    return {
        "suppliers": suppliers,
        "unidentified_transfers": {
            "count": len(unidentified_txns),
            "total": round(unidentified_total, 2),
            "transactions": unidentified_txns,
        },
        "totals": {
            "suppliers_count": len(suppliers),
            "total": total_all,
            "estimated_vat": round(total_all * 0.18 / 1.18, 2),
        },
    }


# --------------------------------------------------------------------- #
# scan_and_alert
# --------------------------------------------------------------------- #
def scan_and_alert(db, org_id: int, lookback_days: int = 14) -> dict[str, int]:
    """סורק תנועות expense_candidate ללא מסמך מתוך lookback_days האחרונים,
    ויוצר CfoInsight (insight_type="missing_document") פר תנועה — עם dedup
    לפי fingerprint ייחודי לתנועה (לא יוצר פעמיים לאותה תנועה)."""
    from ..models import BankTransaction, CfoInsight

    since = date.today() - timedelta(days=lookback_days)
    rows = (
        db.query(BankTransaction)
        .filter(
            BankTransaction.organization_id == org_id,
            BankTransaction.transaction_date >= since,
            BankTransaction.amount < 0,
        )
        .all()
    )

    created = skipped_existing = scanned = 0
    docs = _load_docs(db, org_id)
    for t in rows:
        scanned += 1
        if classify_transaction(t) != "expense_candidate":
            continue
        if _find_document_match(db, org_id, t, docs=docs) is not None:
            continue

        fingerprint = f"missing_document:banktxn:{t.id}"
        existing = db.query(CfoInsight).filter(
            CfoInsight.organization_id == org_id,
            CfoInsight.fingerprint == fingerprint,
        ).first()
        if existing:
            skipped_existing += 1
            continue

        amount = abs(float(t.amount or 0))
        purpose = _transfer_purpose(t)
        supplier = _merchant_name(t) or (t.description or "ספק לא ידוע")
        if purpose:
            supplier = f"{supplier} ({purpose})"
        date_str = t.transaction_date.isoformat() if t.transaction_date else ""
        title = f"הוצאה בבנק ללא חשבונית — {_money(amount)} {supplier} ({date_str})"
        message = (
            f"תנועת בנק מ-{date_str} על סך {_money(amount)} \"{t.description}\" "
            f"אינה מקושרת למסמך הוצאה/חשבון ספק ב-SUMIT."
        )
        db.add(CfoInsight(
            organization_id=org_id,
            fingerprint=fingerprint,
            insight_type="missing_document",
            severity="medium",
            title=title,
            message=message,
            evidence={"bank_txn_id": t.id, "amount": amount, "date": date_str, "description": t.description},
            recommended_action="תייק הוצאה מתאימה ב-SUMIT או התאם לתנועה קיימת.",
            status="active",
        ))
        created += 1

    db.commit()
    return {"created": created, "skipped_existing": skipped_existing, "scanned": scanned}


# --------------------------------------------------------------------- #
# בוט — קריאת ההתרעות הפתוחות (למחשוב ai_chat_tools.get_bank_expense_gap_alerts)
# --------------------------------------------------------------------- #
def list_open_alerts(db, org_id: int, limit: int = 20) -> dict[str, Any]:
    """התרעות missing_document פתוחות (status='active') שנוצרו ע"י
    scan_and_alert — לא מריץ סיווג מחדש, רק קורא מה שכבר נשמר."""
    from ..models import CfoInsight

    rows = (
        db.query(CfoInsight)
        .filter(
            CfoInsight.organization_id == org_id,
            CfoInsight.insight_type == "missing_document",
            CfoInsight.status == "active",
        )
        .order_by(CfoInsight.created_at.desc())
        .limit(limit)
        .all()
    )
    alerts = [
        {
            "id": r.id,
            "title": r.title,
            "message": r.message,
            "evidence": r.evidence,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]
    total = sum(float((r.evidence or {}).get("amount", 0) or 0) for r in rows)
    return {"count": len(alerts), "total_amount": round(total, 2), "alerts": alerts}
