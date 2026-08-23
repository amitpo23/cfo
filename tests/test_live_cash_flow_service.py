"""LiveCashFlowService — נתוני מסך "תזרים — מפורט" (`/cashflow-detail`) מבוססי
BankTransaction/Account, לא טבלת Transaction הקפואה (127 שורות ₪0, קפואה
מ-19/08). honest-null + as_of, אותה מוסכמה כמו LiveForecastService (משימה 1).
"""
from datetime import date, datetime, timedelta
from decimal import Decimal

from cfo.database import SessionLocal
from cfo.models import (
    Account, AccountType, BankTransaction, Bill, BillStatus, Category, Contact,
    ContactType, Invoice, InvoiceStatus,
)
from cfo.services.live_cash_flow_service import LiveCashFlowService

TODAY = date.today()
MONTH_ANCHOR = TODAY.replace(day=1)


def _add_months(d: date, months: int) -> date:
    idx = d.month - 1 + months
    return date(d.year + idx // 12, idx % 12 + 1, 1)


# --------------------------------------------------------------------- #
# monthly_cash_flow
# --------------------------------------------------------------------- #
def test_monthly_cash_flow_sums_bank_transactions_per_calendar_month(fresh_org):
    org_id = fresh_org()["org_id"]
    prev_month = _add_months(MONTH_ANCHOR, -1)
    db = SessionLocal()
    try:
        db.add(BankTransaction(organization_id=org_id, transaction_date=MONTH_ANCHOR + timedelta(days=9),
                                description="הפקדה", amount=Decimal("5000")))
        db.add(BankTransaction(organization_id=org_id, transaction_date=MONTH_ANCHOR + timedelta(days=10),
                                description="חיוב", amount=Decimal("-1200")))
        db.add(BankTransaction(organization_id=org_id, transaction_date=prev_month + timedelta(days=5),
                                description="הפקדה קודמת", amount=Decimal("2000")))
        db.commit()

        result = LiveCashFlowService(db, org_id).monthly_cash_flow(months=2, as_of_date=TODAY)
    finally:
        db.close()

    assert result["as_of"] == TODAY.isoformat()
    assert result["data_sources"] == ["bank_transactions_actual"]
    assert result["message"] is None
    assert len(result["months"]) == 2

    m_prev, m_cur = result["months"]
    assert m_prev["month"] == prev_month.strftime("%Y-%m")
    assert m_prev["inflows"] == 2000.0
    assert m_prev["outflows"] == 0.0
    assert m_prev["net_flow"] == 2000.0
    assert m_prev["cumulative"] == 2000.0

    assert m_cur["month"] == MONTH_ANCHOR.strftime("%Y-%m")
    assert m_cur["inflows"] == 5000.0
    assert m_cur["outflows"] == 1200.0
    assert m_cur["net_flow"] == 3800.0
    assert m_cur["cumulative"] == 5800.0


def test_monthly_cash_flow_honest_null_for_empty_org(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        result = LiveCashFlowService(db, org_id).monthly_cash_flow(months=6, as_of_date=TODAY)
    finally:
        db.close()

    assert result["as_of"] == TODAY.isoformat()
    assert result["data_sources"] == []
    assert result["months"] == []
    assert result["message"]
    assert "אין" in result["message"]


def test_monthly_cash_flow_org_isolation(fresh_org):
    org_a = fresh_org()["org_id"]
    org_b = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        db.add(BankTransaction(organization_id=org_a, transaction_date=TODAY,
                                description="x", amount=Decimal("999")))
        db.commit()

        result_a = LiveCashFlowService(db, org_a).monthly_cash_flow(months=1, as_of_date=TODAY)
        result_b = LiveCashFlowService(db, org_b).monthly_cash_flow(months=1, as_of_date=TODAY)
    finally:
        db.close()

    assert result_a["months"][0]["inflows"] == 999.0
    assert result_b["months"] == []
    assert result_b["message"]


# --------------------------------------------------------------------- #
# daily_cash_position
# --------------------------------------------------------------------- #
def test_daily_cash_position_walks_from_live_account_balance(fresh_org):
    """חוזה המזומן (P0-B, 23/08/2026): 'יתרה חיה' = BANK ממקור Open
    Finance עם חותמת-זמן טרייה (source="open_finance" + balance_as_of
    בתוך 48h) — לא כל Account BANK/ASSET שקיים. הפיקסצ'ורה כאן מייצגת
    בכוונה חשבון כשיר, כדי לבדוק את מסלול-החישוב עצמו (ולא את הסינון)."""
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        acct = Account(organization_id=org_id, name="בנק", account_type=AccountType.BANK,
                       balance=Decimal("10000"), source="open_finance",
                       balance_as_of=datetime.utcnow())
        db.add(acct); db.flush()
        db.add(BankTransaction(organization_id=org_id, transaction_date=TODAY - timedelta(days=1),
                                description="הפקדה", amount=Decimal("1000")))
        db.add(BankTransaction(organization_id=org_id, transaction_date=TODAY,
                                description="חיוב", amount=Decimal("-300")))
        db.commit()

        result = LiveCashFlowService(db, org_id).daily_cash_position(days=1, as_of_date=TODAY)
    finally:
        db.close()

    assert result["balance_basis"] == "account_balance"
    assert len(result["days"]) == 2
    d_prev, d_cur = result["days"]
    assert d_prev["date"] == (TODAY - timedelta(days=1)).isoformat()
    assert d_prev["inflows"] == 1000.0
    assert d_cur["date"] == TODAY.isoformat()
    assert d_cur["outflows"] == 300.0
    # היתרה החיה של היום היא העוגן ליום האחרון בחלון.
    assert d_cur["closing_balance"] == 10000.0
    # מהלך אחורה: אתמול = היום - נטו-היום = 10000 - (-300) = 10300.
    assert d_prev["closing_balance"] == 10300.0


def test_daily_cash_position_no_live_balance_omits_closing_balance(fresh_org):
    """אין Account כשיר (BANK ממקור Open Finance עם חותמת-זמן טרייה) =>
    אין יתרה חיה. closing_balance=None, לא נפילה חזרה לסכימת Transaction
    (זו בדיוק הטבלה הקפואה)."""
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        db.add(BankTransaction(organization_id=org_id, transaction_date=TODAY,
                                description="חיוב", amount=Decimal("-50")))
        db.commit()

        result = LiveCashFlowService(db, org_id).daily_cash_position(days=0, as_of_date=TODAY)
    finally:
        db.close()

    assert result["balance_basis"] == "unavailable"
    assert result["days"][0]["closing_balance"] is None
    assert result["days"][0]["outflows"] == 50.0
    assert result["balance_reason"]
    assert "אין" in result["balance_reason"]


def test_daily_cash_position_asset_account_does_not_supply_closing_balance(fresh_org):
    """תיקון-ביקורת 23/08/2026 (P0-B, ממצא 1): _live_cash_balance סיכם עד
    כה גם ASSET (חסכונות/נכסים ידניים) — חוזה המזומן דורש BANK+OF בלבד.
    חשבון ASSET יחיד לא אמור לספק עוגן ליתרת סגירה."""
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        db.add(Account(organization_id=org_id, name="נכס", account_type=AccountType.ASSET,
                        balance=Decimal("999999"), source="open_finance",
                        balance_as_of=datetime.utcnow()))
        db.add(BankTransaction(organization_id=org_id, transaction_date=TODAY,
                                description="חיוב", amount=Decimal("-50")))
        db.commit()

        result = LiveCashFlowService(db, org_id).daily_cash_position(days=0, as_of_date=TODAY)
    finally:
        db.close()

    assert result["balance_basis"] == "unavailable"
    assert result["days"][0]["closing_balance"] is None


def test_daily_cash_position_honest_null_for_empty_org(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        result = LiveCashFlowService(db, org_id).daily_cash_position(days=5, as_of_date=TODAY)
    finally:
        db.close()

    assert result["days"] == []
    assert result["data_sources"] == []
    assert result["message"]


# --------------------------------------------------------------------- #
# burn_rate
# --------------------------------------------------------------------- #
def test_burn_rate_uses_bank_transactions_and_live_balance(fresh_org):
    """חוזה המזומן (P0-B): 'יתרה חיה' דורשת BANK ממקור Open Finance +
    חותמת-זמן טרייה — הפיקסצ'ורה כאן מייצגת בכוונה חשבון כשיר."""
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        acct = Account(organization_id=org_id, name="בנק", account_type=AccountType.BANK,
                       balance=Decimal("30000"), source="open_finance",
                       balance_as_of=datetime.utcnow())
        db.add(acct); db.flush()
        db.add(BankTransaction(organization_id=org_id, transaction_date=TODAY - timedelta(days=10),
                                description="הכנסה", amount=Decimal("9000")))
        db.add(BankTransaction(organization_id=org_id, transaction_date=TODAY - timedelta(days=5),
                                description="הוצאה", amount=Decimal("-3000")))
        db.commit()

        result = LiveCashFlowService(db, org_id).burn_rate(months=3, as_of_date=TODAY)
    finally:
        db.close()

    assert result["as_of"] == TODAY.isoformat()
    assert "bank_transactions_actual" in result["data_sources"]
    assert result["current_balance"] == 30000.0
    assert result["current_balance_available"] is True
    assert result["current_balance_reason"] is None
    assert result["monthly_income"] == round(9000 / 3, 2)
    assert result["monthly_burn_rate"] == round(3000 / 3, 2)
    assert result["net_monthly_burn"] == round(1000 - 3000, 2)  # burn < income => negative net burn
    # honest-null (P0-B): net_burn<=0 עם יתרה ידועה חיובית הוא runway
    # אינסופי *אמיתי*, לא סנטינל — אבל runway_months נשאר None (לא מספר
    # מומצא), וה-status מבחין מפורשות בין "אינסופי" ל"לא ידוע".
    assert result["runway_months"] is None
    assert result["runway_status"] == "infinite"
    assert result["runway_reason"]
    assert result["message"] is None


def test_burn_rate_surfaces_expected_ar_ap_within_30_days(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        customer = Contact(organization_id=org_id, name="לקוח", contact_type=ContactType.CUSTOMER)
        vendor = Contact(organization_id=org_id, name="ספק", contact_type=ContactType.VENDOR)
        db.add_all([customer, vendor]); db.flush()

        db.add(Invoice(
            organization_id=org_id, contact_id=customer.id, invoice_number="INV-30D",
            subtotal=Decimal("1200"), tax=Decimal("0"), total=Decimal("1200"),
            balance=Decimal("1200"), status=InvoiceStatus.SENT,
            issue_date=TODAY, due_date=TODAY + timedelta(days=15),
        ))
        # מחוץ לחלון 30 הימים — לא אמור להיכלל.
        db.add(Invoice(
            organization_id=org_id, contact_id=customer.id, invoice_number="INV-FAR",
            subtotal=Decimal("500"), tax=Decimal("0"), total=Decimal("500"),
            balance=Decimal("500"), status=InvoiceStatus.SENT,
            issue_date=TODAY, due_date=TODAY + timedelta(days=45),
        ))
        db.add(Bill(
            organization_id=org_id, vendor_id=vendor.id, bill_number="BILL-30D",
            subtotal=Decimal("400"), tax=Decimal("0"), total=Decimal("400"),
            balance=Decimal("400"), status=BillStatus.RECEIVED,
            issue_date=TODAY, due_date=TODAY + timedelta(days=10),
        ))
        db.commit()

        result = LiveCashFlowService(db, org_id).burn_rate(months=3, as_of_date=TODAY)
    finally:
        db.close()

    assert result["expected_receivables_30d"] == 1200.0
    assert result["expected_receivables_30d_count"] == 1
    assert result["expected_payables_30d"] == 400.0
    assert result["expected_payables_30d_count"] == 1
    assert "invoices_open_ar" in result["data_sources"]
    assert "bills_open_ap" in result["data_sources"]


def test_burn_rate_honest_null_message_when_totally_empty(fresh_org):
    """P0-B: אין יותר סנטינל 999.0 — ארגון ריק לגמרי מקבל runway_months=None
    + runway_status="unavailable" + reason, לא מספר-כאילו-סופי."""
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        result = LiveCashFlowService(db, org_id).burn_rate(months=3, as_of_date=TODAY)
    finally:
        db.close()

    assert result["runway_months"] is None
    assert result["runway_status"] == "unavailable"
    assert result["runway_reason"]
    assert result["current_balance"] is None
    assert result["data_sources"] == []
    assert result["message"]
    assert result["current_balance_available"] is False
    assert result["current_balance_reason"]


def test_burn_rate_asset_account_not_counted_as_cash(fresh_org):
    """תיקון-ביקורת 23/08/2026 (P0-B, ממצא 1): חשבון ASSET (חסכונות/נכס
    ידני) לא נספר כמזומן — גם אם הוא ה-Account היחיד בארגון, current_balance
    נשאר None (honest-null), לא סכום-ASSET מוצג כ'מזומן'."""
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        db.add(Account(organization_id=org_id, name="חסכון", account_type=AccountType.ASSET,
                        balance=Decimal("500000"), source="open_finance",
                        balance_as_of=datetime.utcnow()))
        db.add(BankTransaction(organization_id=org_id, transaction_date=TODAY - timedelta(days=5),
                                description="הוצאה", amount=Decimal("-1000")))
        db.commit()

        result = LiveCashFlowService(db, org_id).burn_rate(months=3, as_of_date=TODAY)
    finally:
        db.close()

    assert result["current_balance"] is None
    assert result["current_balance_available"] is False
    assert result["runway_months"] is None
    assert result["runway_status"] == "unavailable"


def test_burn_rate_manual_source_bank_account_not_counted_as_cash(fresh_org):
    """BANK אבל לא ממקור Open Finance (SUMIT-מסונתז/ידני) — לא נספר
    כ'מזומן חי' (אין מקור-אמת חיצוני שמאמת את היתרה)."""
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        db.add(Account(organization_id=org_id, name="בנק ידני", account_type=AccountType.BANK,
                        balance=Decimal("20000"), source="manual",
                        balance_as_of=datetime.utcnow()))
        db.commit()

        result = LiveCashFlowService(db, org_id).burn_rate(months=3, as_of_date=TODAY)
    finally:
        db.close()

    assert result["current_balance"] is None
    assert result["current_balance_available"] is False


def test_burn_rate_stale_of_balance_not_counted_as_cash(fresh_org):
    """יתרת OF/BANK קיימת אבל ישנה מ-48 שעות — לא 'עכשיו', לא נספרת."""
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        db.add(Account(organization_id=org_id, name="בנק", account_type=AccountType.BANK,
                        balance=Decimal("20000"), source="open_finance",
                        balance_as_of=datetime.utcnow() - timedelta(hours=72)))
        db.commit()

        result = LiveCashFlowService(db, org_id).burn_rate(months=3, as_of_date=TODAY)
    finally:
        db.close()

    assert result["current_balance"] is None
    assert result["current_balance_available"] is False
    assert result["current_balance_reason"]
    assert "טרי" in result["current_balance_reason"] or "48" in result["current_balance_reason"]


def test_burn_rate_missing_balance_timestamp_not_counted_as_cash(fresh_org):
    """OF/BANK בלי שום חותמת-זמן (balance_as_of/synced_at/observed_at) —
    אי-אפשר לדעת אם היא טרייה, אז לא נספרת (לא ברירת-מחדל אופטימית)."""
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        db.add(Account(organization_id=org_id, name="בנק", account_type=AccountType.BANK,
                        balance=Decimal("20000"), source="open_finance"))
        db.commit()

        result = LiveCashFlowService(db, org_id).burn_rate(months=3, as_of_date=TODAY)
    finally:
        db.close()

    assert result["current_balance"] is None
    assert result["current_balance_available"] is False


def test_burn_rate_accepts_fresh_sync_when_balance_as_of_is_missing(fresh_org):
    """כש-referenceDate חסר אך החשבון עודכן בסנכרון טרי, synced_at מעיד
    שהיתרה עצמה הגיעה באותה פעימת sync ולכן מותר להשתמש בה. observed_at
    אינו fallback לטריות יתרה."""
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        db.add(Account(
            organization_id=org_id,
            name="בנק ללא referenceDate",
            account_type=AccountType.BANK,
            balance=Decimal("20000"),
            source="open_finance",
            balance_as_of=None,
            synced_at=datetime.utcnow(),
        ))
        db.commit()

        result = LiveCashFlowService(db, org_id).burn_rate(months=3, as_of_date=TODAY)
    finally:
        db.close()

    assert result["current_balance"] == 20000.0
    assert result["current_balance_available"] is True
    assert result["current_balance_reason"] is None


def test_burn_rate_observed_at_alone_does_not_make_balance_fresh(fresh_org):
    """observed_at מתאר תצפית כללית ברשומה ולא מוכיח שהיתרה סונכרנה."""
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        db.add(Account(
            organization_id=org_id,
            name="בנק עם observed_at בלבד",
            account_type=AccountType.BANK,
            balance=Decimal("20000"),
            source="open_finance",
            balance_as_of=None,
            synced_at=None,
            observed_at=datetime.utcnow(),
        ))
        db.commit()

        result = LiveCashFlowService(db, org_id).burn_rate(months=3, as_of_date=TODAY)
    finally:
        db.close()

    assert result["current_balance"] is None
    assert result["current_balance_available"] is False
    assert "observed_at בלבד" in result["current_balance_reason"]


def test_burn_rate_mixed_fresh_and_stale_balances_fails_closed(fresh_org):
    """שני חשבונות OF/BANK: אחד טרי ואחד ישן. ברמת הארגון אסור להציג
    את החשבון הטרי כסכום מלא; כל היתרה נסגרת ל-null וה-reason מזהה את
    החשבון שנפסל."""
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        db.add(Account(organization_id=org_id, name="בנק טרי", account_type=AccountType.BANK,
                        balance=Decimal("1000"), source="open_finance",
                        balance_as_of=datetime.utcnow()))
        db.add(Account(organization_id=org_id, name="בנק ישן", account_type=AccountType.BANK,
                        balance=Decimal("500000"), source="open_finance",
                        balance_as_of=datetime.utcnow() - timedelta(hours=72)))
        db.commit()

        result = LiveCashFlowService(db, org_id).burn_rate(months=3, as_of_date=TODAY)
    finally:
        db.close()

    assert result["current_balance"] is None
    assert result["current_balance_available"] is False
    assert result["current_balance_reason"]
    assert "בנק ישן" in result["current_balance_reason"]


def test_burn_rate_not_positive_runway_when_burning_with_nonpositive_balance(fresh_org):
    """שורפים מזומן נטו (הוצאות > הכנסות) אבל היתרה החיה הידועה אינה
    חיובית — runway_status='not_positive', לא 'infinite' ולא מספר שלילי."""
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        db.add(Account(organization_id=org_id, name="בנק", account_type=AccountType.BANK,
                        balance=Decimal("0"), source="open_finance",
                        balance_as_of=datetime.utcnow()))
        db.add(BankTransaction(organization_id=org_id, transaction_date=TODAY - timedelta(days=5),
                                description="הוצאה", amount=Decimal("-3000")))
        db.commit()

        result = LiveCashFlowService(db, org_id).burn_rate(months=3, as_of_date=TODAY)
    finally:
        db.close()

    assert result["net_monthly_burn"] > 0
    assert result["current_balance"] == 0.0
    assert result["runway_months"] is None
    assert result["runway_status"] == "not_positive"
    assert result["runway_reason"]


def test_burn_rate_negative_balance_is_not_infinite_when_net_burn_is_nonpositive(fresh_org):
    """יתרה שלילית לעולם אינה runway אינסופי, גם כשההכנסות בתקופה עולות
    על ההוצאות וה-net burn אינו חיובי."""
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        db.add(Account(
            organization_id=org_id,
            name="בנק במינוס",
            account_type=AccountType.BANK,
            balance=Decimal("-100"),
            source="open_finance",
            balance_as_of=datetime.utcnow(),
        ))
        db.add(BankTransaction(
            organization_id=org_id,
            transaction_date=TODAY - timedelta(days=5),
            description="הכנסה",
            amount=Decimal("3000"),
        ))
        db.commit()

        result = LiveCashFlowService(db, org_id).burn_rate(months=3, as_of_date=TODAY)
    finally:
        db.close()

    assert result["net_monthly_burn"] <= 0
    assert result["current_balance"] == -100.0
    assert result["runway_months"] is None
    assert result["runway_status"] == "not_positive"
    assert "אינה חיובית" in result["runway_reason"]


def test_burn_rate_computed_runway_when_burning_with_positive_balance(fresh_org):
    """המקרה הרגיל: שורפים מזומן נטו, יש יתרה חיה חיובית — runway_months
    מחושב בפועל, לא None ולא סנטינל."""
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        db.add(Account(organization_id=org_id, name="בנק", account_type=AccountType.BANK,
                        balance=Decimal("9000"), source="open_finance",
                        balance_as_of=datetime.utcnow()))
        db.add(BankTransaction(organization_id=org_id, transaction_date=TODAY - timedelta(days=5),
                                description="הוצאה", amount=Decimal("-3000")))
        db.commit()

        result = LiveCashFlowService(db, org_id).burn_rate(months=3, as_of_date=TODAY)
    finally:
        db.close()

    assert result["net_monthly_burn"] == round(3000 / 3, 2)
    assert result["runway_status"] == "computed"
    assert result["runway_months"] == round(9000 / (3000 / 3), 2)
    assert result["runway_reason"] is None


# --------------------------------------------------------------------- #
# by_category
# --------------------------------------------------------------------- #
def test_by_category_groups_real_categories_when_coverage_is_strong(fresh_org):
    """כשרוב התנועות בחלון מסווגות (categorized_share >= הסף) — הפירוק
    מוצג בביטחון מלא, message=None."""
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        cat = Category(organization_id=org_id, name="שכירות", category_type="expense")
        db.add(cat); db.flush()
        db.add(BankTransaction(organization_id=org_id, transaction_date=TODAY,
                                description="שכ״ד 1", amount=Decimal("-2000"), category_id=cat.id))
        db.add(BankTransaction(organization_id=org_id, transaction_date=TODAY,
                                description="שכ״ד 2", amount=Decimal("-500"), category_id=cat.id))
        db.add(BankTransaction(organization_id=org_id, transaction_date=TODAY,
                                description="לא מסווג", amount=Decimal("500")))
        db.commit()

        result = LiveCashFlowService(db, org_id).by_category(
            start_date=TODAY - timedelta(days=1), end_date=TODAY, as_of_date=TODAY,
        )
    finally:
        db.close()

    assert result["data_sources"] == ["bank_transactions_actual"]
    assert result["categories"]["שכירות"]["outflows"] == 2500.0
    assert result["categories"]["לא מסווג"]["inflows"] == 500.0
    assert result["coverage"] == {
        "categorized_count": 2, "total_count": 3, "categorized_share": round(2 / 3, 4),
    }
    assert result["message"] is None


def test_by_category_discloses_partial_coverage_when_uncategorized_dominates(fresh_org):
    """הממצא מהביקורת (21/08/2026): מיעוט תנועות מסווגות מול רוב "לא
    מסווג" חייב לא להיראות כמו פירוק מלא ואמין. הפירוק עדיין מוצג (נתון
    אמיתי, לא מוסתר) — אבל עם הודעת-כיסוי מפורשת, לא message=None."""
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        cat = Category(organization_id=org_id, name="שכירות", category_type="expense")
        db.add(cat); db.flush()
        db.add(BankTransaction(organization_id=org_id, transaction_date=TODAY,
                                description="שכ״ד", amount=Decimal("-2000"), category_id=cat.id))
        for i in range(3):
            db.add(BankTransaction(organization_id=org_id, transaction_date=TODAY,
                                    description=f"לא מסווג {i}", amount=Decimal("100")))
        db.commit()

        result = LiveCashFlowService(db, org_id).by_category(
            start_date=TODAY - timedelta(days=1), end_date=TODAY, as_of_date=TODAY,
        )
    finally:
        db.close()

    # הנתון האמיתי עדיין מוצג — לא מוחבא מאחורי honest-null ריק.
    assert result["categories"]["שכירות"]["outflows"] == 2000.0
    assert result["categories"]["לא מסווג"]["inflows"] == 300.0
    assert result["coverage"] == {
        "categorized_count": 1, "total_count": 4, "categorized_share": 0.25,
    }
    assert result["message"]
    assert "1 מתוך 4" in result["message"]


def test_by_category_honest_null_when_uncategorized(fresh_org):
    """BankTransaction.category_id כמעט אף פעם לא מאוכלס בפועל — הודעה
    כנה, לא עוגה שקרית של פרוסה אחת."""
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        db.add(BankTransaction(organization_id=org_id, transaction_date=TODAY,
                                description="x", amount=Decimal("100")))
        db.commit()

        result = LiveCashFlowService(db, org_id).by_category(
            start_date=TODAY, end_date=TODAY, as_of_date=TODAY,
        )
    finally:
        db.close()

    assert result["categories"] == {}
    assert result["coverage"] == {"categorized_count": 0, "total_count": 1, "categorized_share": 0.0}
    assert result["message"]


def test_by_category_honest_null_for_empty_window(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        result = LiveCashFlowService(db, org_id).by_category(
            start_date=TODAY, end_date=TODAY, as_of_date=TODAY,
        )
    finally:
        db.close()

    assert result["categories"] == {}
    assert result["message"]


# --------------------------------------------------------------------- #
# routes: GET /api/cashflow/monthly, /daily, /burn-rate, /by-category
# --------------------------------------------------------------------- #
def test_cashflow_monthly_route_returns_live_shape(client, fresh_org):
    org = fresh_org()
    db = SessionLocal()
    try:
        db.add(BankTransaction(organization_id=org["org_id"], transaction_date=TODAY,
                                description="x", amount=Decimal("777")))
        db.commit()
    finally:
        db.close()

    r = client.get("/api/cashflow/monthly?months=1", headers=org["headers"])
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["as_of"] == TODAY.isoformat()
    assert body["months"][0]["inflows"] == 777.0


def test_cashflow_daily_route_org_isolation(client, fresh_org):
    org_a = fresh_org()
    org_b = fresh_org()
    db = SessionLocal()
    try:
        db.add(BankTransaction(organization_id=org_a["org_id"], transaction_date=TODAY,
                                description="x", amount=Decimal("321")))
        db.commit()
    finally:
        db.close()

    r_a = client.get("/api/cashflow/daily?days=1", headers=org_a["headers"])
    r_b = client.get("/api/cashflow/daily?days=1", headers=org_b["headers"])
    assert "321" not in r_b.text
    assert r_a.json()["days"][-1]["inflows"] == 321.0
    assert r_b.json()["days"] == []


def test_cashflow_burn_rate_route_carries_runway_fields_over_http(client, fresh_org):
    """אין response_model קשיח על /burn-rate — בלי אסרשן מפורש כאן, שדה
    חדש (runway_status/runway_reason/current_balance_reason) שנשמט היה
    עובר בשקט (P0-B, בעקבות המלצת-הביקורת לבדוק את גבול ה-HTTP במפורש)."""
    org = fresh_org()
    r = client.get("/api/cashflow/burn-rate", headers=org["headers"])
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["runway_months"] is None
    assert body["runway_status"] == "unavailable"
    assert body["runway_reason"]
    assert body["current_balance"] is None
    assert body["current_balance_reason"]


def test_cashflow_by_category_route_honest_null_empty_org(client, fresh_org):
    org = fresh_org()
    r = client.get(
        f"/api/cashflow/by-category?start_date={TODAY.isoformat()}&end_date={TODAY.isoformat()}",
        headers=org["headers"],
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["categories"] == {}
    assert body["message"]
