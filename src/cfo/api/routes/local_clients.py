"""Import-only office client routes. Every operation is DB-only."""
from typing import Any
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session
from ..dependencies import get_current_org_id, require_admin
from ...database import get_db_session
from ...services import local_client_service

router = APIRouter()


class LocalClientRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=255)
    tax_id: str = Field(pattern=r"^\d{9}$")


@router.post("/office/clients/import-only")
def register_local_client(body: LocalClientRequest, office_id: int = Depends(get_current_org_id),
                          user=Depends(require_admin), db: Session = Depends(get_db_session)):
    try:
        return local_client_service.register_local_client(db, office_id, name=body.name,
                                                         tax_id=body.tax_id, actor_id=user.id)
    except ValueError as error:
        raise HTTPException(409, str(error)) from error


@router.get("/office/clients/daily-coverage")
def local_client_coverage(office_id: int = Depends(get_current_org_id),
                          user=Depends(require_admin), db: Session = Depends(get_db_session)):
    return local_client_service.local_client_coverage(db, office_id)


@router.post("/office/clients/{client_id}/reviewed-import")
def import_reviewed_source(client_id: int, body: dict[str, Any],
                           office_id: int = Depends(get_current_org_id),
                           user=Depends(require_admin), db: Session = Depends(get_db_session)):
    try:
        return local_client_service.import_reviewed_source(db, office_id, client_id, body, actor_id=user.id)
    except ValueError as error:
        raise HTTPException(409, str(error)) from error
