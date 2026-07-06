"""Wave 2 addition E: fixed assets & depreciation (רכוש קבוע ופחת).

Straight-line depreciation (פחת ישר): annual = (cost - salvage) * rate%,
prorated monthly from purchase_date's month (purchase month counted as a full
month — 12 - month + 1 months in the first year), capped so accumulated
depreciation never exceeds cost - salvage.
"""
from datetime import date
from decimal import Decimal

import pytest

from cfo.database import SessionLocal
from cfo.services import depreciation_service as svc
from cfo.services.ledger_service import CHART


def _make_asset(organization_id, **overrides):
    from cfo.models import FixedAsset
    defaults = dict(
        organization_id=organization_id,
        name="מחשב נייד",
        category="computers",
        cost=Decimal("12000"),
        purchase_date=date(2024, 1, 1),
        depreciation_rate=Decimal("33"),
        salvage_value=Decimal("0"),
    )
    defaults.update(overrides)
    return FixedAsset(**defaults)


# ---------------------------------------------------------------------- #
# Schedule math
# ---------------------------------------------------------------------- #
def test_schedule_full_year_asset_no_proration():
    """Purchased Jan 1 -> first year is a full 12/12 year, no proration."""
    asset = _make_asset(1, purchase_date=date(2024, 1, 1), cost=Decimal("12000"),
                        depreciation_rate=Decimal("33"), salvage_value=Decimal("0"))
    schedule = svc.depreciation_schedule(asset)
    assert schedule[0]["year"] == 2024
    assert schedule[0]["annual_depreciation"] == pytest.approx(3960.0)  # 12000*0.33
    assert schedule[0]["accumulated"] == pytest.approx(3960.0)
    assert schedule[0]["book_value"] == pytest.approx(12000 - 3960.0)


def test_schedule_mid_year_purchase_prorates_first_year():
    """Purchased June (month=6) -> 7/12 of the annual amount in the first year
    (Jun-Dec inclusive of the purchase month)."""
    asset = _make_asset(1, purchase_date=date(2024, 6, 15), cost=Decimal("12000"),
                        depreciation_rate=Decimal("33"), salvage_value=Decimal("0"))
    schedule = svc.depreciation_schedule(asset)
    annual_full = 12000 * 0.33
    expected_first_year = round(annual_full * 7 / 12, 2)
    assert schedule[0]["year"] == 2024
    assert schedule[0]["annual_depreciation"] == pytest.approx(expected_first_year)
    # Second year is a full year at the full annual rate (uncapped).
    assert schedule[1]["annual_depreciation"] == pytest.approx(round(annual_full, 2))


def test_schedule_caps_accumulated_at_cost_minus_salvage():
    asset = _make_asset(1, purchase_date=date(2020, 1, 1), cost=Decimal("10000"),
                        depreciation_rate=Decimal("15"), salvage_value=Decimal("1000"))
    schedule = svc.depreciation_schedule(asset)
    depreciable_base = 10000 - 1000
    total_depreciation = sum(r["annual_depreciation"] for r in schedule)
    assert total_depreciation == pytest.approx(depreciable_base)
    for row in schedule:
        assert row["accumulated"] <= depreciable_base + 0.01
    # Final book value settles at the salvage value, never below it.
    assert schedule[-1]["book_value"] == pytest.approx(1000.0)


def test_schedule_zero_rate_asset_never_depreciates():
    asset = _make_asset(1, purchase_date=date(2024, 1, 1), cost=Decimal("5000"),
                        depreciation_rate=Decimal("0"), salvage_value=Decimal("0"))
    schedule = svc.depreciation_schedule(asset)
    assert len(schedule) == 1
    assert schedule[0]["annual_depreciation"] == 0.0
    assert schedule[0]["accumulated"] == 0.0
    assert schedule[0]["book_value"] == pytest.approx(5000.0)


# ---------------------------------------------------------------------- #
# CRUD (org-scoped)
# ---------------------------------------------------------------------- #
def test_create_asset_defaults_rate_from_category_config(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        asset = svc.create_asset(
            db, org_id, name="בניין משרדים", category="buildings",
            cost=Decimal("500000"), purchase_date=date(2024, 1, 1),
        )
        assert float(asset.depreciation_rate) == svc.DEPRECIATION_RATE_CONFIG["buildings"]
    finally:
        db.close()


def test_create_asset_explicit_rate_overrides_config_default(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        asset = svc.create_asset(
            db, org_id, name="ציוד מיוחד", category="equipment",
            cost=Decimal("20000"), purchase_date=date(2024, 1, 1),
            depreciation_rate=Decimal("12"),
        )
        assert float(asset.depreciation_rate) == 12.0
    finally:
        db.close()


def test_list_and_delete_asset_are_org_scoped(fresh_org):
    org_a = fresh_org()["org_id"]
    org_b = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        asset = svc.create_asset(
            db, org_a, name="רכב חברה", category="vehicles",
            cost=Decimal("100000"), purchase_date=date(2023, 1, 1),
        )
        assert len(svc.list_assets(db, org_a)) == 1
        assert svc.list_assets(db, org_b) == []
        assert svc.get_asset(db, org_b, asset.id) is None
        with pytest.raises(ValueError):
            svc.delete_asset(db, org_b, asset.id)
        svc.delete_asset(db, org_a, asset.id)
        assert svc.list_assets(db, org_a) == []
    finally:
        db.close()


# ---------------------------------------------------------------------- #
# Derived journal entries
# ---------------------------------------------------------------------- #
def test_journal_entries_balance_and_are_marked_derived(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        svc.create_asset(
            db, org_id, name="ציוד ייצור", category="equipment",
            cost=Decimal("40000"), purchase_date=date(2025, 1, 1),
            depreciation_rate=Decimal("10"), salvage_value=Decimal("0"),
        )
        result = svc.journal_entries(db, org_id, 2025)
        assert result["derived"] is True
        assert "לבדיקת רו\"ח" in result["disclaimer"]
        assert len(result["entries"]) == 1
        entry = result["entries"][0]
        assert entry["total_debit"] == entry["total_credit"]
        assert entry["total_debit"] == pytest.approx(4000.0)  # 40000 * 0.10
        assert entry["balanced"] is True
    finally:
        db.close()


def test_journal_entries_use_chart_accounts_for_depreciation():
    """The two dedicated פחת chart codes must exist so the derived entry's
    account names resolve instead of falling back to the bare code."""
    assert "5200" in CHART and CHART["5200"]["type"] == "expense"
    assert "1250" in CHART and CHART["1250"]["type"] == "asset"


def test_annual_depreciation_total_sums_across_assets(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        svc.create_asset(db, org_id, name="נכס א", category="equipment",
                         cost=Decimal("10000"), purchase_date=date(2025, 1, 1),
                         depreciation_rate=Decimal("10"), salvage_value=Decimal("0"))
        svc.create_asset(db, org_id, name="נכס ב", category="furniture",
                         cost=Decimal("6000"), purchase_date=date(2025, 1, 1),
                         depreciation_rate=Decimal("6"), salvage_value=Decimal("0"))
        total = svc.annual_depreciation_total(db, org_id, 2025)
        assert total == pytest.approx(1000.0 + 360.0)
    finally:
        db.close()


def test_annual_depreciation_total_zero_for_year_before_purchase(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        svc.create_asset(db, org_id, name="נכס עתידי", category="equipment",
                         cost=Decimal("10000"), purchase_date=date(2025, 6, 1),
                         depreciation_rate=Decimal("10"))
        assert svc.annual_depreciation_total(db, org_id, 2024) == 0.0
    finally:
        db.close()


# ---------------------------------------------------------------------- #
# Form 1342 draft (נספח פחת — טופס י"א)
# ---------------------------------------------------------------------- #
def test_form_1342_draft_totals_equal_sum_of_rows(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        svc.create_asset(db, org_id, name="משאית", category="vehicles",
                         cost=Decimal("150000"), purchase_date=date(2023, 1, 1),
                         depreciation_rate=Decimal("15"), salvage_value=Decimal("0"))
        svc.create_asset(db, org_id, name="שרת", category="computers",
                         cost=Decimal("8000"), purchase_date=date(2024, 7, 1),
                         depreciation_rate=Decimal("33"), salvage_value=Decimal("0"))
        rep = svc.form_1342_draft(db, org_id, 2025)
        assert rep["draft"] is True
        assert "רו\"ח" in rep["disclaimer"]  # same disclaimer convention as annual_report_service
        assert len(rep["rows"]) == 2
        assert rep["totals"]["cost"] == pytest.approx(sum(r["cost"] for r in rep["rows"]))
        assert rep["totals"]["depreciation_this_year"] == pytest.approx(
            sum(r["depreciation_this_year"] for r in rep["rows"]))
        assert rep["totals"]["accumulated_depreciation"] == pytest.approx(
            sum(r["accumulated_depreciation"] for r in rep["rows"]))


    finally:
        db.close()


def test_form_1342_draft_excludes_assets_not_yet_purchased(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        svc.create_asset(db, org_id, name="נכס עתידי", category="equipment",
                         cost=Decimal("10000"), purchase_date=date(2026, 1, 1),
                         depreciation_rate=Decimal("10"))
        rep = svc.form_1342_draft(db, org_id, 2025)
        assert rep["rows"] == []
        assert rep["totals"]["cost"] == 0.0
    finally:
        db.close()


# ---------------------------------------------------------------------- #
# Ledger integration — build_journal must include depreciation when assets exist
# ---------------------------------------------------------------------- #
def test_build_journal_includes_depreciation_entry_when_asset_exists(fresh_org):
    from cfo.services import ledger_service

    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        svc.create_asset(db, org_id, name="ציוד", category="equipment",
                         cost=Decimal("20000"), purchase_date=date(2025, 1, 1),
                         depreciation_rate=Decimal("10"), salvage_value=Decimal("0"))
        entries = ledger_service.build_journal(db, org_id, start=date(2025, 1, 1), end=date(2025, 12, 31))
        dep_entries = [e for e in entries if e.source_ref.startswith("depreciation:")]
        assert len(dep_entries) == 1
        assert dep_entries[0].balanced
        assert dep_entries[0].total_debit == pytest.approx(2000.0)

        tb = ledger_service.trial_balance(db, org_id, start=date(2025, 1, 1), end=date(2025, 12, 31))
        assert tb["balanced"] is True
        expense_row = next(a for a in tb["accounts"] if a["account"] == "5200")
        assert expense_row["debit"] == pytest.approx(2000.0)
    finally:
        db.close()


def test_build_journal_no_depreciation_entries_without_assets(fresh_org):
    from cfo.services import ledger_service

    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        entries = ledger_service.build_journal(db, org_id)
        assert not any(e.source_ref.startswith("depreciation:") for e in entries)
    finally:
        db.close()
