"""Dashboard filing report and plan budget lines. Classification stays in filing.py."""
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from cfo.database import SessionLocal
from cfo.models import AuditLog, BankTransaction, Budget, DashboardMember, Invoice, User
from cfo.services.dashboards.filing_report import build_filing_report
from cfo.services.dashboards.service import DashboardError, validate_filing_payload

DAY = date(2026, 8, 15)


class _Row:
    def __init__(self, ident, description, amount, *, organization_id=2, debtor="", creditor=""):
        self.id = ident
        self.organization_id = organization_id
        self.account_id = None
        self.transaction_date = DAY
        self.amount = Decimal(str(amount))
        self.description = description
        self.raw_data = {"debtorName": debtor, "creditorName": creditor}


def _rule(rule_id):
    return next(rule for rule in _LAST["rules"] if rule["id"] == rule_id)


_LAST: dict = {}


def _report(rows, payload, **kwargs):
    report = build_filing_report(rows, payload, page=1, page_size=50, **kwargs)
    _LAST.clear()
    _LAST.update(report)
    return report


def test_report_counts_decision_over_custom_over_builtin():
    payload = {
        "statusRules": [{
            "id": "custom-fee", "contains": "עמל", "field": "description",
            "direction": "out", "category": "office",
        }],
        "statusDecisions": {
            "1": {
                "category": "salaries", "organizationId": 2, "date": DAY.isoformat(),
                "amount": -12,
            },
        },
    }
    report = _report([
        _Row(1, "עמלת ניהול", -12),
        _Row(2, "עמלת סליקה", -7),
        _Row(3, "עמלה", -3),
    ], payload)
    custom = _rule("custom-fee")
    builtin = _rule("builtin:bank_fees")
    assert custom["match_count"] == 2
    assert custom["total"] == 10
    assert custom["overridden"] == 1
    assert custom["source"] == "custom"
    assert builtin["match_count"] == 0
    assert builtin["overridden"] == 3
    assert report["review"]["total"] == 0
    assert "עמלת|עמלה" in builtin["contains"]


def test_mismatched_decision_is_reported_and_not_applied():
    payload = {
        "statusDecisions": {
            "9": {"category": "salaries", "organizationId": 2, "date": DAY.isoformat(), "amount": -100},
            "8": {"category": "rent", "organizationId": 99, "date": DAY.isoformat(), "amount": -40},
        },
    }
    report = _report([
        _Row(9, "עמלת בנק", -12),
        _Row(8, "דלק", -40),
    ], payload)
    reasons = {item["transaction_id"]: item["reason"] for item in report["unmatched_decisions"]}
    assert reasons["9"] == "amount"
    assert reasons["8"] == "organization"
    assert _rule("builtin:bank_fees")["match_count"] == 1
    assert _rule("builtin:fuel_energy")["match_count"] == 1


def test_amount_within_half_agora_still_matches_the_decision():
    payload = {"statusDecisions": {
        "4": {"category": "interest", "organizationId": 2, "date": DAY.isoformat(), "amount": -10},
    }}
    report = _report([_Row(4, "ריבית", Decimal("-10.004"))], payload)
    assert report["unmatched_decisions"] == []
    assert _rule("builtin:interest")["overridden"] == 1
    assert _rule("builtin:interest")["match_count"] == 0


def test_custom_rule_can_be_limited_to_one_organization_and_counterparty():
    payload = {"statusRules": [
        {
            "id": "org-only", "contains": "עמלה", "field": "description",
            "direction": "out", "category": "office", "organizationId": 6,
        },
        {
            "id": "who", "contains": "ספק ירקות", "field": "counterparty",
            "direction": "out", "category": "supplier_transfers",
        },
    ]}
    report = _report([
        _Row(1, "עמלה", -5, organization_id=2),
        _Row(2, "עמלה", -5, organization_id=6),
        _Row(3, "העברה", -80, creditor="ספק ירקות"),
    ], payload)
    assert _rule("org-only")["match_count"] == 1
    assert _rule("builtin:bank_fees")["match_count"] == 1
    assert _rule("who")["match_count"] == 1
    assert _rule("who")["field"] == "counterparty"
    assert report["review"]["total"] == 0


def test_unresolved_positive_rows_are_the_review_queue():
    report = _report([
        _Row(1, "משהו לא מוכר", 15),
        _Row(2, "העברה לספק", -20),
        _Row(3, "יומן זכות", 30),
        _Row(4, "חיוב ספק", -8),
    ], {})
    queued = {item["description"]: item["category"] for item in report["review"]["items"]}
    assert queued == {
        "משהו לא מוכר": "other_in",
        "העברה לספק": "transfers_out",
        "יומן זכות": "bank_journal",
    }
    assert "לבירור" in report["review"]["items"][0]["filed_by"]["reason_he"]


def test_plan_rejects_unknown_filing_category_null_direction_and_too_many_rules():
    with pytest.raises(DashboardError) as unknown:
        validate_filing_payload({"statusRules": [{
            "id": "x", "contains": "א", "category": "other_in",
        }]})
    assert unknown.value.status == 422
    assert "קטגורי" in unknown.value.message_he
    with pytest.raises(DashboardError):
        validate_filing_payload({"statusRules": [{
            "id": "x", "contains": "א", "category": "office", "direction": None,
        }]})
    rules = [{"id": f"r{i}", "contains": "א", "category": "office"} for i in range(201)]
    with pytest.raises(DashboardError) as capped:
        validate_filing_payload({"statusRules": rules})
    assert "200" in capped.value.message_he


def _create(client, headers, org_id, slug):
    response = client.post("/api/dashboards", headers=headers, json={
        "primary_organization_id": org_id, "slug": slug, "title": "תיוק",
        "access_mode": "link",
    })
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _save(client, headers, dashboard_id, payload, version="null"):
    return client.put(
        f"/api/dashboards/{dashboard_id}/plan",
        headers={**headers, "If-Match": version},
        json={"payload": payload},
    )


def _member(dashboard_id, org_id, role):
    with SessionLocal() as db:
        user = db.query(User).filter(User.organization_id == org_id).one()
        db.add(DashboardMember(
            dashboard_id=dashboard_id, user_id=user.id, role=role, status="active",
        ))
        db.commit()


def _bank(
    org_id, ident, description, amount, *, debtor=None, creditor=None,
    superseded_by_id=None, source="manual", external_id=None, status=None, raw_type=None,
):
    raw = {}
    if debtor:
        raw["debtorName"] = debtor
    if creditor:
        raw["creditorName"] = creditor
    if status:
        raw["status"] = status
    if raw_type:
        raw["type"] = raw_type
    with SessionLocal() as db:
        db.add(BankTransaction(
            organization_id=org_id, source=source, external_id=external_id,
            transaction_date=DAY, description=description, amount=Decimal(str(amount)),
            raw_data=raw or None, superseded_by_id=superseded_by_id,
        ))
        db.commit()
        return db.query(BankTransaction).filter_by(
            organization_id=org_id, description=description, source=source,
        ).order_by(BankTransaction.id.desc()).one().id


def test_review_list_pages_past_sixty_and_hides_superseded_rows(client, fresh_org):
    owner = fresh_org()
    dashboard_id = _create(client, owner["headers"], owner["org_id"], "filing-pages")
    for index in range(61):
        _bank(owner["org_id"], index, f"לא מסווג {index}", index + 1)
    duplicate = _bank(owner["org_id"], 99, "כפילות", 50)
    _bank(owner["org_id"], 100, "כפילות ששורדת", 50, superseded_by_id=duplicate)
    _bank(owner["org_id"], 101, "עמלת בנק", -8)
    first = client.get(
        f"/api/dashboards/{dashboard_id}/filing", headers=owner["headers"],
        params={"page": 1, "page_size": 50},
    )
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["provider_calls"] == 0
    assert body["can_edit"] is True
    assert body["review"]["total"] == 62
    assert len(body["review"]["items"]) == 50
    assert body["budget_categories"]
    second = client.get(
        f"/api/dashboards/{dashboard_id}/filing", headers=owner["headers"],
        params={"page": 2, "page_size": 50},
    )
    assert len(second.json()["review"]["items"]) == 12
    descriptions = {item["description"] for item in body["review"]["items"]}
    descriptions.update(item["description"] for item in second.json()["review"]["items"])
    assert "כפילות ששורדת" not in descriptions
    assert "עמלת בנק" not in descriptions
    assert "כפילות" in descriptions
    fee = next(rule for rule in body["rules"] if rule["id"] == "builtin:bank_fees")
    assert fee["match_count"] == 1
    assert fee["total"] == 8
    assert client.get(
        f"/api/dashboards/{dashboard_id}/filing", headers=owner["headers"],
        params={"page_size": 201},
    ).status_code == 422


def test_review_skips_pending_and_card_rows(client, fresh_org):
    owner = fresh_org()
    dashboard_id = _create(client, owner["headers"], owner["org_id"], "filing-booked")
    _bank(
        owner["org_id"], 1, "ממתין", 40, source="open_finance", external_id="p1", status="PENDING",
    )
    _bank(
        owner["org_id"], 2, "כרטיס", -15, source="open_finance", external_id="c1",
        status="BOOKED", raw_type="CARD",
    )
    _bank(
        owner["org_id"], 3, "נרשם", 40, source="open_finance", external_id="b1", status="BOOKED",
    )
    report = client.get(f"/api/dashboards/{dashboard_id}/filing", headers=owner["headers"])
    assert report.status_code == 200, report.text
    descriptions = [item["description"] for item in report.json()["review"]["items"]]
    assert descriptions == ["נרשם"]


def test_invoice_match_leaves_the_review_queue(client, fresh_org):
    owner = fresh_org()
    dashboard_id = _create(client, owner["headers"], owner["org_id"], "filing-invoice")
    _bank(owner["org_id"], 1, "תשלום לקוח", 118)
    with SessionLocal() as db:
        db.add(Invoice(
            organization_id=owner["org_id"], invoice_number="a-1", issue_date=DAY,
            subtotal=Decimal("100"), tax=Decimal("18"), total=Decimal("118"),
        ))
        db.commit()
    report = client.get(f"/api/dashboards/{dashboard_id}/filing", headers=owner["headers"])
    assert report.status_code == 200, report.text
    assert report.json()["review"]["total"] == 0


def test_viewer_is_read_only_and_accountant_can_save_a_rule(client, fresh_org):
    owner = fresh_org()
    viewer = fresh_org()
    accountant = fresh_org()
    dashboard_id = _create(client, owner["headers"], owner["org_id"], "filing-roles")
    _member(dashboard_id, viewer["org_id"], "client_viewer")
    _member(dashboard_id, accountant["org_id"], "accountant")
    denied = _save(client, viewer["headers"], dashboard_id, {"statusRules": []})
    assert denied.status_code == 404
    found = client.get("/api/dashboards/by-slug/filing-roles", headers=viewer["headers"])
    assert found.status_code == 200, found.text
    assert found.json()["role"] == "client_viewer"
    assert found.json()["can_edit"] is False
    assert client.get("/api/dashboards/by-slug/filing-roles", headers=accountant["headers"]).json()["can_edit"] is True
    stranger = fresh_org()
    assert client.get("/api/dashboards/by-slug/filing-roles", headers=stranger["headers"]).status_code == 404
    saved = _save(client, accountant["headers"], dashboard_id, {
        "statusRules": [{
            "id": "custom-1", "contains": "פיצה", "field": "description",
            "direction": "in", "category": "other_income",
        }],
        "note": "נשמר",
    })
    assert saved.status_code == 200, saved.text
    tx_id = _bank(owner["org_id"], 1, "פיצה משלוח", 90)
    report = client.get(f"/api/dashboards/{dashboard_id}/filing", headers=viewer["headers"])
    assert report.status_code == 200, report.text
    assert report.json()["can_edit"] is False
    custom = next(rule for rule in report.json()["rules"] if rule["id"] == "custom-1")
    assert custom["match_count"] == 1
    assert custom["source"] == "custom"
    assert report.json()["review"]["total"] == 0
    decided = _save(
        client, accountant["headers"], dashboard_id,
        {
            "statusRules": saved.json()["payload"]["statusRules"],
            "statusDecisions": {
                str(tx_id): {
                    "category": "supplier_transfers", "organizationId": owner["org_id"],
                    "date": DAY.isoformat(), "amount": 90, "note": "סופק",
                },
            },
            "note": "נשמר",
        },
        version=saved.json()["version"],
    )
    assert decided.status_code == 200, decided.text
    again = client.get(f"/api/dashboards/{dashboard_id}/filing", headers=owner["headers"])
    assert again.status_code == 200, again.text
    assert again.json()["review"]["total"] == 0
    custom = next(rule for rule in again.json()["rules"] if rule["id"] == "custom-1")
    assert custom["match_count"] == 0
    assert custom["overridden"] == 1


def test_budget_lines_project_quantity_times_rate_and_drop_removed_months(client, fresh_org):
    owner = fresh_org()
    dashboard_id = _create(client, owner["headers"], owner["org_id"], "filing-budget")
    manual = client.put(f"/api/dashboards/{dashboard_id}/budget", headers=owner["headers"], json={"rows": [
        {"year": 2026, "month": 1, "category": "marketing", "budgeted_amount": 10, "notes": "ידני"},
    ]})
    assert manual.status_code == 200, manual.text
    payload = {"budgetLines": [
        {
            "id": "line-a", "label": "עליה", "category": "salaries", "kind": "cost",
            "months": {"2026-08": {"quantity": 1, "rate": 9000}},
        },
        {
            "id": "line-b", "label": "אליאב", "category": "salaries", "kind": "cost",
            "months": {"2026-08": {"quantity": 1, "rate": 30000}, "2026-09": {"quantity": 2, "rate": 100}},
        },
        {
            "id": "line-c", "label": "מכירות", "category": "מכירות",
            "months": {"2026-08": {"quantity": 3, "rate": 10.5}},
        },
    ]}
    saved = _save(client, owner["headers"], dashboard_id, payload)
    assert saved.status_code == 200, saved.text
    with SessionLocal() as db:
        rows = db.query(Budget).filter_by(organization_id=owner["org_id"]).all()
        by_key = {(row.year, row.month, row.category_name): row for row in rows}
        assert by_key[(2026, 8, "salaries")].budgeted_amount == Decimal("39000.00")
        assert by_key[(2026, 9, "salaries")].budgeted_amount == Decimal("200.00")
        assert by_key[(2026, 8, "sales")].budgeted_amount == Decimal("31.50")
        assert by_key[(2026, 8, "salaries")].notes.startswith("plan:")
        assert by_key[(2026, 1, "marketing")].budgeted_amount == Decimal("10.00")
        assert by_key[(2026, 1, "marketing")].notes == "ידני"
        audit = db.query(AuditLog).filter_by(
            organization_id=owner["org_id"], action="SAVE_DASHBOARD_PLAN",
        ).one()
        assert audit.details["provider_calls"] == 0
        assert audit.details["projected_budget_rows"] == 3
    listed = client.get(f"/api/dashboards/{dashboard_id}/budget", headers=owner["headers"])
    amounts = {(row["year"], row["month"], row["category"]): row["budgeted_amount"] for row in listed.json()["rows"]}
    assert amounts[(2026, 8, "salaries")] == 39000
    assert amounts[(2026, 8, "sales")] == 31.5
    trimmed = _save(client, owner["headers"], dashboard_id, {"budgetLines": [{
        "id": "line-a", "label": "עליה", "category": "salaries",
        "months": {"2026-08": {"quantity": 1, "rate": 1}},
    }]}, version=saved.json()["version"])
    assert trimmed.status_code == 200, trimmed.text
    with SessionLocal() as db:
        rows = db.query(Budget).filter_by(organization_id=owner["org_id"]).all()
        keys = {(row.year, row.month, row.category_name) for row in rows}
        assert (2026, 9, "salaries") not in keys
        assert (2026, 8, "sales") not in keys
        assert (2026, 1, "marketing") in keys
        august = next(row for row in rows if (row.year, row.month, row.category_name) == (2026, 8, "salaries"))
        assert august.budgeted_amount == Decimal("1.00")
    bad = _save(client, owner["headers"], dashboard_id, {"budgetLines": [{
        "id": "nope", "label": "לא", "category": "קטגוריה לא קיימת",
        "months": {"2026-08": {"quantity": 1, "rate": 1}},
    }]}, version=trimmed.json()["version"])
    assert bad.status_code == 422
    assert bad.json()["error"]["code"] == "invalid_plan"


def test_budget_editing_is_open_to_owner_accountant_and_client_editor(client, fresh_org):
    """Same roles as PUT /budget in #47 (PLAN_ROLES). A viewer reads only."""
    owner = fresh_org()
    editor = fresh_org()
    accountant = fresh_org()
    viewer = fresh_org()
    dashboard_id = _create(client, owner["headers"], owner["org_id"], "filing-budget-roles")
    _member(dashboard_id, editor["org_id"], "client_editor")
    _member(dashboard_id, accountant["org_id"], "accountant")
    _member(dashboard_id, viewer["org_id"], "client_viewer")
    row = {"rows": [{"year": 2026, "month": 2, "category": "rent", "budgeted_amount": 5}]}
    for who in (owner, accountant, editor):
        meta = client.get("/api/dashboards/by-slug/filing-budget-roles", headers=who["headers"])
        assert meta.json()["can_edit"] is True
        put = client.put(f"/api/dashboards/{dashboard_id}/budget", headers=who["headers"], json=row)
        assert put.status_code == 200, put.text
    meta = client.get("/api/dashboards/by-slug/filing-budget-roles", headers=viewer["headers"])
    assert meta.json()["can_edit"] is False
    denied = client.put(f"/api/dashboards/{dashboard_id}/budget", headers=viewer["headers"], json=row)
    assert denied.status_code in (403, 404)
    saved = _save(client, editor["headers"], dashboard_id, {"budgetLines": [{
        "id": "line-e", "label": "שכירות", "category": "rent",
        "months": {"2026-03": {"quantity": 2, "rate": 50}},
    }]})
    assert saved.status_code == 200, saved.text
    with SessionLocal() as db:
        march = db.query(Budget).filter_by(
            organization_id=owner["org_id"], year=2026, month=3, category_name="rent",
        ).one()
        assert march.budgeted_amount == Decimal("100.00")
    blocked = _save(client, viewer["headers"], dashboard_id, {"budgetLines": []},
                    version=saved.json()["version"])
    assert blocked.status_code == 404


def test_filing_module_does_not_call_a_provider():
    import cfo.services.dashboards.filing as filing
    import cfo.services.dashboards.filing_report as filing_report
    import cfo.services.dashboards.plan_budget as plan_budget
    assert hasattr(filing, "classify_builtin")
    assert not hasattr(filing, "file_transactions")
    for module in (filing, filing_report, plan_budget):
        text = Path(module.__file__).read_text(encoding="utf-8").lower()
        for banned in ("sumit_integration", "open_finance", "financy"):
            assert banned not in text
