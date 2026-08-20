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
    is_valid_account,
    is_valid_bank_code,
    is_valid_branch,
    is_valid_israeli_id,
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
    """איסוף חשבוניות ספק פתוחות + פרטי הבנק; מחזיר (תנועות, מדולגות).

    הסריקה הכללית (בלי ``bill_ids``) עדיין מסננת ``balance != 0`` -- חשבונית
    ששולמה במלואה (balance=0) פשוט לא רלוונטית לתשלום ואין טעם באזהרה על כל
    חשבונית סגורה בכל תצוגה מקדימה. אבל כשהמשתמש *בחר* חשבוניות מפורשות
    (``bill_ids``) אסור שחשבונית שנבחרה תיעלם בשקט מהתוצאה -- אז הסינון
    מוסר ומועבר ללולאה, שם כל יתרה שאינה חיובית (שלילית *או אפס*, למשל אחרי
    זיכוי/תשלום ביתר) מקבלת אזהרה מפורשת: מס"ב לא משדרת קובץ עם סך שלילי
    (או אפס) ללקוח (ר' docs/SUMIT_KNOWLEDGE_BASE.md).
    """
    query = (
        db.query(Bill, Contact)
        .outerjoin(Contact, Bill.vendor_id == Contact.id)
        .filter(Bill.organization_id == org_id)
    )
    if bill_ids:
        query = query.filter(Bill.id.in_(bill_ids))
    else:
        query = query.filter(Bill.balance != 0)

    payments: List[MasavPayment] = []
    skipped: List[dict] = []
    for bill, vendor in query.all():
        name = bill.bill_number or bill.external_id or f"BILL-{bill.id}"
        balance = bill.balance or 0
        if balance <= 0:
            skipped.append({
                "bill": name,
                "vendor": vendor.name if vendor else None,
                "reason": (
                    f"מס\"ב לא תשדר סך שלילי או אפס: יתרת החשבונית ({balance}) אינה חיובית "
                    "— יש לבדוק זיכוי/תשלום ביתר מול הספק"
                ),
            })
            continue
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
        if not is_valid_bank_code(bank_code):
            skipped.append({
                "bill": name,
                "vendor": vendor.name,
                "reason": f"קוד בנק ({bank_code}) אינו ברשימת חברי מס\"ב — יש לבדוק מול הספק",
            })
            continue
        if not is_valid_branch(branch):
            skipped.append({
                "bill": name,
                "vendor": vendor.name,
                "reason": f"מספר סניף ({branch}) לא תקין — נדרשות 1-3 ספרות",
            })
            continue
        if not is_valid_account(account):
            skipped.append({
                "bill": name,
                "vendor": vendor.name,
                "reason": f"מספר חשבון ({account}) לא תקין — נדרשות 4-9 ספרות",
            })
            continue
        if not is_valid_israeli_id(beneficiary_id):
            skipped.append({
                "bill": name,
                "vendor": vendor.name,
                "reason": f"מספר זיהוי ({beneficiary_id}) נכשל בביקורת הספרה — יש לבדוק מול הספק",
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
        # חוק 17 (מרכז הידע): מס"ב אינה מדווחת כשל על פרטי בנק שגויים —
        # תשלום לחשבון סגור פשוט לא יגיע. הוולידציה כאן מבנית בלבד;
        # אימות מול מאגר הבנקים: POST /api/masav/verify-accounts.
        "bank_verification_notice": (
            "מס\"ב אינה מדווחת כשל על פרטי בנק שגויים (חוק 17). החשבונות "
            "עברו בדיקה מבנית בלבד — מומלץ להריץ אימות מול SUMIT "
            "(verify-accounts) לפני יצירת הקובץ."
        ),
    }


async def _verify_accounts_against_sumit(db, org_id: int, accounts: list) -> list:
    """אימות חשבונות מול SUMIT (מאגר הבנקים) — קריאת API אחת לכל חשבון
    ייחודי, דרך המגביל של הארגון."""
    from ...integrations.sumit_models import BankAccountVerification
    from ...services.recurring_billing_service import _client_for_org

    client = await _client_for_org(db, org_id)
    results = []
    try:
        for account in accounts:
            outcome = await client.verify_bank_account(BankAccountVerification(
                bank_number=account["bank_code"],
                branch_number=account["branch"],
                account_number=account["account_number"],
            ))
            data = outcome.get("Data") or outcome or {}
            results.append({
                **account,
                "valid": bool(data.get("Result")),
                "valid_branch": bool(data.get("ValidBranch")),
                "is_limited_account": bool(data.get("IsLimitedAccount")),
            })
    finally:
        await client.client.aclose()
    return results


@router.post("/verify-accounts")
async def verify_masav_accounts(
    request: MasavGenerateRequest,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """חוק 17: אימות חשבונות המוטבים מול SUMIT לפני יצירת קובץ מס"ב.

    פעולה מפורשת (לא אוטומטית) כי כל חשבון ייחודי = קריאת API אחת;
    חשבונות כפולים בין תשלומים מאומתים פעם אחת בלבד.
    """
    payments, _skipped = _gather(db, org_id, request.bill_ids)
    if not payments:
        return {"accounts": [], "verified_count": 0,
                "note": "אין תשלומים ממתינים — אין מה לאמת."}

    distinct: dict[tuple, dict] = {}
    for p in payments:
        key = (p.bank_code, p.branch, p.account_number)
        distinct.setdefault(key, {
            "bank_code": p.bank_code, "branch": p.branch,
            "account_number": p.account_number,
            "beneficiary_name": p.beneficiary_name,
        })

    results = await _verify_accounts_against_sumit(
        db, org_id, list(distinct.values()),
    )
    invalid = [r for r in results if not r.get("valid")]
    return {
        "accounts": results,
        "verified_count": len(results),
        "invalid_count": len(invalid),
        "warning": (
            "יש חשבונות שלא עברו אימות — אין ליצור קובץ מס\"ב עבורם"
            if invalid else None
        ),
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
