"""
Tasks, Alerts, Notes, and Reports API routes.
"""
import csv
import io
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ...database import get_db_session
from ...models import (
    Alert,
    AlertStatus,
    AlertUpdate,
    Budget,
    BudgetCreate,
    Note,
    NoteCreate,
    Task,
    TaskCreate,
    TaskStatus,
    TaskUpdate as TaskUpdateSchema,
)
from ...services.alert_engine import AlertEngine
from ...services.dashboard_service import DashboardService

router = APIRouter()

DEFAULT_ORG_ID = 1


# ===== Tasks =====

@router.post("/tasks")
async def create_task(
    payload: TaskCreate,
    org_id: int = Query(DEFAULT_ORG_ID),
    db: Session = Depends(get_db_session),
):
    task = Task(
        organization_id=org_id,
        title=payload.title,
        description=payload.description,
        due_date=payload.due_date,
        entity_type=payload.entity_type,
        entity_id=payload.entity_id,
        alert_id=payload.alert_id,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return {
        "id": task.id,
        "title": task.title,
        "status": task.status.value,
        "created_at": task.created_at.isoformat(),
    }


@router.get("/tasks")
async def list_tasks(
    status: Optional[str] = None,
    org_id: int = Query(DEFAULT_ORG_ID),
    db: Session = Depends(get_db_session),
):
    query = db.query(Task).filter(Task.organization_id == org_id)
    if status:
        try:
            query = query.filter(Task.status == TaskStatus(status))
        except ValueError:
            pass
    tasks = query.order_by(Task.created_at.desc()).limit(100).all()
    return [
        {
            "id": t.id,
            "title": t.title,
            "description": t.description,
            "status": t.status.value if t.status else None,
            "due_date": t.due_date.isoformat() if t.due_date else None,
            "entity_type": t.entity_type,
            "entity_id": t.entity_id,
            "created_at": t.created_at.isoformat() if t.created_at else None,
        }
        for t in tasks
    ]


@router.patch("/tasks/{task_id}")
async def update_task(
    task_id: int,
    payload: TaskUpdateSchema,
    db: Session = Depends(get_db_session),
):
    task = db.query(Task).get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if payload.title is not None:
        task.title = payload.title
    if payload.description is not None:
        task.description = payload.description
    if payload.status is not None:
        task.status = payload.status
    if payload.due_date is not None:
        task.due_date = payload.due_date
    task.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(task)
    return {
        "id": task.id,
        "title": task.title,
        "status": task.status.value,
    }


# ===== Alerts =====

@router.get("/alerts")
async def list_alerts(
    status: Optional[str] = None,
    org_id: int = Query(DEFAULT_ORG_ID),
    db: Session = Depends(get_db_session),
):
    query = db.query(Alert).filter(Alert.organization_id == org_id)
    if status:
        try:
            query = query.filter(Alert.status == AlertStatus(status))
        except ValueError:
            pass
    alerts = query.order_by(Alert.created_at.desc()).limit(100).all()
    return [
        {
            "id": a.id,
            "alert_type": a.alert_type,
            "severity": a.severity.value if a.severity else None,
            "entity_type": a.entity_type,
            "entity_id": a.entity_id,
            "title": a.title,
            "message": a.message,
            "status": a.status.value if a.status else None,
            "created_at": a.created_at.isoformat() if a.created_at else None,
        }
        for a in alerts
    ]


@router.patch("/alerts/{alert_id}")
async def update_alert(
    alert_id: int,
    payload: AlertUpdate,
    db: Session = Depends(get_db_session),
):
    alert = db.query(Alert).get(alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")

    if payload.status is not None:
        alert.status = payload.status
        if payload.status == AlertStatus.ACKNOWLEDGED:
            alert.acknowledged_at = datetime.utcnow()
        elif payload.status == AlertStatus.RESOLVED:
            alert.resolved_at = datetime.utcnow()

    db.commit()
    return {"id": alert.id, "status": alert.status.value}


@router.post("/alerts/evaluate")
async def evaluate_alerts(
    org_id: int = Query(DEFAULT_ORG_ID),
    db: Session = Depends(get_db_session),
):
    """Manually trigger alert evaluation."""
    engine = AlertEngine(db, org_id)
    new_alerts = engine.evaluate_all()
    return {"new_alerts": len(new_alerts)}


# ===== Notes =====

@router.post("/notes")
async def create_note(
    payload: NoteCreate,
    org_id: int = Query(DEFAULT_ORG_ID),
    db: Session = Depends(get_db_session),
):
    note = Note(
        organization_id=org_id,
        entity_type=payload.entity_type,
        entity_id=payload.entity_id,
        text=payload.text,
    )
    db.add(note)
    db.commit()
    db.refresh(note)
    return {
        "id": note.id,
        "entity_type": note.entity_type,
        "entity_id": note.entity_id,
        "text": note.text,
        "created_at": note.created_at.isoformat(),
    }


@router.get("/notes")
async def list_notes(
    entity_type: str = Query(...),
    entity_id: int = Query(...),
    org_id: int = Query(DEFAULT_ORG_ID),
    db: Session = Depends(get_db_session),
):
    notes = db.query(Note).filter(
        Note.organization_id == org_id,
        Note.entity_type == entity_type,
        Note.entity_id == entity_id,
    ).order_by(Note.created_at.desc()).all()

    return [
        {
            "id": n.id,
            "text": n.text,
            "created_at": n.created_at.isoformat(),
        }
        for n in notes
    ]


# ===== Budgets =====

@router.post("/budgets")
async def create_budget(
    payload: BudgetCreate,
    org_id: int = Query(DEFAULT_ORG_ID),
    db: Session = Depends(get_db_session),
):
    budget = Budget(
        organization_id=org_id,
        category_name=payload.category_name,
        category_id=payload.category_id,
        year=payload.year,
        month=payload.month,
        budgeted_amount=payload.budgeted_amount,
    )
    db.add(budget)
    db.commit()
    db.refresh(budget)
    return {
        "id": budget.id,
        "category_name": budget.category_name,
        "year": budget.year,
        "month": budget.month,
        "budgeted_amount": float(budget.budgeted_amount),
    }


@router.get("/budgets")
async def list_budgets(
    year: Optional[int] = None,
    month: Optional[int] = None,
    org_id: int = Query(DEFAULT_ORG_ID),
    db: Session = Depends(get_db_session),
):
    query = db.query(Budget).filter(Budget.organization_id == org_id)
    if year:
        query = query.filter(Budget.year == year)
    if month:
        query = query.filter(Budget.month == month)
    budgets = query.order_by(Budget.year.desc(), Budget.month.desc()).all()
    return [
        {
            "id": b.id,
            "category_name": b.category_name,
            "year": b.year,
            "month": b.month,
            "budgeted_amount": float(b.budgeted_amount or 0),
            "actual_amount": float(b.actual_amount or 0),
        }
        for b in budgets
    ]


# ===== Reports / Exports =====

@router.get("/reports/{report_type}")
async def export_report(
    report_type: str,
    format: str = Query("csv"),
    org_id: int = Query(DEFAULT_ORG_ID),
    db: Session = Depends(get_db_session),
):
    """
    Export report as CSV.
    report_type: pnl | cashflow | ar_aging | ap_due
    """
    svc = DashboardService(db, org_id)

    if report_type == "pnl":
        data = svc.get_pnl(months=12)
        headers = ["month", "revenue", "cogs", "gross_profit", "opex", "net_profit"]
    elif report_type == "cashflow":
        data = svc.get_cashflow_projection(weeks=12)
        headers = ["week", "expected_inflows", "expected_outflows", "net_flow", "cumulative_balance"]
    elif report_type == "ar_aging":
        aging = svc.get_ar_aging()
        data = aging.get("invoices", [])
        headers = ["id", "invoice_number", "customer", "amount", "balance", "due_date", "days_overdue", "status"]
    elif report_type == "ap_due":
        data = svc.get_ap_bills(days_ahead=90)
        headers = ["id", "bill_number", "vendor", "amount", "balance", "due_date", "days_until_due", "status"]
    else:
        raise HTTPException(status_code=400, detail=f"Unknown report type: {report_type}")

    # Generate CSV
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=headers, extrasaction="ignore")
    writer.writeheader()
    for row in data:
        writer.writerow(row)

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={report_type}_{date.today()}.csv"},
    )
