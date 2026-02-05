"""
FastAPI application initialization
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .routes import (
    accounting, crm, payments, communications, admin,
    cashflow, sync, reports, financial_management, financial_operations
)
from .routes import cfo_dashboard, cfo_sync, cfo_tasks
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
app.include_router(sync.router, prefix="/api/sync-legacy", tags=["Data Sync (Legacy)"])
app.include_router(reports.router, prefix="/api/reports-legacy", tags=["Financial Reports (Legacy)"])
app.include_router(financial_management.router, prefix="/api", tags=["Financial Management"])
app.include_router(financial_operations.router, prefix="/api", tags=["Financial Operations"])

# New CFO routers
app.include_router(cfo_dashboard.router, prefix="/api", tags=["CFO Dashboard"])
app.include_router(cfo_sync.router, prefix="/api", tags=["CFO Sync"])
app.include_router(cfo_tasks.router, prefix="/api", tags=["CFO Tasks & Alerts"])


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
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy"}
