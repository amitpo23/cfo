"""Version-3 dashboard plan: validation, budget projection, concurrency, roles.

No provider calls. The loose plan endpoint is a different contract.
"""
import ast
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from cfo.database import SessionLocal
from cfo.models import (
    AuditLog, Budget, Category, DashboardMember, DashboardPlan, DashboardPlanRevision, User,
)


def _plan(lines=None, **overrides):
    body = {
        "budgetLines": lines if lines is not None else [
            {"group": "הפעלה", "category": "שיווק ופרסום", "month": "2026-03", "amount": "150.00"},
            {"group": "הפעלה", "category": "שכירות", "month": "2026-03", "amount": "1000"},
        ],
        "statusDecisions": {
            "12": {"category": "rent", "organizationId": 1, "date": "2026-03-01", "amount": 100},
        },
        "statusRules": [{"id": "r1", "contains": "בזק", "category": "office"}],
        "booksClosedMonths": ["2026-03"],
        "notes": "הערה ללקוח",
    }
    body.update(overrides)
    return body


def _create(client, headers, org_id, slug):
    response = client.post("/api/dashboards", headers=headers, json={
        "primary_organization_id": org_id, "slug": slug, "title": "תוכנית", "access_mode": "link",
    })
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _put(client, headers, dashboard_id, body, match):
    sent = dict(headers)
    if match is not None:
        sent["If-Match"] = match
    return client.put(f"/api/dashboards/{dashboard_id}/plan/v3", headers=sent, json=body)


def _add_member(dashboard_id, org_id, role):
    with SessionLocal() as db:
        user = db.query(User).filter(User.organization_id == org_id).one()
        db.add(DashboardMember(dashboard_id=dashboard_id, user_id=user.id, role=role, status="active"))
        db.commit()


def test_unknown_fields_bank_decisions_and_bad_lines_are_rejected(client, fresh_org):
    owner = fresh_org()
    dashboard_id = _create(client, owner["headers"], owner["org_id"], f"plan-bad-{owner['org_id']}")
    missing = _put(client, owner["headers"], dashboard_id, _plan(), None)
    assert missing.status_code == 412
    assert missing.json()["error"]["code"] == "if_match_required"

    cases = [
        _plan(bankDecisions=[{"account": "1"}]),
        _plan(owner_id=5),
        _plan(lines=[{"group": "הפעלה", "category": "שכירות", "month": "2026-03", "amount": "1", "year": 2026}]),
        _plan(lines=[{"group": "הפעלה", "category": "שכירות", "month": "2026-13", "amount": "1"}]),
        _plan(lines=[{"group": "הפעלה", "category": "שכירות", "month": "03", "amount": "1"}]),
        _plan(lines=[{"group": "הפעלה", "category": "שכירות", "month": "2026-03", "amount": -1}]),
        _plan(lines=[{"group": "הפעלה", "category": "שכירות", "month": "2026-03", "amount": "abc"}]),
        _plan(lines=[{"group": "הפעלה", "category": "שכירות", "month": "2026-03", "amount": True}]),
        _plan(lines=[{"group": "  ", "category": "שכירות", "month": "2026-03", "amount": "1"}]),
        _plan(lines=[
            {"group": "א", "category": "marketing", "month": "2026-03", "amount": "1"},
            {"group": "ב", "category": "שיווק ופרסום", "month": "2026-03", "amount": "2"},
        ]),
        {key: value for key, value in _plan().items() if key != "notes"},
        _plan(statusDecisions=[{"category": "rent"}]),
        _plan(statusRules=[{"contains": "x", "category": "other_in"}]),
        _plan(booksClosedMonths=["2026-13"]),
        _plan(statusRules=[{"contains": "   ", "category": "office"}]),
    ]
    for body in cases:
        response = _put(client, owner["headers"], dashboard_id, body, "0")
        assert response.status_code == 422, response.text
        assert response.json()["error"]["code"] == "invalid_plan"
    bank = _put(client, owner["headers"], dashboard_id, cases[0], "0")
    assert "נגזרות" in bank.json()["error"]["message_he"]
    unknown_category = _put(
        client, owner["headers"], dashboard_id,
        _plan(statusRules=[{"contains": "x", "category": "other_in"}]), "0",
    )
    assert unknown_category.json()["error"]["message_he"] == "קטגוריית הכלל אינה מוכרת"
    bad_month = _put(
        client, owner["headers"], dashboard_id, _plan(booksClosedMonths=["2026-13"]), "0",
    )
    assert bad_month.json()["error"]["message_he"] == "רשימת החודשים הסגורים לא תקינה"
    with SessionLocal() as db:
        assert db.query(DashboardPlan).filter_by(dashboard_id=dashboard_id).count() == 0
        assert db.query(Budget).filter_by(organization_id=owner["org_id"]).count() == 0
        assert db.query(Category).filter_by(organization_id=owner["org_id"]).count() == 0
        assert db.query(AuditLog).filter_by(
            organization_id=owner["org_id"], action="SAVE_DASHBOARD_PLAN_V3",
        ).count() == 0


def test_projection_is_idempotent_and_audited(client, fresh_org):
    owner = fresh_org()
    other = fresh_org()
    dashboard_id = _create(client, owner["headers"], owner["org_id"], f"plan-proj-{owner['org_id']}")
    empty = client.get(f"/api/dashboards/{dashboard_id}/plan/v3", headers=owner["headers"])
    assert empty.status_code == 200, empty.text
    assert empty.json()["revision"] == 0
    assert empty.json()["plan"] is None
    assert empty.json()["provider_calls"] == 0
    assert empty.headers["etag"] == '"0"'

    first = _put(client, owner["headers"], dashboard_id, _plan(), "0")
    assert first.status_code == 200, first.text
    assert first.json()["revision"] == 1
    assert first.json()["schema_version"] == 3
    assert first.json()["provider_calls"] == 0
    assert first.json()["projected"]["categories_created"] == 3
    assert first.json()["plan"]["budgetLines"][0]["amount"] == "150.00"
    assert "bankDecisions" not in first.json()["plan"]
    assert first.headers["etag"] == '"1"'

    # The Hebrew label and the P&L code are one category: update, do not insert.
    second_body = _plan(lines=[
        {"group": "הפעלה", "category": "marketing", "month": "2026-03", "amount": "250.50"},
        {"group": "הפעלה", "category": "שכירות", "month": "2026-03", "amount": "1000"},
    ])
    second = _put(client, owner["headers"], dashboard_id, second_body, first.headers["etag"])
    assert second.status_code == 200, second.text
    assert second.json()["revision"] == 2
    assert second.json()["projected"]["categories_created"] == 0
    third = _put(client, owner["headers"], dashboard_id, second_body, "2")
    assert third.status_code == 200, third.text
    assert third.json()["projected"]["categories_created"] == 0

    with SessionLocal() as db:
        groups = db.query(Category).filter_by(organization_id=owner["org_id"], parent_id=None).all()
        assert [row.name for row in groups] == ["הפעלה"]
        leaves = db.query(Category).filter(
            Category.organization_id == owner["org_id"], Category.parent_id.is_not(None),
        ).all()
        assert len(leaves) == 2
        budgets = db.query(Budget).filter_by(organization_id=owner["org_id"]).all()
        assert len(budgets) == 2
        marketing = next(row for row in budgets if row.category_name == "marketing")
        rent = next(row for row in budgets if row.category_name == "rent")
        assert marketing.budgeted_amount == Decimal("250.50")
        assert marketing.year == 2026 and marketing.month == 3
        assert rent.budgeted_amount == Decimal("1000.00")
        assert db.query(Budget).filter_by(organization_id=other["org_id"]).count() == 0
        assert db.query(Category).filter_by(organization_id=other["org_id"]).count() == 0
        audits = db.query(AuditLog).filter_by(
            organization_id=owner["org_id"], action="SAVE_DASHBOARD_PLAN_V3",
        ).all()
        assert len(audits) == 3
        assert audits[-1].details["provider_calls"] == 0
        assert db.query(DashboardPlanRevision).filter_by(dashboard_id=dashboard_id).count() == 3
        stored = db.get(DashboardPlan, dashboard_id)
        assert stored.schema_version == 3
        assert "bankDecisions" not in stored.payload

    listed = client.get(f"/api/dashboards/{dashboard_id}/plan/v3", headers=owner["headers"])
    assert listed.status_code == 200
    assert listed.json()["revision"] == 3
    assert listed.json()["plan"]["notes"] == "הערה ללקוח"
    assert listed.json()["plan"]["statusDecisions"]["12"]["category"] == "rent"
    assert listed.json()["plan"]["statusRules"][0]["id"] == "r1"
    assert listed.json()["plan"]["booksClosedMonths"] == ["2026-03"]


def test_stale_revision_conflicts_and_rolls_back(client, fresh_org):
    owner = fresh_org()
    dashboard_id = _create(client, owner["headers"], owner["org_id"], f"plan-race-{owner['org_id']}")
    saved = _put(client, owner["headers"], dashboard_id, _plan(), "0")
    assert saved.status_code == 200, saved.text
    stale = _put(client, owner["headers"], dashboard_id, _plan(notes="אחר"), "0")
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "plan_conflict"
    with SessionLocal() as db:
        current_version = db.get(DashboardPlan, dashboard_id).version
        db.add(DashboardPlanRevision(
            version=f"block-{dashboard_id}", dashboard_id=dashboard_id,
            previous_version=current_version, payload={"blocked": True},
            changed_at=datetime.utcnow(),
        ))
        db.commit()
    raced = _put(
        client, owner["headers"], dashboard_id,
        _plan(lines=[{"group": "הפעלה", "category": "שכירות", "month": "2026-04", "amount": "999"}]),
        "1",
    )
    assert raced.status_code == 409, raced.text
    assert raced.json()["error"]["code"] == "plan_conflict"
    with SessionLocal() as db:
        stored = db.get(DashboardPlan, dashboard_id)
        assert stored.version == current_version
        assert stored.payload["notes"] == "הערה ללקוח"
        budgets = db.query(Budget).filter_by(organization_id=owner["org_id"]).all()
        assert {row.month for row in budgets} == {3}
        assert db.query(Budget).filter_by(organization_id=owner["org_id"], month=4).count() == 0
        assert db.query(AuditLog).filter_by(
            organization_id=owner["org_id"], action="SAVE_DASHBOARD_PLAN_V3",
        ).count() == 1
        assert db.query(DashboardPlanRevision).filter_by(dashboard_id=dashboard_id).count() == 2


def test_editors_write_viewers_read_and_strangers_are_hidden(client, fresh_org):
    owner = fresh_org()
    editor = fresh_org()
    accountant = fresh_org()
    viewer = fresh_org()
    stranger = fresh_org()
    dashboard_id = _create(client, owner["headers"], owner["org_id"], f"plan-auth-{owner['org_id']}")
    _add_member(dashboard_id, editor["org_id"], "client_editor")
    _add_member(dashboard_id, accountant["org_id"], "accountant")
    _add_member(dashboard_id, viewer["org_id"], "client_viewer")

    denied = _put(client, viewer["headers"], dashboard_id, _plan(), "0")
    assert denied.status_code == 404
    assert denied.json()["error"]["code"] == "not_found"
    hidden = _put(client, stranger["headers"], dashboard_id, _plan(), "0")
    assert hidden.status_code == 404
    assert client.get(f"/api/dashboards/{dashboard_id}/plan/v3", headers=stranger["headers"]).status_code == 404
    unauthenticated = client.put(
        f"/api/dashboards/{dashboard_id}/plan/v3",
        headers={"If-Match": "0"}, json=_plan(),
    )
    assert unauthenticated.status_code in (401, 403)

    written = _put(client, editor["headers"], dashboard_id, _plan(), "0")
    assert written.status_code == 200, written.text
    readable = client.get(f"/api/dashboards/{dashboard_id}/plan/v3", headers=viewer["headers"])
    assert readable.status_code == 200, readable.text
    assert readable.json()["revision"] == 1
    updated = _put(client, accountant["headers"], dashboard_id, _plan(notes="רואה חשבון"), '"1"')
    assert updated.status_code == 200, updated.text
    assert updated.json()["plan"]["notes"] == "רואה חשבון"
    with SessionLocal() as db:
        assert db.query(Budget).filter_by(organization_id=viewer["org_id"]).count() == 0
        assert db.query(Budget).filter_by(organization_id=owner["org_id"]).count() == 2


def test_plan_v3_modules_do_not_import_a_provider():
    files = [
        Path("src/cfo/services/dashboards/plan_v3.py"),
        Path("src/cfo/api/routes/dashboard_plan_v3.py"),
    ]
    banned = ("sumit_integration", "open_finance", "httpx", "financy")
    for path in files:
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = []
                if isinstance(node, ast.ImportFrom):
                    names.append(node.module or "")
                    names.extend(alias.name for alias in node.names)
                else:
                    names.extend(alias.name for alias in node.names)
                blob = " ".join(names)
                assert not any(word in blob for word in banned), path


def test_removed_lines_drop_their_budget_rows_and_manual_rows_stay(client, fresh_org):
    owner = fresh_org()
    dashboard_id = _create(client, owner["headers"], owner["org_id"], f"plan-trim-{owner['org_id']}")
    manual = client.put(f"/api/dashboards/{dashboard_id}/budget", headers=owner["headers"], json={"rows": [
        {"year": 2026, "month": 1, "category": "insurance", "budgeted_amount": 7, "notes": "ידני"},
    ]})
    assert manual.status_code == 200, manual.text
    first = _put(client, owner["headers"], dashboard_id, _plan(), "0")
    assert first.status_code == 200, first.text
    trimmed = _put(client, owner["headers"], dashboard_id, _plan(lines=[
        {"group": "הפעלה", "category": "שכירות", "month": "2026-03", "amount": "900"},
    ]), "1")
    assert trimmed.status_code == 200, trimmed.text
    with SessionLocal() as db:
        rows = db.query(Budget).filter_by(organization_id=owner["org_id"]).all()
        keys = {(row.year, row.month, row.category_name): row for row in rows}
        assert (2026, 3, "marketing") not in keys
        assert keys[(2026, 3, "rent")].budgeted_amount == Decimal("900.00")
        assert keys[(2026, 3, "rent")].notes == f"plan:{dashboard_id}-2"
        assert keys[(2026, 1, "insurance")].notes == "ידני"


def test_a_stored_plan_that_v3_would_truncate_is_not_overwritten(client, fresh_org):
    owner = fresh_org()
    dashboard_id = _create(client, owner["headers"], owner["org_id"], f"plan-legacy-{owner['org_id']}")
    loose = client.put(
        f"/api/dashboards/{dashboard_id}/plan",
        headers={**owner["headers"], "If-Match": "null"},
        json={"payload": {"statusParameters": {"scenario": "base"}, "booksClosedMonths": ["2026-01"]}},
    )
    assert loose.status_code == 200, loose.text
    read = client.get(f"/api/dashboards/{dashboard_id}/plan/v3", headers=owner["headers"])
    assert read.json()["plan"] is None
    refused = _put(client, owner["headers"], dashboard_id, _plan(), read.headers["etag"])
    assert refused.status_code == 409, refused.text
    assert refused.json()["error"]["code"] == "plan_schema_mismatch"
    with SessionLocal() as db:
        stored = db.get(DashboardPlan, dashboard_id)
        assert stored.payload["statusParameters"] == {"scenario": "base"}
        assert db.query(Budget).filter_by(organization_id=owner["org_id"]).count() == 0
