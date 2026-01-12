"""
FastAPI application initialization
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .routes import accounting, crm, payments, communications, admin
from ..config import settings

app = FastAPI(
    title=settings.app_name,
    description="CFO Financial Management System with SUMIT API Integration",
    version="1.0.0",
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

# Include routers
app.include_router(accounting.router, prefix="/api/accounting", tags=["Accounting"])
app.include_router(crm.router, prefix="/api/crm", tags=["CRM"])
app.include_router(payments.router, prefix="/api/payments", tags=["Payments"])
app.include_router(communications.router, prefix="/api/communications", tags=["Communications"])
app.include_router(admin.router, prefix="/api/admin", tags=["Admin"])


@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "message": "CFO Financial Management System API",
        "version": "1.0.0",
        "docs": "/api/docs"
    }


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy"}
