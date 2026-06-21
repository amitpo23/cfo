"""Annual tax-return DRAFTS — 1301 (יחיד) and 1214 (חברה).

These are official Israeli tax filings. This module produces a DRAFT ONLY, derived
from the shadow ledger's annual P&L, mapped to the main form fields. Every output
carries `draft: True` and a "לבדיקת רו"ח" disclaimer. It is decision support for the
accountant — NOT a filing-ready return. Tax math is an approximation (annual brackets
= monthly × 12; standard credit-point value) and edge cases (exemptions, multiple
income sources, carry-forward losses, adjustments) are out of scope by design.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from .ledger_service import trial_balance

DISCLAIMER = "טיוטה אוטומטית הנגזרת מהמסמכים — אינה דוח להגשה. חובה בדיקה והשלמה ע\"י רו\"ח."

CORPORATE_TAX_RATE = 0.23  # מס חברות 2025+
CREDIT_POINT_ANNUAL = 2904  # ערך נקודת זיכוי שנתי (2026; לאימות שנתי)

# מדרגות מס הכנסה שנתיות (חודשי × 12, 2024 base — לאימות מול הרשות).
INCOME_TAX_BRACKETS_ANNUAL = [
    (84120, 0.10),
    (120720, 0.14),
    (193800, 0.20),
    (269280, 0.31),
    (560280, 0.35),
    (float("inf"), 0.47),
]


def _annual_pl(db, organization_id: int, year: int) -> dict[str, float]:
    """Revenue / expenses / net profit for the year, from the derived ledger."""
    tb = trial_balance(db, organization_id, start=date(year, 1, 1), end=date(year, 12, 31))
    revenue = expenses = 0.0
    for a in tb["accounts"]:
        if a["type"] == "revenue":
            revenue += a["credit"] - a["debit"]
        elif a["type"] == "expense":
            expenses += a["debit"] - a["credit"]
    return {
        "revenue": round(revenue, 2),
        "expenses": round(expenses, 2),
        "net_profit": round(revenue - expenses, 2),
    }


def _progressive_annual_tax(income: float) -> float:
    if income <= 0:
        return 0.0
    tax = 0.0
    lower = 0.0
    for ceiling, rate in INCOME_TAX_BRACKETS_ANNUAL:
        if income <= lower:
            break
        taxable = min(income, ceiling) - lower
        tax += taxable * rate
        lower = ceiling
    return round(tax, 2)


def form_1301(db, organization_id: int, year: int, *, credit_points: float = 2.25) -> dict[str, Any]:
    """דוח שנתי ליחיד (1301) — טיוטה. Business income taxed by annual brackets."""
    pl = _annual_pl(db, organization_id, year)
    business_income = max(0.0, pl["net_profit"])
    gross_tax = _progressive_annual_tax(business_income)
    credit = round(credit_points * CREDIT_POINT_ANNUAL, 2)
    net_tax = max(0.0, round(gross_tax - credit, 2))
    return {
        "form": "1301",
        "title": "דוח שנתי ליחיד",
        "year": year,
        "fields": {
            "business_revenue": pl["revenue"],
            "business_expenses": pl["expenses"],
            "business_income": business_income,           # שדה הכנסה מעסק
            "gross_income_tax": gross_tax,
            "credit_points": credit_points,
            "credit_points_value": credit,
            "income_tax_due": net_tax,
        },
        "draft": True,
        "disclaimer": DISCLAIMER,
        "notes": [
            "הכנסה מעסק בלבד; הכנסות נוספות (שכר, שכ\"ד, רווחי הון) אינן כלולות.",
            "מדרגות ונקודות זיכוי לאימות מול רשות המסים לשנת הדיווח.",
        ],
    }


def form_1214(db, organization_id: int, year: int) -> dict[str, Any]:
    """דוח שנתי לחברה (1214) — טיוטה. Net profit taxed at the corporate rate."""
    pl = _annual_pl(db, organization_id, year)
    taxable = max(0.0, pl["net_profit"])
    tax = round(taxable * CORPORATE_TAX_RATE, 2)
    return {
        "form": "1214",
        "title": "דוח שנתי לחברה",
        "year": year,
        "fields": {
            "revenue": pl["revenue"],
            "expenses": pl["expenses"],
            "net_profit_before_tax": pl["net_profit"],
            "taxable_income": taxable,
            "corporate_tax_rate": CORPORATE_TAX_RATE,
            "corporate_tax_due": tax,
            "net_profit_after_tax": round(pl["net_profit"] - tax, 2),
        },
        "draft": True,
        "disclaimer": DISCLAIMER,
        "notes": [
            "ללא התאמות מס (הוצאות לא מוכרות, פחת מואץ, הפסדים מועברים).",
            "שיעור מס חברות לאימות לשנת הדיווח.",
        ],
    }
