"""
Financial Reports API Routes
נתיבי API לדוחות כספיים
"""
from typing import Optional
from datetime import date, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
import io

from ..dependencies import get_db, get_current_user
from ...services.financial_reports_service import (
    FinancialReportsService,
    ReportPeriod
)

router = APIRouter(prefix="/reports", tags=["Financial Reports"])


# ============= Request Models =============

class ReportDateRange(BaseModel):
    """טווח תאריכים לדוח"""
    start_date: date
    end_date: date
    compare_previous: bool = True


class CashFlowProjectionRequest(BaseModel):
    """בקשת תזרים חזוי"""
    months: int = 12
    opening_balance: Optional[float] = None


# ============= Profit & Loss Endpoints =============

@router.get("/profit-loss")
async def get_profit_loss(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    period: ReportPeriod = ReportPeriod.MONTHLY,
    compare_previous: bool = True,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    הפקת דוח רווח והפסד
    Generate Profit & Loss Statement
    """
    org_id = current_user.get('organization_id', 1)
    service = FinancialReportsService(db)
    
    # קביעת תאריכים ברירת מחדל
    if not end_date:
        end_date = date.today()
    
    if not start_date:
        if period == ReportPeriod.MONTHLY:
            start_date = end_date.replace(day=1)
        elif period == ReportPeriod.QUARTERLY:
            quarter_start_month = ((end_date.month - 1) // 3) * 3 + 1
            start_date = end_date.replace(month=quarter_start_month, day=1)
        elif period == ReportPeriod.YEARLY:
            start_date = end_date.replace(month=1, day=1)
        else:
            start_date = end_date - timedelta(days=30)
    
    report = service.generate_profit_loss(
        organization_id=org_id,
        start_date=start_date,
        end_date=end_date,
        compare_previous=compare_previous
    )
    
    return report.to_dict()


@router.post("/profit-loss")
async def generate_profit_loss(
    request: ReportDateRange,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    הפקת דוח רווח והפסד עם תאריכים מותאמים
    Generate Profit & Loss with custom dates
    """
    org_id = current_user.get('organization_id', 1)
    service = FinancialReportsService(db)
    
    report = service.generate_profit_loss(
        organization_id=org_id,
        start_date=request.start_date,
        end_date=request.end_date,
        compare_previous=request.compare_previous
    )
    
    return report.to_dict()


@router.get("/profit-loss/export")
async def export_profit_loss_excel(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    ייצוא דוח רווח והפסד ל-Excel
    Export Profit & Loss to Excel
    """
    org_id = current_user.get('organization_id', 1)
    service = FinancialReportsService(db)
    
    if not end_date:
        end_date = date.today()
    if not start_date:
        start_date = end_date.replace(day=1)
    
    report = service.generate_profit_loss(
        organization_id=org_id,
        start_date=start_date,
        end_date=end_date
    )
    
    excel_bytes = service.export_profit_loss_excel(report)
    
    filename = f"profit_loss_{start_date}_{end_date}.xlsx"
    
    return StreamingResponse(
        io.BytesIO(excel_bytes),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


# ============= Balance Sheet Endpoints =============

@router.get("/balance-sheet")
async def get_balance_sheet(
    as_of_date: Optional[date] = None,
    compare_previous: bool = True,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    הפקת מאזן / דוח כספי
    Generate Balance Sheet
    """
    org_id = current_user.get('organization_id', 1)
    service = FinancialReportsService(db)
    
    if not as_of_date:
        as_of_date = date.today()
    
    report = service.generate_balance_sheet(
        organization_id=org_id,
        as_of_date=as_of_date,
        compare_previous=compare_previous
    )
    
    return report.to_dict()


@router.get("/balance-sheet/export")
async def export_balance_sheet_excel(
    as_of_date: Optional[date] = None,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    ייצוא מאזן ל-Excel
    Export Balance Sheet to Excel
    """
    org_id = current_user.get('organization_id', 1)
    service = FinancialReportsService(db)
    
    if not as_of_date:
        as_of_date = date.today()
    
    report = service.generate_balance_sheet(
        organization_id=org_id,
        as_of_date=as_of_date
    )
    
    excel_bytes = service.export_balance_sheet_excel(report)
    
    filename = f"balance_sheet_{as_of_date}.xlsx"
    
    return StreamingResponse(
        io.BytesIO(excel_bytes),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


# ============= Cash Flow Projection Endpoints =============

@router.get("/cash-flow-projection")
async def get_cash_flow_projection(
    months: int = 12,
    opening_balance: Optional[float] = None,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    הפקת תזרים מזומנים חזוי לבנק
    Generate Projected Cash Flow for Bank
    """
    org_id = current_user.get('organization_id', 1)
    service = FinancialReportsService(db)
    
    report = service.generate_cash_flow_projection(
        organization_id=org_id,
        months=months,
        opening_balance=opening_balance
    )
    
    return report.to_dict()


@router.post("/cash-flow-projection")
async def generate_cash_flow_projection(
    request: CashFlowProjectionRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    הפקת תזרים חזוי עם פרמטרים מותאמים
    Generate Projected Cash Flow with custom parameters
    """
    org_id = current_user.get('organization_id', 1)
    service = FinancialReportsService(db)
    
    report = service.generate_cash_flow_projection(
        organization_id=org_id,
        months=request.months,
        opening_balance=request.opening_balance
    )
    
    return report.to_dict()


@router.get("/cash-flow-projection/export")
async def export_cash_flow_projection_excel(
    months: int = 12,
    opening_balance: Optional[float] = None,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    ייצוא תזרים חזוי ל-Excel
    Export Projected Cash Flow to Excel
    """
    org_id = current_user.get('organization_id', 1)
    service = FinancialReportsService(db)
    
    report = service.generate_cash_flow_projection(
        organization_id=org_id,
        months=months,
        opening_balance=opening_balance
    )
    
    excel_bytes = service.export_cash_flow_projection_excel(report)
    
    filename = f"cash_flow_projection_{date.today()}.xlsx"
    
    return StreamingResponse(
        io.BytesIO(excel_bytes),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


# ============= Summary Endpoints =============

@router.get("/summary")
async def get_financial_summary(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    סיכום פיננסי מהיר
    Quick Financial Summary
    """
    org_id = current_user.get('organization_id', 1)
    service = FinancialReportsService(db)
    
    today = date.today()
    month_start = today.replace(day=1)
    year_start = today.replace(month=1, day=1)
    
    # דוחות
    monthly_pl = service.generate_profit_loss(org_id, month_start, today, False)
    yearly_pl = service.generate_profit_loss(org_id, year_start, today, False)
    balance_sheet = service.generate_balance_sheet(org_id, today, False)
    projection = service.generate_cash_flow_projection(org_id, 6)
    
    return {
        "monthly": {
            "revenue": monthly_pl.total_revenue,
            "expenses": monthly_pl.total_expenses,
            "net_income": monthly_pl.net_income,
            "gross_margin": monthly_pl.gross_margin
        },
        "yearly": {
            "revenue": yearly_pl.total_revenue,
            "expenses": yearly_pl.total_expenses,
            "net_income": yearly_pl.net_income,
            "net_margin": yearly_pl.net_margin
        },
        "balance": {
            "total_assets": balance_sheet.total_assets,
            "total_liabilities": balance_sheet.total_liabilities,
            "total_equity": balance_sheet.total_equity,
            "current_ratio": (
                balance_sheet.total_current_assets / balance_sheet.total_current_liabilities
                if balance_sheet.total_current_liabilities else 0
            )
        },
        "projection": {
            "ending_balance": projection.ending_balance,
            "minimum_balance": projection.minimum_balance,
            "runway_months": projection.runway_months,
            "average_monthly_burn": projection.average_monthly_burn
        }
    }


@router.get("/available")
async def get_available_reports():
    """
    רשימת דוחות זמינים
    List available reports
    """
    return {
        "reports": [
            {
                "id": "profit-loss",
                "name": "דוח רווח והפסד",
                "name_en": "Profit & Loss Statement",
                "description": "דוח המציג הכנסות, הוצאות ורווח נקי לתקופה",
                "endpoints": {
                    "view": "/api/reports/profit-loss",
                    "export": "/api/reports/profit-loss/export"
                },
                "parameters": ["start_date", "end_date", "period", "compare_previous"]
            },
            {
                "id": "balance-sheet",
                "name": "מאזן",
                "name_en": "Balance Sheet",
                "description": "דוח המציג נכסים, התחייבויות והון עצמי",
                "endpoints": {
                    "view": "/api/reports/balance-sheet",
                    "export": "/api/reports/balance-sheet/export"
                },
                "parameters": ["as_of_date", "compare_previous"]
            },
            {
                "id": "cash-flow-projection",
                "name": "תזרים מזומנים חזוי",
                "name_en": "Cash Flow Projection",
                "description": "תחזית תזרים מזומנים לבנק",
                "endpoints": {
                    "view": "/api/reports/cash-flow-projection",
                    "export": "/api/reports/cash-flow-projection/export"
                },
                "parameters": ["months", "opening_balance"]
            }
        ]
    }
