"""Daily-cumulative intra-month report routes. Organization-scoped, derived."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ...database import get_db_session
from ..dependencies import get_current_org_id
from ...services import daily_reports_service

router = APIRouter()


def _parse_as_of(as_of: Optional[str]) -> Optional[date]:
    if not as_of:
        return None
    try:
        return datetime.fromisoformat(as_of).date()
    except ValueError:
        return None


@router.get("/daily-reports/cumulative-pl")
def cumulative_pl(
    year: int = Query(...),
    month: int = Query(..., ge=1, le=12),
    org_id: int = Depends(get_current_org_id),
    db: Session = Depends(get_db_session),
):
    return daily_reports_service.cumulative_pl(db, org_id, year, month)


@router.get("/daily-reports/ar-aging")
def ar_aging(
    as_of: Optional[str] = Query(None),
    org_id: int = Depends(get_current_org_id),
    db: Session = Depends(get_db_session),
):
    return daily_reports_service.ar_aging(db, org_id, _parse_as_of(as_of))


@router.get("/daily-reports/ap-aging")
def ap_aging(
    as_of: Optional[str] = Query(None),
    org_id: int = Depends(get_current_org_id),
    db: Session = Depends(get_db_session),
):
    return daily_reports_service.ap_aging(db, org_id, _parse_as_of(as_of))


@router.get("/daily-reports/vat")
def vat_report(
    year: int = Query(...),
    month: int = Query(..., ge=1, le=12),
    months: int = Query(1, ge=1, le=2, description="1=חודשי, 2=דו-חודשי (מאי-יוני וכו')"),
    basis: Literal["document", "captured"] = Query(
        "document", description="document=תאריך מסמך (ברירת מחדל), captured=מועד קליטה לתשומות"),
    org_id: int = Depends(get_current_org_id),
    db: Session = Depends(get_db_session),
):
    return daily_reports_service.vat_report_period(db, org_id, year, month,
                                                    months=months, basis=basis)


@router.get("/daily-reports/pcn874")
def pcn874_file(
    year: int = Query(...),
    month: int = Query(..., ge=1, le=12),
    months: int = Query(1, ge=1, le=2),
    basis: Literal["document", "captured"] = Query("document"),
    company_vat_id: str = Query("000000000"),
    org_id: int = Depends(get_current_org_id),
    db: Session = Depends(get_db_session),
):
    """PCN874 detailed-VAT file (fixed-width draft) for the period, as JSON."""
    from ...services import pcn874
    return pcn874.build_pcn874(db, org_id, year, month, months=months, basis=basis,
                               company_vat_id=company_vat_id)


@router.get("/daily-reports/pcn874/file")
def pcn874_download(
    year: int = Query(...),
    month: int = Query(..., ge=1, le=12),
    months: int = Query(1, ge=1, le=2),
    basis: Literal["document", "captured"] = Query("document"),
    company_vat_id: str = Query("000000000"),
    org_id: int = Depends(get_current_org_id),
    db: Session = Depends(get_db_session),
):
    """PCN874 detailed-VAT file as a downloadable attachment (text/plain).

    DRAFT — see pcn874.DISCLAIMER: field layout needs verification against the Tax
    Authority's current spec before submission.
    """
    from fastapi.responses import PlainTextResponse
    from ...services import pcn874

    out = pcn874.build_pcn874(db, org_id, year, month, months=months, basis=basis,
                              company_vat_id=company_vat_id)
    return PlainTextResponse(
        content=out["content"],
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{out["filename"]}"'},
    )


@router.get("/daily-reports/openfrmt")
def openfrmt_export(
    date_from: str = Query(...),
    date_to: str = Query(...),
    org_id: int = Depends(get_current_org_id),
    db: Session = Depends(get_db_session),
):
    """יצוא 'מבנה אחיד' (INI.TXT + BKMVDATA.TXT) כ-ZIP להורדה — לחשבשבת/תוכנות
    הנה"ח אחרות. DRAFT — ראה openfrmt.DISCLAIMER."""
    import io
    import zipfile

    from fastapi import Response
    from ...services import openfrmt

    d_from = _parse_as_of(date_from)
    d_to = _parse_as_of(date_to)
    if not d_from or not d_to:
        raise HTTPException(status_code=400, detail="date_from/date_to נדרשים בפורמט YYYY-MM-DD")

    out = openfrmt.build_openfrmt(db, org_id, d_from, d_to)
    ini_bytes, _ = openfrmt.encode_openfrmt_text(out["ini"])
    bkm_bytes, bkm_encoding = openfrmt.encode_openfrmt_text(out["bkmvdata"])

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("INI.TXT", ini_bytes)
        zf.writestr("BKMVDATA.TXT", bkm_bytes)

    filename = f"OPENFRMT-{org_id}-{d_from.isoformat()}_{d_to.isoformat()}.zip"
    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Openfrmt-Encoding": bkm_encoding,
        },
    )


@router.get("/daily-reports/suppliers")
def suppliers(
    year: int = Query(...),
    month: int = Query(..., ge=1, le=12),
    org_id: int = Depends(get_current_org_id),
    db: Session = Depends(get_db_session),
):
    return daily_reports_service.supplier_breakdown(db, org_id, year, month)


@router.get("/daily-reports/bank-expense-gap")
def bank_expense_gap(
    year: int = Query(...),
    month: int = Query(..., ge=1, le=12),
    org_id: int = Depends(get_current_org_id),
    db: Session = Depends(get_db_session),
):
    """מנוע פער בנק-חשבוניות: לכל תנועת בנק יוצאת בחודש — האם יש כנגדה
    מסמך הנה"ח, וסיכום הפער הכולל (ראה services/bank_expense_gap.py)."""
    from ...services import bank_expense_gap as bank_expense_gap_service
    return bank_expense_gap_service.gap_report(db, org_id, year, month)


@router.get("/daily-reports/suppliers-missing-invoices")
def suppliers_missing_invoices(
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    org_id: int = Depends(get_current_org_id),
    db: Session = Depends(get_db_session),
):
    """ספקים ששולם להם (בבנק/אשראי) אך אין כנגד התשלום מסמך הוצאה/חשבונית —
    אגרגציה ברמת ספק מעל מנוע הפער (services/bank_expense_gap.py). ברירת
    מחדל ללא פרמטרים: 90 הימים האחרונים."""
    from ...services import bank_expense_gap as bank_expense_gap_service

    parsed_from = _parse_as_of(date_from)
    parsed_to = _parse_as_of(date_to)
    today = date.today()
    if parsed_to is None:
        parsed_to = today
    if parsed_from is None:
        parsed_from = parsed_to - timedelta(days=90)
    return bank_expense_gap_service.suppliers_missing_invoices(db, org_id, parsed_from, parsed_to)
