"""Cashflow-detail liquidity uses the checking snapshot. Missing is not zero."""
from datetime import date, datetime
from decimal import Decimal

from cfo.database import SessionLocal
from cfo.models import Account, AccountType
from cfo.services.dashboards.cashflow_liquidity import cashflow_liquidity_surface, ratios_from_checking
from cfo.services.live_cash_flow_service import LiveCashFlowService


def test_unknown_checking_balance_does_not_become_zero_ratios():
    ratios = ratios_from_checking(None)
    assert ratios["current_ratio"] is None
    assert ratios["quick_ratio"] is None
    assert ratios["cash_ratio"] is None
    assert ratios["working_capital"] is None
    assert ratios["current_assets"] is None
    assert ratios["current_liabilities"] is None
    assert ratios["missing_label"]


def test_a_known_checking_balance_is_not_a_fabricated_current_ratio():
    ratios = ratios_from_checking(5000)
    assert ratios["current_assets"] == 5000
    assert ratios["current_ratio"] is None
    assert ratios["quick_ratio"] is None
    assert ratios["cash_ratio"] is None


def test_an_overdraft_is_not_stored_as_zero_current_assets():
    ratios = ratios_from_checking(-10)
    assert ratios["current_assets"] is None
    assert ratios["current_ratio"] is None


def test_stale_open_finance_balance_keeps_ratios_and_runway_unknown(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        db.add(Account(
            organization_id=org_id,
            name="הפועלים",
            account_type=AccountType.BANK,
            raw_account_type="CHECKING",
            source="open_finance",
            external_id="stale-checking",
            balance=Decimal("-71947.05"),
            credit_limit=Decimal("100000"),
            available_limit=Decimal("28052.95"),
            balance_as_of=datetime(2026, 10, 26),
            currency="ILS",
        ))
        db.commit()
        surface = cashflow_liquidity_surface(db, org_id, today=date(2026, 10, 29))
        burn = LiveCashFlowService(db, org_id).burn_rate(as_of_date=date(2026, 10, 29))
    finally:
        db.close()

    assert surface["provider_calls"] == 0
    assert surface["checking"]["balance"] is None
    assert surface["checking"]["last_booked"] == -71947.05
    assert surface["facility"]["limit"] == 100000
    assert surface["facility"]["used"] is None
    assert surface["facility"]["headroom"] is None
    assert surface["facility"]["breach"] is None
    assert round(surface["facility"]["available_limit"], 2) == 28052.95
    for key in ("current_ratio", "quick_ratio", "cash_ratio", "working_capital", "current_assets"):
        assert surface["ratios"][key] is None
    assert burn["current_balance"] is None
    assert burn["runway_months"] is None
    assert burn["runway_status"] == "unavailable"


def test_fresh_checking_reports_credit_used_headroom_and_breach(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        db.add(Account(
            organization_id=org_id,
            name="הפועלים",
            account_type=AccountType.BANK,
            raw_account_type="CHECKING",
            source="open_finance",
            external_id="fresh-checking",
            balance=Decimal("-10"),
            credit_limit=Decimal("5"),
            available_limit=Decimal("0"),
            balance_as_of=datetime(2026, 10, 29),
            currency="ILS",
        ))
        db.commit()
        surface = cashflow_liquidity_surface(db, org_id, today=date(2026, 10, 29))
    finally:
        db.close()

    assert surface["provider_calls"] == 0
    assert surface["checking"]["balance"] == -10
    assert surface["facility"]["limit"] == 5
    assert surface["facility"]["used"] == 10
    assert surface["facility"]["headroom"] == -5
    assert surface["facility"]["breach"] is True
    assert surface["ratios"]["current_assets"] is None
    assert surface["ratios"]["current_ratio"] is None
    assert surface["credit_line_status"] in {"unknown", "breach", "warning", "ok"}
