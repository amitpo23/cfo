"""
Financial synthesis — combine the two connections (SUMIT books + Open Finance bank)
into one cross-checked picture and an actionable "required reconciliations" worklist.

This is the value created by having *both* connections:

  * SUMIT knows what was *recorded* (invoices, bills, expenses, payments, VAT).
  * Open Finance knows what *actually moved* in the bank.

Synthesis surfaces the gaps between them:
  - bank money out with no document        -> file an expense (missing input VAT)
  - bank money in with no invoice           -> unrecorded income
  - invoice recorded but no money in        -> uncollected receivable
  - bill/expense recorded but no money out  -> unpaid payable
  - SUMIT payment not linked to a document  -> link it (payment_to_document)
  - VAT: output (invoices) vs input (bills/expenses) -> net VAT position

The matching primitives are pure functions over lightweight records (testable
without a DB). `*_organization` wrappers load ORM rows, run the logic, and persist.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Optional

from .bank_reconciliation import BankTxnLite, DocLite, reconcile, _score


# ---------------------------------------------------------------------- #
# Payment <-> document linkage
# ---------------------------------------------------------------------- #
@dataclass
class PaymentLite:
    id: Any
    amount: float
    date: Optional[date]
    contact_id: Optional[Any] = None
    name: str = ""


def link_payments(
    payments: list[PaymentLite],
    invoices: list[DocLite],
    bills: list[DocLite],
    *,
    amount_tol: float = 0.02,
    date_window: int = 14,
    min_score: float = 0.5,
) -> dict[str, Any]:
    """Link SUMIT payments (which carry only a customer/contact id) to a specific
    invoice or bill by amount + date proximity (+ contact when present)."""
    used: set[tuple[str, Any]] = set()
    links: list[dict] = []
    unlinked: list[Any] = []

    for pay in sorted(payments, key=lambda p: abs(p.amount), reverse=True):
        pool = invoices + bills
        best: Optional[tuple[float, DocLite]] = None
        for doc in pool:
            if (doc.entity_type, doc.id) in used:
                continue
            # Represent the payment as a bank-txn-like record for scoring reuse.
            txn = BankTxnLite(id=pay.id, amount=pay.amount, date=pay.date or date.min,
                              description=pay.name)
            score = _score(txn, doc, amount_tol=amount_tol, date_window=date_window)
            if score is None:
                continue
            if best is None or score > best[0]:
                best = (score, doc)
        if best and best[0] >= min_score:
            score, doc = best
            used.add((doc.entity_type, doc.id))
            links.append({"payment_id": pay.id, "entity_type": doc.entity_type,
                          "entity_id": doc.id, "score": round(score, 3)})
        else:
            unlinked.append(pay.id)

    return {"links": links, "unlinked": unlinked, "linked_count": len(links)}


# ---------------------------------------------------------------------- #
# Required-reconciliations worklist + VAT position
# ---------------------------------------------------------------------- #
SEV_INFO, SEV_MED, SEV_HIGH = "info", "medium", "high"


def build_synthesis(
    bank_txns: list[BankTxnLite],
    invoices: list[DocLite],
    bills: list[DocLite],
    expenses: list[DocLite],
    *,
    unpaid_invoice_ids: Optional[set] = None,
    unpaid_bill_ids: Optional[set] = None,
    output_vat: float = 0.0,
    input_vat: float = 0.0,
    vat_period: Optional[str] = None,
) -> dict[str, Any]:
    """Cross-reference bank movements against documents and emit a worklist."""
    unpaid_invoice_ids = unpaid_invoice_ids or set()
    unpaid_bill_ids = unpaid_bill_ids or set()

    recon = reconcile(bank_txns, invoices, bills, expenses)
    matched_txn_ids = {m["bank_txn_id"] for m in recon["matches"]}
    matched_doc_keys = {(m["entity_type"], m["entity_id"]) for m in recon["matches"]}

    actions: list[dict] = []

    # 1) Bank movements with no document.
    txn_by_id = {t.id: t for t in bank_txns}
    for txn_id in recon["unmatched_txns"]:
        t = txn_by_id.get(txn_id)
        if not t:
            continue
        if t.amount < 0:
            actions.append(_action(
                "file_expense", SEV_HIGH,
                f"תנועת בנק יוצאת ללא מסמך — {_money(abs(t.amount))}",
                f"חיוב של {_money(abs(t.amount))} ({t.date}) \"{t.description}\" אינו מקושר "
                f"לחשבונית הוצאה ב-SUMIT. תייק כדי לקבל את ניכוי מס התשומות.",
                amount=abs(t.amount), refs={"bank_txn_id": t.id},
            ))
        else:
            actions.append(_action(
                "record_income", SEV_MED,
                f"תקבול ללא חשבונית — {_money(t.amount)}",
                f"כניסת {_money(t.amount)} ({t.date}) \"{t.description}\" ללא חשבונית מס מתאימה "
                f"ב-SUMIT. הפק/שייך חשבונית כדי לדווח מע\"מ עסקאות.",
                amount=t.amount, refs={"bank_txn_id": t.id},
            ))

    # 2) Documents recorded but with no matching bank movement.
    for inv in invoices:
        if ("invoice", inv.id) in matched_doc_keys:
            continue
        if inv.id in unpaid_invoice_ids:
            actions.append(_action(
                "collect_receivable", SEV_MED,
                f"חשבונית לא נגבתה — {_money(inv.amount)}",
                f"חשבונית על {_money(inv.amount)} ({inv.name}) רשומה ב-SUMIT אך לא נמצאה "
                f"כניסת כסף תואמת בבנק. ייתכן חוב פתוח לגבייה.",
                amount=inv.amount, refs={"invoice_id": inv.id},
            ))
    for bill in bills:
        if ("bill", bill.id) in matched_doc_keys:
            continue
        if bill.id in unpaid_bill_ids:
            actions.append(_action(
                "pay_payable", SEV_INFO,
                f"התחייבות לא שולמה — {_money(bill.amount)}",
                f"חשבון ספק על {_money(bill.amount)} ({bill.name}) רשום ב-SUMIT אך אין חיוב "
                f"תואם בבנק. ודא שהתשלום בוצע/מתוכנן.",
                amount=bill.amount, refs={"bill_id": bill.id},
            ))

    # 3) VAT position (output vs input).
    net_vat = round(output_vat - input_vat, 2)
    vat_summary = {
        "period": vat_period,
        "output_vat": round(output_vat, 2),
        "input_vat": round(input_vat, 2),
        "net_vat": net_vat,
        "direction": "לתשלום" if net_vat >= 0 else "להחזר",
    }

    return {
        "reconciliation": {
            "matched": recon["matched_count"],
            "txn_count": recon["txn_count"],
            "unmatched_txns": len(recon["unmatched_txns"]),
        },
        "required_actions": actions,
        "action_count": len(actions),
        "vat_summary": vat_summary,
    }


# ---------------------------------------------------------------------- #
# DB wrappers
# ---------------------------------------------------------------------- #
def link_payments_organization(db, organization_id: int, *, persist: bool = True) -> dict[str, Any]:
    from ..models import Payment, Invoice, Bill

    pay_rows = db.query(Payment).filter(Payment.organization_id == organization_id).all()
    payments = [
        PaymentLite(id=r.id, amount=float(r.amount or 0), date=r.payment_date,
                    contact_id=r.contact_id, name=_contact_name(r))
        for r in pay_rows
    ]
    invoices = [
        DocLite(id=r.id, entity_type="invoice", amount=float(r.total or 0),
                date=r.issue_date or r.due_date, name=_rel_name(r, "contact"))
        for r in db.query(Invoice).filter(Invoice.organization_id == organization_id).all()
    ]
    bills = [
        DocLite(id=r.id, entity_type="bill", amount=float(r.total or 0),
                date=getattr(r, "issue_date", None) or getattr(r, "due_date", None),
                name=_rel_name(r, "vendor"))
        for r in db.query(Bill).filter(Bill.organization_id == organization_id).all()
    ]

    result = link_payments(payments, invoices, bills)

    if persist and result["links"]:
        pay_by_id = {r.id: r for r in pay_rows}
        for link in result["links"]:
            row = pay_by_id.get(link["payment_id"])
            if row is None:
                continue
            if link["entity_type"] == "invoice":
                row.invoice_id = link["entity_id"]
            elif link["entity_type"] == "bill":
                row.bill_id = link["entity_id"]
        db.commit()
    return result


def _in_vat_period(d, start, end) -> bool:
    if d is None:
        return start is None and end is None  # undated rows only count all-time
    if start is not None and d < start:
        return False
    if end is not None and d > end:
        return False
    return True


# סוגי מסמכים בצד ההכנסות שאינם מסמכי מע"מ — מוחרגים מצד העסקאות של הדוח.
# '5' — שורות legacy שסונכרנו לפני הנרמול עם קוד ה-Type הגולמי של SUMIT: המקרה החי
# external_id=974527677 (total=-23600) תויג באודיט 2026-07-05 כקבלה; לפי ה-swagger
# (Accounting_Typed_DocumentType) קוד 5 הוא דווקא CreditInvoice — הסתירה מתועדת,
# ובשני המקרים שורת legacy כזו אינה ניתנת לאימוץ כמסמך מע"מ בלי סנכרון מחדש
# (זיכוי שמסונכרן כהלכה נושא document_type='credit_note' ולכן לא מוחרג).
# '2'/'receipt' — קבלה לפי ה-swagger/שם: אישור תשלום, לא מסמך מע"מ.
_NON_VAT_SALES_DOC_TYPES = {"5", "2", "receipt"}

# זיכוי מנורמל (מסונכרן ע"י fetch_invoices החדש או הוזן ידנית) — נספר בעסקאות
# בסימן שלילי: מקטין את מע"מ העסקאות (output_vat) ואת סך המכירות.
_CREDIT_SALES_DOC_TYPES = {"credit_note", "credit_invoice"}


def select_vat_documents(
    db, organization_id: int, *, start=None, end=None, basis: str = "document"
) -> dict[str, list[dict[str, Any]]]:
    """Select+dedup the documents behind the canonical VAT position.

    Single source of truth for *which* documents count as sales/inputs for a period —
    shared by `compute_vat_position`, `daily_reports_service.vat_report_period`, and
    `pcn874.build_pcn874` so all three engines always reconcile.

    `basis`:
      - "document" (default, existing behavior): both sides use the document date
        (issue_date/due_date for invoices/bills, expense_date for expenses).
      - "captured": regulatory rule — עסקאות (מכירות) מדווחות תמיד לפי תאריך המסמך;
        רק תשומות (bills/expenses) מותר לקזז לפי מועד הקליטה (created_at). So only the
        input side switches to `created_at`; sales always use the document date.

    Dedup: a document synced twice into SUMIT (as both Bill and Expense, same
    external_id) counts once — the Bill is canonical, the twin Expense is skipped.
    """
    from ..models import Invoice, Bill, Expense
    from .vat_utils import invoice_counts, bill_counts, expense_counts

    def _f(v) -> float:
        try:
            return float(v or 0)
        except (TypeError, ValueError):
            return 0.0

    def _captured(r):
        ca = getattr(r, "created_at", None)
        return ca.date() if ca else None

    inv_rows = db.query(Invoice).filter(Invoice.organization_id == organization_id).all()
    bill_rows = db.query(Bill).filter(Bill.organization_id == organization_id).all()
    exp_rows = db.query(Expense).filter(Expense.organization_id == organization_id).all()

    sales: list[dict[str, Any]] = []
    for r in inv_rows:
        if not invoice_counts(r.status):
            continue
        raw_doc_type = str(((getattr(r, "raw_data", None) or {}).get("document_type")) or "").lower()
        if raw_doc_type in _NON_VAT_SALES_DOC_TYPES:
            continue  # קבלה / שורת legacy קוד-גולמי — לא מסמך מע"מ בצד העסקאות
        is_credit = raw_doc_type in _CREDIT_SALES_DOC_TYPES
        doc_date = getattr(r, "issue_date", None) or getattr(r, "due_date", None)
        if not _in_vat_period(doc_date, start, end):  # always document-basis for sales
            continue
        cname = getattr(getattr(r, "contact", None), "name", None)
        # זיכוי תורם בשלילי (גם אם נשמר בחיובי ביבוא ישן/ידני — הסיווג קובע);
        # כל השאר נשארים abs() כמו קודם.
        sign = -1.0 if is_credit else 1.0
        sales.append({
            "type": "invoice", "id": r.id, "number": r.invoice_number,
            "doc_date": doc_date, "captured_date": _captured(r),
            "counterparty": cname or "", "subtotal": sign * abs(_f(r.subtotal)),
            "vat": sign * abs(_f(r.tax)), "allocation_number": getattr(r, "allocation_number", None),
            "external_id": r.external_id,
        })

    # מסמך SUMIT מסונכרן פעמיים — כ-Bill (ספר AP) וגם כ-Expense (טבלת עבודה) — עם
    # אותו external_id. ה-Bill קנוני לתשומות; Expense עם תאום-Bill מדולג, אחרת כפל
    # תשומות (נמצא באודיט תאימות מול SUMIT: ניפוח 47.5%).
    bill_ext_ids = {str(r.external_id) for r in bill_rows if r.external_id}

    inputs: list[dict[str, Any]] = []
    for r in bill_rows:
        if not bill_counts(r.status):
            continue
        doc_date = getattr(r, "issue_date", None) or getattr(r, "due_date", None)
        captured_date = _captured(r)
        select_date = captured_date if basis == "captured" else doc_date
        if not _in_vat_period(select_date, start, end):
            continue
        subtotal, tax = _f(r.subtotal), _f(r.tax)
        if subtotal == 0 and tax == 0:
            # טיוטה ריקה (צילום קבלה שסונכרן/נשמר בלי סכום — טרם תויקה) —
            # ממצא אודיט אליהב 2026-07-13 (ממצא 5): שורות כאלה יוצאות ב-PCN874
            # כשורת L באפס — פסולה בקובץ רגולטורי, ואינה תורמת דבר לחישוב ממילא.
            # עדיין נספרת בנפרד ב-filing_verification._pending_drafts (שלמות קליטה).
            continue
        vname = getattr(getattr(r, "vendor", None), "name", None)
        inputs.append({
            "type": "bill", "id": r.id, "number": r.bill_number,
            "doc_date": doc_date, "captured_date": captured_date,
            # סימן חתום, לא abs(): אחרי נרמול הסימן (12/07) מסמך רגיל חיובי
            # וזיכוי ספק שלילי — abs() היה הופך זיכוי להגדלת תשומות (קיזוז
            # ביתר, הכיוון האסור בחוק). ה-abs ההיסטורי פיצה על סימן שלילי גורף
            # שכבר לא קיים.
            "counterparty": vname or "", "subtotal": subtotal,
            "vat": tax, "vat_id": _bill_vendor_tax_id(r), "external_id": r.external_id,
        })
    for r in exp_rows:
        if not expense_counts(getattr(r, "status", None)):
            continue
        if r.external_id and str(r.external_id) in bill_ext_ids:
            continue  # דה-דופ: כבר נספר כ-Bill
        doc_date = getattr(r, "expense_date", None)
        captured_date = _captured(r)
        select_date = captured_date if basis == "captured" else doc_date
        if not _in_vat_period(select_date, start, end):
            continue
        subtotal, tax = _f(r.amount), _f(r.vat_amount)
        if subtotal == 0 and tax == 0:
            continue  # טיוטה ריקה — ראו הערה מקבילה בלולאת ה-Bill למעלה.
        inputs.append({
            "type": "expense", "id": r.id, "number": getattr(r, "invoice_number", None),
            "doc_date": doc_date, "captured_date": captured_date,
            # כנ"ל — זיכוי ספק שנקלט כהוצאה שלילית (למשל org5) חייב להקטין תשומות.
            "counterparty": r.supplier_name or "", "subtotal": subtotal,
            "vat": tax, "vat_id": getattr(r, "supplier_tax_id", None),
            "external_id": r.external_id,
        })

    return {"sales": sales, "inputs": inputs}


_BILL_TAX_ID_RAW_KEYS = (
    # מפתחות משוערים בלבד להגנה עתידית: DocumentResponse הנוכחי של SUMIT
    # (src/cfo/integrations/sumit_models.py) אינו חושף שום שדה ח.פ-לקוח/ספק על
    # מסמך הוצאה, כך שבפועל נתיב זה יחזיר תמיד None עד שהמקור יתעשר — אין כאן
    # נתון מומצא, רק גיבוי בטוח למקרה שמפתח כזה יתווסף מתישהו.
    "customer_tax_id", "vendor_tax_id", "CustomerTaxId", "VendorTaxId",
    "VatNumber", "vat_number", "CompanyNumber", "company_number",
)


def _bill_vendor_tax_id(bill_row) -> Optional[str]:
    """ח.פ ספק לשורת L של PCN874: קודם Contact.tax_id של ה-vendor המקושר
    (המקור האמין שקיים כבר במודל), אחרת ניסיון גיבוי מ-raw_data (ראו
    _BILL_TAX_ID_RAW_KEYS), אחרת None — לא ממציאים, pcn874._vat_id ישאיר
    9 אפסים כברירת המחדל הקיימת."""
    vendor = getattr(bill_row, "vendor", None)
    tax_id = getattr(vendor, "tax_id", None) if vendor is not None else None
    if tax_id:
        return tax_id
    raw = bill_row.raw_data if isinstance(getattr(bill_row, "raw_data", None), dict) else {}
    for key in _BILL_TAX_ID_RAW_KEYS:
        value = raw.get(key)
        if value:
            return str(value)
    return None


def period_bounds(year: int, month: int, months: int = 1) -> dict[str, Any]:
    """Period window for VAT reporting: monthly (months=1) or bimonthly (months=2).

    Bimonthly periods follow the Israeli VAT pairing (Jan-Feb, Mar-Apr, ..., Nov-Dec).
    `month` is normally the anchor (first, odd) month of the pair; if an even month is
    passed with months=2 it's normalized down to the preceding odd anchor (so passing
    either month of a pair gives the same period). `due_date` = the 15th of the month
    after the period ends (standard PCN874/VAT filing deadline).
    """
    from calendar import monthrange

    if months not in (1, 2):
        raise ValueError("months must be 1 or 2")
    if not (1 <= month <= 12):
        raise ValueError("month must be 1-12")

    if months == 1:
        anchor = month
        end_month = month
    else:
        anchor = month if month % 2 == 1 else month - 1
        if anchor < 1:
            raise ValueError("invalid month for a bimonthly period")
        end_month = anchor + 1

    start = date(year, anchor, 1)
    end = date(year, end_month, monthrange(year, end_month)[1])

    due_month, due_year = end_month + 1, year
    if due_month > 12:
        due_month, due_year = 1, year + 1
    due_date = date(due_year, due_month, 15)

    return {
        "start": start, "end": end, "anchor_month": anchor, "end_month": end_month,
        "months": [anchor] if months == 1 else [anchor, end_month],
        "due_date": due_date,
    }


def period_label(year: int, month: int, months: int = 1) -> str:
    """מחרוזת התקופה הקנונית (למשל "2026-05" או "2026-05_2026-06") — מקור אמת
    יחיד שמשמש גם את דוח המע"מ (daily_reports_service.vat_report_period) וגם
    את ההצלבה המוקלטת (FilingCrosscheck), כדי שלעולם לא ייווצר פער בין
    הפורמטים שיחביא רשומת הצלבה מ-filing_verification.verify_filing."""
    pb = period_bounds(year, month, months)
    if months == 1:
        return f"{year}-{pb['anchor_month']:02d}"
    return f"{year}-{pb['anchor_month']:02d}_{year}-{pb['end_month']:02d}"


def compute_vat_position(
    db, organization_id: int, *, start=None, end=None, basis: str = "document"
) -> dict[str, Any]:
    """Canonical VAT position from the books (document-actual tax fields).

    Single source of truth for output/input VAT. Reads the real `tax`/`vat_amount`
    fields on Invoice/Bill/Expense (more accurate than estimating amount×rate on the
    generic Transaction table). Optional [start, end] bounds make it period-scoped;
    omit both for the all-time running position used by the synthesis dashboard.
    `basis="captured"` switches the input (tashumot) side to the receipt/sync date
    (created_at) — see `select_vat_documents`.
    """
    sel = select_vat_documents(db, organization_id, start=start, end=end, basis=basis)
    output_vat = round(sum(r["vat"] for r in sel["sales"]), 2)
    input_vat = round(sum(r["vat"] for r in sel["inputs"]), 2)
    net = round(output_vat - input_vat, 2)
    return {
        "output_vat": output_vat,
        "input_vat": input_vat,
        "net_vat": net,
        "direction": "לתשלום" if net >= 0 else "להחזר",
    }


def synthesize_organization(db, organization_id: int) -> dict[str, Any]:
    from ..models import BankTransaction, Invoice, Bill, Expense, InvoiceStatus, BillStatus

    bank_rows = db.query(BankTransaction).filter(
        BankTransaction.organization_id == organization_id).all()
    bank_txns = [
        BankTxnLite(id=r.id, amount=float(r.amount), date=r.transaction_date,
                    description=r.description or "")
        for r in bank_rows if r.transaction_date is not None
    ]

    invoice_rows = db.query(Invoice).filter(Invoice.organization_id == organization_id).all()
    bill_rows = db.query(Bill).filter(Bill.organization_id == organization_id).all()
    expense_rows = db.query(Expense).filter(Expense.organization_id == organization_id).all()

    invoices = [DocLite(id=r.id, entity_type="invoice", amount=float(r.total or 0),
                        date=r.issue_date or r.due_date, name=_rel_name(r, "contact"))
                for r in invoice_rows]
    bills = [DocLite(id=r.id, entity_type="bill", amount=float(r.total or 0),
                     date=getattr(r, "issue_date", None) or getattr(r, "due_date", None),
                     name=_rel_name(r, "vendor")) for r in bill_rows]
    expenses = [DocLite(id=r.id, entity_type="expense",
                        amount=float(getattr(r, "amount", 0) or 0),
                        date=getattr(r, "expense_date", None),
                        name=getattr(r, "supplier_name", "") or "") for r in expense_rows]

    paid_invoice = getattr(InvoiceStatus, "PAID", None)
    paid_bill = getattr(BillStatus, "PAID", None)
    unpaid_invoice_ids = {r.id for r in invoice_rows if r.status != paid_invoice}
    unpaid_bill_ids = {r.id for r in bill_rows if r.status != paid_bill}

    # VAT position from the books — single canonical source (document-actual tax).
    vat = compute_vat_position(db, organization_id)
    output_vat = vat["output_vat"]
    input_vat = vat["input_vat"]

    return build_synthesis(
        bank_txns, invoices, bills, expenses,
        unpaid_invoice_ids=unpaid_invoice_ids, unpaid_bill_ids=unpaid_bill_ids,
        output_vat=output_vat, input_vat=input_vat,
    )


# ---------------------------------------------------------------------- #
# helpers
# ---------------------------------------------------------------------- #
def _action(action_type, severity, title, description, *, amount, refs) -> dict:
    return {"type": action_type, "severity": severity, "title": title,
            "description": description, "amount": round(amount, 2), "refs": refs}


def _money(amount: float) -> str:
    return f"₪{amount:,.0f}" if float(amount).is_integer() else f"₪{amount:,.2f}"


def _contact_name(payment) -> str:
    contact = getattr(payment, "contact", None)
    return getattr(contact, "name", "") if contact else ""


def _rel_name(row, attr) -> str:
    rel = getattr(row, attr, None)
    return getattr(rel, "name", "") if rel else ""
