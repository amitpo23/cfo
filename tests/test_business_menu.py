"""Tests for the per-business capability menu."""
from datetime import date

from cfo.database import SessionLocal
from cfo.models import Invoice, InvoiceStatus
from cfo.services import business_menu


def test_menu_structure_and_summary(fresh_org):
    org_id = fresh_org()["org_id"]
    menu = business_menu.build_menu(SessionLocal(), org_id)
    assert menu["organization_id"] == org_id
    assert menu["sections"], "expected capability sections"
    # Every section has capabilities; summary counts add up.
    total = sum(len(s["capabilities"]) for s in menu["sections"])
    assert menu["summary"]["total"] == total
    # The bank section is blocked without an Open Finance connection.
    bank = next(s for s in menu["sections"] if s["key"] == "bank")
    assert all(c["state"] == "blocked" for c in bank["capabilities"])


def test_menu_reflects_live_data(fresh_org):
    iso = fresh_org()
    org_id = iso["org_id"]
    db = SessionLocal()
    try:
        # With no documents, bookkeeping caps report needs_data.
        menu0 = business_menu.build_menu(db, org_id)
        book0 = next(s for s in menu0["sections"] if s["key"] == "bookkeeping")
        assert all(c["state"] == "needs_data" for c in book0["capabilities"])

        db.add(Invoice(organization_id=org_id, external_id="BM-1", source="bm-test",
                       invoice_number="1", issue_date=date(2026, 6, 1),
                       status=InvoiceStatus.SENT, subtotal=1000, tax=180, total=1180))
        db.commit()

        menu1 = business_menu.build_menu(db, org_id)
        book1 = next(s for s in menu1["sections"] if s["key"] == "bookkeeping")
        assert all(c["state"] == "ready" for c in book1["capabilities"])
        # AR ready (has invoices), payroll still needs employees.
        ar = next(s for s in menu1["sections"] if s["key"] == "receivables")
        assert all(c["state"] == "ready" for c in ar["capabilities"])
        payroll = next(s for s in menu1["sections"] if s["key"] == "payroll")
        assert all(c["state"] == "needs_data" for c in payroll["capabilities"])
    finally:
        db.close()


def test_menu_route_requires_auth(client):
    assert client.get("/api/business/menu").status_code == 403


def test_menu_route_for_default_org(client, owner):
    r = client.get("/api/business/menu", headers=owner["headers"])
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["connections"]["sumit"] is True  # default org has env SUMIT
    assert body["summary"]["total"] > 0
