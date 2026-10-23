"""/d/ makes no provider call, proven at run time.

``test_client_dashboards.test_dashboard_package_does_not_import_a_provider`` checks
the imports of the dashboard package itself. The services it reads through
(bank coverage, financial reports, live cash flow) are outside that scan, so this
test traps every way out: building a SUMIT or Open Finance client, or sending any
request through an httpx network transport, fails the request. The editor's view, filing and plan, a share-link
session and the public live view are all built under the trap."""
from datetime import date

import httpx
import pytest

from cfo.database import SessionLocal
from cfo.integrations.sumit_integration import SumitIntegration
from cfo.services.open_finance_client import OpenFinanceClient
from tests.test_dashboard_eliav_ui_fixes import _account, _bank, _consolidated


class ProviderCalled(AssertionError):
    pass


def _trap(*_args, **_kwargs):
    raise ProviderCalled("a /d/ request reached a provider client")


@pytest.fixture
def trapped(monkeypatch):
    monkeypatch.setattr(SumitIntegration, "__init__", _trap)
    monkeypatch.setattr(OpenFinanceClient, "__init__", _trap)
    # The network transports, not Client.send: the test client is an httpx.Client too,
    # with its own in-process transport.
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", _trap)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", _trap)


def test_every_d_read_builds_without_touching_a_provider(client, fresh_org, platform_admin, trapped):
    dashboard_id, chef, food = _consolidated(client, platform_admin, fresh_org, "trap-provider")
    with SessionLocal() as db:
        chef_main = _account(db, chef["org_id"], "עו״ש 8954", 0).id
        food_main = _account(db, food["org_id"], "Imported bank 1662", None, source="reviewed_local_import").id
        _bank(db, chef["org_id"], date(2026, 9, 2), 5000, "העברה מבנק הפועלים", account_id=chef_main)
        _bank(db, food["org_id"], date(2026, 8, 30), -5000, "העברה לשף", account_id=food_main)
        db.commit()
    headers = platform_admin["headers"]
    for path in (f"/api/dashboards/{dashboard_id}/view", f"/api/dashboards/{dashboard_id}/filing",
                 f"/api/dashboards/{dashboard_id}/plan", "/api/dashboards/by-slug/trap-provider"):
        response = client.get(path, headers=headers)
        assert response.status_code == 200, (path, response.text)
        assert response.json().get("provider_calls", 0) == 0
    activated = client.patch(f"/api/dashboards/{dashboard_id}", headers=headers, json={"status": "active"})
    assert activated.status_code == 200, activated.text
    token = client.post(f"/api/dashboards/{dashboard_id}/share-links", headers=headers, json={}).json()["token"]
    opened = client.post("/api/public/d/trap-provider/session", json={"token": token})
    assert opened.status_code == 200, opened.text
    public = client.get("/api/public/d/trap-provider")
    assert public.status_code == 200, public.text
    assert public.json()["source"] == "live" and public.json()["provider_calls"] == 0


def test_the_trap_itself_fires(trapped):
    with pytest.raises(ProviderCalled):
        OpenFinanceClient()
    with pytest.raises(ProviderCalled):
        httpx.Client().get("http://localhost/")
