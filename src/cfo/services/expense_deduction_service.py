"""Real Israeli expense-deduction calculators.

Each function takes only real, user-supplied inputs and computes the
legally-correct deductible percentage/amount. None of them fabricate a
default when a required input is missing -- they raise ValueError instead,
matching Expense.deduction_percent's existing honest-null design (see
models.py). Percentages are returned as Decimal in [0, 100].
"""
from decimal import Decimal
from typing import Optional


def _to_decimal(value) -> Decimal:
    return Decimal(str(value))


def calculate_vehicle_deduction_percent(
    running_costs_annual: Optional[float],
    use_value_monthly: Optional[float],
    odometer_start: Optional[float],
    odometer_end: Optional[float],
) -> Decimal:
    """Higher-of rule (תקנות מס הכנסה (ניכוי הוצאות רכב) התשנ"ה-1995):
    deductible = MAX(running_costs_annual - use_value_monthly*12, 0.45 * running_costs_annual).
    use_value_monthly (שווי שימוש) is the Tax Authority's published fixed monthly
    figure for the vehicle -- never computed here. Odometer readings are a hard
    statutory precondition; odometer_end must exceed odometer_start.
    """
    if running_costs_annual is None or use_value_monthly is None:
        raise ValueError("running_costs_annual and use_value_monthly are required — refusing to fabricate a default")
    if odometer_start is None or odometer_end is None:
        raise ValueError("odometer_start/odometer_end are a statutory precondition and must be recorded")

    running = _to_decimal(running_costs_annual)
    use_value_annual = _to_decimal(use_value_monthly) * 12
    odo_start = _to_decimal(odometer_start)
    odo_end = _to_decimal(odometer_end)

    if odo_end <= odo_start:
        raise ValueError("odometer readings show no recorded distance — deduction cannot be computed")
    if running < 0:
        raise ValueError("running_costs_annual cannot be negative")
    if running == 0:
        return Decimal("0")

    option_a = running - use_value_annual
    option_b = running * Decimal("0.45")
    deductible = max(option_a, option_b)
    deductible = max(Decimal("0"), min(deductible, running))
    return (deductible / running * 100).quantize(Decimal("1"))


def calculate_mobile_phone_deduction(monthly_expense: Optional[float]) -> tuple[Decimal, Decimal]:
    """תקנות מס הכנסה (ניכוי הוצאות מסוימות) תשל"ב-1972: NOT a flat 80%.
    disallowed = min(115 ILS, 50% of the bill); deductible = bill - disallowed.
    Returns (deductible_amount, deduction_percent).
    """
    if monthly_expense is None:
        raise ValueError("monthly_expense is required")
    monthly = _to_decimal(monthly_expense)
    if monthly < 0:
        raise ValueError("monthly_expense cannot be negative")
    if monthly == 0:
        return Decimal("0"), Decimal("0")

    disallowed = min(Decimal("115"), monthly * Decimal("0.5"))
    deductible = monthly - disallowed
    pct = (deductible / monthly * 100).quantize(Decimal("0.01")).normalize()
    return deductible.quantize(Decimal("0.01")).normalize(), pct


ANNUAL_LANDLINE_CEILING = Decimal("26600")
ANNUAL_LANDLINE_FLOOR = Decimal("2700")


def calculate_landline_deduction(annual_expense: Optional[float]) -> tuple[Decimal, Decimal]:
    """Home landline: deductible = LOWER of (80% of the annual expense) OR
    (the amount exceeding 2,700 ILS/year), capped at a 26,600 ILS annual ceiling.
    Returns (deductible_amount, deduction_percent).
    """
    if annual_expense is None:
        raise ValueError("annual_expense is required")
    annual = _to_decimal(annual_expense)
    if annual < 0:
        raise ValueError("annual_expense cannot be negative")
    if annual == 0:
        return Decimal("0"), Decimal("0")

    option_a = annual * Decimal("0.8")
    option_b = max(annual - ANNUAL_LANDLINE_FLOOR, Decimal("0"))
    deductible = min(option_a, option_b, ANNUAL_LANDLINE_CEILING)
    pct = (deductible / annual * 100).quantize(Decimal("0.01")).normalize()
    return deductible.quantize(Decimal("0.01")).normalize(), pct


def calculate_home_office_percent(office_sqm: Optional[float], total_home_sqm: Optional[float]) -> Decimal:
    """Proportional home-office deduction: (office_sqm / total_home_sqm) * 100."""
    if office_sqm is None or total_home_sqm is None:
        raise ValueError("office_sqm and total_home_sqm are required")
    office = _to_decimal(office_sqm)
    total = _to_decimal(total_home_sqm)
    if total <= 0:
        raise ValueError("total_home_sqm must be positive")
    if office < 0:
        raise ValueError("office_sqm cannot be negative")
    if office > total:
        raise ValueError("office_sqm cannot exceed total_home_sqm")
    return (office / total * 100).quantize(Decimal("0.01")).normalize()


def calculate_internet_deduction_percent(
    office_sqm: Optional[float] = None,
    total_home_sqm: Optional[float] = None,
    business_use_fraction: Optional[float] = None,
) -> Decimal:
    """Internet has no fixed percentage in the Tax Ordinance -- it follows the
    same business-use proportion as the home office, or an explicitly supplied
    business-use fraction (0-1) if the connection isn't tied to a home office.
    """
    if business_use_fraction is not None:
        fraction = _to_decimal(business_use_fraction)
        if fraction < 0 or fraction > 1:
            raise ValueError("business_use_fraction must be between 0 and 1")
        return (fraction * 100).quantize(Decimal("0.01")).normalize()
    if office_sqm is not None and total_home_sqm is not None:
        return calculate_home_office_percent(office_sqm, total_home_sqm)
    raise ValueError("supply either business_use_fraction or office_sqm+total_home_sqm")
