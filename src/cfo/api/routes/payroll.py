"""
Payroll routes — employees, payroll runs, payslips, and Form 102 / 126.
Organization-scoped. Salary math is deterministic (services/payroll_service.py).
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ...database import get_db_session
from ..dependencies import get_current_org_id
from ...models import Employee
from ...services import payroll_service

router = APIRouter()


class EmployeeRequest(BaseModel):
    name: str = Field(..., min_length=1)
    tax_id: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    gross_salary: float = 0
    credit_points: float = 2.25
    pension_pct: float = 6.0
    start_date: Optional[str] = None
    bank_code: Optional[str] = None
    bank_branch: Optional[str] = None
    bank_account_number: Optional[str] = None


def _emp_dict(e: Employee) -> dict:
    return {
        "id": e.id, "name": e.name, "tax_id": e.tax_id, "email": e.email, "phone": e.phone,
        "gross_salary": float(e.gross_salary or 0), "credit_points": float(e.credit_points or 0),
        "pension_pct": float(e.pension_pct or 0),
        "start_date": e.start_date.isoformat() if e.start_date else None,
        "is_active": e.is_active,
    }


# ---- Employees CRUD ---- #
@router.post("/payroll/employees")
async def create_employee(body: EmployeeRequest, org_id: int = Depends(get_current_org_id), db: Session = Depends(get_db_session)):
    emp = Employee(
        organization_id=org_id, name=body.name, tax_id=body.tax_id, email=body.email,
        phone=body.phone, gross_salary=body.gross_salary, credit_points=body.credit_points,
        pension_pct=body.pension_pct, bank_code=body.bank_code, bank_branch=body.bank_branch,
        bank_account_number=body.bank_account_number,
        start_date=date.fromisoformat(body.start_date) if body.start_date else None,
    )
    db.add(emp)
    db.commit()
    db.refresh(emp)
    return _emp_dict(emp)


@router.get("/payroll/employees")
async def list_employees(org_id: int = Depends(get_current_org_id), db: Session = Depends(get_db_session)):
    rows = db.query(Employee).filter(
        Employee.organization_id == org_id, Employee.is_active == True).all()  # noqa: E712
    return {"employees": [_emp_dict(e) for e in rows]}


@router.patch("/payroll/employees/{employee_id}")
async def update_employee(employee_id: int, body: EmployeeRequest, org_id: int = Depends(get_current_org_id), db: Session = Depends(get_db_session)):
    emp = _employee_or_404(db, org_id, employee_id)
    for field in ("name", "tax_id", "email", "phone", "gross_salary", "credit_points",
                  "pension_pct", "bank_code", "bank_branch", "bank_account_number"):
        setattr(emp, field, getattr(body, field))
    if body.start_date:
        emp.start_date = date.fromisoformat(body.start_date)
    emp.updated_at = datetime.now(timezone.utc)
    db.commit()
    return _emp_dict(emp)


@router.delete("/payroll/employees/{employee_id}")
async def delete_employee(employee_id: int, org_id: int = Depends(get_current_org_id), db: Session = Depends(get_db_session)):
    emp = _employee_or_404(db, org_id, employee_id)
    emp.is_active = False
    db.commit()
    return {"deleted": True}


# ---- Payroll run + payslips ---- #
@router.post("/payroll/run")
async def run_payroll(year: int = Query(...), month: int = Query(..., ge=1, le=12),
                      org_id: int = Depends(get_current_org_id), db: Session = Depends(get_db_session)):
    return payroll_service.run_payroll(db, org_id, year, month)


@router.get("/payroll/payslips")
async def list_payslips(year: int = Query(...), month: int = Query(..., ge=1, le=12),
                        org_id: int = Depends(get_current_org_id), db: Session = Depends(get_db_session)):
    return {"payslips": payroll_service.list_payslips(db, org_id, year, month)}


@router.get("/payroll/payslips/{payslip_id}")
async def get_payslip(payslip_id: int, org_id: int = Depends(get_current_org_id), db: Session = Depends(get_db_session)):
    p = payroll_service.get_payslip(db, org_id, payslip_id)
    if not p:
        raise HTTPException(404, "Payslip not found")
    return p


# ---- Statutory reports ---- #
@router.get("/payroll/reports/102")
async def report_102(year: int = Query(...), month: int = Query(..., ge=1, le=12),
                     org_id: int = Depends(get_current_org_id), db: Session = Depends(get_db_session)):
    return payroll_service.form_102(db, org_id, year, month)


@router.get("/payroll/reports/126")
async def report_126(year: int = Query(...), org_id: int = Depends(get_current_org_id),
                     db: Session = Depends(get_db_session)):
    return payroll_service.form_126(db, org_id, year)


def _employee_or_404(db, org_id: int, employee_id: int) -> Employee:
    emp = db.query(Employee).filter(
        Employee.id == employee_id, Employee.organization_id == org_id).first()
    if not emp:
        raise HTTPException(404, "Employee not found")
    return emp
