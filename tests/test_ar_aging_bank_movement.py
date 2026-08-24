"""get_ar_aging — הפער שנמצא ב-24/08/2026, ע"י אתגור ישיר של הבעלים
("למה אתה אומר באיחור — בדקת שנפדו בבנק?"): 10 מ-25 החשבוניות "הפתוחות"
של org2 כבר היו לתנועת בנק מותאמת (is_reconciled=True, bank_reconciliation.py)
— ₪479,260 מתוך ₪1,625,162, כמעט 30%. get_ap_aging כבר קיבל את הדגל הזה
ב-18/08 ("חשבון ספק פתוח עם תנועת בנק תואמת"); get_ar_aging — הכיוון
ההפוך, לקוח — מעולם לא קיבל אותו. אותו מנוע קריאה בדיוק, בלי כתיבה.
"""
from datetime import date, timedelta
from decimal import Decimal

import pytest

from cfo.database import SessionLocal
from cfo.models import BankTransaction, Contact, ContactType, Invoice, InvoiceStatus
from cfo.services.dashboard_service import DashboardService

TODAY = date.today()


def test_an_invoice_with_a_matched_bank_transaction_is_flagged(fresh_org):
    db = SessionLocal()
    org_id = fresh_org()["org_id"]
    customer = Contact(organization_id=org_id, name="לקוח בדיקה", contact_type=ContactType.CUSTOMER)
    db.add(customer); db.flush()
    inv = Invoice(
        organization_id=org_id, contact_id=customer.id, invoice_number="INV-BANK",
        subtotal=Decimal("10000"), tax=Decimal("0"), total=Decimal("10000"),
        balance=Decimal("10000"), status=InvoiceStatus.SENT,
        issue_date=TODAY - timedelta(days=40), due_date=TODAY - timedelta(days=10),
    )
    db.add(inv); db.flush()
    db.add(BankTransaction(
        organization_id=org_id, amount=Decimal("10000"),
        transaction_date=TODAY - timedelta(days=3),
        is_reconciled=True, matched_entity_type="invoice", matched_entity_id=inv.id,
    ))
    db.commit()

    aging = DashboardService(db, org_id).get_ar_aging()
    flagged = next(i for i in aging["invoices"] if i["id"] == inv.id)

    assert flagged["bank_movement_seen"] is True
    assert aging["bank_movement_seen_total"] == 10000.0


def test_an_invoice_without_any_bank_transaction_is_not_flagged(fresh_org):
    db = SessionLocal()
    org_id = fresh_org()["org_id"]
    customer = Contact(organization_id=org_id, name="לקוח בדיקה 2", contact_type=ContactType.CUSTOMER)
    db.add(customer); db.flush()
    inv = Invoice(
        organization_id=org_id, contact_id=customer.id, invoice_number="INV-NOBANK",
        subtotal=Decimal("5000"), tax=Decimal("0"), total=Decimal("5000"),
        balance=Decimal("5000"), status=InvoiceStatus.OVERDUE,
        issue_date=TODAY - timedelta(days=100), due_date=TODAY - timedelta(days=70),
    )
    db.add(inv); db.commit()

    aging = DashboardService(db, org_id).get_ar_aging()
    flagged = next(i for i in aging["invoices"] if i["id"] == inv.id)

    assert flagged["bank_movement_seen"] is False
    assert aging["bank_movement_seen_total"] == 0.0
