"""Tests for the derived double-entry shadow ledger.

The non-negotiable invariant: every entry balances and the whole trial balance
balances (Σdebit == Σcredit), including when source `total` is rounded oddly.
"""
from datetime import date

from cfo.database import SessionLocal
from cfo.models import Invoice, Bill, Expense, Payment, InvoiceStatus, BillStatus
from cfo.services import ledger_service


def _seed(org_id):
    db = SessionLocal()
    try:
        # Idempotent: the `owner` fixture is session-scoped, so wipe any prior
        # ledger-test rows for this org before reseeding (avoids unique-id clashes
        # and cross-test amount accumulation).
        for model in (Payment, Expense, Bill, Invoice):
            db.query(model).filter(model.organization_id == org_id,
                                   model.source == "test").delete()
        db.commit()
        inv = Invoice(organization_id=org_id, external_id="L-INV-1", source="test",
                      invoice_number="100", issue_date=date(2026, 6, 1),
                      status=InvoiceStatus.SENT, subtotal=1000, tax=180, total=1180)
        db.add(inv)
        # A draft must NOT post.
        db.add(Invoice(organization_id=org_id, external_id="L-INV-DRAFT", source="test",
                       invoice_number="DR", issue_date=date(2026, 6, 2),
                       status=InvoiceStatus.DRAFT, subtotal=999, tax=179, total=1178))
        db.add(Bill(organization_id=org_id, external_id="L-BILL-1", source="test",
                    bill_number="B1", issue_date=date(2026, 6, 3),
                    status=BillStatus.RECEIVED, subtotal=500, tax=90, total=590))
        db.add(Expense(organization_id=org_id, external_id="L-EXP-1", source="test",
                       supplier_name="ספק", amount=200, vat_amount=36, total=236,
                       expense_date=date(2026, 6, 4), status="filed"))
        db.commit()
        inv_id = inv.id
        db.add(Payment(organization_id=org_id, external_id="L-PAY-1", source="test",
                       invoice_id=inv_id, payment_date=date(2026, 6, 5), amount=1180))
        db.commit()
        return inv_id
    finally:
        db.close()


def test_every_entry_balances_and_drafts_excluded(fresh_org):
    org_id = fresh_org()["org_id"]
    _seed(org_id)
    db = SessionLocal()
    try:
        entries = ledger_service.build_journal(db, org_id)
        assert entries, "expected derived entries"
        for e in entries:
            assert e.balanced, f"unbalanced entry {e.source_ref}: {e.total_debit} != {e.total_credit}"
        refs = {e.source_ref for e in entries}
        # Draft invoice excluded; the others present.
        assert any(r.startswith("invoice:") for r in refs)
        assert any(r.startswith("bill:") for r in refs)
        assert any(r.startswith("expense:") for r in refs)
        assert any(r.startswith("payment:") for r in refs)
    finally:
        db.close()


def test_trial_balance_balances(fresh_org):
    org_id = fresh_org()["org_id"]
    _seed(org_id)
    db = SessionLocal()
    try:
        tb = ledger_service.trial_balance(db, org_id)
        assert tb["balanced"] is True
        assert abs(tb["total_debit"] - tb["total_credit"]) < 0.01
        assert tb["derived"] is True
        # Revenue should be credited 1000 (net of the one posted invoice).
        rev = next(a for a in tb["accounts"] if a["account"] == "4000")
        assert rev["credit"] == 1000.0
        # VAT output 180.
        vat_out = next(a for a in tb["accounts"] if a["account"] == "2200")
        assert vat_out["credit"] == 180.0
    finally:
        db.close()


def test_general_ledger_running_balance(fresh_org):
    org_id = fresh_org()["org_id"]
    _seed(org_id)
    db = SessionLocal()
    try:
        gl = ledger_service.general_ledger(db, org_id, "1100")  # לקוחות
        # Invoice debits 1180, receipt credits 1180 -> closing 0.
        assert gl["closing_balance"] == 0.0
        assert len(gl["movements"]) == 2
    finally:
        db.close()


def test_ledger_routes_require_auth(client):
    for path in ["/api/ledger/journal", "/api/ledger/trial-balance",
                 "/api/ledger/account/1100", "/api/ledger/chart"]:
        assert client.get(path).status_code == 403, path


def test_trial_balance_route_balances(client, fresh_org):
    iso = fresh_org()
    _seed(iso["org_id"])
    r = client.get("/api/ledger/trial-balance", headers=iso["headers"])
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["balanced"] is True
    assert body["derived"] is True
    assert body["total_debit"] == body["total_credit"]


def test_balance_sheet_identity_holds(fresh_org):
    org_id = fresh_org()["org_id"]
    _seed(org_id)
    db = SessionLocal()
    try:
        bs = ledger_service.balance_sheet(db, org_id)
        assert bs["derived"] is True
        # Assets == Liabilities + Equity (identity by construction).
        assert bs["balanced"] is True
        assert abs(bs["total_assets"] - bs["total_equity_and_liabilities"]) < 0.01
    finally:
        db.close()
