"""פאזה 2 — תקציב מול ביצוע חייב לשקף תנועות אמיתיות, לא נתוני random.

באג ראשון (תוקן קודם): _get_actual_by_category השתמש ב-Transaction.date (שדה
לא קיים) → זרק AttributeError → נפל ל-_get_sample_actuals (random) עבור כל
ארגון. כלומר "תקציב מול ביצוע" היה 100% מזויף. התיקון הראשון: שדה נכון +
הסרת ה-fallback האקראי השקט.

באג שני, החמור בפועל (19/08/2026): גם אחרי התיקון הראשון, `Transaction` הוא
**הצינור הקפוא** — ר' `LegacySyncRetiredError` ב-data_sync_service.py:
שום קוד חי לא כותב אליו יותר מאז המעבר ל-SyncEngine (Invoice/Bill/Expense).
כלומר "תקציב מול ביצוע" היה ריק (honest-null אבל חסר תועלת) לכל ארגון אמיתי,
לנצח — לא מזויף, אבל גם לא נכון: יש הוצאות אמיתיות ב-Bill/Expense שלא נספרות.
התיקון: המקור עבר ל-`ledger_service.build_journal` — אותם ספרים נגזרים
ששאר המערכת (מאזן בוחן, כרטיס לקוח, Moshko) כבר סומכת עליהם, כולל אותה
דה-דופליקציה חשבון/הוצאה שהוכחה ותוקנה ב-test_bill_expense_double_count.py.
"""
from datetime import date

import pytest

from cfo.services.budget_service import BudgetService


@pytest.fixture
def org_factory(fresh_org):
    return fresh_org


def test_actuals_reflect_real_bills_and_expenses(org_factory):
    """המקור האמיתי: Bill (חשבון ספק) + Expense עצמאית + Invoice (הכנסה)."""
    from cfo.database import SessionLocal
    from cfo.models import Bill, BillStatus, Expense, Invoice, InvoiceStatus, Contact

    org = org_factory()
    org_id = org["org_id"]
    db = SessionLocal()
    try:
        vendor = Contact(organization_id=org_id, name="חברת שיווק בע\"מ", contact_type="vendor")
        db.add(vendor); db.flush()
        db.add(Bill(
            organization_id=org_id, external_id="BILL-1", source="sumit",
            vendor_id=vendor.id, bill_number="1", issue_date=date(2026, 4, 5),
            subtotal=1000.0, tax=170.0, status=BillStatus.RECEIVED,
        ))
        db.add(Expense(
            organization_id=org_id, external_id="EXP-1", source="sumit",
            supplier_name="בזק", category="utilities",
            expense_date=date(2026, 4, 10), amount=300.0, vat_amount=51.0,
        ))
        db.add(Invoice(
            organization_id=org_id, external_id="INV-1", source="sumit",
            invoice_number="1", issue_date=date(2026, 4, 15),
            subtotal=5000.0, tax=850.0, balance=5850.0,
            status=InvoiceStatus.SENT,
        ))
        db.commit()
    finally:
        db.close()

    db = SessionLocal()
    try:
        svc = BudgetService(db, organization_id=org_id)
        actuals = svc._get_actual_by_category(date(2026, 4, 1), date(2026, 5, 1))
        assert actuals.get("sales") == 5000.0
        assert actuals.get("utilities") == 300.0
        # הבחון מסווג לפי שם ספק/מספר — "שיווק" בשם החברה → marketing
        assert actuals.get("marketing") == 1000.0
    finally:
        db.close()


def test_actuals_empty_when_nothing_posted_not_random(org_factory):
    """ללא מסמכים בתקופה — מחזיר {} (לא נתוני random מ-_get_sample_actuals)."""
    from cfo.database import SessionLocal

    org = org_factory()
    db = SessionLocal()
    try:
        svc = BudgetService(db, organization_id=org["org_id"])
        actuals = svc._get_actual_by_category(date(2026, 4, 1), date(2026, 5, 1))
        assert actuals == {}
    finally:
        db.close()


def test_transaction_table_is_never_read_the_pipe_is_frozen(org_factory):
    """שער נגדי: Transaction הוא הצינור הקפוא. אפילו אם יש בו שורות (זבל
    היסטורי, ר' client_automation_service.py), הן לא רשאיות להיספר —
    אחרת חזרנו למקור הנתונים שהוכח מת."""
    from cfo.database import SessionLocal
    from cfo.models import Transaction, TransactionType, Account, AccountType

    org = org_factory()
    org_id = org["org_id"]
    db = SessionLocal()
    try:
        acc = Account(organization_id=org_id, name="בנק", account_type=AccountType.BANK, balance=0)
        db.add(acc); db.flush()
        db.add(Transaction(organization_id=org_id, account_id=acc.id,
                           transaction_type=TransactionType.INCOME, amount=99999,
                           description="שורת זבל היסטורית", category="sales",
                           transaction_date=date(2026, 4, 10)))
        db.commit()
    finally:
        db.close()

    db = SessionLocal()
    try:
        svc = BudgetService(db, organization_id=org_id)
        actuals = svc._get_actual_by_category(date(2026, 4, 1), date(2026, 5, 1))
        assert actuals == {}, "Transaction נקרא — הצינור הקפוא הוחזר לפעילות"
    finally:
        db.close()


def test_the_shared_document_is_not_double_counted_in_actuals(org_factory):
    """אותו מזהה חיצוני ב-Bill וב-Expense — נספר פעם אחת (החשבון גובר),
    בדיוק כמו ב-ledger_service.build_journal."""
    from cfo.database import SessionLocal
    from cfo.models import Bill, BillStatus, Expense

    org = org_factory()
    org_id = org["org_id"]
    db = SessionLocal()
    try:
        db.add(Bill(
            organization_id=org_id, external_id="SUMIT-DOC-777", source="sumit",
            bill_number="777", issue_date=date(2026, 4, 3),
            subtotal=1000.0, tax=170.0, status=BillStatus.RECEIVED,
        ))
        db.add(Expense(
            organization_id=org_id, external_id="SUMIT-DOC-777", source="sumit",
            supplier_name="ספק בדיקה", expense_date=date(2026, 4, 3),
            amount=1000.0, vat_amount=170.0,
        ))
        db.commit()
    finally:
        db.close()

    db = SessionLocal()
    try:
        svc = BudgetService(db, organization_id=org_id)
        actuals = svc._get_actual_by_category(date(2026, 4, 1), date(2026, 5, 1))
        total = sum(actuals.values())
        assert total == 1000.0, f"סה\"כ={total} — 2000 פירושו שהמסמך המשותף נספר פעמיים"
    finally:
        db.close()
