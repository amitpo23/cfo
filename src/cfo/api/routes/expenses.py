"""
תיוק הוצאות — ניהול הוצאות ותיוקן ב-SUMIT
Expense filing routes.
"""
from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..dependencies import get_db, get_current_org_id, require_admin
from ...services import expense_category_service
from ...services.expense_category_service import CategoryInUseError
from ...services.expense_filing_service import ExpenseFilingService
from ...services.expense_ocr_pipeline import ExpenseOCRPipeline

router = APIRouter(prefix="/expenses", tags=["Expense Filing"])


class IntakeUpload(BaseModel):
    content_base64: str = Field(max_length=14_000_000)
    media_type: str
    filename: str = Field(default='document', max_length=255)


class IntakeProcess(BaseModel):
    version: int = Field(ge=1)
    retry: bool = False


class DerivationParent(BaseModel):
    document_id: int = Field(ge=1)
    version: int = Field(ge=1)


class DerivationPage(BaseModel):
    document_id: int = Field(ge=1)
    page: int = Field(ge=1)


class DerivationOutput(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    pages: list[DerivationPage] = Field(min_length=1, max_length=100)


class IntakeDerivation(BaseModel):
    parents: list[DerivationParent] = Field(min_length=1, max_length=10)
    outputs: list[DerivationOutput] = Field(min_length=1, max_length=100)
    reason: str = Field(min_length=20, max_length=2000)


@router.post('/intake/derive')
async def intake_derive(request: IntakeDerivation, db: Session = Depends(get_db),
                        org_id: int = Depends(get_current_org_id), user=Depends(require_admin)):
    from ...services.document_derivation import DocumentDerivationService
    try:
        return DocumentDerivationService(db, org_id).derive(**request.model_dump(), actor_id=user.id)
    except PermissionError as exc:
        raise HTTPException(403, str(exc))
    except RuntimeError as exc:
        raise HTTPException(409, str(exc))
    except ValueError as exc:
        raise HTTPException(404 if str(exc) == 'Document not found' else 400, str(exc))


@router.get('/intake')
async def intake_list(db: Session = Depends(get_db), org_id: int = Depends(get_current_org_id),
                      limit: int = 100, offset: int = 0):
    from ...services.document_intake import DocumentIntakeService
    try:
        return DocumentIntakeService(db, org_id).list_documents(limit=limit, offset=offset)
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.post('/intake')
async def intake_upload(request: IntakeUpload, db: Session = Depends(get_db),
                        org_id: int = Depends(get_current_org_id), user=Depends(require_admin)):
    import base64
    import binascii
    from ...services.document_intake import DocumentIntakeService
    try:
        content = base64.b64decode(request.content_base64, validate=True)
        return DocumentIntakeService(db, org_id).receive(content, media_type=request.media_type,
            filename=request.filename, source='upload', source_reference=f'user:{user.id}')
    except (ValueError, binascii.Error) as exc:
        raise HTTPException(400, str(exc))


@router.get('/intake/{document_id}')
async def intake_detail(document_id: int, db: Session = Depends(get_db), org_id: int = Depends(get_current_org_id)):
    from ...services.document_intake import DocumentIntakeService
    try:
        return DocumentIntakeService(db, org_id).detail(document_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc))


@router.get('/intake/{document_id}/source')
async def intake_source(document_id: int, db: Session = Depends(get_db), org_id: int = Depends(get_current_org_id)):
    from ...services.document_intake import DocumentIntakeService
    try:
        content, media_type = DocumentIntakeService(db, org_id).source(document_id)
        return Response(content, media_type=media_type, headers={
            'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
            'Content-Security-Policy': "sandbox; default-src 'none'", 'Content-Disposition': 'attachment'})
    except RuntimeError as exc:
        raise HTTPException(409, str(exc))
    except ValueError as exc:
        raise HTTPException(404, str(exc))


@router.get('/intake/{document_id}/preview')
def intake_preview(document_id: int, page: int = Query(1, ge=1, le=100),
                   db: Session = Depends(get_db), org_id: int = Depends(get_current_org_id)):
    from ...services.document_intake import DocumentIntakeService
    from fastapi.responses import JSONResponse
    try:
        return JSONResponse(DocumentIntakeService(db, org_id).preview(document_id, page_number=page),
            headers={'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'})
    except RuntimeError as exc:
        raise HTTPException(409, str(exc))
    except ValueError as exc:
        raise HTTPException(404 if str(exc) == 'Document not found' else 400, str(exc))


@router.post('/intake/{document_id}/process')
async def intake_process(document_id: int, request: IntakeProcess, db: Session = Depends(get_db),
                         org_id: int = Depends(get_current_org_id), user=Depends(require_admin)):
    from ...models import User, UserRole
    from ...services import membership_service
    from ...services.document_intake import DocumentIntakeService
    from ...database import SessionLocal
    actor_id = user.id
    def reauthorize():
        # Independent read after extraction: stale ORM identity must not retain a revoked role.
        with SessionLocal() as auth_db:
            actor = auth_db.query(User).filter_by(id=actor_id).first()
            if not actor or not actor.is_active or (actor.role != UserRole.SUPER_ADMIN and
                    membership_service.role_in(auth_db, actor_id, org_id) != UserRole.ADMIN):
                raise HTTPException(403, 'Document processing permission was revoked')
    try:
        return await DocumentIntakeService(db, org_id).process(document_id,
            expected_version=request.version, retry=request.retry, uploaded_by_user_id=actor_id,
            reauthorize=reauthorize)
    except ValueError as exc:
        raise HTTPException(404 if str(exc) == 'Document not found' else 409, str(exc))


class IntakeReview(BaseModel):
    version: int = Field(ge=1)
    fields: dict
    reason: str = Field(min_length=20, max_length=2000)


@router.post('/intake/{document_id}/review')
async def intake_review(document_id: int, request: IntakeReview, db: Session = Depends(get_db),
                        org_id: int = Depends(get_current_org_id), user=Depends(require_admin)):
    from ...services.document_intake import DocumentIntakeService
    try:
        return DocumentIntakeService(db, org_id).review(document_id,
            expected_version=request.version, fields=request.fields, reason=request.reason, actor_id=user.id)
    except PermissionError as exc:
        raise HTTPException(403, str(exc))
    except RuntimeError as exc:
        raise HTTPException(409, str(exc))
    except ValueError as exc:
        raise HTTPException(404 if str(exc) == 'Document not found' else 400, str(exc))


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
    # "tax_invoice" | "receipt" | "unknown"/None — שער-המסמך של israeli_tax_rules;
    # ללא ערך, vat_claimable נשאר None (honest-null) עד שמישהו יכריע.
    doc_kind: Optional[str] = None


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
    doc_kind: Optional[str] = None


@router.patch("/{expense_id}")
async def update_expense(
    expense_id: int,
    request: ExpenseUpdateRequest,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """עדכון/אישור הוצאה (סכום, פריט, ספק, אחוז ניכוי) לפני תיוק."""
    from ...services.irreversible_action_service import ActionConflictError
    service = ExpenseFilingService(db, organization_id=org_id)
    try:
        return {"status": "success", "data": service.update_expense(expense_id, request.model_dump(exclude_none=True))}
    except ActionConflictError as exc:
        raise HTTPException(409, str(exc))
    except ValueError as exc:
        detail = str(exc)
        code = 404 if "לא נמצאה" in detail else 400
        raise HTTPException(status_code=code, detail=detail)


@router.post("/{expense_id}/file")
async def file_expense(
    expense_id: int,
    approval_id: Optional[int] = Header(None, alias='X-Rezef-Approval-Id'),
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
    user=Depends(require_admin),
):
    """Submit one approved source expense; acknowledgement is not official books."""
    from ...services.irreversible_action_service import ActionAuthorizationError, ActionConflictError, ActionStateError
    service = ExpenseFilingService(db, organization_id=org_id)
    try:
        return {"status": "success", "data": await service.file_to_sumit(expense_id, approval_id=approval_id, actor_id=user.id)}
    except ActionAuthorizationError as exc:
        raise HTTPException(403, str(exc))
    except ActionConflictError as exc:
        raise HTTPException(409, str(exc))
    except ActionStateError as exc:
        raise HTTPException(502 if str(exc).startswith('Provider outcome is unknown') else 409, str(exc))
    except ValueError as exc:
        raise HTTPException(404 if str(exc) == 'Expense not found' else 400, str(exc))


class FilingProposal(BaseModel):
    reason: str = Field(min_length=20, max_length=2000)


@router.post('/{expense_id}/filing-proposal')
async def propose_expense_filing(expense_id: int, request: FilingProposal, db: Session = Depends(get_db),
                                 org_id: int = Depends(get_current_org_id), user=Depends(require_admin)):
    from ...services.expense_filing_workflow import ExpenseFilingWorkflow
    from ...services.irreversible_action_service import ActionAuthorizationError, ActionConflictError
    try:
        return ExpenseFilingWorkflow(db, org_id).propose(expense_id, actor_id=user.id, reason=request.reason)
    except ActionAuthorizationError as exc:
        raise HTTPException(403, str(exc))
    except ActionConflictError as exc:
        raise HTTPException(409, str(exc))
    except ValueError as exc:
        raise HTTPException(404 if str(exc) == 'Expense not found' else 400, str(exc))


@router.get('/{expense_id}/filing-status')
async def expense_filing_status(expense_id: int, db: Session = Depends(get_db), org_id: int = Depends(get_current_org_id)):
    from ...services.expense_filing_workflow import ExpenseFilingWorkflow
    try:
        return ExpenseFilingWorkflow(db, org_id).status(expense_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc))


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
    user=Depends(require_admin),
):
    raise HTTPException(409, 'Bulk filing requires a separately reviewed batch; prepare and approve each source expense')


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
    אימות ח.פ -> סיווג -> עדכון (נשמר תמיד ל-DB).

    auto_file=true אינו מתייק בפועל: תיוק ל-SUMIT דורש X-Rezef-Approval-Id
    מאושר-אנושי (אפס אוטונומיה בבלתי-הפיך, CLAUDE.md) שאין לו מסלול הזרמה
    מ-OCR אוטומטי — הקריאה תיכשל תמיד עם 400 בבקשת auto_file=true. הדגל
    נשאר בממשק לתאימות; תיוק בפועל דורש את מסלול האישור הידני (/{id}/file)."""
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
    """עיבוד OCR גורף של טיוטות הוצאה ממתינות (source=sumit) דרך ה-API.

    auto_file=true: כמו ב-/{expense_id}/ocr, תיוק בפועל חסום-לתמיד בלי
    אישור אנושי — כאן זה מדווח כ-status="error" פר-שורה (לא מפיל את הריצה
    הגורפת), לא כ-HTTP 400."""
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


# ---------------------------------------------------------------------- #
# כרטיסי הוצאה מותאמים אישית לארגון (ExpenseCategory) — "לבנות קטגוריות
# הוצאה שההוצאות ייקלטו לפי כרטיסים שאני אגיד לפתוח". משלימים את הקטגוריות
# המובנות (VALID_CATEGORIES) בממשק אחד; ה-classifier מעדיף את מילות המפתח
# של הכרטיסים המותאמים על פני המובנות.
# ---------------------------------------------------------------------- #

class ExpenseCategoryCreateRequest(BaseModel):
    key: str
    name_he: str
    keywords: Optional[List[str]] = None


@router.get("/categories")
async def list_expense_categories(
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """קטגוריות מובנות + כרטיסים מותאמים אישית של הארגון, מסומן מי הוא מי."""
    return {"status": "success", "data": expense_category_service.list_categories(db, org_id)}


@router.post("/categories")
async def create_expense_category(
    request: ExpenseCategoryCreateRequest,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """פתיחת כרטיס הוצאה מותאם אישית לארגון."""
    try:
        data = expense_category_service.create_category(
            db, org_id, key=request.key, name_he=request.name_he, keywords=request.keywords,
        )
        return {"status": "success", "data": data}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.delete("/categories/{category_id}")
async def delete_expense_category(
    category_id: int,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_org_id),
):
    """מחיקת כרטיס הוצאה מותאם אישית של הארגון. מסורב (409) אם הוצאות
    כלשהן עדיין משתמשות בקטגוריה זו — עם הכמות, לא רק סירוב עיוור."""
    try:
        expense_category_service.delete_category(db, org_id, category_id)
        return {"status": "success", "data": {"deleted": category_id}}
    except CategoryInUseError as exc:
        raise HTTPException(status_code=409, detail={"message": str(exc), "count": exc.count})
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
