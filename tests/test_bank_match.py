"""Bank match screen: one bank row ↔ one book document, with אשר / בדיקה / חסר מסמך.

A candidate is a suggestion. Only the owner's אשר matches a row. A row the
nightly auto-reconcile matched still waits for the owner. No candidate is
shown as none, not as 0. Coverage is signed: every bucket adds to the total.
"""
from datetime import date
from decimal import Decimal

from cfo.database import SessionLocal
from cfo.models import BankTransaction, Bill, DashboardPlan, Expense, Invoice
from cfo.services.bank_reconciliation import DocLite
from cfo.services.dashboards.bank_match import build_report
from cfo.services.dashboards.filing import Filed, Txn


def _pair(txn_id, amount, description="", debtor="", creditor="", when="2026-10-05", category="suppliers"):
    txn = Txn(txn_id, 1, None, when, amount, description, debtor, creditor)
    return txn, Filed(category, f"rule:{category}", category)


def test_an_outflow_gets_a_bill_candidate_and_an_inflow_gets_an_invoice():
    paired = [_pair(1, -1180.0, "תשלום", debtor="ספק אלפא"), _pair(2, 590.0, "העברה", creditor="לקוח בטא")]
    docs = [
        DocLite(10, "bill", 1180.0, date(2026, 10, 3), "ספק אלפא"),
        DocLite(11, "invoice", 1180.0, date(2026, 10, 3), "ספק אלפא"),
        DocLite(12, "invoice", 590.0, date(2026, 10, 4), "לקוח בטא"),
    ]
    report = build_report(paired, {}, {}, docs)
    rows = {row["id"]: row for row in report["rows"]}
    assert [c["entity_type"] for c in rows[1]["candidates"]] == ["bill"]
    assert rows[1]["candidates"][0]["entity_id"] == 10
    assert [c["entity_id"] for c in rows[2]["candidates"]] == [12]
    assert rows[1]["counterparty"] == "ספק אלפא"
    assert rows[1]["status"] == "open"


def test_no_candidate_is_none_not_zero():
    report = build_report([_pair(1, -77.0, "עמלה")], {}, {}, [])
    row = report["rows"][0]
    assert row["candidates"] == []
    assert row["status"] == "open"
    assert report["summary"]["open"]["count"] == 1


def test_auto_match_waits_for_the_owner_and_owner_approval_is_approved():
    paired = [_pair(1, -100.0), _pair(2, -200.0)]
    recon = {1: ("bill", 10), 2: ("bill", 20)}
    decisions = {"2": {"status": "approved", "entity_type": "bill", "entity_id": 20}}
    docs = [DocLite(10, "bill", 100.0, date(2026, 10, 5), "x"), DocLite(20, "bill", 200.0, date(2026, 10, 5), "y")]
    rows = {row["id"]: row for row in build_report(paired, recon, decisions, docs)["rows"]}
    assert rows[1]["status"] == "open"
    assert rows[1]["auto_match"] == {"entity_type": "bill", "entity_id": 10}
    assert rows[2]["status"] == "approved"
    assert rows[2]["matched"]["entity_id"] == 20


def test_an_auto_match_outside_the_tolerance_is_still_offered_unscored():
    docs = [DocLite(10, "bill", 900.0, date(2026, 10, 5), "x")]
    row = build_report([_pair(1, -1000.0)], {1: ("bill", 10)}, {}, docs)["rows"][0]
    assert row["candidates"] == [{
        "entity_type": "bill", "entity_id": 10, "score": None, "amount": 900.0, "date": "2026-10-05", "name": "x",
    }]


def test_a_stale_approval_without_the_db_match_is_open_again():
    rows = build_report([_pair(1, -100.0)], {}, {"1": {"status": "approved", "entity_type": "bill", "entity_id": 9}}, [])["rows"]
    assert rows[0]["status"] == "open"


def test_a_document_approved_on_another_row_is_not_offered_again():
    paired = [_pair(1, -100.0), _pair(2, -100.0)]
    recon = {1: ("bill", 10)}
    decisions = {"1": {"status": "approved", "entity_type": "bill", "entity_id": 10}}
    docs = [DocLite(10, "bill", 100.0, date(2026, 10, 5), "x")]
    rows = {row["id"]: row for row in build_report(paired, recon, decisions, docs)["rows"]}
    assert rows[2]["candidates"] == []


def test_summary_is_signed_and_balanced():
    paired = [_pair(1, -100.0), _pair(2, -50.0), _pair(3, 30.0), _pair(4, -5.0)]
    recon = {1: ("bill", 10)}
    decisions = {
        "1": {"status": "approved", "entity_type": "bill", "entity_id": 10},
        "2": {"status": "check", "note": "לבדוק מול הספק"},
        "3": {"status": "missing_doc"},
    }
    summary = build_report(paired, recon, decisions, [])["summary"]
    assert summary["approved"] == {"count": 1, "amount": -100.0}
    assert summary["check"] == {"count": 1, "amount": -50.0}
    assert summary["missing_doc"] == {"count": 1, "amount": 30.0}
    assert summary["open"] == {"count": 1, "amount": -5.0}
    assert summary["total"] == {"count": 4, "amount": -125.0}
    assert summary["balanced"] is True
    assert summary["done"] is False


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


def _dashboard(client, owner, slug):
    created = client.post("/api/dashboards", headers=owner["headers"], json={
        "primary_organization_id": owner["org_id"], "slug": slug, "title": "התאמה", "access_mode": "public",
    })
    assert created.status_code == 201, created.text
    return created.json()["id"]


def _seed(org_id):
    with SessionLocal() as db:
        out = BankTransaction(
            organization_id=org_id, transaction_date=date(2026, 10, 5), amount=Decimal("-1180"),
            description="תשלום לספק", source="open_finance", external_id="bm-out",
            raw_data={"status": "BOOKED", "creditorName": "ספק אלפא"},
        )
        fee = BankTransaction(
            organization_id=org_id, transaction_date=date(2026, 10, 6), amount=Decimal("-15"),
            description="עמלה", source="open_finance", external_id="bm-fee",
            raw_data={"status": "BOOKED"},
        )
        bill = Bill(organization_id=org_id, source="test", bill_number="B-1", issue_date=date(2026, 10, 3),
                    subtotal=1000, tax=180, total=1180, balance=1180)
        db.add_all([out, fee, bill])
        db.commit()
        return out.id, fee.id, bill.id


def test_owner_approves_flags_and_reopens(client, fresh_org):
    owner = fresh_org()
    dashboard_id = _dashboard(client, owner, "bank-match-flow")
    out_id, fee_id, bill_id = _seed(owner["org_id"])
    url = f"/api/dashboards/{dashboard_id}/bank-match"
    params = {"start": "2026-10-01", "end": "2026-10-31"}

    listed = client.get(url, headers=owner["headers"], params=params)
    assert listed.status_code == 200, listed.text
    body = listed.json()
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
        "transaction_id": fee_id, "action": "missing_doc", "note": "לבקש מהבנק",
        "amount": 1, "date": "1999-01-01",
    })
    assert missing.status_code == 200, missing.text

    with SessionLocal() as db:
        txn = db.get(BankTransaction, out_id)
        assert txn.is_reconciled is True and txn.matched_entity_id == bill_id
        stored = db.get(DashboardPlan, dashboard_id).payload["bankMatchDecisions"]
    assert stored[str(fee_id)]["amount"] == -15.0
    assert stored[str(fee_id)]["date"] == "2026-10-06"
    assert stored[str(fee_id)]["organizationId"] == owner["org_id"]
    assert stored[str(fee_id)]["note"] == "לבקש מהבנק"

    again = client.get(url, headers=owner["headers"], params=params).json()
    rows = {row["id"]: row for row in again["rows"]}
    assert rows[out_id]["status"] == "approved"
    assert rows[fee_id]["status"] == "missing_doc"
    assert again["summary"]["done"] is True

    reopened = client.post(url, headers=owner["headers"], json={"transaction_id": out_id, "action": "reopen"})
    assert reopened.status_code == 200, reopened.text
    with SessionLocal() as db:
        assert db.get(BankTransaction, out_id).is_reconciled is False
    final = {row["id"]: row for row in client.get(url, headers=owner["headers"], params=params).json()["rows"]}
    assert final[out_id]["status"] == "open"


def test_flagging_an_auto_matched_row_keeps_the_auto_match(client, fresh_org):
    """Only a match the owner approved is undone. An auto match the owner flags stays in the DB."""
    owner = fresh_org()
    dashboard_id = _dashboard(client, owner, "bank-match-auto")
    out_id, _, bill_id = _seed(owner["org_id"])
    with SessionLocal() as db:
        txn = db.get(BankTransaction, out_id)
        txn.matched_entity_type, txn.matched_entity_id, txn.is_reconciled = "bill", bill_id, True
        db.commit()
    url = f"/api/dashboards/{dashboard_id}/bank-match"
    params = {"start": "2026-10-01", "end": "2026-10-31"}
    row = next(r for r in client.get(url, headers=owner["headers"], params=params).json()["rows"] if r["id"] == out_id)
    assert row["status"] == "open"
    assert row["auto_match"] == {"entity_type": "bill", "entity_id": bill_id}

    flagged = client.post(url, headers=owner["headers"], json={"transaction_id": out_id, "action": "check"})
    assert flagged.status_code == 200, flagged.text
    with SessionLocal() as db:
        assert db.get(BankTransaction, out_id).is_reconciled is True


def test_approve_needs_a_document_and_cannot_cross_orgs(client, fresh_org):
    owner = fresh_org()
    other = fresh_org()
    dashboard_id = _dashboard(client, owner, "bank-match-guard")
    out_id, _, _ = _seed(owner["org_id"])
    _, foreign_fee, foreign_bill = _seed(other["org_id"])
    url = f"/api/dashboards/{dashboard_id}/bank-match"

    bare = client.post(url, headers=owner["headers"], json={"transaction_id": out_id, "action": "approve"})
    assert bare.status_code == 422
    cross_doc = client.post(url, headers=owner["headers"], json={
        "transaction_id": out_id, "action": "approve", "entity_type": "bill", "entity_id": foreign_bill,
    })
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
    listed = client.get("/api/public/d/bank-match-public/bank-match", params={"start": "2026-10-01", "end": "2026-10-31"})
    assert listed.status_code == 200, listed.text
    assert len(listed.json()["rows"]) == 2
    assert listed.json()["read_only"] is True
    write = client.post("/api/public/d/bank-match-public/bank-match", json={"transaction_id": 1, "action": "check"})
    assert write.status_code in {404, 405}


def test_an_accountant_cannot_record_a_match_decision(client, fresh_org):
    """The match screen and the generic plan PUT are both owner-only for match decisions."""
    from tests.test_dashboard_eliav_ui_r2 import _member, _put
    owner = fresh_org()
    accountant = fresh_org()
    dashboard_id = _dashboard(client, owner, "bank-match-roles")
    _member(dashboard_id, accountant["org_id"], "accountant")
    _, fee_id, _ = _seed(owner["org_id"])

    screen = client.post(f"/api/dashboards/{dashboard_id}/bank-match", headers=accountant["headers"],
                         json={"transaction_id": fee_id, "action": "check"})
    assert screen.status_code in {403, 404}
    listed = client.get(f"/api/dashboards/{dashboard_id}/bank-match", headers=accountant["headers"],
                        params={"start": "2026-10-01", "end": "2026-10-31"})
    assert listed.status_code == 200 and listed.json()["read_only"] is True
    forged = _put(client, accountant["headers"], dashboard_id, {"bankMatchDecisions": {str(fee_id): {
        "status": "check", "organizationId": owner["org_id"], "date": "2026-10-06", "amount": -15.0,
    }}})
    assert forged.status_code == 403 and forged.json()["error"]["code"] == "bank_match_forbidden"


def test_plan_validator_rejects_a_bad_match_decision():
    import pytest
    from cfo.services.dashboards.service import DashboardError, validate_filing_payload
    validate_filing_payload({"bankMatchDecisions": {"5": {
        "status": "check", "organizationId": 1, "date": "2026-10-01", "amount": -5.0,
    }}})
    for bad in (
        {"bankMatchDecisions": []},
        {"bankMatchDecisions": {"x": {"status": "check", "organizationId": 1, "date": "2026-10-01", "amount": 1}}},
        {"bankMatchDecisions": {"5": {"status": "guess", "organizationId": 1, "date": "2026-10-01", "amount": 1}}},
        {"bankMatchDecisions": {"5": {"status": "check", "organizationId": 1, "date": "2026-10-01", "amount": 1,
                                       "note": "x" * 301}}},
        {"bankMatchDecisions": {"5": {"status": "approved", "organizationId": 1, "date": "2026-10-01",
                                       "amount": 1, "entity_type": "payment", "entity_id": 3}}},
    ):
        with pytest.raises(DashboardError):
            validate_filing_payload(bad)
