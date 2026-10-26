"""דוח PDF של מצב המזומנים מתוך מודל-התצוגה של דשבורד — פונקציה טהורה.

honest-null: ערך לא ידוע מודפס "לא ידוע", לעולם לא 0; ו-0.0 אמיתי מודפס
"0.00". כל מספר מוצג עם תאריך "נכון ל־" כשהמודל נושא אחד. אין כאן מסד
נתונים: הקלט הוא dict בצורת `GET /api/dashboards/{id}/view`.
"""
from __future__ import annotations

from datetime import date

import pypdfium2 as pdfium
import pytest

from cfo.services import cash_position_pdf as report
from cfo.services.cash_position_pdf import UNKNOWN, report_sections, render_cash_position_pdf, visual


# ------------------------------------------------------------------ fixtures


def _liquidity(balance, as_of, limit, *, limit_source="accounts.credit_limit", debts=None,
               upcoming=None, accounts=None, debts_complete=True, debts_known_total=None):
    return {
        "status": "ready",
        "position": {
            "balance": balance, "as_of": as_of, "balance_source": "accounts",
            "limit": limit, "limit_source": limit_source,
            "available_to_limit": None if balance is None or limit is None else limit + balance,
        },
        "accounts": accounts or [],
        "debts": debts or [],
        "debts_known_total": debts_known_total,
        "debts_complete": debts_complete,
        "upcoming": upcoming or [],
        "message": "יתרות מ-Open Finance כפי שנשמרו ברצף.",
    }


def _cash_statement(months, net, *, operating_in=None, forecast=None, scope_note=None):
    totals = {key: {m: None for m in months} for key in
              ("operating_in", "operating_out", "finance", "financing", "internal", "net")}
    totals["net"] = dict(net)
    if operating_in:
        totals["operating_in"] = dict(operating_in)
    return {
        "status": "ready", "months": months, "totals": totals, "lines": [],
        "forecast": forecast, "message": "ביצוע: תנועות בנק BOOKED מתויקות.",
        "scope_note": scope_note,
    }


def single_entity_view():
    liquidity = _liquidity(
        12345.67, "2026-10-20", 50000.0,
        accounts=[
            {"name": "עו״ש לאומי", "kind": "checking", "balance": 12345.67,
             "credit_limit": 50000.0, "as_of": "2026-10-20"},
            {"name": "ויזה", "kind": "card", "balance": None, "credit_limit": None, "as_of": None},
        ],
        debts=[
            {"label": "מינוס בעו״ש", "amount": 0.0, "as_of": "2026-10-20"},
            {"label": "הלוואה — רכב", "amount": 80000.0, "as_of": "2026-10-01"},
        ],
        debts_known_total=80000.0,
        upcoming=[
            {"date": "2026-11-05", "label": "צ׳ק 1234 · ספק בע״מ", "amount": -3000.0, "kind": "check"},
            {"date": "2027-03-31", "label": "מסגרת בנק", "kind": "facility_expiry", "amount": None,
             "reference_amount": 50000.0, "note": "תוקף מסגרת של 50,000 ₪ מסתיים; אין תשלום מתועד"},
        ],
    )
    return {
        "status": "ready",
        "liquidity": liquidity,
        "cash_statement": _cash_statement(
            ["2026-09", "2026-10"], {"2026-09": -1500.5, "2026-10": None},
            operating_in={"2026-09": 20000.0, "2026-10": None},
            forecast={"status": "ready", "months": ["2026-11"],
                      "rows": {"operating_in": {"2026-11": 21000.0}, "operating_out": {"2026-11": -18000.0},
                               "financing": {"2026-11": None}, "net": {"2026-11": 3000.0}},
                      "note": "תחזית: תקציב אם יש, אחרת מגמה. ללא מע״מ — קירוב, לא מצטרף לביצוע."},
        ),
        "entities": [{"label": "שף בע״מ", "role": "primary", "view": None}],
    }


def multi_entity_view():
    chef = _liquidity(-20000.0, "2026-10-20", 100000.0,
                      debts=[{"label": "מינוס בעו״ש", "amount": 20000.0, "as_of": "2026-10-20"}],
                      debts_known_total=20000.0)
    food = _liquidity(None, None, None, limit_source=None,
                      debts=[{"label": "מינוס בעו״ש", "amount": None, "as_of": None}],
                      debts_complete=False)
    combined_liquidity = {
        "balance": None, "balance_known": -20000.0,
        "balance_note": "יתרת העו״ש של פוד אינה ידועה, ולכן אין יתרה מאוחדת.",
        "as_of": "2026-10-20", "limit": None, "limit_known": 100000.0, "available_to_limit": None,
        "debts": [
            {"label": "מינוס בעו״ש", "amount": 20000.0, "as_of": "2026-10-20", "entity": "שף"},
            {"label": "מינוס בעו״ש", "amount": None, "as_of": None, "entity": "פוד"},
        ],
        "debts_known_total": 20000.0, "debts_complete": False,
        "upcoming": [
            {"date": "2026-12-01", "label": "הלוואה · סיום הלוואה", "kind": "loan_maturity",
             "amount": -45000.0, "amount_as_of": "2026-10-01", "entity": "פוד",
             "note": "יתרת ההלוואה נכון ל־2026-10-01; לוח הסילוקין לא מתועד"},
        ],
    }
    return {
        "status": "ready",
        "liquidity": chef,
        "entities": [
            {"label": "שף", "role": "primary", "view": {"liquidity": chef}},
            {"label": "פוד", "role": "entity", "view": {"liquidity": food}},
        ],
        "combined": {
            "liquidity": combined_liquidity,
            "cash_statement": _cash_statement(
                ["2026-10"], {"2026-10": 500.0},
                scope_note="חודש שמסומן \"בלבד\" הוא סכום הישויות שיש להן תנועות בנק.",
            ),
        },
    }


def _section(sections, key):
    found = [s for s in sections if s["key"] == key]
    assert found, f"section {key} missing: {[s['key'] for s in sections]}"
    return found[0]


def _col(section, name):
    return section["columns"].index(name)


# ------------------------------------------------------------------ visual order


def test_visual_reverses_pure_hebrew():
    assert visual("לא ידוע") == "עודי אל"


def test_visual_keeps_numbers_and_dates_left_to_right():
    assert visual("-1,234.00") == "-1,234.00"
    assert visual("26/10/2026") == "26/10/2026"


def test_visual_keeps_a_number_inside_hebrew_as_one_ltr_run():
    # "צ׳ק 1234 · ספק" read right-to-left: the number stays 1234, not 4321.
    assert visual("צ׳ק 1234 · ספק") == "קפס · 1234 ק׳צ"


def test_visual_keeps_a_negative_number_inside_hebrew_signed():
    assert visual("סכום -500") == "-500 םוכס"


def test_visual_keeps_a_shekel_sign_with_its_number():
    assert visual("מסגרת של 50,000 ₪") == "50,000 ₪ לש תרגסמ"


def test_visual_mirrors_brackets_inside_hebrew():
    assert visual("(הערה)") == "(הרעה)"


# ------------------------------------------------------------------ formatting


def test_unknown_amount_is_never_zero():
    assert report.fmt_amount(None) == UNKNOWN
    assert report.fmt_amount(0.0) == "0.00"
    assert report.fmt_amount(-1234.5) == "-1,234.50"
    assert report.fmt_amount("garbage") == UNKNOWN


def test_dates_print_as_day_month_year_and_unknown_when_missing():
    assert report.fmt_date("2026-10-20") == "20/10/2026"
    assert report.fmt_date("2026-10-20T08:00:00") == "20/10/2026"
    assert report.fmt_date(None) == UNKNOWN
    assert report.fmt_month("2026-09") == "09/2026"


# ------------------------------------------------------------------ sections


def test_balances_show_amount_with_its_as_of_date_and_credit_headroom():
    sections = report_sections(single_entity_view(), title="שף בע״מ", generated_on=date(2026, 10, 26))
    balances = _section(sections, "balances")
    row = balances["rows"][0]
    assert row[_col(balances, "ישות")] == "שף בע״מ"
    assert row[_col(balances, "יתרת עו״ש")] == "12,345.67"
    assert row[_col(balances, "נכון ל־")] == "20/10/2026"
    assert row[_col(balances, "מסגרת אשראי")] == "50,000.00"
    assert row[_col(balances, "מרווח עד המסגרת")] == "62,345.67"


def test_unknown_balance_prints_unknown_not_zero():
    view = single_entity_view()
    view["liquidity"]["position"].update(balance=None, as_of=None, available_to_limit=None)
    balances = _section(report_sections(view, title="x", generated_on=date(2026, 10, 26)), "balances")
    row = balances["rows"][0]
    assert row[_col(balances, "יתרת עו״ש")] == UNKNOWN
    assert row[_col(balances, "נכון ל־")] == UNKNOWN
    assert row[_col(balances, "מרווח עד המסגרת")] == UNKNOWN


def test_accounts_list_each_balance_with_its_date():
    accounts = _section(report_sections(single_entity_view(), title="x", generated_on=date(2026, 10, 26)),
                        "accounts")
    by_name = {row[_col(accounts, "חשבון")]: row for row in accounts["rows"]}
    assert by_name["עו״ש לאומי"][_col(accounts, "יתרה")] == "12,345.67"
    assert by_name["עו״ש לאומי"][_col(accounts, "נכון ל־")] == "20/10/2026"
    assert by_name["ויזה"][_col(accounts, "יתרה")] == UNKNOWN
    assert by_name["ויזה"][_col(accounts, "סוג")] == "כרטיס אשראי"


def test_debts_keep_a_real_zero_and_show_the_known_total():
    debts = _section(report_sections(single_entity_view(), title="x", generated_on=date(2026, 10, 26)), "debts")
    by_label = {row[_col(debts, "פריט")]: row for row in debts["rows"]}
    assert by_label["מינוס בעו״ש"][_col(debts, "סכום")] == "0.00"
    assert by_label["הלוואה — רכב"][_col(debts, "סכום")] == "80,000.00"
    assert by_label["הלוואה — רכב"][_col(debts, "נכון ל־")] == "01/10/2026"
    assert by_label["סה״כ ידוע"][_col(debts, "סכום")] == "80,000.00"


def test_incomplete_debts_are_labelled_partial():
    debts = _section(report_sections(multi_entity_view(), title="x", generated_on=date(2026, 10, 26)), "debts")
    amounts = [row[_col(debts, "סכום")] for row in debts["rows"]]
    assert UNKNOWN in amounts
    assert any("חלקי" in note for note in debts["notes"])


def test_upcoming_events_are_dated_and_unknown_amounts_stay_unknown():
    events = _section(report_sections(single_entity_view(), title="x", generated_on=date(2026, 10, 26)),
                      "upcoming")
    dates = [row[_col(events, "תאריך")] for row in events["rows"]]
    assert dates == ["05/11/2026", "31/03/2027"]
    check, facility = events["rows"]
    assert check[_col(events, "סוג")] == "צ׳ק דחוי"
    assert check[_col(events, "סכום")] == "-3,000.00"
    assert facility[_col(events, "סוג")] == "תום תוקף מסגרת"
    assert facility[_col(events, "סכום")] == UNKNOWN
    assert "50,000" in facility[_col(events, "הערה")]


def test_cash_statement_totals_per_month_with_unknown_months():
    cash = _section(report_sections(single_entity_view(), title="x", generated_on=date(2026, 10, 26)),
                    "cash_statement")
    by_month = {row[_col(cash, "חודש")]: row for row in cash["rows"]}
    assert by_month["09/2026"][_col(cash, "נטו")] == "-1,500.50"
    assert by_month["09/2026"][_col(cash, "כניסות תפעוליות")] == "20,000.00"
    assert by_month["10/2026"][_col(cash, "נטו")] == UNKNOWN


def test_forecast_is_a_separate_table_labelled_as_approximation():
    sections = report_sections(single_entity_view(), title="x", generated_on=date(2026, 10, 26))
    forecast = _section(sections, "forecast")
    assert "קירוב" in forecast["heading"] or any("קירוב" in n for n in forecast["notes"])
    row = forecast["rows"][0]
    assert row[_col(forecast, "חודש")] == "11/2026"
    assert row[_col(forecast, "נטו")] == "3,000.00"
    assert row[_col(forecast, "החזרי קרן")] == UNKNOWN


def test_multi_entity_view_has_a_row_per_entity_and_an_honest_combined_row():
    balances = _section(report_sections(multi_entity_view(), title="קבוצה", generated_on=date(2026, 10, 26)),
                        "balances")
    by_entity = {row[_col(balances, "ישות")]: row for row in balances["rows"]}
    assert by_entity["שף"][_col(balances, "יתרת עו״ש")] == "-20,000.00"
    assert by_entity["פוד"][_col(balances, "יתרת עו״ש")] == UNKNOWN
    assert by_entity["מאוחד"][_col(balances, "יתרת עו״ש")] == UNKNOWN
    note = " ".join(balances["notes"])
    assert "-20,000.00" in note and "חלקי" in note


def test_multi_entity_upcoming_and_cash_statement_come_from_combined():
    sections = report_sections(multi_entity_view(), title="קבוצה", generated_on=date(2026, 10, 26))
    events = _section(sections, "upcoming")
    row = events["rows"][0]
    assert row[_col(events, "ישות")] == "פוד"
    assert row[_col(events, "סוג")] == "סיום הלוואה"
    assert row[_col(events, "סכום")] == "-45,000.00"
    cash = _section(sections, "cash_statement")
    assert cash["rows"][0][_col(cash, "נטו")] == "500.00"
    assert any("בלבד" in note for note in cash["notes"])


def test_an_empty_view_renders_unknowns_without_inventing_numbers():
    sections = report_sections({}, title="ריק", generated_on=date(2026, 10, 26))
    balances = _section(sections, "balances")
    assert balances["rows"][0][_col(balances, "יתרת עו״ש")] == UNKNOWN
    for section in sections:
        for row in section["rows"]:
            for cell in row:
                assert cell != "0.00", (section["key"], row)


# ------------------------------------------------------------------ PDF bytes


def _pdf_text(pdf: bytes) -> str:
    document = pdfium.PdfDocument(pdf)
    try:
        return "\n".join(
            document[i].get_textpage().get_text_range() for i in range(len(document))
        )
    finally:
        document.close()


def test_render_returns_a_pdf_with_embedded_hebrew_font_and_visual_text():
    pdf = render_cash_position_pdf(single_entity_view(), title="שף בע״מ", generated_on=date(2026, 10, 26))
    assert pdf.startswith(b"%PDF")
    text = _pdf_text(pdf)
    assert "12,345.67" in text
    assert "20/10/2026" in text
    # pdfium's extractor runs its own bidi over the drawn (visual) glyphs and
    # hands back logical order — so finding the logical Hebrew here is a
    # round-trip check that the visual ordering was right.
    assert UNKNOWN in text
    assert "דוח מצב מזומנים" in text
    assert "צ׳ק 1234 · ספק בע״מ" in text


def test_render_multi_entity_and_empty_views_do_not_crash():
    assert render_cash_position_pdf(multi_entity_view(), title="קבוצה",
                                    generated_on=date(2026, 10, 26)).startswith(b"%PDF")
    assert render_cash_position_pdf({}, title="ריק", generated_on=date(2026, 10, 26)).startswith(b"%PDF")


def test_missing_hebrew_font_fails_loudly_instead_of_printing_boxes(monkeypatch):
    monkeypatch.setattr(report, "hebrew_font_paths", lambda: None)
    monkeypatch.setattr(report, "_FONTS_REGISTERED", False)
    with pytest.raises(report.ReportFontMissing):
        render_cash_position_pdf(single_entity_view(), title="x", generated_on=date(2026, 10, 26))
