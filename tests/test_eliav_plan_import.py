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
    AuditLog, BankTransaction, Budget, Category, DashboardPlan, DashboardPlanRevision,
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
        assert totals[("2026-08", "כוח אדם")] == "49700.00"
        assert totals[("2026-08", "הכנסות")] == "5760.00"
        assert totals[("2026-08", "ספקים")] == "845.00"
        assert totals[("2026-09", "ספקים")] == "676.00"
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
        assert plan.schema_version == 3
        assert "bankDecisions" not in plan.payload
        assert str(transaction_id) in plan.payload["statusDecisions"]
        assert "999999001" not in plan.payload["statusDecisions"]
        assert plan.payload["statusDecisions"][str(transaction_id)]["category"] == "suppliers"
        assert plan.payload["statusDecisions"][str(transaction_id)]["note"] == "קמח לאוגוסט"
        assert plan.payload["statusRules"][0]["contains"] == "טחנת"
        payroll = [line for line in plan.payload["budgetLines"] if line["id"] == "wage_eliav"]
        assert payroll[0]["group"] == "כוח אדם"
        assert payroll[0]["cells"]["2026-08|base"] == {"quantity": 1, "rate": 30000}
        revision = db.get(DashboardPlanRevision, plan.version)
        assert revision.previous_version is None
        assert revision.change_summary.startswith("import from eliav tool db15 sha256:")
        assert first["input_sha256"] in revision.change_summary
        category = db.query(Category).filter_by(
            organization_id=owner["org_id"], external_id="eliav:group:payroll",
        ).one()
        budget = db.query(Budget).filter_by(
            organization_id=owner["org_id"], category_id=category.id, year=2026, month=8,
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
        payroll = next(row for row in bad["rows"] if row["category"] == "כוח אדם" and row["month"] == "2026-08")
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
