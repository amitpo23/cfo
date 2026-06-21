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


def compute_vat_position(
    db, organization_id: int, *, start=None, end=None
) -> dict[str, Any]:
    """Canonical VAT position from the books (document-actual tax fields).

    Single source of truth for output/input VAT. Reads the real `tax`/`vat_amount`
    fields on Invoice/Bill/Expense (more accurate than estimating amount×rate on the
    generic Transaction table). Optional [start, end] bounds make it period-scoped;
    omit both for the all-time running position used by the synthesis dashboard.
    """
    from ..models import Invoice, Bill, Expense

    def _in_period(d) -> bool:
        if d is None:
            return start is None and end is None  # undated rows only count all-time
        if start is not None and d < start:
            return False
        if end is not None and d > end:
            return False
        return True

    inv = db.query(Invoice).filter(Invoice.organization_id == organization_id).all()
    bills = db.query(Bill).filter(Bill.organization_id == organization_id).all()
    exps = db.query(Expense).filter(Expense.organization_id == organization_id).all()

    output_vat = sum(float(r.tax or 0) for r in inv
                     if _in_period(getattr(r, "issue_date", None) or getattr(r, "due_date", None)))
    input_vat = (
        sum(float(r.tax or 0) for r in bills
            if _in_period(getattr(r, "issue_date", None) or getattr(r, "due_date", None)))
        + sum(float(getattr(r, "vat_amount", 0) or 0) for r in exps
              if _in_period(getattr(r, "expense_date", None)))
    )
    net = round(output_vat - input_vat, 2)
    return {
        "output_vat": round(output_vat, 2),
        "input_vat": round(input_vat, 2),
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
