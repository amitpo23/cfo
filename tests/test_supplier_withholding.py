"""Supplier withholding (Form 856) — computed from documents by per-supplier rate."""
from datetime import date

from cfo.database import SessionLocal
from cfo.models import Expense, Contact, ContactType
from cfo.services.tax_service import TaxComplianceService


def _seed(org_id):
    db = SessionLocal()
    try:
        for model in (Expense, Contact):
            db.query(model).filter(model.organization_id == org_id,
                                   model.source == "wh-test").delete()
        db.commit()
        # One supplier with withholding, one exempt (rate 0 default).
        sup_wh = Contact(organization_id=org_id, source="wh-test", name="ספק ללא אישור",
                         contact_type=ContactType.VENDOR, tax_id="111111111",
                         withholding_rate=0.30)
        sup_ok = Contact(organization_id=org_id, source="wh-test", name="ספק עם אישור",
                         contact_type=ContactType.VENDOR, tax_id="222222222",
                         withholding_rate=0)
        db.add_all([sup_wh, sup_ok]); db.commit()
        db.add(Expense(organization_id=org_id, source="wh-test", supplier_id=sup_wh.id,
                       supplier_name="ספק ללא אישור", supplier_tax_id="111111111",
                       amount=10000, vat_amount=1800, total=11800,
                       expense_date=date(2026, 5, 10), status="filed"))
        db.add(Expense(organization_id=org_id, source="wh-test", supplier_id=sup_ok.id,
                       supplier_name="ספק עם אישור", supplier_tax_id="222222222",
                       amount=5000, vat_amount=900, total=5900,
                       expense_date=date(2026, 5, 12), status="filed"))
        db.commit()
    finally:
        db.close()


def test_withholding_only_for_flagged_suppliers(fresh_org):
    org_id = fresh_org()["org_id"]
    _seed(org_id)
    db = SessionLocal()
    try:
        svc = TaxComplianceService(db, organization_id=org_id)
        rows = svc._get_supplier_withholding(2026, 5)
        # Only the 30% supplier is reported; the exempt one is excluded.
        assert len(rows) == 1
        assert rows[0]["tax_id"] == "111111111"
        assert rows[0]["withholding"] == 3000.0  # 10000 * 0.30
    finally:
        db.close()


def test_generate_856_annual_summary(fresh_org):
    org_id = fresh_org()["org_id"]
    _seed(org_id)
    db = SessionLocal()
    try:
        svc = TaxComplianceService(db, organization_id=org_id)
        rep = svc.generate_856(2026)
        assert rep["draft"] is True
        assert rep["supplier_count"] == 1
        assert rep["total_withholding"] == 3000.0
        assert rep["suppliers"][0]["tax_id"] == "111111111"
    finally:
        db.close()


def test_856_route_and_set_rate(client, fresh_org):
    iso = fresh_org()
    org_id = iso["org_id"]
    db = SessionLocal()
    try:
        c = Contact(organization_id=org_id, source="wh-test", name="ספק",
                    contact_type=ContactType.VENDOR, tax_id="333", withholding_rate=0)
        db.add(c); db.commit()
        cid = c.id
    finally:
        db.close()
    # Set the rate via route.
    r = client.post(f"/api/financial/contacts/{cid}/withholding-rate?rate=0.3", headers=iso["headers"])
    assert r.status_code == 200, r.text
    assert r.json()["withholding_rate"] == 0.3
    # 856 route responds.
    r2 = client.get("/api/financial/tax/856?year=2026", headers=iso["headers"])
    assert r2.status_code == 200, r2.text
    assert r2.json()["data"]["form"] == "856"


def test_856_route_requires_auth(client):
    assert client.get("/api/financial/tax/856?year=2026").status_code == 403
