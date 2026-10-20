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

from ..dependencies import get_current_user, get_super_admin
from ...database import get_db_session
from ...models import User, UserRole
from ...services.bank_coverage import (
    OpenFinanceBindError,
    bind_existing_connection,
    classify_open_finance_account,
)
from ...services.membership_service import role_in
from ...services.sumit_request_budget import resolve_office_organization_id

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


class ClassificationBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    state: Literal["BOUND", "INDEPENDENT"]
    coverage_id: Optional[int] = None


def _require_office_admin(db: Session, user: User, org_id: int) -> None:
    if user.role == UserRole.SUPER_ADMIN:
        return
    office_id = resolve_office_organization_id(db, org_id)
    if role_in(db, user.id, office_id) != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Office admin required")


@router.post("/organizations/{org_id}/open-finance/accounts/{account_id}/classification")
def classify_open_finance_account_route(
    org_id: int,
    account_id: int,
    body: ClassificationBody,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
):
    """Office admin sets BOUND or INDEPENDENT. Not part of the public dashboard."""
    _require_office_admin(db, current_user, org_id)
    try:
        return classify_open_finance_account(
            db,
            org_id,
            account_id,
            state=body.state,
            coverage_id=body.coverage_id,
            actor_id=current_user.id,
        )
    except OpenFinanceBindError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
