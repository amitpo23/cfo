"""A bank-match decision is final for every writer and suggester, not only the readers.

Round 3 taught the readers (open payables, aging, contact card, gap, collection)
that a 1:N or category decision settles its documents. The older match paths
did not ask: the manual reconciliation route and the CFO dashboard's
apply_bank_reconciliation could clear or overwrite a bank row that holds a
decision, and match a settled document to a second bank row, which then
looks explained. The suggesters offered settled documents again, and the
synthesis worklist asked to collect an invoice the owner matched 1:N.

The match screen is the one path that changes a decision (reopen there).
All amounts and names are made up.
"""
from datetime import date
from decimal import Decimal

import pytest

from cfo.database import SessionLocal
from cfo.models import BankTransaction
from tests.test_bank_match_consumers import _bank, _seed_and_approve


def _second_charge(org_id, amount=-1180):
    """An unreconciled BOOKED row with exactly one settled bill's amount, the day after the charge."""
    with SessionLocal() as db:
        txn = _bank(db, org_id, "tc-again", amount, date(2026, 10, 16), "חיוב ספק")
        db.commit()
        return txn.id


def test_the_manual_route_cannot_clear_or_overwrite_a_decision(fresh_org):
    from cfo.services.manual_reconciliation import ManualReconciliationService
    org_id = fresh_org()["org_id"]
    ids = _seed_and_approve(org_id)
    with SessionLocal() as db:
        service = ManualReconciliationService(db, org_id)
        for key in ("charge", "payroll"):
            with pytest.raises(ValueError, match="התאמת בנק"):
                service.unmatch_transaction(ids[key])
            with pytest.raises(ValueError, match="התאמת בנק"):
                service.match_transaction(ids[key], "bill", ids["bills"][0])
        db.rollback()
        for key in ("charge", "payroll"):
            row = db.get(BankTransaction, ids[key])
            assert (row.is_reconciled, row.matched_entity_type) == (True, "bank_match")


def test_apply_bank_reconciliation_cannot_overwrite_a_decision(fresh_org):
    from cfo.services.financial_control_service import FinancialControlService
    org_id = fresh_org()["org_id"]
    ids = _seed_and_approve(org_id)
    with SessionLocal() as db:
        with pytest.raises(ValueError, match="התאמת בנק"):
            FinancialControlService(db, org_id).apply_bank_reconciliation(ids["deposit"], "invoice", ids["invoices"][0])
        db.rollback()
        assert db.get(BankTransaction, ids["deposit"]).matched_entity_type == "bank_match"


def test_a_settled_document_cannot_be_matched_to_a_second_bank_row(fresh_org):
    from cfo.services.financial_control_service import FinancialControlService
    from cfo.services.manual_reconciliation import ManualReconciliationService
    org_id = fresh_org()["org_id"]
    ids = _seed_and_approve(org_id)
    again = _second_charge(org_id)
    with SessionLocal() as db:
        with pytest.raises(ValueError, match="כבר מותאם"):
            ManualReconciliationService(db, org_id).match_transaction(again, "bill", ids["bills"][0])
        with pytest.raises(ValueError, match="כבר מותאם"):
            FinancialControlService(db, org_id).apply_bank_reconciliation(again, "bill", ids["bills"][1])
        db.rollback()
        assert db.get(BankTransaction, again).is_reconciled is False


def test_a_reopened_decision_frees_its_documents_for_the_manual_route(fresh_org):
    from cfo.services.dashboards.bank_match import decide
    from cfo.services.manual_reconciliation import ManualReconciliationService
    org_id = fresh_org()["org_id"]
    ids = _seed_and_approve(org_id)
    again = _second_charge(org_id)
    with SessionLocal() as db:
        decide(db, org_id, None, {"transaction_id": ids["charge"], "action": "reopen"})
        db.commit()
        result = ManualReconciliationService(db, org_id).match_transaction(again, "bill", ids["bills"][0])
    assert result["status"] == "matched"


def test_suggesters_do_not_offer_a_settled_document(fresh_org):
    from cfo.services.bank_reconciliation import reconcile_organization
    from cfo.services.financial_control_service import FinancialControlService
    from cfo.services.manual_reconciliation import ManualReconciliationService
    org_id = fresh_org()["org_id"]
    ids = _seed_and_approve(org_id)
    again = _second_charge(org_id)
    settled = {("bill", bill_id) for bill_id in ids["bills"]} | {("invoice", i) for i in ids["invoices"]}
    with SessionLocal() as db:
        manual = ManualReconciliationService(db, org_id).suggest_matches(again)
        control = FinancialControlService(db, org_id).suggest_bank_reconciliations(
            start_date=date(2026, 10, 1), end_date=date(2026, 10, 31))
        heuristic = reconcile_organization(db, org_id, persist=False)
    assert not {(c["entity_type"], c["entity_id"]) for c in manual} & settled
    offered = {(c["entity_type"], c["entity_id"]) for s in control for c in s["candidates"]}
    assert not offered & settled
    assert not {(c["entity_type"], c["entity_id"]) for c in heuristic["candidates"]} & settled
    assert not {(d["entity_type"], d["entity_id"]) for d in heuristic["unmatched_docs"]} & settled


def test_the_synthesis_worklist_does_not_chase_documents_matched_one_to_many(fresh_org):
    from cfo.services.financial_synthesis import synthesize_organization
    org_id = fresh_org()["org_id"]
    ids = _seed_and_approve(org_id)
    with SessionLocal() as db:
        result = synthesize_organization(db, org_id)
    chased = {(a["type"], tuple(sorted(a["refs"].items()))) for a in result["required_actions"]}
    for invoice_id in ids["invoices"]:
        assert ("collect_receivable", (("invoice_id", invoice_id),)) not in chased
    for bill_id in ids["bills"]:
        assert ("pay_payable", (("bill_id", bill_id),)) not in chased


def test_the_synthesis_worklist_still_chases_an_unmatched_invoice(fresh_org):
    """Control: an open invoice nobody matched is still asked about."""
    from cfo.models import Contact, ContactType, Invoice, InvoiceStatus
    from cfo.services.financial_synthesis import synthesize_organization
    org_id = fresh_org()["org_id"]
    _seed_and_approve(org_id)
    with SessionLocal() as db:
        other = Contact(organization_id=org_id, name="לקוח פתוח", contact_type=ContactType.CUSTOMER)
        db.add(other)
        db.flush()
        open_invoice = Invoice(organization_id=org_id, contact_id=other.id, invoice_number="T-9",
                               issue_date=date(2026, 9, 1), due_date=date(2026, 9, 15), status=InvoiceStatus.OVERDUE,
                               subtotal=Decimal("900"), tax=0, total=Decimal("900"), balance=Decimal("900"))
        db.add(open_invoice)
        db.commit()
        result = synthesize_organization(db, org_id)
    assert any(a["type"] == "collect_receivable" and a["refs"] == {"invoice_id": open_invoice.id}
               for a in result["required_actions"])
