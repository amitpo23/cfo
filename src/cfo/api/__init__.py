"""
FastAPI application initialization
"""
from contextlib import asynccontextmanager

import httpx
from fastapi import Depends, FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from .routes import (
    accounting, crm, payments, communications, admin,
    cashflow, sync, reports, financial_management, financial_operations
)
from .routes import cfo_dashboard, cfo_sync, cfo_tasks, cron, masav, inventory, dashboard, expenses, manual_reconciliation, advanced_features, phase10_12, analytics
from .routes import open_finance, office, calculators, payroll, ledger, daily_reports, annual_reports, engine, business, onboarding, accounting_events
from .dependencies import get_current_user
from ..config import settings
from ..database import init_db
from ..integrations.sumit_integration import SumitAPIError
from ..services.data_sync_service import SumitNotConfiguredError


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    """Initialize database tables on startup."""
    if settings.auto_create_db:
        init_db()
    yield


app = FastAPI(
    title=settings.app_name,
    description="CFO Financial Management System with SUMIT API Integration",
    version="2.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    lifespan=_lifespan,
)


@app.exception_handler(httpx.HTTPError)
async def upstream_error_handler(request: Request, exc: httpx.HTTPError):
    """כשל תקשורת מול שירות חיצוני (SUMIT/Open Finance) — 503 כן, לא 500."""
    return JSONResponse(
        status_code=503,
        content={"detail": f"upstream integration unavailable: {type(exc).__name__}"},
    )

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(SumitAPIError)
async def sumit_api_error_handler(_request, exc: SumitAPIError):
    return JSONResponse(
        status_code=status.HTTP_502_BAD_GATEWAY,
        content={
            "detail": str(exc),
            "source": "sumit",
            "code": "external_integration_error",
        },
    )


@app.exception_handler(SumitNotConfiguredError)
async def sumit_not_configured_handler(_request, exc: SumitNotConfiguredError):
    """DataSyncService raises this when no SUMIT credentials exist for the
    org. Some /api/sync/sumit/* routes call DataSyncService directly (no
    Depends(get_sumit_integration)), so without this handler the bare
    ValueError subclass would fall through as a raw 500."""
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={"detail": str(exc)},
    )

# Include existing routers
# SUMIT pass-through routers — every route already injects get_sumit_integration
# (which is org-scoped + authenticated), but pin auth at the mount too so a future
# route added without that dependency can't be exposed unauthenticated.
app.include_router(accounting.router, prefix="/api/accounting", tags=["Accounting"],
                   dependencies=[Depends(get_current_user)])
app.include_router(crm.router, prefix="/api/crm", tags=["CRM"],
                   dependencies=[Depends(get_current_user)])
app.include_router(payments.router, prefix="/api/payments", tags=["Payments"],
                   dependencies=[Depends(get_current_user)])
app.include_router(communications.router, prefix="/api/communications", tags=["Communications"],
                   dependencies=[Depends(get_current_user)])
app.include_router(admin.router, prefix="/api/admin", tags=["Admin"])
app.include_router(cashflow.router, prefix="/api/cashflow", tags=["Cash Flow & Forecasting"])
app.include_router(sync.router, prefix="/api", tags=["Data Sync & Bank Import"])
app.include_router(reports.router, prefix="/api", tags=["Financial Reports"])
app.include_router(
    financial_management.router, prefix="/api", tags=["Financial Management"],
    dependencies=[Depends(get_current_user)],
)
app.include_router(
    financial_operations.router, prefix="/api", tags=["Financial Operations"],
    dependencies=[Depends(get_current_user)],
)
app.include_router(
    masav.router, prefix="/api", tags=["Masav Payments"],
    dependencies=[Depends(get_current_user)],
)
app.include_router(
    inventory.router, prefix="/api", tags=["Inventory"],
    dependencies=[Depends(get_current_user)],
)
app.include_router(
    dashboard.router, prefix="/api", tags=["Executive Dashboard"],
    dependencies=[Depends(get_current_user)],
)
app.include_router(
    expenses.router, prefix="/api", tags=["Expense Filing"],
    dependencies=[Depends(get_current_user)],
)
app.include_router(
    manual_reconciliation.router, prefix="/api",
    dependencies=[Depends(get_current_user)],
)
app.include_router(
    advanced_features.router, prefix="/api",
    dependencies=[Depends(get_current_user)],
)
app.include_router(
    phase10_12.router, prefix="/api",
    dependencies=[Depends(get_current_user)],
)

# New CFO routers — authenticated, same convention as the rest of the API
app.include_router(
    cfo_dashboard.router, prefix="/api", tags=["CFO Dashboard"],
    dependencies=[Depends(get_current_user)],
)
app.include_router(
    cfo_sync.router, prefix="/api", tags=["CFO Sync"],
    dependencies=[Depends(get_current_user)],
)
app.include_router(
    cfo_tasks.router, prefix="/api", tags=["CFO Tasks & Alerts"],
    dependencies=[Depends(get_current_user)],
)

# Phase 13: Analytics & Business Intelligence
app.include_router(
    analytics.router, prefix="/api",
    dependencies=[Depends(get_current_user)],
)

# Open Finance — full integration + bank intelligence. Per-route auth via
# get_current_org_id; the /webhooks route is intentionally public (Open Finance
# posts events to it and no signature scheme is documented).
app.include_router(
    open_finance.router, prefix="/api/open-finance", tags=["Open Finance"],
)

# Accounting-office (multi-company) + cross-source synthesis
app.include_router(
    office.router, prefix="/api", tags=["Office & Synthesis"],
    dependencies=[Depends(get_current_user)],
)

# Deterministic calculators — public utility, no auth, no org data
app.include_router(calculators.router, prefix="/api", tags=["Calculators"])

# Payroll — employees, payslips, Form 102/126
app.include_router(
    payroll.router, prefix="/api", tags=["Payroll"],
    dependencies=[Depends(get_current_user)],
)

# Derived double-entry shadow ledger — organization-scoped, not the official books
app.include_router(
    ledger.router, prefix="/api", tags=["Ledger (Derived)"],
    dependencies=[Depends(get_current_user)],
)

# Read-only accounting event plane — normalized operational events, not a source of truth
app.include_router(
    accounting_events.router, prefix="/api", tags=["Accounting Events (Derived)"],
    dependencies=[Depends(get_current_user)],
)

# Daily-cumulative intra-month reports — organization-scoped, derived
app.include_router(
    daily_reports.router, prefix="/api", tags=["Daily Reports (Derived)"],
    dependencies=[Depends(get_current_user)],
)

# Annual tax-return DRAFTS (1301/1214) — organization-scoped, draft-only
app.include_router(
    annual_reports.router, prefix="/api", tags=["Annual Reports (Draft)"],
    dependencies=[Depends(get_current_user)],
)

# The unifying engine — one command surface over all services
app.include_router(
    engine.router, prefix="/api", tags=["Unifying Engine"],
    dependencies=[Depends(get_current_user)],
)

# Per-business capability menu / syllabus — organization-scoped
app.include_router(
    business.router, prefix="/api", tags=["Business Menu"],
    dependencies=[Depends(get_current_user)],
)

# Onboarding data-mapping checklist — status + manual re-run, organization-scoped
app.include_router(
    onboarding.router, prefix="/api", tags=["Onboarding"],
    dependencies=[Depends(get_current_user)],
)

# Cron jobs authenticate with CRON_SECRET, not user tokens
app.include_router(cron.router, prefix="/api", tags=["Scheduled Jobs"])


@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "message": "CFO Financial Management System API",
        "version": "2.0.0",
        "docs": "/api/docs"
    }


@app.get("/health")
@app.get("/api/health")
async def health_check():
    """Health check endpoint (also served at /api/health for Vercel rewrites)."""
    return {"status": "healthy"}
