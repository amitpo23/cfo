"""תזרים חזוי 13 שבועות (docs/superpowers/specs/2026-10-26-cash-forecast-13w-design.md).

פונקציה טהורה מעל ה-view model של `/d/`: אין מסד, אין ספק. כל טסט בונה
view מינימלי ובודק התנהגות אחת של המודל.
"""
from datetime import date

from cfo.services.dashboards import cash_forecast

TODAY = date(2026, 10, 26)  # יום שני; השבוע הראשון הוא 25/10–30/10 (ראשון–שישי)


def _view(*, balance=-35000.0, as_of="2026-10-21", checks=None, upcoming=None,
          debt_service=None, lines=None, months=None):
    return {
        "liquidity": {
            "position": {"balance": balance, "as_of": as_of, "limit": None},
            "checks": checks or [],
            "upcoming": upcoming or [],
            "debt_service": debt_service or [],
        },
        "cash_statement": {
            "months": months or [],
            "lines": lines or [],
        },
    }


def _plan(facilities=None, items=None, org=2):
    return {
        "liquidityEvidence": {"facilities": [dict(f, organizationId=org) for f in (facilities or [])]},
        "cashForecastItems": [dict(i, organizationId=org) for i in (items or [])],
    }


def _forecast(view, plan=None, org=2):
    return cash_forecast.build_entity_forecast(
        view, plan=plan or _plan(), organization_id=org, label="שף אליהב כהן", today=TODAY,
    )


def test_weeks_run_sunday_to_friday_and_saturday_cash_moves_to_sunday():
    result = _forecast(_view(checks=[{
        "check": "sat", "date": "2026-10-31", "amount": 1000.0, "payee": "ספק", "state": "future",
    }]))

    assert len(result["weeks"]) == 13
    assert result["weeks"][0]["start"] == "2026-10-25"
    assert result["weeks"][0]["end"] == "2026-10-30"
    assert result["weeks"][0]["end"] < "2026-10-31"
    assert result["weeks"][1]["start"] == "2026-11-01"
    assert result["weeks"][1]["end"] == "2026-11-06"
    assert all(item.get("date") != "2026-10-31" for week in result["weeks"] for item in week["items"])
    saturday = [item for item in result["weeks"][1]["items"] if "sat" in (item.get("label") or "")]
    assert [item["date"] for item in saturday] == ["2026-11-01"]
    assert saturday[0]["amount"] == -1000.0
    assert saturday[0]["saturday_rolled"] is True
    assert result["weeks"][1]["out"] == -1000.0
    assert result["weeks"][0]["out"] == 0.0


def test_closing_walks_the_opening_balance_through_dated_items():
    view = _view(checks=[{"check": "1", "date": "2026-10-28", "amount": 3000.0,
                          "payee": "ספק א", "state": "future"}])

    week = _forecast(view)["weeks"][0]

    assert week["out"] == -3000.0
    assert week["closing"] == -38000.0
    assert week["items"][0]["certainty"] == "certain"


def test_headroom_is_limit_plus_closing_and_the_first_breach_names_its_reasons():
    view = _view(balance=-10000.0, checks=[
        {"check": "7", "date": "2026-11-04", "amount": 8000.0, "payee": "ספק", "state": "future"},
    ])
    plan = _plan(facilities=[{"name": "מסגרת עו״ש 8954", "limit": 15000}])

    result = _forecast(view, plan)

    assert result["weeks"][0]["headroom"] == 5000.0
    assert result["weeks"][1]["headroom"] == -3000.0
    breach = result["first_breach"]
    assert breach["week_start"] == "2026-11-01"
    assert breach["headroom"] == -3000.0
    assert any("ספק" in reason for reason in breach["reasons"])


def test_a_facility_stops_counting_after_its_valid_to_date():
    plan = _plan(facilities=[{"name": "מסגרת 1662", "limit": 80000, "validTo": "2026-12-31"}])

    weeks = _forecast(_view(balance=0.0), plan)["weeks"]

    december_last = next(w for w in weeks if w["start"] <= "2026-12-31" <= w["end"])
    after = next(w for w in weeks if w["start"] > "2026-12-31")
    assert december_last["limit"] == 80000.0
    assert after["limit"] is None
    assert after["headroom"] is None


def test_an_unknown_opening_balance_keeps_closing_and_headroom_unknown():
    view = _view(balance=None, as_of=None, checks=[
        {"check": "1", "date": "2026-10-28", "amount": 100.0, "payee": "x", "state": "future"},
    ])
    plan = _plan(facilities=[{"name": "מסגרת", "limit": 80000}])

    result = _forecast(view, plan)

    week = result["weeks"][0]
    assert week["out"] == -100.0
    assert week["closing"] is None
    assert week["headroom"] is None
    assert result["first_breach"] is None
    assert "opening_balance" in result["missing"]


def test_known_checks_consume_the_operating_run_rate_instead_of_adding_to_it():
    months = ["2026-07", "2026-08", "2026-09"]
    lines = [{"id": "checks_out", "group": "operating_out",
              "values": {"2026-07": -31000.0, "2026-08": -31000.0, "2026-09": -31000.0}}]
    with_check = _view(balance=0.0, as_of="2026-10-31", months=months, lines=lines, checks=[
        {"check": "9", "date": "2026-11-10", "amount": 5000.0, "payee": "ספק", "state": "future"},
    ])
    without = _view(balance=0.0, as_of="2026-10-31", months=months, lines=lines)

    november = lambda result: sum(
        w["out"] for w in result["weeks"] if "2026-11-01" <= w["start"] <= "2026-11-29"
    )

    assert round(november(_forecast(with_check)), 2) == round(november(_forecast(without)), 2)


def test_owner_items_are_added_on_top_of_the_run_rate():
    plan = _plan(items=[{"date": "2026-10-29", "amount": -17000, "label": "חוב לעובדים"}])

    week = _forecast(_view(balance=0.0), plan)["weeks"][0]

    assert week["out"] == -17000.0
    assert week["items"][0]["certainty"] == "manual"
    assert week["items"][0]["label"] == "חוב לעובדים"


def test_a_loan_maturity_is_dated_and_marked_as_an_upper_bound():
    view = _view(balance=0.0, upcoming=[{
        "date": "2026-11-25", "kind": "loan_maturity", "label": "גישור · סיום הלוואה",
        "amount": -60000.0, "amount_basis": "outstanding_balance",
    }])

    item = next(i for w in _forecast(view)["weeks"] for i in w["items"])

    assert item["amount"] == -60000.0
    assert item["certainty"] == "certain"
    assert item["upper_bound"] is True


def test_a_transfer_between_entities_is_cash_for_each_and_nets_out_in_the_combined_view():
    """Food Group files its transfers to Eliav under ``transfers_out``; Eliav files
    them as ``internal``. Each side is real cash for its own account, and the
    combined view nets them only when both sides are counted."""
    months = ["2026-07", "2026-08", "2026-09"]
    receiver = _view(balance=0.0, as_of="2026-10-31", months=months, lines=[
        {"id": "intercompany", "group": "internal", "values": {m: 31000.0 for m in months}},
    ])
    payer = _view(balance=0.0, as_of="2026-10-31", months=months, lines=[
        {"id": "transfers_out", "group": "operating_out", "values": {m: -31000.0 for m in months}},
    ])

    eliav = _forecast(receiver)
    food = _forecast(payer, org=6)
    combined = cash_forecast.combine([eliav, food])

    assert sum(w["in"] for w in eliav["weeks"]) > 0
    assert round(sum(w["net"] for w in combined["weeks"]), 2) == 0.0


def test_the_run_rate_adds_up_across_entities():
    """The combined view is the sum of the entities, so the run-rate must be additive:
    the entities' run-rates add up to the run-rate of their summed statements. A median
    per entity takes each entity's middle month from a different month and does not."""
    months = ["2026-07", "2026-08", "2026-09"]
    a = {"2026-07": 30000.0, "2026-08": 0.0, "2026-09": 0.0}
    b = {"2026-07": 0.0, "2026-08": 0.0, "2026-09": 30000.0}
    both = {m: a[m] + b[m] for m in months}
    rate = lambda values: cash_forecast.run_rate(
        _view(months=months, lines=[{"id": "sales_card", "group": "operating_in", "values": values}]), TODAY,
    )["operating_in"]

    assert round(rate(a) + rate(b), 2) == round(rate(both), 2)


def test_one_off_lines_stay_out_of_the_run_rate():
    months = ["2026-07", "2026-08", "2026-09"]
    view = _view(months=months, lines=[
        {"id": "tax_refund", "group": "internal", "values": {"2026-07": 0.0, "2026-08": 17295.0, "2026-09": 0.0}},
        {"id": "intercompany", "group": "internal", "values": {m: 9000.0 for m in months}},
    ])

    assert cash_forecast.run_rate(view, TODAY)["internal"] == 9000.0


def test_a_maturity_already_past_with_no_bank_coverage_is_flagged_not_dropped():
    view = _view(balance=None, as_of=None)
    plan = {"liquidityEvidence": {"loans": [{
        "label": "גישור", "organizationId": 2, "balance": 50000.0, "maturity": "2026-10-25",
    }]}}

    result = _forecast(view, plan)

    overdue = result["overdue"]
    assert overdue[0]["label"] == "גישור"
    assert overdue[0]["amount"] == -50000.0
    assert overdue[0]["date"] == "2026-10-25"


def test_the_combined_view_is_unknown_while_any_entity_balance_is_unknown():
    known = _forecast(_view(balance=-1000.0))
    unknown = _forecast(_view(balance=None, as_of=None), org=6)

    combined = cash_forecast.combine([known, unknown])

    assert combined["weeks"][0]["closing"] is None
    assert "opening_balance" in combined["missing"]
    assert combined["provider_calls"] == 0
