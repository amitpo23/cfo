"""פאזה 11 — AdvancedForecastingService חייב להחזיר נתון אמיתי הנגזר מה-DB,
לא ערכים קשיחים (predicted=0, total_budget=81000, estimated_revenue=100000).

כל טסט זורע נתון ידוע ומאמת שהפלט משקף אותו — כדי להבחין בין delegation אמיתי
ל-stub מזויף.
"""
from datetime import datetime, timedelta
from decimal import Decimal

from cfo.database import SessionLocal
from cfo.models import (
    Account,
    AccountType,
    Budget,
    Transaction,
    TransactionType,
)
from cfo.services.forecasting_advanced import AdvancedForecastingService


def _seed_cashflow(org_id, months=4, income=12000, expense=5000):
    """זריעת income/expense חודשיים עקביים לאורך כמה חודשים אחרונים."""
    db = SessionLocal()
    try:
        acc = Account(organization_id=org_id, name="בנק", account_type=AccountType.BANK, balance=0)
        db.add(acc)
        db.flush()
        now = datetime.now()
        rows = []
        for m in range(months):
            ref = now - timedelta(days=30 * m + 5)
            rows.append(Transaction(
                organization_id=org_id, account_id=acc.id,
                transaction_type=TransactionType.INCOME, amount=income,
                description="הכנסה", category="sales", transaction_date=ref,
            ))
            rows.append(Transaction(
                organization_id=org_id, account_id=acc.id,
                transaction_type=TransactionType.EXPENSE, amount=expense,
                description="הוצאה", category="rent", transaction_date=ref,
            ))
        db.add_all(rows)
        db.commit()
    finally:
        db.close()


def test_forecast_cash_flow_derives_from_transactions(fresh_org):
    """תחזית התזרים חייבת לשקף הכנסות/הוצאות שנזרעו, לא אפסים קשיחים."""
    org_id = fresh_org()["org_id"]
    _seed_cashflow(org_id, income=12000, expense=5000)

    db = SessionLocal()
    try:
        result = AdvancedForecastingService(db, org_id).forecast_cash_flow(
            days_ahead=90, starting_balance=Decimal("10000"),
        )
    finally:
        db.close()

    assert result["starting_balance"] == 10000.0
    assert result["forecast"], "expected non-empty forecast periods"
    first = result["forecast"][0]
    # ה-stub החזיר predicted_inflows=0 לכל התקופות; אמיתי נגזר מ~12000 שנזרעו
    assert first["projected_inflows"] > 0
    assert 6000 < first["projected_inflows"] < 24000
    assert first["projected_outflows"] > 0
    # נטו חיובי (12000 הכנסה מול 5000 הוצאה) -> היתרה גדלה מעבר לפתיחה
    assert result["ending_balance"] > 10000.0


def test_budget_vs_actual_reads_real_budget(fresh_org):
    """total_budget חייב להיגזר מרשומות Budget אמיתיות, לא מ-81000 הקשיח."""
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        db.add(Budget(
            organization_id=org_id, category_name="sales",
            year=2026, month=6, budgeted_amount=Decimal("50000"),
        ))
        db.commit()
    finally:
        db.close()

    db = SessionLocal()
    try:
        result = AdvancedForecastingService(db, org_id).budget_vs_actual(
            period="monthly", year=2026, month=6,
        )
    finally:
        db.close()

    assert result["total_budget"] == 50000.0  # ה-stub החזיר 81000
    assert "by_category" in result
    assert "sales" in result["by_category"]


def test_budget_vs_actual_empty_when_no_budget(fresh_org):
    """ללא תקציב מוגדר -> אפסים כנים, לא 81000 מומצא."""
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        result = AdvancedForecastingService(db, org_id).budget_vs_actual(
            period="monthly", year=2026, month=6,
        )
    finally:
        db.close()

    assert result["total_budget"] == 0.0


def test_scenario_analysis_honors_assumptions(fresh_org):
    """ההנחות (revenue_increase/expense_cut) חייבות להשפיע; ההמלצה נגזרת מהתוצאה."""
    org_id = fresh_org()["org_id"]
    _seed_cashflow(org_id, income=12000, expense=5000)

    scenarios = [
        {"name": "Conservative", "assumptions": {"revenue_increase": 0.0, "expense_cut": 0.1}},
        {"name": "Aggressive", "assumptions": {"revenue_increase": 0.5, "expense_cut": 0.0}},
    ]
    db = SessionLocal()
    try:
        result = AdvancedForecastingService(db, org_id).scenario_analysis(scenarios)
    finally:
        db.close()

    assert len(result["scenarios"]) == 2
    by_name = {s["scenario"]: s for s in result["scenarios"]}
    # ה-stub החזיר estimated_revenue=100000 קבוע לשני התרחישים
    assert by_name["Aggressive"]["estimated_revenue"] > by_name["Conservative"]["estimated_revenue"]
    assert by_name["Conservative"]["estimated_revenue"] != 100000
    # ההמלצה נגזרת מ-net הגבוה, לא "first" קשיח
    assert result["recommendation"] == "Aggressive"
