"""Active office roster link. Dashboard access and account classification share this.

A file is managed by an office only while a ``SumitCompany`` row is active.
Classification adds a stricter wrapper: the office must be a different
organization, and the caller must be an active admin of that office.
"""
from __future__ import annotations

from ..models import SumitCompany


def office_manages(db, office_organization_id: int, organization_id: int) -> bool:
    """True when the office has an active roster row for the file."""
    if office_organization_id is None or organization_id is None:
        return False
    row = (
        db.query(SumitCompany)
        .filter_by(
            office_organization_id=office_organization_id,
            target_organization_id=organization_id,
            status="active",
        )
        .first()
    )
    return row is not None


def classifying_office_id(db, organization_id: int) -> int | None:
    """The newest active office that manages this file, when it is a different org.

    A file with no active link, or a link that points at itself, has no
    classifying office. Super-admin is not a substitute for that link.
    """
    row = (
        db.query(SumitCompany)
        .filter(
            SumitCompany.target_organization_id == organization_id,
            SumitCompany.status == "active",
            SumitCompany.office_organization_id.isnot(None),
            SumitCompany.office_organization_id != organization_id,
        )
        .order_by(SumitCompany.id.desc())
        .first()
    )
    if row is None or not office_manages(db, row.office_organization_id, organization_id):
        return None
    return int(row.office_organization_id)
