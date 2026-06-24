"""פאזה 1 — דוחות פיננסיים חייבים להישען על שכבת ה-ledger (Invoice/Bill/Expense)
עם סכומי נטו מפוצלי-מע"מ, ולא על טבלת Transaction המנופחת (כולל מע"מ).

מקור אמת אחד: הכנסה=subtotal של חשבונית, הוצאה=subtotal של ספק + amount של הוצאה,
מע"מ=שדות tax/vat_amount האמיתיים (כמו financial_synthesis.compute_vat_position).
"""
from datetime import date

import pytest

from cfo.services.financial_reports_service import FinancialReportsService


@pytest.fixture
def seeded_ledger(fresh_org):
    """org מבודד עם חשבונית, ספק והוצאה בערכים ידועים (נטו+מע"מ מפוצל)."""
    from cfo.database import SessionLocal
    from cfo.models import (
        Contact, ContactType, Invoice, InvoiceStatus, Bill, BillStatus, Expense,
    )

    org = fresh_org()
    org_id = org["org_id"]
    db = SessionLocal()
    try:
        customer = Contact(organization_id=org_id, contact_type=ContactType.CUSTOMER,
                           name="לקוח ידוע בעמ", tax_id="555555550")
        vendor = Contact(organization_id=org_id, contact_type=ContactType.VENDOR,
                         name="ספק ידוע בעמ", tax_id="123456782")
        db.add_all([customer, vendor])
        db.flush()

        # חשבונית הכנסה: נטו 1000 + מע"מ 180 = ברוטו 1180
        invoice = Invoice(
            organization_id=org_id, contact_id=customer.id,
            invoice_number="INV-NET-1", issue_date=date(2026, 3, 15),
            due_date=date(2026, 4, 15),
            subtotal=1000, tax=180, total=1180,
            paid_amount=0, balance=1180, status=InvoiceStatus.SENT,
        )
        # ספק: נטו 400 + מע"מ 72 = ברוטו 472
        bill = Bill(
            organization_id=org_id, vendor_id=vendor.id,
            bill_number="BILL-NET-1", issue_date=date(2026, 3, 10),
            due_date=date(2026, 4, 10),
            subtotal=400, tax=72, total=472,
            paid_amount=0, balance=472, status=BillStatus.APPROVED,
        )
        # הוצאה: נטו 200 + מע"מ 36 = ברוטו 236
        expense = Expense(
            organization_id=org_id, supplier_name="ספק הוצאה",
            amount=200, vat_amount=36, total=236,
            expense_date=date(2026, 3, 20), status="filed",
        )
        db.add_all([invoice, bill, expense])
        db.commit()
        return {"org_id": org_id, "db_factory": SessionLocal}
    finally:
        db.close()


def _pl(seeded):
    db = seeded["db_factory"]()
    try:
        return FinancialReportsService(db).generate_profit_loss(
            organization_id=seeded["org_id"],
            start_date=date(2026, 3, 1),
            end_date=date(2026, 3, 31),
            compare_previous=False,
        )
    finally:
        db.close()


def test_profit_loss_revenue_is_net_from_ledger(seeded_ledger):
    """ההכנסה בדוח רווח והפסד = נטו (subtotal=1000), לא ברוטו (1180) ולא 0."""
    assert _pl(seeded_ledger).total_revenue == 1000.0


def test_profit_loss_expenses_are_net_from_ledger(seeded_ledger):
    """ההוצאה = נטו ספק (400) + נטו הוצאה (200) = 600, לא ברוטו ולא 0."""
    assert _pl(seeded_ledger).total_expenses == 600.0


def test_profit_loss_includes_manual_journal_entries(seeded_ledger):
    """פקודת יומן ידנית (Transaction בלי מסמך מקור) נכללת בדוח ואינה נאבדת."""
    from cfo.database import SessionLocal
    from cfo.models import Transaction, TransactionType, Account, AccountType

    db = SessionLocal()
    try:
        org_id = seeded_ledger["org_id"]
        acc = Account(organization_id=org_id, name="Manual", account_type=AccountType.REVENUE,
                      balance=0)
        db.add(acc)
        db.flush()
        # תנועת הכנסה ידנית 500, בלי external_id (לא הד-מסמך)
        db.add(Transaction(
            organization_id=org_id, account_id=acc.id,
            transaction_type=TransactionType.INCOME, amount=500,
            description="פקודת יומן ידנית", category="other_income",
            transaction_date=date(2026, 3, 25),
        ))
        db.commit()
    finally:
        db.close()

    # הכנסה כוללת = 1000 (חשבונית) + 500 (ידני) = 1500
    assert _pl(seeded_ledger).total_revenue == 1500.0


def test_profit_loss_does_not_double_count_document_echo_transactions(seeded_ledger):
    """באג org1: מסמך שנכתב גם כ-Expense וגם כ-Transaction (אותו external_id)
    נספר פעם אחת בלבד — לא כפול."""
    from cfo.database import SessionLocal
    from cfo.models import Transaction, TransactionType, Account, AccountType, Expense

    db = SessionLocal()
    try:
        org_id = seeded_ledger["org_id"]
        # external_id של ההוצאה הקיימת? אין לה. ניצור הוצאה עם external_id מפורש,
        # ואז Transaction-הד שמחקה אותה.
        exp = Expense(organization_id=org_id, supplier_name="ספק כפול",
                      amount=300, vat_amount=54, total=354,
                      expense_date=date(2026, 3, 12), status="filed",
                      external_id="ECHO-1")
        db.add(exp)
        acc = Account(organization_id=org_id, name="Echo", account_type=AccountType.EXPENSE, balance=0)
        db.add(acc)
        db.flush()
        db.add(Transaction(  # הד-מסמך — אותו external_id
            organization_id=org_id, account_id=acc.id,
            transaction_type=TransactionType.EXPENSE, amount=354,
            description="הד של ECHO-1", category="other",
            transaction_date=date(2026, 3, 12), external_id="ECHO-1",
        ))
        db.commit()
    finally:
        db.close()

    # הוצאות = 400 (ספק) + 200 (הוצאה מקורית) + 300 (הוצאה כפולה, נטו) = 900.
    # ה-Transaction ההד (354) לא נספר שוב.
    assert _pl(seeded_ledger).total_expenses == 900.0


def test_vat_report_uses_real_tax_fields_not_18pct_estimate(seeded_ledger):
    """דוח המע"מ נשען על שדות tax אמיתיים מה-ledger, לא על אומדן 18% מ-Transaction.

    מקור אמת אחד עם compute_vat_position: עסק חייב 180 (חשבונית), תשומות 108 (72+36).
    """
    from cfo.services.tax_service import TaxComplianceService

    db = seeded_ledger["db_factory"]()
    try:
        svc = TaxComplianceService(db, organization_id=seeded_ledger["org_id"])
        report = svc.generate_vat_report(2026, 3)
        assert report.output_vat == 180.0
        assert report.total_input_vat == 108.0
        assert report.net_vat == 72.0
    finally:
        db.close()


def test_balance_sheet_retained_earnings_is_net_income_not_plug(seeded_ledger):
    """עודפים נגזרים מרווח נקי מצטבר (חישוב עצמאי), לא plug שמכריח is_balanced.

    רווח נקי = הכנסה 1000 − הוצאה 600 = 400 לפני מס; אחרי מס 23% → 308.
    """
    from datetime import date as _date

    db = seeded_ledger["db_factory"]()
    try:
        svc = FinancialReportsService(db)
        bs = svc.generate_balance_sheet(
            organization_id=seeded_ledger["org_id"],
            as_of_date=_date(2026, 3, 31),
            compare_previous=False,
        )
        retained = next(e.amount for e in bs.equity if e.name == "retained_earnings")
        assert round(retained, 2) == 308.0
    finally:
        db.close()
