"""Second round of fixes from the owner's check of /d/eliav and /budget: the
budget editor on an imported plan, /budget and the dashboard reading one
comparison, Hebrew category labels, and a manual opening balance for an imported
bank account without a balance column. No provider calls."""
import json
import os
import shutil
import subprocess
from datetime import date
from pathlib import Path

import pytest

from cfo.database import SessionLocal
from cfo.models import DashboardMember, User
from cfo.services.dashboards import eliav_import, plan_budget
from tests.test_dashboard_eliav_ui_fixes import _account, _bank, _bind, _consolidated, _create, _save

REPO = Path(__file__).resolve().parent.parent
SEED = REPO / "tests" / "fixtures" / "eliav_budget_seed_shape.json"
IMPORTED_PLAN = REPO / "tests" / "fixtures" / "eliav_imported_plan.json"
IMPORT_MONTHS = "2026-01:2027-06"


def _member(dashboard_id, org_id, role):
    with SessionLocal() as db:
        user = db.query(User).filter(User.organization_id == org_id).one()
        db.add(DashboardMember(dashboard_id=dashboard_id, user_id=user.id, role=role, status="active"))
        db.commit()


def _put(client, headers, dashboard_id, payload):
    current = client.get(f"/api/dashboards/{dashboard_id}/plan", headers=headers).json()
    return client.put(
        f"/api/dashboards/{dashboard_id}/plan",
        headers={**headers, "If-Match": current["version"] or "null"}, json={"payload": payload},
    )


def _render_check(env: dict) -> subprocess.CompletedProcess:
    node = shutil.which("node")
    if node is None or not (REPO / "frontend" / "node_modules" / "esbuild").exists():
        pytest.skip("node or frontend/node_modules is not installed")
    return subprocess.run(
        [node, str(REPO / "frontend" / "scripts" / "dashboard-render-check.mjs")],
        cwd=REPO, capture_output=True, text=True, timeout=120, env={**os.environ, **env},
    )


# ------------------------------------- 1. budget editor on the imported plan

def _import_document():
    import importlib.util
    spec = importlib.util.spec_from_file_location("import_eliav_plan", REPO / "scripts" / "import_eliav_plan.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    seed = json.loads(SEED.read_text(encoding="utf-8"))
    return eliav_import.seed_export(seed, module._month_range(IMPORT_MONTHS))


def test_imported_plan_fixture_is_the_import_script_output(client, fresh_org):
    """The fixture the editor check reads is what the import writes to dashboard_plans."""
    owner = fresh_org()
    dashboard_id = _create(client, owner["headers"], owner["org_id"], "eliav-r2-import")
    with SessionLocal() as db:
        result = eliav_import.import_plan(db, dashboard_id, _import_document(), apply=True, budget_only=True)
        db.commit()
        assert result["applied"] is True
    stored = client.get(f"/api/dashboards/{dashboard_id}/plan", headers=owner["headers"]).json()["payload"]
    fixture = json.loads(IMPORTED_PLAN.read_text(encoding="utf-8"))
    assert stored["budgetLines"] == fixture["budgetLines"]
    assert stored["eliavImport"]["lines"] == fixture["eliavImport"]["lines"]
    # The seed's four payroll lines: 700 + 9,000 + 10,000 + 30,000 a month, as quantity × rate.
    lines = plan_budget.validate_budget_lines(stored)
    october = sum(line["months"]["2026-10"]["amount"] for line in lines if "2026-10" in line["months"])
    assert float(october) == 49700
    assert sum(1 for line in lines if line["months"]) == 4 and len(lines) == 127


def test_budget_editor_maps_and_saves_the_imported_plan_without_loss():
    """frontend/scripts/dashboard-render-check.mjs on the imported plan: 49,700 a month,
    the seed's partial defaults shown as text, and the save payload equal to the stored lines."""
    result = _render_check({"REZEF_IMPORTED_PLAN": str(IMPORTED_PLAN)})
    assert result.returncode == 0, result.stdout + result.stderr
    assert "imported plan" in result.stdout


def test_editor_save_of_the_imported_plan_is_accepted_and_keeps_the_projection(client, fresh_org):
    owner = fresh_org()
    dashboard_id = _create(client, owner["headers"], owner["org_id"], "eliav-r2-roundtrip")
    fixture = json.loads(IMPORTED_PLAN.read_text(encoding="utf-8"))
    assert _put(client, owner["headers"], dashboard_id, fixture).status_code == 200
    saved = _put(client, owner["headers"], dashboard_id, fixture)
    assert saved.status_code == 200, saved.text
    assert saved.json()["payload"]["budgetLines"] == fixture["budgetLines"]


# ------------------------------------------ 5. manual opening balance (1662)

def _food_without_balance(client, platform_admin, fresh_org, slug):
    dashboard_id, chef, food = _consolidated(client, platform_admin, fresh_org, slug)
    with SessionLocal() as db:
        _account(db, chef["org_id"], "עו״ש 8954", -100, limit=15000)
        account = _account(db, food["org_id"], "Imported bank 1662", None, source="reviewed_local_import", as_of=None)
        # Imported rows without a balance column.
        _bank(db, food["org_id"], date(2026, 7, 21), -1000, "לפני הפתיחה", account_id=account.id,
              raw={"original": {"סכום": "-1000"}})
        _bank(db, food["org_id"], date(2026, 7, 31), 999, "ביום הפתיחה", account_id=account.id,
              raw={"original": {"סכום": "999"}})
        _bank(db, food["org_id"], date(2026, 8, 5), -2500, "אחרי", account_id=account.id,
              raw={"original": {"סכום": "-2500"}})
        _bank(db, food["org_id"], date(2026, 10, 13), 400.5, "אחרי", account_id=account.id,
              raw={"original": {"סכום": "400.5"}})
        _bank(db, food["org_id"], date(2026, 10, 14), -50, "ממתין", account_id=account.id,
              raw={"original": {"סכום": "-50"}, "status": "PENDING"})
        db.commit()
        account_id = account.id
    _bind(client, platform_admin, dashboard_id, account_id)
    return dashboard_id, chef, food


def _food_position(client, headers, dashboard_id, end="2026-10-19"):
    view = client.get(f"/api/dashboards/{dashboard_id}/view", headers=headers,
                      params={"start": "2026-07-01", "end": end}).json()
    return view["entities"][1]["view"]["liquidity"], view["combined"]["liquidity"]


def test_opening_balance_plus_later_transactions_gives_the_imported_balance(client, fresh_org, platform_admin):
    dashboard_id, chef, food = _food_without_balance(client, platform_admin, fresh_org, "eliav-r2-opening")
    before, combined = _food_position(client, platform_admin["headers"], dashboard_id)
    assert before["position"]["balance"] is None and combined["balance"] is None

    _save(client, platform_admin["headers"], dashboard_id, {"liquidityEvidence": {"openingBalances": [
        {"organizationId": food["org_id"], "date": "2026-07-31", "amount": -30000,
         "source": "דף בנק 1662 ליום 31.7"},
    ]}})
    food_liquidity, combined = _food_position(client, platform_admin["headers"], dashboard_id)
    position = food_liquidity["position"]
    # -30,000 closing on 31.7, then -2,500 and +400.50; the row of 31.7 is in the opening
    # balance, the PENDING row is not booked.
    assert position["balance"] == -32099.5
    assert position["as_of"] == "2026-10-13"
    assert position["balance_source"] == "opening_balance"
    account = food_liquidity["accounts"][0]
    assert account["opening"] == {"date": "2026-07-31", "amount": -30000.0, "source": "דף בנק 1662 ליום 31.7",
                                  "transactions": 2}
    assert combined["balance"] == round(-100 - 32099.5, 2) and combined["balance_note"] is None

    # A window that ends before the later rows counts only the rows up to its end.
    early, _ = _food_position(client, platform_admin["headers"], dashboard_id, end="2026-08-31")
    assert early["position"]["balance"] == -32500.0
    # A window that ends before the opening date: the balance stays unknown.
    unknown, _ = _food_position(client, platform_admin["headers"], dashboard_id, end="2026-07-30")
    assert unknown["position"]["balance"] is None


def test_opening_balance_needs_a_date_an_amount_and_a_source(client, fresh_org, platform_admin):
    dashboard_id, _chef, food = _food_without_balance(client, platform_admin, fresh_org, "eliav-r2-opening-bad")
    for item in (
        {"organizationId": food["org_id"], "amount": -30000, "source": "דף בנק"},
        {"organizationId": food["org_id"], "date": "31/07/2026", "amount": -30000, "source": "דף בנק"},
        {"organizationId": food["org_id"], "date": "2026-07-31", "amount": None, "source": "דף בנק"},
        {"organizationId": food["org_id"], "date": "2026-07-31", "amount": -30000},
        {"date": "2026-07-31", "amount": -30000, "source": "דף בנק"},
    ):
        response = _put(client, platform_admin["headers"], dashboard_id,
                        {"liquidityEvidence": {"openingBalances": [item]}})
        assert response.status_code == 422, item


def test_only_the_owner_may_enter_an_opening_balance(client, fresh_org, platform_admin):
    dashboard_id, _chef, food = _food_without_balance(client, platform_admin, fresh_org, "eliav-r2-opening-role")
    accountant = fresh_org()
    _member(dashboard_id, accountant["org_id"], "accountant")
    opening = {"liquidityEvidence": {"openingBalances": [
        {"organizationId": food["org_id"], "date": "2026-07-31", "amount": -30000, "source": "דף בנק"},
    ]}}
    denied = _put(client, accountant["headers"], dashboard_id, opening)
    assert denied.status_code == 403, denied.text
    assert denied.json()["error"]["code"] == "opening_balance_forbidden"
    # The owner enters it; the accountant may still save the rest of the plan unchanged.
    assert _put(client, platform_admin["headers"], dashboard_id, opening).status_code == 200
    kept = _put(client, accountant["headers"], dashboard_id, {**opening, "statusParameters": {"scenario": "בסיס"}})
    assert kept.status_code == 200, kept.text
    removed = _put(client, accountant["headers"], dashboard_id, {"statusParameters": {"scenario": "בסיס"}})
    assert removed.status_code == 403


# ------------------------------- 2. /budget reads the dashboard's comparison

def _chef_headers(platform_admin, chef):
    return {**platform_admin["headers"], "X-Active-Org-Id": str(chef["org_id"])}


def _consolidated_august(client, platform_admin, fresh_org, slug):
    dashboard_id, chef, food = _consolidated(client, platform_admin, fresh_org, slug)
    with SessionLocal() as db:
        _bank(db, chef["org_id"], date(2026, 8, 5), 11800, "הפקדת מזומן")
        chef_pay = _bank(db, chef["org_id"], date(2026, 8, 9), -30000, "שכר עובדים")
        _bank(db, food["org_id"], date(2026, 8, 10), 5900, "הפקדת מזומן")
        food_pay = _bank(db, food["org_id"], date(2026, 8, 11), -13783, "שכר עובדים")
        db.commit()
        decisions = {
            str(row.id): {"category": "salaries", "organizationId": row.organization_id,
                          "date": row.transaction_date.isoformat(), "amount": float(row.amount), "note": None}
            for row in (chef_pay, food_pay)
        }
    _save(client, platform_admin["headers"], dashboard_id, {"statusDecisions": decisions, "budgetLines": [
        {"id": "pay", "label": "שכר", "category": "salaries", "kind": "cost",
         "months": {"2026-08": {"quantity": 1, "rate": 49700}}},
        {"id": "rev", "label": "מכירות", "category": "sales", "kind": "revenue",
         "months": {"2026-08": {"quantity": 1, "rate": 20000}}},
    ]})
    return dashboard_id, chef, food


def _view_month(client, headers, dashboard_id, month):
    today = date.today()
    view = client.get(f"/api/dashboards/{dashboard_id}/view", headers=headers,
                      params={"start": "2026-01-01", "end": (today if today.year == 2026 else date(2026, 12, 31)).isoformat()}).json()
    pick = lambda section: next(m for m in section["months"] if m["month"] == month)  # noqa: E731
    return pick(view["combined"]["budget_vs_actual"]), pick(view["entities"][0]["view"]["budget_vs_actual"])


def test_budget_page_shows_the_consolidated_tab_with_its_scope(client, fresh_org, platform_admin):
    dashboard_id, chef, _food = _consolidated_august(client, platform_admin, fresh_org, "eliav-r2-budget")
    headers = _chef_headers(platform_admin, chef)
    data = client.get("/api/financial/budget/vs-actual", headers=headers,
                      params={"year": 2026, "month": 8, "period": "month"}).json()["data"]
    combined, chef_only = _view_month(client, platform_admin["headers"], dashboard_id, "2026-08")
    assert data["scope"] == "combined" and data["scopes"] == ["combined", "primary"]
    assert data["scope_label"].startswith("מאוחד") and "פוד גרופ" in data["scope_label"]
    # The same figures as the consolidated tab: revenue and costs apart, never added up.
    assert data["totals"]["costs"] == {"budget": combined["totals"]["costs"]["budget"],
                                       "actual": combined["totals"]["costs"]["actual"]}
    assert data["totals"]["revenue"]["actual"] == combined["totals"]["revenue"]["actual"]
    assert data["totals"]["costs"]["actual"] == 43783.0
    lines = {line["category_id"]: line for line in data["categories"]}
    tab = {line["category"]: line for line in combined["categories"]}
    assert lines["payroll"]["actual_amount"] == tab["payroll"]["actual"] == 43783.0
    assert lines["payroll"]["category_hebrew"] == "כוח אדם"

    primary = client.get("/api/financial/budget/vs-actual", headers=headers,
                         params={"year": 2026, "month": 8, "period": "month", "scope": "primary"}).json()["data"]
    assert primary["scope"] == "primary" and primary["scope_label"].endswith("בלבד")
    assert primary["totals"]["costs"]["actual"] == chef_only["totals"]["costs"]["actual"] == 30000.0


def test_budget_page_of_a_user_who_cannot_read_the_whole_dashboard_is_the_entity_only(client, fresh_org, platform_admin):
    """The chef's own admin is not an admin of the office, so the dashboard's other
    entity is not theirs to see: /budget shows the chef only and says so."""
    _dashboard_id, chef, _food = _consolidated_august(client, platform_admin, fresh_org, "eliav-r2-budget-own")
    data = client.get("/api/financial/budget/vs-actual", headers=chef["headers"],
                      params={"year": 2026, "month": 8, "period": "month", "scope": "combined"}).json()["data"]
    assert data["scope"] == "primary" and data["scopes"] == ["primary"]
    assert data["totals"]["costs"]["actual"] == 30000.0


# ----------------------------------------------- 3. Hebrew labels everywhere

def test_budget_alerts_of_a_dashboard_organization_have_hebrew_labels(client, fresh_org):
    owner = fresh_org()
    dashboard_id = _create(client, owner["headers"], owner["org_id"], "eliav-r2-alerts")
    today = date.today()
    with SessionLocal() as db:
        pay = _bank(db, owner["org_id"], today.replace(day=1), -60000, "שכר עובדים")
        db.commit()
        decision = {str(pay.id): {"category": "salaries", "organizationId": owner["org_id"],
                                  "date": pay.transaction_date.isoformat(), "amount": -60000, "note": None}}
    month = today.strftime("%Y-%m")
    _save(client, owner["headers"], dashboard_id, {"statusDecisions": decision, "budgetLines": [
        {"id": "pay", "label": "שכר", "category": "salaries", "kind": "cost",
         "months": {month: {"quantity": 1, "rate": 49700}}},
    ]})
    alerts = client.get("/api/financial/budget/alerts", headers=owner["headers"]).json()["data"]
    assert len(alerts) == 1
    alert = alerts[0]
    assert alert["category_hebrew"] == "כוח אדם" and "salaries" not in alert["message"]
    assert alert["percentage_used"] == round(60000 / 49700 * 100, 1) and alert["alert_type"] == "over_budget"


def test_every_category_key_has_a_hebrew_label_and_the_frontend_table_is_the_same():
    import re
    from cfo.services import category_labels
    from cfo.services.dashboards.plan_budget import budget_catalog
    labels = category_labels.all_labels()
    for key in [*labels, *(row["key"] for row in budget_catalog())]:
        assert not re.fullmatch(r"[a-z0-9_]+", category_labels.hebrew(key)), key
    source = (REPO / "frontend" / "src" / "services" / "categoryLabels.ts").read_text(encoding="utf-8")
    frontend = {
        key: json.loads(value)
        for key, value in re.findall(r'^\s+"([a-z0-9_]+)": (".*"),$', source, flags=re.M)
    }
    assert frontend == labels
