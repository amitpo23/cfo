"""Super-admin bind of an Open Finance consent that already exists.

The route does not start a consent journey and does not sync. The nightly
job remains the only caller that may build a connector, and it still has to
pass the 20-hour interval and the two-attempt budget.
"""
from datetime import date
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from ..dependencies import get_super_admin
from ...database import get_db_session
from ...models import User
from ...services.bank_coverage import OpenFinanceBindError, bind_existing_connection

router = APIRouter()


class CoverageBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    local_account_id: int
    covers_from: date
    bank_account_suffix: str = Field(pattern=r"^\d{4,20}$")


class BindBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    connection_id: str = Field(min_length=1, max_length=255)
    status: Literal["ACTIVE", "CONNECTED", "COMPLETED"]
    bank_name: Optional[str] = Field(default=None, max_length=255)
    provider_id: Optional[str] = Field(default=None, max_length=100)
    coverage: Optional[CoverageBody] = None


@router.post("/organizations/{org_id}/open-finance/bind")
def bind_open_finance_connection(
    org_id: int,
    body: BindBody,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_super_admin),
):
    coverage = body.coverage.model_dump() if body.coverage else None
    try:
        return bind_existing_connection(
            db,
            org_id,
            connection_id=body.connection_id,
            status=body.status,
            actor_id=current_user.id,
            bank_name=body.bank_name,
            provider_id=body.provider_id,
            coverage=coverage,
        )
    except OpenFinanceBindError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
