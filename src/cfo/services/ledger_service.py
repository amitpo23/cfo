"""Derived double-entry shadow ledger (מנוע הנהלת חשבונות כפולה).

SUMIT is the system of record but its API does NOT expose journal entries / a
trial balance. This module DERIVES a balanced double-entry ledger from the
documents we *can* sync (invoices, bills, expenses, payments), using fixed Israeli
posting rules. It is explicitly NOT the official books — every output carries
`derived: True` and a "לבדיקת רו"ח" disclaimer.

Hard invariant, verified by tests: every entry balances (Σdebit == Σcredit) and so
does the whole trial balance. We post the accounting identity (DR receivable =
subtotal + tax), never the stored `total`, so a rounding discrepancy in source data
becomes a data-quality flag rather than a ledger imbalance.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Optional

DISCLAIMER = "נגזר מהמסמכים — לא הספרים הרשמיים. לבדיקת רו\"ח."

# Minimal Israeli chart of accounts.
CHART: dict[str, dict[str, str]] = {
    "1100": {"name": "לקוחות", "type": "asset"},
    "1200": {"name": "עו\"ש בנק", "type": "asset"},
    "1300": {"name": "מע\"מ תשומות", "type": "asset"},
    "2100": {"name": "ספקים", "type": "liability"},
    "2200": {"name": "מע\"מ עסקאות", "type": "liability"},
    "3000": {"name": "הון ויתרות פתיחה", "type": "equity"},
    "4000": {"name": "הכנסות", "type": "revenue"},
    "5000": {"name": "הוצאות", "type": "expense"},
    "5100": {"name": "הוצאות שכר", "type": "expense"},
    "2110": {"name": "שכר נטו לתשלום", "type": "liability"},
    "2300": {"name": "ניכויי שכר לתשלום", "type": "liability"},
}

# Statuses that should NOT post to the ledger (not real economic events).
_SKIP_INVOICE = {"draft", "void", "cancelled"}
_SKIP_BILL = {"draft", "void"}


@dataclass
class Line:
    account: str
    debit: float = 0.0
    credit: float = 0.0
    description: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "account": self.account,
            "account_name": CHART.get(self.account, {}).get("name", self.account),
            "debit": round(self.debit, 2),
            "credit": round(self.credit, 2),
            "description": self.description,
        }


@dataclass
class Entry:
    entry_date: Optional[date]
    memo: str
    source_ref: str
    lines: list[Line] = field(default_factory=list)

    @property
    def total_debit(self) -> float:
        return round(sum(l.debit for l in self.lines), 2)

    @property
    def total_credit(self) -> float:
        return round(sum(l.credit for l in self.lines), 2)

    @property
    def balanced(self) -> bool:
        return abs(self.total_debit - self.total_credit) < 0.01

    def as_dict(self) -> dict[str, Any]:
        return {
            "date": self.entry_date.isoformat() if self.entry_date else None,
            "memo": self.memo,
            "source_ref": self.source_ref,
            "lines": [l.as_dict() for l in self.lines],
            "total_debit": self.total_debit,
            "total_credit": self.total_credit,
            "balanced": self.balanced,
        }


def _f(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _in_period(d: Optional[date], start: Optional[date], end: Optional[date]) -> bool:
    if d is None:
        return start is None and end is None
    if start is not None and d < start:
        return False
    if end is not None and d > end:
        return False
    return True


# ---------------------------------------------------------------------- #
# Posting rules — each returns a balanced Entry (DR identity = subtotal+tax).
# ---------------------------------------------------------------------- #
def post_invoice(inv) -> Optional[Entry]:
    """Sales invoice: DR 1100 (subtotal+tax), CR 4000 (subtotal), CR 2200 (tax)."""
    subtotal, tax = _f(inv.subtotal), _f(inv.tax)
    if subtotal == 0 and tax == 0:
        return None
    receivable = round(subtotal + tax, 2)
    name = inv.invoice_number or f"INV-{inv.id}"
    e = Entry(entry_date=inv.issue_date or inv.due_date, memo=f"חשבונית {name}",
              source_ref=f"invoice:{inv.id}")
    e.lines = [
        Line("1100", debit=receivable, description="לקוחות"),
        Line("4000", credit=subtotal, description="הכנסות"),
        Line("2200", credit=tax, description="מע\"מ עסקאות"),
    ]
    return e


def post_bill(bill) -> Optional[Entry]:
    """Purchase bill: DR 5000 (subtotal), DR 1300 (tax), CR 2100 (subtotal+tax)."""
    subtotal, tax = _f(bill.subtotal), _f(bill.tax)
    if subtotal == 0 and tax == 0:
        return None
    payable = round(subtotal + tax, 2)
    name = bill.bill_number or f"BILL-{bill.id}"
    e = Entry(entry_date=bill.issue_date or bill.due_date, memo=f"חשבון ספק {name}",
              source_ref=f"bill:{bill.id}")
    e.lines = [
        Line("5000", debit=subtotal, description="הוצאות"),
        Line("1300", debit=tax, description="מע\"מ תשומות"),
        Line("2100", credit=payable, description="ספקים"),
    ]
    return e


def post_expense(exp) -> Optional[Entry]:
    """Filed expense (no AP cycle): DR 5000 (net), DR 1300 (vat), CR 1200 (bank)."""
    net = _f(exp.amount)
    vat = _f(exp.vat_amount)
    if net == 0 and vat == 0:
        return None
    paid = round(net + vat, 2)
    e = Entry(entry_date=exp.expense_date, memo=f"הוצאה — {exp.supplier_name or ''}".strip(),
              source_ref=f"expense:{exp.id}")
    e.lines = [
        Line("5000", debit=net, description="הוצאות"),
        Line("1300", debit=vat, description="מע\"מ תשומות"),
        Line("1200", credit=paid, description="עו\"ש בנק"),
    ]
    return e


def post_payment(pay) -> Optional[Entry]:
    """Receipt (invoice): DR 1200 CR 1100. Supplier payment (bill): DR 2100 CR 1200."""
    amount = _f(pay.amount)
    if amount == 0:
        return None
    if pay.invoice_id:
        e = Entry(entry_date=pay.payment_date, memo="תקבול מלקוח",
                  source_ref=f"payment:{pay.id}")
        e.lines = [
            Line("1200", debit=amount, description="עו\"ש בנק"),
            Line("1100", credit=amount, description="לקוחות"),
        ]
        return e
    if pay.bill_id:
        e = Entry(entry_date=pay.payment_date, memo="תשלום לספק",
                  source_ref=f"payment:{pay.id}")
        e.lines = [
            Line("2100", debit=amount, description="ספקים"),
            Line("1200", credit=amount, description="עו\"ש בנק"),
        ]
        return e
    return None  # unlinked payment — cannot classify deterministically


# ---------------------------------------------------------------------- #
# Opening balances (carry-forward)
# ---------------------------------------------------------------------- #
def opening_entry(db, organization_id: int) -> Optional[Entry]:
    """Build a single balanced opening-balance entry from stored opening balances.

    Any residual (so debits == credits) is auto-plugged to the equity account 3000,
    keeping the trial-balance invariant intact even with partial opening data.
    """
    from ..models import LedgerOpeningBalance

    rows = db.query(LedgerOpeningBalance).filter(
        LedgerOpeningBalance.organization_id == organization_id).all()
    if not rows:
        return None
    as_of = min((r.as_of for r in rows if r.as_of), default=None)
    e = Entry(entry_date=as_of, memo="יתרות פתיחה", source_ref="opening")
    total_debit = total_credit = 0.0
    for r in rows:
        d, c = float(r.debit or 0), float(r.credit or 0)
        if d == 0 and c == 0:
            continue
        e.lines.append(Line(r.account_code, debit=d, credit=c,
                            description=CHART.get(r.account_code, {}).get("name", "")))
        total_debit += d
        total_credit += c
    residual = round(total_debit - total_credit, 2)
    if abs(residual) >= 0.01:
        # Plug to equity so the opening entry balances (DR if credits exceed debits).
        if residual > 0:
            e.lines.append(Line("3000", credit=residual, description="הון פתיחה (איזון)"))
        else:
            e.lines.append(Line("3000", debit=-residual, description="הון פתיחה (איזון)"))
    return e if e.lines else None


def set_opening_balances(db, organization_id: int, as_of: date,
                         balances: list[dict[str, Any]]) -> dict[str, Any]:
    """Replace the org's opening balances. balances: [{account, debit, credit}]."""
    from ..models import LedgerOpeningBalance

    db.query(LedgerOpeningBalance).filter(
        LedgerOpeningBalance.organization_id == organization_id).delete()
    for b in balances:
        code = str(b.get("account") or b.get("account_code") or "").strip()
        if code not in CHART:
            continue
        db.add(LedgerOpeningBalance(
            organization_id=organization_id, account_code=code, as_of=as_of,
            debit=float(b.get("debit") or 0), credit=float(b.get("credit") or 0)))
    db.commit()
    return get_opening_balances(db, organization_id)


def get_opening_balances(db, organization_id: int) -> dict[str, Any]:
    from ..models import LedgerOpeningBalance

    rows = db.query(LedgerOpeningBalance).filter(
        LedgerOpeningBalance.organization_id == organization_id).all()
    items = [{"account": r.account_code,
              "name": CHART.get(r.account_code, {}).get("name", r.account_code),
              "as_of": r.as_of.isoformat() if r.as_of else None,
              "debit": float(r.debit or 0), "credit": float(r.credit or 0)} for r in rows]
    return {"items": items, "count": len(items)}


# ---------------------------------------------------------------------- #
# Public API
# ---------------------------------------------------------------------- #
def _normalize_and_validate_lines(lines: list[dict], *, require_min_two: bool = True) -> list[dict]:
    """Shared normalization/balance-check for manual and payroll journal entries."""
    norm = []
    total_d = total_c = 0.0
    for ln in lines or []:
        d = _f(ln.get("debit"))
        c = _f(ln.get("credit"))
        total_d += d
        total_c += c
        norm.append({
            "account": str(ln.get("account") or "").strip(),
            "debit": round(d, 2),
            "credit": round(c, 2),
            "description": ln.get("description", ""),
        })
    if require_min_two and len(norm) < 2:
        raise ValueError("פקודת יומן דורשת לפחות שתי שורות")
    if round(total_d, 2) <= 0:
        raise ValueError("פקודת יומן ריקה (סכום אפס)")
    if abs(round(total_d - total_c, 2)) >= 0.01:
        raise ValueError(f"פקודת יומן אינה מאוזנת: חובה {total_d:.2f} ≠ זכות {total_c:.2f}")
    if any(not ln["account"] for ln in norm):
        raise ValueError("כל שורה חייבת קוד חשבון")
    return norm


def add_manual_entry(db, organization_id: int, *, entry_date: date, memo: str,
                     lines: list[dict]) -> "object":
    """פקודת יומן ידנית (התאמת רו"ח). חייבת להיות מאוזנת (Σחובה==Σזכות, >0).

    נשמרת ב-JournalEntry(source='manual') ונכללת אוטומטית ב-build_journal/trial_balance.
    """
    norm = _normalize_and_validate_lines(lines)

    from ..models import JournalEntry
    row = JournalEntry(
        organization_id=organization_id, source="manual",
        entry_date=entry_date, memo=memo or "פקודת יומן ידנית", lines=norm,
    )
    db.add(row)
    db.flush()
    return row


def add_payroll_entry(db, organization_id: int, *, entry_date: date, memo: str,
                      lines: list[dict], external_id: str) -> "object":
    """פקודת יומן שכר נגזרת (ברוטו הוצאה / ניכויים התחייבות / נטו לתשלום).

    נשמרת ב-JournalEntry(source='payroll'), מעודכנת (לא משוכפלת) בהרצה חוזרת
    לאותו external_id — נכללת אוטומטית ב-build_journal/trial_balance.
    """
    norm = _normalize_and_validate_lines(lines)

    from ..models import JournalEntry
    row = db.query(JournalEntry).filter(
        JournalEntry.organization_id == organization_id,
        JournalEntry.source == "payroll",
        JournalEntry.external_id == external_id,
    ).first()
    if row:
        row.entry_date = entry_date
        row.memo = memo
        row.lines = norm
    else:
        row = JournalEntry(
            organization_id=organization_id, source="payroll", external_id=external_id,
            entry_date=entry_date, memo=memo, lines=norm,
        )
        db.add(row)
    db.flush()
    return row


def _entries_by_source(db, organization_id: int, source: str, default_memo: str) -> list[Entry]:
    """פקודות יומן שמורות (ידניות/שכר) → Entry objects (מאוזנות בבנייה)."""
    from ..models import JournalEntry
    out: list[Entry] = []
    rows = db.query(JournalEntry).filter(
        JournalEntry.organization_id == organization_id,
        JournalEntry.source == source,
    ).all()
    for r in rows:
        lines = [Line(account=str(l.get("account")), debit=_f(l.get("debit")),
                      credit=_f(l.get("credit")), description=l.get("description", ""))
                 for l in (r.lines or [])]
        out.append(Entry(entry_date=r.entry_date, memo=r.memo or default_memo,
                          source_ref=f"{source}:{r.id}", lines=lines))
    return out


def _manual_entries(db, organization_id: int) -> list[Entry]:
    return _entries_by_source(db, organization_id, "manual", "פקודת יומן ידנית")


def _payroll_entries(db, organization_id: int) -> list[Entry]:
    return _entries_by_source(db, organization_id, "payroll", "פקודת שכר")


def build_journal(db, organization_id: int, *, start: Optional[date] = None,
                  end: Optional[date] = None, include_opening: bool = True) -> list[Entry]:
    """Derive the full balanced journal for the period from synced documents.

    Includes the opening-balance entry (carry-forward) when `include_opening` and its
    date falls within [start, end] — so position reports (trial balance / balance
    sheet) reflect carried-forward balances, not just in-period movement.
    """
    from ..models import Invoice, Bill, Expense, Payment

    entries: list[Entry] = []
    if include_opening:
        opening = opening_entry(db, organization_id)
        if opening and _in_period(opening.entry_date, start, end):
            entries.append(opening)

    for inv in db.query(Invoice).filter(Invoice.organization_id == organization_id).all():
        status = getattr(inv.status, "value", inv.status)
        if str(status).lower() in _SKIP_INVOICE:
            continue
        if not _in_period(inv.issue_date or inv.due_date, start, end):
            continue
        e = post_invoice(inv)
        if e:
            entries.append(e)

    for bill in db.query(Bill).filter(Bill.organization_id == organization_id).all():
        status = getattr(bill.status, "value", bill.status)
        if str(status).lower() in _SKIP_BILL:
            continue
        if not _in_period(bill.issue_date or bill.due_date, start, end):
            continue
        e = post_bill(bill)
        if e:
            entries.append(e)

    for exp in db.query(Expense).filter(Expense.organization_id == organization_id).all():
        if str(getattr(exp, "status", "") or "").lower() == "error":
            continue
        if not _in_period(exp.expense_date, start, end):
            continue
        e = post_expense(exp)
        if e:
            entries.append(e)

    for pay in db.query(Payment).filter(Payment.organization_id == organization_id).all():
        if not _in_period(pay.payment_date, start, end):
            continue
        e = post_payment(pay)
        if e:
            entries.append(e)

    # פקודות יומן ידניות (התאמות רו"ח)
    for e in _manual_entries(db, organization_id):
        if _in_period(e.entry_date, start, end):
            entries.append(e)

    # פקודות יומן שכר נגזרות
    for e in _payroll_entries(db, organization_id):
        if _in_period(e.entry_date, start, end):
            entries.append(e)

    entries.sort(key=lambda e: (e.entry_date or date.max))
    return entries


def trial_balance(db, organization_id: int, *, start: Optional[date] = None,
                  end: Optional[date] = None) -> dict[str, Any]:
    """Aggregate all postings per account; assert the books balance globally."""
    entries = build_journal(db, organization_id, start=start, end=end)
    debit_by: dict[str, float] = {}
    credit_by: dict[str, float] = {}
    for e in entries:
        for l in e.lines:
            debit_by[l.account] = debit_by.get(l.account, 0.0) + l.debit
            credit_by[l.account] = credit_by.get(l.account, 0.0) + l.credit

    accounts = []
    total_debit = total_credit = 0.0
    for code in sorted(set(debit_by) | set(credit_by)):
        d = round(debit_by.get(code, 0.0), 2)
        c = round(credit_by.get(code, 0.0), 2)
        meta = CHART.get(code, {})
        balance = round(d - c, 2)
        accounts.append({
            "account": code,
            "name": meta.get("name", code),
            "type": meta.get("type", "other"),
            "debit": d,
            "credit": c,
            "balance": balance,
        })
        total_debit += d
        total_credit += c

    total_debit = round(total_debit, 2)
    total_credit = round(total_credit, 2)
    return {
        "period": {"start": start.isoformat() if start else None,
                   "end": end.isoformat() if end else None},
        "accounts": accounts,
        "total_debit": total_debit,
        "total_credit": total_credit,
        "balanced": abs(total_debit - total_credit) < 0.01,
        "entry_count": len(entries),
        "derived": True,
        "disclaimer": DISCLAIMER,
    }


def general_ledger(db, organization_id: int, account_code: str, *,
                   start: Optional[date] = None, end: Optional[date] = None) -> dict[str, Any]:
    """כרטסת — running balance of one account over the period."""
    entries = build_journal(db, organization_id, start=start, end=end)
    movements = []
    running = 0.0
    for e in entries:
        for l in e.lines:
            if l.account != account_code:
                continue
            running = round(running + l.debit - l.credit, 2)
            movements.append({
                "date": e.entry_date.isoformat() if e.entry_date else None,
                "memo": e.memo,
                "source_ref": e.source_ref,
                "debit": round(l.debit, 2),
                "credit": round(l.credit, 2),
                "balance": running,
            })
    meta = CHART.get(account_code, {})
    return {
        "account": account_code,
        "name": meta.get("name", account_code),
        "type": meta.get("type", "other"),
        "movements": movements,
        "closing_balance": running,
        "derived": True,
        "disclaimer": DISCLAIMER,
    }


def contact_card(db, organization_id: int, contact_id: int, *,
                 start: Optional[date] = None, end: Optional[date] = None) -> Optional[dict[str, Any]]:
    """כרטסת לקוח/ספק — Invoice/Bill/Payment של איש קשר אחד, כרונולוגית עם יתרה רצה.

    שלא כמו general_ledger (חשבון בספר הכללי, חובה/זכות), זו יתרת "כמה חייבים
    על החשבון הזה": חשבונית/חשבון ספק מגדילים את היתרה (סכום פתוח), תשלום
    מקטין אותה — ללא תלות אם מדובר בלקוח (הם חייבים לנו) או ספק (אנחנו חייבים).
    """
    from ..models import Contact, Invoice, Bill, Payment

    contact = db.query(Contact).filter(
        Contact.id == contact_id, Contact.organization_id == organization_id
    ).first()
    if not contact:
        return None

    raw_movements = []
    for inv in db.query(Invoice).filter(
        Invoice.contact_id == contact_id, Invoice.organization_id == organization_id
    ).all():
        d = inv.issue_date or inv.due_date
        if not _in_period(d, start, end):
            continue
        raw_movements.append((d, {
            "type": "invoice", "document": inv.invoice_number or f"INV-{inv.id}",
            "description": "חשבונית", "amount": round(_f(inv.total), 2),
        }))

    for bill in db.query(Bill).filter(
        Bill.vendor_id == contact_id, Bill.organization_id == organization_id
    ).all():
        d = bill.issue_date or bill.due_date
        if not _in_period(d, start, end):
            continue
        raw_movements.append((d, {
            "type": "bill", "document": bill.bill_number or f"BILL-{bill.id}",
            "description": "חשבון ספק", "amount": round(_f(bill.total), 2),
        }))

    for pay in db.query(Payment).filter(
        Payment.contact_id == contact_id, Payment.organization_id == organization_id
    ).all():
        d = pay.payment_date
        if not _in_period(d, start, end):
            continue
        raw_movements.append((d, {
            "type": "payment", "document": pay.reference or pay.external_id or f"PAY-{pay.id}",
            "description": "תשלום/תקבול", "amount": round(-_f(pay.amount), 2),
        }))

    raw_movements.sort(key=lambda m: m[0] or date.max)

    movements = []
    running = 0.0
    for d, m in raw_movements:
        running = round(running + m["amount"], 2)
        movements.append({**m, "date": d.isoformat() if d else None, "balance": running})

    return {
        "contact_id": contact.id,
        "contact_name": contact.name,
        "contact_type": getattr(contact.contact_type, "value", contact.contact_type),
        "movements": movements,
        "closing_balance": running,
        "derived": True,
        "disclaimer": DISCLAIMER,
    }


def balance_sheet(db, organization_id: int, *, start: Optional[date] = None,
                  end: Optional[date] = None) -> dict[str, Any]:
    """מאזן נגזר — assets / liabilities / equity from the ledger.

    Equity = opening equity (carried-forward balances) + retained earnings
    (revenue − expenses). The identity Assets = Liabilities + Equity holds by
    construction because the trial balance balances. When opening balances are set,
    this reflects a real starting position; without them it is document-movement only.
    """
    tb = trial_balance(db, organization_id, start=start, end=end)
    assets, liabilities = [], []
    revenue = expenses = opening_equity = 0.0
    for a in tb["accounts"]:
        bal = a["debit"] - a["credit"]
        if a["type"] == "asset":
            assets.append({"account": a["account"], "name": a["name"], "balance": round(bal, 2)})
        elif a["type"] == "liability":
            liabilities.append({"account": a["account"], "name": a["name"], "balance": round(-bal, 2)})
        elif a["type"] == "equity":
            opening_equity += -bal
        elif a["type"] == "revenue":
            revenue += -bal
        elif a["type"] == "expense":
            expenses += bal

    total_assets = round(sum(x["balance"] for x in assets), 2)
    total_liabilities = round(sum(x["balance"] for x in liabilities), 2)
    retained_earnings = round(revenue - expenses, 2)
    opening_equity = round(opening_equity, 2)
    total_equity = round(opening_equity + retained_earnings, 2)
    total_equity_and_liabilities = round(total_liabilities + total_equity, 2)
    return {
        "period": tb["period"],
        "assets": assets,
        "total_assets": total_assets,
        "liabilities": liabilities,
        "total_liabilities": total_liabilities,
        "equity": {"opening_equity": opening_equity, "retained_earnings": retained_earnings,
                   "total_equity": total_equity},
        "total_equity_and_liabilities": total_equity_and_liabilities,
        "balanced": abs(total_assets - total_equity_and_liabilities) < 0.01,
        "derived": True,
        "disclaimer": DISCLAIMER + " ללא יתרות פתיחה.",
    }
