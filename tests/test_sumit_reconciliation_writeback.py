"""Tests for the SUMIT bank-reconciliation write-back — closing the third leg of
the bank <-> insights <-> SUMIT loop (Open Finance dispatch_reconciliation_to_sumit
-> SumitConnector.post_bank_reconciliation), gated through the durable
IrreversibleActionService control plane per AGENTS.md's "zero autonomy on
irreversible actions" doctrine.

Covers three layers:
  1. SumitConnector.post_bank_reconciliation — the raw write (customer remark),
     unit-tested against a stubbed SumitIntegration client.
  2. reconciliation_dispatch._load_entity — resolves contact_external_id /
     document_number for invoice/bill/expense matched entities.
  3. reconciliation_dispatch.dispatch_reconciliation_to_sumit — the approval
     control-plane gating: propose -> pending_approval -> (owner approves) ->
     confirmed, or -> unsupported when rejected/no-contact/no-actor.
"""
from datetime import date
from decimal import Decimal

import pytest

from cfo.database import SessionLocal
from cfo.models import (
    Bill, BillStatus, BankTransaction, Contact, ContactType, Expense, Invoice,
    InvoiceStatus, User,
)
from cfo.services import reconciliation_dispatch
from cfo.services.irreversible_action_service import IrreversibleActionService
from cfo.services.sumit_connector import SumitConnector


# --------------------------------------------------------------------- #
# 1. SumitConnector.post_bank_reconciliation
# --------------------------------------------------------------------- #
def test_post_bank_reconciliation_raises_when_no_contact():
    """Honest-null: nothing in SUMIT to write a remark against."""
    connector = SumitConnector(api_key="k", company_id="c")
    payload = {
        "bank_transaction": {"id": 1, "date": "2026-06-01", "amount": 500, "currency": "ILS", "description": "x"},
        "matched_entity": {"type": "invoice", "id": 1, "contact_external_id": None},
    }
    with pytest.raises(NotImplementedError, match="contact"):
        import asyncio
        asyncio.run(connector.post_bank_reconciliation(payload))


def test_post_bank_reconciliation_calls_create_customer_remark(monkeypatch):
    """With a contact_external_id, posts a remark via SumitIntegration.create_customer_remark."""
    import asyncio

    from cfo.integrations.sumit_models import CustomerRemarkRequest

    captured = {}

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def create_customer_remark(self, remark: CustomerRemarkRequest):
            captured["customer_id"] = remark.customer_id
            captured["remark"] = remark.remark
            return {"RemarkID": 4242}

    connector = SumitConnector(api_key="k", company_id="c")

    async def fake_get_client():
        return FakeClient()

    monkeypatch.setattr(connector, "_get_client", fake_get_client)

    payload = {
        "bank_transaction": {
            "id": 7, "date": "2026-06-01", "amount": 500, "currency": "ILS",
            "description": "תשלום מלקוח",
        },
        "matched_entity": {
            "type": "invoice", "id": 3, "contact_external_id": "SUMIT-CUST-9",
            "document_number": "INV-100",
        },
    }
    result = asyncio.run(connector.post_bank_reconciliation(payload))

    assert result["RemarkID"] == 4242
    assert captured["customer_id"] == "SUMIT-CUST-9"
    assert "7" in captured["remark"]
    assert "INV-100" in captured["remark"]


# --------------------------------------------------------------------- #
# 2. reconciliation_dispatch._load_entity — contact/document resolution
# --------------------------------------------------------------------- #
def test_load_entity_resolves_contact_external_id_for_invoice(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        contact = Contact(
            organization_id=org_id, external_id="SUMIT-CUST-1", contact_type=ContactType.CUSTOMER,
            name="לקוח בדיקה",
        )
        db.add(contact)
        db.flush()
        inv = Invoice(
            organization_id=org_id, external_id="SUMIT-INV-LOAD", source="sumit",
            contact_id=contact.id, invoice_number="INV-500",
            issue_date=date.today(), status=InvoiceStatus.SENT, total=Decimal("500"), balance=Decimal("500"),
        )
        db.add(inv)
        db.flush()
        txn = BankTransaction(
            organization_id=org_id, matched_entity_type="invoice", matched_entity_id=inv.id,
            transaction_date=date.today(), amount=Decimal("500"), currency="ILS",
        )
        db.add(txn)
        db.commit()

        entity = reconciliation_dispatch._load_entity(db, txn)
        assert entity["contact_external_id"] == "SUMIT-CUST-1"
        assert entity["document_number"] == "INV-500"
    finally:
        db.close()


def test_load_entity_resolves_contact_external_id_for_bill(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        contact = Contact(
            organization_id=org_id, external_id="SUMIT-VENDOR-1", contact_type=ContactType.VENDOR,
            name="ספק בדיקה",
        )
        db.add(contact)
        db.flush()
        bill = Bill(
            organization_id=org_id, vendor_id=contact.id, bill_number="BILL-77",
            status=BillStatus.RECEIVED, issue_date=date.today(), total=Decimal("300"),
        )
        db.add(bill)
        db.flush()
        txn = BankTransaction(
            organization_id=org_id, matched_entity_type="bill", matched_entity_id=bill.id,
            transaction_date=date.today(), amount=Decimal("-300"), currency="ILS",
        )
        db.add(txn)
        db.commit()

        entity = reconciliation_dispatch._load_entity(db, txn)
        assert entity["contact_external_id"] == "SUMIT-VENDOR-1"
        assert entity["document_number"] == "BILL-77"
    finally:
        db.close()


def test_load_entity_returns_none_contact_external_id_when_document_has_no_contact(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        inv = Invoice(
            organization_id=org_id, external_id="SUMIT-INV-NOCONTACT", source="sumit",
            issue_date=date.today(), status=InvoiceStatus.SENT, total=Decimal("500"), balance=Decimal("500"),
        )
        db.add(inv)
        db.flush()
        txn = BankTransaction(
            organization_id=org_id, matched_entity_type="invoice", matched_entity_id=inv.id,
            transaction_date=date.today(), amount=Decimal("500"), currency="ILS",
        )
        db.add(txn)
        db.commit()

        entity = reconciliation_dispatch._load_entity(db, txn)
        assert entity["contact_external_id"] is None
    finally:
        db.close()


# --------------------------------------------------------------------- #
# 3. dispatch_reconciliation_to_sumit — approval control-plane gating
# --------------------------------------------------------------------- #
def _seed_matched_txn_with_contact(db, org_id, *, external_id_suffix="A"):
    contact = Contact(
        organization_id=org_id, external_id=f"SUMIT-CUST-{external_id_suffix}",
        contact_type=ContactType.CUSTOMER, name="לקוח",
    )
    db.add(contact)
    db.flush()
    inv = Invoice(
        organization_id=org_id, external_id=f"SUMIT-INV-{external_id_suffix}", source="sumit",
        contact_id=contact.id, issue_date=date(2026, 6, 4), status=InvoiceStatus.SENT,
        total=Decimal("1170"), balance=Decimal("1170"),
    )
    txn = BankTransaction(
        organization_id=org_id, external_id=f"OF-TXN-{external_id_suffix}", source="open_finance",
        transaction_date=date(2026, 6, 5), description="תשלום מאת לקוח", amount=Decimal("1170"),
        currency="ILS",
    )
    db.add_all([inv, txn])
    db.commit()
    return txn


class _FakeConnector:
    """Stubbed SUMIT connector — no real network calls."""

    def __init__(self, response=None, error=None):
        self.response = response if response is not None else {"RemarkID": 555}
        self.error = error
        self.calls = []

    async def post_bank_reconciliation(self, payload):
        self.calls.append(payload)
        if self.error is not None:
            raise self.error
        return self.response


def _patch_connector(monkeypatch, connector):
    def fake_get_connector_for_org(db, org_id, preferred_source=None):
        return connector, None, "sumit"

    monkeypatch.setattr(reconciliation_dispatch, "get_connector_for_org", fake_get_connector_for_org)


def test_dispatch_marks_unsupported_without_actor_even_with_contact(fresh_org, monkeypatch):
    """Zero-autonomy: no authenticated actor means no proposal can be made —
    fail closed to `unsupported`, never silently write to SUMIT."""
    org_id = fresh_org()["org_id"]
    _patch_connector(monkeypatch, _FakeConnector())
    db = SessionLocal()
    try:
        txn = _seed_matched_txn_with_contact(db, org_id)

        import asyncio
        result = asyncio.run(
            reconciliation_dispatch.dispatch_reconciliation_to_sumit(db, org_id, actor=None)
        )
        assert result["unsupported"] == 1

        db.refresh(txn)
        assert txn.reconciliation_dispatch_status == "unsupported"
        assert "actor" in txn.reconciliation_error
    finally:
        db.close()


def test_dispatch_proposes_and_marks_pending_approval(fresh_org, monkeypatch):
    org_id = fresh_org()["org_id"]
    _patch_connector(monkeypatch, _FakeConnector())
    db = SessionLocal()
    try:
        txn = _seed_matched_txn_with_contact(db, org_id)
        actor = db.query(User).filter(User.organization_id == org_id).first()

        import asyncio
        result = asyncio.run(
            reconciliation_dispatch.dispatch_reconciliation_to_sumit(db, org_id, actor=actor)
        )
        assert result["pending_approval"] == 1
        assert result["confirmed"] == 0

        db.refresh(txn)
        assert txn.reconciliation_dispatch_status == "pending_approval"

        action_service = IrreversibleActionService(db, org_id)
        actions = action_service.list(status="proposed")
        assert len(actions) == 1
        assert actions[0].action_type == "sumit_writeback"
    finally:
        db.close()


def test_dispatch_confirms_after_owner_approves(fresh_org, monkeypatch):
    """Second dispatch run, after the owner approves the proposed action,
    actually calls SUMIT (via the stubbed connector) and marks the row confirmed."""
    org_id = fresh_org()["org_id"]
    fake = _FakeConnector(response={"RemarkID": 999})
    _patch_connector(monkeypatch, fake)
    db = SessionLocal()
    try:
        txn = _seed_matched_txn_with_contact(db, org_id)
        actor = db.query(User).filter(User.organization_id == org_id).first()

        import asyncio
        asyncio.run(reconciliation_dispatch.dispatch_reconciliation_to_sumit(db, org_id, actor=actor))

        action_service = IrreversibleActionService(db, org_id)
        proposed = action_service.list(status="proposed")[0]
        action_service.approve(proposed.id, approved_by=actor)

        result = asyncio.run(
            reconciliation_dispatch.dispatch_reconciliation_to_sumit(db, org_id, actor=actor)
        )
        assert result["confirmed"] == 1
        assert len(fake.calls) == 1

        db.refresh(txn)
        assert txn.reconciliation_dispatch_status == "confirmed"
        assert txn.external_reconciliation_id == "999"

        action = action_service.get(proposed.id)
        assert action.status == "executed"
        assert action.provider_reference == "999"

        # Third run: idempotent, does not re-call SUMIT.
        result2 = asyncio.run(
            reconciliation_dispatch.dispatch_reconciliation_to_sumit(db, org_id, actor=actor)
        )
        assert result2["confirmed"] == 1
        assert len(fake.calls) == 1
    finally:
        db.close()


def test_dispatch_marks_unsupported_after_owner_rejects(fresh_org, monkeypatch):
    org_id = fresh_org()["org_id"]
    _patch_connector(monkeypatch, _FakeConnector())
    db = SessionLocal()
    try:
        txn = _seed_matched_txn_with_contact(db, org_id)
        actor = db.query(User).filter(User.organization_id == org_id).first()

        import asyncio
        asyncio.run(reconciliation_dispatch.dispatch_reconciliation_to_sumit(db, org_id, actor=actor))

        action_service = IrreversibleActionService(db, org_id)
        proposed = action_service.list(status="proposed")[0]
        action_service.reject(proposed.id, rejected_by=actor, reason="לא רלוונטי")

        result = asyncio.run(
            reconciliation_dispatch.dispatch_reconciliation_to_sumit(db, org_id, actor=actor)
        )
        assert result["unsupported"] == 1

        db.refresh(txn)
        assert txn.reconciliation_dispatch_status == "unsupported"
        assert txn.reconciliation_error == "לא רלוונטי"
    finally:
        db.close()


def test_dispatch_marks_failed_when_connector_errors_after_approval(fresh_org, monkeypatch):
    org_id = fresh_org()["org_id"]
    fake = _FakeConnector(error=RuntimeError("SUMIT 500"))
    _patch_connector(monkeypatch, fake)
    db = SessionLocal()
    try:
        txn = _seed_matched_txn_with_contact(db, org_id)
        actor = db.query(User).filter(User.organization_id == org_id).first()

        import asyncio
        asyncio.run(reconciliation_dispatch.dispatch_reconciliation_to_sumit(db, org_id, actor=actor))

        action_service = IrreversibleActionService(db, org_id)
        proposed = action_service.list(status="proposed")[0]
        action_service.approve(proposed.id, approved_by=actor)

        result = asyncio.run(
            reconciliation_dispatch.dispatch_reconciliation_to_sumit(db, org_id, actor=actor)
        )
        assert result["failed"] == 1

        db.refresh(txn)
        assert txn.reconciliation_dispatch_status == "failed"
        assert "SUMIT 500" in txn.reconciliation_error

        action = action_service.get(proposed.id)
        assert action.status == "failed"
    finally:
        db.close()


def test_dispatch_route_requires_auth(client):
    r = client.post("/api/open-finance/reconcile/sumit-dispatch")
    assert r.status_code == 403


def test_dispatch_route_wires_actor_and_reaches_pending_approval(client, fresh_org, monkeypatch):
    org = fresh_org()
    _patch_connector(monkeypatch, _FakeConnector())
    db = SessionLocal()
    try:
        _seed_matched_txn_with_contact(db, org["org_id"])
    finally:
        db.close()

    r = client.post("/api/open-finance/reconcile/sumit-dispatch", headers=org["headers"])
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["pending_approval"] == 1
