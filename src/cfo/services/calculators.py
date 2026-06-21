"""
Deterministic Israeli calculators — fields in, a number out. No language model.

Each calculator is a pure function returning {result, unit, breakdown, note}. The
constants below are 2026 statutory values; those sourced from the installed Skills IL
reference files are cited inline. Values that update annually carry a `verify` note,
and complex/edge cases route to the matching full skill (as the calculator's `note`).

Rates source: .claude/skills/israeli-payroll-calculator/references/* (tax brackets,
credit points, NI rates), israeli-bituach-leumi/references/benefit-programs.md,
israeli-tax-returns/references/tax-brackets-credits.md.
"""
from __future__ import annotations

from typing import Any, Callable

# ====================================================================== #
# 2026 statutory constants
# ====================================================================== #
# Monthly income-tax brackets: (upper_bound, marginal_rate). Source: payroll skill.
TAX_BRACKETS_MONTHLY = [
    (7010, 0.10), (10060, 0.14), (19000, 0.20), (25100, 0.31),
    (46690, 0.35), (60130, 0.47), (float("inf"), 0.50),
]
CREDIT_POINT_MONTHLY = 2904 / 12          # 242 NIS/month (2,904/yr)
PENSION_CREDIT_CEILING = 9700             # insured-salary ceiling for §45a credit
PENSION_CREDIT_RATE = 0.35
PENSION_QUALIFYING_RATE = 0.07

# National Insurance + health (employee side). Source: NI rates ref.
NI_REDUCED_THRESHOLD = 7703
NI_CEILING = 51910
NI_EMPLOYEE_REDUCED = 0.0427              # 1.04% NI + 3.23% health
NI_EMPLOYEE_FULL = 0.1217                 # 7.00% NI + 5.17% health
NI_SELF_REDUCED = 0.077                   # 4.47% + 3.23%
NI_SELF_FULL = 0.180                      # 12.83% + 5.17%
# Employer side (no health tax for employers). Source: NI rates ref.
NI_EMPLOYER_REDUCED = 0.0451              # 4.51% (up to reduced threshold)
NI_EMPLOYER_FULL = 0.0760                 # 7.60% (above threshold to ceiling)
PENSION_EMPLOYER_RATE = 0.065             # tagmulim (employer pension)
SEVERANCE_EMPLOYER_RATE = 0.06            # pitzuim (employer severance accrual)

SURTAX_THRESHOLD_MONTHLY = 60130          # 721,560/yr
SURTAX_RATE_ACTIVE = 0.03
SURTAX_RATE_PASSIVE = 0.05

# Capital gains. Source: tax-returns ref.
CGT_INDIVIDUAL = 0.25
CGT_SUBSTANTIAL = 0.30

# Bituach Leumi benefit anchors (2026). Source: benefit-programs.md.
UNEMPLOYMENT_DAILY_CAP_1 = 550.76         # days 1-125
UNEMPLOYMENT_DAILY_CAP_2 = 367.17         # days 126+
RESERVE_DAILY_CAP = 1730.33
RESERVE_DAILY_MIN = 328.76
CHILD_ALLOWANCE = {"first": 173, "middle": 219, "fifth_plus": 173}  # by birth order

# Labor law (statutory formulas; daily rates are inputs so they stay current).
RECUPERATION_DAYS = [  # (min_year_inclusive, days) — private sector schedule
    (1, 5), (2, 6), (4, 7), (11, 8), (16, 9), (20, 10),
]
RECUPERATION_DEFAULT_DAILY = 471          # private sector ~2026; verify annually
# Annual vacation entitlement in *calendar* days by seniority year (Hofesh Shnati law).
VACATION_CALENDAR_DAYS = {1: 16, 2: 16, 3: 16, 4: 16, 5: 18, 6: 21, 7: 23,
                          8: 24, 9: 25, 10: 26, 11: 27, 12: 28}

# Reserve-duty tax credit points (from 2026). Source: tax-returns ref.
RESERVE_CREDIT_POINTS = [(60, 1.0), (45, 0.75), (20, 0.5)]  # (min_days, points)

# Purchase tax (Mas Rechisha) — single residence, 2025/2026 brackets (verify Jan).
PURCHASE_TAX_SINGLE = [  # (upper_bound, rate)
    (1_978_745, 0.0), (2_347_040, 0.035), (6_055_070, 0.05),
    (20_183_565, 0.08), (float("inf"), 0.10),
]
PURCHASE_TAX_ADDITIONAL = [(6_055_070, 0.08), (float("inf"), 0.10)]

# Discharge deposit (Pikadon Shichrur) — total grant by service track (₪, verify).
DISCHARGE_DEPOSIT_TOTAL = {"combat": 29_820, "combat_support": 22_365, "non_combat": 17_892}
DISCHARGE_SERVICE_MONTHS = 32  # reference full-service length for pro-rata


# ====================================================================== #
# helpers
# ====================================================================== #
def _progressive(amount: float, brackets: list[tuple[float, float]]) -> float:
    tax, lower = 0.0, 0.0
    for upper, rate in brackets:
        if amount <= lower:
            break
        taxed = min(amount, upper) - lower
        tax += taxed * rate
        lower = upper
    return tax


def _ni_health(gross: float, *, self_employed: bool = False) -> float:
    reduced = NI_SELF_REDUCED if self_employed else NI_EMPLOYEE_REDUCED
    full = NI_SELF_FULL if self_employed else NI_EMPLOYEE_FULL
    capped = min(gross, NI_CEILING)
    if capped <= NI_REDUCED_THRESHOLD:
        return capped * reduced
    return NI_REDUCED_THRESHOLD * reduced + (capped - NI_REDUCED_THRESHOLD) * full


def _ni_employer(gross: float) -> float:
    capped = min(gross, NI_CEILING)
    if capped <= NI_REDUCED_THRESHOLD:
        return capped * NI_EMPLOYER_REDUCED
    return (NI_REDUCED_THRESHOLD * NI_EMPLOYER_REDUCED
            + (capped - NI_REDUCED_THRESHOLD) * NI_EMPLOYER_FULL)


def payslip_components(gross: float, *, credit_points: float = 2.25, pension_pct: float = 6.0) -> dict:
    """Full payslip math (single source of truth) — employee deductions, net, and
    employer costs. Reused by net_salary, the payroll module and Form 102."""
    gross_tax = _progressive(gross, TAX_BRACKETS_MONTHLY)
    pension_employee = gross * pension_pct / 100
    eligible = min(pension_employee, PENSION_QUALIFYING_RATE * min(gross, PENSION_CREDIT_CEILING))
    pension_credit = PENSION_CREDIT_RATE * eligible
    points_credit = credit_points * CREDIT_POINT_MONTHLY
    income_tax = max(0.0, gross_tax - points_credit - pension_credit)
    ni_health = _ni_health(gross)
    # Split NI/health into the NI and health portions for reporting (Form 102).
    capped = min(gross, NI_CEILING)
    if capped <= NI_REDUCED_THRESHOLD:
        health = capped * 0.0323
    else:
        health = NI_REDUCED_THRESHOLD * 0.0323 + (capped - NI_REDUCED_THRESHOLD) * 0.0517
    ni_employee = ni_health - health
    net = gross - income_tax - ni_health - pension_employee

    employer_ni = _ni_employer(gross)
    employer_pension = gross * PENSION_EMPLOYER_RATE
    employer_severance = gross * SEVERANCE_EMPLOYER_RATE
    employer_cost = gross + employer_ni + employer_pension + employer_severance
    return {
        "gross": round(gross, 2),
        "income_tax": round(income_tax, 2),
        "ni_employee": round(ni_employee, 2),
        "health_tax": round(health, 2),
        "pension_employee": round(pension_employee, 2),
        "net": round(net, 2),
        "employer_ni": round(employer_ni, 2),
        "employer_pension": round(employer_pension, 2),
        "employer_severance": round(employer_severance, 2),
        "employer_cost": round(employer_cost, 2),
    }


def _row(label: str, value: float, unit: str = "₪") -> dict:
    return {"label": label, "value": round(value, 2), "unit": unit}


def _result(result: float, unit: str, breakdown: list[dict], note: str = "") -> dict:
    return {"result": round(result, 2), "unit": unit, "breakdown": breakdown, "note": note}


# ====================================================================== #
# Calculators
# ====================================================================== #
def net_salary(*, gross: float, credit_points: float = 2.25, pension_pct: float = 6.0) -> dict:
    gross_tax = _progressive(gross, TAX_BRACKETS_MONTHLY)
    pension_contrib = gross * pension_pct / 100
    eligible = min(pension_contrib, PENSION_QUALIFYING_RATE * min(gross, PENSION_CREDIT_CEILING))
    pension_credit = PENSION_CREDIT_RATE * eligible
    points_credit = credit_points * CREDIT_POINT_MONTHLY
    income_tax = max(0.0, gross_tax - points_credit - pension_credit)
    ni = _ni_health(gross)
    net = gross - income_tax - ni - pension_contrib
    return _result(net, "₪", [
        _row("ברוטו", gross),
        _row("מס הכנסה", -income_tax),
        _row("ביטוח לאומי + בריאות", -ni),
        _row("הפרשת עובד לפנסיה", -pension_contrib),
        _row("זיכוי נקודות זיכוי", points_credit),
        _row("זיכוי פנסיה (45א)", pension_credit),
    ], note="נטו לפי מדרגות 2026. מקרים מיוחדים (שווי רכב, זיכויים נוספים) → israeli-payroll-calculator.")


def severance(*, last_monthly_salary: float, years: float) -> dict:
    amount = last_monthly_salary * years
    return _result(amount, "₪", [
        _row("שכר חודשי אחרון", last_monthly_salary),
        _row("שנות ותק", years, "שנים"),
        _row("פיצויים (חודש לשנה)", amount),
    ], note="מינימום חוקי: חודש שכר לכל שנה (כולל יחסי לחלקי שנה). מקרים גבוליים → israeli-payroll-calculator.")


def unemployment(*, avg_monthly_gross: float, days: int = 100) -> dict:
    daily_wage = avg_monthly_gross / 25
    cap = UNEMPLOYMENT_DAILY_CAP_1 if days <= 125 else UNEMPLOYMENT_DAILY_CAP_2
    # Regressive replacement (approximation): ~upper bound is the official cap.
    daily_benefit = min(daily_wage * 0.7, cap)
    total = daily_benefit * days
    return _result(total, "₪", [
        _row("שכר יומי ממוצע", daily_wage),
        _row("תקרה יומית", cap),
        _row("תגמול יומי (אומדן)", daily_benefit),
        _row("מספר ימים", days, "ימים"),
    ], note="אומדן לפי תקרות 2026. החישוב הרגרסיבי המדויק → israeli-bituach-leumi.")


def mortgage_payment(*, principal: float, annual_rate_pct: float, years: int) -> dict:
    r = annual_rate_pct / 100 / 12
    n = years * 12
    if r == 0:
        pmt = principal / n
    else:
        pmt = principal * r / (1 - (1 + r) ** (-n))
    total = pmt * n
    return _result(pmt, "₪/חודש", [
        _row("קרן ההלוואה", principal),
        _row("ריבית שנתית", annual_rate_pct, "%"),
        _row("תקופה", years, "שנים"),
        _row("סך החזר כולל", total),
        _row("סך ריבית", total - principal),
    ], note="לוח שפיצר. לתמהיל רב-מסלולי חשב כל מסלול בנפרד וסכם → israeli-budget-planner.")


def bituach_leumi(*, monthly_gross: float, self_employed: bool = False) -> dict:
    amount = _ni_health(monthly_gross, self_employed=self_employed)
    return _result(amount, "₪/חודש", [
        _row("ברוטו חודשי", monthly_gross),
        _row("מדרגה מופחתת עד", NI_REDUCED_THRESHOLD),
        _row("תקרה", NI_CEILING),
        _row("ניכוי ב\"ל + בריאות", amount),
    ], note="עובד שכיר 2026. עצמאי/פטורים → israeli-bituach-leumi.")


def recuperation(*, years_seniority: float, daily_rate: float = RECUPERATION_DEFAULT_DAILY) -> dict:
    days = 5
    for min_year, d in RECUPERATION_DAYS:
        if years_seniority >= min_year:
            days = d
    amount = days * daily_rate
    return _result(amount, "₪", [
        _row("ותק", years_seniority, "שנים"),
        _row("ימי הבראה", days, "ימים"),
        _row("תעריף יומי", daily_rate),
        _row("דמי הבראה", amount),
    ], note="ימים לפי ותק; תעריף יומי מתעדכן שנתית (ברירת מחדל מגזר פרטי). ודא תעריף עדכני.")


def options_102(*, gain: float, substantial_shareholder: bool = False) -> dict:
    rate = CGT_SUBSTANTIAL if substantial_shareholder else CGT_INDIVIDUAL
    tax = max(0.0, gain) * rate
    return _result(tax, "₪", [
        _row("רווח (מימוש פחות הקצאה)", gain),
        _row("שיעור מס", rate * 100, "%"),
        _row("מס לתשלום", tax),
    ], note="מסלול הוני 102 (נאמן, מעל שנתיים) = 25%. רכיב פירותי/מסלול אחר → israeli-tax-returns.")


def notice_period(*, months_seniority: float, monthly_salary: float = 0.0) -> dict:
    m = months_seniority
    if m >= 12:
        days = 30
    elif m >= 6:
        days = 6 + (m - 6) * 2.5
    else:
        days = m  # 1 day per month in first 6 months
    days = round(days)
    pay = monthly_salary / 30 * days if monthly_salary else 0.0
    breakdown = [_row("ותק", months_seniority, "חודשים"), _row("ימי הודעה מוקדמת", days, "ימים")]
    if monthly_salary:
        breakdown.append(_row("שווי בכסף", pay))
    return _result(days, "ימים", breakdown,
                   note="עובד חודשי. עובד שעתי/יומי לפי לוח שונה → israeli-payroll-calculator.")


def reserve_tax_credit(*, reserve_days: int) -> dict:
    points = 0.0
    for min_days, p in RESERVE_CREDIT_POINTS:
        if reserve_days >= min_days:
            points = p
            break
    annual_credit = points * CREDIT_POINT_MONTHLY * 12
    return _result(annual_credit, "₪/שנה", [
        _row("ימי מילואים", reserve_days, "ימים"),
        _row("נקודות זיכוי", points, "נק'"),
        _row("זיכוי שנתי", annual_credit),
    ], note="זיכוי מילואים מ-2026: 0.5 (20+), 0.75 (45+), 1.0 (60+ ימים).")


def purchase_tax(*, price: float, single_residence: bool = True) -> dict:
    brackets = PURCHASE_TAX_SINGLE if single_residence else PURCHASE_TAX_ADDITIONAL
    tax = _progressive(price, brackets)
    return _result(tax, "₪", [
        _row("מחיר הדירה", price),
        _row("סוג", 0 if single_residence else 1, "דירה יחידה/נוספת"),
        _row("מס רכישה", tax),
    ], note="מדרגות מתעדכנות ב-16 בינואר. דירה יחידה/נוספת/עולה → israeli-tax-returns.")


def vacation_days(*, years_seniority: int, work_days_per_week: int = 5) -> dict:
    cal = VACATION_CALENDAR_DAYS.get(min(int(years_seniority), 12), 28)
    # Net working days: 5-day week ≈ calendar × 5/6 (rounded down); 6-day week = calendar.
    working = cal if work_days_per_week >= 6 else int(cal * 5 / 6)
    return _result(working, "ימים", [
        _row("ותק", years_seniority, "שנים"),
        _row("ימי חופשה קלנדריים", cal, "ימים"),
        _row("ימי עבודה בפועל", working, "ימים"),
    ], note="לפי חוק חופשה שנתית. הסכמים קיבוציים עשויים להיטיב.")


def child_allowance(*, num_children: int) -> dict:
    total = 0.0
    for i in range(1, num_children + 1):
        if i == 1 or i >= 5:
            total += CHILD_ALLOWANCE["first"] if i == 1 else CHILD_ALLOWANCE["fifth_plus"]
        else:
            total += CHILD_ALLOWANCE["middle"]
    return _result(total, "₪/חודש", [
        _row("מספר ילדים", num_children, "ילדים"),
        _row("קצבה חודשית", total),
    ], note="ילד 1: ₪173; ילדים 2-4: ₪219; 5+: ₪173. בנוסף חיסכון לכל ילד ₪58.")


def reserve_pay(*, avg_monthly_gross: float, days: int) -> dict:
    daily = avg_monthly_gross / 30
    daily = max(RESERVE_DAILY_MIN, min(daily, RESERVE_DAILY_CAP))
    total = daily * days
    return _result(total, "₪", [
        _row("שכר חודשי ממוצע", avg_monthly_gross),
        _row("תגמול יומי", daily),
        _row("מינימום/תקרה יומית", RESERVE_DAILY_MIN, "₪ מינ'"),
        _row("ימי מילואים", days, "ימים"),
        _row("תגמול כולל", total),
    ], note="100% מהשכר היומי הממוצע (3 חודשים), בין מינימום ₪328.76 לתקרה ₪1,730.33.")


def discharge_deposit(*, service_months: int, track: str = "combat") -> dict:
    total = DISCHARGE_DEPOSIT_TOTAL.get(track, DISCHARGE_DEPOSIT_TOTAL["non_combat"])
    accrued = total * min(service_months, DISCHARGE_SERVICE_MONTHS) / DISCHARGE_SERVICE_MONTHS
    return _result(accrued, "₪", [
        _row("חודשי שירות", service_months, "חודשים"),
        _row("מסלול", 0, track),
        _row("פיקדון מלא במסלול", total),
        _row("נצבר (יחסי)", accrued),
    ], note="פיקדון לפי מסלול ומשך שירות; ערכים מתעדכנים. למשיכה/הכרה → israeli-bituach-leumi.")


def capital_gains(*, gain: float, substantial_shareholder: bool = False, apply_surtax: bool = False) -> dict:
    rate = CGT_SUBSTANTIAL if substantial_shareholder else CGT_INDIVIDUAL
    base_tax = max(0.0, gain) * rate
    surtax = max(0.0, gain) * SURTAX_RATE_PASSIVE if apply_surtax else 0.0
    total = base_tax + surtax
    rows = [
        _row("רווח הון", gain),
        _row("שיעור מס", rate * 100, "%"),
        _row("מס בסיס", base_tax),
    ]
    if apply_surtax:
        rows.append(_row("מס יסף (5%)", surtax))
    rows.append(_row("מס כולל", total))
    return _result(total, "₪", rows,
                   note="מניות/קריפטו: 25% (בעל מניות מהותי 30%). מס יסף 5% מעל ₪721,560 הכנסה שנתית.")


def bagrut_grade(*, subjects: list[dict]) -> dict:
    """subjects: [{grade, units, bonus?}]. bonus defaults by units (4→10, 5→20)."""
    total_w, total_u = 0.0, 0
    rows = []
    for s in subjects:
        grade = float(s.get("grade", 0))
        units = int(s.get("units", 0))
        bonus = s.get("bonus")
        if bonus is None:
            bonus = 20 if units >= 5 else (10 if units == 4 else 0)
        eff = min(grade + bonus, 100)
        total_w += eff * units
        total_u += units
        rows.append(_row(f"{units} יח' (ציון {grade}+{bonus})", eff, "משוקלל"))
    final = total_w / total_u if total_u else 0.0
    rows.append(_row("סך יחידות", total_u, "יח'"))
    rows.append(_row("ממוצע משוקלל", final))
    return _result(final, "ציון", rows,
                   note="ממוצע משוקלל לפי יחידות עם בונוס (4 יח'=+10, 5 יח'=+20). בונוסים משתנים בין מוסדות.")


# ====================================================================== #
# Registry — metadata for the UI (fields → number). Order matches the catalog.
# ====================================================================== #
def _num(name, label, default=None, unit="₪"):
    return {"name": name, "label": label, "type": "number", "default": default, "unit": unit}


def _bool(name, label, default=False):
    return {"name": name, "label": label, "type": "boolean", "default": default}


CALCULATORS: dict[str, dict[str, Any]] = {
    "net_salary": {
        "title": "נטו מהמשכורת", "category": "שכר", "fn": net_salary,
        "fields": [_num("gross", "ברוטו חודשי"), _num("credit_points", "נקודות זיכוי", 2.25, "נק'"),
                   _num("pension_pct", "אחוז הפרשה לפנסיה", 6.0, "%")],
    },
    "severance": {
        "title": "פיצויי פיטורים", "category": "שכר", "fn": severance,
        "fields": [_num("last_monthly_salary", "שכר חודשי אחרון"), _num("years", "שנות ותק", None, "שנים")],
    },
    "bituach_leumi": {
        "title": "ביטוח לאומי ובריאות", "category": "שכר", "fn": bituach_leumi,
        "fields": [_num("monthly_gross", "ברוטו חודשי"), _bool("self_employed", "עצמאי")],
    },
    "recuperation": {
        "title": "דמי הבראה", "category": "שכר", "fn": recuperation,
        "fields": [_num("years_seniority", "ותק", None, "שנים"),
                   _num("daily_rate", "תעריף יומי", RECUPERATION_DEFAULT_DAILY)],
    },
    "notice_period": {
        "title": "הודעה מוקדמת", "category": "שכר", "fn": notice_period,
        "fields": [_num("months_seniority", "ותק", None, "חודשים"),
                   _num("monthly_salary", "שכר חודשי (אופציונלי)", 0)],
    },
    "vacation_days": {
        "title": "ימי חופשה", "category": "שכר", "fn": vacation_days,
        "fields": [_num("years_seniority", "ותק", None, "שנים"),
                   _num("work_days_per_week", "ימי עבודה בשבוע", 5, "ימים")],
    },
    "mortgage_payment": {
        "title": "החזר חודשי על המשכנתא", "category": "נדל\"ן", "fn": mortgage_payment,
        "fields": [_num("principal", "סכום ההלוואה"), _num("annual_rate_pct", "ריבית שנתית", None, "%"),
                   _num("years", "תקופה", 25, "שנים")],
    },
    "purchase_tax": {
        "title": "מס רכישה על דירה", "category": "נדל\"ן", "fn": purchase_tax,
        "fields": [_num("price", "מחיר הדירה"), _bool("single_residence", "דירה יחידה", True)],
    },
    "capital_gains": {
        "title": "מס רווח הון (מניות/קריפטו)", "category": "מיסוי", "fn": capital_gains,
        "fields": [_num("gain", "רווח ההון"), _bool("substantial_shareholder", "בעל מניות מהותי"),
                   _bool("apply_surtax", "חייב במס יסף")],
    },
    "options_102": {
        "title": "מס על אופציות (102)", "category": "מיסוי", "fn": options_102,
        "fields": [_num("gain", "רווח (מימוש פחות הקצאה)"), _bool("substantial_shareholder", "בעל מניות מהותי")],
    },
    "unemployment": {
        "title": "דמי אבטלה", "category": "ביטוח לאומי", "fn": unemployment,
        "fields": [_num("avg_monthly_gross", "ברוטו חודשי ממוצע"), _num("days", "מספר ימים", 100, "ימים")],
    },
    "child_allowance": {
        "title": "קצבת ילדים", "category": "ביטוח לאומי", "fn": child_allowance,
        "fields": [_num("num_children", "מספר ילדים", None, "ילדים")],
    },
    "reserve_pay": {
        "title": "תגמול מילואים", "category": "מילואים", "fn": reserve_pay,
        "fields": [_num("avg_monthly_gross", "שכר חודשי ממוצע"), _num("days", "ימי מילואים", None, "ימים")],
    },
    "reserve_tax_credit": {
        "title": "זיכוי מס מילואים", "category": "מילואים", "fn": reserve_tax_credit,
        "fields": [_num("reserve_days", "ימי מילואים", None, "ימים")],
    },
    "discharge_deposit": {
        "title": "פיקדון שחרור", "category": "מילואים", "fn": discharge_deposit,
        "fields": [_num("service_months", "חודשי שירות", None, "חודשים"),
                   {"name": "track", "label": "מסלול", "type": "select",
                    "options": ["combat", "combat_support", "non_combat"], "default": "combat"}],
    },
    "bagrut_grade": {
        "title": "ציון סופי בבגרות", "category": "חינוך", "fn": bagrut_grade,
        "fields": [{"name": "subjects", "label": "מקצועות (ציון/יחידות)", "type": "subjects"}],
    },
}


def list_calculators() -> list[dict]:
    return [
        {"id": cid, "title": c["title"], "category": c["category"], "fields": c["fields"]}
        for cid, c in CALCULATORS.items()
    ]


def run(calculator_id: str, inputs: dict[str, Any]) -> dict:
    spec = CALCULATORS.get(calculator_id)
    if not spec:
        raise KeyError(f"Unknown calculator: {calculator_id}")
    fn: Callable = spec["fn"]
    allowed = {f["name"] for f in spec["fields"]}
    kwargs = {k: v for k, v in inputs.items() if k in allowed}
    return fn(**kwargs)
