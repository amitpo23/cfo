"""TDD for real Israeli expense-deduction calculators (P1 roadmap item:
"מנגנוני ניכוי הוצאה"). Every calculator takes only real, user-supplied
inputs and raises/refuses rather than fabricating a fallback when a
required input is missing — matching Expense.deduction_percent's existing
honest-null design (see models.py's docstring on that field).
"""
from decimal import Decimal

import pytest

from cfo.services.expense_deduction_service import (
    calculate_vehicle_deduction_percent,
    calculate_mobile_phone_deduction,
    calculate_landline_deduction,
    calculate_home_office_percent,
    calculate_internet_deduction_percent,
)


# ==================== Vehicle (higher-of rule) ====================

def test_vehicle_deduction_uses_higher_of_two_options():
    """running_costs_annual=10,000, use_value_monthly=250 (=3,000/year):
    option (a) = 10,000 - 3,000 = 7,000 -> 70%
    option (b) = 45% * 10,000 = 4,500 -> 45%
    higher-of = 70%.
    """
    pct = calculate_vehicle_deduction_percent(
        running_costs_annual=10000,
        use_value_monthly=250,
        odometer_start=10000,
        odometer_end=25000,
    )
    assert pct == Decimal("70")


def test_vehicle_deduction_falls_back_to_45_percent_floor():
    """When use-value is large relative to running costs, 45% wins."""
    pct = calculate_vehicle_deduction_percent(
        running_costs_annual=10000,
        use_value_monthly=700,  # 8,400/year -> option (a) = 1,600 -> 16%
        odometer_start=0,
        odometer_end=5000,
    )
    assert pct == Decimal("45")


@pytest.mark.parametrize("missing_field", ["running_costs_annual", "use_value_monthly", "odometer_start", "odometer_end"])
def test_vehicle_deduction_refuses_when_input_missing(missing_field):
    """No fabricated fallback: a missing required input must raise, not guess."""
    kwargs = dict(running_costs_annual=10000, use_value_monthly=250, odometer_start=10000, odometer_end=25000)
    kwargs[missing_field] = None
    with pytest.raises(ValueError):
        calculate_vehicle_deduction_percent(**kwargs)


def test_vehicle_deduction_refuses_when_odometer_readings_not_recorded():
    """Statutory precondition: odometer_end must exceed odometer_start."""
    with pytest.raises(ValueError):
        calculate_vehicle_deduction_percent(
            running_costs_annual=10000, use_value_monthly=250,
            odometer_start=20000, odometer_end=20000,
        )


# ==================== Mobile phone ====================

def test_mobile_phone_deduction_applies_the_50_percent_floor_not_flat_80():
    """monthly bill 180: disallowed = min(115, 90) = 90 -> deductible = 90 (50%)."""
    deductible, pct = calculate_mobile_phone_deduction(monthly_expense=180)
    assert deductible == Decimal("90")
    assert pct == Decimal("50")


def test_mobile_phone_deduction_uses_115_cap_for_large_bills():
    """monthly bill 1000: disallowed = min(115, 500) = 115 -> deductible = 885 (88.5%)."""
    deductible, pct = calculate_mobile_phone_deduction(monthly_expense=1000)
    assert deductible == Decimal("885")
    assert pct == Decimal("88.5")


def test_mobile_phone_deduction_refuses_when_missing():
    with pytest.raises(ValueError):
        calculate_mobile_phone_deduction(monthly_expense=None)


# ==================== Landline ====================

def test_landline_deduction_lower_of_80pct_or_amount_over_2700():
    """annual 10,000: option_a = 8,000; option_b = 10,000-2,700 = 7,300 -> lower = 7,300 (73%)."""
    deductible, pct = calculate_landline_deduction(annual_expense=10000)
    assert deductible == Decimal("7300")
    assert pct == Decimal("73")


def test_landline_deduction_capped_at_annual_ceiling():
    """A huge annual bill still can't exceed the 26,600 ceiling."""
    deductible, _pct = calculate_landline_deduction(annual_expense=1000000)
    assert deductible == Decimal("26600")


def test_landline_deduction_refuses_when_missing():
    with pytest.raises(ValueError):
        calculate_landline_deduction(annual_expense=None)


# ==================== Home office ====================

def test_home_office_percent_is_proportional_area():
    """12 sqm office / 80 sqm home = 15%."""
    pct = calculate_home_office_percent(office_sqm=12, total_home_sqm=80)
    assert pct == Decimal("15")


def test_home_office_percent_refuses_when_missing():
    with pytest.raises(ValueError):
        calculate_home_office_percent(office_sqm=None, total_home_sqm=80)


def test_home_office_percent_refuses_when_office_exceeds_home():
    with pytest.raises(ValueError):
        calculate_home_office_percent(office_sqm=100, total_home_sqm=80)


# ==================== Internet ====================

def test_internet_deduction_follows_home_office_ratio_by_default():
    pct = calculate_internet_deduction_percent(office_sqm=12, total_home_sqm=80)
    assert pct == Decimal("15")


def test_internet_deduction_accepts_explicit_business_use_fraction():
    pct = calculate_internet_deduction_percent(business_use_fraction=0.3)
    assert pct == Decimal("30")


def test_internet_deduction_refuses_when_nothing_supplied():
    with pytest.raises(ValueError):
        calculate_internet_deduction_percent()
