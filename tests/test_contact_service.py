"""contact_service.py — resolve-or-create for SUMIT customer/vendor
references. Root-cause fix for a live data-integrity bug: DocumentManager.tsx
(and document_issuance_service.create_document) send a free-text customer
name directly as SUMIT's customer_id on every document issuance, with no
lookup against an existing Contact first. SUMIT's own by-name search
("SearchMode": "Automatic") can create a NEW customer record on every
slightly-different name spelling -- the likely root cause of the
"2095660683" ghost-customer artifact already tracked in Task #1. This
service is the fix: search existing contacts before falling back to
create-by-name, and persist whatever external_id SUMIT returns so the next
document for the same contact reuses it instead of searching by name again.
"""
from cfo.database import SessionLocal
from cfo.models import Contact, ContactType
from cfo.services.contact_service import resolve_or_create_contact, search_contacts


def test_search_contacts_matches_partial_name_case_insensitive(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        db.add(Contact(organization_id=org_id, name="Acme Ltd", contact_type=ContactType.CUSTOMER))
        db.add(Contact(organization_id=org_id, name="Other Co", contact_type=ContactType.CUSTOMER))
        db.commit()

        results = search_contacts(db, org_id, "acme")

        assert len(results) == 1
        assert results[0].name == "Acme Ltd"
    finally:
        db.close()


def test_search_contacts_is_org_scoped(fresh_org):
    org_a = fresh_org()["org_id"]
    org_b = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        db.add(Contact(organization_id=org_a, name="Shared Name Ltd", contact_type=ContactType.CUSTOMER))
        db.commit()

        results = search_contacts(db, org_b, "Shared Name")

        assert results == []
    finally:
        db.close()


def test_resolve_or_create_contact_reuses_existing_by_exact_name_match(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        existing = Contact(
            organization_id=org_id, name="Acme Ltd", contact_type=ContactType.CUSTOMER,
            external_id="sumit-123",
        )
        db.add(existing)
        db.commit()
        existing_id = existing.id

        contact = resolve_or_create_contact(db, org_id, name="Acme Ltd")

        assert contact.id == existing_id
        assert contact.external_id == "sumit-123"
        # No duplicate created.
        assert db.query(Contact).filter(Contact.organization_id == org_id).count() == 1
    finally:
        db.close()


def test_resolve_or_create_contact_creates_new_when_no_match(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        contact = resolve_or_create_contact(db, org_id, name="Brand New Customer")

        assert contact.id is not None
        assert contact.name == "Brand New Customer"
        assert contact.organization_id == org_id
        assert contact.external_id is None
    finally:
        db.close()


def test_resolve_or_create_contact_is_case_insensitive(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        existing = Contact(organization_id=org_id, name="Acme Ltd", contact_type=ContactType.CUSTOMER)
        db.add(existing)
        db.commit()
        existing_id = existing.id

        contact = resolve_or_create_contact(db, org_id, name="acme ltd")

        assert contact.id == existing_id
        assert db.query(Contact).filter(Contact.organization_id == org_id).count() == 1
    finally:
        db.close()
