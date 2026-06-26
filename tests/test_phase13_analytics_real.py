"""פאזה 13A/13B — revenue_analytics + expense_analytics חייבים לרוץ על הסכמה
האמיתית (total/contact_id/supplier_id), לא לקרוס על עמודות לא-קיימות.
המתודות שאין להן תשתית בסכמה (revenue by category/region) מחזירות 'unsupported'
מפורש במקום לקרוס.
"""
from datetime import date, datetime, timezone
from decimal import Decimal

from cfo.database import SessionLocal
from cfo.models import Contact, ContactType, Expense, Invoice, InvoiceStatus
from cfo.services.expense_analytics import ExpenseAnalyticsService
from cfo.services.revenue_analytics import RevenueAnalyticsService


def _seed_customer_invoices(org_id):
    db = SessionLocal()
    try:
        c = Contact(organization_id=org_id, name="לקוח א", contact_type=ContactType.CUSTOMER)
        db.add(c)
        db.flush()
        now = datetime.now(timezone.utc)
        db.add_all([
            Invoice(organization_id=org_id, contact_id=c.id, total=Decimal("1000"),
                    paid_amount=Decimal("1000"), status=InvoiceStatus.PAID, created_at=now),
            Invoice(organization_id=org_id, contact_id=c.id, total=Decimal("1000"),
                    paid_amount=Decimal("0"), status=InvoiceStatus.SENT, created_at=now),
        ])
        db.commit()
        return c.id
    finally:
        db.close()


def _seed_supplier_expenses(org_id):
    db = SessionLocal()
    try:
        s = Contact(organization_id=org_id, name="ספק ב", contact_type=ContactType.VENDOR)
        db.add(s)
        db.flush()
        today = date.today()
        db.add_all([
            Expense(organization_id=org_id, supplier_id=s.id, supplier_name="ספק ב",
                    category="rent", total=Decimal("500"), expense_date=today, status="filed"),
            Expense(organization_id=org_id, supplier_id=s.id, supplier_name="ספק ב",
                    category="rent", total=Decimal("500"), expense_date=today, status="filed"),
        ])
        db.commit()
        return s.id
    finally:
        db.close()


# ==================== Revenue Analytics ====================

def test_revenue_summary_derives_from_invoices(fresh_org):
    org_id = fresh_org()["org_id"]
    _seed_customer_invoices(org_id)
    db = SessionLocal()
    try:
        summary = RevenueAnalyticsService(db, org_id).get_revenue_summary(days=30)
    finally:
        db.close()
    assert summary["total_invoiced"] == 2000.0
    assert summary["total_paid"] == 1000.0
    assert summary["invoice_count"] == 2


def test_revenue_by_customer_uses_contact_join(fresh_org):
    org_id = fresh_org()["org_id"]
    _seed_customer_invoices(org_id)
    db = SessionLocal()
    try:
        rows = RevenueAnalyticsService(db, org_id).analyze_revenue_by_customer(days=90)
    finally:
        db.close()
    assert len(rows) == 1
    assert rows[0]["total_revenue"] == 2000.0
    assert rows[0]["customer_name"] == "לקוח א"


def test_revenue_by_category_reports_unsupported(fresh_org):
    """ל-Invoice אין עמודת category — חייב להחזיר 'unsupported', לא לקרוס."""
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        result = RevenueAnalyticsService(db, org_id).analyze_revenue_by_category(days=90)
    finally:
        db.close()
    assert result["status"] == "unsupported"


def test_revenue_by_region_reports_unsupported(fresh_org):
    """ל-Contact אין שדות גאוגרפיים — חייב להחזיר 'unsupported', לא לקרוס."""
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        result = RevenueAnalyticsService(db, org_id).analyze_revenue_by_region(days=90)
    finally:
        db.close()
    assert result["status"] == "unsupported"


def test_investment_opportunities_runs_without_crash(fresh_org):
    org_id = fresh_org()["org_id"]
    _seed_customer_invoices(org_id)
    db = SessionLocal()
    try:
        result = RevenueAnalyticsService(db, org_id).identify_investment_opportunities(days=90)
    finally:
        db.close()
    assert isinstance(result, list)


# ==================== Expense Analytics ====================

def test_expense_summary_derives_from_expenses(fresh_org):
    org_id = fresh_org()["org_id"]
    _seed_supplier_expenses(org_id)
    db = SessionLocal()
    try:
        summary = ExpenseAnalyticsService(db, org_id).get_expense_summary(days=30)
    finally:
        db.close()
    assert summary["total_expenses"] == 1000.0
    assert summary["expense_count"] == 2
    assert summary["unique_vendors"] == 1


def test_vendor_spending_uses_supplier_join(fresh_org):
    org_id = fresh_org()["org_id"]
    _seed_supplier_expenses(org_id)
    db = SessionLocal()
    try:
        rows = ExpenseAnalyticsService(db, org_id).analyze_vendor_spending(days=30)
    finally:
        db.close()
    assert len(rows) == 1
    assert rows[0]["total_amount"] == 1000.0
    assert rows[0]["vendor_name"] == "ספק ב"


def test_category_spending_and_optimization_run(fresh_org):
    org_id = fresh_org()["org_id"]
    _seed_supplier_expenses(org_id)
    db = SessionLocal()
    try:
        svc = ExpenseAnalyticsService(db, org_id)
        cats = svc.analyze_category_spending(days=30)
        opt = svc.get_cost_optimization_opportunities()
    finally:
        db.close()
    assert any(c["category"] == "rent" and c["total_amount"] == 1000.0 for c in cats)
    assert isinstance(opt, list)
