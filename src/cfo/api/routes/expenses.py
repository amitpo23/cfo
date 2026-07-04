"""
תיוק הוצאות — ניהול הוצאות ותיוקן ב-SUMIT
Expense filing routes.
"""
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..dependencies import get_db, get_current_org_id
from ...services.expense_filing_service import ExpenseFilingService
from ...services.expense_ocr_pipeline import ExpenseOCRPipeline

router = APIRouter(prefix="/expenses", tags=["Expense Filing"])


class ExpenseCreateRequest(BaseModel):
    supplier_name: str
    amount: float
    vat_amount: float = 0
    total: Optional[float] = None
    expense_date: date
    category: Optional[str] = None
    description: Optional[str] = None
    invoice_number: Optional[str] = None
    supplier_id: Optional[int] = None


@router.get("")
async def list_expenses(
    status: Optional[str] = None,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """רשימת הוצאות (אופציונלי לפי סטטוס: pending/filed/error)."""
    service = ExpenseFilingService(db, organization_id=org_id)
    return {"status": "success", "data": service.list_expenses(status)}


@router.post("")
async def create_expense(
    request: ExpenseCreateRequest,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """יצירת הוצאה חדשה (סטטוס pending עד לתיוק ב-SUMIT)."""
    service = ExpenseFilingService(db, organization_id=org_id)
    return {"status": "success", "data": service.create_expense(request.model_dump())}


class ExpenseUpdateRequest(BaseModel):
    supplier_name: Optional[str] = None
    amount: Optional[float] = None
    vat_amount: Optional[float] = None
    total: Optional[float] = None
    category: Optional[str] = None
    description: Optional[str] = None
    invoice_number: Optional[str] = None
    deduction_percent: Optional[float] = Field(default=None, ge=0, le=100)


@router.patch("/{expense_id}")
async def update_expense(
    expense_id: int,
    request: ExpenseUpdateRequest,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """עדכון/אישור הוצאה (סכום, פריט, ספק, אחוז ניכוי) לפני תיוק."""
    service = ExpenseFilingService(db, organization_id=org_id)
    try:
        return {"status": "success", "data": service.update_expense(expense_id, request.model_dump(exclude_none=True))}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/{expense_id}/file")
async def file_expense(
    expense_id: int,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """תיוק הוצאה ב-SUMIT."""
    service = ExpenseFilingService(db, organization_id=org_id)
    try:
        return {"status": "success", "data": await service.file_to_sumit(expense_id)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/classify")
async def classify_expenses(
    reclassify_all: bool = False,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """סיווג אוטומטי של הוצאות (ברירת מחדל: רק ללא קטגוריה)."""
    service = ExpenseFilingService(db, organization_id=org_id)
    return {"status": "success", "data": service.classify_uncategorized(reclassify_all)}


@router.post("/file-all")
async def file_all_pending(
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """תיוק גורף של כל ההוצאות הממתינות ב-SUMIT."""
    service = ExpenseFilingService(db, organization_id=org_id)
    try:
        return {"status": "success", "data": await service.file_all_pending()}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/pcn874-readiness")
async def pcn874_readiness(
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """דוח מוכנות PCN874 — אילו הוצאות חסרות ח.פ/מע"מ וסיכום סכומים להתאמה מול SUMIT."""
    service = ExpenseFilingService(db, organization_id=org_id)
    return {"status": "success", "data": service.pcn874_readiness()}


@router.post("/resolve-suppliers")
async def resolve_suppliers(
    limit: Optional[int] = None,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """פתרון שמות ספקים מ-SUMIT (ID→שם) וסיווג מחדש."""
    service = ExpenseFilingService(db, organization_id=org_id)
    try:
        return {"status": "success", "data": await service.resolve_supplier_names(limit=limit)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/{expense_id}/ocr")
async def ocr_expense(
    expense_id: int,
    auto_file: bool = False,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """עיבוד OCR אוטומטי של טיוטת הוצאה בודדת: משיכת צילום -> חילוץ ראייה ->
    אימות ח.פ -> סיווג -> עדכון. auto_file=true גם מתייק ב-SUMIT אם אומת."""
    pipeline = ExpenseOCRPipeline(db, organization_id=org_id)
    try:
        return {"status": "success", "data": await pipeline.process_expense(expense_id, auto_file=auto_file)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/ocr-pending")
async def ocr_pending(
    limit: Optional[int] = None,
    auto_file: bool = False,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """עיבוד OCR גורף של טיוטות הוצאה ממתינות (source=sumit) דרך ה-API."""
    pipeline = ExpenseOCRPipeline(db, organization_id=org_id)
    try:
        return {"status": "success", "data": await pipeline.process_pending(limit=limit, auto_file=auto_file)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/sync-pending")
async def sync_pending(
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """משיכת מסמכי הוצאה מ-SUMIT אל המערכת."""
    service = ExpenseFilingService(db, organization_id=org_id)
    try:
        return {"status": "success", "data": await service.sync_pending_from_sumit()}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
