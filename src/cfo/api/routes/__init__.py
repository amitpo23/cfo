"""
Route modules initialization
"""
from . import accounting, crm, payments, communications, admin, cashflow, sync, reports, financial_management

__all__ = [
    "accounting", 
    "crm", 
    "payments", 
    "communications", 
    "admin",
    "cashflow",
    "sync",
    "reports",
    "financial_management"
]
