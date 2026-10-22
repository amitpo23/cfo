"""P1 gaps of the Rezef port of the Eliav tool (SPEC §10): the Food Group SUMIT
journal in the P&L (G-27), the explicit intercompany netting rule (G-26), the
source-freshness table (G-22), cash flow by line × month (G-21), the liquidity
evidence form (G-11) and pizza revenue from Z reports (G-20). No provider calls."""
from datetime import date
from decimal import Decimal

from cfo.database import SessionLocal
from cfo.models import JournalEntry
from cfo.services.dashboards import source_journal
from tests.test_dashboard_eliav_ui_fixes import _bank, _consolidated, _save


def _journal(db, org_id, day, lines, *, memo="", external_id=None):
    row = JournalEntry(
        organization_id=org_id, source=source_journal.SOURCE, entry_date=day, memo=memo,
        external_id=external_id or f"journal:{org_id}:{day.isoformat()}:{len(lines)}:{memo}",
        lines=[{"account": code, "debit": str(debit), "credit": str(credit)} for code, debit, credit in lines],
        raw_data={"reporting_status": "source_chart_unmapped", "provider_calls": 0},
    )
    db.add(row)
    db.flush()
    return row


def _view(client, headers, dashboard_id, start, end):
    response = client.get(f"/api/dashboards/{dashboard_id}/view", headers=headers,
                          params={"start": start, "end": end})
    assert response.status_code == 200, response.text
    return response.json()


def _month(pnl, key):
    return next(month for month in pnl["months"] if month["month"] == key)


def _line(month, row_id):
    return next(line for line in month["lines"] if line["id"] == row_id)


# ------------------------------------------ G-27. Food Group journal in the P&L

def _food_with_journal(client, platform_admin, fresh_org, slug):
    dashboard_id, chef, food = _consolidated(client, platform_admin, fresh_org, slug)
    with SessionLocal() as db:
        _bank(db, chef["org_id"], date(2026, 8, 5), 23600, "הפקדת מזומן")
        _bank(db, food["org_id"], date(2026, 8, 5), 11800, "הפקדת מזומן")
        _bank(db, food["org_id"], date(2026, 8, 12), -5900, "הו\"ק ספק מזון")
        _bank(db, food["org_id"], date(2026, 8, 20), -20, "עמלת פעולה")
        _bank(db, food["org_id"], date(2026, 8, 25), -1000, "בזק")
        # Supplier invoices (P&L code against the supplier), a fee against the bank,
        # and the payment of a supplier (balance sheet only: skipped).
        _journal(db, food["org_id"], date(2026, 8, 3), [("90003", 3000, 0), ("50001", 0, 3000)], memo="מזון")
        _journal(db, food["org_id"], date(2026, 8, 9), [("90004", 1000, 0), ("50002", 0, 1000)], memo="משקאות")
        _journal(db, food["org_id"], date(2026, 8, 20), [("99001", 25, 0), ("10001", 0, 25)], memo="עמלה")
        _journal(db, food["org_id"], date(2026, 8, 12), [("50001", 5900, 0), ("10001", 0, 5900)], memo="תשלום")
        # A month without bank rows: the journal has no revenue, so the month stays unknown.
        _journal(db, food["org_id"], date(2026, 7, 10), [("99002", 300, 0)], memo="ריבית")
        db.commit()
    return dashboard_id, chef, food


def test_food_group_journal_replaces_the_bank_rows_it_covers(client, fresh_org, platform_admin):
    dashboard_id, chef, food = _food_with_journal(client, platform_admin, fresh_org, "p1-journal")
    view = _view(client, platform_admin["headers"], dashboard_id, "2026-07-01", "2026-08-31")
    pnl = view["entities"][1]["view"]["pnl"]
    august = _month(pnl, "2026-08")
    assert august["source"] == "cash_basis"
    assert "יומן SUMIT" in august["source_label"]
    # Suppliers: the bank's 5,900 / 1.18 = 5,000 is dropped, the journal's 3,000 + 1,000 is used.
    assert _line(august, "suppliers") == {**_line(august, "suppliers"), "amount": 4000.0, "source": "journal"}
    # Bank fees: 20 from the bank dropped, 25 from the journal.
    assert _line(august, "bank_fees")["amount"] == 25.0
    # Rows the journal does not cover stay on the bank: revenue 11,800 / 1.18, overhead 1,000 / 1.18.
    assert _line(august, "revenue") == {**_line(august, "revenue"), "amount": 10000.0, "source": "bank"}
    assert _line(august, "overhead")["amount"] == round(1000 / 1.18, 2)
    assert august["costs"] == round(4000 + 25 + 1000 / 1.18, 2)
    assert august["journal_dedupe"]["bank_dropped"] == 5020.0
    assert august["journal_dedupe"]["journal_used"] == 4025.0
    assert august["journal"]["balance_only"] == 1 and august["journal"]["entries"] == 4
    july = _month(pnl, "2026-07")
    assert july["source"] is None and july["revenue"] is None
    assert july["journal"]["lines"] == [{"code": "99002", "label": "ריבית", "row": "interest", "amount": 300.0}]
    assert july["journal"]["unbalanced"] == 1

    # The consolidated P&L and budget vs actual carry Food Group's journal costs.
    combined = view["combined"]
    assert combined["pnl"]["total_expenses"] == round(pnl["total_expenses"] + view["entities"][0]["view"]["pnl"]["total_expenses"], 2)
    bva = next(m for m in combined["budget_vs_actual"]["months"] if m["month"] == "2026-08")
    suppliers = next(line for line in bva["categories"] if line["category"] == "suppliers")
    assert suppliers["actual"] == 4000.0
    assert view["provider_calls"] == 0


def test_journal_account_map_in_the_plan_overrides_the_draft(client, fresh_org, platform_admin):
    dashboard_id, chef, food = _food_with_journal(client, platform_admin, fresh_org, "p1-journal-map")
    _save(client, platform_admin["headers"], dashboard_id, {"journalAccountMap": {"90004": None, "99001": "overhead"}})
    view = _view(client, platform_admin["headers"], dashboard_id, "2026-08-01", "2026-08-31")
    august = _month(view["entities"][1]["view"]["pnl"], "2026-08")
    assert _line(august, "suppliers")["amount"] == 3000.0
    # The fee now sits on overhead, which the journal then covers: the bank's בזק row is dropped.
    assert _line(august, "overhead")["amount"] == 25.0
    assert _line(august, "bank_fees") == {**_line(august, "bank_fees"), "amount": 20.0, "source": "bank"}


def test_journal_account_map_is_validated(client, fresh_org, platform_admin):
    dashboard_id, chef, food = _consolidated(client, platform_admin, fresh_org, "p1-journal-bad")
    current = client.get(f"/api/dashboards/{dashboard_id}/plan", headers=platform_admin["headers"]).json()
    for bad in ({"90003": "no_such_row"}, {"bad code!": "suppliers"}, ["90003"]):
        response = client.put(f"/api/dashboards/{dashboard_id}/plan",
                              headers={**platform_admin["headers"], "If-Match": current["version"] or "null"},
                              json={"payload": {"journalAccountMap": bad}})
        assert response.status_code == 422, bad


def test_journal_of_other_sources_and_books_months_is_not_read(fresh_org):
    org = fresh_org()
    with SessionLocal() as db:
        db.add(JournalEntry(organization_id=org["org_id"], source="manual", entry_date=date(2026, 8, 3),
                            external_id="m-1", lines=[{"account": "90003", "debit": "50", "credit": "0"}]))
        db.commit()
        assert source_journal.journal_months(db, org["org_id"], date(2026, 8, 1), date(2026, 8, 31)) == {}
    bank = {"lines": [{"id": "suppliers", "label": "ספקים", "side": "cost", "amount": 10.0}],
            "revenue": 0.0, "costs": 10.0}
    assert source_journal.merge_into_cash_month(bank, None) is bank
    assert source_journal.default_line("10001") is None and source_journal.default_line("50001") is None
    assert source_journal.default_line("90512") == ("overhead", "אחזקה, הקמה ותפעול")
    assert Decimal("0") == source_journal._amount("not a number")
