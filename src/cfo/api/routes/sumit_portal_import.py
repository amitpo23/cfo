"""Upload a SUMIT portal export. The file is parsed locally. No provider call."""
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from ...database import get_db_session
from ...services.sumit_portal_export import PortalImportError, import_portal_export, summarize_snapshots
from ..dependencies import get_current_org_id, require_admin

router = APIRouter()


@router.get("/sumit-portal-imports")
def list_sumit_portal_imports(
    org_id: int = Depends(get_current_org_id),
    _user=Depends(require_admin),
    db: Session = Depends(get_db_session),
):
    return summarize_snapshots(db, org_id)


@router.post("/sumit-portal-imports")
async def upload_sumit_portal_import(
    file: UploadFile = File(...),
    kind: str | None = Form(None),
    as_of: str | None = Form(None),
    org_id: int = Depends(get_current_org_id),
    user=Depends(require_admin),
    db: Session = Depends(get_db_session),
):
    content = await file.read()
    if len(content) > 5 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="הקובץ גדול מ-5MB")
    try:
        return import_portal_export(
            db, org_id, content,
            filename=file.filename or "",
            kind=kind,
            as_of=as_of,
            actor_id=getattr(user, "id", None),
        )
    except PortalImportError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
