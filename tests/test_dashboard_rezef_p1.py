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


# ------------------------------------------------ G-26. intercompany netting rule

def _ic_dashboard(client, platform_admin, fresh_org, slug):
    from tests.test_dashboard_eliav_ui_fixes import _account
    dashboard_id, chef, food = _consolidated(client, platform_admin, fresh_org, slug)
    with SessionLocal() as db:
        chef_main = _account(db, chef["org_id"], "עו״ש 8954", 0).id
        chef_other = _account(db, chef["org_id"], "עו״ש אחר", 0).id
        food_main = _account(db, food["org_id"], "Imported bank 1662", None, source="reviewed_local_import").id
        # 1. Food Group pays the chef 5,000 on 30.8; the chef receives it on 2.9 (3 days): netted.
        _bank(db, food["org_id"], date(2026, 8, 30), -5000, "העברה לשף", account_id=food_main)
        _bank(db, chef["org_id"], date(2026, 9, 2), 5000, "העברה מבנק הפועלים", account_id=chef_main)
        # 2. Same amount, 6 days apart: outside the window.
        _bank(db, food["org_id"], date(2026, 9, 10), -2000, "העברה לשף", account_id=food_main)
        _bank(db, chef["org_id"], date(2026, 9, 16), 2000, "העברה", account_id=chef_main)
        # 3. A cash sale of the chef equal to a Food Group transfer: a sale is not netted.
        _bank(db, food["org_id"], date(2026, 9, 20), -1180, "העברה לספק", account_id=food_main)
        _bank(db, chef["org_id"], date(2026, 9, 20), 1180, "הפקדת מזומן", account_id=chef_main)
        # 4. Two inflows equal to one outflow: the closer one is taken, once.
        _bank(db, food["org_id"], date(2026, 9, 24), -700, "העברה לשף", account_id=food_main)
        _bank(db, chef["org_id"], date(2026, 9, 21), 700, "העברה", account_id=chef_other)
        _bank(db, chef["org_id"], date(2026, 9, 25), 700, "העברה", account_id=chef_main)
        db.commit()
    return dashboard_id, chef, food, chef_main


def test_intercompany_rule_amount_window_category_and_one_use(client, fresh_org, platform_admin):
    dashboard_id, chef, food, chef_main = _ic_dashboard(client, platform_admin, fresh_org, "p1-ic")
    view = _view(client, platform_admin["headers"], dashboard_id, "2026-08-01", "2026-09-30")
    removed = view["combined"]["intercompany_removed"]
    assert removed["pairs"] == 2 and removed["amount"] == 5700.0
    assert removed["window_days"] == 4 and "4 ימים" in removed["rule"]
    chef_label = view["entities"][0]["label"]
    assert [(item["from"], item["to"], item["amount"], item["days_apart"]) for item in removed["items"]] == [
        ("פוד גרופ", chef_label, 5000.0, 3), ("פוד גרופ", chef_label, 700.0, 1),
    ]
    assert removed["items"][1]["in_date"] == "2026-09-25"
    # Each side leaves its own month.
    combined = {m["month"]: m for m in view["combined"]["cashflow"]["months"]}
    entity = [{m["month"]: m for m in section["view"]["cashflow"]["months"]} for section in view["entities"]]
    assert combined["2026-08"]["outflows"] == round(entity[1]["2026-08"]["outflows"] - 5000, 2)
    assert combined["2026-09"]["inflows"] == round(
        entity[0]["2026-09"]["inflows"] + entity[1].get("2026-09", {"inflows": 0})["inflows"] - 5700, 2)


def test_intercompany_window_and_accounts_come_from_the_plan(client, fresh_org, platform_admin):
    dashboard_id, chef, food, chef_main = _ic_dashboard(client, platform_admin, fresh_org, "p1-ic-plan")
    _save(client, platform_admin["headers"], dashboard_id, {"intercompany": {"windowDays": 6, "accountIds": [chef_main]}})
    view = _view(client, platform_admin["headers"], dashboard_id, "2026-08-01", "2026-09-30")
    removed = view["combined"]["intercompany_removed"]
    # 6 days: the 2,000 pair is netted. Only the chef's main account: the 700 on 25.9.
    assert sorted(item["amount"] for item in removed["items"]) == [700.0, 2000.0, 5000.0]
    assert removed["items"][-1]["in_date"] == "2026-09-25"
    current = client.get(f"/api/dashboards/{dashboard_id}/plan", headers=platform_admin["headers"]).json()
    for bad in ({"windowDays": 30}, {"accountIds": ["35"]}, {"other": 1}, {"windowDays": True}):
        response = client.put(f"/api/dashboards/{dashboard_id}/plan",
                              headers={**platform_admin["headers"], "If-Match": current["version"]},
                              json={"payload": {"intercompany": bad}})
        assert response.status_code == 422, bad


# --------------------------------------------------- G-22. sources and freshness

def test_sources_table_per_account_with_last_dates_counts_and_stale_flag(client, fresh_org, platform_admin):
    from datetime import datetime, timedelta
    from cfo.models import IntegrationConnection, Invoice
    from cfo.services.dashboards import freshness
    from tests.test_dashboard_eliav_ui_fixes import _account
    dashboard_id, chef, food = _consolidated(client, platform_admin, fresh_org, "p1-sources")
    today = date.today()
    with SessionLocal() as db:
        live = _account(db, chef["org_id"], "עו״ש 8954", 0).id
        imported = _account(db, food["org_id"], "Imported bank 1662", None, source="reviewed_local_import").id
        for days in (3, 1):
            row = _bank(db, chef["org_id"], today - timedelta(days=days), 10, "הפקדת מזומן", account_id=live)
            row.source, row.external_id, row.raw_data = "open_finance", f"of-{days}", {"status": "BOOKED"}
        db.add(IntegrationConnection(organization_id=chef["org_id"], source="open_finance", status="active",
                                     last_synced_at=datetime.utcnow() - timedelta(days=5)))
        row = _bank(db, food["org_id"], today - timedelta(days=20), -5, "עמלה", account_id=imported)
        row.source, row.external_id = "reviewed_local_import", "bank:1662:1"
        db.add(Invoice(organization_id=chef["org_id"], invoice_number="A1", issue_date=today - timedelta(days=2),
                       subtotal=Decimal("100"), tax=Decimal("18"), total=Decimal("118"), source="sumit"))
        _journal(db, food["org_id"], today - timedelta(days=3), [("90003", 1, 0)], memo="x")
        db.commit()
        chef_sources = freshness.build_freshness(db, chef["org_id"], today=today)
    bank = next(item for item in chef_sources["items"] if item["kind"] == "bank")
    # A live feed is judged by its last successful sync (5 days > 2): stale, though the data is 1 day old.
    assert (bank["label"], bank["rows"], bank["last_date"], bank["status"], bank["age_days"]) == (
        "עו״ש 8954", 2, (today - timedelta(days=1)).isoformat(), "stale", 5)
    invoices = next(item for item in chef_sources["items"] if item["kind"] == "invoices")
    # SUMIT without any sync time: stale, never fresh by default.
    assert invoices["rows"] == 1 and invoices["status"] == "stale" and invoices["last_sync"] is None

    view = _view(client, platform_admin["headers"], dashboard_id, (today - timedelta(days=60)).isoformat(), today.isoformat())
    food_sources = view["entities"][1]["view"]["sources"]["items"]
    food_bank = next(item for item in food_sources if item["kind"] == "bank")
    # An imported source is judged by its last row: 20 days > 14.
    assert food_bank["status"] == "stale" and food_bank["age_days"] == 20 and food_bank["last_sync"] is not None
    journal = next(item for item in food_sources if item["kind"] == "journal")
    assert journal["status"] == "fresh" and journal["source"] == "reviewed_local_import"
    combined = view["combined"]["sources"]
    assert {item["entity"] for item in combined["items"]} == {view["entities"][0]["label"], "פוד גרופ"}
    assert combined["stale_count"] == 3
    assert freshness.redact_public(view["combined"]["sources"])["items"][0].get("account_id") is None


def test_sources_of_an_organization_without_rows_are_unknown(fresh_org):
    from cfo.services.dashboards import freshness
    org = fresh_org()
    with SessionLocal() as db:
        section = freshness.build_freshness(db, org["org_id"], today=date(2026, 10, 22))
    assert section["status"] == "unknown" and section["items"] == [] and section["provider_calls"] == 0


# ------------------------------------------- G-21. cash flow by line × month

def test_cash_statement_by_line_and_month_with_forecast(client, fresh_org, platform_admin):
    dashboard_id, chef, food, chef_main = _ic_dashboard(client, platform_admin, fresh_org, "p1-cash-statement")
    with SessionLocal() as db:
        _bank(db, chef["org_id"], date(2026, 8, 3), 11800, "הפקדת מזומן")
        _bank(db, chef["org_id"], date(2026, 8, 7), -40, "עמלת פעולה")
        _bank(db, chef["org_id"], date(2026, 9, 7), -2000, "פרעון הלוואה")
        db.commit()
    view = _view(client, platform_admin["headers"], dashboard_id, "2026-08-01", "2026-09-30")
    chef_statement = view["entities"][0]["view"]["cash_statement"]
    assert chef_statement["months"] == ["2026-08", "2026-09"] and chef_statement["status"] == "ready"
    lines = {line["id"]: line for line in chef_statement["lines"]}
    assert lines["sales_cash"]["group"] == "operating_in"
    assert lines["sales_cash"]["values"] == {"2026-08": 11800.0, "2026-09": 1180.0}
    assert lines["bank_fees"]["group"] == "finance" and lines["bank_fees"]["values"]["2026-08"] == -40.0
    assert lines["loans_out"]["group"] == "financing" and lines["loans_out"]["values"]["2026-09"] == -2000.0
    totals = chef_statement["totals"]
    assert totals["after_finance"]["2026-08"] == round(totals["operating"]["2026-08"] - 40, 2)
    # The statement's net is the entity's cash flow net, month by month.
    for month in view["entities"][0]["view"]["cashflow"]["months"]:
        assert totals["net"][month["month"]] == month["net_flow"]
    assert chef_statement["forecast"]["months"] == view["entities"][0]["view"]["forecast"]["months"]
    assert "ללא מע״מ" in chef_statement["forecast"]["note"]

    combined = view["combined"]["cash_statement"]
    lines = {line["id"]: line for line in combined["lines"]}
    # The 5,000 pair crosses the month: August's outflow and September's inflow leave the statement.
    # The 700 pair is inside September. Each side is its own line, so neither shows as 0.
    assert lines["intercompany_netting_in"]["values"] == {"2026-08": 0.0, "2026-09": -5700.0}  # 5,000 + 700
    assert lines["intercompany_netting_out"]["values"] == {"2026-08": 5000.0, "2026-09": 700.0}
    assert lines["intercompany_netting_in"]["total"] == -5700.0 and lines["intercompany_netting_out"]["total"] == 5700.0
    assert "intercompany_netting" not in lines
    assert view["combined"]["intercompany_removed"]["by_month"] == {
        "2026-08": {"inflows": 0.0, "outflows": 5000.0}, "2026-09": {"inflows": 5700.0, "outflows": 700.0},
    }
    for month in view["combined"]["cashflow"]["months"]:
        assert combined["totals"]["net"][month["month"]] == month["net_flow"], month["month"]
    assert combined["forecast"]["months"] == view["combined"]["forecast"]["months"]


def _section(label, values):
    """One entity's cash statement: a single transfer line, every month known."""
    months = sorted(values)
    return {"label": label, "view": {"cash_statement": {
        "months": months,
        "lines": [{"id": "intercompany", "label": "בין-חברתי", "group": "internal", "review": False,
                   "values": dict(values), "total": sum(values.values())}],
        "totals": {"net": dict(values)},
    }}}


def test_netting_inside_one_month_is_shown_on_both_lines_not_as_zero():
    from cfo.services.dashboards import cash_statement
    # The chef sends 30,000 to Food Group on 3.8; Food Group receives it on 4.8: both sides in August.
    sections = [_section("שף", {"2026-08": -30000.0}), _section("פוד גרופ", {"2026-08": 30000.0})]
    netted = {"2026-08": {"inflows": 30000.0, "outflows": 30000.0}}
    statement = cash_statement.combine(sections, None, netted)
    lines = {line["id"]: line for line in statement["lines"]}
    assert lines["intercompany_netting_in"]["values"] == {"2026-08": -30000.0}
    assert lines["intercompany_netting_out"]["values"] == {"2026-08": 30000.0}
    # The net is unchanged: the two sides cancel, as the transfers themselves do.
    assert statement["totals"]["net"] == {"2026-08": 0.0}
    assert "כבר הוסרו" in statement["netting_note"]


def test_cash_statement_month_without_bank_rows_is_unknown(fresh_org):
    from cfo.services.dashboards import cash_statement, filing
    rows = [(filing.Txn(1, 1, 1, "2026-08-03", 100.0, "הפקדת מזומן"), filing.Filed("sales_cash", "rule", "sales_cash"))]
    section = cash_statement.build_cash_statement(rows, date(2026, 7, 1), date(2026, 8, 31))
    assert section["lines"][0]["values"] == {"2026-07": None, "2026-08": 100.0}
    assert section["totals"]["net"] == {"2026-07": None, "2026-08": 100.0}
    assert cash_statement.build_cash_statement([], date(2026, 7, 1), date(2026, 7, 31))["status"] == "unknown"


# -------------------------------------------- G-11. liquidity evidence form

def test_only_the_owner_may_change_liquidity_evidence(client, fresh_org, platform_admin):
    from tests.test_dashboard_eliav_ui_r2 import _member, _put
    dashboard_id, chef, food = _consolidated(client, platform_admin, fresh_org, "p1-evidence")
    accountant = fresh_org()
    _member(dashboard_id, accountant["org_id"], "accountant")
    evidence = {"liquidityEvidence": {
        "openingBalances": [{"organizationId": food["org_id"], "date": "2026-07-31", "amount": -30000, "source": "דף בנק"}],
        "facilities": [{"organizationId": food["org_id"], "label": "מסגרת 1662", "limit": 80000, "validTo": "2026-12-31"}],
    }, "statusParameters": {"scenario": "בסיס"}}
    denied = _put(client, accountant["headers"], dashboard_id,
                  {"liquidityEvidence": {"facilities": evidence["liquidityEvidence"]["facilities"]}})
    assert denied.status_code == 403 and denied.json()["error"]["code"] == "liquidity_evidence_forbidden"
    assert _put(client, platform_admin["headers"], dashboard_id, evidence).status_code == 200
    # The owner's form adds a check and keeps the opening balance and the other keys.
    added = dict(evidence["liquidityEvidence"])
    added["checks"] = [{"organizationId": food["org_id"], "check": "10005", "date": "2026-11-05", "amount": 2500,
                        "payee": None, "source": "צילום צ׳ק", "note": None}]
    saved = _put(client, platform_admin["headers"], dashboard_id, {**evidence, "liquidityEvidence": added})
    assert saved.status_code == 200, saved.text
    stored = saved.json()["payload"]
    assert stored["liquidityEvidence"]["openingBalances"] == evidence["liquidityEvidence"]["openingBalances"]
    assert stored["statusParameters"] == {"scenario": "בסיס"}
    # The accountant may still save other parts with the evidence unchanged.
    kept = _put(client, accountant["headers"], dashboard_id, {**stored, "statusParameters": {"scenario": "שמרני"}})
    assert kept.status_code == 200, kept.text
    deleted = dict(stored["liquidityEvidence"], checks=[])
    assert _put(client, accountant["headers"], dashboard_id, {**stored, "liquidityEvidence": deleted}).status_code == 403
    view = _view(client, platform_admin["headers"], dashboard_id, "2026-10-01", "2026-10-31")
    assert any(item.get("check") == "10005" for item in view["entities"][1]["view"]["liquidity"]["checks"])


# ------------------------------------------------ G-20. pizza revenue from Z reports

def test_z_report_replaces_the_bank_till_takings_in_the_revenue(client, fresh_org, platform_admin):
    dashboard_id, chef, food = _consolidated(client, platform_admin, fresh_org, "p1-z")
    with SessionLocal() as db:
        _bank(db, food["org_id"], date(2026, 8, 5), 11800, "הפקדת מזומן")
        _bank(db, food["org_id"], date(2026, 8, 6), 23600, "סליקה ויזה")
        _bank(db, food["org_id"], date(2026, 8, 7), 1180, "הפקדת שיק")
        _bank(db, food["org_id"], date(2026, 8, 9), -1180, "בזק")
        _bank(db, food["org_id"], date(2026, 9, 5), 5900, "הפקדת מזומן")
        _bank(db, chef["org_id"], date(2026, 8, 5), 2360, "הפקדת מזומן")
        db.commit()
    _save(client, platform_admin["headers"], dashboard_id, {"zReports": [
        {"organizationId": food["org_id"], "month": "2026-08", "revenueExVat": 52126.2,
         "totalInclVat": 61509, "cashNet": 21658, "cardNet": 39851, "source": "דוח Z אוגוסט"},
        {"organizationId": food["org_id"], "month": "2026-07", "revenueExVat": 76510.82, "source": "דוח Z יולי"},
    ]})
    view = _view(client, platform_admin["headers"], dashboard_id, "2026-07-01", "2026-09-30")
    pnl = view["entities"][1]["view"]["pnl"]
    august = _month(pnl, "2026-08")
    # 52,126.20 from Z + the check 1,180 / 1.18; the bank's 11,800 + 23,600 till takings are dropped.
    assert _line(august, "revenue")["amount"] == round(52126.2 + 1000, 2)
    assert _line(august, "revenue")["source"] == "z_report"
    assert august["revenue"] == round(52126.2 + 1000, 2) and august["costs"] == 1000.0
    assert august["z_dedupe"]["bank_till_dropped"] == 30000.0
    assert "דוח Z" in august["source_label"]
    assert august["z_report"]["total_incl_vat"] == 61509
    # September has no Z report: the bank stays. July has no bank rows: unknown, the Z is still listed.
    assert _month(pnl, "2026-09")["revenue"] == 5000.0 and _month(pnl, "2026-09")["z_report"] is None
    july = _month(pnl, "2026-07")
    assert july["source"] is None and july["z_report"]["revenue_ex_vat"] == 76510.82
    # The chef's months do not read Food Group's Z reports.
    assert all(month["z_report"] is None for month in view["entities"][0]["view"]["pnl"]["months"])
    assert view["combined"]["pnl"]["total_revenue"] == round(
        pnl["total_revenue"] + view["entities"][0]["view"]["pnl"]["total_revenue"], 2)


def test_z_reports_are_validated_and_owner_only(client, fresh_org, platform_admin):
    from tests.test_dashboard_eliav_ui_r2 import _member, _put
    dashboard_id, chef, food = _consolidated(client, platform_admin, fresh_org, "p1-z-role")
    accountant = fresh_org()
    _member(dashboard_id, accountant["org_id"], "accountant")
    good = {"organizationId": food["org_id"], "month": "2026-08", "revenueExVat": 100.0, "source": "Z"}
    for bad in ([{**good, "month": "2026-13"}], [{**good, "revenueExVat": -1}], [{**good, "source": ""}],
                [good, good], [{**good, "extra": 1}], [{**good, "organizationId": None}]):
        assert _put(client, platform_admin["headers"], dashboard_id, {"zReports": bad}).status_code == 422, bad
    denied = _put(client, accountant["headers"], dashboard_id, {"zReports": [good]})
    assert denied.status_code == 403 and denied.json()["error"]["code"] == "z_reports_forbidden"
    assert _put(client, platform_admin["headers"], dashboard_id, {"zReports": [good]}).status_code == 200


def test_import_script_reads_the_tool_file_and_merges_months(client, fresh_org, platform_admin, tmp_path, capsys):
    import importlib.util
    import json
    from pathlib import Path
    from cfo.models import User
    repo = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("import_z_reports", repo / "scripts" / "import_z_reports.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    dashboard_id, chef, food = _consolidated(client, platform_admin, fresh_org, "p1-z-import")
    _save(client, platform_admin["headers"], dashboard_id, {
        "zReports": [{"organizationId": food["org_id"], "month": "2026-06", "revenueExVat": 1.0, "source": "ידני"},
                     {"organizationId": food["org_id"], "month": "2026-08", "revenueExVat": 2.0, "source": "ידני"}],
        "statusParameters": {"scenario": "בסיס"},
    })
    document = {"pizza_z": [
        {"month": "2026-07", "revenue_ex_vat": 76510.82, "total_net_vat_included": 90283, "cash_net": 44745, "card_net": 45538},
        {"month": "2026-08", "revenue_ex_vat": 52126.2, "total_net_vat_included": 61509, "cash_net": 21658, "card_net": 39851},
    ]}
    path = tmp_path / "reviewed-evidence.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    with SessionLocal() as db:
        user_id = db.query(User).filter(User.email == "platform@example.com").one().id
    args = ["--dashboard-id", str(dashboard_id), "--organization-id", str(food["org_id"]), "--user-id", str(user_id),
            "--file", str(path), "--source", "דוחות Z מאומתים"]
    assert module.main(args) == 0
    assert "לא נכתב דבר" in capsys.readouterr().out
    before = client.get(f"/api/dashboards/{dashboard_id}/plan", headers=platform_admin["headers"]).json()["payload"]
    assert [item["month"] for item in before["zReports"]] == ["2026-06", "2026-08"]
    assert module.main([*args, "--apply"]) == 0
    after = client.get(f"/api/dashboards/{dashboard_id}/plan", headers=platform_admin["headers"]).json()["payload"]
    assert [(item["month"], item["revenueExVat"]) for item in after["zReports"]] == [
        ("2026-06", 1.0), ("2026-07", 76510.82), ("2026-08", 52126.2)]
    assert after["statusParameters"] == {"scenario": "בסיס"}
    assert module.main([*args, "--apply"]) == 0
    assert "אין שינויים" in capsys.readouterr().out
