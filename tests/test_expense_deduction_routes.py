"""Integration tests for the expense-deduction profile routes: org-scoped
CRUD + compute, org isolation, and applying a computed percent to a real
Expense via the existing deduction_percent field."""
from datetime import date

import pytest


@pytest.fixture
def acc(client, fresh_org):
    return fresh_org()


@pytest.fixture
def other_acc(client, fresh_org):
    return fresh_org()


def _create_expense(client, acc, amount=1000):
    r = client.post("/api/expenses", json={
        "supplier_name": "ספק בדיקה",
        "amount": amount,
        "vat_amount": 0,
        "expense_date": date.today().isoformat(),
        "category": "materials",
        "invoice_number": "DED-1",
    }, headers=acc["headers"])
    assert r.status_code == 200, r.text
    return r.json()["data"]["id"]


# ==================== Vehicle profile ====================

def test_vehicle_profile_upsert_and_compute(client, acc):
    r = client.post("/api/expenses/deduction/vehicle-profile", json={
        "tax_year": 2026,
        "vehicle_label": "12-345-67",
        "running_costs_annual": 10000,
        "use_value_monthly": 250,
        "odometer_start": 10000,
        "odometer_end": 25000,
    }, headers=acc["headers"])
    assert r.status_code == 200, r.text

    r2 = client.post(
        "/api/expenses/deduction/vehicle-profile/2026/compute?vehicle_label=12-345-67",
        json={}, headers=acc["headers"],
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["data"]["deduction_percent"] == 70.0


def test_vehicle_profile_compute_applies_to_expense(client, acc):
    client.post("/api/expenses/deduction/vehicle-profile", json={
        "tax_year": 2026, "vehicle_label": None,
        "running_costs_annual": 10000, "use_value_monthly": 250,
        "odometer_start": 0, "odometer_end": 12000,
    }, headers=acc["headers"])
    eid = _create_expense(client, acc)

    r = client.post(
        "/api/expenses/deduction/vehicle-profile/2026/compute",
        json={"expense_id": eid}, headers=acc["headers"],
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["expense"]["deduction_percent"] == 70.0

    listing = client.get("/api/expenses", headers=acc["headers"]).json()["data"]
    updated = next(e for e in listing if e["id"] == eid)
    assert updated["deduction_percent"] == 70.0


def test_vehicle_profile_compute_400_when_profile_incomplete(client, acc):
    client.post("/api/expenses/deduction/vehicle-profile", json={
        "tax_year": 2026, "vehicle_label": "no-odometer",
        "running_costs_annual": 10000, "use_value_monthly": 250,
        # odometer readings omitted entirely
    }, headers=acc["headers"])
    r = client.post(
        "/api/expenses/deduction/vehicle-profile/2026/compute?vehicle_label=no-odometer",
        json={}, headers=acc["headers"],
    )
    assert r.status_code == 400


def test_vehicle_profile_compute_404_when_no_profile_at_all(client, acc):
    r = client.post(
        "/api/expenses/deduction/vehicle-profile/2099/compute",
        json={}, headers=acc["headers"],
    )
    assert r.status_code == 400  # no profile -> ValueError -> 400, not a fabricated result


def test_vehicle_profile_is_org_isolated(client, acc, other_acc):
    client.post("/api/expenses/deduction/vehicle-profile", json={
        "tax_year": 2026, "vehicle_label": None,
        "running_costs_annual": 10000, "use_value_monthly": 250,
        "odometer_start": 0, "odometer_end": 12000,
    }, headers=acc["headers"])

    r = client.get("/api/expenses/deduction/vehicle-profile?tax_year=2026", headers=other_acc["headers"])
    assert r.status_code == 404


def test_vehicle_profile_delete(client, acc):
    client.post("/api/expenses/deduction/vehicle-profile", json={
        "tax_year": 2026, "vehicle_label": None,
        "running_costs_annual": 10000, "use_value_monthly": 250,
        "odometer_start": 0, "odometer_end": 12000,
    }, headers=acc["headers"])

    r = client.delete("/api/expenses/deduction/vehicle-profile?tax_year=2026", headers=acc["headers"])
    assert r.status_code == 200, r.text

    r2 = client.get("/api/expenses/deduction/vehicle-profile?tax_year=2026", headers=acc["headers"])
    assert r2.status_code == 404


def test_vehicle_profile_delete_404_when_missing(client, acc):
    r = client.delete("/api/expenses/deduction/vehicle-profile?tax_year=2099", headers=acc["headers"])
    assert r.status_code == 404


def test_vehicle_profile_delete_is_org_isolated(client, acc, other_acc):
    client.post("/api/expenses/deduction/vehicle-profile", json={
        "tax_year": 2026, "vehicle_label": None,
        "running_costs_annual": 10000, "use_value_monthly": 250,
        "odometer_start": 0, "odometer_end": 12000,
    }, headers=acc["headers"])

    r = client.delete("/api/expenses/deduction/vehicle-profile?tax_year=2026", headers=other_acc["headers"])
    assert r.status_code == 404

    r2 = client.get("/api/expenses/deduction/vehicle-profile?tax_year=2026", headers=acc["headers"])
    assert r2.status_code == 200


# ==================== Home office profile ====================

def test_home_office_profile_upsert_and_compute(client, acc):
    r = client.post("/api/expenses/deduction/home-office-profile", json={
        "office_sqm": 12, "total_home_sqm": 80,
    }, headers=acc["headers"])
    assert r.status_code == 200, r.text

    r2 = client.post("/api/expenses/deduction/home-office-profile/compute", json={}, headers=acc["headers"])
    assert r2.status_code == 200, r2.text
    assert r2.json()["data"]["deduction_percent"] == 15.0


def test_home_office_profile_compute_400_when_missing(client, acc):
    r = client.post("/api/expenses/deduction/home-office-profile/compute", json={}, headers=acc["headers"])
    assert r.status_code == 400


def test_home_office_profile_delete(client, acc):
    client.post("/api/expenses/deduction/home-office-profile", json={
        "office_sqm": 12, "total_home_sqm": 80,
    }, headers=acc["headers"])

    r = client.delete("/api/expenses/deduction/home-office-profile", headers=acc["headers"])
    assert r.status_code == 200, r.text

    r2 = client.get("/api/expenses/deduction/home-office-profile", headers=acc["headers"])
    assert r2.status_code == 404


def test_home_office_profile_delete_404_when_missing(client, acc):
    r = client.delete("/api/expenses/deduction/home-office-profile", headers=acc["headers"])
    assert r.status_code == 404


def test_home_office_profile_delete_is_org_isolated(client, acc, other_acc):
    client.post("/api/expenses/deduction/home-office-profile", json={
        "office_sqm": 12, "total_home_sqm": 80,
    }, headers=acc["headers"])

    r = client.delete("/api/expenses/deduction/home-office-profile", headers=other_acc["headers"])
    assert r.status_code == 404

    r2 = client.get("/api/expenses/deduction/home-office-profile", headers=acc["headers"])
    assert r2.status_code == 200


def test_internet_deduction_defaults_to_home_office_ratio(client, acc):
    client.post("/api/expenses/deduction/home-office-profile", json={
        "office_sqm": 12, "total_home_sqm": 80,
    }, headers=acc["headers"])
    r = client.post("/api/expenses/deduction/internet/compute", headers=acc["headers"])
    assert r.status_code == 200, r.text
    assert r.json()["data"]["deduction_percent"] == 15.0


def test_internet_deduction_accepts_explicit_fraction(client, acc):
    r = client.post(
        "/api/expenses/deduction/internet/compute?business_use_fraction=0.3",
        headers=acc["headers"],
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["deduction_percent"] == 30.0


# ==================== Mobile phone / landline (stateless) ====================

def test_mobile_phone_compute_route(client, acc):
    r = client.post(
        "/api/expenses/deduction/mobile-phone/compute?monthly_expense=180",
        headers=acc["headers"],
    )
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["deductible_amount"] == 90.0
    assert data["deduction_percent"] == 50.0


def test_landline_compute_route(client, acc):
    r = client.post(
        "/api/expenses/deduction/landline/compute?annual_expense=10000",
        headers=acc["headers"],
    )
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["deductible_amount"] == 7300.0
    assert data["deduction_percent"] == 73.0


def test_deduction_routes_require_auth(client):
    r = client.post("/api/expenses/deduction/mobile-phone/compute?monthly_expense=180")
    assert r.status_code == 403
