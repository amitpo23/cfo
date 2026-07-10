"""פאזה 13D — AnalyticsReportingService חייב לגזור מזומן/תקציב מנתון אמיתי,
לא מ-stubs שמחזירים אפסים קשיחים.
"""
import calendar
from datetime import date
from decimal import Decimal

from cfo.database import SessionLocal
from cfo.models import Account, AccountType, Budget, Expense
from cfo.services.analytics_reporting import AnalyticsReportingService


def test_cash_position_sums_real_account_balances(fresh_org):
    """מצב המזומן חייב לסכם יתרות חשבונות בנק אמיתיות, לא 0 קשיח."""
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        db.add_all([
            Account(organization_id=org_id, name="עו\"ש", account_type=AccountType.BANK,
                    balance=Decimal("8000")),
            Account(organization_id=org_id, name="חיסכון", account_type=AccountType.BANK,
                    balance=Decimal("2000")),
        ])
        db.commit()

        position = AnalyticsReportingService(db, org_id)._get_cash_position()
    finally:
        db.close()

    assert position["total_cash"] == 10000.0
    assert len(position["bank_accounts"]) == 2


def test_weekly_budget_report_reads_real_budget(fresh_org):
    """הדוח השבועי חייב לשקף תקציב אמיתי + ביצוע בפועל, לא אפסים קשיחים."""
    org_id = fresh_org()["org_id"]
    today = date.today()
    db = SessionLocal()
    try:
        # תקציב חודשי אמיתי לחודש הנוכחי
        db.add(Budget(
            organization_id=org_id, category_name="rent",
            year=today.year, month=today.month, budgeted_amount=Decimal("3000"),
        ))
        # הוצאה אמיתית בשבוע הנוכחי
        db.add(Expense(
            organization_id=org_id, category="rent", total=Decimal("700"),
            supplier_name="בעל הבית", expense_date=today, status="filed",
            description="שכירות",
        ))
        db.commit()

        report = AnalyticsReportingService(db, org_id).generate_weekly_budget_report(today)
    finally:
        db.close()

    avb = report["actual_vs_budget"]
    # ה-stub החזיר budget=0 קבוע; פרורציה של 3000 חודשי לשבוע > 0
    days_in_month = calendar.monthrange(today.year, today.month)[1]
    assert avb["budget"] > 0
    assert avb["budget"] < 3000  # שבוע < חודש
    assert avb["actual"] == 700.0

    variance = report["variance_analysis"]
    assert variance["variance_categories"], "expected per-category variance, not empty stub"


def test_daily_report_runs_without_column_error(fresh_org):
    """generate_daily_report קרס קודם על Invoice/Expense.total_amount החסר."""
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        report = AnalyticsReportingService(db, org_id).generate_daily_report(date.today())
    finally:
        db.close()

    assert report["report_type"] == "daily"
    assert "cash_position" in report
    assert "cumulative_pl_current_month" in report


def test_monthly_pl_report_runs_without_column_error(fresh_org):
    """generate_monthly_pl_report קרס קודם על אותו באג עמודות."""
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        report = AnalyticsReportingService(db, org_id).generate_monthly_pl_report(date.today())
    finally:
        db.close()

    assert report["report_type"] == "monthly_pl"
    assert "revenue" in report
    assert "expenses" in report


def test_prorated_budget_spans_month_boundary(fresh_org):
    """שבוע שחוצה חודשים חייב לשקלל תקציב משני החודשים — לא רק מחודש ההתחלה."""
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        db.add(Budget(organization_id=org_id, category_name="rent",
                      year=2026, month=6, budgeted_amount=Decimal("3000")))
        db.add(Budget(organization_id=org_id, category_name="rent",
                      year=2026, month=7, budgeted_amount=Decimal("3100")))
        db.commit()
        svc = AnalyticsReportingService(db, org_id)
        # שבוע 2026-06-29 (שני) עד 2026-07-05 (ראשון): 2 ימי יוני + 5 ימי יולי
        total, by_cat = svc._prorated_budget(date(2026, 6, 29), date(2026, 7, 5))
    finally:
        db.close()

    expected = 3000 * (2 / 30) + 3100 * (5 / 31)  # 200 + 500 = 700
    assert abs(total - expected) < 0.01
    assert abs(by_cat["rent"] - expected) < 0.01
