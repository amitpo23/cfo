"""One money figure per organization.

The checking number is the Open Finance booked balance (``closingBooked``).
Available credit (``interimAvailable`` / ``forwardAvailable``) is a second
figure. A friendlier available amount is never substituted for the booked
balance, because that hides a credit-line overrun.

An unexplained gap between that booked balance and a transaction-implied
balance is a mismatch. It is not a funding need. Funding need comes only
from forecast obligations.

A missing date is ``חסר``, never a fabricated zero.
"""
from __future__ import annotations

from datetime import date, datetime


MISMATCH_LABEL = "פער לא מוסבר בין יתרת Open Finance לסכום התנועות. זה אינו צורך מימון."
# Product gate, not an invitation. Inviting Yuval or Eliav stays an owner action.
BANK_PACK_GATE_HE = (
    "הזמנת יובל ואליהב וחבילת הבנק נשארות חסומות עד שיתרת Open Finance והחריגה מהמסגרת מוצגות, "
    "שורות תקציב מדומות אינן נספרות, חובות הלקוחות נוקו, ותור התיוק ריק. זה שער מוצר, לא הזמנה."
)


def _iso(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value)
    return text[:10] if len(text) >= 10 else text


def _ddmm(value) -> str | None:
    text = _iso(value)
    if not text or len(text) < 10 or text[4] != "-":
        return None
    return f"{text[8:10]}.{text[5:7]}"


def org_partial_banner(db, organization_id: int) -> dict:
    """Latest stored bank movement and latest stored book document. No provider call."""
    from sqlalchemy import func

    from ...models import BankTransaction, Bill, Expense, Invoice

    bank = (
        db.query(func.max(BankTransaction.transaction_date))
        .filter(BankTransaction.organization_id == organization_id)
        .scalar()
    )
    books_dates = []
    for model, column in (
        (Invoice, Invoice.issue_date),
        (Bill, Bill.issue_date),
        (Expense, Expense.expense_date),
    ):
        books_dates.append(
            db.query(func.max(column)).filter(model.organization_id == organization_id).scalar()
        )
    known = [value for value in books_dates if value is not None]
    return partial_data_banner(bank, max(known) if known else None)


def partial_data_banner(bank_as_of, books_as_of) -> dict:
    """«נתונים חלקיים — בנק עד DD.MM, ספרים עד DD.MM»."""
    bank = _ddmm(bank_as_of)
    books = _ddmm(books_as_of)
    return {
        "text_he": f"נתונים חלקיים — בנק עד {bank or 'חסר'}, ספרים עד {books or 'חסר'}",
        "bank_as_of": _iso(bank_as_of),
        "books_as_of": _iso(books_as_of),
    }


def credit_overrun(balance, limit) -> dict:
    """Used above the credit line is an overrun. Unknown stays null, not zero."""
    if balance is None:
        return {
            "used": None,
            "overrun": None,
            "status": "unknown",
            "label_he": "חריגת מסגרת לא ידועה כי יתרת העו״ש חסרה. לא הוזן 0.",
        }
    used = round(max(0.0, -float(balance)), 2)
    if limit is None:
        return {
            "used": used,
            "overrun": None,
            "status": "unknown",
            "label_he": "חריגת מסגרת לא ידועה כי המסגרת חסרה. לא הוזן 0.",
        }
    overrun = round(max(0.0, used - float(limit)), 2)
    if overrun > 0:
        return {
            "used": used,
            "overrun": overrun,
            "status": "overrun",
            "label_he": f"חריגת מסגרת {overrun:.2f} ₪. היתרה הזמינה אינה מחליפה את היתרה הסגורה.",
        }
    return {
        "used": used,
        "overrun": 0.0,
        "status": "within",
        "label_he": "בתוך המסגרת",
    }


def unexplained_gap(of_balance, txn_implied, *, parts: list[dict] | None = None) -> dict | None:
    """OF booked balance versus a transaction-implied balance.

    The difference is a mismatch report. ``counts_as_funding_need`` is always
    false, including when the parts are 41,000 and the 62,898 cheque.
    """
    named = [part for part in (parts or []) if isinstance(part, dict) and part.get("amount") is not None]
    if of_balance is None and not named:
        return None
    if named:
        amount = round(sum(float(part["amount"]) for part in named), 2)
    elif txn_implied is None:
        return None
    else:
        amount = round(float(txn_implied) - float(of_balance), 2)
    if abs(amount) < 0.05:
        return None
    return {
        "amount": amount,
        "of_balance": None if of_balance is None else round(float(of_balance), 2),
        "txn_implied_balance": None if txn_implied is None else round(float(txn_implied), 2),
        "parts": named,
        "counts_as_funding_need": False,
        "label_he": MISMATCH_LABEL,
    }


PROFIT_BLOCKED_HE = "חסר/לסיווג — אי אפשר לטעון רווח כשיש יציאות בנק שלא תויקו."
AR_MISSING_HE = "חסר — אין חשבוניות שמורות. לא הוזן 0."
AR_INVALID_HE = "יתרת הלקוחות גבוהה מכל מה שחויב אי פעם. לא מוצג מספר מנופח."


def verified_amount(amount, *, measured: bool):
    """A zero that was not measured is not a money figure."""
    if not measured or amount is None:
        return None
    return amount


def ar_display(open_balance, overdue, ever_invoiced, *, saw_invoices: bool) -> dict:
    """Displayed AR is at most what was invoiced. An empty book is חסר, not 0."""
    if not saw_invoices:
        return {
            "amount": None,
            "overdue": None,
            "ever_invoiced": None,
            "status": "missing",
            "reason_he": AR_MISSING_HE,
        }
    opened = None if open_balance is None else round(float(open_balance), 2)
    invoiced = None if ever_invoiced is None else round(float(ever_invoiced), 2)
    late = None if overdue is None else round(float(overdue), 2)
    if opened is None or invoiced is None:
        return {
            "amount": None,
            "overdue": None,
            "ever_invoiced": invoiced,
            "status": "missing",
            "reason_he": "חסר — יתרת הלקוחות או סכום החיוב אינם ידועים. לא הוזן 0.",
        }
    if opened > invoiced + 0.01:
        return {
            "amount": None,
            "overdue": None,
            "ever_invoiced": invoiced,
            "open_balance": opened,
            "status": "invalid",
            "reason_he": AR_INVALID_HE,
        }
    return {
        "amount": opened,
        "overdue": late,
        "ever_invoiced": invoiced,
        "status": "ok",
        "reason_he": None,
    }


def operating_income_hits(invoices, filed_pairs) -> list[float]:
    """Books invoice once. A bank row counts only as operating revenue.

    A discounted-cheque advance and an intercompany collection of another
    entity's invoice are not extra income. The same cheque is not invoice
    plus bank plus discount.
    """
    from .filing import REVENUE_CATS

    hits = []
    for invoice in invoices or []:
        total = float(invoice.get("total") or 0)
        if total > 0:
            hits.append(round(total, 2))
    for txn, filed in filed_pairs or []:
        amount = getattr(txn, "amount", None)
        category = getattr(filed, "category", None)
        if amount is not None and amount > 0 and category in REVENUE_CATS:
            hits.append(round(float(amount), 2))
    return hits


def profit_claim(unclassified: dict | None) -> dict:
    """Unclassified outflows block a profit claim. The amount is not replaced with 0."""
    count = 0 if not unclassified else int(unclassified.get("count") or 0)
    if count <= 0:
        return {"allowed": True, "reason_he": None, "unclassified_amount": None}
    return {
        "allowed": False,
        "reason_he": PROFIT_BLOCKED_HE,
        "unclassified_amount": unclassified.get("amount"),
    }


def withhold_profit(figure: dict | None, reason: str) -> dict | None:
    if not isinstance(figure, dict):
        return figure
    copied = dict(figure)
    copied["amount"] = None
    copied["missing_label"] = reason
    return copied


def reject_gap_as_funding(need_amount, gap_amount):
    """A funding figure that is only the unexplained gap is not a funding need."""
    if need_amount is None or gap_amount is None:
        return need_amount
    if abs(abs(float(need_amount)) - abs(float(gap_amount))) < 0.05:
        return None
    return need_amount
