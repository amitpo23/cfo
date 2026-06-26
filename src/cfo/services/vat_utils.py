"""VAT split helpers (פיצול מע"מ).

SUMIT's document-list endpoint returns only the VAT-inclusive gross (`DocumentValue`)
and no VAT breakdown, so synced documents land with tax=0 / subtotal=gross — which
zeroes every downstream VAT figure. These helpers recover the split deterministically
from the gross and the document date, using the statutory Israeli VAT rate in effect
on that date. Prefer a real VAT field from the source when one exists; fall back to
this derivation otherwise.

Caveat: derivation assumes a standard VAT-taxable, VAT-inclusive document. VAT-exempt
(פטור) / zero-rated (אפס) documents are over-split by this; when the source exposes an
exemption flag or an explicit VAT amount, that should win over derivation.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP

# Statutory Israeli VAT rate by effective date (most recent first).
_VAT_SCHEDULE = [
    (date(2025, 1, 1), Decimal("0.18")),   # 18% from 2025-01-01
    (date(2015, 10, 1), Decimal("0.17")),  # 17% 2015-10 .. 2024-12
    (date(1900, 1, 1), Decimal("0.18")),   # older fallback
]


def vat_rate_for(doc_date: date | None) -> Decimal:
    d = doc_date or date.today()
    for effective, rate in _VAT_SCHEDULE:
        if d >= effective:
            return rate
    return Decimal("0.18")


def _q(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# ---- סינון לפי סטטוס מסמך ----
# מסמכים שאינם סופיים אינם נספרים כהכנסה/הוצאה/מע"מ: חשבונית/ספק טיוטה או מבוטל,
# והוצאה שטרם תויקה (pending). מונע ניפוח דוחות ודיווח מע"מ ממסמך מבוטל/טיוטה.
_EXCLUDED_INVOICE_STATUSES = {"draft", "void", "cancelled"}
_EXCLUDED_BILL_STATUSES = {"draft", "void"}
_INCLUDED_EXPENSE_STATUSES = {"filed"}


def _status_str(status) -> str:
    return (getattr(status, "value", status) or "").lower() if status is not None else ""


def invoice_counts(status) -> bool:
    """האם חשבונית נספרת (לא טיוטה/מבוטלת)."""
    return _status_str(status) not in _EXCLUDED_INVOICE_STATUSES


def bill_counts(status) -> bool:
    """האם מסמך ספק נספר (לא טיוטה/מבוטל)."""
    return _status_str(status) not in _EXCLUDED_BILL_STATUSES


def expense_counts(status) -> bool:
    """האם הוצאה נספרת (רק filed; pending=טיוטה לא מתויקת)."""
    return _status_str(status) in _INCLUDED_EXPENSE_STATUSES


def split_inclusive(gross, doc_date: date | None) -> tuple[Decimal, Decimal]:
    """Split a VAT-inclusive gross into (subtotal, vat). Sign-preserving.

    subtotal = gross / (1 + rate); vat = gross - subtotal. Rounded to agorot so that
    subtotal + vat == gross exactly (vat absorbs the rounding residue).
    """
    gross = Decimal(str(gross or 0))
    if gross == 0:
        return Decimal("0.00"), Decimal("0.00")
    rate = vat_rate_for(doc_date)
    subtotal = _q(gross / (Decimal("1") + rate))
    vat = _q(gross - subtotal)
    return subtotal, vat
