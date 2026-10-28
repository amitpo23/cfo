"""Fixes from the owner's check of /d/eliav: the consolidated budget-vs-actual
shape, the legacy /budget page, the consolidated bank balance and credit line,
upcoming amounts, and the number of queries one /view makes. No provider calls."""
import os
import shutil
import subprocess
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import event

from cfo.database import SessionLocal, engine
from cfo.models import (
    Account, AccountType, BankTransaction, ClientDashboard, Invoice, InvoiceStatus, SumitCompany,
    Transaction, TransactionType,
)
from cfo.services.dashboards import liquidity, multi_entity, view_model
from cfo.services.financial_reports_service import FinancialReportsService

REPO = Path(__file__).resolve().parent.parent


def _create(client, headers, org_id, slug):
    response = client.post("/api/dashboards", headers=headers, json={
        "primary_organization_id": org_id, "slug": slug, "title": "שף אליהב", "access_mode": "link",
    })
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _save(client, headers, dashboard_id, payload):
    current = client.get(f"/api/dashboards/{dashboard_id}/plan", headers=headers).json()
    response = client.put(
        f"/api/dashboards/{dashboard_id}/plan",
        headers={**headers, "If-Match": current["version"] or "null"}, json={"payload": payload},
    )
    assert response.status_code == 200, response.text
    return response


def _bank(db, org_id, day, amount, description, *, account_id=None, raw=None):
    row = BankTransaction(
        organization_id=org_id, account_id=account_id, transaction_date=day,
        amount=Decimal(str(amount)), description=description, raw_data=raw,
    )
    db.add(row)
    db.flush()
    return row


def _account(db, org_id, name, balance, *, limit=None, source="open_finance", as_of=datetime(2026, 10, 19)):
    row = Account(
        organization_id=org_id, name=name, account_type=AccountType.BANK, raw_account_type="CHECKING",
        balance=None if balance is None else Decimal(str(balance)),
        credit_limit=None if limit is None else Decimal(str(limit)), source=source, balance_as_of=as_of,
    )
    db.add(row)
    db.flush()
    return row


def _consolidated(client, platform_admin, fresh_org, slug):
    chef, food, office = fresh_org(), fresh_org(), fresh_org()
    dashboard_id = _create(client, platform_admin["headers"], chef["org_id"], slug)
    with SessionLocal() as db:
        db.get(ClientDashboard, dashboard_id).office_organization_id = office["org_id"]
        for org, name in ((chef, "השף"), (food, "פוד גרופ")):
            db.add(SumitCompany(office_organization_id=office["org_id"], company_id=f"file-{org['org_id']}",
                                name=name, status="active", target_organization_id=org["org_id"]))
        db.commit()
    added = client.post(f"/api/dashboards/{dashboard_id}/entities", headers=platform_admin["headers"],
                        json={"organization_id": food["org_id"], "label": "פוד גרופ"})
    assert added.status_code == 201, added.text
    return dashboard_id, chef, food


def _bind(client, platform_admin, dashboard_id, account_id, *, index=1):
    entities = client.get(f"/api/dashboards/{dashboard_id}/entities", headers=platform_admin["headers"]).json()
    entity_id = entities["entities"][index]["id"]
    bound = client.put(f"/api/dashboards/{dashboard_id}/entities/{entity_id}/accounts",
                       headers=platform_admin["headers"], json={"accounts": [{"account_id": account_id}]})
    assert bound.status_code == 200, bound.text


# ------------------------------------------- 1. consolidated budget vs actual

def test_consolidated_budget_months_have_the_totals_the_tab_reads(client, fresh_org, platform_admin):
    dashboard_id, chef, food = _consolidated(client, platform_admin, fresh_org, "eliav-ui-bva")
    with SessionLocal() as db:
        _bank(db, chef["org_id"], date(2026, 8, 5), 11800, "הפקדת מזומן")
        _bank(db, chef["org_id"], date(2026, 8, 9), -30000, "שכר עובדים")
        _bank(db, food["org_id"], date(2026, 8, 10), 5900, "הפקדת מזומן")
        db.commit()
    _save(client, platform_admin["headers"], dashboard_id, {"budgetLines": [
        {"id": "pay", "label": "שכר", "category": "salaries", "kind": "cost",
         "months": {"2026-08": {"quantity": 1, "rate": 49700}}},
        {"id": "rev", "label": "מכירות", "category": "sales", "kind": "revenue",
         "months": {"2026-08": {"quantity": 1, "rate": 20000}}},
    ]})
    view = client.get(f"/api/dashboards/{dashboard_id}/view", headers=platform_admin["headers"],
                      params={"start": "2026-08-01", "end": "2026-08-31"}).json()
    combined = view["combined"]["budget_vs_actual"]
    assert combined["status"] == "ready"
    august = combined["months"][0]
    # The tab reads month.totals.revenue / .costs; without them the page went blank.
    assert set(august["totals"]) == {"revenue", "costs"}
    for total in august["totals"].values():
        assert set(total) == {"budget", "actual", "variance", "variance_pct"}
    assert august["totals"]["revenue"]["budget"] == 20000
    assert august["totals"]["revenue"]["actual"] == round(11800 / 1.18 + 5900 / 1.18, 2)
    assert august["totals"]["costs"]["budget"] == 49700
    assert august["source"] == "cash_basis" and august["source_label"]
    assert isinstance(august["blocked"], bool)
    # The same shape as one entity's month.
    single = view["entities"][0]["view"]["budget_vs_actual"]["months"][0]
    assert set(single) <= set(august) | {"period_start", "period_end"}


def test_dashboard_tabs_render_with_the_payloads_the_api_sends():
    """Server-side render of the tabs (frontend/scripts/dashboard-render-check.mjs)."""
    node = shutil.which("node")
    if node is None or not (REPO / "frontend" / "node_modules" / "esbuild").exists():
        pytest.skip("node or frontend/node_modules is not installed")
    result = subprocess.run(
        [node, str(REPO / "frontend" / "scripts" / "dashboard-render-check.mjs")],
        cwd=REPO, capture_output=True, text=True, timeout=120, env={**os.environ},
    )
    assert result.returncode == 0, result.stdout + result.stderr


# ---------------------------------------------------------- 3. legacy /budget

def test_legacy_budget_page_reads_the_dashboard_comparison_for_the_month(client, fresh_org):
    owner = fresh_org()
    dashboard_id = _create(client, owner["headers"], owner["org_id"], "eliav-ui-legacy")
    with SessionLocal() as db:
        _bank(db, owner["org_id"], date(2026, 8, 5), 11800, "הפקדת מזומן")
        payroll = _bank(db, owner["org_id"], date(2026, 8, 9), -30000, "שכר", raw={"creditorName": "עובד"})
        db.commit()
        payroll_id = payroll.id
    months = {f"2026-{m:02d}": {"quantity": 1, "rate": 49700} for m in range(1, 13)}
    _save(client, owner["headers"], dashboard_id, {
        "statusDecisions": {str(payroll_id): {
            "category": "salaries", "organizationId": owner["org_id"], "date": "2026-08-09",
            "amount": -30000, "note": None,
        }},
        "budgetLines": [{"id": "pay", "label": "שכר", "category": "salaries", "kind": "cost", "months": months}],
    })
    response = client.get("/api/financial/budget/vs-actual", headers=owner["headers"],
                          params={"year": 2026, "month": 8, "period": "month"})
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["source"] == "dashboard" and data["dashboard_slug"] == "eliav-ui-legacy"
    assert data["period"] == "2026-08"
    lines = {line["category_id"]: line for line in data["categories"]}
    # A cash-basis month: the salary budget meets the payroll actual, with a Hebrew label.
    assert lines["payroll"]["category_hebrew"] != "payroll" and "salaries" not in lines
    assert lines["payroll"]["budget_amount"] == 49700 and lines["payroll"]["actual_amount"] == 30000
    assert lines["payroll"]["variance"] == 19700  # legacy sign: budget minus actual
    # The month, not the year: 49,700 and not 596,400.
    assert data["total_budget"] == round(49700 + 0, 2)
    view = client.get(f"/api/dashboards/{dashboard_id}/view", headers=owner["headers"],
                      params={"start": "2026-08-01", "end": "2026-08-31"}).json()
    tab = {line["category"]: line for line in view["budget_vs_actual"]["months"][0]["categories"]}
    assert tab["payroll"]["actual"] == lines["payroll"]["actual_amount"]


def test_legacy_budget_year_without_books_keeps_the_actual_unknown(client, fresh_org):
    owner = fresh_org()
    dashboard_id = _create(client, owner["headers"], owner["org_id"], "eliav-ui-legacy-year")
    months = {f"2026-{m:02d}": {"quantity": 1, "rate": 49700} for m in range(1, 13)}
    _save(client, owner["headers"], dashboard_id, {"budgetLines": [
        {"id": "pay", "label": "שכר", "category": "salaries", "kind": "cost", "months": months},
    ]})
    data = client.get("/api/financial/budget/vs-actual", headers=owner["headers"],
                      params={"year": 2026, "period": "year"}).json()["data"]
    assert data["total_budget"] == 596400
    assert data["total_actual"] is None  # no books and no bank rows: unknown, not 0 and not 100%
    line = data["categories"][0]
    assert line["category_hebrew"] == "משכורות"
    assert line["actual_amount"] is None and line["variance_percentage"] is None and line["status"] == "unknown"


def test_legacy_budget_without_a_dashboard_labels_salaries_in_hebrew(client, fresh_org):
    owner = fresh_org()
    today = date.today()
    created = client.post("/api/financial/budget", headers=owner["headers"], json={
        "category": "salaries", "planned_amount": 1000,
        "period_start": today.replace(day=1).isoformat(), "period_end": today.isoformat(),
    })
    assert created.status_code == 200, created.text
    data = client.get("/api/financial/budget/vs-actual", headers=owner["headers"],
                      params={"year": today.year, "month": today.month}).json()["data"]
    labels = {c["category_id"]: c["category_hebrew"] for c in data["categories"]}
    assert labels["salaries"] == "משכורות"


# --------------------------------------- 4. consolidated balance, credit line

FOOD_RUNNING = [
    # The statement's own running balance, in its own column name.
    ("2026-10-12", "-1000.00", "-40,000.00"),
    ("2026-10-13", "-500.00", "-40,500.00"),
    ("2026-10-13", "200.00", "-40,300.00"),
]


def _imported_rows(db, org_id, account_id, rows, column="יתרה בש\"ח"):
    for index, (day, amount, running) in enumerate(rows):
        db.add(BankTransaction(
            organization_id=org_id, account_id=account_id, transaction_date=date.fromisoformat(day),
            amount=Decimal(amount), description=f"פעולה {index}", source="reviewed_local_import",
            external_id=f"bank:1662:{index}",
            raw_data={"original": {"תאריך": day, "סכום": amount, column: running},
                      "normalized": {"date": day, "amount": amount}},
        ))


def test_imported_bank_balance_comes_from_the_statement_running_balance(client, fresh_org, platform_admin):
    dashboard_id, chef, food = _consolidated(client, platform_admin, fresh_org, "eliav-ui-running")
    with SessionLocal() as db:
        _account(db, chef["org_id"], "עו״ש 8954", -100, limit=15000)
        food_account = _account(db, food["org_id"], "Imported bank 1662", None,
                                source="reviewed_local_import", as_of=None)
        _imported_rows(db, food["org_id"], food_account.id, FOOD_RUNNING)
        db.commit()
        food_account_id = food_account.id
    _bind(client, platform_admin, dashboard_id, food_account_id)
    _save(client, platform_admin["headers"], dashboard_id, {"liquidityEvidence": {"facilities": [
        {"label": "מסגרת עו״ש 1662", "organizationId": food["org_id"], "limit": 80000},
    ]}})
    view = client.get(f"/api/dashboards/{dashboard_id}/view", headers=platform_admin["headers"],
                      params={"start": "2026-07-01", "end": "2026-10-19"}).json()
    food_position = view["entities"][1]["view"]["liquidity"]["position"]
    # The last day's closing is the row no other row of that day follows.
    assert food_position["balance"] == -40300.0
    assert food_position["as_of"] == "2026-10-13"
    assert food_position["balance_source"] == "imported_running_balance"
    assert food_position["limit"] == 80000.0 and food_position["available_to_limit"] == 39700.0
    combined = view["combined"]["liquidity"]
    assert combined["balance"] == -40400.0 and combined["balance_note"] is None
    assert combined["limit"] == 95000.0  # 15,000 (chef account) + 80,000 (Food Group facility)
    assert {entity["entity"]: entity["limit"] for entity in combined["entities"]}["פוד גרופ"] == 80000.0


def test_unknown_imported_balance_shows_the_known_part_and_names_the_entity(client, fresh_org, platform_admin):
    dashboard_id, chef, food = _consolidated(client, platform_admin, fresh_org, "eliav-ui-partial")
    with SessionLocal() as db:
        _account(db, chef["org_id"], "עו״ש 8954", -100, limit=15000)
        food_account = _account(db, food["org_id"], "Imported bank 1662", None,
                                source="reviewed_local_import", as_of=None)
        _bank(db, food["org_id"], date(2026, 10, 13), -500, "בלי יתרה", account_id=food_account.id,
              raw={"original": {"סכום": "-500"}})
        db.commit()
        food_account_id = food_account.id
    _bind(client, platform_admin, dashboard_id, food_account_id)
    _save(client, platform_admin["headers"], dashboard_id, {"liquidityEvidence": {"facilities": [
        {"label": "מסגרת עו״ש 1662", "organizationId": food["org_id"], "limit": 80000},
    ]}})
    view = client.get(f"/api/dashboards/{dashboard_id}/view", headers=platform_admin["headers"],
                      params={"start": "2026-07-01", "end": "2026-10-19"}).json()
    combined = view["combined"]["liquidity"]
    assert combined["balance"] is None
    assert combined["balance_known"] == -100.0
    chef_label = view["entities"][0]["label"]
    assert "פוד גרופ" in combined["balance_note"] and chef_label not in combined["balance_note"]
    by_entity = {entity["entity"]: entity for entity in combined["entities"]}
    assert by_entity[chef_label]["balance"] == -100.0 and by_entity[chef_label]["as_of"] == "2026-10-19"
    assert by_entity["פוד גרופ"]["balance"] is None and by_entity["פוד גרופ"]["limit"] == 80000.0
    assert combined["limit"] == 95000.0  # 15,000 (chef account) + 80,000 (Food Group facility)


def test_running_balance_with_two_closings_on_the_last_day_stays_unknown(fresh_org):
    owner = fresh_org()
    with SessionLocal() as db:
        account = _account(db, owner["org_id"], "Imported bank 1662", None, source="reviewed_local_import", as_of=None)
        _imported_rows(db, owner["org_id"], account.id, [
            ("2026-10-13", "-500.00", "-1,000.00"), ("2026-10-13", "-700.00", "-2,000.00"),
        ], column="Balance")
        db.commit()
        assert liquidity.imported_balance(db, account) is None
        assert liquidity._statement_number("1,234.50-") == -1234.5
        assert liquidity._statement_number("₪ 1,234.50") == 1234.5


# ------------------------------------------------------- 6. upcoming amounts

def test_upcoming_dates_carry_the_amounts_the_evidence_has(fresh_org):
    owner = fresh_org()
    plan = {"liquidityEvidence": {
        "observedAt": "2026-10-15T13:08:23Z",
        "facilities": [{"label": "מסגרת עו״ש 1662", "limit": 80000, "account": "1662"}],
        "loans": [{"label": "הלוואה ללווים חדשים", "balance": 261254.84, "asOf": "2026-10-14",
                   "maturity": "2027-01-10"}],
        "events": [
            {"date": "2026-10-25", "label": "גישור · סיום חוזה", "kind": "loan_maturity",
             "amount": None, "referenceBalance": 62708.33},
            {"date": "2026-12-31", "label": "מסגרת חח\"ד · סוף תוקף", "kind": "facility_expiry",
             "amount": None, "account": "1662"},
            {"date": "2026-11-01", "label": "תשלום ידוע", "kind": "event", "amount": -1200},
            {"date": "2026-11-02", "label": "בלי ראיה", "kind": "event", "amount": None},
        ],
    }}
    with SessionLocal() as db:
        section = liquidity.build_liquidity(db, owner["org_id"], date(2026, 10, 1), date(2026, 10, 19),
                                            plan=plan, today=date(2026, 10, 19))
    by_label = {item["label"]: item for item in section["upcoming"]}
    bridge = by_label["גישור · סיום חוזה"]
    assert bridge["amount"] == -62708.33 and bridge["amount_basis"] == "outstanding_balance"
    assert bridge["amount_as_of"] == "2026-10-15"
    loan = by_label["הלוואה ללווים חדשים · סיום הלוואה"]
    assert loan["amount"] == -261254.84 and loan["amount_as_of"] == "2026-10-14"
    facility = by_label["מסגרת חח\"ד · סוף תוקף"]
    assert facility["amount"] is None and facility["reference_amount"] == 80000.0
    assert "80,000" in facility["note"]
    assert by_label["תשלום ידוע"]["amount"] == -1200 and by_label["תשלום ידוע"]["note"] is None
    # No evidence for it: still unknown, never 0.
    assert by_label["בלי ראיה"]["amount"] is None and by_label["בלי ראיה"]["note"] == "הסכום לא מתועד"


# ----------------------------------------------------- 5. /view query count

def _count_queries(fn):
    seen = {"n": 0}

    def _count(*_args):
        seen["n"] += 1

    event.listen(engine, "before_cursor_execute", _count)
    try:
        fn()
    finally:
        event.remove(engine, "before_cursor_execute", _count)
    return seen["n"]


def test_view_queries_do_not_grow_with_the_number_of_months(client, fresh_org, platform_admin):
    dashboard_id, chef, food = _consolidated(client, platform_admin, fresh_org, "eliav-ui-queries")
    with SessionLocal() as db:
        for org in (chef, food):
            for month in range(1, 11):
                _bank(db, org["org_id"], date(2026, month, 3), 1180, "הפקדת מזומן")
                _bank(db, org["org_id"], date(2026, month, 9), -500, "העברה לספק")
                db.add(Invoice(organization_id=org["org_id"], invoice_number=f"q{org['org_id']}-{month}",
                               issue_date=date(2026, month, 4), status=InvoiceStatus.SENT,
                               subtotal=Decimal("1000"), tax=Decimal("180"), total=Decimal("1180")))
        db.commit()

    def build(end):
        with SessionLocal() as db:
            row = db.get(ClientDashboard, dashboard_id)
            multi_entity.build_dashboard_view(db, row, date(2026, 1, 1), end,
                                              plan=view_model.plan_payload(db, dashboard_id))

    two_months = _count_queries(lambda: build(date(2026, 2, 28)))
    ten_months = _count_queries(lambda: build(date(2026, 10, 19)))
    # Before: about 20 queries per month per entity (each month re-read every
    # document and journal of the organization).
    assert ten_months <= two_months + 4, (two_months, ten_months)
    # Fixed per entity (books P&L, balance sheet), not per month. 136 measured.
    assert ten_months < 150


def test_memoized_reports_give_the_same_ledger_sums(fresh_org):
    owner = fresh_org()
    with SessionLocal() as db:
        account = _account(db, owner["org_id"], "עו״ש", 0)
        for day, amount in ((datetime(2026, 3, 1, 0, 0), 100), (datetime(2026, 3, 31, 23, 59), 50),
                            (datetime(2026, 4, 1, 0, 0), 25)):
            db.add(Transaction(organization_id=owner["org_id"], account_id=account.id,
                               transaction_type=TransactionType.INCOME, amount=Decimal(amount),
                               category="services", transaction_date=day))
        db.add(Invoice(organization_id=owner["org_id"], invoice_number="m1", issue_date=date(2026, 3, 31),
                       status=InvoiceStatus.SENT, subtotal=Decimal("1000"), tax=Decimal("180"),
                       total=Decimal("1180")))
        db.commit()
        plain, memo = FinancialReportsService(db), FinancialReportsService(db, memoize=True)
        for lo, hi in ((date(2026, 3, 1), date(2026, 3, 31)), (date(2026, 4, 1), date(2026, 4, 30)),
                       (date(2026, 3, 15), date(2026, 3, 31))):
            for method in ("_ledger_revenue_items", "_ledger_expense_items"):
                expected = {i.category: i.amount for i in getattr(plain, method)(owner["org_id"], lo, hi, lo, hi, False)}
                got = {i.category: i.amount for i in getattr(memo, method)(owner["org_id"], lo, hi, lo, hi, False)}
                assert got == expected, (method, lo, hi)
