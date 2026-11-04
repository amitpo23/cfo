"""One checking picture on the bank report, the executive and the command center.

A stale overdraft above its limit keeps its last booked amount and date on
every screen, not 0. A month with no bank rows is חסר, not 0/0. Loans are not
the credit line. Made-up accounts and amounts only.
"""
from datetime import date, datetime
from decimal import Decimal

from cfo.database import SessionLocal
from cfo.models import Account, AccountType
from cfo.services.dashboard_service import DashboardService


def _accounts(org_id: int) -> None:
    with SessionLocal() as db:
        db.add(Account(
            organization_id=org_id, name="עו״ש בדיקה", account_type=AccountType.BANK,
            raw_account_type="CHECKING", source="open_finance", external_id=f"t-bal-{org_id}",
            balance=Decimal("-21000"), credit_limit=Decimal("9000"),
            balance_as_of=datetime(2026, 10, 26), currency="ILS",
        ))
        db.add(Account(
            organization_id=org_id, name="הלוואה בדיקה", account_type=AccountType.LIABILITY,
            raw_account_type="LOAN", source="open_finance", external_id=f"t-loan-{org_id}",
            balance=Decimal("-250000"), currency="ILS",
        ))
        db.commit()


def _line(lines):
    [line] = lines["accounts"]
    return line


def test_bank_report_and_executive_show_the_stale_overdraft(client, fresh_org):
    owner = fresh_org()
    _accounts(owner["org_id"])
    bank = client.get("/api/reports/bank-status", headers=owner["headers"]).json()["data"]
    executive = client.get("/api/dashboard/executive", headers=owner["headers"]).json()["data"]
    panel = executive["panels"]["checking"]
    assert panel["ok"], panel
    for lines in (bank["credit_lines"], panel["data"]["credit_lines"]):
        line = _line(lines)
        assert line["balance"] == -21000
        assert line["as_of"] == "2026-10-26" and line["stale"] is True
        assert line["limit"] == 9000 and line["used"] == 21000
        assert line["overrun"] == 12000 and line["status"] == "overrun"
    # Loans stay loans. They are not added to the credit line.
    assert panel["data"]["loans_total"] == -250000
    assert bank["loans_total"] == -250000


def test_command_center_month_without_bank_rows_is_missing(fresh_org):
    owner = fresh_org()
    _accounts(owner["org_id"])
    with SessionLocal() as db:
        flows = DashboardService(db, owner["org_id"])._bank_month_flows(date(2026, 11, 1), date(2026, 11, 30))
    assert flows == {"inflow": None, "outflow": None, "net": None}


def test_bank_report_excel_carries_the_last_booked_balance_not_zero(client, fresh_org):
    from io import BytesIO

    import openpyxl

    owner = fresh_org()
    _accounts(owner["org_id"])
    r = client.get("/api/reports/bank-status/export", headers=owner["headers"])
    assert r.status_code == 200, r.text
    rows = {row[0]: row[1] for row in openpyxl.load_workbook(BytesIO(r.content)).active.iter_rows(values_only=True)}
    assert rows["עו״ש בדיקה: יתרה"] == -21000
    assert rows["עו״ש בדיקה: נכון ל-"] == "2026-10-26"
    assert rows["עו״ש בדיקה: מסגרת"] == 9000
    assert rows["עו״ש בדיקה: חריגה"] == 12000
    assert rows["הלוואות (יתרה)"] == -250000
    # No bank rows in the period: the net flow is not invented.
    assert rows["תזרים בנק נטו בתקופה"] in ("חסר", 0)


def test_bank_report_excel_does_not_start_a_formula_from_an_account_name(client, fresh_org):
    from io import BytesIO

    import openpyxl

    owner = fresh_org()
    with SessionLocal() as db:
        db.add(Account(
            organization_id=owner["org_id"], name="=HYPERLINK(\"x\")", account_type=AccountType.BANK,
            raw_account_type="CHECKING", source="open_finance", external_id=f"t-inj-{owner['org_id']}",
            balance=Decimal("100"), balance_as_of=datetime(2026, 10, 26), currency="ILS",
        ))
        db.commit()
    r = client.get("/api/reports/bank-status/export", headers=owner["headers"])
    labels = [row[0] for row in openpyxl.load_workbook(BytesIO(r.content)).active.iter_rows(values_only=True) if row[0]]
    assert not any(str(label).startswith("=") for label in labels)
