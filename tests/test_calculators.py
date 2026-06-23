"""Tests for the deterministic Israeli calculators (known-value checks)."""
import pytest

from cfo.services import calculators as C


def test_registry_has_all_calculators():
    # 16 original + 3 expense-deduction calculators.
    assert len(C.CALCULATORS) == 19
    listed = C.list_calculators()
    assert len(listed) == 19
    assert all("fields" in c and "title" in c for c in listed)


def test_bituach_leumi_matches_skill_example():
    # Skill worked example: 12,000 gross -> ~852 NIS employee NI+health.
    r = C.bituach_leumi(monthly_gross=12000)
    assert abs(r["result"] - 851.86) < 0.5


def test_net_salary_components_consistent():
    r = C.net_salary(gross=12000)
    # Net must be gross minus the three deductions shown in the breakdown.
    assert 9000 < r["result"] < 10500
    labels = {b["label"]: b["value"] for b in r["breakdown"]}
    assert labels["ברוטו"] == 12000


def test_net_salary_below_tax_threshold_has_no_income_tax():
    r = C.net_salary(gross=6000, credit_points=2.25)
    tax_row = next(b for b in r["breakdown"] if b["label"] == "מס הכנסה")
    assert tax_row["value"] == 0  # credit points wipe out the 10% bracket


def test_severance_is_month_per_year():
    assert C.severance(last_monthly_salary=10000, years=5)["result"] == 50000
    assert C.severance(last_monthly_salary=8000, years=2.5)["result"] == 20000


def test_mortgage_zero_interest():
    r = C.mortgage_payment(principal=120000, annual_rate_pct=0, years=10)
    assert r["result"] == 1000.0  # 120000 / 120 months


def test_mortgage_standard_pmt():
    r = C.mortgage_payment(principal=1000000, annual_rate_pct=5, years=25)
    assert abs(r["result"] - 5845.90) < 1


def test_child_allowance_birth_order():
    assert C.child_allowance(num_children=1)["result"] == 173
    assert C.child_allowance(num_children=4)["result"] == 173 + 219 * 3  # 830
    assert C.child_allowance(num_children=5)["result"] == 173 + 219 * 3 + 173


def test_capital_gains_rates():
    assert C.capital_gains(gain=100000)["result"] == 25000
    assert C.capital_gains(gain=100000, substantial_shareholder=True)["result"] == 30000
    assert C.capital_gains(gain=100000, apply_surtax=True)["result"] == 30000  # 25% + 5%


def test_reserve_pay_clamped():
    assert C.reserve_pay(avg_monthly_gross=15000, days=10)["result"] == 5000  # 500/day
    # Below the daily minimum -> clamped up.
    low = C.reserve_pay(avg_monthly_gross=3000, days=10)["result"]
    assert low == round(C.RESERVE_DAILY_MIN * 10, 2)


def test_reserve_tax_credit_tiers():
    assert C.reserve_tax_credit(reserve_days=10)["result"] == 0          # below 20
    assert C.reserve_tax_credit(reserve_days=20)["breakdown"][1]["value"] == 0.5
    assert C.reserve_tax_credit(reserve_days=60)["breakdown"][1]["value"] == 1.0


def test_notice_period_schedule():
    assert C.notice_period(months_seniority=3)["result"] == 3      # 1 day/month first 6
    assert C.notice_period(months_seniority=12)["result"] == 30    # full month after a year


def test_vacation_days_seniority():
    assert C.vacation_days(years_seniority=1, work_days_per_week=6)["result"] == 16
    assert C.vacation_days(years_seniority=1, work_days_per_week=5)["result"] == 13  # 16*5/6


def test_purchase_tax_single_first_bracket_is_zero():
    assert C.purchase_tax(price=1500000, single_residence=True)["result"] == 0
    assert C.purchase_tax(price=2000000, single_residence=True)["result"] > 0


def test_bagrut_weighted_average_with_bonus():
    r = C.bagrut_grade(subjects=[{"grade": 90, "units": 5}, {"grade": 80, "units": 5}])
    # (110 capped 100 *5 + 100*5)/10 = (100+100)/2 = 100
    assert r["result"] == 100.0
    r2 = C.bagrut_grade(subjects=[{"grade": 70, "units": 3}, {"grade": 70, "units": 5}])
    # 3 units: 70 (no bonus); 5 units: 90 -> (70*3 + 90*5)/8 = (210+450)/8 = 82.5
    assert r2["result"] == 82.5


def test_run_dispatch_ignores_unknown_inputs():
    r = C.run("net_salary", {"gross": 12000, "garbage": 1})
    assert r["result"] > 0


def test_run_unknown_calculator_raises():
    with pytest.raises(KeyError):
        C.run("nope", {})


def test_deduction_calculators_registered_and_compute():
    from cfo.services import calculators
    ids = {c["id"] for c in calculators.list_calculators()}
    assert {"vehicle_deduction", "home_office_deduction", "phone_internet_deduction"} <= ids
    # business ratio applied: 30000 * 15000/20000 = 22500
    veh = calculators.run("vehicle_deduction", {"annual_cost": 30000, "business_km": 15000, "total_km": 20000})
    assert veh[-1]["value"] == 22500.0
    # home: 60000 * 15/100 = 9000
    home = calculators.run("home_office_deduction", {"annual_home_cost": 60000, "office_area_sqm": 15, "total_area_sqm": 100})
    assert home[-1]["value"] == 9000.0
    # phone: 6000 * 70% = 4200
    phone = calculators.run("phone_internet_deduction", {"annual_cost": 6000, "business_pct": 70})
    assert phone[-1]["value"] == 4200.0
