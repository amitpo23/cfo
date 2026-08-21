"""משימה 2 — מסך המאזן (`/api/reports/balance-sheet`, ReportsDashboard.tsx
"מאזן") עבר ממקור Transaction הקפואה (~127 שורות ₪0, קפואה מ-19/08/2026)
למנוע ledger_service הנגזר מפקודות היומן (חשבוניות/חשבונות-ספק/הוצאות
מסונכרנים) — אותו מנוע כמו /api/ledger/balance-sheet, לא מנוע מקביל.
"""
from datetime import date

from cfo.database import SessionLocal
from cfo.models import (
    Account, AccountType, Bill, BillStatus, Contact, ContactType, Invoice,
    InvoiceStatus, JournalEntry, Transaction, TransactionType,
)
from cfo.services.financial_reports_service import FinancialReportsService

AS_OF = date(2026, 3, 31)


def _seed_invoice_and_bill(db, org_id):
    customer = Contact(organization_id=org_id, contact_type=ContactType.CUSTOMER,
                       name="לקוח", tax_id="555555550")
    vendor = Contact(organization_id=org_id, contact_type=ContactType.VENDOR,
                     name="ספק", tax_id="123456782")
    db.add_all([customer, vendor]); db.flush()
    # נטו 1000 + מע"מ 180 => DR 1100 (לקוחות) 1180, CR 4000 1000, CR 2200 180.
    db.add(Invoice(
        organization_id=org_id, contact_id=customer.id, invoice_number="INV-BS-1",
        issue_date=date(2026, 3, 15), due_date=date(2026, 4, 15),
        subtotal=1000, tax=180, total=1180, paid_amount=0, balance=1180,
        status=InvoiceStatus.SENT,
    ))
    # נטו 400 + מע"מ 72 => DR 5000 400, DR 1300 72, CR 2100 (ספקים) 472.
    db.add(Bill(
        organization_id=org_id, vendor_id=vendor.id, bill_number="BILL-BS-1",
        issue_date=date(2026, 3, 10), due_date=date(2026, 4, 10),
        subtotal=400, tax=72, total=472, paid_amount=0, balance=472,
        status=BillStatus.APPROVED,
    ))
    db.commit()


def test_balance_sheet_current_assets_come_from_ledger_not_frozen_transaction(fresh_org):
    """נכס AR (1100) = 1180 (subtotal+tax, זהות הרישום הכפול) — לא 0, ולא
    מושפע משורת Transaction בודדת/מנותקת שאינה חלק מזרם המסמכים."""
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _seed_invoice_and_bill(db, org_id)
        # שורת Transaction ענקית ומנותקת — היתה קודם המקור היחיד למאזן.
        # אם היא עדיין משפיעה על הפלט, המעבר למנוע ה-ledger לא הושלם.
        acc = Account(organization_id=org_id, name="Legacy", account_type=AccountType.ASSET, balance=0)
        db.add(acc); db.flush()
        db.add(Transaction(
            organization_id=org_id, account_id=acc.id,
            transaction_type=TransactionType.INCOME, amount=999999,
            description="שורת Transaction קפואה מנותקת", category="other",
            transaction_date=date(2026, 3, 20),
        ))
        db.commit()

        svc = FinancialReportsService(db)
        bs = svc.generate_balance_sheet(org_id, as_of_date=AS_OF, compare_previous=False)
    finally:
        db.close()

    ar_item = next(a for a in bs.current_assets if a.name == "1100")
    assert ar_item.amount == 1180.0
    assert 999999 not in [a.amount for a in bs.current_assets]
    assert bs.total_assets < 999999


def test_balance_sheet_is_balanced_by_construction(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _seed_invoice_and_bill(db, org_id)
        svc = FinancialReportsService(db)
        bs = svc.generate_balance_sheet(org_id, as_of_date=AS_OF, compare_previous=False)
    finally:
        db.close()

    assert bs.is_balanced is True
    assert round(bs.total_assets, 2) == round(bs.total_liabilities_and_equity, 2)


def test_balance_sheet_org_isolation(fresh_org):
    org_a = fresh_org()["org_id"]
    org_b = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _seed_invoice_and_bill(db, org_a)
        svc = FinancialReportsService(db)
        bs_a = svc.generate_balance_sheet(org_a, as_of_date=AS_OF, compare_previous=False)
        bs_b = svc.generate_balance_sheet(org_b, as_of_date=AS_OF, compare_previous=False)
    finally:
        db.close()

    assert bs_a.total_assets > 0
    assert bs_b.total_assets == 0.0
    assert bs_b.current_assets == []


def test_balance_sheet_empty_org_is_honest_null_not_fabricated(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        svc = FinancialReportsService(db)
        bs = svc.generate_balance_sheet(org_id, as_of_date=AS_OF, compare_previous=False)
    finally:
        db.close()

    assert bs.current_assets == []
    assert bs.current_liabilities == []
    assert bs.fixed_assets == []
    assert bs.other_assets == []
    assert bs.long_term_liabilities == []
    assert bs.total_assets == 0.0


def test_balance_sheet_surfaces_imported_entries_warning(fresh_org):
    """פקודות מיובאות מהנה"ח חיצונית (חשבשבת) — הכרעת הבעלים 17/08/2026:
    אזהרה מפורשת חייבת להופיע כשהמאזן כולל אותן, אחרת יש סיכון לדיווח
    כפול על תקופה שכבר דווחה. ledger_service.balance_sheet() עצמו לא
    חושף את הדגל — הוא נמשך פה במפורש מ-trial_balance."""
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        db.add(JournalEntry(
            organization_id=org_id, source="hashavshevet_mdb",
            external_id="imp-bs-1", entry_date=date(2026, 3, 5),
            memo="יבוא חשבשבת",
            lines=[
                {"account": "5100", "debit": 500.0, "credit": 0.0, "description": "הוצאה"},
                {"account": "2100", "debit": 0.0, "credit": 500.0, "description": "ספק"},
            ],
        ))
        db.commit()

        svc = FinancialReportsService(db)
        bs = svc.generate_balance_sheet(org_id, as_of_date=AS_OF, compare_previous=False)
    finally:
        db.close()

    assert bs.includes_imported is True
    assert bs.imported_entry_count == 1
    assert bs.imported_warning_he
    assert "כבר דווחה" in bs.imported_warning_he

    out = bs.to_dict()
    assert out["includes_imported"] is True
    assert out["imported_warning_he"]


def test_balance_sheet_no_imported_entries_no_warning(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _seed_invoice_and_bill(db, org_id)
        svc = FinancialReportsService(db)
        bs = svc.generate_balance_sheet(org_id, as_of_date=AS_OF, compare_previous=False)
    finally:
        db.close()

    assert bs.includes_imported is False
    assert bs.imported_entry_count == 0
    assert bs.imported_warning_he is None


# --------------------------------------------------------------------- #
# route: GET /api/reports/balance-sheet
# --------------------------------------------------------------------- #
def test_balance_sheet_route_returns_ledger_sourced_data(client, fresh_org):
    org = fresh_org()
    db = SessionLocal()
    try:
        _seed_invoice_and_bill(db, org["org_id"])
    finally:
        db.close()

    r = client.get(f"/api/reports/balance-sheet?as_of_date={AS_OF.isoformat()}", headers=org["headers"])
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["is_balanced"] is True
    assert body["derived"] is True
    ar_item = next(a for a in body["current_assets"] if a["name"] == "1100")
    assert ar_item["amount"] == 1180.0


def test_balance_sheet_route_requires_auth(client):
    assert client.get("/api/reports/balance-sheet").status_code == 403
