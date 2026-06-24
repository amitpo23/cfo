"""פאזה 2 — תחזית תזרים נשענת על מסמכי ledger (ברוטו = תנועת מזומן בפועל),
לא על טבלת Transaction הריקה לארגוני ledger, וללא רעש אקראי מלאכותי.
"""
from datetime import date, timedelta

import pytest

from cfo.services.financial_reports_service import FinancialReportsService


@pytest.fixture
def ledger_cash_org(fresh_org):
    from cfo.database import SessionLocal
    from cfo.models import (
        Contact, ContactType, Invoice, InvoiceStatus, Expense,
    )

    org = fresh_org()
    org_id = org["org_id"]
    recent = date.today() - timedelta(days=40)  # בתוך חלון 180 הימים
    db = SessionLocal()
    try:
        cust = Contact(organization_id=org_id, contact_type=ContactType.CUSTOMER, name="לקוח")
        db.add(cust); db.flush()
        # חשבונית ברוטו 1180 (נטו 1000 + מע"מ 180)
        db.add(Invoice(organization_id=org_id, contact_id=cust.id, invoice_number="CF-1",
                       issue_date=recent, due_date=recent,
                       subtotal=1000, tax=180, total=1180, paid_amount=0, balance=1180,
                       status=InvoiceStatus.SENT))
        # הוצאה ברוטו 236
        db.add(Expense(organization_id=org_id, supplier_name="ספק",
                       amount=200, vat_amount=36, total=236,
                       expense_date=recent, status="filed"))
        db.commit()
        return {"org_id": org_id}
    finally:
        db.close()


def test_cashflow_historical_inflows_from_ledger_gross(ledger_cash_org):
    """ממוצע היסטורי של כניסות = ברוטו החשבונית (1180), לא 0."""
    from cfo.database import SessionLocal
    db = SessionLocal()
    try:
        rep = FinancialReportsService(db).generate_cash_flow_projection(
            organization_id=ledger_cash_org["org_id"], months=3, opening_balance=0
        )
        assert rep.historical_average_inflows == 1180.0
        assert rep.historical_average_outflows == 236.0
    finally:
        db.close()


def test_cashflow_projection_is_deterministic_no_random(ledger_cash_org):
    """אותה קלט → אותה תחזית בדיוק (ללא רעש אקראי)."""
    from cfo.database import SessionLocal
    db = SessionLocal()
    try:
        svc = FinancialReportsService(db)
        a = svc.generate_cash_flow_projection(ledger_cash_org["org_id"], months=3, opening_balance=0)
        b = svc.generate_cash_flow_projection(ledger_cash_org["org_id"], months=3, opening_balance=0)
        assert [p.inflows for p in a.projections] == [p.inflows for p in b.projections]
        # ללא רעש: כניסה חזויה = ממוצע היסטורי × עונתיות; עבור חודש בלי עונתיות = 1180
        assert any(p.inflows == 1180.0 for p in a.projections)
    finally:
        db.close()
