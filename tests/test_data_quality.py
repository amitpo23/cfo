"""data_quality.run_checks — בדיקות שפיות (invariants) פר-ארגון.
ראה docs/REZEF_DATA_INTEGRITY_PLAN.md סעיף ג.
"""
from datetime import date, datetime, timedelta

import pytest


def test_run_checks_all_pass_on_clean_org(fresh_org):
    from cfo.database import SessionLocal
    from cfo.services.data_quality import run_checks

    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        result = run_checks(db, org_id)
        assert result["status"] == "ok"
        assert result["issues_count"] == 0
        names = {c["name"] for c in result["checks"]}
        assert names == {
            "bills_nonnegative", "no_paid_invoice_with_open_balance",
            "invoice_balance_consistency", "currency_whitelist",
            "of_balance_freshness", "duplicate_external_ids",
            "empty_draft_expenses_count",
        }
        assert all(c["passed"] for c in result["checks"])
        assert "checked_at" in result
    finally:
        db.close()


def test_bills_nonnegative_fails_on_negative_total(fresh_org):
    from cfo.database import SessionLocal
    from cfo.models import Contact, ContactType, Bill, BillStatus
    from cfo.services.data_quality import run_checks

    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        vend = Contact(organization_id=org_id, contact_type=ContactType.VENDOR, name="ספק")
        db.add(vend)
        db.flush()
        db.add(Bill(organization_id=org_id, vendor_id=vend.id, bill_number="B1",
                    issue_date=date(2026, 5, 1), subtotal=-100, tax=-18, total=-118,
                    paid_amount=0, balance=-118, status=BillStatus.RECEIVED))
        db.commit()

        result = run_checks(db, org_id)
        check = next(c for c in result["checks"] if c["name"] == "bills_nonnegative")
        assert check["passed"] is False
        assert result["status"] == "issues"
        assert result["issues_count"] >= 1
    finally:
        db.close()


def test_no_paid_invoice_with_open_balance_fails(fresh_org):
    from cfo.database import SessionLocal
    from cfo.models import Invoice, InvoiceStatus
    from cfo.services.data_quality import run_checks

    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        db.add(Invoice(organization_id=org_id, invoice_number="I1",
                       issue_date=date(2026, 5, 1), status=InvoiceStatus.PAID,
                       total=1000, paid_amount=0, balance=1000))
        db.commit()

        result = run_checks(db, org_id)
        check = next(c for c in result["checks"] if c["name"] == "no_paid_invoice_with_open_balance")
        assert check["passed"] is False
    finally:
        db.close()


def test_invoice_balance_consistency_fails_on_mismatch(fresh_org):
    from cfo.database import SessionLocal
    from cfo.models import Invoice, InvoiceStatus
    from cfo.services.data_quality import run_checks

    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        db.add(Invoice(organization_id=org_id, invoice_number="I1",
                       issue_date=date(2026, 5, 1), status=InvoiceStatus.SENT,
                       total=1000, paid_amount=200, balance=999))  # should be 800
        db.commit()

        result = run_checks(db, org_id)
        check = next(c for c in result["checks"] if c["name"] == "invoice_balance_consistency")
        assert check["passed"] is False
    finally:
        db.close()


def test_currency_whitelist_fails_on_unknown_currency(fresh_org):
    from cfo.database import SessionLocal
    from cfo.models import Account, AccountType
    from cfo.services.data_quality import run_checks

    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        db.add(Account(organization_id=org_id, name="Weird", account_type=AccountType.BANK,
                       balance=0, currency="ILY"))
        db.commit()

        result = run_checks(db, org_id)
        check = next(c for c in result["checks"] if c["name"] == "currency_whitelist")
        assert check["passed"] is False
    finally:
        db.close()


def test_of_balance_freshness_passes_when_no_of_accounts(fresh_org):
    from cfo.database import SessionLocal
    from cfo.services.data_quality import run_checks

    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        result = run_checks(db, org_id)
        check = next(c for c in result["checks"] if c["name"] == "of_balance_freshness")
        assert check["passed"] is True
    finally:
        db.close()


def test_of_balance_freshness_fails_on_stale_balance(fresh_org):
    from cfo.database import SessionLocal
    from cfo.models import Account, AccountType
    from cfo.services.data_quality import run_checks

    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        db.add(Account(organization_id=org_id, name="עו\"ש", account_type=AccountType.BANK,
                       balance=1000, currency="ILS", source="open_finance",
                       balance_as_of=datetime.utcnow() - timedelta(hours=72)))
        db.commit()

        result = run_checks(db, org_id)
        check = next(c for c in result["checks"] if c["name"] == "of_balance_freshness")
        assert check["passed"] is False
    finally:
        db.close()


def test_of_balance_freshness_passes_on_fresh_balance(fresh_org):
    from cfo.database import SessionLocal
    from cfo.models import Account, AccountType
    from cfo.services.data_quality import run_checks

    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        db.add(Account(organization_id=org_id, name="עו\"ש", account_type=AccountType.BANK,
                       balance=1000, currency="ILS", source="open_finance",
                       balance_as_of=datetime.utcnow() - timedelta(hours=2)))
        db.commit()

        result = run_checks(db, org_id)
        check = next(c for c in result["checks"] if c["name"] == "of_balance_freshness")
        assert check["passed"] is True
    finally:
        db.close()


def test_duplicate_external_ids_fails_on_duplicate(fresh_org):
    """invoices/bills/bank_transactions כבר מוגנים ב-unique index (org,
    external_id, source) — הכפילות האמיתית שהבדיקה תופסת היא בטבלת
    expenses (בכוונה לא unique, כי אותו מסמך SUMIT מסונכרן גם כ-Bill),
    שם דו-רישום אמיתי (בטעות) עדיין אפשרי."""
    from cfo.database import SessionLocal
    from cfo.models import Expense
    from cfo.services.data_quality import run_checks

    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        db.add(Expense(organization_id=org_id, external_id="DUP1", supplier_name="ספק",
                       amount=100, total=118, expense_date=date(2026, 5, 1), status="filed"))
        db.add(Expense(organization_id=org_id, external_id="DUP1", supplier_name="ספק",
                       amount=100, total=118, expense_date=date(2026, 5, 1), status="filed"))
        db.commit()

        result = run_checks(db, org_id)
        check = next(c for c in result["checks"] if c["name"] == "duplicate_external_ids")
        assert check["passed"] is False
    finally:
        db.close()


def test_empty_draft_expenses_count_is_always_passed(fresh_org):
    from cfo.database import SessionLocal
    from cfo.models import Expense
    from cfo.services.data_quality import run_checks

    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        db.add(Expense(organization_id=org_id, supplier_name="ספק", amount=0, total=0,
                       expense_date=date(2026, 5, 1), status="pending"))
        db.commit()

        result = run_checks(db, org_id)
        check = next(c for c in result["checks"] if c["name"] == "empty_draft_expenses_count")
        assert check["passed"] is True  # אינפורמטיבי — תמיד True
        assert "1" in check["details"]
    finally:
        db.close()


def test_org_isolation(fresh_org):
    """בדיקות מוגבלות ל-org — נתון פגום ב-org אחד לא משפיע על אחר."""
    from cfo.database import SessionLocal
    from cfo.models import Contact, ContactType, Bill, BillStatus
    from cfo.services.data_quality import run_checks

    org_bad = fresh_org()["org_id"]
    org_clean = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        vend = Contact(organization_id=org_bad, contact_type=ContactType.VENDOR, name="ספק")
        db.add(vend)
        db.flush()
        db.add(Bill(organization_id=org_bad, vendor_id=vend.id, bill_number="B1",
                    issue_date=date(2026, 5, 1), subtotal=-100, tax=-18, total=-118,
                    paid_amount=0, balance=-118, status=BillStatus.RECEIVED))
        db.commit()

        result_clean = run_checks(db, org_clean)
        assert result_clean["status"] == "ok"
    finally:
        db.close()
