"""The Eliav tool's tabs inside Rezef /d/: budget seed, cash-basis budget vs actual,
liquidity and obligations, forecast, the 23 filing rules, the consolidated
chef + Food Group dashboard. No provider calls."""
import ast
import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from cfo.database import SessionLocal
from cfo.models import (
    Account, AccountType, BankTransaction, Budget, ClientDashboard, DashboardEntity,
    DashboardEntityAccount, DashboardPlan, SumitCompany,
)
from cfo.services.dashboards import eliav_import, filing, forecast, liquidity
from cfo.services.dashboards.service import DashboardError, validate_filing_payload

SEED = Path(__file__).parent / "fixtures" / "eliav_budget_seed_shape.json"
TOOL_RULE_ORDER = [
    "intercompany", "sales_card", "card_bills", "check_discounting", "loans_in", "loans_out",
    "interest", "bank_fees", "tax_refund", "sales_cash", "customer_checks", "reversal",
    "bank_journal", "supplier_checks", "national_insurance", "pension_insurance", "fuel_energy",
    "vehicles", "office", "cash_withdrawals", "transfers_out", "other_in", "suppliers_direct",
]


def _create(client, headers, org_id, slug):
    response = client.post("/api/dashboards", headers=headers, json={
        "primary_organization_id": org_id, "slug": slug, "title": "שף אליהב",
        "access_mode": "link",
    })
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _save(client, headers, dashboard_id, payload):
    current = client.get(f"/api/dashboards/{dashboard_id}/plan", headers=headers).json()
    return client.put(
        f"/api/dashboards/{dashboard_id}/plan",
        headers={**headers, "If-Match": current["version"] or "null"},
        json={"payload": payload},
    )


def _bank(db, org_id, day, amount, description, *, account_id=None, raw=None):
    row = BankTransaction(
        organization_id=org_id, account_id=account_id, transaction_date=day,
        amount=Decimal(str(amount)), description=description, raw_data=raw,
    )
    db.add(row)
    db.flush()
    return row


def _account(db, org_id, name, raw_type, balance, *, limit=None, source="open_finance",
             as_of=datetime(2026, 10, 19)):
    row = Account(
        organization_id=org_id, name=name, account_type=AccountType.BANK, raw_account_type=raw_type,
        balance=Decimal(str(balance)), credit_limit=None if limit is None else Decimal(str(limit)),
        source=source, balance_as_of=as_of,
    )
    db.add(row)
    db.flush()
    return row


# ---------------------------------------------------------------- budget seed

def test_seed_of_127_lines_imports_in_the_canonical_format_and_keeps_filing(client, fresh_org):
    owner = fresh_org()
    dashboard_id = _create(client, owner["headers"], owner["org_id"], "eliav-seed-import")
    rule = {"id": "r1", "contains": "טחנת", "field": "description", "direction": "out",
            "category": "supplier_transfers"}
    assert _save(client, owner["headers"], dashboard_id, {"statusRules": [rule]}).status_code == 200
    seed = json.loads(SEED.read_text(encoding="utf-8"))
    assert len(seed) == 127
    months = [f"2026-{m:02d}" for m in range(1, 13)]
    document = eliav_import.seed_export(seed, months)
    with SessionLocal() as db:
        dry = eliav_import.import_plan(db, dashboard_id, document, apply=False, budget_only=True)
        assert dry["applied"] is False and dry["budget_lines"] == 127
        assert db.get(DashboardPlan, dashboard_id).payload == {"statusRules": [rule]}
        done = eliav_import.import_plan(db, dashboard_id, document, apply=True, budget_only=True)
        assert done["applied"] is True
        again = eliav_import.import_plan(db, dashboard_id, document, apply=True, budget_only=True)
        assert again["idempotent"] is True and again["applied"] is False
        payload = db.get(DashboardPlan, dashboard_id).payload
        budgets = db.query(Budget).filter_by(organization_id=owner["org_id"]).all()
    assert payload["statusRules"] == [rule]
    lines = payload["budgetLines"]
    assert len(lines) == 127
    assert all(set(line) >= {"id", "label", "category", "kind", "months"} for line in lines)
    budgeted = [line for line in lines if line["months"]]
    assert len(budgeted) == 4 and all(len(line["months"]) == 12 for line in budgeted)
    kinds = {line["kind"] for line in lines}
    assert kinds == {"revenue", "cost", "financing"}
    principal = [line for line in lines if line["id"].endswith("_principal")]
    assert principal and all(line["category"] == "loan_principal" for line in principal)
    assert next(line for line in lines if line["id"] == "overhead_bank_fees")["category"] == "bank_fees"
    # Only P&L categories reach ``budgets``; payroll is 49,700 a month, as in the tool.
    by_month = {}
    for row in budgets:
        by_month.setdefault(row.month, {})[row.category_name] = float(row.budgeted_amount)
    assert set(by_month) == set(range(1, 13))
    assert by_month[8] == {"salaries": 49700.0}
    partial = payload["eliavImport"]["lines"]["wage_01"]["defaults"]
    assert partial == {"quantity": None, "rate": 57}
    # The editor can save the imported plan back unchanged.
    assert _save(client, owner["headers"], dashboard_id, payload).status_code == 200


def test_financing_lines_stay_on_the_plan_and_are_not_projected(client, fresh_org):
    owner = fresh_org()
    dashboard_id = _create(client, owner["headers"], owner["org_id"], "eliav-financing-line")
    response = _save(client, owner["headers"], dashboard_id, {"budgetLines": [
        {"id": "loan", "label": "קרן הלוואה", "category": "loan_principal", "kind": "financing",
         "months": {"2026-11": {"quantity": 1, "rate": 7835.97}}},
        {"id": "pay", "label": "שכר", "category": "salaries", "kind": "cost",
         "months": {"2026-11": {"quantity": 1, "rate": 49700}}},
    ]})
    assert response.status_code == 200, response.text
    with SessionLocal() as db:
        rows = db.query(Budget).filter_by(organization_id=owner["org_id"]).all()
    assert [(row.category_name, float(row.budgeted_amount)) for row in rows] == [("salaries", 49700.0)]
    bad = _save(client, owner["headers"], dashboard_id, {"budgetLines": [
        {"id": "x", "label": "x", "category": "loan_principal", "kind": "cost", "months": {}},
    ]})
    assert bad.status_code == 422
    filing_body = client.get(f"/api/dashboards/{dashboard_id}/filing", headers=owner["headers"]).json()
    assert {"key": "loan_principal", "label_he": "החזרי קרן — הלוואות וליסינג", "kind": "financing"} in filing_body["budget_categories"]


# ------------------------------------------------- cash-basis budget vs actual

def test_cash_basis_month_compares_the_salary_budget_with_payroll(client, fresh_org):
    owner = fresh_org()
    dashboard_id = _create(client, owner["headers"], owner["org_id"], "eliav-cash-bva")
    with SessionLocal() as db:
        _bank(db, owner["org_id"], date(2026, 8, 5), 11800, "הפקדת מזומן")
        _bank(db, owner["org_id"], date(2026, 8, 9), -30000, "שכר", raw={"creditorName": "עובד"})
        bank_id = db.query(BankTransaction).filter_by(organization_id=owner["org_id"], description="שכר").one().id
        db.commit()
    payload = {
        "statusDecisions": {str(bank_id): {
            "category": "salaries", "organizationId": owner["org_id"], "date": "2026-08-09",
            "amount": -30000, "note": None,
        }},
        "budgetLines": [
            {"id": "pay", "label": "שכר", "category": "salaries", "kind": "cost",
             "months": {"2026-08": {"quantity": 1, "rate": 49700}}},
            {"id": "dep", "label": "פחת", "category": "depreciation", "kind": "cost",
             "months": {"2026-08": {"quantity": 1, "rate": 1000}}},
        ],
    }
    assert _save(client, owner["headers"], dashboard_id, payload).status_code == 200
    view = client.get(f"/api/dashboards/{dashboard_id}/view", headers=owner["headers"],
                      params={"start": "2026-08-01", "end": "2026-08-31"}).json()
    august = view["budget_vs_actual"]["months"][0]
    assert august["source"] == "cash_basis"
    lines = {line["category"]: line for line in august["categories"]}
    assert "salaries" not in lines
    assert lines["payroll"]["budget"] == 49700 and lines["payroll"]["actual"] == 30000
    assert lines["payroll"]["variance"] == -19700
    assert lines["depreciation"]["budget"] == 1000 and lines["depreciation"]["actual"] is None
    assert lines["revenue"]["actual"] == 10000


# ----------------------------------------------------------------- liquidity

def _liquidity_fixture(db, org_id):
    checking = _account(db, org_id, "עו״ש 8954", "CHECKING", -31873.87, limit=15000)
    _account(db, org_id, "ויזה כאל זהב", "CARD", -5698.78)
    _account(db, org_id, "ניידת מעל 31 חודש", "LOAN", -6725.49)
    _account(db, org_id, "מסגרת אשראי בשח", "LOAN", -31873.87)
    _account(db, org_id, "חשבון ידני", "CHECKING", 999, source="manual")
    booked = {"status": "BOOKED"}
    _bank(db, org_id, date(2026, 10, 5), -100, "עמלה", account_id=checking.id,
          raw={**booked, "balancePerEndDay": "-10000"})
    _bank(db, org_id, date(2026, 10, 12), -2508, "שיק 10005", account_id=checking.id,
          raw={**booked, "balancePerEndDay": "-20000"})
    _bank(db, org_id, date(2026, 10, 14), -700, "הלוואה קרן/כללי", account_id=checking.id,
          raw={**booked, "balancePerEndDay": "-20700"})
    _bank(db, org_id, date(2026, 10, 14), -50, "ריבית", account_id=checking.id,
          raw={**booked, "balancePerEndDay": "-20700"})
    _bank(db, org_id, date(2026, 10, 15), 10, "x", account_id=checking.id,
          raw={**booked, "balancePerEndDay": "-1"})
    _bank(db, org_id, date(2026, 10, 15), 20, "y", account_id=checking.id,
          raw={**booked, "balancePerEndDay": "-2"})
    return checking


EVIDENCE = {
    "observedAt": "2026-10-15T13:08:23Z",
    "loans": [{"label": "גישור על פער בתזרים", "balance": 62708.33, "asOf": "2026-10-14",
               "maturity": "2026-10-25"}],
    "checks": [
        {"check": "10005", "date": "2026-10-12", "amount": 2508, "payee": "ספק א"},
        {"check": "10006", "date": "2026-11-17", "amount": 2506, "payee": "ספק א"},
        {"check": "10009", "date": "2026-10-16", "amount": 3040, "payee": "ספק ב"},
        {"check": "10004", "date": "2026-10-01", "amount": 999, "payee": "ספק ג"},
    ],
    "events": [{"date": "2026-12-31", "label": "מסגרת חח\"ד · סוף תוקף", "kind": "facility_expiry",
                "amount": None}],
}


def test_liquidity_reads_accounts_daily_balances_checks_and_debt_service(client, fresh_org):
    owner = fresh_org()
    with SessionLocal() as db:
        _liquidity_fixture(db, owner["org_id"])
        db.commit()
        section = liquidity.build_liquidity(
            db, owner["org_id"], date(2026, 10, 1), date(2026, 10, 19),
            plan={"liquidityEvidence": EVIDENCE}, today=date(2026, 10, 19),
        )
    assert section["provider_calls"] == 0
    assert section["position"] == {
        "balance": -31873.87, "as_of": "2026-10-19", "balance_source": "accounts", "limit": 15000.0,
        "limit_source": "accounts.credit_limit", "available_to_limit": -16873.87,
    }
    # The manual account is not Open Finance and is not read without a binding.
    assert {a["kind"] for a in section["accounts"]} == {"checking", "card", "loan", "credit_line_mirror"}
    assert section["cards"][0]["balance"] == 5698.78
    assert [loan["name"] for loan in section["loans"]] == ["ניידת מעל 31 חודש", "גישור על פער בתזרים"]
    october = section["months"][0]
    # 15.10 carries two different closings and is left out.
    assert october["days"] == 3 and october["min"] == -20700 and october["negative_days"] == 3
    assert october["beyond_limit_days"] == 2 and october["last"] == -20700
    assert section["balance_conflicts"] == 1
    states = {c["check"]: c["state"] for c in section["checks"]}
    # 10009 is after the last bank day (15.10): no coverage, not "not found".
    assert states == {"10005": "cleared", "10006": "future", "10009": "no_coverage", "10004": "not_found"}
    kinds = [item["kind"] for item in section["upcoming"]]
    assert kinds == ["loan_maturity", "check", "facility_expiry"]
    # The maturity's amount is the loan's last known balance, labelled as such.
    assert section["upcoming"][0]["amount"] == -62708.33
    assert section["upcoming"][0]["amount_basis"] == "outstanding_balance"
    assert "2026-10-14" in section["upcoming"][0]["note"]
    # The facility expiry names no account, so nothing is filled in for it.
    assert section["upcoming"][2]["amount"] is None and section["upcoming"][2]["note"] == "הסכום לא מתועד"
    assert section["debt_service"] == [{"month": "2026-10", "principal": 700.0, "interest": 50.0, "new_loans": 0.0}]
    debts = {d["label"]: d["amount"] for d in section["debts"]}
    # The credit-line account mirrors the overdraft and is not counted twice.
    assert debts == {
        "מינוס בעו״ש": 31873.87, "כרטיסי אשראי": 5698.78,
        "הלוואה — ניידת מעל 31 חודש": 6725.49, "הלוואה — גישור על פער בתזרים": 62708.33,
    }
    assert section["debts_known_total"] == round(31873.87 + 5698.78 + 6725.49 + 62708.33, 2)


def test_bound_accounts_limit_what_liquidity_reads(client, fresh_org, platform_admin):
    owner = fresh_org()
    dashboard_id = _create(client, platform_admin["headers"], owner["org_id"], "eliav-bound-accounts")
    with SessionLocal() as db:
        checking = _liquidity_fixture(db, owner["org_id"])
        manual = db.query(Account).filter_by(organization_id=owner["org_id"], source="manual").one()
        entity = db.query(DashboardEntity).filter_by(dashboard_id=dashboard_id).one()
        db.commit()
        checking_id, manual_id, entity_id = checking.id, manual.id, entity.id
    response = client.put(
        f"/api/dashboards/{dashboard_id}/entities/{entity_id}/accounts", headers=platform_admin["headers"],
        json={"accounts": [{"account_id": checking_id, "display_label": "עו״ש מזרחי"}, {"account_id": manual_id}]},
    )
    assert response.status_code == 200, response.text
    assert [a["account_id"] for a in response.json()["accounts"]] == sorted([checking_id, manual_id])
    view = client.get(f"/api/dashboards/{dashboard_id}/view", headers=platform_admin["headers"],
                      params={"start": "2026-10-01", "end": "2026-10-19"}).json()
    section = view["entities"][0]["view"]["liquidity"]
    assert sorted(a["name"] for a in section["accounts"]) == ["חשבון ידני", "עו״ש 8954"]
    assert section["position"]["balance"] == round(-31873.87 + 999, 2)
    assert view["entities"][0]["accounts"] == [
        {"account_id": checking_id, "display_label": "עו״ש מזרחי"},
        {"account_id": manual_id, "display_label": "חשבון ידני"},
    ]


# ------------------------------------------------------------------ forecast

def test_forecast_uses_budget_first_then_the_median_with_growth():
    months = [
        {"month": "2026-07", "source": "cash_basis", "revenue": 100.0, "costs": 50.0},
        {"month": "2026-08", "source": "cash_basis", "revenue": 300.0, "costs": 70.0},
        {"month": "2026-09", "source": "ledger", "revenue": 200.0, "costs": 60.0},
        {"month": "2026-10", "source": "cash_basis", "revenue": 1.0, "costs": 1.0},  # current month
        {"month": "2026-06", "source": None, "revenue": None, "costs": None},
    ]
    plan = {"statusParameters": {"horizonMonths": 3, "revenueGrowthPct": 10, "costGrowthPct": 0}}
    out = forecast.build_forecast(
        months, as_of=date(2026, 10, 19), plan=plan,
        debt_service=[{"month": m, "principal": p} for m, p in (("2026-07", 10.0), ("2026-08", 30.0), ("2026-09", 20.0))],
        budget_sums={"2026-12": {"cost": 49700.0}}, opening_balance=-1000.0,
    )
    assert out["months"] == ["2026-11", "2026-12", "2027-01"]
    assert out["based_on"] == ["2026-07", "2026-08", "2026-09"]
    revenue = {m: c["value"] for m, c in out["rows"][0]["months"].items()}
    assert revenue == {"2026-11": 220.0, "2026-12": 242.0, "2027-01": 266.2}
    costs = out["rows"][1]["months"]
    assert costs["2026-12"] == {"value": 49700.0, "source": "budget"}
    assert costs["2026-11"] == {"value": 60.0, "source": "trend"}
    november = out["totals"]["2026-11"]
    assert november["result"] == 160.0 and november["principal"] == 20.0 and november["cash_flow"] == 140.0
    assert november["projected_balance"] == -860.0
    assert out["provider_calls"] == 0


def test_forecast_without_history_is_unknown_not_zero():
    out = forecast.build_forecast([], as_of=date(2026, 10, 19))
    assert out["status"] == "unknown"
    assert all(cell["value"] is None for row in out["rows"] for cell in row["months"].values())
    assert all(total["cumulative_cash"] is None for total in out["totals"].values())


# ---------------------------------------------------------- filing rules (23)

def test_the_23_builtin_rules_are_listed_in_the_tool_order_with_a_hash():
    manifest = filing.builtin_rules_manifest()
    assert manifest["count"] == 23
    assert [rule["id"] for rule in manifest["rules"]] == TOOL_RULE_ORDER
    assert [rule["id"] for rule in manifest["rules"] if rule["fallback"]] == ["other_in", "suppliers_direct"]
    assert manifest == filing.builtin_rules_manifest()
    golden = json.loads((Path(__file__).parent / "fixtures" / "eliav_filing_golden.json").read_text(encoding="utf-8"))
    assert golden  # the golden table still runs in test_filing_* against the same rules


def test_filing_report_shows_every_builtin_rule_and_the_pin_status(client, fresh_org):
    owner = fresh_org()
    dashboard_id = _create(client, owner["headers"], owner["org_id"], "eliav-rules-pin")
    body = client.get(f"/api/dashboards/{dashboard_id}/filing", headers=owner["headers"]).json()
    builtin = [rule["category"] for rule in body["rules"] if rule["source"] == "builtin"]
    assert sorted(builtin) == sorted(TOOL_RULE_ORDER)
    assert body["builtin_manifest"]["in_sync"] is None
    manifest = filing.builtin_rules_manifest()
    pin = {"sha256": manifest["sha256"], "rules": manifest["rules"], "source": "eliav-tool db15"}
    assert _save(client, owner["headers"], dashboard_id, {"filingRulesBuiltin": pin}).status_code == 200
    body = client.get(f"/api/dashboards/{dashboard_id}/filing", headers=owner["headers"]).json()
    assert body["builtin_manifest"]["in_sync"] is True
    stale = {**pin, "sha256": "0" * 64}
    assert _save(client, owner["headers"], dashboard_id, {"filingRulesBuiltin": stale}).status_code == 200
    body = client.get(f"/api/dashboards/{dashboard_id}/filing", headers=owner["headers"]).json()
    assert body["builtin_manifest"]["in_sync"] is False


@pytest.mark.parametrize("payload", [
    {"filingRulesBuiltin": {"sha256": "x", "rules": []}},
    {"filingRulesBuiltin": {"sha256": "0" * 64, "rules": [{"category": "nope"}]}},
    {"statusParameters": {"horizonMonths": 13}},
    {"statusParameters": {"vatRate": 0.5}},
    {"statusParameters": {"unknown": 1}},
    {"liquidityEvidence": {"checks": [{"check": "1", "date": "2026-13-01", "amount": 5}]}},
    {"liquidityEvidence": {"loans": [{"label": "x", "balance": -5}]}},
    {"liquidityEvidence": {"cars": []}},
])
def test_plan_rejects_bad_parameters_evidence_and_pins(payload):
    with pytest.raises(DashboardError):
        validate_filing_payload(payload)


def test_plan_accepts_the_tool_parameters_and_evidence():
    validate_filing_payload({
        "statusParameters": {"scenario": "בסיס", "horizonMonths": 6, "revenueGrowthPct": 0,
                             "costGrowthPct": 1.5, "vatRate": 0.18},
        "liquidityEvidence": EVIDENCE,
    })


# ----------------------------------------------- consolidated chef + Food Group

def _roster(db, office_id, target_id, name):
    db.add(SumitCompany(office_organization_id=office_id, company_id=f"file-{target_id}", name=name,
                        status="active", target_organization_id=target_id))


def test_consolidated_dashboard_adds_food_group_and_files_both(client, fresh_org, platform_admin):
    chef, food, office, other = fresh_org(), fresh_org(), fresh_org(), fresh_org()
    dashboard_id = _create(client, platform_admin["headers"], chef["org_id"], "eliav-consolidated")
    with SessionLocal() as db:
        db.get(ClientDashboard, dashboard_id).office_organization_id = office["org_id"]
        _roster(db, office["org_id"], chef["org_id"], "השף")
        _roster(db, office["org_id"], food["org_id"], "פוד גרופ")
        _roster(db, other["org_id"], other["org_id"], "זר")
        _account(db, chef["org_id"], "עו״ש 8954", "CHECKING", -100, limit=15000)
        _bank(db, chef["org_id"], date(2026, 9, 3), 500, "העברה נכנסת לא ידועה")
        _bank(db, food["org_id"], date(2026, 9, 4), -800, "העברה לספק")
        db.commit()
    wrong = client.post(f"/api/dashboards/{dashboard_id}/entities", headers=platform_admin["headers"],
                        json={"organization_id": other["org_id"], "label": "זר"})
    assert wrong.status_code == 404  # outside the dashboard's office
    denied = client.post(f"/api/dashboards/{dashboard_id}/entities", headers=chef["headers"],
                         json={"organization_id": food["org_id"], "label": "פוד גרופ"})
    assert denied.status_code == 404
    added = client.post(f"/api/dashboards/{dashboard_id}/entities", headers=platform_admin["headers"],
                        json={"organization_id": food["org_id"], "label": "פוד גרופ"})
    assert added.status_code == 201, added.text
    again = client.post(f"/api/dashboards/{dashboard_id}/entities", headers=platform_admin["headers"],
                        json={"organization_id": food["org_id"], "label": "פוד גרופ"})
    assert again.status_code == 409
    listed = client.get(f"/api/dashboards/{dashboard_id}/entities", headers=platform_admin["headers"]).json()
    assert [entity["role"] for entity in listed["entities"]] == ["primary", "related"]
    with SessionLocal() as db:
        # A local import: balance 0 without a date is unknown, not zero.
        food_account = _account(db, food["org_id"], "הפועלים 1662", "CHECKING", 0,
                                source="local_import", as_of=None)
        db.commit()
        food_account_id = food_account.id
    foreign = client.put(
        f"/api/dashboards/{dashboard_id}/entities/{listed['entities'][0]['id']}/accounts",
        headers=platform_admin["headers"], json={"accounts": [{"account_id": food_account_id}]},
    )
    assert foreign.status_code == 422 and foreign.json()["error"]["code"] == "account_not_in_entity"

    filing_body = client.get(f"/api/dashboards/{dashboard_id}/filing", headers=platform_admin["headers"]).json()
    entities = {item["entity"] for item in filing_body["review"]["items"]}
    assert len(entities) == 2 and "פוד גרופ" in entities
    view = client.get(f"/api/dashboards/{dashboard_id}/view", headers=platform_admin["headers"],
                      params={"start": "2026-07-01", "end": "2026-10-19"}).json()
    combined = view["combined"]
    assert combined["liquidity"]["balance"] is None  # Food Group's checking balance is not known
    assert combined["liquidity"]["balance_note"]
    assert combined["forecast"]["months"][0] == "2026-11"
    assert combined["forecast"]["provider_calls"] == 0
    assert view["entities"][0]["view"]["liquidity"]["position"]["balance"] == -100


def test_public_view_has_no_account_ids(client, fresh_org, platform_admin):
    owner = fresh_org()
    dashboard_id = _create(client, platform_admin["headers"], owner["org_id"], "eliav-public-ids")
    with SessionLocal() as db:
        _liquidity_fixture(db, owner["org_id"])
        db.commit()
    client.patch(f"/api/dashboards/{dashboard_id}", headers=platform_admin["headers"],
                 json={"status": "active", "access_mode": "public"})
    body = client.get("/api/public/d/eliav-public-ids").json()
    text = json.dumps(body, ensure_ascii=False)
    assert "account_id" not in text and "organization_id" not in text
    assert body["liquidity"]["position"]["balance"] == -31873.87
    assert "forecast" in body


def test_new_modules_do_not_call_a_provider():
    for module in (liquidity, forecast):
        tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
        imported = {
            alias.name for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        } | {
            node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
        }
        assert not any("sumit" in name.lower() or "open_finance" in name.lower() or "financy" in name.lower()
                       for name in imported)


def _importer():
    import importlib.util
    path = Path(__file__).resolve().parents[1] / "scripts" / "import_eliav_plan.py"
    spec = importlib.util.spec_from_file_location("import_eliav_plan_port", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cli_imports_the_seed_dry_run_first(client, fresh_org, capsys):
    owner = fresh_org()
    dashboard_id = _create(client, owner["headers"], owner["org_id"], "eliav-seed-cli")
    importer = _importer()
    args = ["--dashboard-id", str(dashboard_id), "--seed", str(SEED), "--months", "2026-01:2026-03",
            "--budget-only"]
    assert importer.main(args) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["applied"] is False and printed["budget_lines"] == 127 and printed["budget_only"] is True
    assert {row["month"] for row in printed["budget_diff"]} == {"2026-01", "2026-02", "2026-03"}
    with SessionLocal() as db:
        assert db.get(DashboardPlan, dashboard_id) is None
    assert importer.main([*args, "--apply"]) == 0
    assert json.loads(capsys.readouterr().out)["applied"] is True


def test_cli_refuses_a_remote_database_without_both_guards(monkeypatch):
    from cfo.config import settings
    importer = _importer()
    monkeypatch.setattr(settings, "database_url", "postgresql://u:p@db.example.invalid/x")
    with pytest.raises(SystemExit):
        importer._assert_database(allow_remote=False, writes=False)
    importer._assert_database(allow_remote=True, writes=False)
    monkeypatch.delenv("REZEF_ALLOW_REMOTE_WRITE", raising=False)
    with pytest.raises(SystemExit):
        importer._assert_database(allow_remote=True, writes=True)
    monkeypatch.setenv("REZEF_ALLOW_REMOTE_WRITE", "1")
    importer._assert_database(allow_remote=True, writes=True)
