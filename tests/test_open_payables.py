"""A matched supplier tax invoice leaves the open payable list.

The stored bill balance is not rewritten by a bank match or by a journal
entry. The open list has to read those links. An unmatched bill stays.
"""
from datetime import date, timedelta
from decimal import Decimal

from cfo.database import SessionLocal
from cfo.models import BankTransaction, Bill, BillStatus, Contact, ContactType, JournalEntry, Payment
from cfo.services.dashboard_service import DashboardService
from cfo.services.payable_workbench import payable_workbench


def _vendor(db, org_id):
    vendor = Contact(organization_id=org_id, name="ספק", contact_type=ContactType.VENDOR)
    db.add(vendor)
    db.flush()
    return vendor


def _bill(db, org_id, vendor, number, amount, *, source="sumit", external_id=None):
    bill = Bill(
        organization_id=org_id, vendor_id=vendor.id, bill_number=number,
        external_id=external_id, source=source,
        total=Decimal(amount), balance=Decimal(amount), status=BillStatus.RECEIVED,
        issue_date=date.today() - timedelta(days=20),
        due_date=date.today() + timedelta(days=10),
    )
    db.add(bill)
    db.flush()
    return bill


def test_matched_bank_bill_leaves_and_unmatched_stays(fresh_org):
    db = SessionLocal()
    org_id = fresh_org()["org_id"]
    vendor = _vendor(db, org_id)
    matched = _bill(db, org_id, vendor, "TAX-1", "500")
    open_bill = _bill(db, org_id, vendor, "TAX-2", "80")
    db.add(BankTransaction(
        organization_id=org_id, amount=Decimal("-500"),
        transaction_date=date.today() - timedelta(days=1),
        is_reconciled=True, matched_entity_type="bill", matched_entity_id=matched.id,
    ))
    db.commit()

    bills = DashboardService(db, org_id).get_ap_bills()
    numbers = {row["bill_number"] for row in bills}

    assert "TAX-1" not in numbers
    assert "TAX-2" in numbers
    assert bills[0]["balance"] == 80.0


def test_accounting_payment_link_closes_the_bill(fresh_org):
    db = SessionLocal()
    org_id = fresh_org()["org_id"]
    vendor = _vendor(db, org_id)
    bill = _bill(db, org_id, vendor, "TAX-PAY", "250")
    db.add(Payment(
        organization_id=org_id, bill_id=bill.id, payment_date=date.today(),
        amount=Decimal("250"), source="manual",
    ))
    db.commit()

    bills = DashboardService(db, org_id).get_ap_bills()

    assert bills == []


def test_journal_reference_closes_the_bill(fresh_org):
    db = SessionLocal()
    org_id = fresh_org()["org_id"]
    vendor = _vendor(db, org_id)
    _bill(db, org_id, vendor, "TAX-J", "400", external_id="doc-400")
    db.add(JournalEntry(
        organization_id=org_id, source="manual", entry_date=date.today(),
        memo="סגירת ספק",
        lines=[
            {"account": "2100", "debit": 400, "credit": 0},
            {"account": "1000", "debit": 0, "credit": 400},
        ],
        raw_data={"reference": "TAX-J"},
    ))
    db.commit()

    aging = DashboardService(db, org_id).get_ap_aging()

    assert aging["count"] == 0
    assert aging["total"] == 0.0


def test_partial_bank_match_keeps_the_remainder(fresh_org):
    db = SessionLocal()
    org_id = fresh_org()["org_id"]
    vendor = _vendor(db, org_id)
    bill = _bill(db, org_id, vendor, "TAX-PART", "400")
    db.add(BankTransaction(
        organization_id=org_id, amount=Decimal("-100"),
        transaction_date=date.today(),
        is_reconciled=True, matched_entity_type="bill", matched_entity_id=bill.id,
    ))
    db.commit()

    bills = DashboardService(db, org_id).get_ap_bills()

    assert len(bills) == 1
    assert bills[0]["balance"] == 300.0


def test_workbench_hides_a_settled_sumit_bill(fresh_org):
    db = SessionLocal()
    org_id = fresh_org()["org_id"]
    vendor = _vendor(db, org_id)
    settled = _bill(db, org_id, vendor, "WB-1", "90")
    _bill(db, org_id, vendor, "WB-2", "40")
    db.add(BankTransaction(
        organization_id=org_id, amount=Decimal("-90"),
        transaction_date=date.today(),
        is_reconciled=True, matched_entity_type="bill", matched_entity_id=settled.id,
    ))
    db.commit()

    workbench = payable_workbench(db, org_id)

    numbers = {row["number"] for row in workbench["bills"]}
    assert numbers == {"WB-2"}
