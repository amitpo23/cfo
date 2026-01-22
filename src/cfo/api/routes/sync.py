"""
Data Sync and Bank Statement API Routes
נתיבי API לסנכרון נתונים וקליטת דפי בנק
"""
from typing import Optional
from datetime import date
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..dependencies import get_db, get_current_user
from ...services.data_sync_service import DataSyncService
from ...services.bank_statement_service import BankStatementService, BankFormat

router = APIRouter(prefix="/sync", tags=["Data Sync & Bank Import"])


# ============= Request Models =============

class SyncRequest(BaseModel):
    """בקשת סנכרון"""
    from_date: Optional[date] = None
    to_date: Optional[date] = None


# ============= SUMIT Sync Endpoints =============

@router.post("/sumit/documents")
async def sync_documents(
    request: SyncRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    סנכרון מסמכים מ-SUMIT
    Sync documents from SUMIT API
    """
    org_id = current_user.get('organization_id', 1)
    service = DataSyncService(db, org_id)
    
    try:
        result = await service.sync_documents(
            from_date=request.from_date,
            to_date=request.to_date
        )
        return result
    finally:
        await service.close()


@router.post("/sumit/payments")
async def sync_payments(
    request: SyncRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    סנכרון תשלומים מ-SUMIT
    Sync payments from SUMIT API
    """
    org_id = current_user.get('organization_id', 1)
    service = DataSyncService(db, org_id)
    
    try:
        result = await service.sync_payments(
            from_date=request.from_date,
            to_date=request.to_date
        )
        return result
    finally:
        await service.close()


@router.post("/sumit/billing")
async def sync_billing(
    request: SyncRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    סנכרון עסקאות סליקה מ-SUMIT
    Sync billing/credit card transactions from SUMIT API
    """
    org_id = current_user.get('organization_id', 1)
    service = DataSyncService(db, org_id)
    
    try:
        result = await service.sync_billing_transactions(
            from_date=request.from_date,
            to_date=request.to_date
        )
        return result
    finally:
        await service.close()


@router.get("/sumit/debts")
async def get_debts(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    שליפת דוח חובות מ-SUMIT
    Get debt report from SUMIT API
    """
    org_id = current_user.get('organization_id', 1)
    service = DataSyncService(db, org_id)
    
    try:
        result = await service.sync_debt_report()
        return result
    finally:
        await service.close()


@router.get("/sumit/income-items")
async def get_income_items(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    שליפת פריטי הכנסה מ-SUMIT
    Get income items from SUMIT API
    """
    org_id = current_user.get('organization_id', 1)
    service = DataSyncService(db, org_id)
    
    try:
        result = await service.sync_income_items()
        return result
    finally:
        await service.close()


@router.get("/sumit/vat-rate")
async def get_vat_rate(
    for_date: Optional[date] = None,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    שליפת שיעור מע"מ מ-SUMIT
    Get current VAT rate from SUMIT API
    """
    org_id = current_user.get('organization_id', 1)
    service = DataSyncService(db, org_id)
    
    try:
        rate = await service.get_vat_rate(for_date)
        return {"vat_rate": rate, "date": for_date or date.today()}
    finally:
        await service.close()


@router.get("/sumit/exchange-rate")
async def get_exchange_rate(
    from_currency: str = "USD",
    to_currency: str = "ILS",
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    שליפת שער חליפין מ-SUMIT
    Get exchange rate from SUMIT API
    """
    org_id = current_user.get('organization_id', 1)
    service = DataSyncService(db, org_id)
    
    try:
        rate = await service.get_exchange_rate(from_currency, to_currency)
        return {
            "from_currency": from_currency,
            "to_currency": to_currency,
            "rate": rate,
            "date": date.today()
        }
    finally:
        await service.close()


@router.post("/sumit/full")
async def sync_all_data(
    request: SyncRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    סנכרון מלא של כל הנתונים מ-SUMIT
    Full sync of all data from SUMIT API
    """
    org_id = current_user.get('organization_id', 1)
    service = DataSyncService(db, org_id)
    
    try:
        result = await service.sync_all(
            from_date=request.from_date,
            to_date=request.to_date
        )
        return result
    finally:
        await service.close()


# ============= Bank Statement Import Endpoints =============

@router.post("/bank/import")
async def import_bank_statement(
    file: UploadFile = File(...),
    bank_format: str = Form(default="auto"),
    auto_categorize: bool = Form(default=True),
    create_transactions: bool = Form(default=True),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    ייבוא דף בנק
    Import bank statement (CSV/Excel)
    
    Supported formats:
    - leumi (בנק לאומי)
    - hapoalim (בנק הפועלים)
    - discount (בנק דיסקונט)
    - mizrahi (בנק מזרחי-טפחות)
    - isracard (ישראכרט)
    - cal (כאל)
    - max (מקס)
    - generic (גנרי)
    - auto (זיהוי אוטומטי)
    """
    org_id = current_user.get('organization_id', 1)
    service = BankStatementService(db, org_id)
    
    # זיהוי סוג הקובץ
    filename = file.filename.lower() if file.filename else ''
    if filename.endswith('.xlsx') or filename.endswith('.xls'):
        file_type = 'excel'
    else:
        file_type = 'csv'
    
    # קליטת הקובץ
    content = await file.read()
    
    try:
        bank_format_enum = BankFormat(bank_format)
    except ValueError:
        bank_format_enum = BankFormat.AUTO
    
    result = service.import_statement(
        content=content,
        bank_format=bank_format_enum,
        file_type=file_type,
        auto_categorize=auto_categorize,
        create_transactions=create_transactions
    )
    
    return result


@router.post("/bank/parse")
async def parse_bank_statement(
    file: UploadFile = File(...),
    bank_format: str = Form(default="auto"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    ניתוח דף בנק ללא שמירה
    Parse bank statement without saving (preview mode)
    """
    org_id = current_user.get('organization_id', 1)
    service = BankStatementService(db, org_id)
    
    filename = file.filename.lower() if file.filename else ''
    if filename.endswith('.xlsx') or filename.endswith('.xls'):
        file_type = 'excel'
    else:
        file_type = 'csv'
    
    content = await file.read()
    
    try:
        bank_format_enum = BankFormat(bank_format)
    except ValueError:
        bank_format_enum = BankFormat.AUTO
    
    result = service.import_statement(
        content=content,
        bank_format=bank_format_enum,
        file_type=file_type,
        auto_categorize=True,
        create_transactions=False  # לא ליצור עסקאות - רק ניתוח
    )
    
    return result


@router.get("/bank/spending-patterns")
async def get_spending_patterns(
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    ניתוח דפוסי הוצאות
    Analyze spending patterns from imported bank transactions
    """
    org_id = current_user.get('organization_id', 1)
    service = BankStatementService(db, org_id)
    
    result = service.get_spending_patterns(from_date, to_date)
    return result


@router.get("/bank/recurring")
async def get_recurring_transactions(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    זיהוי עסקאות חוזרות
    Detect recurring transactions from bank statements
    """
    org_id = current_user.get('organization_id', 1)
    service = BankStatementService(db, org_id)
    
    result = service.detect_recurring_transactions()
    return {"recurring_transactions": result}


@router.get("/bank/supported-formats")
async def get_supported_formats():
    """
    רשימת פורמטים נתמכים
    List supported bank statement formats
    """
    return {
        "formats": [
            {"id": "auto", "name": "זיהוי אוטומטי", "description": "Auto-detect format"},
            {"id": "leumi", "name": "בנק לאומי", "description": "Bank Leumi"},
            {"id": "hapoalim", "name": "בנק הפועלים", "description": "Bank Hapoalim"},
            {"id": "discount", "name": "בנק דיסקונט", "description": "Discount Bank"},
            {"id": "mizrahi", "name": "בנק מזרחי-טפחות", "description": "Mizrahi-Tefahot Bank"},
            {"id": "isracard", "name": "ישראכרט", "description": "Isracard Credit Card"},
            {"id": "cal", "name": "כאל", "description": "Cal Credit Card"},
            {"id": "max", "name": "מקס", "description": "Max Credit Card"},
            {"id": "generic", "name": "גנרי", "description": "Generic CSV/Excel"}
        ],
        "file_types": ["csv", "xlsx", "xls"]
    }
