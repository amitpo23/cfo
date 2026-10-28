"""Daily watch over the 13-week cash forecast of every dashboard.

Owner request 26/10/2026: "a cron that runs, checks and does". The watch reads
the database only and keeps one CfoInsight per finding per organization: a
projected breach of the credit facility, a past-due maturity, a facility that
drops within 60 days, a missing opening balance. A finding that no longer holds
is resolved. No provider calls.
"""
from datetime import date, datetime
from decimal import Decimal

from cfo.database import SessionLocal
from cfo.models import Account, AccountType, CfoInsight, ClientDashboard, SumitCompany

TODAY = date(2026, 10, 26)


def _dashboard(client, platform_admin, fresh_org, slug, *, balance="-35000"):
    chef, food, office = fresh_org(), fresh_org(), fresh_org()
    response = client.post("/api/dashboards", headers=platform_admin["headers"], json={
        "primary_organization_id": chef["org_id"], "slug": slug, "title": "שף", "access_mode": "link",
    })
    assert response.status_code == 201, response.text
    dashboard_id = response.json()["id"]
    with SessionLocal() as db:
        db.get(ClientDashboard, dashboard_id).office_organization_id = office["org_id"]
        for org, name in ((chef, "השף"), (food, "פוד גרופ")):
            db.add(SumitCompany(office_organization_id=office["org_id"], company_id=f"file-{org['org_id']}",
                                name=name, status="active", target_organization_id=org["org_id"]))
        db.add(Account(
            organization_id=chef["org_id"], name="עו״ש", account_type=AccountType.BANK,
            raw_account_type="CHECKING", balance=Decimal(balance), source="open_finance",
            balance_as_of=datetime(2026, 10, 26),
        ))
        db.commit()
    added = client.post(f"/api/dashboards/{dashboard_id}/entities", headers=platform_admin["headers"],
                        json={"organization_id": food["org_id"], "label": "פוד גרופ"})
    assert added.status_code == 201, added.text
    return dashboard_id, chef, food


def _plan(client, headers, dashboard_id, payload):
    from tests.test_dashboard_eliav_ui_r2 import _put
    assert _put(client, headers, dashboard_id, payload).status_code == 200


def _watch(dashboard_id):
    from cfo.services.dashboards import cash_forecast_watch
    with SessionLocal() as db:
        return cash_forecast_watch.run_watch(db, TODAY, dashboard_ids=[dashboard_id])


def _insights(org_id, insight_type=None):
    with SessionLocal() as db:
        query = db.query(CfoInsight).filter(CfoInsight.organization_id == org_id)
        if insight_type:
            query = query.filter(CfoInsight.insight_type == insight_type)
        return [(row.insight_type, row.severity, row.status, row.fingerprint, row.title) for row in query.all()]


def test_a_breach_in_the_coming_weeks_raises_a_critical_insight_with_its_week(client, fresh_org, platform_admin):
    dashboard_id, chef, _food = _dashboard(client, platform_admin, fresh_org, "watch-breach")
    _plan(client, platform_admin["headers"], dashboard_id, {"liquidityEvidence": {"facilities": [
        {"label": "מסגרת 8954", "organizationId": chef["org_id"], "limit": 15000},
    ]}})

    result = _watch(dashboard_id)

    breach = _insights(chef["org_id"], "cash_forecast_breach")
    assert len(breach) == 1
    _type, severity, status, fingerprint, title = breach[0]
    assert (severity, status) == ("critical", "active")
    assert fingerprint == "cash_forecast_breach:2026-10-25"
    assert "25/10" in title
    assert result["provider_calls"] == 0


def test_a_second_run_updates_the_insight_instead_of_adding_one(client, fresh_org, platform_admin):
    dashboard_id, chef, _food = _dashboard(client, platform_admin, fresh_org, "watch-twice")
    _plan(client, platform_admin["headers"], dashboard_id, {"liquidityEvidence": {"facilities": [
        {"label": "מסגרת 8954", "organizationId": chef["org_id"], "limit": 15000},
    ]}})

    _watch(dashboard_id)
    _watch(dashboard_id)

    assert len(_insights(chef["org_id"], "cash_forecast_breach")) == 1


def test_a_finding_that_no_longer_holds_is_resolved(client, fresh_org, platform_admin):
    dashboard_id, chef, _food = _dashboard(client, platform_admin, fresh_org, "watch-resolve")
    _plan(client, platform_admin["headers"], dashboard_id, {"liquidityEvidence": {"facilities": [
        {"label": "מסגרת 8954", "organizationId": chef["org_id"], "limit": 15000},
    ]}})
    _watch(dashboard_id)

    _plan(client, platform_admin["headers"], dashboard_id, {"liquidityEvidence": {"facilities": [
        {"label": "מסגרת 8954", "organizationId": chef["org_id"], "limit": 500000},
    ]}})
    _watch(dashboard_id)

    assert [row[2] for row in _insights(chef["org_id"], "cash_forecast_breach")] == ["resolved"]


def test_a_past_due_maturity_and_a_missing_balance_each_raise_an_insight(client, fresh_org, platform_admin):
    dashboard_id, _chef, food = _dashboard(client, platform_admin, fresh_org, "watch-overdue")
    _plan(client, platform_admin["headers"], dashboard_id, {"liquidityEvidence": {"loans": [
        {"label": "גישור", "organizationId": food["org_id"], "balance": 50000.0, "maturity": "2026-10-25"},
    ]}})

    _watch(dashboard_id)

    overdue = _insights(food["org_id"], "cash_forecast_overdue")
    assert len(overdue) == 1 and overdue[0][1] == "high" and "גישור" in overdue[0][4]
    assert [row[1] for row in _insights(food["org_id"], "cash_forecast_missing")] == ["low"]


def test_a_facility_that_drops_within_60_days_raises_an_insight(client, fresh_org, platform_admin):
    dashboard_id, chef, _food = _dashboard(client, platform_admin, fresh_org, "watch-facility", balance="100000")
    _plan(client, platform_admin["headers"], dashboard_id, {"liquidityEvidence": {"facilities": [
        {"label": "מסגרת 1662", "organizationId": chef["org_id"], "limit": 80000, "validTo": "2026-12-15"},
    ]}})

    _watch(dashboard_id)

    drop = _insights(chef["org_id"], "cash_forecast_facility_drop")
    assert len(drop) == 1 and drop[0][1] == "medium" and "80,000" in drop[0][4]


def test_the_cron_route_needs_the_secret_and_reports_no_provider_calls(client, monkeypatch):
    from cfo.services.dashboards import cash_forecast_watch

    monkeypatch.setattr(cash_forecast_watch, "run_watch",
                        lambda _db, _today, dashboard_ids=None: {"dashboards": 0, "provider_calls": 0})
    assert client.get("/api/cron/cashflow-watch").status_code == 401
    response = client.get("/api/cron/cashflow-watch", headers={"Authorization": "Bearer test-cron-secret"})
    assert response.status_code == 200, response.text
    assert response.json()["provider_calls"] == 0
