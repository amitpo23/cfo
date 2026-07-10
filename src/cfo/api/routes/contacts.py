"""
Contact search — backs the customer autocomplete used when issuing
documents, so a real Contact is found/reused instead of sending SUMIT a
free-text name on every call (see contact_service.py for the full
rationale).
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..dependencies import get_db, get_current_org_id
from ...services.contact_service import search_contacts

router = APIRouter(prefix="/contacts", tags=["Contacts"])


@router.get("")
async def list_contacts(
    query: str = Query(..., min_length=1),
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    results = search_contacts(db, org_id, query)
    return {
        "status": "success",
        "data": [
            {
                "id": c.id,
                "name": c.name,
                "email": c.email,
                "phone": c.phone,
                "contact_type": c.contact_type.value,
                "external_id": c.external_id,
            }
            for c in results
        ],
    }
