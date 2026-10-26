"""Moshko answers "how much room is left, and until when" from the 13-week cash forecast.

Owner request 26/10/2026: Moshko must give the same answer as the "תזרים חזוי" tab,
not the older overdraft-only tools. The tool reads the dashboard whose primary
organization is the chat's organization. No provider calls.
"""
import asyncio
from datetime import date, datetime
from decimal import Decimal

from cfo.database import SessionLocal
from cfo.models import Account, AccountType, ClientDashboard
from cfo.services.ai_chat_tools import TOOLS


def _dashboard(client, platform_admin, org_id, slug):
    response = client.post("/api/dashboards", headers=platform_admin["headers"], json={
        "primary_organization_id": org_id, "slug": slug, "title": "עסק", "access_mode": "link",
    })
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _call(org_id, **kwargs):
    with SessionLocal() as db:
        return asyncio.run(TOOLS["get_cash_forecast"].fn(db, org_id, _today=date(2026, 10, 26), **kwargs))


def test_the_tool_is_a_read_tool_open_to_every_role():
    tool = TOOLS["get_cash_forecast"]
    assert tool.category == "read"
    assert tool.office is False


def test_it_answers_with_the_breach_week_and_its_reasons(client, fresh_org, platform_admin):
    from tests.test_dashboard_eliav_ui_r2 import _put
    org = fresh_org()
    dashboard_id = _dashboard(client, platform_admin, org["org_id"], "moshko-forecast")
    with SessionLocal() as db:
        db.add(Account(
            organization_id=org["org_id"], name="עו״ש", account_type=AccountType.BANK, raw_account_type="CHECKING",
            balance=Decimal("-20000"), source="open_finance", balance_as_of=datetime(2026, 10, 21),
        ))
        db.commit()
    assert _put(client, platform_admin["headers"], dashboard_id, {"liquidityEvidence": {"facilities": [
        {"label": "מסגרת", "organizationId": org["org_id"], "limit": 15000},
    ]}}).status_code == 200

    result = _call(org["org_id"])

    assert result["status"] == "ready"
    entity = result["entities"][0]
    assert entity["opening"] == {"amount": -20000.0, "as_of": "2026-10-21"}
    assert entity["first_breach"]["week_start"] == "2026-10-25"
    assert entity["first_breach"]["reasons"]
    assert len(entity["weeks"]) == 13
    assert set(entity["weeks"][0]) == {"start", "end", "in", "out", "closing", "limit", "headroom"}
    assert result["provider_calls"] == 0


def test_without_a_dashboard_it_says_so_instead_of_guessing(fresh_org):
    result = _call(fresh_org()["org_id"])

    assert result["status"] == "unknown"
    assert "דשבורד" in result["message"]


def test_it_never_reads_a_dashboard_of_another_organization(client, fresh_org, platform_admin):
    owner, other = fresh_org(), fresh_org()
    _dashboard(client, platform_admin, owner["org_id"], "moshko-forecast-owner")

    result = _call(other["org_id"], slug="moshko-forecast-owner")

    assert result["status"] == "unknown"


def test_the_cfo_hat_reaches_for_the_cash_forecast_first():
    from cfo.services.ai_chat_personas import PERSONAS

    assert "get_cash_forecast" in PERSONAS["cfo"].prompt_addendum
