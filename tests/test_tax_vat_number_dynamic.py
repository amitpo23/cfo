"""פאזה 3 — ח.פ בדוחות/ייצוא SHAAM נטען דינמית מ-Organization.tax_id,
לא קשיח '123456789'. בלי זה ייצוא SHAAM אינו פונקציונלי.
"""
import pytest

from cfo.services.tax_service import TaxComplianceService


def test_company_vat_number_from_organization(fresh_org):
    from cfo.database import SessionLocal
    from cfo.models import Organization

    org = fresh_org()
    org_id = org["org_id"]
    db = SessionLocal()
    try:
        row = db.query(Organization).filter(Organization.id == org_id).first()
        row.tax_id = "514999996"
        db.commit()
    finally:
        db.close()

    db = SessionLocal()
    try:
        svc = TaxComplianceService(db, organization_id=org_id)
        assert svc.company_vat_number == "514999996"
        assert svc.company_vat_number != "123456789"
    finally:
        db.close()
