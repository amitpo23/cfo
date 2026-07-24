"""TDD למנוע חוקי המס הישראלי (income tax + VAT-input) — israeli_tax_rules.py.

מקורות: docs/bookkeeper_kb/01-income-tax-recognition.md (מס הכנסה) +
02-vat-input-deductibility.md (מע"מ תשומות). כל שיוך קטגוריה->חוק כאן משקף
את שני המסמכים האלה; אם הם משתנים, TAX_RULES ו-VERIFICATION_NEEDED צריכים
להשתנות איתם.
"""
from decimal import Decimal
from pathlib import Path

import pytest

from cfo.services import expense_deduction_service
from cfo.services.expense_classifier import VALID_CATEGORIES
from cfo.services.israeli_tax_rules import (
    IncomeTaxTreatment,
    TAX_RULES,
    SUPPLIER_KINDS_NO_VAT,
    VERIFICATION_NEEDED,
    claimable_vat,
    render_bridge_table_he,
    resolve_vehicle_profile_args,
)

ALLOWED_FRACTIONS = {
    None,
    Decimal("0"),
    Decimal("1"),
    Decimal("1") / Decimal("4"),
    Decimal("2") / Decimal("3"),
}


# ---------------------------------------------------------------------- #
# TAX_RULES coverage
# ---------------------------------------------------------------------- #

def test_every_valid_category_has_a_rule():
    missing = VALID_CATEGORIES - set(TAX_RULES.keys())
    assert not missing, f"קטגוריות ללא חוק: {missing}"


@pytest.mark.parametrize("key,rule", list(TAX_RULES.items()))
def test_rule_fraction_is_one_of_allowed_values(key, rule):
    assert rule.input_vat_fraction in ALLOWED_FRACTIONS, (key, rule.input_vat_fraction)


@pytest.mark.parametrize("key,rule", list(TAX_RULES.items()))
def test_rule_formula_ref_resolves_on_expense_deduction_service(key, rule):
    if rule.formula_ref is not None:
        assert hasattr(expense_deduction_service, rule.formula_ref), (key, rule.formula_ref)


@pytest.mark.parametrize("key,rule", list(TAX_RULES.items()))
def test_rule_has_citation_and_category_key_matches(key, rule):
    assert rule.category == key
    assert rule.citation_he.strip()
    assert rule.name_he.strip()


def test_new_categories_present():
    for cat in (
        "vehicle", "vehicle_purchase", "hospitality", "refreshments", "fines",
        "interest_authorities", "donations", "social_insurance_owner",
    ):
        assert cat in TAX_RULES


def test_personal_deduction_categories_not_posted_as_business_expense():
    """תרומות וב"ל עצמאי — ניכוי/זיכוי אישי, לא הוצאה עסקית (KB01 סעיף 7)."""
    for cat in ("donations", "social_insurance_owner"):
        assert TAX_RULES[cat].income_tax == IncomeTaxTreatment.PERSONAL_DEDUCTION
        assert TAX_RULES[cat].input_vat_fraction == Decimal("0")


def test_fines_and_interest_authorities_never_recognized():
    for cat in ("fines", "interest_authorities"):
        assert TAX_RULES[cat].income_tax == IncomeTaxTreatment.NONE
        assert TAX_RULES[cat].input_vat_fraction == Decimal("0")


def test_vehicle_uses_formula_and_context_vat():
    rule = TAX_RULES["vehicle"]
    assert rule.income_tax == IncomeTaxTreatment.FORMULA
    assert rule.formula_ref == "calculate_vehicle_deduction_percent"
    assert rule.input_vat_fraction is None  # context — per-vehicle profile decides


# ---------------------------------------------------------------------- #
# claimable_vat — document gate before any fraction
# ---------------------------------------------------------------------- #

def test_receipt_only_is_always_zero_regardless_of_category():
    assert claimable_vat(category="services", vat_on_doc=Decimal("18"), doc_kind="receipt") == Decimal("0.00")
    assert claimable_vat(category="hospitality", vat_on_doc=Decimal("18"), doc_kind="receipt") == Decimal("0.00")


def test_unknown_or_missing_doc_kind_is_review_not_zero():
    assert claimable_vat(category="services", vat_on_doc=Decimal("18"), doc_kind="unknown") is None
    assert claimable_vat(category="services", vat_on_doc=Decimal("18"), doc_kind=None) is None


def test_structurally_vat_free_supplier_kind_overrides_category():
    assert "bank" in SUPPLIER_KINDS_NO_VAT
    assert claimable_vat(
        category="services", vat_on_doc=Decimal("18"), doc_kind="tax_invoice", supplier_kind="bank",
    ) == Decimal("0.00")


def test_tax_invoice_full_fraction_category():
    assert claimable_vat(category="office", vat_on_doc=Decimal("18"), doc_kind="tax_invoice") == Decimal("18.00")


def test_tax_invoice_zero_fraction_category():
    assert claimable_vat(category="hospitality", vat_on_doc=Decimal("18"), doc_kind="tax_invoice") == Decimal("0.00")


def test_context_dependent_category_without_context_is_none():
    assert claimable_vat(category="refreshments", vat_on_doc=Decimal("18"), doc_kind="tax_invoice") is None
    assert claimable_vat(category="other", vat_on_doc=Decimal("18"), doc_kind="tax_invoice") is None
    assert claimable_vat(category="petty_cash", vat_on_doc=Decimal("18"), doc_kind="tax_invoice") is None


# ---------------------------------------------------------------------- #
# claimable_vat — vehicle (running costs, תקנה 18) and vehicle_purchase (תקנה 14)
# ---------------------------------------------------------------------- #

def test_vehicle_primarily_business_gets_two_thirds():
    result = claimable_vat(
        category="vehicle", vat_on_doc=Decimal("90"), doc_kind="tax_invoice",
        vehicle_primarily_business=True,
    )
    assert result == (Decimal("90") * Decimal("2") / Decimal("3")).quantize(Decimal("0.01"))


def test_vehicle_not_primarily_business_gets_one_quarter():
    result = claimable_vat(
        category="vehicle", vat_on_doc=Decimal("100"), doc_kind="tax_invoice",
        vehicle_primarily_business=False,
    )
    assert result == Decimal("25.00")


def test_vehicle_without_profile_is_none():
    assert claimable_vat(
        category="vehicle", vat_on_doc=Decimal("100"), doc_kind="tax_invoice",
    ) is None


def test_vehicle_purchase_private_is_zero():
    result = claimable_vat(
        category="vehicle_purchase", vat_on_doc=Decimal("5000"), doc_kind="tax_invoice",
        vehicle_kind="private",
    )
    assert result == Decimal("0.00")


@pytest.mark.parametrize("kind", ["commercial", "taxi", "rental", "driving_school", "dealer_stock"])
def test_vehicle_purchase_exception_kinds_get_full(kind):
    result = claimable_vat(
        category="vehicle_purchase", vat_on_doc=Decimal("5000"), doc_kind="tax_invoice",
        vehicle_kind=kind,
    )
    assert result == Decimal("5000.00")


def test_vehicle_purchase_without_kind_is_none():
    assert claimable_vat(
        category="vehicle_purchase", vat_on_doc=Decimal("5000"), doc_kind="tax_invoice",
    ) is None


# ---------------------------------------------------------------------- #
# resolve_vehicle_profile_args — pure selection over loaded profiles
# ---------------------------------------------------------------------- #

def test_resolve_vehicle_profile_args_single_profile():
    profiles = [{"primarily_business": True, "vehicle_kind": "commercial"}]
    assert resolve_vehicle_profile_args(profiles) == (True, "commercial")


def test_resolve_vehicle_profile_args_none_when_zero_profiles():
    assert resolve_vehicle_profile_args([]) == (None, None)


def test_resolve_vehicle_profile_args_none_when_multiple_profiles():
    profiles = [
        {"primarily_business": True, "vehicle_kind": "private"},
        {"primarily_business": False, "vehicle_kind": "commercial"},
    ]
    assert resolve_vehicle_profile_args(profiles) == (None, None)


# ---------------------------------------------------------------------- #
# VERIFICATION_NEEDED — every ⚠️ flag in KB 01+02 must be tracked
# ---------------------------------------------------------------------- #

def test_verification_needed_covers_kb_flagged_thresholds():
    kb_dir = Path(__file__).resolve().parents[1] / "docs" / "bookkeeper_kb"
    text = (kb_dir / "01-income-tax-recognition.md").read_text(encoding="utf-8")
    text += (kb_dir / "02-vat-input-deductibility.md").read_text(encoding="utf-8")
    warn_count = text.count("⚠️")
    assert warn_count >= 8
    assert len(VERIFICATION_NEEDED) >= 8

    joined = " | ".join(VERIFICATION_NEEDED)
    for term in (
        "15,000", "97", "162", "240", "1,200", "2.48", "122,833", "239", "2,700", "26,600", "33%", "6%",
    ):
        assert term in joined, term


# ---------------------------------------------------------------------- #
# render_bridge_table_he — deterministic, wrapped, checked into the docs
# ---------------------------------------------------------------------- #

def test_render_is_deterministic_and_wrapped_in_generated_markers():
    out1 = render_bridge_table_he()
    out2 = render_bridge_table_he()
    assert out1 == out2
    assert out1.strip().startswith("<!-- BEGIN GENERATED -->")
    assert out1.strip().endswith("<!-- END GENERATED -->")
    for key in TAX_RULES:
        assert key in out1


def test_render_contains_verification_needed_list():
    out = render_bridge_table_he()
    for item in VERIFICATION_NEEDED:
        assert item in out


def test_generated_doc_file_matches_current_render():
    """scripts/render_bookkeeper_kb.py writes docs/bookkeeper_kb/03-classification-bridge.md
    with the generated block verbatim. If this fails, re-run the script."""
    doc_path = (
        Path(__file__).resolve().parents[1] / "docs" / "bookkeeper_kb" / "03-classification-bridge.md"
    )
    assert doc_path.exists(), "run scripts/render_bookkeeper_kb.py"
    content = doc_path.read_text(encoding="utf-8")
    assert render_bridge_table_he() in content
