"""Custom driver lines stay separate from the fixed assumption buckets.

Two income lines and their costs add up. A missing culinary line is not 0.
A round million of income stays stored and stays out of the totals.
"""
from datetime import date

from cfo.database import SessionLocal
from cfo.services.dashboards import cash_forecast, forecast_rules
from cfo.services.dashboards.books_pnl import books_pnl
from cfo.services.dashboards.budget_fill import apply_updates, driver_csv_updates
from cfo.services.dashboards.plan_budget import monthly_line_sums, validate_budget_lines

MONTH = "2026-11"


def _drivers():
    rows = [
        ("משלוחים", "del_revenue", "הכנסות משלוחים", "income", 14400, 10.5, 151200),
        ("משלוחים", "del_drivers", "נהגים", "expense", 14400, 5, 72000),
        ("משלוחים", "del_vehicles", "עלויות רכבים", "expense", 14400, 2, 28800),
        ("משלוחים", "del_new_vehicle_ops", "רכב חדש ואופרציה", "expense", 1, 12000, 12000),
        ("משלוחים", "del_ga", "הנהלה וכלליות", "expense", 1, 10000, 10000),
        ("פיצה", "piz_revenue", "הכנסות פיצה", "income", 22, 6000, 132000),
        ("פיצה", "piz_drivers", "שליחים", "expense", 66, 600, 39600),
        ("פיצה", "piz_food_cost", "פוד קוסט", "expense", 1, 39600, 39600),
        ("פיצה", "piz_rent", "שכר דירה", "expense", 1, 5000, 5000),
        ("פיצה", "piz_energy", "חשמל ואנרגיה", "expense", 1, 5000, 5000),
        ("פיצה", "piz_order_taker", "מקבלת הזמנות", "expense", 1, 9000, 9000),
        ("פיצה", "piz_ads", "פרסום", "expense", 1, 5000, 5000),
    ]
    updates = []
    for division, line_id, label, kind, qty, price, amount in rows:
        updates.append({
            "id": line_id, "label": label, "kind": kind, "custom": True,
            "division": division, "source": "עמית", "driver_formula": f"{qty}×{price}",
            "qty": qty, "unit_price": price, "amount": amount,
            "month": MONTH, "status": "assumption",
        })
    updates.append({
        "id": "cul_all", "label": "חטיבת קולינריה", "kind": "income", "custom": True,
        "division": "קולינריה", "covers": "income_and_expense", "source": "לא נמסר",
        "month": MONTH, "status": "missing",
    })
    updates.append({
        "id": "assumption:income", "label": "הכנסות", "category": "revenue", "kind": "revenue",
        "month": MONTH, "status": "filled", "amount": 10_000_000,
    })
    return updates


def _plan():
    return apply_updates({"budgetLines": []}, _drivers())


def test_custom_lines_stay_separate_and_missing_is_not_zero():
    plan = _plan()
    ids = [line["id"] for line in plan["budgetLines"]]
    assert ids.count("del_revenue") == 1
    assert ids.count("piz_revenue") == 1
    assert "assumption:income" in ids
    culinary = next(line for line in plan["budgetLines"] if line["id"] == "cul_all")
    assert culinary["division"] == "קולינריה"
    assert culinary["months"] == {}
    assert culinary.get("months", {}).get(MONTH) is None

    validated = validate_budget_lines(plan)
    assert forecast_rules.income_amount(validated, MONTH) == 283200
    sums = monthly_line_sums(validated)
    assert sums[MONTH]["revenue"] == 283200.0
    assert sums[MONTH]["cost"] == 226000.0
    costs = forecast_rules.custom_operating_items(validated, date(2026, 11, 1), date(2026, 11, 30))
    assert round(sum(-item["amount"] for item in costs), 2) == 226000
    assert all(item["division"] in {"משלוחים", "פיצה"} for item in costs)
    assert not any(item["label"] == "חטיבת קולינריה" for item in costs)


def test_books_and_weekly_forecast_include_the_driver_lines(client):
    plan = _plan()
    from cfo.database import SessionLocal
    from cfo.models import Organization
    db = SessionLocal()
    try:
        org = Organization(name="driver-budget", is_active=True)
        db.add(org)
        db.commit()
        report = books_pnl(db, org.id, start=date(2026, 11, 1), end=date(2026, 11, 30), plan=plan)
    finally:
        db.close()
    assert report["months"][0]["budget_revenue"] == 283200.0
    assert report["months"][0]["budget_costs"] == 226000.0
    view = {
        "liquidity": {"position": {"balance": None, "as_of": None, "limit": None}, "checks": [], "upcoming": [], "debt_service": []},
        "cash_statement": {"months": [], "lines": []},
        "pnl": {"total_revenue": None, "total_expenses": None},
        "budget_vs_actual": {"status": "unknown", "months": []},
    }
    forecast = cash_forecast.build_entity_forecast(view, plan=plan, organization_id=1, label="פוד", today=date(2026, 11, 1))
    labels = [item.get("label") for week in forecast["weeks"] for item in week["items"]]
    assert any(label == "נהגים" for label in labels)
    assert any(label == "פוד קוסט" for label in labels)
    assert "חטיבת קולינריה" not in labels
    assert "הכנסות משלוחים" not in labels


def test_save_lists_and_removes_a_custom_line(client, fresh_org):
    owner = fresh_org()
    created = client.post("/api/dashboards", headers=owner["headers"], json={
        "primary_organization_id": owner["org_id"], "slug": "driver-lines", "title": "דרייברים", "access_mode": "link",
    })
    assert created.status_code == 201, created.text
    saved = client.put("/api/financial/budget/lines", headers=owner["headers"], json={"updates": _drivers()})
    assert saved.status_code == 200, saved.text
    listed = client.get("/api/financial/budget/lines", headers=owner["headers"], params={
        "year": 2026, "from_month": 11, "to_month": 11,
    })
    assert listed.status_code == 200, listed.text
    lines = {row["id"]: row for row in listed.json()["data"]["lines"]}
    assert lines["del_revenue"]["custom"] is True
    assert lines["del_revenue"]["division"] == "משלוחים"
    assert lines["del_revenue"]["months"]["2026-11"]["amount"] == "151200.00"
    assert lines["piz_revenue"]["months"]["2026-11"]["amount"] == "132000.00"
    culinary = lines["cul_all"]["months"]["2026-11"]
    assert culinary["amount"] is None
    assert culinary["status"] == "missing"
    assert culinary["status_he"] == "חסר"
    assert "0" != culinary["amount"]
    removed = client.put("/api/financial/budget/lines", headers=owner["headers"], json={
        "updates": [{"id": "piz_ads", "remove": True}],
    })
    assert removed.status_code == 200, removed.text
    again = client.get("/api/financial/budget/lines", headers=owner["headers"], params={
        "year": 2026, "from_month": 11, "to_month": 11,
    })
    assert all(row["id"] != "piz_ads" for row in again.json()["data"]["lines"])


def test_budget_screen_lists_each_driver_and_not_the_rollup():
    from cfo.services.dashboards.budget import with_driver_rows
    section = {
        "has_budget": True,
        "months": [{
            "month": MONTH,
            "categories": [
                {"kind": "revenue", "category": "revenue", "category_he": "הכנסות", "budget": 283200.0,
                 "actual": None, "variance": None, "variance_pct": None},
                {"kind": "cost", "category": "other", "category_he": "אחר", "budget": 226000.0,
                 "actual": None, "variance": None, "variance_pct": None},
            ],
            "totals": {
                "revenue": {"budget": 283200.0, "actual": None},
                "costs": {"budget": 226000.0, "actual": None},
            },
        }],
    }
    expanded = with_driver_rows(section, _plan())
    rows = expanded["months"][0]["categories"]
    labels = [row["category_he"] for row in rows]
    assert "הכנסות משלוחים" in labels
    assert "הכנסות פיצה" in labels
    assert "הכנסות" not in labels
    assert "נהגים" in labels and "פוד קוסט" in labels and "פרסום" in labels
    culinary = next(row for row in rows if row["category"] == "cul_all")
    assert culinary["budget"] is None
    assert culinary["line_status"] == "missing"
    assert expanded["months"][0]["totals"]["revenue"]["budget"] == 283200.0
    assert expanded["months"][0]["totals"]["costs"]["budget"] == 226000.0
    assert all(row.get("budget") != 10_000_000 for row in rows)


def test_driver_csv_imports_the_same_month():
    text = """division,line_key,label_he,kind,driver_formula,qty,unit_price,amount,status,source,as_of,rezef_account_hint
משלוחים,del_revenue,הכנסות משלוחים,income,600×24×10.5,14400,10.5,151200,assumption,עמית,2026-10-29,80100
קולינריה,cul_all,חטיבת קולינריה,income/expense,לא נמסר,,,,missing,לא נמסר,2026-10-29,
"""
    updates = driver_csv_updates(text, MONTH)
    plan = apply_updates({"budgetLines": []}, updates)
    revenue = next(line for line in plan["budgetLines"] if line["id"] == "del_revenue")
    assert revenue["months"][MONTH]["quantity"] == 14400
    assert revenue["months"][MONTH]["rate"] == 10.5
    culinary = next(line for line in plan["budgetLines"] if line["id"] == "cul_all")
    assert culinary["months"] == {}
    assert culinary["covers"] == "income_and_expense"
