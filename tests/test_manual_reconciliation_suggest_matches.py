"""suggest_matches — הממצא (24-25/08/2026, שתי בדיקות-ארכיטקטורה עצמאיות
מצאו את זה בנפרד): `pool = invoices + bills + expenses` ב-
manual_reconciliation.py:175 מפנה למשתנים שלא מוגדרים בפונקציה כלל —
NameError מובטח בכל קריאה. אפס טסטים קיימים לפונקציה הזו — בדיוק למה
זה שרד בפרוד בלי שאף אחד ישים לב.
"""
from datetime import date, timedelta
from decimal import Decimal

from cfo.database import SessionLocal
from cfo.models import Bill, BillStatus, Contact, ContactType, Expense, Invoice, InvoiceStatus
from cfo.services.manual_reconciliation import ManualReconciliationService

TODAY = date.today()


def _mk_txn(db, org_id, *, amount, days_ago=0, description="עסקה"):
    from cfo.models import BankTransaction
    txn = BankTransaction(
        organization_id=org_id, amount=Decimal(str(amount)),
        transaction_date=TODAY - timedelta(days=days_ago), description=description,
    )
    db.add(txn)
    db.flush()
    return txn


def test_suggest_matches_does_not_crash_and_returns_candidates(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        customer = Contact(organization_id=org_id, name="לקוח בדיקה", contact_type=ContactType.CUSTOMER)
        db.add(customer); db.flush()
        db.add(Invoice(
            organization_id=org_id, contact_id=customer.id, invoice_number="INV-1",
            subtotal=Decimal("1000"), tax=Decimal("0"), total=Decimal("1000"),
            balance=Decimal("1000"), status=InvoiceStatus.SENT,
            issue_date=TODAY - timedelta(days=3),
        ))
        txn = _mk_txn(db, org_id, amount=1000, days_ago=1)
        db.commit()

        service = ManualReconciliationService(db, org_id)
        candidates = service.suggest_matches(txn.id)

        assert isinstance(candidates, list)
        assert len(candidates) == 1
        assert candidates[0]["entity_type"] == "invoice"
        assert candidates[0]["score"] > 0
    finally:
        db.close()


def test_suggest_matches_considers_bills_and_expenses_too(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        vendor = Contact(organization_id=org_id, name="ספק בדיקה", contact_type=ContactType.VENDOR)
        db.add(vendor); db.flush()
        db.add(Bill(
            organization_id=org_id, vendor_id=vendor.id, bill_number="B-1",
            subtotal=Decimal("500"), tax=Decimal("0"), total=Decimal("500"),
            balance=Decimal("500"), status=BillStatus.RECEIVED,
            issue_date=TODAY - timedelta(days=2),
        ))
        db.add(Expense(
            organization_id=org_id, supplier_name="ספק ב", expense_date=TODAY - timedelta(days=2),
            amount=Decimal("200"), vat_amount=Decimal("0"), total=Decimal("200"),
        ))
        txn_bill = _mk_txn(db, org_id, amount=-500, days_ago=1)
        db.commit()

        service = ManualReconciliationService(db, org_id)
        candidates = service.suggest_matches(txn_bill.id)

        assert any(c["entity_type"] == "bill" for c in candidates)
    finally:
        db.close()


def test_suggest_matches_returns_empty_for_unknown_transaction(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        service = ManualReconciliationService(db, org_id)
        assert service.suggest_matches(999999) == []
    finally:
        db.close()


def test_suggest_matches_is_org_scoped(fresh_org):
    org_a = fresh_org()["org_id"]
    org_b = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        customer = Contact(organization_id=org_b, name="לקוח ב", contact_type=ContactType.CUSTOMER)
        db.add(customer); db.flush()
        db.add(Invoice(
            organization_id=org_b, contact_id=customer.id, invoice_number="INV-B",
            subtotal=Decimal("1000"), tax=Decimal("0"), total=Decimal("1000"),
            balance=Decimal("1000"), status=InvoiceStatus.SENT,
            issue_date=TODAY - timedelta(days=3),
        ))
        txn = _mk_txn(db, org_a, amount=1000, days_ago=1)
        db.commit()

        service = ManualReconciliationService(db, org_a)
        candidates = service.suggest_matches(txn.id)

        assert candidates == [], "חשבונית מארגון אחר לא אמורה להיות מועמדת"
    finally:
        db.close()
