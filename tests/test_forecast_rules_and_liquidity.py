"""Explicit forecast rules and owner-entered liquidity. No provider calls.

Worked week, Sunday 25/10/2026–Saturday 31/10/2026, opening dated 28/10/2026
(the day after which the forecast moves). October has 31 days; only 29–31
are still ahead of the opening, so October's budget income of 62,000 is
62,000 × 3/31 = 6,000. September's supplier budget of 30,000 is paid on
31/10 (שוטף 30). Checking facility 50,000.

    opening                         -12,000   accounts, as of 28/10
    income 29–31/10                  +6,000   plan.budgetLines
    suppliers, supply 2026-09       -30,000   due 31/10
    net                             -24,000
    closing                         -36,000
    headroom                 50,000 - 36,000 = 14,000   not a breach

Payroll of 18,000 is the plan's payroll definition, paid on the 1st, so it
lands on 01/11, not in this week. The bridge of 61,000 closes on 25/11
against a receipt of the same amount.
"""
from datetime import date, datetime
from decimal import Decimal

from cfo.database import SessionLocal
from cfo.models import Account, AccountType, BankTransaction
from cfo.services.dashboards import cash_forecast, forecast, forecast_rules, liquidity
from cfo.services.dashboards.service import validate_filing_payload

TODAY = date(2026, 10, 28)
ORG = 2


def _lines():
    return [
        {"id": "sales", "label": "מכירות", "category": "sales",
         "months": {"2026-10": {"quantity": 1, "rate": 62000}}},
        {"id": "suppliers", "label": "ספקים", "category": "cost_of_goods",
         "months": {"2026-09": {"quantity": 1, "rate": 30000}}},
    ]


def _plan(**extra):
    plan = {
        "budgetLines": _lines(),
        "payroll": [{"id": "crew", "label": "צוות", "monthly": 18000}],
        "liquidityEvidence": {"observedAt": "2026-10-28", "loans": [], "facilities": []},
    }
    plan.update(extra)
    return plan


def _view(*, balance=-12000.0, as_of="2026-10-28", limit=50000.0):
    return {
        "liquidity": {
            "position": {"balance": balance, "as_of": as_of, "limit": limit, "balance_source": "accounts"},
            "checks": [], "upcoming": [], "debt_service": [],
        },
        "cash_statement": {"months": [], "lines": []},
    }


def _run(view=None, plan=None):
    return cash_forecast.build_entity_forecast(
        view or _view(), plan=plan if plan is not None else _plan(),
        organization_id=ORG, label="אליהב", today=TODAY,
    )


def _week(result, start):
    return next(week for week in result["weeks"] if week["start"] == start)


def _item(result, label_part):
    return next(item for week in result["weeks"] for item in week["items"] if label_part in (item.get("label") or ""))


def test_shotef_30_is_the_last_day_of_the_next_month():
    assert forecast_rules.shotef_30(2026, 9) == date(2026, 10, 31)
    assert forecast_rules.shotef_30(2026, 10) == date(2026, 11, 30)
    assert forecast_rules.shotef_30(2026, 12) == date(2027, 1, 31)


def test_the_forecast_starts_at_todays_position_and_ignores_cash_already_in_it():
    view = _view()
    view["liquidity"]["checks"] = [
        {"check": "old", "date": "2026-10-27", "amount": 9000.0, "payee": "ספק", "state": "future"},
    ]

    result = _run(view)

    opening = result["opening"]
    assert opening["amount"] == -12000.0
    assert opening["as_of"] == "2026-10-28"
    assert opening["source"] == "accounts"
    assert opening["rule"] == "today_position"
    assert all("old" not in (item.get("label") or "") for week in result["weeks"] for item in week["items"])
    assert result["provider_calls"] == 0


def test_suppliers_are_paid_on_shotef_30_from_the_supply_months_budget():
    week = _week(_run(), "2026-10-25")
    supplier = _item(_run(), "שוטף 30")

    assert supplier["date"] == "2026-10-31"
    assert supplier["amount"] == -30000.0
    assert supplier["source"] == "plan.budgetLines"
    assert supplier["rule"] == "shotef_30"
    assert week["out"] == -30000.0


def test_payroll_comes_from_the_budget_definition_on_the_first():
    item = _item(_run(), "שכר")

    assert item["date"] == "2026-11-01"
    assert item["amount"] == -18000.0
    assert item["source"] == "plan.payroll"
    assert item["rule"] == "budget_payroll_definition"


def test_payroll_falls_back_to_salary_budget_lines_when_there_is_no_definition():
    plan = _plan()
    plan.pop("payroll")
    plan["budgetLines"] = _lines() + [{
        "id": "pay", "label": "משכורות", "category": "salaries",
        "months": {"2026-11": {"quantity": 1, "rate": 9000}},
    }]

    item = _item(_run(plan=plan), "שכר")

    assert item["date"] == "2026-11-01"
    assert item["amount"] == -9000.0
    assert item["source"] == "plan.budgetLines"


def test_expected_income_comes_from_the_budget_not_from_a_run_rate():
    week = _week(_run(), "2026-10-25")
    income = next(item for item in week["items"] if item["label"] == "הכנסה לפי התקציב")

    assert income["amount"] == 6000.0
    assert income["source"] == "plan.budgetLines"
    assert income["certainty"] == "scheduled"
    assert all(item.get("stream") != "operating_in" for item in week["items"])


def test_a_short_loan_closes_on_its_maturity_against_a_receipt():
    plan = _plan()
    plan["liquidityEvidence"]["loans"] = [{
        "label": "גישור נובמבר", "kind": "bridge", "balance": 61000, "maturity": "2026-11-25",
        "asOf": "2026-10-28", "organizationId": ORG, "source": "בעלים",
    }]

    result = _run(plan=plan)
    legs = [item for week in result["weeks"] for item in week["items"] if "גישור נובמבר" in item["label"]]

    assert [leg["amount"] for leg in legs] == [-61000.0, 61000.0]
    assert {leg["date"] for leg in legs} == {"2026-11-25"}
    assert all(leg["source"] == "plan.liquidityEvidence" for leg in legs)
    assert all(leg["rule"] == "close_on_maturity_against_receipt" for leg in legs)
    assert sum(leg["amount"] for leg in legs) == 0


def test_a_stated_instalment_is_not_the_whole_balance():
    plan = _plan()
    plan["liquidityEvidence"]["loans"] = [{
        "label": "הלוואה 300,000", "kind": "term", "balance": 261800, "approximate": True,
        "paymentAmount": 5745.17, "paymentDate": "2026-11-10", "organizationId": ORG,
    }]

    item = _item(_run(plan=plan), "החזר")

    assert item["date"] == "2026-11-10"
    assert item["amount"] == -5745.17
    assert not any(item.get("amount") == -261800 for week in _run(plan=plan)["weeks"] for item in week["items"])


def test_missing_inputs_stay_null_and_are_labelled():
    plan = _plan()
    plan["budgetLines"] = [{
        "id": "sales", "label": "מכירות", "category": "sales",
        "months": {"2026-10": {"quantity": 1, "rate": 62000}},
    }]
    plan["payroll"] = [{"id": "crew", "label": "צוות", "monthly": None}]
    plan["liquidityEvidence"]["loans"] = [{
        "label": "גישור", "kind": "bridge", "balance": None, "maturity": "2026-11-25", "organizationId": ORG,
    }]

    result = _run(plan=plan)
    november = _week(result, "2026-11-29")

    assert november["net"] is None
    assert november["in"] is None
    assert november["out"] is None
    assert any("ספקים" in text for text in november["unknown"])
    assert not any(item.get("amount") == 0 for week in result["weeks"] for item in week["items"])
    payroll_week = _week(result, "2026-11-01")
    assert any("שכר" in text for text in payroll_week["unknown"])
    bridge_week = _week(result, "2026-11-22")
    assert any("הלוואה קצרה" in text for text in bridge_week["unknown"])
    assert "forecast_rules" in result["missing"]


def test_an_unknown_opening_does_not_become_zero():
    result = _run(_view(balance=None, as_of=None, limit=50000))

    assert result["opening"]["amount"] is None
    assert result["weeks"][0]["closing"] is None
    assert result["first_breach"] is None
    assert "opening_balance" in result["missing"]


def test_the_worked_week_of_25_to_31_october():
    week = _week(_run(), "2026-10-25")

    assert week["in"] == 6000.0
    assert week["out"] == -30000.0
    assert week["net"] == -24000.0
    assert week["closing"] == -36000.0
    assert week["limit"] == 50000.0
    assert week["headroom"] == 14000.0
    assert _run()["first_breach"] is None


def test_a_missing_facility_is_not_a_breach_against_zero():
    result = _run(_view(balance=-100000.0, limit=None), plan={})

    assert all(week["limit"] is None for week in result["weeks"])
    assert all(week["headroom"] is None for week in result["weeks"])
    assert result["first_breach"] is None
    assert "facility_limit" in result["missing"]


def test_a_breach_is_computed_against_the_real_facility():
    inside = _run(_view(balance=-100000.0, limit=150000.0), plan={})
    outside = _run(_view(balance=-100000.0, limit=50000.0), plan={})

    assert inside["weeks"][0]["headroom"] == 50000.0
    assert inside["first_breach"] is None
    assert outside["weeks"][0]["limit"] == 50000.0
    assert outside["weeks"][0]["headroom"] == -50000.0
    assert outside["first_breach"]["headroom"] == -50000.0


def test_an_ended_evidence_facility_falls_back_to_the_account_limit():
    plan = {"liquidityEvidence": {"facilities": [
        {"label": "מסגרת זמנית", "limit": 10000, "validTo": "2026-10-31", "organizationId": ORG},
    ]}}

    result = _run(_view(balance=-20000.0, limit=80000.0), plan=plan)

    assert _week(result, "2026-10-25")["limit"] == 10000.0
    assert _week(result, "2026-11-01")["limit"] == 80000.0
    assert _week(result, "2026-11-01")["headroom"] == 60000.0


def test_cheque_discounting_does_not_become_the_checking_facility():
    plan = {"liquidityEvidence": {"facilities": [
        {"label": "ניכיון שיקים", "kind": "cheque_discounting", "limit": 200000, "organizationId": ORG},
    ]}}

    result = _run(_view(balance=-10000.0, limit=None), plan=plan)

    assert all(week["limit"] is None for week in result["weeks"])
    assert result["first_breach"] is None


def test_monthly_cells_are_filled_from_the_rules_and_missing_ones_stay_null():
    plan = _plan()
    out = forecast.build_forecast([], as_of=TODAY, plan=plan, opening_balance=-12000.0)
    november = out["cash_rules"]["months"]["2026-11"]

    assert november["income"]["amount"] is None
    assert "לא ידוע" in november["income"]["label"]
    assert november["payroll"] == {
        "amount": -18000.0, "source": "plan.payroll", "rule": "budget_payroll_definition",
        "pay_date": "2026-11-01",
    }
    # September's suppliers are paid in October, which is the current month and not in the horizon.
    # October has no supplier line, so November's שוטף 30 payment stays unknown.
    assert november["suppliers"]["amount"] is None
    assert november["suppliers"]["supply_month"] == "2026-10"
    assert november["suppliers"]["due"] == "2026-11-30"
    assert "לא ידוע" in november["suppliers"]["label"]
    assert out["cash_rules"]["provider_calls"] == 0


def test_owner_stated_loans_and_the_discounting_facility_are_evidence(fresh_org):
    owner = fresh_org()
    plan = {"liquidityEvidence": {
        "observedAt": "2026-10-28T09:00:00Z",
        "facilities": [{"label": "ניכיון שיקים", "kind": "cheque_discounting", "organizationId": owner["org_id"]}],
        "loans": [
            {"label": "גישור נובמבר", "kind": "bridge", "balance": 61000, "maturity": "2026-11-25",
             "asOf": "2026-10-28", "source": "בעלים 28.10.2026", "organizationId": owner["org_id"]},
            {"label": "גישור דצמבר", "kind": "bridge", "balance": 41000, "maturity": "2026-12-25",
             "asOf": "2026-10-28", "organizationId": owner["org_id"]},
            {"label": "הלוואה 300,000", "kind": "term", "balance": 261800, "approximate": True,
             "asOf": "2026-10-28", "paymentAmount": 5745.17, "paymentDate": "2026-11-10",
             "organizationId": owner["org_id"]},
        ],
    }}
    with SessionLocal() as db:
        db.add(Account(
            organization_id=owner["org_id"], name="עו״ש אליהב", account_type=AccountType.BANK,
            raw_account_type="CHECKING", source="open_finance", external_id="checking",
            balance=Decimal("-12000"), balance_as_of=datetime(2026, 10, 28), currency="ILS",
            credit_limit=Decimal("80000"),
        ))
        db.commit()
        section = liquidity.build_liquidity(
            db, owner["org_id"], date(2026, 10, 1), TODAY, plan=plan, classified=[], today=TODAY,
        )

    discount = next(row for row in section["facilities"] if row["kind"] == "cheque_discounting")
    credit = next(row for row in section["facilities"] if row["kind"] == "credit_line")
    loans = {loan["name"]: loan for loan in section["loans"]}

    assert discount["limit"] is None
    assert discount["uncertainty"] == "לא ידוע, הבעלים יזין"
    assert discount["provider_data"] is False
    assert all(row["limit"] != 200000 for row in section["facilities"])
    assert credit["limit"] == 80000.0
    assert credit["available"] == 68000.0
    assert credit["source"] == "accounts.credit_limit"
    assert credit["as_of"] == "2026-10-28"
    assert credit["provider_data"] is True
    november = loans["גישור נובמבר"]
    assert november["balance"] == 61000.0
    assert november["maturity"] == "2026-11-25"
    assert november["source"] == "בעלים 28.10.2026"
    assert november["owner_entered"] is True
    assert november["provider_data"] is False
    assert loans["גישור דצמבר"]["maturity"] == "2026-12-25"
    term = loans["הלוואה 300,000"]
    assert term["balance"] == 261800.0
    assert term["payment_amount"] == 5745.17
    assert term["payment_date"] == "2026-11-10"
    assert term["provider_data"] is False
    assert "בקירוב" in term["uncertainty"]
    assert section["provider_calls"] == 0


def test_without_an_entered_discounting_limit_the_row_stays_unknown(fresh_org):
    owner = fresh_org()
    with SessionLocal() as db:
        section = liquidity.build_liquidity(
            db, owner["org_id"], date(2026, 10, 1), TODAY, plan={}, classified=[], today=TODAY,
        )
    discount = next(row for row in section["facilities"] if row["kind"] == "cheque_discounting")

    assert discount["limit"] is None
    assert discount["uncertainty"] == "לא ידוע, הבעלים יזין"
    assert discount["owner_entered"] is False


def test_card_available_uses_the_stored_figure_then_derives_and_names_the_gap(fresh_org):
    owner = fresh_org()
    with SessionLocal() as db:
        stored = Account(
            organization_id=owner["org_id"], name="Cal Intl", account_type=AccountType.LIABILITY,
            raw_account_type="CARD", source="open_finance", external_id="cal",
            balance=Decimal("-20000"), balance_as_of=datetime(2026, 10, 28), currency="ILS",
            credit_limit=Decimal("50000"), available_limit=Decimal("28000"),
        )
        derived = Account(
            organization_id=owner["org_id"], name="Amex", account_type=AccountType.LIABILITY,
            raw_account_type="CARD", source="open_finance", external_id="amex",
            balance=Decimal("-24175"), balance_as_of=datetime(2026, 10, 27), currency="ILS",
            credit_limit=Decimal("70000"),
        )
        unknown = Account(
            organization_id=owner["org_id"], name="Gold MC", account_type=AccountType.LIABILITY,
            raw_account_type="CARD", source="open_finance", external_id="mc",
            balance=Decimal("-1000"), balance_as_of=datetime(2026, 10, 28), currency="ILS",
        )
        db.add_all([stored, derived, unknown])
        db.flush()
        db.add(BankTransaction(
            organization_id=owner["org_id"], account_id=derived.id, source="open_finance",
            transaction_date=date(2026, 10, 26), amount=Decimal("-500"), description="עסקה ממתינה",
            raw_data={"status": "PENDING"}, external_id="amex-pending",
        ))
        db.add(BankTransaction(
            organization_id=owner["org_id"], account_id=stored.id, source="open_finance",
            transaction_date=date(2026, 10, 20), amount=Decimal("-15"), description="קניה",
            raw_data={}, external_id="cal-blank",
        ))
        db.commit()
        section = liquidity.build_liquidity(
            db, owner["org_id"], date(2026, 10, 1), TODAY, plan={}, classified=[], today=TODAY,
        )

    cards = {card["name"]: card for card in section["cards"]}
    assert cards["Cal Intl"]["available"] == 28000.0
    assert cards["Cal Intl"]["available_source"] == "accounts.available_limit"
    assert cards["Cal Intl"]["available_as_of"] == "2026-10-28"
    # 70,000 limit − 24,175 statement balance − 500 pending.
    assert cards["Amex"]["available"] == 45325.0
    assert cards["Amex"]["available_source"] == "credit_limit_minus_unbilled"
    assert cards["Amex"]["available_as_of"] == "2026-10-27"
    assert "אינו הסכום שהבנק מסר" in cards["Amex"]["available_note"]
    assert cards["Gold MC"]["available"] is None
    assert "אין מסגרת" in cards["Gold MC"]["available_note"]
    activity = section["card_activity"]
    assert activity["defined"] is True
    assert activity["amount"] == -15.0
    assert activity["count"] == 1
    assert section["provider_calls"] == 0


def test_a_pending_charge_without_an_amount_keeps_available_unknown():
    account = Account(credit_limit=Decimal("20000"), available_limit=None, balance_as_of=datetime(2026, 10, 28))

    row = liquidity.card_open_to_buy(account, 1000.0, None, "2026-10-28")

    assert row["available"] is None
    assert "בלי סכום" in row["available_note"]


def test_evidence_rejects_a_bad_loan_kind_and_accepts_the_owner_shape():
    try:
        validate_filing_payload({"liquidityEvidence": {"loans": [{"label": "x", "kind": "invented"}]}})
        raised = False
    except Exception:
        raised = True
    assert raised
    validate_filing_payload({"liquidityEvidence": {"loans": [{
        "label": "גישור נובמבר", "kind": "bridge", "balance": 61000, "maturity": "2026-11-25",
        "asOf": "2026-10-28", "approximate": False,
    }], "facilities": [{
        "label": "ניכיון שיקים", "kind": "cheque_discounting", "limit": None, "asOf": "2026-10-28",
    }]}})
