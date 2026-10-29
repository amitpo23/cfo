"""The legacy /budget quarter must not compare three months of budget with one month of actual."""
from datetime import date

from cfo.api.routes import financial_management


def test_current_quarter_does_not_triple_a_monthly_budget(client, fresh_org, monkeypatch):
    owner = fresh_org()
    created = client.post("/api/dashboards", headers=owner["headers"], json={
        "primary_organization_id": owner["org_id"], "slug": "quarter-window", "title": "רבעון", "access_mode": "link",
    })
    assert created.status_code == 201, created.text
    updates = []
    for month in ("2026-10", "2026-11", "2026-12"):
        updates.append({
            "id": "sales", "label": "מכירות", "category": "sales", "kind": "revenue",
            "month": month, "status": "filled", "amount": 283200,
        })
        updates.append({
            "id": "other", "label": "אחר", "category": "other", "kind": "cost",
            "month": month, "status": "filled", "amount": 226000,
        })
    saved = client.put("/api/financial/budget/lines", headers=owner["headers"], json={"updates": updates})
    assert saved.status_code == 200, saved.text

    class _Date(date):
        @classmethod
        def today(cls):
            return date(2026, 10, 29)

    monkeypatch.setattr(financial_management, "date", _Date)
    response = client.get("/api/financial/budget/vs-actual", headers=owner["headers"], params={
        "year": 2026, "month": 10, "period": "quarter",
    })
    assert response.status_code == 200, response.text
    totals = response.json()["data"]["totals"]
    assert totals["revenue"]["budget"] == 283200
    assert totals["costs"]["budget"] == 226000
    assert totals["revenue"]["budget"] != 849600
    assert totals["costs"]["budget"] != 678000
