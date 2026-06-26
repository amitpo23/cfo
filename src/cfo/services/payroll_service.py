"""
Payroll module — employees → payslips → Form 102 / Form 126.

All salary math comes from `calculators.payslip_components` (the single validated
source of truth), so payroll, the net-salary calculator and Form 102 never diverge.
`employee_withholding_rows` feeds `tax_service._get_employee_data`, closing the gap
where the withholding (102) report had no employee data source.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional

from ..models import Employee, Payslip
from .calculators import payslip_components


# ---------------------------------------------------------------------- #
# Payroll run
# ---------------------------------------------------------------------- #
def run_payroll(db, organization_id: int, year: int, month: int) -> dict[str, Any]:
    """Generate/refresh payslips for every active employee for the month."""
    employees = (
        db.query(Employee)
        .filter(Employee.organization_id == organization_id, Employee.is_active == True)  # noqa: E712
        .all()
    )
    created = updated = 0
    totals = _empty_totals()
    for emp in employees:
        comp = payslip_components(
            float(emp.gross_salary or 0),
            credit_points=float(emp.credit_points if emp.credit_points is not None else 2.25),
            pension_pct=float(emp.pension_pct if emp.pension_pct is not None else 6.0),
        )
        row = (
            db.query(Payslip)
            .filter(
                Payslip.organization_id == organization_id,
                Payslip.employee_id == emp.id,
                Payslip.year == year, Payslip.month == month,
            )
            .first()
        )
        if row:
            updated += 1
        else:
            row = Payslip(organization_id=organization_id, employee_id=emp.id, year=year, month=month)
            db.add(row)
            created += 1
        for k, v in comp.items():
            setattr(row, k, v)
        for k in totals:
            totals[k] += comp.get(k, 0)
    db.commit()
    totals = {k: round(v, 2) for k, v in totals.items()}
    return {"year": year, "month": month, "employees": len(employees),
            "created": created, "updated": updated, "totals": totals}


def list_payslips(db, organization_id: int, year: int, month: int) -> list[dict]:
    rows = (
        db.query(Payslip)
        .filter(Payslip.organization_id == organization_id,
                Payslip.year == year, Payslip.month == month)
        .all()
    )
    out = []
    for r in rows:
        emp = r.employee
        out.append({
            "id": r.id, "employee_id": r.employee_id,
            "employee_name": emp.name if emp else None,
            "tax_id": emp.tax_id if emp else None,
            **_payslip_dict(r),
        })
    return out


def get_payslip(db, organization_id: int, payslip_id: int) -> Optional[dict]:
    r = db.query(Payslip).filter(
        Payslip.id == payslip_id, Payslip.organization_id == organization_id).first()
    if not r:
        return None
    emp = r.employee
    return {
        "id": r.id, "year": r.year, "month": r.month,
        "employee": {"id": emp.id, "name": emp.name, "tax_id": emp.tax_id} if emp else None,
        **_payslip_dict(r),
    }


# ---------------------------------------------------------------------- #
# Statutory reports
# ---------------------------------------------------------------------- #
def form_102(db, organization_id: int, year: int, month: int) -> dict[str, Any]:
    """Monthly employer withholding report (דוח 102): income tax + NI + health."""
    rows = _period_payslips(db, organization_id, year, month)
    income_tax = sum(float(r.income_tax or 0) for r in rows)
    ni_employee = sum(float(r.ni_employee or 0) for r in rows)
    health = sum(float(r.health_tax or 0) for r in rows)
    employer_ni = sum(float(r.employer_ni or 0) for r in rows)
    total_to_mas_hachnasa = income_tax
    total_to_btl = ni_employee + health + employer_ni
    due = date(year + (1 if month == 12 else 0), 1 if month == 12 else month + 1, 15)
    return {
        "report_type": "102", "period": f"{year}-{month:02d}",
        "employees": len(rows),
        "income_tax": round(income_tax, 2),
        "ni_employee": round(ni_employee, 2),
        "health_tax": round(health, 2),
        "employer_ni": round(employer_ni, 2),
        "total_income_tax_withheld": round(total_to_mas_hachnasa, 2),
        "total_national_insurance": round(total_to_btl, 2),
        "grand_total": round(total_to_mas_hachnasa + total_to_btl, 2),
        "due_date": due.isoformat(),
    }


def form_126(db, organization_id: int, year: int) -> dict[str, Any]:
    """Annual employer report (דוח 126): per-employee yearly totals."""
    rows = (
        db.query(Payslip)
        .filter(Payslip.organization_id == organization_id, Payslip.year == year)
        .all()
    )
    by_emp: dict[int, dict] = {}
    for r in rows:
        e = by_emp.setdefault(r.employee_id, {
            "employee_id": r.employee_id,
            "employee_name": r.employee.name if r.employee else None,
            "tax_id": r.employee.tax_id if r.employee else None,
            "months": 0, "gross": 0.0, "income_tax": 0.0,
            "ni_employee": 0.0, "health_tax": 0.0, "net": 0.0,
        })
        e["months"] += 1
        e["gross"] += float(r.gross or 0)
        e["income_tax"] += float(r.income_tax or 0)
        e["ni_employee"] += float(r.ni_employee or 0)
        e["health_tax"] += float(r.health_tax or 0)
        e["net"] += float(r.net or 0)
    employees = [{k: (round(v, 2) if isinstance(v, float) else v) for k, v in e.items()}
                 for e in by_emp.values()]
    totals = {
        "gross": round(sum(e["gross"] for e in employees), 2),
        "income_tax": round(sum(e["income_tax"] for e in employees), 2),
        "ni_employee": round(sum(e["ni_employee"] for e in employees), 2),
        "health_tax": round(sum(e["health_tax"] for e in employees), 2),
        "net": round(sum(e["net"] for e in employees), 2),
    }
    return {"report_type": "126", "year": year, "employee_count": len(employees),
            "employees": employees, "totals": totals}


def employee_withholding_rows(db, organization_id: int, year: int, month: int) -> list[dict]:
    """Adapter for tax_service._get_employee_data (Form 102 in tax_service)."""
    rows = _period_payslips(db, organization_id, year, month)
    return [{
        "income_tax": float(r.income_tax or 0),
        "social_security_employee": float(r.ni_employee or 0),
        "health_tax": float(r.health_tax or 0),
        "social_security_employer": float(r.employer_ni or 0),
    } for r in rows]


# ---------------------------------------------------------------------- #
def _period_payslips(db, organization_id: int, year: int, month: int):
    return (
        db.query(Payslip)
        .filter(Payslip.organization_id == organization_id,
                Payslip.year == year, Payslip.month == month)
        .all()
    )


def _payslip_dict(r: Payslip) -> dict:
    return {
        "gross": float(r.gross or 0), "income_tax": float(r.income_tax or 0),
        "ni_employee": float(r.ni_employee or 0), "health_tax": float(r.health_tax or 0),
        "pension_employee": float(r.pension_employee or 0), "net": float(r.net or 0),
        "employer_ni": float(r.employer_ni or 0), "employer_pension": float(r.employer_pension or 0),
        "employer_severance": float(r.employer_severance or 0), "employer_cost": float(r.employer_cost or 0),
    }


def _empty_totals() -> dict:
    return {k: 0.0 for k in (
        "gross", "income_tax", "ni_employee", "health_tax", "pension_employee",
        "net", "employer_ni", "employer_pension", "employer_severance", "employer_cost",
    )}
