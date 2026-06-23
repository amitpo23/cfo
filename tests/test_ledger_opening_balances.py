"""Opening balances (carry-forward) for the derived ledger."""
from datetime import date

from cfo.database import SessionLocal
from cfo.models import Invoice, InvoiceStatus
from cfo.services import ledger_service


def test_opening_entry_auto_plugs_to_equity(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        # Set a partial opening balance (only a bank asset) — must auto-balance to 3000.
        ledger_service.set_opening_balances(db, org_id, date(2026, 1, 1), [
            {"account": "1200", "debit": 50000, "credit": 0},
        ])
        e = ledger_service.opening_entry(db, org_id)
        assert e is not None and e.balanced
        # The plug landed in equity 3000 as a credit of 50000.
        plug = next(l for l in e.lines if l.account == "3000")
        assert plug.credit == 50000.0
    finally:
        db.close()


def test_trial_balance_includes_opening_and_stays_balanced(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        db.add(Invoice(organization_id=org_id, external_id="OB-INV", source="ob-test",
                       invoice_number="1", issue_date=date(2026, 3, 1),
                       status=InvoiceStatus.SENT, subtotal=1000, tax=180, total=1180))
        db.commit()
        ledger_service.set_opening_balances(db, org_id, date(2026, 1, 1), [
            {"account": "1200", "debit": 50000, "credit": 0},
            {"account": "3000", "debit": 0, "credit": 50000},
        ])
        tb = ledger_service.trial_balance(db, org_id)
        assert tb["balanced"] is True
        bank = next(a for a in tb["accounts"] if a["account"] == "1200")
        assert bank["debit"] >= 50000  # opening bank carried forward
        equity = next(a for a in tb["accounts"] if a["account"] == "3000")
        assert equity["credit"] == 50000.0
    finally:
        db.close()


def test_balance_sheet_reflects_opening_equity(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        ledger_service.set_opening_balances(db, org_id, date(2026, 1, 1), [
            {"account": "1200", "debit": 50000, "credit": 0},
            {"account": "3000", "debit": 0, "credit": 50000},
        ])
        bs = ledger_service.balance_sheet(db, org_id)
        assert bs["balanced"] is True
        assert bs["equity"]["opening_equity"] == 50000.0
        assert bs["total_equity_and_liabilities"] == bs["total_assets"]
    finally:
        db.close()


def test_opening_balance_routes_require_auth(client):
    assert client.get("/api/ledger/opening-balances").status_code == 403
    assert client.post("/api/ledger/opening-balances", json={}).status_code == 403


def test_opening_balance_roundtrip_via_route(client, fresh_org):
    iso = fresh_org()
    r = client.post("/api/ledger/opening-balances", headers=iso["headers"], json={
        "as_of": "2026-01-01",
        "balances": [{"account": "1200", "debit": 10000, "credit": 0},
                     {"account": "3000", "debit": 0, "credit": 10000}],
    })
    assert r.status_code == 200, r.text
    assert r.json()["count"] == 2
    g = client.get("/api/ledger/opening-balances", headers=iso["headers"])
    assert g.json()["count"] == 2
