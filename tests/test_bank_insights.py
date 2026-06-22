"""Tests for the bank-intelligence insights engine."""
from datetime import date

from cfo.services import bank_insights
from cfo.services.bank_insights import Txn


def _by_type(insights):
    out = {}
    for i in insights:
        out.setdefault(i["insight_type"], []).append(i)
    return out


def test_duplicate_charge_detected():
    txns = [
        Txn("a", date(2026, 6, 1), -120.0, merchant="Pizza Place", category_main="FOOD_&_DRINKS"),
        Txn("b", date(2026, 6, 1), -120.0, merchant="Pizza Place", category_main="FOOD_&_DRINKS"),
    ]
    out = _by_type(bank_insights.generate_insights(txns, today=date(2026, 6, 2)))
    assert "duplicate_charge" in out
    assert out["duplicate_charge"][0]["evidence"]["count"] == 2


def test_subscription_detected_across_months():
    txns = [
        Txn(f"s{m}", date(2026, m, 5), -39.9, merchant="Spotify", category_main="LEISURE")
        for m in (3, 4, 5, 6)
    ]
    out = _by_type(bank_insights.generate_insights(txns, today=date(2026, 6, 30)))
    assert "subscription" in out
    ev = out["subscription"][0]["evidence"]
    assert ev["monthly"] == 39.9
    assert ev["annual_estimate"] == round(39.9 * 12, 2)


def test_installment_ending_detected():
    txns = [Txn("i1", date(2026, 6, 3), -200.0, merchant="Electronics",
                installment_number=11, installment_total=12)]
    out = _by_type(bank_insights.generate_insights(txns, today=date(2026, 6, 4)))
    assert "installment_ending" in out


def test_bank_fees_aggregated():
    txns = [
        Txn("f1", date(2026, 6, 1), -22.0, merchant="Bank", category_main="FINANCE"),
        Txn("f2", date(2026, 6, 2), -10.0, merchant="Card", category_main="SHOPPING", markup_fee=10.0),
    ]
    out = _by_type(bank_insights.generate_insights(txns, today=date(2026, 6, 3)))
    assert "bank_fees" in out
    ev = out["bank_fees"][0]["evidence"]
    assert ev["fees"] == 22.0 and ev["fx_markup"] == 10.0


def test_category_spike_detected():
    txns = []
    # baseline ~1000/month for 3 months, then a spike to 2000.
    for m, total in [(3, 1000), (4, 1000), (5, 1000), (6, 2000)]:
        txns.append(Txn(f"c{m}", date(2026, m, 10), -float(total), merchant=f"shop{m}",
                        category_main="SHOPPING"))
    out = _by_type(bank_insights.generate_insights(txns, today=date(2026, 6, 30)))
    assert "category_spike" in out
    assert out["category_spike"][0]["evidence"]["pct"] >= 40


def test_cashflow_forecast_negative():
    txns = [
        Txn("in", date(2026, 6, 1), 5000.0, merchant="Salary", category_main="SALARY"),
        Txn("out", date(2026, 6, 5), -4000.0, merchant="Rent", category_main="HOUSEHOLD_&_SERVICES"),
    ]
    out = _by_type(bank_insights.generate_insights(txns, today=date(2026, 6, 10)))
    assert "cashflow_forecast" in out
    # 4000 spent by day 10 -> pro-rated > income 5000 -> projected negative.
    assert out["cashflow_forecast"][0]["evidence"]["projected_net"] < 0


def test_anomaly_detected_for_large_charge():
    txns = [Txn(f"n{i}", date(2026, 6, (i % 25) + 1), -30.0, merchant="store",
                category_main="SHOPPING") for i in range(12)]
    txns.append(Txn("big", date(2026, 6, 15), -5000.0, merchant="???", category_main="SHOPPING"))
    out = _by_type(bank_insights.generate_insights(txns, today=date(2026, 6, 20)))
    assert "anomaly" in out
    assert any(i["evidence"]["external_id"] == "big" for i in out["anomaly"])


def test_risk_signals_from_monthly_report():
    report = {"openBankingReportBalances": {"nsf": 2, "canceledChecks": 1, "accountForeclosure": 0}}
    out = _by_type(bank_insights.generate_insights([], monthly_report=report))
    types = {i["title"] for i in out.get("risk_signal", [])}
    assert any("NSF" in t for t in types)
    # zero-count fields produce no insight
    assert not any("עיקול" in t for t in types)


def test_fingerprints_are_stable_and_unique():
    txns = [
        Txn("a", date(2026, 6, 1), -120.0, merchant="Pizza Place"),
        Txn("b", date(2026, 6, 1), -120.0, merchant="Pizza Place"),
    ]
    first = bank_insights.generate_insights(txns, today=date(2026, 6, 2))
    second = bank_insights.generate_insights(txns, today=date(2026, 6, 2))
    assert [i["fingerprint"] for i in first] == [i["fingerprint"] for i in second]
    assert len({i["fingerprint"] for i in first}) == len(first)


def test_txn_from_raw_extracts_open_finance_fields():
    raw = {
        "category": {"main": "FOOD_&_DRINKS", "sub": "RESTAURANTS"},
        "merchantName": "Cafe",
        "isDuplicate": True,
        "installments": {"number": 2, "total": 6},
        "markupFee": {"amount": 3.5, "currency": "ILS"},
        "accountId": "acc-1",
    }
    t = bank_insights.txn_from_raw(
        external_id="x", tx_date=date(2026, 6, 1), amount=-50.0, currency="ILS",
        description="Cafe", raw=raw,
    )
    assert t.category_main == "FOOD_&_DRINKS"
    assert t.merchant == "Cafe"
    assert t.is_duplicate is True
    assert t.installment_number == 2 and t.installment_total == 6
    assert t.markup_fee == 3.5
    assert t.account_id == "acc-1"


def _cat_txn(i, amount, cat):
    return Txn(external_id=f"s{i}", date=date(2026, 6, (i % 27) + 1),
               amount=amount, category_main=cat)


def test_sign_validator_passes_for_correct_convention():
    txns = [_cat_txn(i, 10000, "SALARY") for i in range(4)]
    txns += [_cat_txn(i, -200, "FOOD_&_DRINKS") for i in range(6)]
    assert bank_insights.validate_sign_convention(txns) is None


def test_sign_validator_flags_inverted_convention():
    # Provider emits positive-for-debit: salary negative, expenses positive.
    txns = [_cat_txn(i, -10000, "SALARY") for i in range(4)]
    txns += [_cat_txn(i, 200, "FOOD_&_DRINKS") for i in range(6)]
    warn = bank_insights.validate_sign_convention(txns)
    assert warn is not None and warn["inverted"] is True
    assert warn["sample"] == 10


def test_sign_validator_returns_none_below_min_sample():
    txns = [_cat_txn(i, -10000, "SALARY") for i in range(3)]
    assert bank_insights.validate_sign_convention(txns) is None


# ---------------------------------------------------------------------- #
# Server-side aggregate detectors (item 2.2)
# ---------------------------------------------------------------------- #
def test_portfolio_insight_from_extended_securities():
    securities = {
        "totalPositionsValue": 250000,
        "positions": [
            {"securityName": "Apple", "marketValue": 120000, "profitLossPct": 18.0},
            {"securityName": "טבע", "marketValue": 90000, "profitLossPct": -25.0},
            {"securityName": "Bond X", "marketValue": 40000, "profitLossPct": 1.0},
        ],
        "orders": [],
    }
    out = _by_type(bank_insights.detect_portfolio_insights(securities))
    assert "portfolio_summary" in out
    summary = out["portfolio_summary"][0]
    assert summary["evidence"]["total_value"] == 250000
    assert summary["evidence"]["positions"] == 3
    # A single large losing position is surfaced as a concentration/loss alert.
    assert "portfolio_position" in out
    loser = out["portfolio_position"][0]
    assert loser["evidence"]["security"] == "טבע"
    assert loser["evidence"]["profit_loss_pct"] == -25.0


def test_portfolio_insights_empty_payload_returns_nothing():
    assert bank_insights.detect_portfolio_insights({}) == []
    assert bank_insights.detect_portfolio_insights(None) == []
    assert bank_insights.detect_portfolio_insights({"positions": []}) == []


def test_aggregate_balance_insight_negative_cashflow():
    report = {
        "openBankingReportBalances": {
            "incomes": {"total": 18000, "incomeFromSalary": 18000},
            "expenses": {"total": 23000, "regularExpensesSum": 20000},
        }
    }
    out = _by_type(bank_insights.detect_aggregate_balance_insights(report))
    assert "aggregate_balance" in out
    ev = out["aggregate_balance"][0]["evidence"]
    assert ev["income"] == 18000 and ev["expense"] == 23000
    assert ev["net"] == -5000
    assert out["aggregate_balance"][0]["severity"] in ("high", "critical")


def test_aggregate_balance_insight_positive_surplus():
    report = {
        "openBankingReportBalances": {
            "incomes": {"total": 25000},
            "expenses": {"total": 18000},
        }
    }
    out = _by_type(bank_insights.detect_aggregate_balance_insights(report))
    assert "aggregate_balance" in out
    assert out["aggregate_balance"][0]["evidence"]["net"] == 7000


def test_aggregate_balance_insight_empty_returns_nothing():
    assert bank_insights.detect_aggregate_balance_insights({}) == []
    assert bank_insights.detect_aggregate_balance_insights(None) == []
    # Both totals zero/absent → no actionable insight.
    assert bank_insights.detect_aggregate_balance_insights(
        {"openBankingReportBalances": {"incomes": {}, "expenses": {}}}
    ) == []


def test_aggregate_balance_fingerprint_stable_across_magnitude_change():
    # Mid-month income/expense grow on each fetch; the fingerprint must stay stable
    # (keyed to the month) so re-runs UPDATE the row instead of spawning duplicates.
    from datetime import date as _date
    r1 = {"openBankingReportBalances": {"incomes": {"total": 18000}, "expenses": {"total": 23000}}}
    r2 = {"openBankingReportBalances": {"incomes": {"total": 18000}, "expenses": {"total": 24000}}}
    fp1 = bank_insights.detect_aggregate_balance_insights(r1, today=_date(2026, 6, 10))[0]["fingerprint"]
    fp2 = bank_insights.detect_aggregate_balance_insights(r2, today=_date(2026, 6, 20))[0]["fingerprint"]
    assert fp1 == fp2
    # A different month yields a distinct fingerprint.
    fp3 = bank_insights.detect_aggregate_balance_insights(r1, today=_date(2026, 7, 1))[0]["fingerprint"]
    assert fp3 != fp1


def test_generate_insights_wires_securities_and_balances():
    securities = {
        "totalPositionsValue": 100000,
        "positions": [{"securityName": "Apple", "marketValue": 100000, "profitLossPct": 5.0}],
    }
    report = {
        "openBankingReportBalances": {
            "incomes": {"total": 10000},
            "expenses": {"total": 12000},
        }
    }
    out = _by_type(bank_insights.generate_insights(
        [], monthly_report=report, securities=securities,
    ))
    assert "portfolio_summary" in out
    assert "aggregate_balance" in out
