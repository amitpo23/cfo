"""Client dashboard API. Unknown and forbidden dashboards both return 404.

Public reads set no-referrer and noindex. They do not call SUMIT or Open Finance.
"""
from __future__ import annotations

import hashlib
import os
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from ..dependencies import get_current_user
from ...config import settings
from ...database import get_db_session
from ...models import DashboardRateLimit, PublishedSnapshot, User
from ...services.dashboards import budget, service, view_model
from ...services.dashboards.service import READ_ROLES, DashboardError

router = APIRouter()
public_router = APIRouter()

_COOKIE_SALT = "rezef-dashboard-share"
_PUBLIC_HEADERS = {
    "Referrer-Policy": "no-referrer",
    "X-Robots-Tag": "noindex",
    "X-Frame-Options": "DENY",
    "Cache-Control": "private, no-store",
}


class DashboardCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    primary_organization_id: int
    slug: str = Field(min_length=3, max_length=48)
    title: str = Field(min_length=1, max_length=255)
    template: str = "generic"
    access_mode: str = "link"
    office_organization_id: int | None = None


class DashboardPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str | None = None
    access_mode: str | None = None
    status: str | None = None


class PlanBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    payload: dict


class BudgetRowBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    year: int
    month: int
    category: str | None = Field(default=None, max_length=255)
    category_id: int | None = None
    budgeted_amount: float
    notes: str | None = Field(default=None, max_length=2000)


class BudgetBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rows: list[BudgetRowBody]


class ShareBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str | None = Field(default=None, max_length=255)


class SessionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(min_length=1, max_length=200)


def _error(exc: DashboardError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status,
        content={"error": {"code": exc.code, "message_he": exc.message_he}},
    )


def _cookie_secret() -> str:
    return settings.dashboard_cookie_secret or settings.jwt_secret_key


def _cookie_secure(request: Request) -> bool:
    if os.getenv("VERCEL") or os.getenv("VERCEL_ENV"):
        return True
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    return proto == "https"


def _sign_cookie(payload: dict) -> str:
    import base64
    import hmac
    import json
    import time
    body = dict(payload)
    body["iat"] = int(time.time())
    raw = base64.urlsafe_b64encode(json.dumps(body, separators=(",", ":")).encode()).decode().rstrip("=")
    sig = hmac.new(
        f"{_cookie_secret()}:{_COOKIE_SALT}".encode(), raw.encode(), hashlib.sha256,
    ).hexdigest()
    return f"{raw}.{sig}"


class _BadCookie(Exception):
    pass


def _read_cookie(value: str, *, max_age: int) -> dict:
    import base64
    import hmac
    import json
    import time
    from ...services.secret_compare import constant_time_equal
    try:
        raw, sig = value.split(".", 1)
    except ValueError:
        raise _BadCookie()
    expected = hmac.new(
        f"{_cookie_secret()}:{_COOKIE_SALT}".encode(), raw.encode(), hashlib.sha256,
    ).hexdigest()
    if not constant_time_equal(sig, expected):
        raise _BadCookie()
    try:
        data = json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
    except (json.JSONDecodeError, ValueError):
        raise _BadCookie()
    if int(time.time()) - int(data.get("iat", 0)) > max_age:
        raise _BadCookie()
    return data


@router.get("/dashboards")
def list_dashboards(db: Session = Depends(get_db_session), user: User = Depends(get_current_user)):
    return {"dashboards": service.list_dashboards(db, user), "provider_calls": 0}


@router.post("/dashboards", status_code=201)
def create_dashboard(body: DashboardCreate, db: Session = Depends(get_db_session),
                     user: User = Depends(get_current_user)):
    try:
        row = service.create_dashboard(
            db, user, organization_id=body.primary_organization_id, slug=body.slug,
            title=body.title, template=body.template, access_mode=body.access_mode,
            office_organization_id=body.office_organization_id,
        )
    except DashboardError as exc:
        return _error(exc)
    return {"id": row.id, "slug": row.slug, "status": row.status, "provider_calls": 0}


@router.get("/dashboards/by-slug/{slug}")
def read_dashboard_by_slug(slug: str, db: Session = Depends(get_db_session),
                           user: User = Depends(get_current_user)):
    try:
        return service.dashboard_by_slug(db, user, slug)
    except DashboardError as exc:
        return _error(exc)


@router.get("/dashboards/{dashboard_id}")
def read_dashboard(dashboard_id: int, db: Session = Depends(get_db_session),
                   user: User = Depends(get_current_user)):
    try:
        row = service.get_dashboard(db, user, dashboard_id, allowed=READ_ROLES)
    except DashboardError as exc:
        return _error(exc)
    return {"id": row.id, "slug": row.slug, "title": row.title, "status": row.status,
            "access_mode": row.access_mode, "provider_calls": 0}


@router.patch("/dashboards/{dashboard_id}")
def patch_dashboard(dashboard_id: int, body: DashboardPatch, db: Session = Depends(get_db_session),
                    user: User = Depends(get_current_user)):
    try:
        row = service.update_dashboard(db, user, dashboard_id, body.model_dump(exclude_unset=True))
    except DashboardError as exc:
        return _error(exc)
    return {"id": row.id, "slug": row.slug, "status": row.status, "access_mode": row.access_mode}


@router.get("/dashboards/{dashboard_id}/view")
def dashboard_view(dashboard_id: int, start: date | None = None, end: date | None = None,
                   db: Session = Depends(get_db_session), user: User = Depends(get_current_user)):
    try:
        row = service.get_dashboard(db, user, dashboard_id, allowed=READ_ROLES)
        window_end = end or date.today()
        window_start = start or date(window_end.year, 1, 1)
        view = view_model.build_view(db, row.primary_organization_id, window_start, window_end,
                                     plan=view_model.plan_payload(db, row.id))
    except DashboardError as exc:
        return _error(exc)
    except ValueError as exc:
        return _error(DashboardError(422, "invalid_range", str(exc)))
    view["dashboard_id"] = row.id
    return view


@router.post("/dashboards/{dashboard_id}/snapshots", status_code=201)
def publish_snapshot(dashboard_id: int, db: Session = Depends(get_db_session),
                     user: User = Depends(get_current_user)):
    try:
        row = service.get_dashboard(db, user, dashboard_id, allowed={"owner"})
        today = date.today()
        view = view_model.build_view(db, row.primary_organization_id, date(today.year, 1, 1), today,
                                     plan=view_model.plan_payload(db, row.id))
        saved = view_model.publish_view(db, row, view, day=today)
    except DashboardError as exc:
        return _error(exc)
    saved["provider_calls"] = 0
    return saved


@router.post("/dashboards/{dashboard_id}/share-links", status_code=201)
def create_share_link(dashboard_id: int, body: ShareBody, db: Session = Depends(get_db_session),
                      user: User = Depends(get_current_user)):
    try:
        return service.create_share_link(db, user, dashboard_id, label=body.label)
    except DashboardError as exc:
        return _error(exc)


@router.get("/dashboards/{dashboard_id}/share-links")
def list_share_links(dashboard_id: int, db: Session = Depends(get_db_session),
                     user: User = Depends(get_current_user)):
    try:
        return {"links": service.list_share_links(db, user, dashboard_id)}
    except DashboardError as exc:
        return _error(exc)


@router.delete("/dashboards/{dashboard_id}/share-links/{link_id}", status_code=204)
def revoke_share_link(dashboard_id: int, link_id: int, db: Session = Depends(get_db_session),
                      user: User = Depends(get_current_user)):
    try:
        service.revoke_share_link(db, user, dashboard_id, link_id)
    except DashboardError as exc:
        return _error(exc)
    return Response(status_code=204)


@router.get("/dashboards/{dashboard_id}/plan")
def read_plan(dashboard_id: int, response: Response, db: Session = Depends(get_db_session),
              user: User = Depends(get_current_user)):
    try:
        plan = service.read_plan(db, user, dashboard_id)
    except DashboardError as exc:
        return _error(exc)
    response.headers["ETag"] = f'"{plan["version"]}"' if plan["version"] else "null"
    return plan


@router.put("/dashboards/{dashboard_id}/plan")
def save_plan(dashboard_id: int, body: PlanBody, db: Session = Depends(get_db_session),
              user: User = Depends(get_current_user), if_match: str | None = Header(default=None)):
    try:
        plan = service.save_plan(db, user, dashboard_id, body.payload, if_match)
    except DashboardError as exc:
        return _error(exc)
    response = JSONResponse(plan)
    response.headers["ETag"] = f'"{plan["version"]}"'
    return response


@router.get("/dashboards/{dashboard_id}/filing")
def read_filing(dashboard_id: int, page: int = 1, page_size: int = 50,
                db: Session = Depends(get_db_session), user: User = Depends(get_current_user)):
    try:
        return service.read_filing(db, user, dashboard_id, page=page, page_size=page_size)
    except DashboardError as exc:
        return _error(exc)


@router.get("/dashboards/{dashboard_id}/budget")
def read_budget(dashboard_id: int, year: int | None = None, db: Session = Depends(get_db_session),
                user: User = Depends(get_current_user)):
    try:
        return budget.read_budget(db, user, dashboard_id, year=year)
    except DashboardError as exc:
        return _error(exc)


@router.put("/dashboards/{dashboard_id}/budget")
def save_budget(dashboard_id: int, body: BudgetBody, db: Session = Depends(get_db_session),
                user: User = Depends(get_current_user)):
    try:
        return budget.upsert_budget(db, user, dashboard_id, [row.model_dump() for row in body.rows])
    except DashboardError as exc:
        return _error(exc)


def _public_response(payload: dict, status_code: int = 200) -> JSONResponse:
    response = JSONResponse(status_code=status_code, content=payload)
    for key, value in _PUBLIC_HEADERS.items():
        response.headers[key] = value
    return response


def _forwarded_client(value: str | None) -> str | None:
    if not value:
        return None
    first = value.split(",")[0].strip()
    return first or None


def _client_address(request: Request) -> str:
    """The address the rate limit may trust.

    On Vercel the platform overwrites ``x-vercel-forwarded-for`` with the
    client address. Off Vercel a caller can set ``X-Forwarded-For``, so the
    limit uses the socket peer only.
    """
    if os.getenv("VERCEL") or os.getenv("VERCEL_ENV"):
        for header in ("x-vercel-forwarded-for", "x-real-ip", "x-forwarded-for"):
            client = _forwarded_client(request.headers.get(header))
            if client:
                return client
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def _naive_utc(value: datetime) -> datetime:
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _purge_rate_limits(db: Session) -> None:
    cutoff = datetime.utcnow() - timedelta(days=1)
    db.query(DashboardRateLimit).filter(DashboardRateLimit.window_start < cutoff).delete(
        synchronize_session=False,
    )


def _bump_rate_limit(db: Session, scope_key: str, window_kind: str, window_start: datetime, limit: int) -> bool:
    """Atomically increment a window. False when the window is already full."""
    _purge_rate_limits(db)
    table = DashboardRateLimit.__table__
    values = {
        "scope_key": scope_key,
        "window_kind": window_kind,
        "window_start": _naive_utc(window_start),
        "used": 1,
        "created_at": datetime.utcnow(),
    }
    dialect = db.get_bind().dialect.name
    if dialect == "postgresql":
        statement = pg_insert(table).values(**values)
    elif dialect == "sqlite":
        statement = sqlite_insert(table).values(**values)
    else:
        db.rollback()
        return False
    statement = statement.on_conflict_do_update(
        index_elements=["scope_key", "window_kind", "window_start"],
        set_={"used": table.c.used + 1},
        where=table.c.used < limit,
    ).returning(table.c.used)
    allowed = db.execute(statement).scalar_one_or_none() is not None
    db.commit()
    return allowed


def _claim_public_limit(db: Session, request: Request, slug: str) -> JSONResponse | None:
    host = _client_address(request)
    scope = hashlib.sha256(f"{host}|{slug}".encode()).hexdigest()[:40]
    window = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    if _bump_rate_limit(db, scope, "minute", window, 120):
        return None
    return _public_response({"error": {"code": "rate_limited", "message_he": "יותר מדי בקשות"}}, 429)


def _claim_failure(db: Session, request: Request, slug: str) -> bool:
    host = _client_address(request)
    scope = hashlib.sha256(f"fail|{host}|{slug}".encode()).hexdigest()[:40]
    window = service.failure_window_start()
    return not _bump_rate_limit(db, scope, "quarter_hour", window, 5)


def _cookie_dashboard(db: Session, request: Request, dashboard_id: int):
    raw = request.cookies.get(f"rzd_{dashboard_id}")
    if not raw:
        return None
    try:
        data = _read_cookie(raw, max_age=30 * 24 * 3600)
    except _BadCookie:
        return None
    from ...models import DashboardShareLink
    link = db.get(DashboardShareLink, data.get("link_id"))
    if link is None or link.dashboard_id != dashboard_id or link.revoked_at is not None:
        return None
    if link.expires_at and link.expires_at < datetime.utcnow():
        return None
    return link


@public_router.post("/d/{slug}/session")
def open_share_session(slug: str, body: SessionBody, request: Request,
                       db: Session = Depends(get_db_session)):
    limited = _claim_public_limit(db, request, slug)
    if limited:
        return limited
    try:
        dashboard, link = service.resolve_share_token(db, slug, body.token)
    except DashboardError:
        if _claim_failure(db, request, slug):
            return _public_response({"error": {"code": "rate_limited", "message_he": "יותר מדי ניסיונות"}}, 429)
        return _public_response({"error": {"code": "not_found", "message_he": "הדשבורד לא נמצא"}}, 404)
    service.mark_link_used(db, link)
    response = _public_response({"ok": True, "provider_calls": 0})
    secure = _cookie_secure(request)
    response.set_cookie(
        key=f"rzd_{dashboard.id}",
        value=_sign_cookie({"link_id": link.id, "dashboard_id": dashboard.id}),
        httponly=True,
        secure=secure,
        samesite="lax",
        max_age=30 * 24 * 3600,
        path="/",
    )
    return response


@public_router.get("/d/{slug}")
def read_public_dashboard(slug: str, request: Request, db: Session = Depends(get_db_session)):
    limited = _claim_public_limit(db, request, slug)
    if limited:
        return limited
    try:
        dashboard = service.public_dashboard(db, slug)
    except DashboardError as exc:
        return _public_response({"error": {"code": exc.code, "message_he": exc.message_he}}, exc.status)
    link = None
    if dashboard.access_mode != "public":
        link = _cookie_dashboard(db, request, dashboard.id)
        if link is None:
            return _public_response({"error": {"code": "not_found", "message_he": "הדשבורד לא נמצא"}}, 404)
        service.mark_link_used(db, link)
    snapshot = None
    if dashboard.current_snapshot_id:
        snapshot = db.get(PublishedSnapshot, dashboard.current_snapshot_id)
    if snapshot is not None:
        payload = view_model.redact_public_view(dict(snapshot.view_model or {}))
        payload["provider_calls"] = 0
        payload["freshness"] = dict(snapshot.freshness or {})
        payload["freshness"]["published"] = True
        payload["source"] = "snapshot"
        return _public_response(payload)
    today = date.today()
    view = view_model.redact_public_view(
        view_model.build_view(db, dashboard.primary_organization_id, date(today.year, 1, 1), today,
                              plan=view_model.plan_payload(db, dashboard.id))
    )
    view["source"] = "live"
    return _public_response(view)
