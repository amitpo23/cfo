"""A document the owner matched on the bank-match screen is settled everywhere.

A 1:N approval, or one with a fee, writes ``matched_entity_type='bank_match'``
on the bank row and keeps the documents in ``bank_match_documents``. Every
reader that treats a 1:1 match as settled must treat these the same: open
payables, AR/AP aging, the contact card, the bank–document gap report and
collection reminders. Without the migration the readers keep working on
1:1 matches and the match screen says so instead of a 500.

All amounts and names are made up.
"""
from contextlib import contextmanager
from datetime import date
from decimal import Decimal

from cfo.database import SessionLocal, engine
from cfo.models import (
    BankMatchDecision, BankMatchDocument, BankTransaction, Bill, BillStatus, Contact, ContactType,
    Invoice, InvoiceStatus,
)
from cfo.services.bank_match_settlements import bank_match_settlements, match_tables_ready
from cfo.services.dashboards.bank_match import decide

TODAY = date(2026, 11, 4)


def _bank(db, org_id, ext, amount, when, description):
    txn = BankTransaction(
        organization_id=org_id, transaction_date=when, amount=Decimal(str(amount)), description=description,
        source="open_finance", external_id=ext, raw_data={"status": "BOOKED"},
    )
    db.add(txn)
    return txn


def _seed_and_approve(org_id):
    """A card deposit for two sales invoices less a fee, one charge for two bills, one payroll row by category."""
    with SessionLocal() as db:
        customer = Contact(organization_id=org_id, name="לקוח דוגמה", contact_type=ContactType.CUSTOMER)
        vendor = Contact(organization_id=org_id, name="ספק דוגמה", contact_type=ContactType.VENDOR)
        db.add_all([customer, vendor])
        db.flush()
        invoices = [
            Invoice(organization_id=org_id, contact_id=customer.id, invoice_number=f"T-{n}",
                    issue_date=date(2026, 10, n), due_date=date(2026, 10, n + 10),
                    status=InvoiceStatus.OVERDUE, subtotal=amount, tax=0, total=amount, balance=amount)
            for n, amount in ((1, 4000), (2, 3000))
        ]
        bills = [
            Bill(organization_id=org_id, vendor_id=vendor.id, source="test", bill_number=f"S-{n}",
                 issue_date=date(2026, 10, n), due_date=date(2026, 10, n + 20), status=BillStatus.RECEIVED,
                 subtotal=1000, tax=180, total=1180, balance=1180)
            for n in (3, 4)
        ]
        db.add_all(invoices + bills)
        deposit = _bank(db, org_id, "tc-dep", 6700, date(2026, 10, 12), "הפקדת סליקה")
        charge = _bank(db, org_id, "tc-chg", -2360, date(2026, 10, 15), "חיוב ספק")
        payroll = _bank(db, org_id, "tc-pay", -5000, date(2026, 10, 20), "תשלום שוטף")
        db.commit()
        ids = {
            "customer": customer.id, "vendor": vendor.id,
            "invoices": [row.id for row in invoices], "bills": [row.id for row in bills],
            "deposit": deposit.id, "charge": charge.id, "payroll": payroll.id,
        }
        decide(db, org_id, None, {
            "transaction_id": deposit.id, "action": "approve", "fee": 300,
            "documents": [{"entity_type": "invoice", "entity_id": i} for i in ids["invoices"]],
        })
        decide(db, org_id, None, {
            "transaction_id": charge.id, "action": "approve",
            "documents": [{"entity_type": "bill", "entity_id": i} for i in ids["bills"]],
        })
        decide(db, org_id, None, {
            "transaction_id": payroll.id, "action": "approve_category",
            "category": "payroll", "target_account": "שכר 900",
        })
        db.commit()
        for key in ("deposit", "charge", "payroll"):
            assert db.get(BankTransaction, ids[key]).matched_entity_type == "bank_match"
    return ids


@contextmanager
def _without_match_tables():
    """Prod before migration m50b2c3d4e5f: the two tables are not there."""
    BankMatchDocument.__table__.drop(engine)
    BankMatchDecision.__table__.drop(engine)
    try:
        yield
    finally:
        BankMatchDecision.__table__.create(engine)
        BankMatchDocument.__table__.create(engine)


# ---------------------------------------------------------------- the shared helper

def test_the_helper_lists_each_matched_document_with_its_own_amount(fresh_org):
    org_id = fresh_org()["org_id"]
    ids = _seed_and_approve(org_id)
    with SessionLocal() as db:
        found = sorted((s.entity_type, s.entity_id, s.amount, s.bank_transaction_id)
                       for s in bank_match_settlements(db, org_id))
        assert found == sorted([
            ("invoice", ids["invoices"][0], 4000.0, ids["deposit"]),
            ("invoice", ids["invoices"][1], 3000.0, ids["deposit"]),
            ("bill", ids["bills"][0], -1180.0, ids["charge"]),
            ("bill", ids["bills"][1], -1180.0, ids["charge"]),
        ])
        assert [s.entity_id for s in bank_match_settlements(db, org_id, ("bill",), [ids["bills"][1]])] == [ids["bills"][1]]
        assert bank_match_settlements(db, org_id, ("invoice",), []) == []

        decide(db, org_id, None, {"transaction_id": ids["charge"], "action": "reopen"})
        db.commit()
        assert {s.entity_type for s in bank_match_settlements(db, org_id)} == {"invoice"}


def test_a_bank_row_that_no_longer_holds_the_decision_settles_nothing(fresh_org):
    org_id = fresh_org()["org_id"]
    ids = _seed_and_approve(org_id)
    with SessionLocal() as db:
        db.get(BankTransaction, ids["deposit"]).is_reconciled = False
        db.commit()
        assert {s.entity_type for s in bank_match_settlements(db, org_id)} == {"bill"}


# ---------------------------------------------------------------- consumers

def test_open_payables_cover_each_bill_by_its_own_line_not_the_whole_charge(fresh_org):
    from cfo.services.dashboard_service import DashboardService
    from cfo.services.open_payables import confirmed_cover
    org_id = fresh_org()["org_id"]
    ids = _seed_and_approve(org_id)
    with SessionLocal() as db:
        cover = confirmed_cover(db, org_id)
        assert {bill_id: float(cover[bill_id]) for bill_id in ids["bills"]} == {bill_id: 1180.0 for bill_id in ids["bills"]}
        service = DashboardService(db, org_id)
        assert [bill.id for bill, _ in service._open_ap_rows()] == []
        aging = service.get_ap_aging()
        assert aging["total"] == 0.0 and aging["bills"] == []


def test_ar_aging_flags_invoices_matched_one_to_many(fresh_org):
    from cfo.services.dashboard_service import DashboardService
    org_id = fresh_org()["org_id"]
    ids = _seed_and_approve(org_id)
    with SessionLocal() as db:
        aging = DashboardService(db, org_id).get_ar_aging()
    seen = {row["id"]: row["bank_movement_seen"] for row in aging["invoices"]}
    assert seen == {ids["invoices"][0]: True, ids["invoices"][1]: True}
    assert aging["bank_movement_seen_total"] == 7000.0


def test_the_contact_card_settles_each_invoice_by_its_line(fresh_org):
    from cfo.services.ledger_service import contact_card
    org_id = fresh_org()["org_id"]
    ids = _seed_and_approve(org_id)
    with SessionLocal() as db:
        customer = contact_card(db, org_id, ids["customer"])
        vendor = contact_card(db, org_id, ids["vendor"])
    settled = sorted(m["amount"] for m in customer["movements"] if m["type"] == "bank_settlement")
    assert settled == [-4000.0, -3000.0]
    assert customer["closing_balance"] == 0.0
    assert customer["totals"]["payments"] == 7000.0
    assert sorted(m["amount"] for m in vendor["movements"] if m["type"] == "bank_settlement") == [-1180.0, -1180.0]
    assert vendor["closing_balance"] == 0.0


def test_the_gap_report_counts_matched_rows_as_explained(fresh_org):
    from cfo.services.bank_expense_gap import classify_transaction, gap_report, suppliers_missing_invoices
    org_id = fresh_org()["org_id"]
    ids = _seed_and_approve(org_id)
    with SessionLocal() as db:
        assert classify_transaction(db.get(BankTransaction, ids["payroll"])) == "expense_candidate"
        report = gap_report(db, org_id, 2026, 10)
        missing = suppliers_missing_invoices(db, org_id, date(2026, 10, 1), date(2026, 10, 31))
    totals = report["totals"]
    assert [row["has_document"] for row in report["transactions"]] == [True]
    assert totals["documented_total"] == 2360.0
    assert totals["undocumented_count"] == 0 and totals["undocumented_total"] == 0.0
    assert totals["excluded_by_class"]["bank_match_category"] == {"count": 1, "total": 5000.0}
    assert report["inflows"] == {"undocumented_total": 0.0, "undocumented_count": 0}
    assert missing["suppliers"] == []
    assert missing["unidentified_transfers"]["count"] == 0


def test_no_collection_reminder_for_an_invoice_matched_one_to_many(fresh_org):
    from cfo.services.collection_service import CollectionService
    org_id = fresh_org()["org_id"]
    ids = _seed_and_approve(org_id)
    with SessionLocal() as db:
        planned = CollectionService(db, org_id).plan_reminders(TODAY)
    assert [p for p in planned if p.contact_id == ids["customer"]] == []


def test_a_matched_credit_note_does_not_stop_reminders_for_another_invoice(fresh_org):
    """A sale credit note's line is money out; it is not a payment of the customer's debt."""
    from cfo.services.collection_service import CollectionService
    org_id = fresh_org()["org_id"]
    with SessionLocal() as db:
        customer = Contact(organization_id=org_id, name="לקוח זיכוי", contact_type=ContactType.CUSTOMER)
        db.add(customer)
        db.flush()
        credit = Invoice(organization_id=org_id, contact_id=customer.id, invoice_number="CR-1",
                         issue_date=date(2026, 10, 1), status=InvoiceStatus.SENT, total=-200, balance=0,
                         raw_data={"document_type": "credit_note"})
        debt = Invoice(organization_id=org_id, contact_id=customer.id, invoice_number="D-1",
                       issue_date=date(2026, 10, 1), due_date=date(2026, 10, 10), status=InvoiceStatus.OVERDUE,
                       total=900, balance=900)
        db.add_all([credit, debt])
        refund = _bank(db, org_id, "tc-ref", -210, date(2026, 10, 5), "החזר ללקוח")
        db.commit()
        decide(db, org_id, None, {"transaction_id": refund.id, "action": "approve", "fee": 10,
                                  "documents": [{"entity_type": "invoice", "entity_id": credit.id}]})
        db.commit()
        planned = CollectionService(db, org_id).plan_reminders(TODAY)
    assert [p.invoice_numbers for p in planned if p.contact_id == customer.id] == [["D-1"]]


# ---------------------------------------------------------------- before the migration

def test_without_the_match_tables_readers_keep_their_one_to_one_matches(fresh_org):
    from cfo.services.bank_expense_gap import gap_report
    from cfo.services.collection_service import CollectionService
    from cfo.services.dashboard_service import DashboardService
    from cfo.services.ledger_service import contact_card
    from cfo.services.open_payables import confirmed_cover
    org_id = fresh_org()["org_id"]
    with SessionLocal() as db:
        vendor = Contact(organization_id=org_id, name="ספק ישיר", contact_type=ContactType.VENDOR)
        db.add(vendor)
        db.flush()
        bill = Bill(organization_id=org_id, vendor_id=vendor.id, source="test", bill_number="DIR-1",
                    issue_date=date(2026, 10, 3), status=BillStatus.RECEIVED, total=590, balance=590)
        db.add(bill)
        db.flush()
        db.add(BankTransaction(organization_id=org_id, transaction_date=date(2026, 10, 6), amount=Decimal("-590"),
                               description="חיוב ספק ישיר", source="open_finance", external_id="tc-dir",
                               is_reconciled=True, matched_entity_type="bill", matched_entity_id=bill.id))
        db.commit()
        bill_id, vendor_id = bill.id, vendor.id

    with _without_match_tables():
        with SessionLocal() as db:
            assert match_tables_ready(db) is False
            assert bank_match_settlements(db, org_id) == []
            assert float(confirmed_cover(db, org_id)[bill_id]) == 590.0
            service = DashboardService(db, org_id)
            service.get_ar_aging()
            assert service.get_ap_aging()["bills"] == []
            assert contact_card(db, org_id, vendor_id)["closing_balance"] == 0.0
            assert gap_report(db, org_id, 2026, 10)["totals"]["documented_total"] == 590.0
            CollectionService(db, org_id).plan_reminders(TODAY)
    with SessionLocal() as db:
        assert match_tables_ready(db) is True


def _dashboard(client, owner, slug):
    created = client.post("/api/dashboards", headers=owner["headers"], json={
        "primary_organization_id": owner["org_id"], "slug": slug, "title": "התאמה", "access_mode": "public",
    })
    assert created.status_code == 201, created.text
    return created.json()["id"]


def test_the_match_screen_says_the_migration_is_pending_instead_of_a_500(client, fresh_org):
    owner = fresh_org()
    dashboard_id = _dashboard(client, owner, "bank-match-premigration")
    client.patch(f"/api/dashboards/{dashboard_id}", headers=owner["headers"],
                 json={"status": "active", "access_mode": "public"})
    url = f"/api/dashboards/{dashboard_id}/bank-match"
    window = {"start": "2026-10-01", "end": "2026-10-31"}
    with _without_match_tables():
        listed = client.get(url, headers=owner["headers"], params=window)
        decided = client.post(url, headers=owner["headers"], json={"transaction_id": 1, "action": "check"})
        public = client.get("/api/public/d/bank-match-premigration/bank-match", params=window)
    for response in (listed, decided, public):
        assert response.status_code == 503, response.text
        error = response.json()["error"]
        assert error["code"] == "migration_pending"
        assert "התאמת בנק" in error["message_he"]
    assert client.get(url, headers=owner["headers"], params=window).status_code == 200
