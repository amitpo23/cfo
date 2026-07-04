"""
מנגנוני ניכוי הוצאה — רכב (higher-of), טלפון נייד/קווי, בית/אינטרנט.
Real Israeli expense-deduction calculators. Every route requires real
inputs; nothing here fabricates a deduction_percent.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..dependencies import get_db, get_current_org_id
from ...services.expense_deduction_profile_service import ExpenseDeductionProfileService
from ...services.expense_deduction_service import (
    calculate_landline_deduction,
    calculate_mobile_phone_deduction,
)

router = APIRouter(prefix="/expenses/deduction", tags=["Expense Deduction"])


def _profile_to_dict(p) -> dict:
    return {
        "id": p.id,
        "tax_year": getattr(p, "tax_year", None),
        "vehicle_label": getattr(p, "vehicle_label", None),
        "running_costs_annual": float(p.running_costs_annual) if getattr(p, "running_costs_annual", None) is not None else None,
        "use_value_monthly": float(p.use_value_monthly) if getattr(p, "use_value_monthly", None) is not None else None,
        "odometer_start": float(p.odometer_start) if getattr(p, "odometer_start", None) is not None else None,
        "odometer_end": float(p.odometer_end) if getattr(p, "odometer_end", None) is not None else None,
    }


# ==================== Vehicle profile ====================

class VehicleProfileRequest(BaseModel):
    tax_year: int
    vehicle_label: Optional[str] = None
    running_costs_annual: Optional[float] = None
    use_value_monthly: Optional[float] = None
    odometer_start: Optional[float] = None
    odometer_end: Optional[float] = None


@router.post("/vehicle-profile")
async def upsert_vehicle_profile(
    request: VehicleProfileRequest,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """שמירת/עדכון פרופיל-רכב אמיתי (עלויות שוטפות, שווי שימוש, ק"מ) לשנת-מס."""
    service = ExpenseDeductionProfileService(db, organization_id=org_id)
    profile = service.upsert_vehicle_profile(
        request.tax_year, request.vehicle_label,
        running_costs_annual=request.running_costs_annual,
        use_value_monthly=request.use_value_monthly,
        odometer_start=request.odometer_start,
        odometer_end=request.odometer_end,
    )
    return {"status": "success", "data": _profile_to_dict(profile)}


@router.get("/vehicle-profile")
async def get_vehicle_profile(
    tax_year: int,
    vehicle_label: Optional[str] = None,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    service = ExpenseDeductionProfileService(db, organization_id=org_id)
    profile = service.get_vehicle_profile(tax_year, vehicle_label)
    if not profile:
        raise HTTPException(status_code=404, detail="no vehicle deduction profile for this tax_year/vehicle_label")
    return {"status": "success", "data": _profile_to_dict(profile)}


class ComputeRequest(BaseModel):
    expense_id: Optional[int] = None


@router.post("/vehicle-profile/{tax_year}/compute")
async def compute_vehicle_deduction(
    tax_year: int,
    request: ComputeRequest,
    vehicle_label: Optional[str] = None,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """מחשב את אחוז-הניכוי (higher-of) מתוך פרופיל-הרכב השמור, ומעדכן הוצאה אם סופק expense_id."""
    service = ExpenseDeductionProfileService(db, organization_id=org_id)
    try:
        pct = service.compute_vehicle_deduction(tax_year, vehicle_label)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    result = {"deduction_percent": float(pct)}
    if request.expense_id is not None:
        try:
            result["expense"] = service.apply_deduction_percent(request.expense_id, pct)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
    return {"status": "success", "data": result}


# ==================== Home office profile ====================

class HomeOfficeProfileRequest(BaseModel):
    office_sqm: float = Field(..., gt=0)
    total_home_sqm: float = Field(..., gt=0)


@router.post("/home-office-profile")
async def upsert_home_office_profile(
    request: HomeOfficeProfileRequest,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    service = ExpenseDeductionProfileService(db, organization_id=org_id)
    try:
        profile = service.upsert_home_office_profile(request.office_sqm, request.total_home_sqm)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"status": "success", "data": {
        "office_sqm": float(profile.office_sqm),
        "total_home_sqm": float(profile.total_home_sqm),
    }}


@router.get("/home-office-profile")
async def get_home_office_profile(
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    service = ExpenseDeductionProfileService(db, organization_id=org_id)
    profile = service.get_home_office_profile()
    if not profile:
        raise HTTPException(status_code=404, detail="no home-office profile configured for this organization")
    return {"status": "success", "data": {
        "office_sqm": float(profile.office_sqm),
        "total_home_sqm": float(profile.total_home_sqm),
    }}


@router.post("/home-office-profile/compute")
async def compute_home_office_deduction(
    request: ComputeRequest,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    service = ExpenseDeductionProfileService(db, organization_id=org_id)
    try:
        pct = service.compute_home_office_deduction()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    result = {"deduction_percent": float(pct)}
    if request.expense_id is not None:
        try:
            result["expense"] = service.apply_deduction_percent(request.expense_id, pct)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
    return {"status": "success", "data": result}


@router.post("/internet/compute")
async def compute_internet_deduction(
    business_use_fraction: Optional[float] = None,
    expense_id: Optional[int] = None,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    service = ExpenseDeductionProfileService(db, organization_id=org_id)
    try:
        pct = service.compute_internet_deduction(business_use_fraction)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    result = {"deduction_percent": float(pct)}
    if expense_id is not None:
        try:
            result["expense"] = service.apply_deduction_percent(expense_id, pct)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
    return {"status": "success", "data": result}


# ==================== Stateless phone/landline calculators ====================

@router.post("/mobile-phone/compute")
async def compute_mobile_phone_deduction(
    monthly_expense: float,
    expense_id: Optional[int] = None,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    try:
        deductible, pct = calculate_mobile_phone_deduction(monthly_expense)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    result = {"deductible_amount": float(deductible), "deduction_percent": float(pct)}
    if expense_id is not None:
        service = ExpenseDeductionProfileService(db, organization_id=org_id)
        try:
            result["expense"] = service.apply_deduction_percent(expense_id, pct)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
    return {"status": "success", "data": result}


@router.post("/landline/compute")
async def compute_landline_deduction(
    annual_expense: float,
    expense_id: Optional[int] = None,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    try:
        deductible, pct = calculate_landline_deduction(annual_expense)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    result = {"deductible_amount": float(deductible), "deduction_percent": float(pct)}
    if expense_id is not None:
        service = ExpenseDeductionProfileService(db, organization_id=org_id)
        try:
            result["expense"] = service.apply_deduction_percent(expense_id, pct)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
    return {"status": "success", "data": result}
