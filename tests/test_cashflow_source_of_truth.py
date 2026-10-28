"""One cash-flow source of truth for every organization. No provider calls.

The numbers below are fixtures for the rules. They are not a customer's balances.
"""
from datetime import date

from cfo.database import SessionLocal
from cfo.services.dashboards import cashflow_truth as truth
from cfo.services.dashboards import forecast_rules
from cfo.services.dashboards.service import DashboardError, validate_filing_payload
from cfo.services.dashboards.view_model import build_view

AS_OF = date(2026, 10, 28)
FORBIDDEN = ("פוד גרופ", "אליאב", "Food Group", "food group", "49700", "61000", "41000")


def test_defaults_are_the_owner_rules_and_an_org_can_override_them():
    settings = truth.resolve_settings(None, organization_id=99)

    assert settings.payroll_day == 10
    assert settings.terms() == {"type": "eom_plus_days", "days": 30}
    assert settings.saturday_cash == "next_sunday"
    assert settings.opening_accounts == "checking_only"
    assert settings.credit_facility == "separate_headroom"
    assert settings.shared_costs == "unallocated_row"
    assert settings.cheque_discount == "short_loan_closes_on_maturity"
    assert settings.loss_cap is None
    assert settings.funding_source is None

    plan = {"cashflowSettings": {
        "payroll_day": 10,
        "organizations": {"99": {"payroll_day": 12, "loss_cap": 1000, "funding_source": "מסגרת"}},
        "suppliers": {"s1": {"type": "fixed_day_of_month", "day_of_month": 15}},
    }}
    overridden = truth.resolve_settings(plan, 99)

    assert overridden.payroll_day == 12
    assert overridden.loss_cap == 1000
    assert overridden.funding_source == "מסגרת"
    assert truth.terms_for(overridden, "s1")["type"] == "fixed_day_of_month"
    assert truth.resolve_settings(plan, 100).payroll_day == 10


def test_saturday_cash_moves_to_the_next_sunday_once():
    saturday = date(2026, 10, 31)

    assert saturday.weekday() == 5
    assert truth.roll_saturday(saturday) == date(2026, 11, 1)
    assert truth.roll_saturday(date(2026, 10, 30)) == date(2026, 10, 30)

    report = truth.scaffold(as_of=AS_OF, checks=[{
        "check": "1", "date": "2026-10-31", "amount": 50, "discounted": True, "status": "unverified",
    }])
    legs = [event for event in report["events"] if event.get("offsets")]

    assert {event["date"] for event in legs} == {"2026-11-01"}
    assert len(legs) == 2
    assert sum(event["amount"] for event in legs) == 0
    assert all(event["line_key"] == "financing" for event in legs)
    assert all(event["is_financing"] for event in legs)
    october = next(week for week in report["weeks"] if week["week_start"] == "2026-10-25")
    assert all(event["date"] != "2026-10-31" for event in report["events"])
    assert october["week_end"] == "2026-10-30"


def test_supplier_due_is_end_of_month_plus_30_unless_the_supplier_overrides_it():
    assert truth.supplier_due(date(2026, 9, 3), None) == date(2026, 10, 30)
    assert truth.supplier_due(date(2026, 9, 30), None) == date(2026, 10, 30)
    assert truth.supplier_due(date(2026, 1, 15), {"type": "eom_plus_days", "days": 30}) == date(2026, 3, 2)
    assert truth.supplier_due(date(2026, 2, 10), {"type": "eom_plus_days", "days": 30}) == date(2026, 3, 30)
    assert truth.supplier_due(date(2026, 9, 1), {"type": "fixed_day_of_month", "day_of_month": 10}) == date(2026, 10, 10)
    assert truth.supplier_due(date(2026, 9, 1), {"type": "other_text", "free_text": "כל חמישי"}) is None

    settings = truth.resolve_settings({"cashflowSettings": {"suppliers": {
        "s1": {"type": "days_from_invoice", "days": 7},
    }}})
    assert truth.supplier_due(date(2026, 9, 1), truth.terms_for(settings, "s1")) == date(2026, 9, 8)
    assert truth.supplier_due(date(2026, 9, 1), truth.terms_for(settings, "other")) == date(2026, 10, 30)


def test_payroll_uses_the_org_day_and_leaves_saturday():
    assert truth.payroll_date(2026, 11, 10) == date(2026, 11, 10)
    assert date(2026, 10, 10).weekday() == 5
    assert truth.payroll_date(2026, 10, 10) == date(2026, 10, 11)

    plan = {"budgetLines": [], "payroll": [{"id": "crew", "label": "צוות", "monthly": 100}],
            "cashflowSettings": {"payroll_day": 12}}
    items, _unknown = forecast_rules.supplier_and_payroll(plan, [], date(2026, 11, 1), date(2026, 11, 30))
    payroll = next(item for item in items if "שכר" in item["label"])

    assert payroll["date"] == date(2026, 11, 12)


def test_opening_is_checking_only_and_the_facility_is_headroom():
    position = truth.liquidity_position(
        balance=-100, limit=10000, balance_date=date(2026, 10, 28), report_date=AS_OF,
        settings=truth.CashflowSettings(),
    )

    assert position["balance"] == -100
    assert position["limit"] == 10000
    assert position["headroom"] == 9900
    assert position["state"] == "בתוך המסגרת"
    assert position["headroom"] == position["balance"] + position["limit"]
    near = truth.liquidity_position(
        balance=-100, limit=1000, balance_date=date(2026, 10, 28), report_date=AS_OF,
        settings=truth.CashflowSettings(),
    )
    assert near["headroom"] == 900
    assert near["state"] == "קרוב למסגרת"

    unknown = truth.liquidity_position(
        balance=None, limit=1000, balance_date=None, report_date=AS_OF, settings=truth.CashflowSettings(),
    )
    assert unknown["state"] == "לא ידוע"
    assert unknown["headroom"] is None
    stale = truth.liquidity_position(
        balance=-100, limit=1000, balance_date=date(2026, 10, 20), report_date=AS_OF,
        settings=truth.CashflowSettings(),
    )
    assert stale["stale"] is True
    assert stale["stale_label"] == "יתרה ישנה"


def test_a_past_cheque_is_not_open():
    past = truth.cheque_verification(when=date(2026, 10, 1), today=AS_OF, state="not_found")
    future = truth.cheque_verification(when=date(2026, 11, 17), today=AS_OF, state="future")

    assert past["status"] == "past_maturity_unknown"
    assert past["label"] == "מועד שחלף ומצב לא ידוע"
    assert past["counts_as_open"] is False
    assert past["status"] != "open"
    assert "פתוח" not in past["label"]
    assert future["certainty"] == "סביר"
    assert future["counts_as_open"] is False


def test_duplicate_check_blocks_a_document_counted_twice_and_a_matched_provision():
    document = {
        "id": "d1", "kind": "AP", "supplier_id": "s", "supplier_name": "ספק",
        "doc_ref": "100", "doc_date": "2026-09-15", "gross": 1000, "paid_gross": None,
        "matched_bank_txn_id": "t1",
    }
    twin = dict(document, id="d2")
    short = [{"id": "t1", "booking_date": "2026-10-20", "amount": -400, "status": "BOOKED",
              "counterparty": "ספק", "description": "100", "match_state": "confirmed"}]
    blocked = truth.detect_duplicates([document, twin], short)

    assert blocked["blocks_publish"] is True
    assert {item["code"] for item in blocked["violations"]} >= {"duplicate_document_key", "provision_on_fully_matched"}

    partial = dict(document, matched_bank_txn_id=None, payments=[{"txn_id": "t1", "amount": 400, "match_state": "confirmed"}])
    kept = truth.detect_duplicates([partial], short)
    assert kept["blocks_publish"] is False
    assert kept["provisions"][0]["amount"] == 600

    candidate_only = dict(document, matched_bank_txn_id=None, paid_gross=None)
    bank_candidate = [dict(short[0], amount=-1000, match_state="candidate")]
    still_open = truth.detect_duplicates([candidate_only], bank_candidate)
    assert still_open["provisions"][0]["amount"] == 1000
    assert still_open["candidates"]

    unloaded = truth.detect_duplicates(None, None)
    assert unloaded["status"] == "missing"
    assert unloaded["blocks_publish"] is False
    assert "0" not in unloaded["label"]


def test_a_card_charge_and_the_same_purchase_cannot_both_be_forecast():
    document = {
        "id": "d1", "kind": "AP", "supplier_id": "s", "supplier_name": "חנות",
        "doc_ref": "9", "doc_date": "2026-10-01", "gross": 200, "card_purchase": True,
    }
    bank = [{"id": "b1", "booking_date": "2026-10-02", "amount": -200, "status": "BOOKED",
             "counterparty": "חנות", "description": "9", "is_card_charge": True}]
    lines = [
        {"line_key": "suppliers_provision", "layer": 2, "source_id": "doc:d1", "amount": -200},
        {"line_key": "cards", "layer": 1, "source_id": "bank:b1", "amount": -200},
    ]

    assert truth.detect_duplicates([document], bank, lines)["blocks_publish"] is True
    assert truth.detect_duplicates([document], bank, [lines[1]])["blocks_publish"] is False


def test_remaining_budget_does_not_treat_a_hole_as_zero():
    assert truth.remaining_budget(100, 40, 50) == 10
    assert truth.remaining_budget(100, 80, 30) == 0
    assert truth.remaining_budget(None, 0, 0) is None
    assert truth.remaining_budget(100, None, 0) is None
    assert truth.remaining_budget(100, 0, None) is None


def test_coverage_keeps_an_unclassified_row_and_blocks_a_gap():
    missing = truth.coverage(None)
    assert missing["unclassified"]["amount"] is None
    assert missing["status"] == "missing"
    assert missing["blocks_publish"] is False

    empty = truth.coverage([])
    assert empty["ok"] is True
    assert empty["charges_total"] == 0
    assert empty["unclassified"]["label"] == "לא מסווג"
    assert "ספירה" in empty["label"]

    rows = [
        {"amount": -80, "category": "rent", "unclassified": False},
        {"amount": -20, "category": None, "unclassified": True},
    ]
    covered = truth.coverage(rows)
    assert covered["ok"] is True
    assert covered["charges_total"] == -100
    assert covered["unclassified"]["amount"] == -20

    broken = truth.coverage([{"amount": None, "category": "rent"}])
    assert broken["blocks_publish"] is True
    assert broken["charges_total"] is None
    twice = truth.coverage([
        {"id": 1, "amount": -10, "category": "rent"},
        {"id": 1, "amount": -10, "category": "rent"},
    ])
    assert twice["blocks_publish"] is True
    assert twice["ok"] is False


def test_internal_transfer_and_financing_are_not_income():
    bank = [{"id": "t", "amount": 500, "is_internal_transfer": True, "is_financing": False}]
    line = {"line_key": "income", "source_id": "bank:t", "amount": 500}
    blocked = truth.detect_duplicates([], bank, [line])
    assert any(item["code"] == "internal_transfer_as_income" for item in blocked["violations"])

    loan = [{"id": "l", "amount": 500, "is_financing": True}]
    financed = truth.detect_duplicates([], loan, [{"line_key": "income", "source_id": "bank:l", "amount": 500}])
    assert any(item["code"] == "financing_as_income" for item in financed["violations"])


def test_layer2_supplier_forecast_cannot_exceed_open_payables():
    document = {
        "id": "d1", "kind": "AP", "supplier_id": "s", "supplier_name": "ספק",
        "doc_ref": "1", "doc_date": "2026-09-01", "gross": 100, "paid_gross": 0,
    }
    line = {"line_key": "suppliers_provision", "layer": 2, "amount": -250, "source_id": "doc:d1"}
    result = truth.detect_duplicates([document], [], [line])

    assert result["blocks_publish"] is True
    assert result["violations"][0]["code"] == "layer2_exceeds_open_ap"


def test_variance_splits_quantity_and_price_and_keeps_ytd_apart_from_the_annual_remainder():
    one = truth.variance_line(kind="revenue", budget_qty=10, budget_price=100, actual_qty=8, actual_price=120)

    assert one["variance"] == -40
    assert one["quantity_variance"] == -200
    assert one["price_variance"] == 160
    assert one["quantity_variance"] + one["price_variance"] == one["variance"]
    assert one["favorable"] is False

    cost = truth.variance_line(kind="cost", budget_qty=10, budget_price=100, actual_qty=8, actual_price=100)
    assert cost["variance"] == -200
    assert cost["favorable"] is True

    hole = truth.variance_line(kind="revenue", budget_qty=10, budget_price=100, actual_qty=None, actual_price=120)
    assert hole["status"] == "missing"
    assert hole["variance"] is None

    lines = [
        {"in_ytd": True, "in_annual": True, "budget_qty": 1, "budget_price": 100, "actual_qty": 1, "actual_price": 100},
        {"in_ytd": True, "in_annual": True, "budget_qty": 10, "budget_price": 200, "actual_qty": 10, "actual_price": 200},
        {"in_ytd": False, "in_annual": True, "budget_qty": 5, "budget_price": 100, "actual_qty": None, "actual_price": None},
    ]
    report = truth.variance_set(lines, kind="revenue")

    assert report["ytd"]["budget_price_weighted"] == 190.91
    assert report["ytd"]["budget_price_simple_average"] == 150
    assert report["ytd"]["budget_price_weighted"] != report["ytd"]["budget_price_simple_average"]
    assert report["remaining_to_annual"]["qty"] == 5
    assert report["remaining_to_annual"]["amount"] == 500
    assert "אינו חריגה" in report["remaining_to_annual"]["label"]
    mix = report["mix"]
    assert mix["identity"] is True
    assert round(mix["volume_variance"] + mix["mix_variance"] + mix["price_variance"], 2) == mix["variance"]


def test_drivers_stay_missing_until_every_component_exists_and_profit_needs_revenue():
    payroll = truth.evaluate_driver({
        "line_key": "payroll", "driver_type": "payroll", "month": "2026-11",
        "rate": 100, "qty": 10, "status": "assumption",
    })
    assert payroll["status"] == "missing"
    assert payroll["amount_net"] is None
    assert payroll["label_he"] == "חסרים היקף או עלויות מעסיק"

    filled = truth.evaluate_driver({
        "line_key": "payroll", "driver_type": "payroll", "month": "2026-11",
        "rate": 100, "qty": 10, "employer_uplift_pct": 0.2, "status": "confirmed",
    })
    assert filled["amount_gross"] == 1200
    assert filled["pay_date"] == "2026-11-10"
    assert filled["certainty"] == "הערכה"
    assert filled["layer"] == 3

    revenue = truth.evaluate_driver({
        "line_key": "revenue", "driver_type": "quantity_price", "qty": 2, "unit_price_net": 50,
        "status": "assumption",
    })
    assert revenue["amount_net"] == 100
    assert revenue["amount_gross"] is None

    group = truth.evaluate_drivers([
        {"line_key": "revenue", "driver_type": "quantity_price", "qty": 2, "unit_price_net": 50,
         "vat_pct": 0.18, "status": "confirmed"},
        {"line_key": "suppliers", "driver_type": "quantity_price", "classification": "unclassified",
         "qty": 1, "unit_price_net": 10, "vat_pct": 0, "status": "confirmed"},
    ])
    assert group["amount_net"] is None
    assert group["label"] == "יש שורות לסיווג"
    assert truth.profit_rate(30, 0) is None
    assert truth.profit_rate(None, 100) is None
    assert truth.profit_rate(25, 100) == 0.25


def test_a_manual_completion_needs_amount_source_and_date():
    refused = truth.accept_manual(None, "", None)
    assert refused["ok"] is False
    assert refused["amount"] is None
    assert refused["label"] == "נדרש סכום, מקור ותאריך"

    zero = truth.accept_manual(0, "בעלים", "2026-10-01")
    assert zero["ok"] is False
    verified = truth.accept_manual(0, "בעלים", "2026-10-01", verified_by="עמית")
    assert verified["ok"] is True
    assert verified["amount"] == 0
    assert verified["status"] == "confirmed"


def test_shared_costs_stay_on_their_own_row():
    shared = truth.evaluate_driver({
        "line_key": "shared", "driver_type": "shared_cost", "amount": 80, "status": "assumption",
    })
    assert shared["allocated"] is False
    assert shared["amount_net"] == 80
    try:
        truth.validate_settings({"allocation_rule": {"method": "revenue_share"}})
        raised = False
    except truth.CashflowSettingsError:
        raised = True
    assert raised


def test_funding_need_is_the_trough_and_negative_weeks_are_a_different_number():
    need = truth.funding_need([-10, 20, -30], opening=0, credit_limit=10, weekly_nets=[-10, 30, -50])

    assert need["amount"] == 30
    assert need["after_credit"] == 20
    assert need["sum_of_negative_weeks"] == -60
    assert need["amount"] != abs(need["sum_of_negative_weeks"])

    unknown = truth.funding_need([None], opening=0, credit_limit=30, weekly_nets=[0])
    assert unknown["status"] == "missing"
    assert unknown["amount"] is None


def test_the_daily_minimum_is_lower_than_the_friday_close_when_cash_dips():
    events = [
        {"date": "2026-10-28", "amount": -80, "status": "confirmed", "scenario": "base"},
        {"date": "2026-10-30", "amount": 70, "status": "confirmed", "scenario": "base"},
    ]

    assert truth._daily_min(100, events, date(2026, 10, 25), date(2026, 10, 30), True) == 20


def test_an_empty_organization_gets_a_full_scaffold_of_unknowns():
    report = truth.scaffold(as_of=AS_OF, organization_id=404, plan=None)

    assert report["provider_calls"] == 0
    assert len(report["weeks"]) == 13
    assert {row["line_key"] for row in report["lines"]} == {key for key, *_rest in truth.SCAFFOLD_ROWS}
    for row in report["lines"]:
        assert row["status"] == "missing"
        assert row["amount"] is None
        assert row["layer"] in (1, 2, 3)
        assert row["certainty"] in ("מאושר", "סביר", "מסוכן", "הערכה")
        if row["layer"] == 3:
            assert row["certainty"] == "הערכה"
    for week in report["weeks"]:
        start = date.fromisoformat(week["week_start"])
        end = date.fromisoformat(week["week_end"])
        assert start.weekday() == 6
        assert end.weekday() == 4
        assert end == start + __import__("datetime").timedelta(days=5)
        assert week["in"] is None and week["out"] is None and week["net"] is None
        assert week["closing"] is None and week["headroom"] is None and week["daily_min"] is None
    assert report["liquidity"]["state"] == "לא ידוע"
    assert report["drivers"]["amount_net"] is None
    assert report["drivers"]["complete"] == 0
    assert report["shared_costs"]["allocated"] is False
    assert report["shared_costs"]["amount"] is None
    assert report["coverage"]["unclassified"]["amount"] is None
    assert report["duplicates"]["status"] == "missing"
    assert report["variance"]["status"] == "missing"
    assert report["funding_need"]["amount"] is None
    blob = __import__("json").dumps(report, ensure_ascii=False)
    for token in FORBIDDEN:
        assert token not in blob


def test_the_live_view_of_a_new_org_carries_that_scaffold(fresh_org):
    owner = fresh_org()
    with SessionLocal() as db:
        view = build_view(db, owner["org_id"], date(2026, 10, 1), AS_OF, plan=None)

    source = view["cashflow_source"]
    assert source["provider_calls"] == 0
    assert source["settings"]["payroll_day"] == 10
    assert source["settings"]["supplier_terms"]["days"] == 30
    opening = next(row for row in source["lines"] if row["line_key"] == "opening")
    facility = next(row for row in source["lines"] if row["line_key"] == "credit_facility")
    assert opening["amount"] is None and opening["status"] == "missing"
    assert facility["amount"] is None
    assert all(week["net"] is None for week in source["weeks"])
    assert all(week["closing"] is None for week in source["weeks"])
    blob = __import__("json").dumps(source, ensure_ascii=False)
    for token in FORBIDDEN:
        assert token not in blob


def test_settings_reject_an_unknown_field_and_a_guessed_free_text_term():
    validate_filing_payload({"cashflowSettings": {"payroll_day": 10}})
    try:
        validate_filing_payload({"cashflowSettings": {"payroll_day": 31}})
        raised = False
    except DashboardError as exc:
        raised = True
        assert "יום השכר" in exc.message_he
    assert raised
