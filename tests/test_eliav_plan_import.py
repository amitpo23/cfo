"""One-time Eliav plan import and monthly reconciliation. No provider calls."""
import ast
import importlib.util
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from cfo.database import SessionLocal
from cfo.models import (
    AuditLog, BankTransaction, Budget, DashboardPlan, DashboardPlanRevision,
)
from cfo.services.dashboards.eliav_import import (
    ImportRejected,
    import_plan,
    reconcile,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = Path(__file__).parent / "fixtures" / "eliav_plan_export.json"
BASELINE = Path(__file__).parent / "fixtures" / "eliav_reconcile_baseline.json"


def _create(client, headers, org_id, slug):
    response = client.post("/api/dashboards", headers=headers, json={
        "primary_organization_id": org_id,
        "slug": slug,
        "title": "אליהב",
        "access_mode": "link",
    })
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _plan(org_id: int, transaction_id: int) -> dict:
    document = json.loads(FIXTURE.read_text(encoding="utf-8"))
    decisions = document["data"]["statusDecisions"]
    matched = decisions.pop("101")
    matched["organizationId"] = org_id
    decisions[str(transaction_id)] = matched
    decisions["999999001"]["organizationId"] = org_id
    document["data"]["statusRules"][0]["organizationId"] = org_id
    return document


def _seed_transaction(org_id: int) -> int:
    with SessionLocal() as db:
        row = BankTransaction(
            organization_id=org_id,
            transaction_date=date(2026, 8, 12),
            amount=Decimal("-840.50"),
            description="טחנת קמח",
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row.id


def _cli(filename: str):
    path = ROOT / "scripts" / filename
    spec = importlib.util.spec_from_file_location(filename.replace(".py", ""), path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_dry_run_reports_the_diff_and_writes_nothing(client, fresh_org):
    owner = fresh_org()
    dashboard_id = _create(client, owner["headers"], owner["org_id"], "eliav-dry-run")
    transaction_id = _seed_transaction(owner["org_id"])
    with SessionLocal() as db:
        result = import_plan(db, dashboard_id, _plan(owner["org_id"], transaction_id), apply=False)
        assert result["applied"] is False
        assert result["idempotent"] is False
        assert result["provider_calls"] == 0
        assert result["decisions_applied"] == 1
        assert result["decisions_rejected"] == 1
        assert result["rejected"][0]["reason"] == "not_found"
        assert result["rejected"][0]["note"] == "תנועה שלא נמצאה בבנק"
        totals = {(row["month"], row["category"]): row["amount"] for row in result["monthly_totals"]}
        assert totals[("2026-08", "salaries")] == "49700.00"
        assert totals[("2026-08", "sales")] == "5760.00"
        assert totals[("2026-08", "cost_of_goods")] == "845.00"
        assert totals[("2026-09", "cost_of_goods")] == "676.00"
        assert db.get(DashboardPlan, dashboard_id) is None
        assert db.query(Budget).filter_by(organization_id=owner["org_id"]).count() == 0


def test_apply_is_idempotent_and_keeps_line_detail(client, fresh_org):
    owner = fresh_org()
    dashboard_id = _create(client, owner["headers"], owner["org_id"], "eliav-apply")
    transaction_id = _seed_transaction(owner["org_id"])
    document = _plan(owner["org_id"], transaction_id)
    with SessionLocal() as db:
        banks_before = db.query(BankTransaction).filter_by(organization_id=owner["org_id"]).count()
        first = import_plan(db, dashboard_id, document, apply=True)
        assert first["applied"] is True
        plan = db.get(DashboardPlan, dashboard_id)
        assert plan.schema_version == 2
        assert "schemaVersion" not in plan.payload
        assert "bankDecisions" not in plan.payload
        assert str(transaction_id) in plan.payload["statusDecisions"]
        assert "999999001" not in plan.payload["statusDecisions"]
        assert plan.payload["statusDecisions"][str(transaction_id)]["category"] == "supplier_transfers"
        assert plan.payload["statusDecisions"][str(transaction_id)]["note"] == "קמח לאוגוסט"
        assert plan.payload["statusRules"][0]["contains"] == "טחנת"
        payroll = [line for line in plan.payload["budgetLines"] if line["id"] == "wage_eliav"]
        assert payroll[0] == {
            "id": "wage_eliav", "label": "אליאב", "category": "salaries", "kind": "cost",
            "months": {
                "2026-08": {"quantity": 1, "rate": 30000},
                "2026-09": {"quantity": 1, "rate": 30000},
            },
            "group": "כוח אדם", "unit": "חודש",
        }
        assert plan.payload["eliavImport"]["lines"]["wage_eliav"]["group"] == "כוח אדם"
        revision = db.get(DashboardPlanRevision, plan.version)
        assert revision.previous_version is None
        assert revision.change_summary.startswith("import from eliav tool db15 sha256:")
        assert first["input_sha256"] in revision.change_summary
        budget = db.query(Budget).filter_by(
            organization_id=owner["org_id"], category_name="salaries", year=2026, month=8,
        ).one()
        assert Decimal(budget.budgeted_amount) == Decimal("49700.00")
        assert budget.notes == f"plan:{plan.version}"
        audit = db.query(AuditLog).filter_by(
            organization_id=owner["org_id"], action="IMPORT_DASHBOARD_PLAN",
        ).one()
        assert audit.details["provider_calls"] == 0
        assert db.query(BankTransaction).filter_by(organization_id=owner["org_id"]).count() == banks_before
        second = import_plan(db, dashboard_id, document, apply=True)
        assert second["idempotent"] is True
        assert second["applied"] is False
        assert db.query(DashboardPlanRevision).filter_by(dashboard_id=dashboard_id).count() == 1
        assert db.query(Budget).filter_by(organization_id=owner["org_id"]).count() == 6


def test_unknown_field_and_amount_mismatch_stop_or_skip(client, fresh_org):
    owner = fresh_org()
    dashboard_id = _create(client, owner["headers"], owner["org_id"], "eliav-invalid")
    transaction_id = _seed_transaction(owner["org_id"])
    document = _plan(owner["org_id"], transaction_id)
    document["data"]["surprise"] = True
    with SessionLocal() as db:
        with pytest.raises(ImportRejected) as caught:
            import_plan(db, dashboard_id, document, apply=True)
        assert caught.value.code == "unknown_field"
        assert db.get(DashboardPlan, dashboard_id) is None
        close = _plan(owner["org_id"], transaction_id)
        close["data"]["statusDecisions"][str(transaction_id)]["amount"] = -840.504
        close_result = import_plan(db, dashboard_id, close, apply=False)
        assert close_result["decisions_applied"] == 1
        off = _plan(owner["org_id"], transaction_id)
        off["data"]["statusDecisions"][str(transaction_id)]["amount"] = -840.51
        off_result = import_plan(db, dashboard_id, off, apply=False)
        assert off_result["decisions_applied"] == 0
        assert {row["reason"] for row in off_result["rejected"]} == {"not_found", "amount_mismatch"}


def test_reconcile_matches_the_baseline_within_one_shekel(client, fresh_org):
    owner = fresh_org()
    dashboard_id = _create(client, owner["headers"], owner["org_id"], "eliav-reconcile")
    transaction_id = _seed_transaction(owner["org_id"])
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    with SessionLocal() as db:
        missing = reconcile(db, dashboard_id, baseline)
        assert missing["ok"] is False
        assert missing["rows"][0]["computed"] is None
        assert missing["rows"][0]["status"] == "missing"
        import_plan(db, dashboard_id, _plan(owner["org_id"], transaction_id), apply=True)
        report = reconcile(db, dashboard_id, baseline)
        assert report["ok"] is True
        assert report["provider_calls"] == 0
        assert all(row["status"] == "ok" for row in report["rows"])
        drifted = json.loads(json.dumps(baseline))
        drifted["months"]["2026-08"]["כוח אדם"] = 49702
        bad = reconcile(db, dashboard_id, drifted)
        assert bad["ok"] is False
        payroll = next(row for row in bad["rows"] if row["category"] == "salaries" and row["month"] == "2026-08")
        assert payroll["status"] == "diff"
        edge = json.loads(json.dumps(baseline))
        edge["months"]["2026-08"]["ספקים"] = 846
        assert reconcile(db, dashboard_id, edge)["ok"] is True
        over = json.loads(json.dumps(baseline))
        over["months"]["2026-08"]["ספקים"] = 846.01
        assert reconcile(db, dashboard_id, over)["ok"] is False


def test_cli_dry_run_and_reconcile_commands(client, fresh_org, capsys, tmp_path):
    owner = fresh_org()
    dashboard_id = _create(client, owner["headers"], owner["org_id"], "eliav-cli")
    transaction_id = _seed_transaction(owner["org_id"])
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(_plan(owner["org_id"], transaction_id)), encoding="utf-8")
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(BASELINE.read_text(encoding="utf-8"), encoding="utf-8")
    importer = _cli("import_eliav_plan.py")
    assert importer.main(["--dashboard-id", str(dashboard_id), "--plan", str(plan_path)]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["applied"] is False
    assert printed["monthly_totals"]
    with SessionLocal() as db:
        assert db.get(DashboardPlan, dashboard_id) is None
    assert importer.main([
        "--dashboard-id", str(dashboard_id), "--plan", str(plan_path), "--apply",
    ]) == 0
    capsys.readouterr()
    reconciler = _cli("reconcile_eliav.py")
    assert reconciler.main([
        "--dashboard-id", str(dashboard_id), "--baseline", str(baseline_path),
    ]) == 0
    report = capsys.readouterr().out
    assert "תוצאה: תקין" in report
    assert "49700.00" in report
    drifted = tmp_path / "drift.json"
    drifted.write_text(json.dumps({"months": {"2026-08": {"כוח אדם": 100}}}), encoding="utf-8")
    assert reconciler.main([
        "--dashboard-id", str(dashboard_id), "--baseline", str(drifted),
    ]) == 1
    assert "תוצאה: לא תואם" in capsys.readouterr().out


def test_import_scripts_do_not_import_provider_clients():
    banned = ("sumit", "financy", "open_finance", "openfinance")
    files = [
        ROOT / "scripts" / "import_eliav_plan.py",
        ROOT / "scripts" / "reconcile_eliav.py",
        ROOT / "src" / "cfo" / "services" / "dashboards" / "eliav_import.py",
    ]
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            lowered = " ".join(names).lower()
            assert not any(word in lowered for word in banned), path


def _put_plan(client, headers, dashboard_id, payload, version):
    return client.put(
        f"/api/dashboards/{dashboard_id}/plan",
        headers={**headers, "If-Match": f'"{version}"'},
        json={"payload": payload},
    )


def test_editor_put_plan_succeeds_after_an_import(client, fresh_org):
    """Import, then the #49 editor's own save path: GET /plan, edit, PUT /plan -> 200."""
    owner = fresh_org()
    dashboard_id = _create(client, owner["headers"], owner["org_id"], "eliav-then-editor")
    transaction_id = _seed_transaction(owner["org_id"])
    with SessionLocal() as db:
        assert import_plan(db, dashboard_id, _plan(owner["org_id"], transaction_id), apply=True)["applied"]
    got = client.get(f"/api/dashboards/{dashboard_id}/plan", headers=owner["headers"])
    assert got.status_code == 200, got.text
    plan = got.json()
    payload = plan["payload"]
    # Unchanged round trip, the way the editor saves a rule or a decision.
    same = _put_plan(client, owner["headers"], dashboard_id, payload, plan["version"])
    assert same.status_code == 200, same.text
    # A budget edit, built the way budgetLinesPayload builds it (unknown line keys dropped).
    lines = [
        {"id": line["id"], "label": line["label"], "category": line["category"],
         "kind": line["kind"], "months": line["months"]}
        for line in same.json()["payload"]["budgetLines"]
    ]
    pizza = next(line for line in lines if line["id"] == "revenue_pizza")
    pizza["months"]["2026-08"] = {"quantity": 130, "rate": 48}
    edited = _put_plan(
        client, owner["headers"], dashboard_id,
        {**same.json()["payload"], "budgetLines": lines}, same.json()["version"],
    )
    assert edited.status_code == 200, edited.text
    with SessionLocal() as db:
        sales = db.query(Budget).filter_by(
            organization_id=owner["org_id"], category_name="sales", year=2026, month=8,
        ).all()
        assert [Decimal(row.budgeted_amount) for row in sales] == [Decimal("6240.00")]
        assert sales[0].notes == f"plan:{edited.json()['version']}"
        assert db.query(Budget).filter_by(organization_id=owner["org_id"]).count() == 6
        assert db.get(DashboardPlan, dashboard_id).payload["statusRules"][0]["contains"] == "טחנת"


def test_other_scenarios_are_kept_but_not_projected(client, fresh_org):
    owner = fresh_org()
    dashboard_id = _create(client, owner["headers"], owner["org_id"], "eliav-scenarios")
    transaction_id = _seed_transaction(owner["org_id"])
    document = _plan(owner["org_id"], transaction_id)
    document["data"]["budgets"]["2026-08|optimistic"] = {"revenue_pizza": {"quantity": 200, "rate": 48}}
    with SessionLocal() as db:
        result = import_plan(db, dashboard_id, document, apply=True)
        assert result["scenario"] == "base"
        assert result["other_scenarios"] == ["optimistic"]
        payload = db.get(DashboardPlan, dashboard_id).payload
        pizza = next(line for line in payload["budgetLines"] if line["id"] == "revenue_pizza")
        assert set(pizza["months"]) == {"2026-08", "2026-09"}
        assert pizza["months"]["2026-08"] == {"quantity": 120, "rate": 48}
        assert payload["eliavImport"]["otherScenarios"] == {
            "optimistic": {"revenue_pizza": {"2026-08": {"quantity": 200, "rate": 48}}},
        }
        sales = db.query(Budget).filter_by(
            organization_id=owner["org_id"], category_name="sales", year=2026, month=8,
        ).one()
        assert Decimal(sales.budgeted_amount) == Decimal("5760.00")


def test_import_keeps_plan_keys_it_does_not_own(client, fresh_org):
    owner = fresh_org()
    dashboard_id = _create(client, owner["headers"], owner["org_id"], "eliav-merge")
    transaction_id = _seed_transaction(owner["org_id"])
    pairs = [{"keep": 1, "drop": 2}]
    saved = _put_plan(client, owner["headers"], dashboard_id, {
        "booksClosedMonths": ["2026-07"], "dedupePairs": pairs,
    }, "null")
    assert saved.status_code == 200, saved.text
    with SessionLocal() as db:
        import_plan(db, dashboard_id, _plan(owner["org_id"], transaction_id), apply=True)
        payload = db.get(DashboardPlan, dashboard_id).payload
        assert payload["booksClosedMonths"] == ["2026-07"]
        assert payload["dedupePairs"] == pairs
        assert payload["budgetLines"]


def _long_line_id(data):
    long_id = "x" * 65
    data["lines"][0]["id"] = long_id
    for month in data["budgets"].values():
        month[long_id] = month.pop("revenue_pizza")


@pytest.mark.parametrize("case, mutate, code", [
    ("rule-category", lambda data: data["statusRules"][0].update(category="suppliers"), "unknown_category"),
    ("rule-field", lambda data: data["statusRules"][0].update(field="reference"), "invalid_plan"),
    ("balance-sheet-category", lambda data: data["lines"][0].update(category="inventory"), "unknown_category"),
    ("kind-mismatch", lambda data: data["lines"][0].update(category="salaries"), "invalid_plan"),
    ("long-line-id", _long_line_id, "invalid_plan"),
])
def test_import_refuses_what_the_editor_could_not_save(client, fresh_org, case, mutate, code):
    owner = fresh_org()
    dashboard_id = _create(client, owner["headers"], owner["org_id"], f"eliav-refuse-{case}")
    transaction_id = _seed_transaction(owner["org_id"])
    document = _plan(owner["org_id"], transaction_id)
    mutate(document["data"])
    with SessionLocal() as db:
        with pytest.raises(ImportRejected) as caught:
            import_plan(db, dashboard_id, document, apply=True)
        assert caught.value.code == code, caught.value.message
        assert db.get(DashboardPlan, dashboard_id) is None


def test_unknown_decision_category_is_an_exception_not_a_decision(client, fresh_org):
    owner = fresh_org()
    dashboard_id = _create(client, owner["headers"], owner["org_id"], "eliav-bad-decision")
    transaction_id = _seed_transaction(owner["org_id"])
    document = _plan(owner["org_id"], transaction_id)
    document["data"]["statusDecisions"][str(transaction_id)]["category"] = "suppliers"
    with SessionLocal() as db:
        result = import_plan(db, dashboard_id, document, apply=False)
        assert result["decisions_applied"] == 0
        assert {row["reason"] for row in result["rejected"]} == {"unknown_category", "not_found"}
