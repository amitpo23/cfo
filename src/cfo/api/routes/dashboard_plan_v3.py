"""GET/PUT the version-3 client dashboard plan.

Separate from ``client_dashboards`` so the budget-vs-actual routes stay untouched.
Reads and writes use that module's dashboard roles. No provider calls.
"""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, Header, Response
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ..dependencies import get_current_user
from ...database import get_db_session
from ...models import User
from ...services.dashboards import plan_v3
from ...services.dashboards.service import DashboardError

router = APIRouter()


def _error(exc: DashboardError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status,
        content={"error": {"code": exc.code, "message_he": exc.message_he}},
    )


def _etag(plan: dict) -> str:
    token = plan["revision"] if plan["revision"] is not None else plan["version"]
    return f'"{token}"'


@router.get("/dashboards/{dashboard_id}/plan/v3")
def read_plan(dashboard_id: int, response: Response, db: Session = Depends(get_db_session),
              user: User = Depends(get_current_user)):
    try:
        plan = plan_v3.read_plan(db, user, dashboard_id)
    except DashboardError as exc:
        return _error(exc)
    response.headers["ETag"] = _etag(plan)
    return plan


@router.put("/dashboards/{dashboard_id}/plan/v3")
def save_plan(dashboard_id: int, db: Session = Depends(get_db_session),
              user: User = Depends(get_current_user),
              body: dict = Body(...), if_match: str | None = Header(default=None)):
    try:
        plan = plan_v3.save_plan(db, user, dashboard_id, body, if_match)
    except DashboardError as exc:
        return _error(exc)
    response = JSONResponse(plan)
    response.headers["ETag"] = _etag(plan)
    return response
