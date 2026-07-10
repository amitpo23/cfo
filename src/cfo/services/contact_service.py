"""Resolve-or-create for customer/vendor contacts.

Root-cause fix for a live data-integrity bug: document issuance sent a
free-text customer name directly as SUMIT's customer_id on every call, with
no lookup against an existing Contact first. SUMIT's by-name search
("SearchMode": "Automatic") can create a new customer record on any
slightly-different spelling -- this is the likely source of the
"2095660683" ghost-customer artifact tracked in Task #1. Callers should
search/resolve a Contact first, use its external_id (if SUMIT already knows
it) instead of a free-text name, and persist whatever external_id SUMIT
returns so the next document reuses it instead of searching by name again.
"""
from __future__ import annotations

from typing import List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import Contact, ContactType


def search_contacts(
    db: Session,
    organization_id: int,
    query: str,
    *,
    contact_type: Optional[ContactType] = None,
    limit: int = 20,
) -> List[Contact]:
    """Case-insensitive partial-name search, scoped to one organization."""
    q = db.query(Contact).filter(
        Contact.organization_id == organization_id,
        Contact.name.ilike(f"%{query}%"),
    )
    if contact_type is not None:
        q = q.filter(Contact.contact_type == contact_type)
    return q.order_by(Contact.name.asc()).limit(limit).all()


def resolve_or_create_contact(
    db: Session,
    organization_id: int,
    *,
    name: str,
    email: Optional[str] = None,
    phone: Optional[str] = None,
    contact_type: ContactType = ContactType.CUSTOMER,
) -> Contact:
    """Reuse an existing contact by exact (case-insensitive) name match
    within the organization; create one only if nothing matches."""
    existing = (
        db.query(Contact)
        .filter(
            Contact.organization_id == organization_id,
            func.lower(Contact.name) == name.strip().lower(),
        )
        .first()
    )
    if existing:
        return existing

    contact = Contact(
        organization_id=organization_id,
        name=name.strip(),
        email=email,
        phone=phone,
        contact_type=contact_type,
    )
    db.add(contact)
    db.flush()
    return contact
