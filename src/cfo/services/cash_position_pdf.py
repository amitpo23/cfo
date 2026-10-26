"""דוח PDF של מצב המזומנים — מתוך מודל-התצוגה של דשבורד, בעברית מימין לשמאל.

הקלט הוא ה-dict ש-`GET /api/dashboards/{id}/view` מחזיר
(`dashboards.multi_entity.build_dashboard_view`): `liquidity`, `cash_statement`,
ולדשבורד רב-ישותי גם `entities[]` ו-`combined`. הפונקציות כאן טהורות: אין
מסד נתונים, אין רשת, אין קריאה לספק. כך אפשר לבדוק אותן בלי DB.

כללים:
* honest-null — ערך לא ידוע (`None`) מודפס "לא ידוע", לעולם לא 0. ו-0.0 אמיתי
  (למשל "מינוס בעו״ש" כשהיתרה חיובית) מודפס "0.00".
* כל מספר מוצג ליד תאריך "נכון ל־" כשהמודל נושא אחד.
* סכום חלקי מסומן כחלקי; תחזית מסומנת כקירוב ללא מע״מ, בטבלה נפרדת.
* מודל-התצוגה נבנה במודול אחר שמשתנה במקביל — כל גישה כאן היא `.get()`,
  ומפתח חסר נקרא כ"לא ידוע".

עברית ב-reportlab: אין כאן ספריית bidi. כל תא נעטף לשורות בסדר הלוגי, ואז כל
שורה מומרת לסדר חזותי (`visual`): רצפי עברית מתהפכים, רצפי ספרות/לטינית
נשארים משמאל לימין. הגופן הוא DejaVu Sans שמגיע עם matplotlib (תלות פרוד
קיימת); בלעדיו הדוח נכשל במפורש ולא מדפיס ריבועים.
"""
from __future__ import annotations

import io
import os
import re
from datetime import date, datetime
from typing import Any, Iterable
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo

UNKNOWN = "לא ידוע"
REPORT_TITLE = "דוח מצב מזומנים"
FONT = "RezefHebrew"
FONT_BOLD = "RezefHebrew-Bold"
_FONTS_REGISTERED = False

ACCOUNT_KINDS = {
    "checking": "עו״ש",
    "card": "כרטיס אשראי",
    "loan": "הלוואה",
    "credit_line_mirror": "חשבון מסגרת",
    "other": "אחר",
}
EVENT_KINDS = {
    "check": "צ׳ק דחוי",
    "loan_maturity": "סיום הלוואה",
    "facility_expiry": "תום תוקף מסגרת",
    "event": "אירוע",
}
LIMIT_SOURCES = {
    "accounts.credit_limit": "חשבון הבנק",
    "plan.liquidityEvidence": "ראיה מתועדת בתוכנית",
}
NO_AMOUNT_NOTE = "הסכום לא מתועד"


class ReportFontMissing(RuntimeError):
    """אין גופן עם אותיות עבריות — עדיף כישלון גלוי על PDF של ריבועים."""


# ------------------------------------------------------------------ bidi


_MIRROR = str.maketrans("()[]{}<>", ")(][}{><")
_SHEKEL_AMOUNT = re.compile(r"\d[\d,.]* ?₪|₪ ?-?\d")


def _strong(ch: str) -> str:
    if "֐" <= ch <= "׿" or "יִ" <= ch <= "ﭏ":
        return "R"
    if ch.isdigit() or (ch.isascii() and ch.isalpha()):
        return "L"
    return "N"


def _classes(text: str) -> list[str]:
    classes = [_strong(ch) for ch in text]
    # A sign glued to a number belongs to the number: "-500" stays "-500".
    for i, ch in enumerate(text):
        if ch in "-+" and i + 1 < len(text) and text[i + 1].isdigit():
            classes[i] = "L"
        if ch == "%" and i > 0 and text[i - 1].isdigit():
            classes[i] = "L"
    # A shekel sign next to a number travels with it, as in the Unicode
    # algorithm: "50,000 ₪" stays one left-to-right run.
    for match in _SHEKEL_AMOUNT.finditer(text):
        for k in range(match.start(), match.end()):
            classes[k] = "L"
    # Neutrals between two LTR runs join them ("1,234.00", "26/10/2026");
    # anything else follows the paragraph direction, which is RTL.
    i = 0
    while i < len(classes):
        if classes[i] != "N":
            i += 1
            continue
        j = i
        while j < len(classes) and classes[j] == "N":
            j += 1
        before = classes[i - 1] if i > 0 else "R"
        after = classes[j] if j < len(classes) else "R"
        fill = "L" if before == "L" and after == "L" else "R"
        for k in range(i, j):
            classes[k] = fill
        i = j
    return classes


def visual(text: str) -> str:
    """סדר לוגי → סדר חזותי לשורה אחת בפסקה מימין לשמאל.

    שורה בלי אות עברית (מספר, תאריך) חוזרת כמות שהיא."""
    if not text or not any(_strong(ch) == "R" for ch in text):
        return text
    classes = _classes(text)
    runs: list[tuple[str, str]] = []
    for ch, cls in zip(text, classes):
        if runs and runs[-1][0] == cls:
            runs[-1] = (cls, runs[-1][1] + ch)
        else:
            runs.append((cls, ch))
    out = []
    for cls, chunk in reversed(runs):
        out.append(chunk[::-1].translate(_MIRROR) if cls == "R" else chunk)
    return "".join(out)


# ------------------------------------------------------------------ formatting


def _num(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def fmt_amount(value: Any) -> str:
    number = _num(value)
    if number is None:
        return UNKNOWN
    text = f"{number:,.2f}"
    return "0.00" if text == "-0.00" else text


def fmt_date(value: Any) -> str:
    if value is None or value == "":
        return UNKNOWN
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, date):
        return value.strftime("%d/%m/%Y")
    text = str(value)[:10]
    try:
        return date.fromisoformat(text).strftime("%d/%m/%Y")
    except ValueError:
        return UNKNOWN


def fmt_month(value: Any) -> str:
    text = str(value or "")
    if len(text) >= 7 and text[4] == "-":
        return f"{text[5:7]}/{text[:4]}"
    return text or UNKNOWN


def _text(value: Any, default: str = "") -> str:
    return default if value is None else str(value)


def _dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list:
    return value if isinstance(value, list) else []


# ------------------------------------------------------------------ sections


def _entities(view: dict, title: str) -> list[dict]:
    """[(label, liquidity)] per entity. The top-level view is the primary
    entity's view, so a primary section without its own view reads it."""
    sections = [s for s in _list(view.get("entities")) if isinstance(s, dict)]
    if not sections:
        return [{"label": title, "liquidity": _dict(view.get("liquidity"))}]
    out = []
    for section in sections:
        liquidity = _dict(_dict(section.get("view")).get("liquidity"))
        if not liquidity and (section.get("role") == "primary" or len(sections) == 1):
            liquidity = _dict(view.get("liquidity"))
        out.append({"label": _text(section.get("label"), title), "liquidity": liquidity})
    return out


def _balances(entities: list[dict], combined: dict | None) -> dict:
    rows, notes = [], []
    for entity in entities:
        position = _dict(entity["liquidity"].get("position"))
        rows.append([
            entity["label"],
            fmt_amount(position.get("balance")),
            fmt_date(position.get("as_of")),
            fmt_amount(position.get("limit")),
            LIMIT_SOURCES.get(position.get("limit_source"), "—") if position.get("limit") is not None else "—",
            fmt_amount(position.get("available_to_limit")),
        ])
    if combined is not None:
        rows.append([
            "מאוחד",
            fmt_amount(combined.get("balance")),
            fmt_date(combined.get("as_of")),
            fmt_amount(combined.get("limit")),
            "—",
            fmt_amount(combined.get("available_to_limit")),
        ])
        if combined.get("balance") is None and _num(combined.get("balance_known")) is not None:
            notes.append(
                f"יתרה מאוחדת חלקית (רק ישויות שהיתרה שלהן ידועה): {fmt_amount(combined.get('balance_known'))}. "
                + _text(combined.get("balance_note"))
            )
        if combined.get("limit") is None and _num(combined.get("limit_known")) is not None:
            notes.append(f"מסגרת מאוחדת חלקית (רק ישויות שהמסגרת שלהן ידועה): {fmt_amount(combined.get('limit_known'))}.")
        notes.append("תאריך היתרה המאוחדת הוא המוקדם מבין תאריכי הישויות.")
    notes.append("מרווח עד המסגרת = מסגרת האשראי ועוד יתרת העו״ש. בלי יתרה או מסגרת ידועה — לא ידוע.")
    return {
        "key": "balances",
        "heading": "יתרות ומסגרות אשראי",
        "columns": ["ישות", "יתרת עו״ש", "נכון ל־", "מסגרת אשראי", "מקור המסגרת", "מרווח עד המסגרת"],
        "widths": [0.22, 0.15, 0.13, 0.15, 0.18, 0.17],
        "rows": rows,
        "notes": notes,
    }


def _accounts(entities: list[dict]) -> dict:
    rows = []
    for entity in entities:
        for account in _list(entity["liquidity"].get("accounts")):
            if not isinstance(account, dict):
                continue
            rows.append([
                entity["label"],
                _text(account.get("name") or account.get("display_label"), UNKNOWN),
                ACCOUNT_KINDS.get(account.get("kind"), "אחר"),
                fmt_amount(account.get("balance")),
                fmt_amount(account.get("credit_limit")) if account.get("credit_limit") is not None else "—",
                fmt_date(account.get("as_of")),
            ])
    notes = [] if rows else ["אין חשבונות בנק מחוברים או מתועדים לדשבורד."]
    notes.append("חשבון \"מסגרת\" משקף את המינוס בעו״ש ואינו נספר שוב בחובות.")
    return {
        "key": "accounts",
        "heading": "חשבונות",
        "columns": ["ישות", "חשבון", "סוג", "יתרה", "מסגרת", "נכון ל־"],
        "widths": [0.18, 0.24, 0.13, 0.16, 0.15, 0.14],
        "rows": rows,
        "notes": notes,
    }


def _known_total(items: Iterable[Any]) -> float | None:
    known = [_num(item) for item in items]
    known = [value for value in known if value is not None]
    return round(sum(known), 2) if known else None


def _debts(entities: list[dict], combined: dict | None) -> dict:
    if combined is not None:
        source = combined
        items = [(_text(d.get("entity"), ""), d) for d in _list(combined.get("debts")) if isinstance(d, dict)]
    else:
        entity = entities[0]
        source = entity["liquidity"]
        items = [(entity["label"], d) for d in _list(source.get("debts")) if isinstance(d, dict)]
    rows = [
        [label, _text(debt.get("label"), UNKNOWN), fmt_amount(debt.get("amount")),
         fmt_date(debt.get("as_of")), _text(debt.get("note"))]
        for label, debt in items
    ]
    total = source.get("debts_known_total") if "debts_known_total" in source else _known_total(
        d.get("amount") for _l, d in items
    )
    complete = source.get("debts_complete")
    if complete is None:
        complete = bool(items) and all(_num(d.get("amount")) is not None for _l, d in items)
    rows.append(["", "סה״כ ידוע", fmt_amount(total), "", "חלקי" if not complete else ""])
    notes = []
    if not complete:
        notes.append("הסכום חלקי: לחלק מהחובות אין סכום ידוע (מסומנים \"לא ידוע\"), והם אינם בסיכום.")
    return {
        "key": "debts",
        "heading": "חובות והלוואות ידועים",
        "columns": ["ישות", "פריט", "סכום", "נכון ל־", "הערה"],
        "widths": [0.17, 0.27, 0.16, 0.14, 0.26],
        "rows": rows,
        "notes": notes,
    }


def _upcoming(entities: list[dict], combined: dict | None) -> dict:
    if combined is not None:
        items = [(_text(e.get("entity"), ""), e) for e in _list(combined.get("upcoming")) if isinstance(e, dict)]
    else:
        entity = entities[0]
        items = [(entity["label"], e) for e in _list(entity["liquidity"].get("upcoming")) if isinstance(e, dict)]
    items.sort(key=lambda pair: str(pair[1].get("date") or ""))
    rows = []
    for label, event in items:
        note = _text(event.get("note"))
        if not note and _num(event.get("amount")) is None:
            note = NO_AMOUNT_NOTE
        rows.append([
            fmt_date(event.get("date")),
            label,
            EVENT_KINDS.get(event.get("kind"), "אירוע"),
            _text(event.get("label"), UNKNOWN),
            fmt_amount(event.get("amount")),
            note,
        ])
    notes = [] if rows else ["אין אירועים מתוארכים מתועדים בטווח."]
    notes.append("צ׳קים דחויים, סיום הלוואות ותום תוקף מסגרות — כפי שתועדו בתוכנית הדשבורד. סכום שלילי = יציאה.")
    return {
        "key": "upcoming",
        "heading": "אירועים צפויים",
        "columns": ["תאריך", "ישות", "סוג", "אירוע", "סכום", "הערה"],
        "widths": [0.12, 0.13, 0.13, 0.22, 0.13, 0.27],
        "rows": rows,
        "notes": notes,
    }


_CASH_COLUMNS = (
    ("operating_in", "כניסות תפעוליות"),
    ("operating_out", "יציאות תפעוליות"),
    ("finance", "מימון שוטף"),
    ("financing", "מימון"),
    ("internal", "פנימי ומסים"),
    ("net", "נטו"),
)


def _cash_statement(statement: dict) -> dict:
    months = [m for m in _list(statement.get("months")) if m]
    totals = _dict(statement.get("totals"))
    rows = []
    for month in months:
        rows.append([fmt_month(month)] + [
            fmt_amount(_dict(totals.get(key)).get(month)) for key, _label in _CASH_COLUMNS
        ])
    notes = [] if rows else ["אין נתוני תזרים בפועל לתקופה."]
    for key in ("message", "scope_note", "netting_note"):
        if statement.get(key):
            notes.append(str(statement[key]))
    return {
        "key": "cash_statement",
        "heading": "תזרים מזומנים חודשי — ביצוע",
        "columns": ["חודש"] + [label for _key, label in _CASH_COLUMNS],
        "widths": [0.1, 0.15, 0.15, 0.14, 0.14, 0.15, 0.17],
        "rows": rows,
        "notes": notes,
    }


def _forecast(statement: dict) -> dict | None:
    forecast = _dict(statement.get("forecast"))
    months = [m for m in _list(forecast.get("months")) if m]
    if not months:
        return None
    rows_by = _dict(forecast.get("rows"))
    rows = [
        [fmt_month(month)] + [
            fmt_amount(_dict(rows_by.get(key)).get(month))
            for key in ("operating_in", "operating_out", "financing", "net")
        ]
        for month in months
    ]
    notes = [str(forecast["note"])] if forecast.get("note") else []
    notes.append("תחזית אינה נתון בפועל ואינה מצטרפת לביצוע.")
    return {
        "key": "forecast",
        "heading": "תחזית — ללא מע״מ, קירוב",
        "columns": ["חודש", "כניסות", "יציאות", "החזרי קרן", "נטו"],
        "widths": [0.16, 0.21, 0.21, 0.21, 0.21],
        "rows": rows,
        "notes": notes,
    }


def report_sections(view: dict, *, title: str, generated_on: date) -> list[dict]:
    """תוכן הדוח בסדר לוגי (מחרוזות), לפני עימוד. כאן נבדקים honest-null
    והתאריכים; `render_cash_position_pdf` רק מעמד את זה."""
    view = _dict(view)
    entities = _entities(view, title)
    combined_view = _dict(view.get("combined")) if len(entities) > 1 else {}
    combined_liquidity = _dict(combined_view.get("liquidity")) if combined_view else None
    if combined_view and combined_view.get("cash_statement") is not None:
        statement = _dict(combined_view.get("cash_statement"))
    else:
        statement = _dict(view.get("cash_statement"))
    sections = [
        _balances(entities, combined_liquidity),
        _accounts(entities),
        _debts(entities, combined_liquidity),
        _upcoming(entities, combined_liquidity),
        _cash_statement(statement),
    ]
    forecast = _forecast(statement)
    if forecast is not None:
        sections.append(forecast)
    return sections


# ------------------------------------------------------------------ PDF


def hebrew_font_paths() -> tuple[str, str] | None:
    """DejaVu Sans (regular, bold) מתוך matplotlib — תלות פרוד קיימת."""
    try:
        import matplotlib
    except ImportError:
        return None
    folder = os.path.join(matplotlib.get_data_path(), "fonts", "ttf")
    regular = os.path.join(folder, "DejaVuSans.ttf")
    bold = os.path.join(folder, "DejaVuSans-Bold.ttf")
    if not os.path.isfile(regular):
        return None
    return regular, bold if os.path.isfile(bold) else regular


def _register_fonts() -> None:
    global _FONTS_REGISTERED
    if _FONTS_REGISTERED:
        return
    paths = hebrew_font_paths()
    if paths is None:
        raise ReportFontMissing("לא נמצא גופן עברי (DejaVu Sans) — הדוח לא הופק")
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    pdfmetrics.registerFont(TTFont(FONT, paths[0]))
    pdfmetrics.registerFont(TTFont(FONT_BOLD, paths[1]))
    _FONTS_REGISTERED = True


def _wrap(text: str, font: str, size: float, width: float) -> list[str]:
    """עטיפה בסדר הלוגי — לפני ההיפוך, אחרת שורות עברית נקראות מלמטה למעלה."""
    from reportlab.pdfbase.pdfmetrics import stringWidth

    lines: list[str] = []
    for paragraph in str(text).split("\n"):
        current = ""
        for word in paragraph.split(" "):
            candidate = word if not current else f"{current} {word}"
            if stringWidth(candidate, font, size) <= width:
                current = candidate
                continue
            if current:
                lines.append(current)
            current = ""
            while word and stringWidth(word, font, size) > width:
                cut = len(word)
                while cut > 1 and stringWidth(word[:cut], font, size) > width:
                    cut -= 1
                lines.append(word[:cut])
                word = word[cut:]
            current = word
        lines.append(current)
    return lines


def _cell(text: str, font: str, size: float, width: float) -> str:
    return "\n".join(visual(line) for line in _wrap(text, font, size, width))


def render_cash_position_pdf(view: dict, *, title: str, generated_on: date | None = None) -> bytes:
    """PDF (A4, עברית מימין לשמאל) ממודל-התצוגה. טהור: בלי DB ובלי רשת."""
    _register_fonts()
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_RIGHT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    generated_on = generated_on or datetime.now(ZoneInfo("Asia/Jerusalem")).date()
    title = _text(title).strip() or "דשבורד"
    margin = 36
    page_width = A4[0] - 2 * margin
    heading_style = ParagraphStyle("h", fontName=FONT_BOLD, fontSize=12, leading=16, alignment=TA_RIGHT,
                                   spaceBefore=10, spaceAfter=4)
    title_style = ParagraphStyle("t", parent=heading_style, fontSize=16, leading=21, spaceBefore=0)
    note_style = ParagraphStyle("n", fontName=FONT, fontSize=8, leading=11, alignment=TA_RIGHT,
                                textColor=colors.HexColor("#444444"))

    def para(text: str, style: ParagraphStyle) -> Paragraph:
        lines = _wrap(text, style.fontName, style.fontSize, page_width - 4)
        return Paragraph("<br/>".join(escape(visual(line)) for line in lines), style)

    story = [
        para(f"{REPORT_TITLE} — {title}", title_style),
        para(f"הופק: {fmt_date(generated_on)}. כל סכום בש״ח, ליד התאריך שבו הוא ידוע.", note_style),
        para("מקור: נתונים שכבר שמורים ברצף. הדוח לא פנה ל-SUMIT, ל-Open Finance או לבנק. "
             "ערך שאינו ידוע מודפס \"לא ידוע\" ולא 0.", note_style),
    ]
    size = 8
    padding = 4
    for section in report_sections(view, title=title, generated_on=generated_on):
        story.append(para(section["heading"], heading_style))
        widths = [fraction * page_width for fraction in section["widths"]]
        header = [_cell(name, FONT_BOLD, size, w - 2 * padding) for name, w in zip(section["columns"], widths)]
        body = [
            [_cell(cell, FONT, size, w - 2 * padding) for cell, w in zip(row, widths)]
            for row in section["rows"]
        ]
        if not body:
            body = [["—"] * len(widths)]
        # RTL: the first logical column sits on the right.
        data = [list(reversed(row)) for row in [header] + body]
        table = Table(data, colWidths=list(reversed(widths)), repeatRows=1)
        table.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, -1), FONT),
            ("FONTNAME", (0, 0), (-1, 0), FONT_BOLD),
            ("FONTSIZE", (0, 0), (-1, -1), size),
            ("LEADING", (0, 0), (-1, -1), size + 2),
            ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E8EEF4")),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#9AA5B1")),
            ("LEFTPADDING", (0, 0), (-1, -1), padding),
            ("RIGHTPADDING", (0, 0), (-1, -1), padding),
        ]))
        story.append(table)
        for note in section["notes"]:
            story.append(Spacer(1, 2))
            story.append(para(note, note_style))

    buffer = io.BytesIO()
    document = SimpleDocTemplate(
        buffer, pagesize=A4, leftMargin=margin, rightMargin=margin, topMargin=margin, bottomMargin=margin,
        title=f"{REPORT_TITLE} — {title}", author="רצף — מושקו",
    )
    document.build(story)
    return buffer.getvalue()
