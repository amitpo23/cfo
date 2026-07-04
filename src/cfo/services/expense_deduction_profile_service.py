"""Organization-scoped persistence for the real inputs the deduction
calculators need (vehicle profile, home-office profile), plus a thin
compute-and-optionally-apply layer over expense_deduction_service's pure
calculators. Never fabricates deduction_percent — an Expense only gets a
value written when a calculator actually ran on real inputs.
"""
from decimal import Decimal
from typing import Dict, Optional

from sqlalchemy.orm import Session

from ..models import Expense, HomeOfficeProfile, VehicleDeductionProfile
from .expense_deduction_service import (
    calculate_home_office_percent,
    calculate_internet_deduction_percent,
    calculate_landline_deduction,
    calculate_mobile_phone_deduction,
    calculate_vehicle_deduction_percent,
)


class ExpenseDeductionProfileService:
    def __init__(self, db: Session, organization_id: int):
        self.db = db
        self.organization_id = organization_id

    # ---------- Vehicle profile ----------

    def upsert_vehicle_profile(self, tax_year: int, vehicle_label: Optional[str], **fields) -> VehicleDeductionProfile:
        profile = (
            self.db.query(VehicleDeductionProfile)
            .filter(
                VehicleDeductionProfile.organization_id == self.organization_id,
                VehicleDeductionProfile.tax_year == tax_year,
                VehicleDeductionProfile.vehicle_label == vehicle_label,
            )
            .first()
        )
        if not profile:
            profile = VehicleDeductionProfile(
                organization_id=self.organization_id, tax_year=tax_year, vehicle_label=vehicle_label,
            )
            self.db.add(profile)
        for key in ("running_costs_annual", "use_value_monthly", "odometer_start", "odometer_end"):
            if key in fields and fields[key] is not None:
                setattr(profile, key, Decimal(str(fields[key])))
        self.db.commit()
        self.db.refresh(profile)
        return profile

    def get_vehicle_profile(self, tax_year: int, vehicle_label: Optional[str]) -> Optional[VehicleDeductionProfile]:
        return (
            self.db.query(VehicleDeductionProfile)
            .filter(
                VehicleDeductionProfile.organization_id == self.organization_id,
                VehicleDeductionProfile.tax_year == tax_year,
                VehicleDeductionProfile.vehicle_label == vehicle_label,
            )
            .first()
        )

    def compute_vehicle_deduction(self, tax_year: int, vehicle_label: Optional[str] = None) -> Decimal:
        profile = self.get_vehicle_profile(tax_year, vehicle_label)
        if not profile:
            raise ValueError(f"no vehicle deduction profile for tax_year={tax_year}, vehicle_label={vehicle_label!r}")
        return calculate_vehicle_deduction_percent(
            running_costs_annual=profile.running_costs_annual,
            use_value_monthly=profile.use_value_monthly,
            odometer_start=profile.odometer_start,
            odometer_end=profile.odometer_end,
        )

    # ---------- Home office profile ----------

    def upsert_home_office_profile(self, office_sqm, total_home_sqm) -> HomeOfficeProfile:
        profile = (
            self.db.query(HomeOfficeProfile)
            .filter(HomeOfficeProfile.organization_id == self.organization_id)
            .first()
        )
        if not profile:
            profile = HomeOfficeProfile(organization_id=self.organization_id, office_sqm=office_sqm, total_home_sqm=total_home_sqm)
            self.db.add(profile)
        else:
            profile.office_sqm = Decimal(str(office_sqm))
            profile.total_home_sqm = Decimal(str(total_home_sqm))
        self.db.commit()
        self.db.refresh(profile)
        return profile

    def get_home_office_profile(self) -> Optional[HomeOfficeProfile]:
        return (
            self.db.query(HomeOfficeProfile)
            .filter(HomeOfficeProfile.organization_id == self.organization_id)
            .first()
        )

    def compute_home_office_deduction(self) -> Decimal:
        profile = self.get_home_office_profile()
        if not profile:
            raise ValueError("no home-office profile configured for this organization")
        return calculate_home_office_percent(profile.office_sqm, profile.total_home_sqm)

    def compute_internet_deduction(self, business_use_fraction: Optional[float] = None) -> Decimal:
        if business_use_fraction is not None:
            return calculate_internet_deduction_percent(business_use_fraction=business_use_fraction)
        profile = self.get_home_office_profile()
        if not profile:
            raise ValueError("no home-office profile configured and no business_use_fraction supplied")
        return calculate_internet_deduction_percent(office_sqm=profile.office_sqm, total_home_sqm=profile.total_home_sqm)

    # ---------- Apply to an Expense (org-scoped) ----------

    def apply_deduction_percent(self, expense_id: int, deduction_percent: Decimal) -> Dict:
        expense = (
            self.db.query(Expense)
            .filter(Expense.id == expense_id, Expense.organization_id == self.organization_id)
            .first()
        )
        if not expense:
            raise ValueError(f"expense {expense_id} not found in this organization")
        expense.deduction_percent = deduction_percent
        self.db.commit()
        self.db.refresh(expense)
        return {
            "id": expense.id,
            "deduction_percent": float(expense.deduction_percent),
        }
