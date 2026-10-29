"""Checking balance refresh includes accounts, and today's block stays honest."""
from datetime import date

from cfo.services.dashboards.liquidity_today import build_liquidity_today
from cfo.services.sync_engine import ensure_open_finance_accounts


def test_open_finance_bank_refresh_writes_accounts_first():
    assert ensure_open_finance_accounts(
        "open_finance", ["bank_transactions"],
    ) == ["accounts", "bank_transactions"]


def test_sumit_and_full_sync_are_unchanged():
    assert ensure_open_finance_accounts("sumit", ["bank_transactions"]) == ["bank_transactions"]
    assert ensure_open_finance_accounts("open_finance", None) is None
    assert ensure_open_finance_accounts(
        "open_finance", ["accounts", "bank_transactions"],
    ) == ["accounts", "bank_transactions"]


def test_stale_checking_is_unknown_and_keeps_the_last_booked_amount():
    block = build_liquidity_today(
        {
            "position": {"balance": -71947.05, "as_of": "2026-10-26", "limit": 100000, "available_to_limit": 28052.95},
            "stale_balances": [{"observed_balance": -71947.05, "as_of": "2026-10-26"}],
            "accounts": [{"kind": "checking", "available_limit": 5000, "as_of": "2026-10-26"}],
        },
        {"weeks": [{"start": "2026-10-29", "end": "2026-11-04", "in": 1, "out": 2, "net": -1, "closing": None, "headroom": None}]},
        today=date(2026, 10, 29),
    )
    assert block["checking"]["balance"] is None
    assert block["checking"]["last_booked"] == -71947.05
    assert block["facility"]["used"] is None
    assert block["facility"]["headroom"] is None
    assert block["facility"]["breach"] is None
    assert block["facility"]["available_limit"] == 5000
    assert block["provider_calls"] == 0


def test_fresh_checking_reports_used_headroom_and_breach():
    block = build_liquidity_today(
        {
            "position": {
                "balance": -10, "as_of": "2026-10-29", "balance_source": "checking_snapshot",
                "limit": 5, "available_to_limit": -5,
            },
            "upcoming": [{"date": "2026-11-10", "label": "שכר", "kind": "payroll", "amount": -1000}],
        },
        None,
        today=date(2026, 10, 29),
    )
    assert block["checking"]["balance"] == -10
    assert block["checking"]["status"] == "ready"
    assert block["facility"]["used"] == 10
    assert block["facility"]["headroom"] == -5
    assert block["facility"]["breach"] is True
    assert block["upcoming"][0]["kind"] == "payroll"
