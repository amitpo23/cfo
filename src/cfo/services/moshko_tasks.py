"""Org-scoped task operations used by Moshko's chat tools.

The model supplies human date phrases, but never an organization id. Writes
are invoked only after ``AIChatService.confirm_action`` approves the pending
tool call.
"""
from __future__ import annotations

import calendar
import re
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from ..models import Alert, Task, TaskStatus


ISRAEL_TZ = ZoneInfo("Asia/Jerusalem")
_DAY_ONLY_RE = re.compile(r"^ב[-־–]?(\d{1,2})$")
_SLASH_DATE_RE = re.compile(r"^(\d{1,2})/(\d{1,2})(?:/(\d{4}))?$")


def israel_now() -> datetime:
    return datetime.now(ISRAEL_TZ)


def _next_day_of_month(day: int, today: date) -> date:
    if not 1 <= day <= 31:
        raise ValueError("תאריך יעד לא תקין")
    year, month = today.year, today.month
    for offset in range(13):
        candidate_month = month + offset
        candidate_year = year + (candidate_month - 1) // 12
        candidate_month = (candidate_month - 1) % 12 + 1
        if day > calendar.monthrange(candidate_year, candidate_month)[1]:
            continue
        candidate = date(candidate_year, candidate_month, day)
        if candidate >= today:
            return candidate
    raise ValueError("תאריך יעד לא תקין")


def parse_due_date(value: str | date | None) -> date | None:
    """Parse a small, explicit Hebrew/ISO date vocabulary in Israel time.

    Ambiguous free text is rejected rather than guessed. ``ב-15`` means the
    next calendar occurrence of day 15, including today when applicable.
    """
    if value is None:
        return None
    if isinstance(value, date):
        return value
    normalized = str(value).strip()
    if not normalized:
        return None
    today = israel_now().date()
    if normalized == "היום":
        return today
    if normalized == "מחר":
        return today + timedelta(days=1)

    match = _DAY_ONLY_RE.fullmatch(normalized)
    if match:
        return _next_day_of_month(int(match.group(1)), today)

    try:
        return date.fromisoformat(normalized)
    except ValueError:
        pass

    match = _SLASH_DATE_RE.fullmatch(normalized)
    if match:
        day, month = int(match.group(1)), int(match.group(2))
        if match.group(3):
            try:
                return date(int(match.group(3)), month, day)
            except ValueError as exc:
                raise ValueError("תאריך יעד לא תקין") from exc
        year = today.year
        try:
            candidate = date(year, month, day)
        except ValueError as exc:
            raise ValueError("תאריך יעד לא תקין") from exc
        if candidate < today:
            candidate = date(year + 1, month, day)
        return candidate

    raise ValueError(
        "תאריך יעד לא ברור; יש להשתמש ב'היום', 'מחר', 'ב-15', YYYY-MM-DD או DD/MM/YYYY"
    )


def _status_value(value: TaskStatus | str | None) -> str | None:
    return value.value if isinstance(value, TaskStatus) else value


def task_to_dict(task: Task) -> dict[str, Any]:
    return {
        "id": task.id,
        "title": task.title,
        "description": task.description,
        "status": _status_value(task.status),
        "due_date": task.due_date.isoformat() if task.due_date else None,
        "entity_type": task.entity_type,
        "entity_id": task.entity_id,
        "alert_id": task.alert_id,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "updated_at": task.updated_at.isoformat() if task.updated_at else None,
    }


def create_task(
    db: Session,
    organization_id: int,
    *,
    title: str,
    description: str | None = None,
    due_date: str | date | None = None,
    entity_type: str | None = None,
    entity_id: int | None = None,
    alert_id: int | None = None,
) -> dict[str, Any]:
    normalized_title = (title or "").strip()
    if not normalized_title:
        raise ValueError("כותרת משימה נדרשת")
    if len(normalized_title) > 500:
        raise ValueError("כותרת משימה ארוכה מדי")

    alert = None
    if alert_id is not None:
        alert = db.query(Alert).filter(
            Alert.id == alert_id,
            Alert.organization_id == organization_id,
        ).first()
        if alert is None:
            raise ValueError("ההתראה לא נמצאה בארגון הנוכחי")
        entity_type = entity_type or alert.entity_type
        entity_id = entity_id if entity_id is not None else alert.entity_id

    row = Task(
        organization_id=organization_id,
        title=normalized_title,
        description=(description or "").strip() or None,
        status=TaskStatus.OPEN,
        due_date=parse_due_date(due_date),
        entity_type=(entity_type or "").strip() or None,
        entity_id=entity_id,
        alert_id=alert.id if alert is not None else None,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return task_to_dict(row)


def list_tasks(
    db: Session,
    organization_id: int,
    *,
    status: str | None = None,
    due_from: str | date | None = None,
    due_to: str | date | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    query = db.query(Task).filter(Task.organization_id == organization_id)
    if status:
        try:
            parsed_status = TaskStatus(status)
        except ValueError as exc:
            raise ValueError(f"סטטוס משימה לא תקין: {status}") from exc
        query = query.filter(Task.status == parsed_status)
    if due_from is not None:
        query = query.filter(Task.due_date >= parse_due_date(due_from))
    if due_to is not None:
        query = query.filter(Task.due_date <= parse_due_date(due_to))
    safe_limit = min(max(int(limit), 1), 100)
    rows = query.order_by(Task.due_date.asc(), Task.id.desc()).limit(safe_limit).all()
    return {"tasks": [task_to_dict(row) for row in rows], "count": len(rows)}


def update_task(
    db: Session,
    organization_id: int,
    *,
    task_id: int,
    status: str | None = None,
    due_date: str | date | None = None,
    clear_due_date: bool = False,
) -> dict[str, Any]:
    row = db.query(Task).filter(
        Task.id == task_id,
        Task.organization_id == organization_id,
    ).first()
    if row is None:
        raise ValueError("המשימה לא נמצאה בארגון הנוכחי")
    if status is None and due_date is None and not clear_due_date:
        raise ValueError("יש לציין סטטוס או תאריך יעד לעדכון")
    if status is not None:
        try:
            row.status = TaskStatus(status)
        except ValueError as exc:
            raise ValueError(f"סטטוס משימה לא תקין: {status}") from exc
    if clear_due_date:
        row.due_date = None
    elif due_date is not None:
        row.due_date = parse_due_date(due_date)
    row.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(row)
    return task_to_dict(row)
