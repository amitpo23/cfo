"""LiveForecastService — תחזית תזרים חודשית מבוססת ספרים חיים (Invoice/Bill/
Expense פתוחים), לא טבלת Transaction הקפואה (127 שורות ₪0, קפואה מ-19/08).

פירוק גלוי (intermediate-sums): כל חודש = צבר in/out + שורת מקור לכל רכיב.
אין ML — סכימה ישירה. honest-null כשאין נתונים חיים.
"""
from datetime import date, timedelta
from decimal import Decimal

from cfo.database import SessionLocal
from cfo.models import (
    BankTransaction, Bill, BillStatus, Contact, ContactType, Expense, Invoice, InvoiceStatus,
)
from cfo.services.live_forecast_service import LiveForecastService

TODAY = date.today()
MONTH_START = TODAY.replace(day=1)


def _next_month(d: date, months: int = 1) -> date:
    idx = d.month - 1 + months
    return date(d.year + idx // 12, idx % 12 + 1, 1)


def test_monthly_forecast_decomposes_ar_ap_and_recurring_expenses(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        customer = Contact(organization_id=org_id, name="לקוח", contact_type=ContactType.CUSTOMER)
        vendor = Contact(organization_id=org_id, name="ספק", contact_type=ContactType.VENDOR)
        db.add_all([customer, vendor]); db.flush()

        # AR פתוח: חשבונית לחודש הנוכחי, וחשבונית לחודש הבא.
        db.add(Invoice(
            organization_id=org_id, contact_id=customer.id, invoice_number="INV-1",
            subtotal=Decimal("1000"), tax=Decimal("0"), total=Decimal("1000"),
            balance=Decimal("1000"), status=InvoiceStatus.SENT,
            issue_date=TODAY, due_date=MONTH_START + timedelta(days=5),
        ))
        db.add(Invoice(
            organization_id=org_id, contact_id=customer.id, invoice_number="INV-2",
            subtotal=Decimal("500"), tax=Decimal("0"), total=Decimal("500"),
            balance=Decimal("500"), status=InvoiceStatus.OVERDUE,
            issue_date=TODAY, due_date=_next_month(MONTH_START, 1) + timedelta(days=2),
        ))
        # חשבונית סגורה (balance=0) — לא אמורה להיכלל.
        db.add(Invoice(
            organization_id=org_id, contact_id=customer.id, invoice_number="INV-PAID",
            subtotal=Decimal("999"), tax=Decimal("0"), total=Decimal("999"),
            balance=Decimal("0"), status=InvoiceStatus.PAID,
            issue_date=TODAY, due_date=MONTH_START + timedelta(days=3),
        ))

        # AP פתוח: חשבון ספק לחודש הנוכחי.
        db.add(Bill(
            organization_id=org_id, vendor_id=vendor.id, bill_number="BILL-1",
            subtotal=Decimal("300"), tax=Decimal("0"), total=Decimal("300"),
            balance=Decimal("300"), status=BillStatus.RECEIVED,
            issue_date=TODAY, due_date=MONTH_START + timedelta(days=10),
        ))

        # הוצאות חוזרות: שני חודשים שונים ב-90 הימים האחרונים.
        db.add(Expense(
            organization_id=org_id, supplier_name="ספק חוזר",
            amount=Decimal("600"), total=Decimal("600"),
            expense_date=TODAY - timedelta(days=20),
        ))
        db.add(Expense(
            organization_id=org_id, supplier_name="ספק חוזר",
            amount=Decimal("900"), total=Decimal("900"),
            expense_date=TODAY - timedelta(days=50),
        ))
        db.commit()

        result = LiveForecastService(db, org_id).monthly_forecast(periods=3, as_of_date=TODAY)
    finally:
        db.close()

    assert result["as_of"] == TODAY.isoformat()
    assert result["message"] is None
    assert set(result["data_sources"]) == {"invoices_open_ar", "bills_open_ap", "expenses_recurring_avg"}
    assert len(result["months"]) == 3

    recurring_avg = (600 + 900) / 2  # שני חודשים נפרדים עם נתונים -> ממוצע, לא סכום.

    m0, m1, m2 = result["months"]
    assert m0["month"] == MONTH_START.strftime("%Y-%m")
    assert m0["inflow_total"] == 1000.0
    assert m0["outflow_total"] == round(300 + recurring_avg, 2)
    assert m0["net_flow"] == round(1000 - (300 + recurring_avg), 2)

    assert m1["month"] == _next_month(MONTH_START, 1).strftime("%Y-%m")
    assert m1["inflow_total"] == 500.0
    assert m1["outflow_total"] == round(recurring_avg, 2)

    assert m2["inflow_total"] == 0.0
    assert m2["outflow_total"] == round(recurring_avg, 2)

    # שורות-מקור גלויות לחודש הראשון.
    by_source = {c["source"]: c for c in m0["components"]}
    assert by_source["invoices_open_ar"]["amount"] == 1000.0
    assert by_source["invoices_open_ar"]["count"] == 1
    assert by_source["bills_open_ap"]["amount"] == 300.0
    assert by_source["bills_open_ap"]["count"] == 1
    assert by_source["expenses_recurring_avg"]["amount"] == round(recurring_avg, 2)
    assert by_source["expenses_recurring_avg"]["count"] == 2


def test_monthly_forecast_honest_null_for_empty_org(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        result = LiveForecastService(db, org_id).monthly_forecast(periods=6, as_of_date=TODAY)
    finally:
        db.close()

    assert result["as_of"] == TODAY.isoformat()
    assert result["data_sources"] == []
    assert result["months"] == []
    assert result["message"]
    assert "אין נתונים" in result["message"]


def test_monthly_forecast_org_isolation(fresh_org):
    org_a = fresh_org()["org_id"]
    org_b = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        customer = Contact(organization_id=org_a, name="לקוח א", contact_type=ContactType.CUSTOMER)
        db.add(customer); db.flush()
        db.add(Invoice(
            organization_id=org_a, contact_id=customer.id, invoice_number="INV-A",
            subtotal=Decimal("1000"), tax=Decimal("0"), total=Decimal("1000"),
            balance=Decimal("1000"), status=InvoiceStatus.SENT,
            issue_date=TODAY, due_date=MONTH_START + timedelta(days=5),
        ))
        db.commit()

        result_a = LiveForecastService(db, org_a).monthly_forecast(periods=1, as_of_date=TODAY)
        result_b = LiveForecastService(db, org_b).monthly_forecast(periods=1, as_of_date=TODAY)
    finally:
        db.close()

    assert result_a["months"][0]["inflow_total"] == 1000.0
    # org_b לא רואה את הנתונים של org_a — honest-null, לא זליגה.
    assert result_b["months"] == []
    assert result_b["message"]


def test_monthly_forecast_expense_deduped_against_matching_bill_external_id(fresh_org):
    """הוצאה עם external_id שכבר קיים כ-Bill לא נספרת פעמיים בבסיס החוזר."""
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        vendor = Contact(organization_id=org_id, name="ספק", contact_type=ContactType.VENDOR)
        db.add(vendor); db.flush()
        db.add(Bill(
            organization_id=org_id, vendor_id=vendor.id, bill_number="BILL-DUP",
            external_id="EXT-1",
            subtotal=Decimal("300"), tax=Decimal("0"), total=Decimal("300"),
            balance=Decimal("300"), status=BillStatus.RECEIVED,
            issue_date=TODAY, due_date=MONTH_START + timedelta(days=10),
        ))
        # אותו מסמך, גם כהוצאה — לא אמור להצטרף לבסיס החוזר.
        db.add(Expense(
            organization_id=org_id, supplier_name="ספק", external_id="EXT-1",
            amount=Decimal("300"), total=Decimal("300"),
            expense_date=TODAY - timedelta(days=5),
        ))
        db.commit()

        result = LiveForecastService(db, org_id).monthly_forecast(periods=1, as_of_date=TODAY)
    finally:
        db.close()

    assert "expenses_recurring_avg" not in result["data_sources"]
    by_source = {c["source"]: c for c in result["months"][0]["components"]}
    assert by_source["expenses_recurring_avg"]["amount"] == 0.0
    assert by_source["expenses_recurring_avg"]["count"] == 0


def test_monthly_forecast_excludes_failed_expenses_from_recurring_baseline(fresh_org):
    """הוצאה עם status='error' (OCR/סיווג כושל) לא אמורה לזהם את בסיס
    ההוצאות החוזרות — אותו פילטר בדיוק כמו
    DashboardService._month_expenses_accrual (func.lower(status)!='error')."""
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        db.add(Expense(
            organization_id=org_id, supplier_name="ספק תקין",
            amount=Decimal("500"), total=Decimal("500"), status="pending",
            expense_date=TODAY - timedelta(days=10),
        ))
        db.add(Expense(
            organization_id=org_id, supplier_name="ספק כושל",
            amount=Decimal("9999"), total=Decimal("9999"), status="error",
            expense_date=TODAY - timedelta(days=15),
        ))
        db.commit()

        result = LiveForecastService(db, org_id).monthly_forecast(periods=1, as_of_date=TODAY)
    finally:
        db.close()

    by_source = {c["source"]: c for c in result["months"][0]["components"]}
    # רק ההוצאה התקינה (500) נכללת; ה-9999 הכושלת מודרת לגמרי — גם
    # מהסכום וגם ממונה החודשים (חודש יחיד עם נתונים -> ממוצע = 500).
    assert by_source["expenses_recurring_avg"]["amount"] == 500.0
    assert by_source["expenses_recurring_avg"]["count"] == 1


def test_monthly_forecast_overdue_ar_and_ap_are_not_dropped(fresh_org):
    """באג שנמצא בסקירה: חשבונית/חשבון-ספק שה-due_date שלהם כבר עבר (לפני
    תחילת חלון התחזית) לא התאימו לאף בקצת-חודש ונעלמו בשקט — 'אפסים
    בביטחון' עם תג מקור-נתונים חי מעליהם. הם חייבים להופיע כרכיב overdue
    נפרד בחודש הראשון, ולהיכלל בצבר inflow/outflow שלו."""
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        customer = Contact(organization_id=org_id, name="לקוח", contact_type=ContactType.CUSTOMER)
        vendor = Contact(organization_id=org_id, name="ספק", contact_type=ContactType.VENDOR)
        db.add_all([customer, vendor]); db.flush()

        db.add(Invoice(
            organization_id=org_id, contact_id=customer.id, invoice_number="INV-OVERDUE",
            subtotal=Decimal("2000"), tax=Decimal("0"), total=Decimal("2000"),
            balance=Decimal("2000"), status=InvoiceStatus.OVERDUE,
            issue_date=TODAY - timedelta(days=60), due_date=MONTH_START - timedelta(days=40),
        ))
        db.add(Bill(
            organization_id=org_id, vendor_id=vendor.id, bill_number="BILL-OVERDUE",
            subtotal=Decimal("800"), tax=Decimal("0"), total=Decimal("800"),
            balance=Decimal("800"), status=BillStatus.OVERDUE,
            issue_date=TODAY - timedelta(days=50), due_date=MONTH_START - timedelta(days=20),
        ))
        db.commit()

        result = LiveForecastService(db, org_id).monthly_forecast(periods=2, as_of_date=TODAY)
    finally:
        db.close()

    assert "invoices_overdue_ar" in result["data_sources"]
    assert "bills_overdue_ap" in result["data_sources"]

    m0, m1 = result["months"]
    assert m0["inflow_total"] == 2000.0
    assert m0["outflow_total"] == 800.0
    by_source0 = {c["source"]: c for c in m0["components"]}
    assert by_source0["invoices_overdue_ar"]["amount"] == 2000.0
    assert by_source0["invoices_overdue_ar"]["count"] == 1
    assert by_source0["bills_overdue_ap"]["amount"] == 800.0

    # החודש השני לא סוחב את ה-overdue שוב (זה כבר "טופל" בחודש הראשון).
    by_source1 = {c["source"]: c for c in m1["components"]}
    assert by_source1["invoices_overdue_ar"]["amount"] == 0.0
    assert m1["inflow_total"] == 0.0


def test_monthly_forecast_ar_invariant_across_months_including_overdue(fresh_org):
    """שער-נגד-רגרסיה: סכום כל רכיבי ה-AR (open + overdue) על פני כל
    החודשים המוחזרים = סך יתרת ה-AR הפתוחה עם due_date בתוך החלון (כולל
    overdue). שום שקל לא נעלם בשקט בין הבקצות."""
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        customer = Contact(organization_id=org_id, name="לקוח", contact_type=ContactType.CUSTOMER)
        db.add(customer); db.flush()
        db.add(Invoice(
            organization_id=org_id, contact_id=customer.id, invoice_number="INV-OVERDUE",
            subtotal=Decimal("300"), tax=Decimal("0"), total=Decimal("300"),
            balance=Decimal("300"), status=InvoiceStatus.OVERDUE,
            issue_date=TODAY - timedelta(days=60), due_date=MONTH_START - timedelta(days=10),
        ))
        db.add(Invoice(
            organization_id=org_id, contact_id=customer.id, invoice_number="INV-CUR",
            subtotal=Decimal("400"), tax=Decimal("0"), total=Decimal("400"),
            balance=Decimal("400"), status=InvoiceStatus.SENT,
            issue_date=TODAY, due_date=MONTH_START + timedelta(days=5),
        ))
        db.add(Invoice(
            organization_id=org_id, contact_id=customer.id, invoice_number="INV-NEXT",
            subtotal=Decimal("500"), tax=Decimal("0"), total=Decimal("500"),
            balance=Decimal("500"), status=InvoiceStatus.SENT,
            issue_date=TODAY, due_date=_next_month(MONTH_START, 1) + timedelta(days=2),
        ))
        db.commit()

        result = LiveForecastService(db, org_id).monthly_forecast(periods=2, as_of_date=TODAY)
    finally:
        db.close()

    total_ar_across_months = sum(
        sum(c["amount"] for c in m["components"] if c["source"] in ("invoices_open_ar", "invoices_overdue_ar"))
        for m in result["months"]
    )
    # 300 (overdue) + 400 (חודש נוכחי) + 500 (חודש הבא) — כולן בתוך חלון 2
    # החודשים המוחזר, אף שקל לא נעלם.
    assert total_ar_across_months == 1200.0


def test_bank_actual_context_surfaces_when_only_bank_data_present(fresh_org):
    """ארגון בלי AR/AP/הוצאות אבל עם תנועות בנק אמיתיות לא אמור לקבל
    honest-null 'שקרי' שמסתיר את היסטוריית הבנק — הוא כן מוחזר, בנפרד
    מהתחזית-קדימה (months נשאר [], כי אין בסיס תחזית-קדימה אחראי)."""
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        db.add(BankTransaction(
            organization_id=org_id, transaction_date=TODAY - timedelta(days=10),
            description="הפקדה", amount=Decimal("5000"),
        ))
        db.add(BankTransaction(
            organization_id=org_id, transaction_date=TODAY - timedelta(days=5),
            description="חיוב", amount=Decimal("-1200"),
        ))
        db.commit()

        result = LiveForecastService(db, org_id).monthly_forecast(periods=3, as_of_date=TODAY)
    finally:
        db.close()

    assert result["months"] == []  # אין AR/AP/הוצאות -> אין תחזית-קדימה אחראית.
    assert result["data_sources"] == ["bank_transactions_actual"]
    assert result["message"]
    ctx = result["historical_context"]
    assert ctx["available"] is True
    assert ctx["inflow"] == 5000.0
    assert ctx["outflow"] == 1200.0
    assert ctx["net"] == 3800.0
    assert ctx["count"] == 2


# --------------------------------------------------------------------- #
# route: GET /api/cashflow/forecast/live-monthly
# --------------------------------------------------------------------- #
def test_live_monthly_forecast_route_requires_auth(client):
    r = client.get("/api/cashflow/forecast/live-monthly")
    assert r.status_code == 403


def test_live_monthly_forecast_route_returns_expected_shape(client, fresh_org):
    org = fresh_org()
    db = SessionLocal()
    try:
        customer = Contact(organization_id=org["org_id"], name="לקוח", contact_type=ContactType.CUSTOMER)
        db.add(customer); db.flush()
        db.add(Invoice(
            organization_id=org["org_id"], contact_id=customer.id, invoice_number="INV-ROUTE",
            subtotal=Decimal("750"), tax=Decimal("0"), total=Decimal("750"),
            balance=Decimal("750"), status=InvoiceStatus.SENT,
            issue_date=TODAY, due_date=MONTH_START + timedelta(days=5),
        ))
        db.commit()
    finally:
        db.close()

    r = client.get("/api/cashflow/forecast/live-monthly?periods=2", headers=org["headers"])
    assert r.status_code == 200
    body = r.json()
    assert body["as_of"] == TODAY.isoformat()
    assert "invoices_open_ar" in body["data_sources"]
    assert len(body["months"]) == 2
    assert body["months"][0]["inflow_total"] == 750.0
    assert body["message"] is None


def test_live_monthly_forecast_route_honest_null_for_empty_org(client, fresh_org):
    org = fresh_org()
    r = client.get("/api/cashflow/forecast/live-monthly", headers=org["headers"])
    assert r.status_code == 200
    body = r.json()
    assert body["months"] == []
    assert body["data_sources"] == []
    assert body["message"]
