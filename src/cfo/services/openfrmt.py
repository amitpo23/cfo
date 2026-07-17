"""OPENFRMT — יצוא 'מבנה אחיד' (הוראות ניהול פנקסים / תקנה 36, הוראה 1.31).

מייצר את זוג הקבצים INI.TXT + BKMVDATA.TXT שתוכנות הנה"ח (חשבשבת ואחרות) מייבאות —
מה-invoices/bills הקיימים לנו כמסמכי מכירה/רכש (C100 + D110), תקבולים מ-Payment
(D120), ופקודות יומן אמיתיות אם קיימות בטבלת JournalEntry המסונכרנת מ-SUMIT (B100).

DRAFT — כמו pcn874.py: סוגי הרשומות (A100/B100/C100/D110/D120/Z900) והשדות עוקבים
אחרי המפרט הציבורי, אך רוחבי/סדר השדות המדויקים *לא* אומתו מול 'בודק קבצים להפקת
מסמכים ממוחשבים' של רשות המסים — ראה DISCLAIMER. שדות שאין לנו מקור נתונים אמין
עבורם (כתובת מפורקת לרחוב/עיר/מיקוד, סוג הנהלת חשבונות חד/דו-צידית, קוד אמצעי
תשלום וכו') ממולאים באפסים/רווחים לפי רוחב השדה בלבד ומתועדים ב-
summary["placeholder_fields"] — לא מומצאים. קוד סוג המסמך (C100.document_type_code)
הוא מיפוי גס לא-מאומת (מתועד ב-summary["approximate_mappings"]), לא ערך רשמי.

B100 (פקודות יומן): רק אם קיימות רשומות JournalEntry אמיתיות (מסונכרנות מ-SUMIT)
בטווח התאריכים. אם אין — לא מייצרים B100 בדוי; מתועד ב-summary["b100_note"].
"""
from __future__ import annotations

from datetime import date
from typing import Any, Optional

DISCLAIMER = (
    "יצוא טיוטת מבנה אחיד — לאימות מול 'בודק קבצים להפקת מסמכים ממוחשבים' של רשות "
    "המסים לפני שימוש רשמי. שדות תחת placeholder_fields מולאו כרווחים/אפסים בלבד "
    "(אין מקור נתונים אמין עבורם) — לא הומצאו."
)

SOFTWARE_NAME = "CFO-ENGINE"
SOFTWARE_VERSION = "0001"

# מיפוי גס (לא מאומת) של סוג מסמך ל-C100.document_type_code.
DOC_TYPE_SALE = "100"      # חשבונית מס (מכירה) — הערכה, ראה summary.approximate_mappings
DOC_TYPE_PURCHASE = "405"  # חשבון/חשבונית ספק (רכש) — הערכה, ראה summary.approximate_mappings
DOC_TYPE_CREDIT = "330"    # חשבונית זיכוי (מבנה אחיד) — הערכה, ראה summary.approximate_mappings

# סיווגי raw_data.document_type שמסמנים חשבונית זיכוי (ראה sumit_connector /
# financial_synthesis) — סכומיה נשארים שליליים כמו שהם בשורת C100.
CREDIT_DOC_TYPES = {"credit_note", "credit_invoice"}

PLACEHOLDER_FIELDS = {
    "A100": ["street", "city", "zip_code", "fax", "software_house_vat_id",
             "software_registration_number", "bookkeeping_method"],
    "C100": ["branch_id"],
    "D110": ["quantity (כשאין line_items אמיתיים)", "unit_price (כשאין line_items אמיתיים)",
             "vat_amount (כשאין line_items אמיתיים — רק ברמת מסמך שלם)"],
    "D120": ["payment_method_code"],
    "B100": [],
    "Z900": [],
}


def _digits(value, width: int) -> str:
    d = "".join(ch for ch in str(value or "") if ch.isdigit())
    return d.rjust(width, "0")[-width:] if d else "0" * width


def _txt(value, width: int) -> str:
    return (str(value or "")[:width]).ljust(width)


def _f(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _num(value, width: int) -> str:
    """Zero-padded non-negative integer, agorot (2 decimal digits folded in)."""
    n = int(round(abs(_f(value)) * 100))
    return str(n).rjust(width, "0")[:width]


def _num_signed(value, width: int) -> str:
    """כמו _num אך משמר סימן שלילי (חשבונית זיכוי): '-' תופס את תו הריפוד הראשון,
    כך שרוחב השדה נשמר וערכים אי-שליליים זהים לפלט _num. placeholder לאימות מול
    המפרט הרשמי (כמו שאר ה-DISCLAIMER)."""
    n = int(round(_f(value) * 100))
    if n >= 0:
        return str(n).rjust(width, "0")[:width]
    return ("-" + str(abs(n)).rjust(width - 1, "0")[:width - 1])[:width]


def _signed_num(value, width: int) -> str:
    """Sign + zero-padded integer, agorot. width includes the sign character."""
    n = int(round(_f(value) * 100))
    sign = "-" if n < 0 else "+"
    return sign + str(abs(n)).rjust(width - 1, "0")[:width - 1]


def _yyyymmdd(d: Optional[date]) -> str:
    return d.strftime("%Y%m%d") if d else "0" * 8


def _blank(width: int) -> str:
    return " " * width


def _zeros(width: int) -> str:
    return "0" * width


def encode_openfrmt_text(text: str) -> tuple[bytes, str]:
    """Encode per the מבנה אחיד convention (ISO-8859-8), falling back to UTF-8 with
    `errors="replace"` if a character can't be represented in ISO-8859-8 (returns the
    encoding actually used so callers can surface/log the fallback)."""
    try:
        return text.encode("iso-8859-8"), "iso-8859-8"
    except UnicodeEncodeError:
        return text.encode("utf-8", errors="replace"), "utf-8"


def build_openfrmt(db, organization_id: int, date_from: date, date_to: date) -> dict[str, Any]:
    """Build the INI.TXT + BKMVDATA.TXT content for [date_from, date_to] (inclusive)."""
    from ..models import Organization, Invoice, Bill, Payment, JournalEntry
    from .vat_utils import invoice_counts, bill_counts

    org = db.get(Organization, organization_id)
    org_vat = _digits(getattr(org, "tax_id", None), 9)
    org_name = _txt(getattr(org, "name", None), 50)

    def _in_range(d) -> bool:
        return d is not None and date_from <= d <= date_to

    # ---- A100 — רשומת פתיחה ----------------------------------------------------
    a100 = (
        "A100" + org_vat + org_name
        + _blank(30) + _blank(20) + _zeros(7)            # street, city, zip — placeholder
        + _digits(getattr(org, "phone", None), 11)
        + _zeros(11)                                       # fax — placeholder
        + _zeros(9) + _zeros(8)                             # software-house vat id, reg number — placeholder
        + _txt(SOFTWARE_NAME, 20) + _txt(SOFTWARE_VERSION, 8)
        + "0"                                                # bookkeeping method — placeholder
        + _txt("ILS", 3)
        + _yyyymmdd(date.today())
        + _yyyymmdd(date_from) + _yyyymmdd(date_to)
    )

    # ---- מסמכים (C100 + D110) ---------------------------------------------------
    docs: list[dict[str, Any]] = []
    for inv in db.query(Invoice).filter(Invoice.organization_id == organization_id).all():
        if not invoice_counts(inv.status):
            continue
        d = getattr(inv, "issue_date", None) or getattr(inv, "due_date", None)
        if not _in_range(d):
            continue
        contact = getattr(inv, "contact", None)
        # חשבונית זיכוי (לפי הסיווג המנורמל ב-raw_data) — קוד סוג 330 וסכומים
        # שליליים כמו שהם; שאר החשבוניות נשארות abs() כמו קודם.
        raw_doc_type = str(((getattr(inv, "raw_data", None) or {}).get("document_type")) or "").lower()
        is_credit = raw_doc_type in CREDIT_DOC_TYPES
        sign = -1.0 if is_credit else 1.0
        docs.append({
            "doc_type": DOC_TYPE_CREDIT if is_credit else DOC_TYPE_SALE,
            "number": inv.invoice_number, "date": d,
            "cp_vat": _digits(getattr(contact, "tax_id", None), 9),
            "cp_name": _txt(getattr(contact, "name", None), 30),
            "subtotal": sign * abs(_f(inv.subtotal)), "vat": sign * abs(_f(inv.tax)),
            "total": (sign * abs(_f(inv.total))) or (sign * (abs(_f(inv.subtotal)) + abs(_f(inv.tax)))),
            "line_items": inv.line_items,
        })

    for bill in db.query(Bill).filter(Bill.organization_id == organization_id).all():
        if not bill_counts(bill.status):
            continue
        d = getattr(bill, "issue_date", None) or getattr(bill, "due_date", None)
        if not _in_range(d):
            continue
        vendor = getattr(bill, "vendor", None)
        docs.append({
            "doc_type": DOC_TYPE_PURCHASE, "number": bill.bill_number, "date": d,
            "cp_vat": _digits(getattr(vendor, "tax_id", None), 9),
            "cp_name": _txt(getattr(vendor, "name", None), 30),
            "subtotal": abs(_f(bill.subtotal)), "vat": abs(_f(bill.tax)),
            "total": abs(_f(bill.total)) or (abs(_f(bill.subtotal)) + abs(_f(bill.tax))),
            "line_items": bill.line_items,
        })

    c100_lines: list[str] = []
    d110_lines: list[str] = []
    for doc in docs:
        c100_lines.append(
            "C100" + org_vat + _txt(doc["doc_type"], 3) + _txt(doc["number"], 20)
            + _yyyymmdd(doc["date"]) + doc["cp_vat"] + doc["cp_name"]
            + _signed_num(doc["total"], 13) + _num_signed(doc["vat"], 11)
            + _txt("ILS", 3) + _zeros(3)  # currency, branch id — branch is placeholder
        )
        items = doc["line_items"] if isinstance(doc["line_items"], list) and doc["line_items"] else None
        if items:
            for i, item in enumerate(items, start=1):
                if not isinstance(item, dict):
                    continue
                qty = item.get("qty", item.get("quantity"))
                price = item.get("unit_price", item.get("price"))
                amount = item.get("total", item.get("amount", 0))
                desc = item.get("description") or ""
                d110_lines.append(
                    "D110" + org_vat + _txt(doc["doc_type"], 3) + _txt(doc["number"], 20)
                    + str(i).rjust(4, "0") + _txt(desc, 30)
                    + (_num(qty, 13) if qty is not None else _zeros(13))
                    + (_num(price, 13) if price is not None else _zeros(13))
                    + _num(amount, 13)
                    + _zeros(11)  # per-line VAT unknown from line_items — placeholder
                )
        else:
            # אין line_items אמיתיים — שורה אחת לסכום המסמך כולו (subtotal/vat אמיתיים,
            # quantity/unit_price אין להם משמעות ברמת מסמך שלם — placeholder).
            d110_lines.append(
                "D110" + org_vat + _txt(doc["doc_type"], 3) + _txt(doc["number"], 20)
                + "0001" + _blank(30)
                + _zeros(13) + _zeros(13)
                + _num(doc["subtotal"], 13) + _num(doc["vat"], 11)
            )

    # ---- תקבולים (D120) ---------------------------------------------------------
    d120_lines: list[str] = []
    for pay in db.query(Payment).filter(Payment.organization_id == organization_id).all():
        if not _in_range(pay.payment_date):
            continue
        ref_number = None
        if pay.invoice_id:
            ref_inv = db.get(Invoice, pay.invoice_id)
            ref_number = ref_inv.invoice_number if ref_inv else None
        elif pay.bill_id:
            ref_bill = db.get(Bill, pay.bill_id)
            ref_number = ref_bill.bill_number if ref_bill else None
        d120_lines.append(
            "D120" + org_vat + _txt(ref_number, 20) + _yyyymmdd(pay.payment_date)
            + _signed_num(_f(pay.amount), 13)
            + "0"                                # payment method code — placeholder
            + _txt(pay.reference, 20)
        )

    # ---- פקודות יומן (B100) — רק אם קיימת רשומת JournalEntry אמיתית בטווח -------
    je_rows = db.query(JournalEntry).filter(
        JournalEntry.organization_id == organization_id,
        JournalEntry.entry_date >= date_from,
        JournalEntry.entry_date <= date_to,
    ).all()
    b100_lines: list[str] = []
    for je in je_rows:
        lines = je.lines if isinstance(je.lines, list) else []
        ref = je.external_id or str(je.id)
        for line in lines:
            if not isinstance(line, dict):
                continue
            b100_lines.append(
                "B100" + org_vat + _txt(ref, 20) + _yyyymmdd(je.entry_date)
                + _txt(line.get("account_id"), 15)
                + _num(line.get("debit"), 13) + _num(line.get("credit"), 13)
                + _txt(line.get("description"), 30)
            )
    if je_rows and not b100_lines:
        b100_note = f"נמצאו {len(je_rows)} פקודות יומן בטווח אך ללא שורות (lines) — לא הופקו רשומות B100."
    elif not je_rows:
        b100_note = "אין רשומות B100 — לא נמצאו פקודות יומן מסונכרנות (JournalEntry) בטווח התאריכים."
    else:
        b100_note = f"{len(b100_lines)} רשומות B100 מתוך {len(je_rows)} פקודות יומן מסונכרנות."

    body_lines = [a100] + c100_lines + d110_lines + d120_lines + b100_lines
    z900 = "Z900" + _num(len(body_lines) + 1, 9)  # +1 סופר את עצמה
    bkmvdata = "\r\n".join(body_lines + [z900])

    counts = {
        "A100": 1, "C100": len(c100_lines), "D110": len(d110_lines),
        "D120": len(d120_lines), "B100": len(b100_lines), "Z900": 1,
    }
    total_records = sum(counts.values())

    ini_lines = [
        "[General]",
        f"SoftwareName={SOFTWARE_NAME}",
        f"SoftwareVersion={SOFTWARE_VERSION}",
        f"GeneratedAt={date.today().strftime('%Y%m%d')}",
        f"OrgVatId={org_vat}",
        f"PeriodFrom={date_from.strftime('%Y%m%d')}",
        f"PeriodTo={date_to.strftime('%Y%m%d')}",
        "",
        "[RecordCounts]",
    ] + [f"{k}={v}" for k, v in counts.items()] + [f"TotalRecords={total_records}"]
    ini = "\r\n".join(ini_lines)

    return {
        "ini": ini,
        "bkmvdata": bkmvdata,
        "summary": {
            "record_counts": counts,
            "total_records": total_records,
            "documents": len(docs),
            "b100_note": b100_note,
            "placeholder_fields": PLACEHOLDER_FIELDS,
            "approximate_mappings": {
                "C100.document_type_code": (
                    f"{DOC_TYPE_SALE}=מכירה (חשבונית), {DOC_TYPE_PURCHASE}=רכש (חשבון ספק), "
                    f"{DOC_TYPE_CREDIT}=חשבונית זיכוי (סכומים שליליים כמו שהם) — "
                    "מיפוי גס, לא מאומת מול טבלת הקודים הרשמית של רשות המסים"
                ),
            },
            "encoding": "ISO-8859-8, עם fallback ל-UTF-8 (errors=replace) לתו שלא ניתן לקידוד",
        },
        "disclaimer": DISCLAIMER,
        "draft": True,
    }
