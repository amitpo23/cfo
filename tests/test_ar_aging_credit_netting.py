"""get_ar_aging מדווח יתרה גולמית — זיכוי ללא-שיוך (Invoice עם total
שלילי, balance=0 במכוון) לא נספר כחוב בפני עצמו, אבל גם לא מפחית מהיתרה
הכוללת. ר' test_financial_statements_reconcile.py (18-19/08/2026):
פער מוסבר ומתועד, לא תוקן במכוון בגלל חוסר ודאות בהקצאה לדלג ספציפי —
אין בנתונים קישור בין זיכוי לחשבונית שהוא מקזז, אז אין דרך אמינה לדעת
לאיזה דלג (0-30/31-60/...) מקזזים אותו בלי לנחש.

**התיקון (19/08/2026):** לא לנחש הקצאה לדלג — להוסיף שדה נטו נפרד
ברמת סה"כ, כך שגם התצוגה הגולמית (buckets, ללא שינוי) וגם החשיפה
האמיתית-נטו זמינות, בלי לבחור עבור המשתמש דלג שהמידע לא תומך בו.
"""
from datetime import date, timedelta
from decimal import Decimal

import pytest

from cfo.database import SessionLocal
from cfo.models import Contact, ContactType, Invoice, InvoiceStatus
from cfo.services.dashboard_service import DashboardService

TODAY = date.today()


def test_unapplied_credit_is_surfaced_but_not_allocated_to_a_bucket(fresh_org):
    db = SessionLocal()
    org_id = fresh_org()["org_id"]
    customer = Contact(organization_id=org_id, name="לקוח בדיקה", contact_type=ContactType.CUSTOMER)
    db.add(customer); db.flush()

    db.add(Invoice(
        organization_id=org_id, contact_id=customer.id, invoice_number="INV-OPEN",
        subtotal=Decimal("10000"), tax=Decimal("0"), total=Decimal("10000"),
        balance=Decimal("10000"), status=InvoiceStatus.SENT,
        issue_date=TODAY - timedelta(days=70), due_date=TODAY - timedelta(days=40),
    ))
    db.add(Invoice(
        organization_id=org_id, contact_id=customer.id, invoice_number="INV-CREDIT",
        subtotal=Decimal("-1500"), tax=Decimal("0"), total=Decimal("-1500"),
        balance=Decimal("0"), status=InvoiceStatus.SENT,
        issue_date=TODAY - timedelta(days=10),
    ))
    db.commit()

    aging = DashboardService(db, org_id).get_ar_aging()

    # הגולמי לא זז — אי-אפשר לדעת לאיזה דלג הזיכוי שייך.
    assert aging["total"] == 10000.0
    assert aging["bucket_31_60"] == 10000.0

    # אבל החשיפה האמיתית-נטו כן זמינה, בלי הקצאה.
    assert aging["unapplied_credits_total"] == 1500.0
    assert aging["net_of_credits_total"] == 8500.0


def test_no_credits_means_net_equals_gross(fresh_org):
    db = SessionLocal()
    org_id = fresh_org()["org_id"]
    customer = Contact(organization_id=org_id, name="לקוח בדיקה 2", contact_type=ContactType.CUSTOMER)
    db.add(customer); db.flush()
    db.add(Invoice(
        organization_id=org_id, contact_id=customer.id, invoice_number="INV-A",
        subtotal=Decimal("2000"), tax=Decimal("0"), total=Decimal("2000"),
        balance=Decimal("2000"), status=InvoiceStatus.SENT,
        issue_date=TODAY - timedelta(days=10), due_date=TODAY - timedelta(days=1),
    ))
    db.commit()

    aging = DashboardService(db, org_id).get_ar_aging()

    assert aging["unapplied_credits_total"] == 0.0
    assert aging["net_of_credits_total"] == aging["total"] == 2000.0
