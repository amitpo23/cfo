"""
מס"ב — יצירת קובץ זיכויים לתשלומי ספקים
Masav supplier-payment file routes.
"""
import re
from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..dependencies import get_db, get_current_org_id
from ...models import Bill, Contact, Organization
from ...services.masav_service import (
    MasavInstitution,
    MasavPayment,
    MasavValidationError,
    build_masav_file,
    summarize,
)

router = APIRouter(prefix="/masav", tags=["Masav Payments"])


class MasavSettings(BaseModel):
    """הגדרות מוסד מס"ב (ניתנות ע"י מס"ב)."""
    institution_code: str   # מוסד/נושא (8 ספרות)
    sending_institution: str  # מוסד שולח (5 ספרות)
    institution_name: str


class MasavGenerateRequest(BaseModel):
    payment_date: date
    bill_ids: Optional[List[int]] = None  # None = כל חשבוניות הספק הפתוחות
    # אופציונלי — דורס את הגדרות המוסד השמורות
    settings: Optional[MasavSettings] = None


def _digits(value: Optional[str]) -> str:
    return re.sub(r"\D", "", value or "")


def _load_settings(
    db: Session, org_id: int, override: Optional[MasavSettings]
) -> MasavSettings:
    if override:
        return override
    org = db.query(Organization).filter(Organization.id == org_id).first()
    masav = (org.settings or {}).get("masav") if org else None
    if not masav:
        raise HTTPException(
            status_code=400,
            detail="הגדרות מס\"ב חסרות. יש להגדיר מוסד/נושא ומוסד שולח תחילה.",
        )
    return MasavSettings(**masav)


def _gather(db: Session, org_id: int, bill_ids: Optional[List[int]]):
    """איסוף חשבוניות ספק פתוחות + פרטי הבנק; מחזיר (תנועות, מדולגות)."""
    query = (
        db.query(Bill, Contact)
        .outerjoin(Contact, Bill.vendor_id == Contact.id)
        .filter(Bill.organization_id == org_id, Bill.balance > 0)
    )
    if bill_ids:
        query = query.filter(Bill.id.in_(bill_ids))

    payments: List[MasavPayment] = []
    skipped: List[dict] = []
    for bill, vendor in query.all():
        name = bill.bill_number or bill.external_id or f"BILL-{bill.id}"
        if vendor is None:
            skipped.append({"bill": name, "reason": "אין ספק משויך"})
            continue
        bank_code = _digits(vendor.bank_code)
        branch = _digits(vendor.bank_branch)
        account = _digits(vendor.bank_account_number)
        beneficiary_id = _digits(vendor.tax_id)
        missing = []
        if not bank_code:
            missing.append("קוד בנק")
        if not branch:
            missing.append("סניף")
        if not account:
            missing.append("מספר חשבון")
        if not beneficiary_id:
            missing.append("מספר זיהוי (ח.פ / ת.ז)")
        if missing:
            skipped.append({
                "bill": name,
                "vendor": vendor.name,
                "reason": "חסרים פרטי בנק: " + ", ".join(missing),
            })
            continue
        payments.append(MasavPayment(
            bank_code=bank_code,
            branch=branch,
            account_number=account,
            beneficiary_id=beneficiary_id,
            beneficiary_name=vendor.bank_account_holder or vendor.name,
            amount=bill.balance or 0,
            reference=bill.bill_number or (vendor.external_id or str(bill.id)),
        ))
    return payments, skipped


@router.get("/settings")
async def get_masav_settings(
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """קריאת הגדרות מס"ב של הארגון."""
    org = db.query(Organization).filter(Organization.id == org_id).first()
    masav = (org.settings or {}).get("masav") if org else None
    return {"configured": bool(masav), "settings": masav}


@router.post("/settings")
async def save_masav_settings(
    settings: MasavSettings,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """שמירת הגדרות מס"ב של הארגון."""
    org = db.query(Organization).filter(Organization.id == org_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="ארגון לא נמצא")
    current = dict(org.settings or {})
    current["masav"] = settings.model_dump()
    org.settings = current
    db.commit()
    return {"status": "success", "settings": current["masav"]}


@router.post("/preview")
async def preview_masav(
    request: MasavGenerateRequest,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """תצוגה מקדימה: כמה תנועות ייכללו, סכום כולל, ומה מדולג."""
    payments, skipped = _gather(db, org_id, request.bill_ids)
    settings = _load_settings(db, org_id, request.settings)
    inst = MasavInstitution(
        institution_code=settings.institution_code,
        sending_institution=settings.sending_institution,
        institution_name=settings.institution_name,
        payment_date=request.payment_date,
        payments=payments,
    )
    return {
        "summary": summarize([inst]) if payments else {
            "institutions": 0, "payment_count": 0, "total_amount": 0, "currency": "ILS",
        },
        "payments": [
            {
                "beneficiary_name": p.beneficiary_name,
                "bank_code": p.bank_code,
                "branch": p.branch,
                "account_number": p.account_number,
                "amount": float(p.amount),
                "reference": p.reference,
            }
            for p in payments
        ],
        "skipped": skipped,
    }


@router.post("/generate")
async def generate_masav(
    request: MasavGenerateRequest,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """יצירת קובץ מס"ב להורדה."""
    payments, skipped = _gather(db, org_id, request.bill_ids)
    if not payments:
        raise HTTPException(
            status_code=400,
            detail="אין תנועות לתשלום. בדוק שלספקים יש פרטי בנק וחשבוניות פתוחות.",
        )
    settings = _load_settings(db, org_id, request.settings)
    inst = MasavInstitution(
        institution_code=settings.institution_code,
        sending_institution=settings.sending_institution,
        institution_name=settings.institution_name,
        payment_date=request.payment_date,
        payments=payments,
    )
    try:
        content = build_masav_file([inst])
    except MasavValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    filename = f"masav_{request.payment_date.strftime('%Y%m%d')}.txt"
    return Response(
        content=content,
        media_type="text/plain; charset=cp862",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Masav-Skipped": str(len(skipped)),
        },
    )
