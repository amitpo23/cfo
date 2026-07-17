"""PCN874 detailed-VAT file builder (דוח מפורט מע"מ — מבנה אחיד).

Builds the fixed-width PCN874 text file the Israeli Tax Authority expects, from the
same document selection engine as the rest of the VAT stack
(`financial_synthesis.select_vat_documents`) — so its totals always reconcile 1:1
with `daily_reports_service.vat_report_period` run with the same year/month/months/
basis, and the Bill↔Expense SUMIT-twin dedup is shared, not reimplemented.

IMPORTANT — DRAFT STRUCTURE: the record types (O/S1/L/X) and field order follow the
published מבנה-אחיד, but exact byte offsets evolve by spec version. Output is marked
a draft to validate against the current official spec before submission; it is NOT a
guaranteed-conformant file. The numbers themselves reconcile to the canonical VAT
position (tested), so it is correct as data even where the layout needs verification.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Optional

DISCLAIMER = "טיוטת PCN874 — מבנה לאימות מול מפרט רשות המסים העדכני לפני הגשה."

# Record-type codes (מבנה אחיד).
REC_HEADER = "O"
REC_SALE_TAXABLE = "S1"
REC_INPUT = "L"
REC_TRAILER = "X"


def _num(value, width: int) -> str:
    """Zero-padded, right-aligned non-negative integer (agorot-rounded shekels)."""
    n = int(round(abs(float(value or 0))))
    return str(n).rjust(width, "0")[:width]


def _signed_num(value, width: int) -> str:
    """כמו _num אך משמר סימן שלילי (חשבונית זיכוי): '-' תופס את תו הריפוד הראשון,
    כך שרוחב השדה נשמר וערכים אי-שליליים נראים בדיוק כמו ב-_num.

    PLACEHOLDER לאימות (כמו שאר ה-DISCLAIMER): במבנה PCN874 האמיתי זיכויים מיוצגים
    בסכום שלילי עם ייצוג סימן בשדה — הייצוג המדויק (מיקום/תו הסימן) טעון אימות מול
    המפרט הרשמי לפני הגשה. הנתון עצמו (הנטו כולל הזיכוי) נכון ומתואם 1:1 מול
    vat_report_period.
    """
    n = int(round(float(value or 0)))
    if n >= 0:
        return str(n).rjust(width, "0")[:width]
    return ("-" + str(abs(n)).rjust(width - 1, "0")[:width - 1])[:width]


def _txt(value, width: int) -> str:
    return (str(value or "")[:width]).ljust(width)


def _vat_id(value, width: int = 9) -> str:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    return digits.rjust(width, "0")[-width:] if digits else "0" * width


def _yyyymmdd(d: Optional[date]) -> str:
    return d.strftime("%Y%m%d") if d else "00000000"


def build_pcn874(db, organization_id: int, year: int, month: int, *,
                 months: int = 1, basis: str = "document",
                 company_vat_id: str = "000000000",
                 gen_date: Optional[date] = None) -> dict[str, Any]:
    """Build the PCN874 file content + a reconciling summary for the period.

    `months`/`basis` mirror `daily_reports_service.vat_report_period` exactly (same
    underlying `select_vat_documents` call) — pass the same values to both to get
    reconciling totals for a monthly/bimonthly, document/captured-basis period.
    """
    from . import financial_synthesis

    pb = financial_synthesis.period_bounds(year, month, months)
    start = pb["start"]
    sel = financial_synthesis.select_vat_documents(
        db, organization_id, start=start, end=pb["end"], basis=basis)

    # שורות מכירה: _signed_num ולא _num — חשבונית זיכוי מגיעה מ-select_vat_documents
    # בסכומים שליליים וחייבת לשאת את הסימן בשורת ה-S1 (ולא להיבלע ב-abs).
    sale_lines, total_sales, total_output_vat = [], 0.0, 0.0
    for r in sel["sales"]:
        total_sales += r["subtotal"]
        total_output_vat += r["vat"]
        sale_lines.append(
            REC_SALE_TAXABLE
            + _vat_id(r.get("allocation_number"))
            + _yyyymmdd(r["doc_date"])
            + _txt(r["number"], 9)
            + _signed_num(r["subtotal"], 11) + _signed_num(r["vat"], 9)
        )

    # שורת התשומה נושאת את תאריך הקליטה כש-basis=captured (עקבי עם הבחירה עצמה),
    # אחרת את תאריך המסמך — כמו ב-vat_report_period.
    input_lines, total_inputs, total_input_vat = [], 0.0, 0.0
    for r in sel["inputs"]:
        total_inputs += r["subtotal"]
        total_input_vat += r["vat"]
        line_date = r["captured_date"] if (basis == "captured" and r["captured_date"]) else r["doc_date"]
        input_lines.append(
            REC_INPUT + _vat_id(r.get("vat_id")) + _yyyymmdd(line_date) + _txt(r["number"], 9)
            + _num(r["subtotal"], 11) + _num(r["vat"], 9)
        )

    # שורת ה-O משקפת את הנטו כולל זיכויים (total_sales/total_output_vat כבר מסוכמים
    # בסימן); _signed_num מגן גם על מקרה קצה של נטו שלילי בתקופה.
    header = (
        REC_HEADER + _vat_id(company_vat_id) + f"{year}{pb['anchor_month']:02d}"
        + _yyyymmdd(gen_date or start)
        + _signed_num(total_sales, 11) + _signed_num(total_output_vat, 9)
        + _num(total_inputs, 11) + _num(total_input_vat, 9)
    )
    detail = sale_lines + input_lines
    trailer = REC_TRAILER + _num(len(detail), 9)
    content = "\r\n".join([header] + detail + [trailer])

    net_vat = round(total_output_vat - total_input_vat, 2)
    period_label = (f"{year}-{pb['anchor_month']:02d}" if months == 1 else
                    f"{year}-{pb['anchor_month']:02d}_{year}-{pb['end_month']:02d}")
    return {
        "filename": f"PCN874_{_vat_id(company_vat_id)}_{year}{pb['anchor_month']:02d}.txt",
        "period": period_label,
        "months": months,
        "basis": basis,
        "content": content,
        "record_count": len(detail),
        "summary": {
            "sales": round(total_sales, 2),
            "output_vat": round(total_output_vat, 2),
            "inputs": round(total_inputs, 2),
            "input_vat": round(total_input_vat, 2),
            "net_vat": net_vat,
            "direction": "לתשלום" if net_vat >= 0 else "להחזר",
        },
        "draft": True,
        "disclaimer": DISCLAIMER,
    }
