"""בדיקות endpoints של תקציב — אין קריסות, והתרחיש המותאם עובד."""


def test_budget_vs_actual_no_crash(client, owner):
    r = client.get("/api/financial/budget/vs-actual", headers=owner["headers"])
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert "categories" in data


def test_budget_alerts_list(client, owner):
    r = client.get("/api/financial/budget/alerts", headers=owner["headers"])
    assert r.status_code == 200, r.text
    assert isinstance(r.json()["data"], list)


def test_budget_scenario_custom_pct(client, owner):
    r = client.post("/api/financial/budget/scenario", json={
        "revenue_change_pct": 10, "expense_change_pct": -5,
    }, headers=owner["headers"])
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    for k in ("projected_revenue", "projected_expenses", "projected_net_income"):
        assert k in data
    # נטו = הכנסות צפויות פחות הוצאות צפויות
    assert round(data["projected_net_income"], 2) == round(
        data["projected_revenue"] - data["projected_expenses"], 2
    )


def test_tax_calendar_no_crash(client, owner):
    r = client.get("/api/financial/tax/calendar", headers=owner["headers"])
    assert r.status_code == 200, r.text
    assert "upcoming_deadlines" in r.json()["data"]


def test_budget_persists_and_affects_vs_actual(client):
    """תקציב שנוצר נשמר ב-DB ומשתקף בהשוואה מול ביצוע (הטמעת תקציב)."""
    from datetime import date
    reg = client.post("/api/admin/auth/register", json={
        "email": "budgetowner@example.com", "password": "secret123", "full_name": "Budget Owner",
    })
    assert reg.status_code == 201, reg.text
    h = {"Authorization": f"Bearer {reg.json()['access_token']}"}
    today = date.today()

    create = client.post("/api/financial/budget", json={
        "category": "materials",
        "planned_amount": 50000,
        "period_start": today.replace(day=1).isoformat(),
        "period_end": today.isoformat(),
    }, headers=h)
    assert create.status_code == 200, create.text

    # ההשוואה מול ביצוע צריכה לכלול את התקציב שנשמר
    va = client.get(
        f"/api/financial/budget/vs-actual?year={today.year}&month={today.month}",
        headers=h,
    )
    assert va.status_code == 200, va.text
    cats = va.json()["data"]["categories"]
    materials = [c for c in cats if c.get("category_id") == "materials" or c.get("category_name") == "materials"]
    assert materials, cats
    assert materials[0]["budget_amount"] == 50000
