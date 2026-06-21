"""
FastAPI application initialization
"""
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .routes import (
    accounting, crm, payments, communications, admin,
    cashflow, sync, reports, financial_management, financial_operations
)
from .routes import cfo_dashboard, cfo_sync, cfo_tasks, cron, masav, inventory, dashboard, expenses
from .routes import open_finance, office, calculators, payroll
from .dependencies import get_current_user
from ..config import settings
from ..database import init_db

app = FastAPI(
    title=settings.app_name,
    description="CFO Financial Management System with SUMIT API Integration",
    version="2.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include existing routers
app.include_router(accounting.router, prefix="/api/accounting", tags=["Accounting"])
app.include_router(crm.router, prefix="/api/crm", tags=["CRM"])
app.include_router(payments.router, prefix="/api/payments", tags=["Payments"])
app.include_router(communications.router, prefix="/api/communications", tags=["Communications"])
app.include_router(admin.router, prefix="/api/admin", tags=["Admin"])
app.include_router(cashflow.router, prefix="/api/cashflow", tags=["Cash Flow & Forecasting"])
app.include_router(sync.router, prefix="/api", tags=["Data Sync & Bank Import"])
app.include_router(reports.router, prefix="/api", tags=["Financial Reports"])
app.include_router(
    financial_management.router, prefix="/api", tags=["Financial Management"],
    dependencies=[Depends(get_current_user)],
)
app.include_router(financial_operations.router, prefix="/api", tags=["Financial Operations"])
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

# Cron jobs authenticate with CRON_SECRET, not user tokens
app.include_router(cron.router, prefix="/api", tags=["Scheduled Jobs"])


@app.on_event("startup")
async def startup_event():
    """Initialize database tables on startup."""
    init_db()


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
