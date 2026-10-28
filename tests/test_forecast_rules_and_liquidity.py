"""Explicit forecast rules and owner-entered liquidity. No provider calls.

Worked week, Sunday 25/10/2026–Friday 30/10/2026, opening dated 28/10/2026
(the day after which the forecast moves). October has 31 days. Only 29–30
are still ahead of the opening and inside this Sunday–Friday week, so
October's budget income of 62,000 contributes 62,000 × 2/31 = 4,000 here.
31/10 is a Saturday; its 2,000 is taken on Sunday 01/11 and is not in this
week. The default supplier mode is eom_plus_30_days, so September's 30,000
is paid on 30/10. end_of_next_month is a per-org setting and is not the default.
Checking facility 50,000 is headroom, not part of the balance.

    opening                         -12,000   accounts, as of 28/10
    income 29–30/10                  +4,000   plan.budgetLines
    suppliers, supply 2026-09       -30,000   due 30/10 (eom_plus_30_days)
    net                             -26,000
    closing                         -38,000
    headroom                 50,000 - 38,000 = 12,000   not a breach

Payroll of 18,000 is the plan's payroll definition, paid on the 10th, so it
lands on 10/11, not in this week. The bridge of 61,000 closes on 25/11
against a receipt of the same amount.
"""
from datetime import date, datetime
from decimal import Decimal

from cfo.database import SessionLocal
from cfo.models import Account, AccountType, BankTransaction, ClientDashboard, SumitCompany
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


def test_opening_stands_without_a_credit_limit_and_stale_open_finance_is_unknown(fresh_org):
    owner = fresh_org()
    with SessionLocal() as db:
        db.add(Account(
            organization_id=owner["org_id"], name="עו״ש", account_type=AccountType.BANK,
            raw_account_type="CHECKING", source="open_finance", external_id="fresh-chk",
            balance=Decimal("-2500"), credit_limit=None,
            balance_as_of=datetime(2026, 10, 28), currency="ILS",
        ))
        db.commit()
        fresh = liquidity.build_liquidity(
            db, owner["org_id"], date(2026, 10, 1), date(2026, 10, 31),
            classified=[], today=date(2026, 10, 28),
        )
    assert fresh["position"]["balance"] == -2500.0
    assert fresh["position"]["limit"] is None
    assert fresh["position"]["available_to_limit"] is None
    assert fresh["position"]["as_of"] == "2026-10-28"

    other = fresh_org()
    with SessionLocal() as db:
        db.add(Account(
            organization_id=other["org_id"], name="עו״ש ישן", account_type=AccountType.BANK,
            raw_account_type="CHECKING", source="open_finance", external_id="stale-chk",
            balance=Decimal("-800"), credit_limit=None,
            balance_as_of=datetime(2026, 10, 25), currency="ILS",
        ))
        db.add(Account(
            organization_id=other["org_id"], name="עו״ש חדש", account_type=AccountType.BANK,
            raw_account_type="CHECKING", source="open_finance", external_id="newer-chk",
            balance=Decimal("-100"), credit_limit=None,
            balance_as_of=datetime(2026, 10, 28), currency="ILS",
        ))
        db.commit()
        stale = liquidity.build_liquidity(
            db, other["org_id"], date(2026, 10, 1), date(2026, 10, 31),
            classified=[], today=date(2026, 10, 28),
        )
    assert stale["position"]["balance"] is None
    assert stale["position"]["as_of"] is None
    assert stale["stale_balances"][0]["as_of"] == "2026-10-25"
    assert stale["stale_balances"][0]["status"] == "unknown"
    shown = next(row for row in stale["accounts"] if row["name"] == "עו״ש ישן")
    assert shown["balance"] is None and shown["as_of"] == "2026-10-25"


def test_combined_as_of_is_the_oldest_account_date_not_the_newest(fresh_org):
    owner = fresh_org()
    with SessionLocal() as db:
        db.add(Account(
            organization_id=owner["org_id"], name="א", account_type=AccountType.BANK,
            raw_account_type="CHECKING", source="open_finance", external_id="a",
            balance=Decimal("10"), balance_as_of=datetime(2026, 10, 27), currency="ILS",
        ))
        db.add(Account(
            organization_id=owner["org_id"], name="ב", account_type=AccountType.BANK,
            raw_account_type="CHECKING", source="open_finance", external_id="b",
            balance=Decimal("20"), balance_as_of=datetime(2026, 10, 28), currency="ILS",
        ))
        db.commit()
        section = liquidity.build_liquidity(
            db, owner["org_id"], date(2026, 10, 1), date(2026, 10, 31),
            classified=[], today=date(2026, 10, 28),
        )
    assert section["position"]["balance"] == 30.0
    assert section["position"]["as_of"] == "2026-10-27"


def test_shotef_30_is_thirty_days_after_the_end_of_the_supply_month():
    assert forecast_rules.shotef_30(2026, 9) == date(2026, 10, 30)
    assert forecast_rules.shotef_30(2026, 10) == date(2026, 11, 30)
    assert forecast_rules.shotef_30(2026, 12) == date(2027, 1, 30)


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
    assert result["engine"] == "cashflow_source"


def test_default_supplier_mode_pays_september_on_30_october():
    week = _week(_run(), "2026-10-25")
    supplier = _item(_run(), "שוטף 30")

    assert supplier["date"] == "2026-10-30"
    assert supplier["amount"] == -30000.0
    assert supplier["source"] == "plan.budgetLines"
    assert supplier["rule"] == "eom_plus_30_days"
    assert week["out"] == -30000.0


def test_end_of_next_month_moves_september_off_saturday_to_1_november():
    plan = _plan(cashflowSettings={"supplierTermsMode": "end_of_next_month"})
    october = _week(_run(plan=plan), "2026-10-25")
    supplier = _item(_run(plan=plan), "סוף החודש העוקב")

    assert date(2026, 10, 31).weekday() == 5
    assert supplier["date"] == "2026-11-01"
    assert supplier["amount"] == -30000.0
    assert supplier["rule"] == "end_of_next_month"
    assert october["out"] == 0.0
    assert all(item.get("date") != "2026-10-31" for week in _run(plan=plan)["weeks"] for item in week["items"])


def test_salary_budget_lines_win_over_plan_payroll():
    lines = _lines() + [{
        "id": "pay", "label": "שכר", "category": "salaries",
        "months": {"2026-11": {"quantity": 1, "rate": 22000}},
    }]
    plan = _plan(budgetLines=lines)

    item = _item(_run(plan=plan), "שכר")

    assert item["date"] == "2026-11-10"
    assert item["amount"] == -22000.0
    assert item["source"] == "plan.budgetLines"


def test_discounted_cheques_stay_outstanding_until_each_due_date():
    plan = _plan()
    plan["liquidityEvidence"]["checks"] = [
        {"check": "c1", "date": "2026-11-25", "amount": 4000, "discounted": True, "organizationId": ORG},
        {"check": "c2", "date": "2026-12-25", "amount": 9000, "discounted": True, "organizationId": ORG},
    ]
    result = _run(plan=plan)
    balances = {row["check"]: row for row in result["discounted_cheque_balances"]}

    assert balances["c1"]["closes_on"] == "2026-11-25" and balances["c1"]["outstanding"] is True
    assert balances["c2"]["closes_on"] == "2026-12-25" and balances["c2"]["amount"] == 9000.0
    november = [item for week in result["weeks"] for item in week["items"] if "c1" in (item.get("label") or "")]
    december = [item for week in result["weeks"] for item in week["items"] if "c2" in (item.get("label") or "")]
    assert [(item["date"], item["amount"]) for item in november] == [("2026-11-25", -4000.0)]
    assert [(item["date"], item["amount"]) for item in december] == [("2026-12-25", -9000.0)]


def test_payroll_comes_from_the_budget_definition_on_the_first():
    item = _item(_run(), "שכר")

    assert item["date"] == "2026-11-10"
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

    assert item["date"] == "2026-11-10"
    assert item["amount"] == -9000.0
    assert item["source"] == "plan.budgetLines"


def test_expected_income_comes_from_the_budget_not_from_a_run_rate():
    week = _week(_run(), "2026-10-25")
    income = next(item for item in week["items"] if item["label"] == "הכנסה לפי התקציב")

    assert income["amount"] == 4000.0
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
    payroll_week = _week(result, "2026-11-08")
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

    assert week["start"] == "2026-10-25"
    assert week["end"] == "2026-10-30"
    assert week["in"] == 4000.0
    assert week["out"] == -30000.0
    assert week["net"] == -26000.0
    assert week["closing"] == -38000.0
    assert week["limit"] == 50000.0
    assert week["headroom"] == 12000.0
    rolled = next(item for item in _week(_run(), "2026-11-01")["items"] if item["label"] == "הכנסה לפי התקציב")
    assert rolled["amount"] == 2000.0
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
        "pay_date": "2026-11-10",
    }
    # Default mode: September is paid in October. October has no supplier line,
    # so November's payment stays unknown.
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
    }], "checks": [{
        "check": "4401", "date": "2026-11-12", "amount": 7500, "payee": "לקוח", "discounted": True,
    }]}})


def test_bridge_61000_due_25_11_is_repaid_against_a_receipt_the_same_day():
    plan = _plan()
    plan["liquidityEvidence"]["loans"] = [{
        "label": "גישור", "kind": "bridge", "balance": 61000, "maturity": "2026-11-25",
        "asOf": "2026-10-28", "organizationId": ORG,
    }]

    legs = [item for week in _run(plan=plan)["weeks"] for item in week["items"] if item["date"] == "2026-11-25"]

    assert [leg["amount"] for leg in legs] == [-61000.0, 61000.0]
    assert {leg["label"] for leg in legs} == {"גישור · פירעון הלוואה קצרה", "גישור · תקבול שסוגר את ההלוואה הקצרה"}
    assert sum(leg["amount"] for leg in legs) == 0.0


def test_each_discounted_cheque_is_a_short_loan_on_its_own_date():
    plan = _plan()
    plan["liquidityEvidence"]["checks"] = [
        {"check": "4401", "date": "2026-11-12", "amount": 7500, "payee": "לקוח א", "discounted": True, "organizationId": ORG},
        {"check": "4402", "date": "2026-12-03", "amount": 2200, "payee": "לקוח ב", "discounted": True, "organizationId": ORG},
    ]
    view = _view()
    view["liquidity"]["checks"] = [
        {"check": "4401", "date": "2026-11-12", "amount": 7500, "payee": "לקוח א", "state": "future"},
    ]

    result = _run(view, plan)
    items = [item for week in result["weeks"] for item in week["items"] if "4401" in (item.get("label") or "")]

    assert [item["date"] for item in items] == ["2026-11-12"]
    assert [item["amount"] for item in items] == [-7500.0]
    assert items[0]["loan_balance"] == 7500.0
    later = [item for week in result["weeks"] for item in week["items"] if "4402" in (item.get("label") or "")]
    assert [item["date"] for item in later] == ["2026-12-03"]
    assert [item["amount"] for item in later] == [-2200.0]
    balances = {row["check"]: row for row in result["discounted_cheque_balances"]}
    assert balances["4401"]["closes_on"] == "2026-11-12" and balances["4401"]["outstanding"] is True
    assert balances["4402"]["closes_on"] == "2026-12-03" and balances["4402"]["amount"] == 2200.0


def _office_dashboard(client, platform_admin, fresh_org, slug):
    chef, food, office = fresh_org(), fresh_org(), fresh_org()
    response = client.post("/api/dashboards", headers=platform_admin["headers"], json={
        "primary_organization_id": chef["org_id"], "slug": slug, "title": "שף", "access_mode": "link",
    })
    assert response.status_code == 201, response.text
    dashboard_id = response.json()["id"]
    with SessionLocal() as db:
        db.get(ClientDashboard, dashboard_id).office_organization_id = office["org_id"]
        for org, name in ((chef, "השף"), (food, "פוד גרופ")):
            db.add(SumitCompany(
                office_organization_id=office["org_id"], company_id=f"file-{org['org_id']}",
                name=name, status="active", target_organization_id=org["org_id"],
            ))
        db.commit()
    added = client.post(f"/api/dashboards/{dashboard_id}/entities", headers=platform_admin["headers"],
                        json={"organization_id": food["org_id"], "label": "פוד גרופ"})
    assert added.status_code == 201, added.text
    return dashboard_id, chef, food, added.json()["id"]


def _save_plan(client, headers, dashboard_id, payload):
    current = client.get(f"/api/dashboards/{dashboard_id}/plan", headers=headers).json()
    response = client.put(
        f"/api/dashboards/{dashboard_id}/plan",
        headers={**headers, "If-Match": current["version"] or "null"},
        json={"payload": payload},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_food_group_hapoalim_balance_is_the_opening(client, fresh_org, platform_admin):
    """A blocked savings row, and a binding that predates the bank account, do not hide it.

    Root cause: SAVINGS was classified as checking, so a Hapoalim savings account
    with no balance date made every checking balance unknown. A binding that
    listed only a card also dropped the current account synced later onto the
    same organization.
    """
    dashboard_id, _chef, food, _entity_id = _office_dashboard(
        client, platform_admin, fresh_org, "food-hapoalim",
    )
    with SessionLocal() as db:
        checking = Account(
            organization_id=food["org_id"], name="הפועלים עו״ש", account_type=AccountType.BANK,
            raw_account_type="CHECKING", source="open_finance", external_id="hapoalim-checking",
            provider_account_number="12-345-678901", balance=Decimal("-44000"),
            balance_as_of=datetime(2026, 10, 28), currency="ILS",
        )
        savings = Account(
            organization_id=food["org_id"], name="הפועלים פר״י", account_type=AccountType.ASSET,
            raw_account_type="SAVINGS", source="open_finance", external_id="hapoalim-savings",
            balance=Decimal("0"), currency="ILS",
        )
        card = Account(
            organization_id=food["org_id"], name="כאל", account_type=AccountType.LIABILITY,
            raw_account_type="CARD", source="open_finance", external_id="hapoalim-card",
            balance=Decimal("-100"), balance_as_of=datetime(2026, 10, 28), currency="ILS",
        )
        db.add_all([checking, savings, card])
        db.commit()
    body = client.get(
        f"/api/dashboards/{dashboard_id}/view", headers=platform_admin["headers"],
        params={"start": "2026-07-01", "end": "2026-10-28"},
    ).json()
    food_view = next(entity for entity in body["entities"] if entity["label"] == "פוד גרופ")["view"]

    assert food_view["liquidity"]["position"]["balance"] == -44000.0
    assert food_view["liquidity"]["position"]["as_of"] == "2026-10-28"
    assert food_view["liquidity"]["position"]["balance_source"] == "open_finance"
    assert food_view["cash_forecast"]["opening"]["amount"] == -44000.0
    assert "opening_balance" not in food_view["cash_forecast"]["missing"]
    assert body["provider_calls"] == 0


def test_opening_balance_is_checking_only_and_the_facility_is_separate(fresh_org):
    """The forecast opens on Open Finance checking balances. The credit line is headroom."""
    owner = fresh_org()
    synced = datetime(2026, 10, 28, 6, 0)
    with SessionLocal() as db:
        db.add(Account(
            organization_id=owner["org_id"], name="הפועלים עו״ש", account_type=AccountType.BANK,
            raw_account_type="CHECKING", source="open_finance", external_id="chk",
            balance=Decimal("-44000"), balance_as_of=synced, currency="ILS",
            credit_limit=Decimal("80000"),
        ))
        db.add(Account(
            organization_id=owner["org_id"], name="חיסכון", account_type=AccountType.ASSET,
            raw_account_type="SAVINGS", source="open_finance", external_id="sav",
            balance=Decimal("5000"), balance_as_of=synced, currency="ILS",
        ))
        db.add(Account(
            organization_id=owner["org_id"], name="כאל", account_type=AccountType.LIABILITY,
            raw_account_type="CARD", source="open_finance", external_id="card",
            balance=Decimal("-1000"), balance_as_of=synced, currency="ILS",
            credit_limit=Decimal("20000"),
        ))
        db.commit()
        section = liquidity.build_liquidity(
            db, owner["org_id"], date(2026, 10, 1), date(2026, 10, 28), classified=[], today=date(2026, 10, 28),
        )
    view = {"liquidity": section, "cash_statement": {"months": [], "lines": []}}
    result = cash_forecast.build_entity_forecast(
        view, plan=None, organization_id=owner["org_id"], label="פוד גרופ", today=date(2026, 10, 28),
    )

    assert section["position"]["balance"] == -44000.0
    assert section["position"]["as_of"] == "2026-10-28"
    assert section["position"]["balance_source"] == "open_finance"
    assert section["position"]["limit"] == 80000.0
    assert section["position"]["available_to_limit"] == 36000.0
    assert result["opening"]["amount"] == -44000.0
    assert result["opening"]["as_of"] == "2026-10-28"
    assert result["opening"]["source"] == "open_finance"
    assert result["weeks"][0]["start"] == "2026-10-25"
    assert result["weeks"][0]["end"] == "2026-10-30"
    assert result["weeks"][0]["limit"] == 80000.0
    assert result["weeks"][0]["closing"] == -44000.0
    assert result["weeks"][0]["headroom"] == 36000.0
    assert result["provider_calls"] == 0


def test_budget_entry_lines_change_the_13_week_forecast(client, fresh_org, platform_admin):
    """/budget-entry (PR #84) writes plan.budgetLines. That is what the forecast reads."""
    owner = fresh_org()
    created = client.post("/api/dashboards", headers=platform_admin["headers"], json={
        "primary_organization_id": owner["org_id"], "slug": "budget-forecast", "title": "תקציב", "access_mode": "link",
    })
    assert created.status_code == 201, created.text
    dashboard_id = created.json()["id"]
    with SessionLocal() as db:
        db.add(Account(
            organization_id=owner["org_id"], name="עו״ש", account_type=AccountType.BANK,
            raw_account_type="CHECKING", source="open_finance", external_id="checking",
            balance=Decimal("-12000"), balance_as_of=datetime(2026, 10, 28), currency="ILS",
            credit_limit=Decimal("50000"),
        ))
        db.commit()

    def view():
        response = client.get(
            f"/api/dashboards/{dashboard_id}/view", headers=platform_admin["headers"],
            params={"start": "2026-07-01", "end": "2026-10-28"},
        )
        assert response.status_code == 200, response.text
        return response.json()["entities"][0]["view"]["cash_forecast"]

    before = view()
    assert not any(item.get("rule") == "budget_income" for week in before["weeks"] for item in week["items"])

    saved = _save_plan(client, platform_admin["headers"], dashboard_id, {"budgetLines": [
        {"id": "sales", "label": "מכירות", "category": "sales", "kind": "revenue",
         "months": {"2026-10": {"quantity": 1, "rate": 62000}}},
        {"id": "salaries", "label": "שכר", "category": "salaries", "kind": "cost",
         "months": {"2026-11": {"quantity": 1, "rate": 18000}}},
    ]})
    assert saved["payload"]["budgetLines"][0]["months"]["2026-10"]["rate"] == 62000

    after = view()
    income = next(item for week in after["weeks"] for item in week["items"] if item.get("label") == "הכנסה לפי התקציב")
    payroll = next(item for week in after["weeks"] for item in week["items"] if "שכר" in (item.get("label") or ""))
    assert income["amount"] == 4000.0
    assert income["source"] == "plan.budgetLines"
    assert payroll["date"] == "2026-11-10"
    assert payroll["amount"] == -18000.0
    assert payroll["source"] == "plan.budgetLines"
    assert after["opening"]["amount"] == -12000.0
    assert after["weeks"][0]["in"] != before["weeks"][0]["in"]


def test_a_card_only_binding_still_reads_the_connected_checking_account(client, fresh_org, platform_admin):
    dashboard_id, _chef, food, entity_id = _office_dashboard(
        client, platform_admin, fresh_org, "food-binding",
    )
    with SessionLocal() as db:
        checking = Account(
            organization_id=food["org_id"], name="הפועלים עו״ש", account_type=AccountType.BANK,
            raw_account_type="CHECKING", source="open_finance", external_id="hapoalim-2",
            balance=Decimal("-44000"), balance_as_of=datetime(2026, 10, 28), currency="ILS",
        )
        card = Account(
            organization_id=food["org_id"], name="כאל", account_type=AccountType.LIABILITY,
            raw_account_type="CARD", source="open_finance", external_id="card-2",
            balance=Decimal("-100"), balance_as_of=datetime(2026, 10, 28), currency="ILS",
        )
        db.add_all([checking, card])
        db.commit()
        card_id = card.id
    bound = client.put(
        f"/api/dashboards/{dashboard_id}/entities/{entity_id}/accounts",
        headers=platform_admin["headers"],
        json={"accounts": [{"account_id": card_id}]},
    )
    assert bound.status_code == 200, bound.text
    body = client.get(
        f"/api/dashboards/{dashboard_id}/view", headers=platform_admin["headers"],
        params={"start": "2026-07-01", "end": "2026-10-28"},
    ).json()
    food_view = next(entity for entity in body["entities"] if entity["label"] == "פוד גרופ")["view"]
    assert food_view["cash_forecast"]["opening"]["amount"] == -44000.0
