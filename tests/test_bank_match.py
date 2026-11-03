"""Bank match screen: one bank row ↔ one or many book documents, or a category.

A candidate is a suggestion. Only the owner's אשר matches a row. A row the
nightly auto-reconcile matched still waits for the owner. No candidate is
shown as none, not as 0. Balanced means every row is explained; a row in
check or missing a document is decided, not balanced. Decisions live in
their own table and are written with the bank columns in one transaction.
"""
import ast
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from cfo.database import SessionLocal
from cfo.models import (
    BankMatchDecision, BankMatchDocument, BankTransaction, Bill, BillStatus, Expense, Invoice, InvoiceStatus,
)
from cfo.services.dashboards.bank_match import MatchDoc, build_report, closing_state
from cfo.services.dashboards.filing import Filed, Txn


def _pair(txn_id, amount, description="", debtor="", creditor="", when="2026-10-05", category="suppliers"):
    txn = Txn(txn_id, 1, None, when, amount, description, debtor, creditor)
    return txn, Filed(category, f"rule:{category}", category)


# ---------------------------------------------------------------- pure report

def test_an_outflow_gets_a_bill_candidate_and_an_inflow_gets_an_invoice():
    paired = [_pair(1, -1180.0, "תשלום", debtor="ספק אלפא"), _pair(2, 590.0, "העברה", creditor="לקוח בטא")]
    docs = [
        MatchDoc("bill", 10, -1180.0, date(2026, 10, 3), "ספק אלפא"),
        MatchDoc("invoice", 11, 1180.0, date(2026, 10, 3), "ספק אלפא"),
        MatchDoc("invoice", 12, 590.0, date(2026, 10, 4), "לקוח בטא"),
    ]
    rows = {row["id"]: row for row in build_report(paired, {}, {}, docs)["rows"]}
    assert [c["entity_id"] for c in rows[1]["candidates"]] == [10]
    assert [c["entity_id"] for c in rows[2]["candidates"]] == [12]
    assert rows[1]["counterparty"] == "ספק אלפא"
    assert rows[1]["status"] == "open"


def test_credit_notes_and_refunds_are_offered_in_their_bank_direction():
    """Blocker 7: a sale credit note is money out; a supplier credit or refund is money in."""
    paired = [_pair(1, -236.0, "החזר ללקוח", debtor="לקוח גמא"), _pair(2, 354.0, "זיכוי ספק", creditor="ספק דלתא")]
    docs = [
        MatchDoc("invoice", 20, -236.0, date(2026, 10, 4), "לקוח גמא", credit=True),
        MatchDoc("bill", 21, 354.0, date(2026, 10, 4), "ספק דלתא", credit=True),
        MatchDoc("invoice", 22, 236.0, date(2026, 10, 4), "לקוח גמא"),
    ]
    rows = {row["id"]: row for row in build_report(paired, {}, {}, docs)["rows"]}
    assert [(c["entity_type"], c["entity_id"], c["credit"]) for c in rows[1]["candidates"]] == [("invoice", 20, True)]
    assert [(c["entity_type"], c["entity_id"]) for c in rows[2]["candidates"]] == [("bill", 21)]


def test_no_candidate_is_none_not_zero():
    report = build_report([_pair(1, -77.0, "עמלה")], {}, {}, [])
    row = report["rows"][0]
    assert row["candidates"] == []
    assert report["summary"]["open"]["count"] == 1


def test_auto_match_waits_for_the_owner_and_owner_approval_is_approved():
    paired = [_pair(1, -100.0), _pair(2, -200.0)]
    recon = {1: ("bill", 10), 2: ("bill", 20)}
    decisions = {2: {"id": 7, "status": "approved", "kind": "documents",
                     "documents": [{"entity_type": "bill", "entity_id": 20, "amount": -200.0}]}}
    docs = [MatchDoc("bill", 10, -100.0, date(2026, 10, 5), "x"), MatchDoc("bill", 20, -200.0, date(2026, 10, 5), "y")]
    rows = {row["id"]: row for row in build_report(paired, recon, decisions, docs, taken={("bill", 10), ("bill", 20)})["rows"]}
    assert rows[1]["status"] == "open"
    assert rows[1]["auto_match"] == {"entity_type": "bill", "entity_id": 10}
    assert rows[1]["candidates"][0]["entity_id"] == 10  # its own auto match is still offered on it
    assert rows[2]["status"] == "approved"
    assert rows[2]["matched"]["documents"][0]["entity_id"] == 20


def test_a_stale_approval_without_the_db_match_is_open_again():
    decisions = {1: {"id": 3, "status": "approved", "kind": "documents",
                     "documents": [{"entity_type": "bill", "entity_id": 9, "amount": -100.0}]}}
    assert build_report([_pair(1, -100.0)], {}, decisions, [])["rows"][0]["status"] == "open"


def test_a_document_taken_anywhere_in_the_org_is_not_offered():
    """Blocker 4: taken comes from the whole organization, not the window's decisions."""
    paired = [_pair(1, -100.0)]
    docs = [MatchDoc("bill", 10, -100.0, date(2026, 10, 5), "x")]
    report = build_report(paired, {}, {}, docs, taken={("bill", 10)}, start=date(2026, 10, 1), end=date(2026, 10, 31))
    assert report["rows"][0]["candidates"] == []
    assert report["documents"] == []


def test_balanced_only_when_every_row_is_explained():
    """Blocker 3: check and missing_doc rows are decided, not balanced."""
    paired = [_pair(1, -100.0), _pair(2, -50.0), _pair(3, 30.0), _pair(4, -5.0)]
    recon = {1: ("bill", 10), 4: ("bank_match", 9)}
    decisions = {
        1: {"id": 8, "status": "approved", "kind": "documents",
            "documents": [{"entity_type": "bill", "entity_id": 10, "amount": -100.0}]},
        2: {"id": 5, "status": "check", "note": "לבדוק מול הספק"},
        3: {"id": 6, "status": "missing_doc"},
        4: {"id": 9, "status": "approved", "kind": "category", "category": "owner_current", "target_account": "300"},
    }
    summary = build_report(paired, recon, decisions, [])["summary"]
    assert summary["approved"] == {"count": 2, "amount": -105.0}
    assert summary["check"] == {"count": 1, "amount": -50.0}
    assert summary["missing_doc"]["count"] == 1 and summary["missing_doc"]["abs_amount"] == 30.0
    assert summary["coverage_ok"] is True
    assert summary["decided"] is True
    assert summary["balanced"] is False and summary["done"] is False
    state = closing_state(summary, "2026-10-31", "2026-10-31")
    assert state["done"] is False
    assert state["label_he"] == "הוכרע, לא מאוזן — חסרים 1 מסמכים ₪30 · 1 בבדיקה"

    only_approved = build_report(paired[:1] + paired[3:], recon, decisions, [])["summary"]
    assert only_approved["balanced"] is True
    assert closing_state(only_approved, "2026-10-31", "2026-10-31")["label_he"] == "מאוזן — כל התנועות בטווח הוסברו"


def test_an_empty_window_is_not_done():
    state = closing_state(build_report([], {}, {}, [])["summary"], "2026-10-06", "2026-10-31")
    assert state["done"] is False
    assert "אין תנועות" in state["label_he"]


def test_a_window_past_the_bank_date_is_balanced_only_up_to_that_date():
    recon = {1: ("bank_match", 4)}
    decisions = {1: {"id": 4, "status": "approved", "kind": "category", "category": "payroll", "target_account": "6100"}}
    summary = build_report([_pair(1, -5.0)], recon, decisions, [])["summary"]
    assert closing_state(summary, "2026-10-06", "2026-10-31")["label_he"] == \
        "מאוזן עד 06.10 — הבנק לא מעודכן אחרי התאריך הזה"
    assert "תאריך הבנק חסר" in closing_state(summary, None, "2026-10-31")["label_he"]


# ---------------------------------------------------------------- documents from the DB

def test_load_docs_scores_an_expense_on_its_total_with_vat(fresh_org):
    from cfo.services.bank_reconciliation import load_docs_for_org
    owner = fresh_org()
    with SessionLocal() as db:
        db.add(Expense(organization_id=owner["org_id"], supplier_name="ספק", amount=Decimal("100"),
                       vat_amount=Decimal("18"), total=Decimal("118"), expense_date=date(2026, 10, 1)))
        db.add(Expense(organization_id=owner["org_id"], supplier_name="ספק ישן", amount=Decimal("50"),
                       expense_date=date(2026, 10, 1)))
        db.commit()
        _, _, expenses = load_docs_for_org(db, owner["org_id"])
    assert sorted(doc.amount for doc in expenses) == [50.0, 118.0]


def test_paid_invoices_are_not_open_but_credit_notes_are(fresh_org):
    """Blockers 4 + 7: a paid invoice is closed; a synced credit note (status paid, total < 0) is open, signed −."""
    from cfo.services.dashboards.bank_match import load_match_docs
    owner = fresh_org()
    with SessionLocal() as db:
        db.add_all([
            Invoice(organization_id=owner["org_id"], invoice_number="P", issue_date=date(2026, 10, 1),
                    status=InvoiceStatus.PAID, total=500, balance=0),
            Invoice(organization_id=owner["org_id"], invoice_number="C", issue_date=date(2026, 10, 1),
                    status=InvoiceStatus.PAID, total=-236, raw_data={"document_type": "credit_note"}),
            Invoice(organization_id=owner["org_id"], invoice_number="H", issue_date=date(2026, 10, 1),
                    status=InvoiceStatus.PARTIALLY_PAID, total=1000, balance=400),
            Bill(organization_id=owner["org_id"], bill_number="BP", issue_date=date(2026, 10, 1),
                 status=BillStatus.PAID, total=300),
            Bill(organization_id=owner["org_id"], bill_number="BC", issue_date=date(2026, 10, 1), total=-354),
            Expense(organization_id=owner["org_id"], supplier_name="החזר", amount=-100, total=-100,
                    expense_date=date(2026, 10, 1)),
        ])
        db.commit()
        docs = sorted((doc.entity_type, doc.amount, doc.credit) for doc in load_match_docs(db, owner["org_id"]))
    assert docs == [
        ("bill", 354.0, True), ("expense", 100.0, True), ("invoice", -236.0, True), ("invoice", 400.0, False),
    ]


# ---------------------------------------------------------------- API

def _dashboard(client, owner, slug):
    created = client.post("/api/dashboards", headers=owner["headers"], json={
        "primary_organization_id": owner["org_id"], "slug": slug, "title": "התאמה", "access_mode": "public",
    })
    assert created.status_code == 201, created.text
    return created.json()["id"]


def _bank(db, org_id, ext, amount, when=date(2026, 10, 5), description="", **raw):
    txn = BankTransaction(
        organization_id=org_id, transaction_date=when, amount=Decimal(str(amount)), description=description,
        source="open_finance", external_id=ext, raw_data={"status": "BOOKED", **raw},
    )
    db.add(txn)
    return txn


def _seed(org_id):
    with SessionLocal() as db:
        out = _bank(db, org_id, "bm-out", -1180, description="תשלום לספק", creditorName="ספק אלפא")
        fee = _bank(db, org_id, "bm-fee", -15, when=date(2026, 10, 6), description="עמלה")
        bill = Bill(organization_id=org_id, source="test", bill_number="B-1", issue_date=date(2026, 10, 3),
                    subtotal=1000, tax=180, total=1180, balance=1180)
        db.add(bill)
        db.commit()
        return out.id, fee.id, bill.id


URL = "/api/dashboards/{}/bank-match"
WINDOW = {"start": "2026-10-01", "end": "2026-10-31"}


def test_owner_approves_flags_and_reopens(client, fresh_org):
    owner = fresh_org()
    dashboard_id = _dashboard(client, owner, "bank-match-flow")
    out_id, fee_id, bill_id = _seed(owner["org_id"])
    url = URL.format(dashboard_id)

    body = client.get(url, headers=owner["headers"], params=WINDOW).json()
    rows = {row["id"]: row for row in body["rows"]}
    assert rows[out_id]["counterparty"] == "ספק אלפא"
    assert rows[out_id]["candidates"][0]["entity_id"] == bill_id
    assert rows[fee_id]["candidates"] == []
    assert body["partial_banner"]["text_he"].startswith("נתונים חלקיים — בנק עד 06.10")
    assert body["provider_calls"] == 0

    approved = client.post(url, headers=owner["headers"], json={
        "transaction_id": out_id, "action": "approve", "entity_type": "bill", "entity_id": bill_id,
    })
    assert approved.status_code == 200, approved.text
    missing = client.post(url, headers=owner["headers"], json={
        "transaction_id": fee_id, "action": "missing_doc", "note": "לבקש מהבנק", "amount": 1, "date": "1999-01-01",
    })
    assert missing.status_code == 200, missing.text

    with SessionLocal() as db:
        txn = db.get(BankTransaction, out_id)
        assert txn.is_reconciled is True and (txn.matched_entity_type, txn.matched_entity_id) == ("bill", bill_id)
        flagged = db.query(BankMatchDecision).filter_by(bank_transaction_id=fee_id).one()
        assert (flagged.status, flagged.note) == ("missing_doc", "לבקש מהבנק")

    again = client.get(url, headers=owner["headers"], params=WINDOW).json()
    rows = {row["id"]: row for row in again["rows"]}
    assert rows[out_id]["status"] == "approved"
    assert rows[fee_id]["status"] == "missing_doc"
    assert again["summary"]["balanced"] is False
    assert again["closing"]["label_he"] == "הוכרע, לא מאוזן — חסרים 1 מסמכים ₪15"

    reopened = client.post(url, headers=owner["headers"], json={"transaction_id": out_id, "action": "reopen"})
    assert reopened.status_code == 200, reopened.text
    with SessionLocal() as db:
        assert db.get(BankTransaction, out_id).is_reconciled is False
        assert db.query(BankMatchDecision).filter_by(bank_transaction_id=out_id).count() == 0
        assert db.query(BankMatchDocument).filter_by(bank_transaction_id=out_id).count() == 0
    final = {row["id"]: row for row in client.get(url, headers=owner["headers"], params=WINDOW).json()["rows"]}
    assert final[out_id]["status"] == "open"


def test_one_max_settlement_against_many_invoices_with_a_fee(client, fresh_org):
    """Blocker 1: a weekly Max deposit = Σ sales invoices − clearing fee, within ₪1."""
    owner = fresh_org()
    dashboard_id = _dashboard(client, owner, "bank-match-max")
    with SessionLocal() as db:
        deposit = _bank(db, owner["org_id"], "max-1", 9700.4, description="מקס איט פיננסים", debtorName="מקס")
        invoices = [Invoice(organization_id=owner["org_id"], invoice_number=f"Z-{n}", issue_date=date(2026, 10, n),
                            status=InvoiceStatus.SENT, total=amount, balance=amount)
                    for n, amount in ((1, 4000), (2, 3500), (3, 2500))]
        db.add_all(invoices)
        db.commit()
        deposit_id, ids = deposit.id, [inv.id for inv in invoices]
    url = URL.format(dashboard_id)
    docs = [{"entity_type": "invoice", "entity_id": i} for i in ids]

    listed = client.get(url, headers=owner["headers"], params=WINDOW).json()
    assert {d["entity_id"] for d in listed["documents"]} == set(ids)

    short = client.post(url, headers=owner["headers"], json={"transaction_id": deposit_id, "action": "approve", "documents": docs})
    assert short.status_code == 422 and "הפרש" in short.json()["error"]["message_he"]
    with SessionLocal() as db:
        assert db.query(BankMatchDecision).filter_by(bank_transaction_id=deposit_id).count() == 0

    ok = client.post(url, headers=owner["headers"], json={
        "transaction_id": deposit_id, "action": "approve", "documents": docs, "fee": 300,
    })
    assert ok.status_code == 200, ok.text
    with SessionLocal() as db:
        txn = db.get(BankTransaction, deposit_id)
        decision = db.query(BankMatchDecision).filter_by(bank_transaction_id=deposit_id).one()
        assert txn.is_reconciled is True
        assert (txn.matched_entity_type, txn.matched_entity_id) == ("bank_match", decision.id)
        assert float(decision.fee_amount) == 300.0
        lines = db.query(BankMatchDocument).filter_by(decision_id=decision.id).all()
        assert sorted(float(line.amount) for line in lines) == [2500.0, 3500.0, 4000.0]

    row = next(r for r in client.get(url, headers=owner["headers"], params=WINDOW).json()["rows"] if r["id"] == deposit_id)
    assert row["status"] == "approved"
    assert len(row["matched"]["documents"]) == 3 and row["matched"]["fee"] == 300.0


def test_one_card_charge_against_many_expenses_and_a_refund(client, fresh_org):
    """Blockers 1 + 7: an Isracard charge = Σ expenses − a refund on the same statement."""
    owner = fresh_org()
    dashboard_id = _dashboard(client, owner, "bank-match-card")
    with SessionLocal() as db:
        charge = _bank(db, owner["org_id"], "isra-1", -1500, when=date(2026, 10, 15), description="ישראכרט")
        expenses = [Expense(organization_id=owner["org_id"], supplier_name=name, amount=total, total=total,
                            expense_date=date(2026, 9, day))
                    for name, total, day in (("דלק", 1000, 20), ("משרד", 600, 22), ("החזר", -100, 25))]
        db.add_all(expenses)
        db.commit()
        charge_id, ids = charge.id, [exp.id for exp in expenses]
    response = client.post(URL.format(dashboard_id), headers=owner["headers"], json={
        "transaction_id": charge_id, "action": "approve",
        "documents": [{"entity_type": "expense", "entity_id": i} for i in ids],
    })
    assert response.status_code == 200, response.text
    with SessionLocal() as db:
        lines = db.query(BankMatchDocument).filter_by(bank_transaction_id=charge_id).all()
        assert sorted(float(line.amount) for line in lines) == [-1000.0, -600.0, 100.0]


def test_approve_by_category_without_a_document(client, fresh_org):
    """Blocker 2: owner current account / payroll / loan / discounting / card clearing need a target card."""
    owner = fresh_org()
    dashboard_id = _dashboard(client, owner, "bank-match-category")
    with SessionLocal() as db:
        loan = _bank(db, owner["org_id"], "loan-1", 50000, when=date(2026, 10, 2), description="הלוואה")
        db.commit()
        loan_id = loan.id
    url = URL.format(dashboard_id)
    no_card = client.post(url, headers=owner["headers"], json={
        "transaction_id": loan_id, "action": "approve_category", "category": "loan"})
    assert no_card.status_code == 422
    unknown = client.post(url, headers=owner["headers"], json={
        "transaction_id": loan_id, "action": "approve_category", "category": "income", "target_account": "4000"})
    assert unknown.status_code == 422
    ok = client.post(url, headers=owner["headers"], json={
        "transaction_id": loan_id, "action": "approve_category", "category": "loan", "target_account": "2400"})
    assert ok.status_code == 200, ok.text
    body = client.get(url, headers=owner["headers"], params=WINDOW).json()
    row = body["rows"][0]
    assert row["status"] == "approved"
    assert row["matched"]["category"] == "loan" and row["matched"]["target_account"] == "2400"
    assert body["summary"]["balanced"] is True and body["closing"]["done"] is True
    with SessionLocal() as db:
        assert db.get(BankTransaction, loan_id).is_reconciled is True


def test_a_document_matched_to_another_row_cannot_be_approved_again(client, fresh_org):
    """Blocker 4: a bank row matched outside the window still holds its document."""
    owner = fresh_org()
    dashboard_id = _dashboard(client, owner, "bank-match-taken")
    out_id, _, bill_id = _seed(owner["org_id"])
    with SessionLocal() as db:
        earlier = _bank(db, owner["org_id"], "bm-old", -1180, when=date(2026, 8, 5))
        earlier.is_reconciled, earlier.matched_entity_type, earlier.matched_entity_id = True, "bill", bill_id
        db.commit()
    url = URL.format(dashboard_id)
    row = next(r for r in client.get(url, headers=owner["headers"], params=WINDOW).json()["rows"] if r["id"] == out_id)
    assert row["candidates"] == []
    again = client.post(url, headers=owner["headers"], json={
        "transaction_id": out_id, "action": "approve", "entity_type": "bill", "entity_id": bill_id})
    assert again.status_code == 422 and "כבר מותאם" in again.json()["error"]["message_he"]


def test_a_failure_rolls_back_the_decision_and_the_bank_columns(client, fresh_org, monkeypatch):
    """Blocker 5: decision row, document lines and bank columns are one transaction."""
    from cfo.services.manual_reconciliation import ManualReconciliationService
    owner = fresh_org()
    dashboard_id = _dashboard(client, owner, "bank-match-atomic")
    out_id, _, bill_id = _seed(owner["org_id"])

    def boom(txn, entity_type, entity_id):
        raise ValueError("כשל מכוון")
    monkeypatch.setattr(ManualReconciliationService, "mark_reconciled", staticmethod(boom))
    failed = client.post(URL.format(dashboard_id), headers=owner["headers"], json={
        "transaction_id": out_id, "action": "approve", "entity_type": "bill", "entity_id": bill_id})
    assert failed.status_code == 422
    with SessionLocal() as db:
        assert db.query(BankMatchDecision).filter_by(bank_transaction_id=out_id).count() == 0
        assert db.query(BankMatchDocument).filter_by(bank_transaction_id=out_id).count() == 0
        assert db.get(BankTransaction, out_id).is_reconciled is not True


def test_the_plan_never_carries_match_decisions(client, fresh_org):
    """Blocker 5: no decision JSON in the dashboard plan, for any role."""
    from tests.test_dashboard_eliav_ui_r2 import _put
    owner = fresh_org()
    dashboard_id = _dashboard(client, owner, "bank-match-noplan")
    forged = _put(client, owner["headers"], dashboard_id, {"bankMatchDecisions": {"5": {"status": "check"}}})
    assert forged.status_code == 422 and forged.json()["error"]["code"] == "invalid_plan"


def test_bank_match_uses_only_the_public_reconciliation_api():
    """Blocker 6: no private ManualReconciliationService method is called from the match screen."""
    source = Path(__file__).resolve().parents[1] / "src/cfo/services/dashboards/bank_match.py"
    private = {node.attr for node in ast.walk(ast.parse(source.read_text()))
               if isinstance(node, ast.Attribute) and node.attr.startswith("_")
               and isinstance(node.value, ast.Name) and node.value.id == "service"}
    assert private == set()
    imported = {alias.name for node in ast.walk(ast.parse(source.read_text()))
                if isinstance(node, ast.ImportFrom) for alias in node.names if alias.name.startswith("_")}
    assert imported == set()


def test_public_reconciliation_building_blocks_do_not_commit(fresh_org):
    """Blocker 6: assert_matchable / get_document / mark_reconciled leave the commit to the caller."""
    from cfo.services.manual_reconciliation import ManualReconciliationService
    owner = fresh_org()
    out_id, _, bill_id = _seed(owner["org_id"])
    with SessionLocal() as db:
        service = ManualReconciliationService(db, organization_id=owner["org_id"])
        txn = db.get(BankTransaction, out_id)
        service.assert_matchable(txn)
        assert service.get_document("bill", bill_id) is not None
        assert service.get_document("bill", bill_id + 10_000) is None
        service.mark_reconciled(txn, "bill", bill_id)
        db.rollback()
    with SessionLocal() as db:
        assert db.get(BankTransaction, out_id).is_reconciled is not True
        txn = db.get(BankTransaction, out_id)
        txn.is_provisional = True
        with pytest.raises(ValueError):
            ManualReconciliationService(db, organization_id=owner["org_id"]).assert_matchable(txn)


def test_flagging_an_auto_matched_row_keeps_the_auto_match(client, fresh_org):
    """Only a match the owner approved is undone. An auto match the owner flags stays in the DB."""
    owner = fresh_org()
    dashboard_id = _dashboard(client, owner, "bank-match-auto")
    out_id, _, bill_id = _seed(owner["org_id"])
    with SessionLocal() as db:
        txn = db.get(BankTransaction, out_id)
        txn.matched_entity_type, txn.matched_entity_id, txn.is_reconciled = "bill", bill_id, True
        db.commit()
    url = URL.format(dashboard_id)
    row = next(r for r in client.get(url, headers=owner["headers"], params=WINDOW).json()["rows"] if r["id"] == out_id)
    assert row["status"] == "open"
    assert row["auto_match"] == {"entity_type": "bill", "entity_id": bill_id}
    assert row["candidates"][0]["entity_id"] == bill_id

    flagged = client.post(url, headers=owner["headers"], json={"transaction_id": out_id, "action": "check"})
    assert flagged.status_code == 200, flagged.text
    with SessionLocal() as db:
        assert db.get(BankTransaction, out_id).is_reconciled is True
    approved = client.post(url, headers=owner["headers"], json={
        "transaction_id": out_id, "action": "approve", "entity_type": "bill", "entity_id": bill_id})
    assert approved.status_code == 200, approved.text


def test_approve_needs_a_document_and_cannot_cross_orgs(client, fresh_org):
    owner = fresh_org()
    other = fresh_org()
    dashboard_id = _dashboard(client, owner, "bank-match-guard")
    out_id, _, _ = _seed(owner["org_id"])
    _, foreign_fee, foreign_bill = _seed(other["org_id"])
    url = URL.format(dashboard_id)

    assert client.post(url, headers=owner["headers"], json={"transaction_id": out_id, "action": "approve"}).status_code == 422
    cross_doc = client.post(url, headers=owner["headers"], json={
        "transaction_id": out_id, "action": "approve", "entity_type": "bill", "entity_id": foreign_bill})
    assert cross_doc.status_code == 422
    cross_txn = client.post(url, headers=owner["headers"], json={"transaction_id": foreign_fee, "action": "check"})
    assert cross_txn.status_code == 422
    with SessionLocal() as db:
        assert db.get(BankTransaction, out_id).is_reconciled is not True


def test_public_link_reads_but_does_not_write(client, fresh_org):
    owner = fresh_org()
    dashboard_id = _dashboard(client, owner, "bank-match-public")
    client.patch(f"/api/dashboards/{dashboard_id}", headers=owner["headers"],
                 json={"status": "active", "access_mode": "public"})
    _seed(owner["org_id"])
    listed = client.get("/api/public/d/bank-match-public/bank-match", params=WINDOW)
    assert listed.status_code == 200, listed.text
    assert len(listed.json()["rows"]) == 2
    assert listed.json()["read_only"] is True
    assert "documents" not in listed.json()
    too_wide = client.get("/api/public/d/bank-match-public/bank-match", params={"start": "2026-01-01", "end": "2026-10-31"})
    assert too_wide.status_code == 422
    write = client.post("/api/public/d/bank-match-public/bank-match", json={"transaction_id": 1, "action": "check"})
    assert write.status_code in {404, 405}


def test_an_accountant_cannot_record_a_match_decision(client, fresh_org):
    from tests.test_dashboard_eliav_ui_r2 import _member
    owner = fresh_org()
    accountant = fresh_org()
    dashboard_id = _dashboard(client, owner, "bank-match-roles")
    _member(dashboard_id, accountant["org_id"], "accountant")
    _, fee_id, _ = _seed(owner["org_id"])
    screen = client.post(URL.format(dashboard_id), headers=accountant["headers"],
                         json={"transaction_id": fee_id, "action": "check"})
    assert screen.status_code in {403, 404}
    listed = client.get(URL.format(dashboard_id), headers=accountant["headers"], params=WINDOW)
    assert listed.status_code == 200 and listed.json()["read_only"] is True
    assert "documents" not in listed.json()
    with SessionLocal() as db:
        assert db.query(BankMatchDecision).filter_by(bank_transaction_id=fee_id).count() == 0


def test_a_returned_cheque_warns_of_double_income_and_names_the_same_amount_invoice(client, fresh_org):
    """Fixlist 11: a returned cheque next to an invoice of the same amount may be income counted twice."""
    from cfo.services.dashboards.bank_match import returned_cheque_warning
    txn, _ = _pair(1, -4321.0, "שיק חוזר")
    warning = returned_cheque_warning(txn, [MatchDoc("invoice", 7701, 4321.0, date(2026, 10, 1), "לקוח קפא")])
    assert warning["code"] == "returned_cheque"
    assert "לקוח קפא" in warning["label_he"] and "חשבונית #7701" in warning["label_he"]
    assert "פעמיים" in warning["label_he"]
    assert returned_cheque_warning(_pair(2, -4321.0, "העברה לספק")[0], []) is None
    bare = returned_cheque_warning(_pair(3, -500.0, "החזרת שיק")[0], [])
    assert bare is not None and "אין חשבונית" in bare["label_he"]

    owner = fresh_org()
    dashboard_id = _dashboard(client, owner, "bank-match-returned")
    with SessionLocal() as db:
        _bank(db, owner["org_id"], "ret-1", -4321, description="שיק חוזר")
        db.add(Invoice(organization_id=owner["org_id"], invoice_number="7701", issue_date=date(2026, 9, 1),
                       status=InvoiceStatus.PAID, total=4321, balance=0))
        db.commit()
    body = client.get(URL.format(dashboard_id), headers=owner["headers"], params=WINDOW).json()
    assert body["rows"][0]["warning"]["code"] == "returned_cheque"
    assert "מס׳ 7701" in body["rows"][0]["warning"]["label_he"]
    assert body["summary"]["warnings"] == 1
