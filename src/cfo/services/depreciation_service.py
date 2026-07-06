"""Fixed assets & depreciation (רכוש קבוע ופחת) — Wave 2 addition E.

Straight-line depreciation (פחת ישר) per the Income Tax (Depreciation)
Regulations, 1959: annual = (cost - salvage) * rate%, prorated monthly from
the purchase month (the purchase month itself counts as a full month — the
common convention this module follows), capped so accumulated depreciation
never exceeds cost - salvage.

DEPRECIATION_RATE_CONFIG holds DEFAULT annual rates per category — the real
regulations specify ranges/sub-categories (e.g. equipment 7%-10% depending on
use). The asset itself always stores its OWN chosen rate (defaulted from this
config at creation, but always overridable) — a rate choice is therefore a
per-asset, auditable fact, never re-derived silently from the category later.

Every derived output here (journal_entries, entries_for_ledger,
form_1342_draft) is explicitly labeled derived/draft — decision support for
an accountant, never a filing or the official books.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Optional

from .ledger_service import CHART, DISCLAIMER, Entry, Line

# Annual straight-line rate DEFAULTS (%) per category, per Israeli Income Tax
# (Depreciation) Regulations. Real regulations carve out sub-categories/ranges;
# these are sane single-value defaults for asset creation, always overridable.
DEPRECIATION_RATE_CONFIG: dict[str, float] = {
    "buildings": 4.0,    # מבנים (בטון/קבע) — 4% שנתי
    "equipment": 7.0,    # מכונות וציוד כללי — טווח נפוץ 7%-10%, ברירת מחדל שמרנית
    "computers": 33.0,   # מחשבים ותוכנה — 33% שנתי (כ-3 שנות חיים)
    "vehicles": 15.0,    # כלי רכב — 15% שנתי
    "furniture": 6.0,    # ריהוט וציוד משרדי — טווח נפוץ 6%-7%
    "other": 10.0,       # נכס לא מסווג — ברירת מחדל כללית, לאישור מול רו"ח
}

EXPENSE_ACCOUNT = "5200"             # הוצאות פחת
ACCUM_DEPRECIATION_ACCOUNT = "1250"  # פחת נצבר (רכוש קבוע)

# Safety guard against an unbounded loop in depreciation_schedule (float
# rounding could in theory make `portion` shrink to ~0 without accumulated
# ever quite reaching depreciable_base). 200 years is far beyond any real
# straight-line schedule (max ~25y even at the slowest 4% buildings rate).
_MAX_SCHEDULE_YEARS = 200


def default_rate_for_category(category: str) -> float:
    return DEPRECIATION_RATE_CONFIG.get(category, DEPRECIATION_RATE_CONFIG["other"])


# ---------------------------------------------------------------------- #
# CRUD (org-scoped)
# ---------------------------------------------------------------------- #
def create_asset(db, organization_id: int, *, name: str, category: str, cost,
                 purchase_date: date, depreciation_rate=None, salvage_value=0,
                 notes: Optional[str] = None):
    from ..models import FixedAsset

    rate = depreciation_rate if depreciation_rate is not None else default_rate_for_category(category)
    asset = FixedAsset(
        organization_id=organization_id, name=name, category=category,
        cost=cost, purchase_date=purchase_date, depreciation_rate=rate,
        salvage_value=salvage_value or 0, notes=notes,
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return asset


def list_assets(db, organization_id: int):
    from ..models import FixedAsset
    return db.query(FixedAsset).filter(
        FixedAsset.organization_id == organization_id
    ).order_by(FixedAsset.purchase_date.asc()).all()


def get_asset(db, organization_id: int, asset_id: int):
    from ..models import FixedAsset
    return db.query(FixedAsset).filter(
        FixedAsset.organization_id == organization_id,
        FixedAsset.id == asset_id,
    ).first()


def delete_asset(db, organization_id: int, asset_id: int) -> None:
    asset = get_asset(db, organization_id, asset_id)
    if asset is None:
        raise ValueError("נכס קבוע לא נמצא")
    db.delete(asset)
    db.commit()


def asset_to_dict(asset) -> dict[str, Any]:
    return {
        "id": asset.id,
        "name": asset.name,
        "category": asset.category,
        "cost": float(asset.cost or 0),
        "purchase_date": asset.purchase_date.isoformat() if asset.purchase_date else None,
        "depreciation_rate": float(asset.depreciation_rate or 0),
        "salvage_value": float(asset.salvage_value or 0),
        "notes": asset.notes,
        "created_at": asset.created_at.isoformat() if asset.created_at else None,
    }


# ---------------------------------------------------------------------- #
# Schedule math
# ---------------------------------------------------------------------- #
def depreciation_schedule(asset) -> list[dict[str, Any]]:
    """Straight-line yearly schedule: [{year, annual_depreciation, accumulated,
    book_value}, ...] from the purchase year until fully depreciated (or a
    single zero row if the rate is 0 / the asset has no depreciable base)."""
    cost = float(asset.cost or 0)
    salvage = float(asset.salvage_value or 0)
    rate = float(asset.depreciation_rate or 0)
    depreciable_base = round(max(0.0, cost - salvage), 2)
    purchase_year = asset.purchase_date.year
    purchase_month = asset.purchase_date.month

    if rate <= 0 or depreciable_base <= 0:
        return [{
            "year": purchase_year,
            "annual_depreciation": 0.0,
            "accumulated": 0.0,
            "book_value": round(cost, 2),
        }]

    annual_full = round(depreciable_base * rate / 100.0, 2)
    # Purchase month counts as a full month of use (common convention):
    # e.g. purchased in June (month=6) -> 7/12 in the first year (Jun..Dec).
    months_in_first_year = 12 - purchase_month + 1

    rows: list[dict[str, Any]] = []
    accumulated = 0.0
    year = purchase_year
    first = True
    while accumulated < depreciable_base and len(rows) < _MAX_SCHEDULE_YEARS:
        portion = round(annual_full * months_in_first_year / 12, 2) if first else annual_full
        first = False
        if accumulated + portion >= depreciable_base:
            portion = round(depreciable_base - accumulated, 2)
        accumulated = round(accumulated + portion, 2)
        rows.append({
            "year": year,
            "annual_depreciation": portion,
            "accumulated": accumulated,
            "book_value": round(cost - accumulated, 2),
        })
        year += 1
    return rows


# ---------------------------------------------------------------------- #
# Derived journal entries — for the ledger integration and the /journal-facing
# reports (year total, form 1342).
# ---------------------------------------------------------------------- #
def entries_for_ledger(db, organization_id: int) -> list[Entry]:
    """One aggregated Entry per calendar year across ALL of the org's assets
    (DR 5200 הוצאות פחת / CR 1250 פחת נצבר), dated Dec 31 of that year. Used
    directly by ledger_service.build_journal — the same _in_period filter
    every other source goes through applies to these too."""
    assets = list_assets(db, organization_id)
    totals_by_year: dict[int, float] = {}
    for asset in assets:
        for row in depreciation_schedule(asset):
            if row["annual_depreciation"] <= 0:
                continue
            totals_by_year[row["year"]] = round(
                totals_by_year.get(row["year"], 0.0) + row["annual_depreciation"], 2)

    out: list[Entry] = []
    for year in sorted(totals_by_year):
        total = totals_by_year[year]
        e = Entry(entry_date=date(year, 12, 31), memo=f"פחת שנתי {year}",
                  source_ref=f"depreciation:{year}")
        e.lines = [
            Line(EXPENSE_ACCOUNT, debit=total, description="הוצאות פחת"),
            Line(ACCUM_DEPRECIATION_ACCOUNT, credit=total, description="פחת נצבר"),
        ]
        out.append(e)
    return out


def annual_depreciation_total(db, organization_id: int, year: int) -> float:
    """Sum of depreciation across the org's assets for one tax year."""
    for e in entries_for_ledger(db, organization_id):
        if e.entry_date and e.entry_date.year == year:
            return e.total_debit
    return 0.0


def journal_entries(db, organization_id: int, year: int) -> dict[str, Any]:
    """Derived double-entry rows for one year, in the same shape
    ledger_service produces (Entry.as_dict()) — marked derived/draft."""
    year_entries = [e for e in entries_for_ledger(db, organization_id)
                    if e.entry_date and e.entry_date.year == year]
    total = round(sum(e.total_debit for e in year_entries), 2)
    return {
        "year": year,
        "entries": [e.as_dict() for e in year_entries],
        "total_depreciation": total,
        "derived": True,
        "disclaimer": DISCLAIMER,
    }


# ---------------------------------------------------------------------- #
# Form 1342 draft (נספח פחת — טופס י"א)
# ---------------------------------------------------------------------- #
def form_1342_draft(db, organization_id: int, year: int) -> dict[str, Any]:
    """טיוטת נספח פחת (טופס 1342 / נספח י\"א) — per-asset rows + totals.

    Only includes assets already purchased by the end of `year`. For an asset
    already fully depreciated before `year`, this-year depreciation is 0 and
    its closing accumulated stays flat at the (already-reached) depreciable
    base — never re-derived past that cap."""
    rows: list[dict[str, Any]] = []
    total_cost = total_this_year = total_closing_accum = 0.0

    for asset in list_assets(db, organization_id):
        if asset.purchase_date.year > year:
            continue
        schedule = depreciation_schedule(asset)
        opening = 0.0
        this_year = 0.0
        closing = 0.0
        matched = False
        for row in schedule:
            if row["year"] < year:
                opening = row["accumulated"]
            elif row["year"] == year:
                this_year = row["annual_depreciation"]
                closing = row["accumulated"]
                matched = True
        if not matched:
            # Fully depreciated before `year` (or this-year row doesn't exist
            # for another honest reason) — stays flat, no further charge.
            closing = opening

        cost = float(asset.cost or 0)
        book_value = round(cost - closing, 2)
        rows.append({
            "asset_id": asset.id,
            "name": asset.name,
            "category": asset.category,
            "cost": round(cost, 2),
            "purchase_date": asset.purchase_date.isoformat(),
            "rate": float(asset.depreciation_rate or 0),
            "opening_accumulated": round(opening, 2),
            "depreciation_this_year": round(this_year, 2),
            "accumulated_depreciation": round(closing, 2),
            "book_value": book_value,
        })
        total_cost += cost
        total_this_year += this_year
        total_closing_accum += closing

    return {
        "form": "1342",
        "title": "נספח פחת (טופס 1342 — נספח י\"א)",
        "year": year,
        "rows": rows,
        "totals": {
            "cost": round(total_cost, 2),
            "depreciation_this_year": round(total_this_year, 2),
            "accumulated_depreciation": round(total_closing_accum, 2),
            "book_value": round(total_cost - total_closing_accum, 2),
        },
        "draft": True,
        "disclaimer": "טיוטה אוטומטית הנגזרת מהנכסים הרשומים — אינה דוח להגשה. חובה בדיקה והשלמה ע\"י רו\"ח.",
    }
