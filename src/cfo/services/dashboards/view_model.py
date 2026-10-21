"""Live cash-flow and profit-and-loss for one organization.

Both inputs are Books already in the database. This module does not construct
a SUMIT or Open Finance client. Missing books are unknown, not zero.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime

from ...models import Bill, Expense, Invoice, PipelineRun
from ..bank_coverage import redact_public_coverage
from ..financial_reports_service import FinancialReportsService
from ..live_cash_flow_service import LiveCashFlowService
from . import budget

MAX_RANGE_DAYS = 366


def build_view(db, organization_id: int, start: date, end: date) -> dict:
    if end < start:
        raise ValueError("end date is before the start date")
    if (end - start).days > MAX_RANGE_DAYS:
        raise ValueError("date range is longer than 366 days")
    months = (end.year - start.year) * 12 + (end.month - start.month) + 1
    cashflow = LiveCashFlowService(db, organization_id).monthly_cash_flow(
        months=max(months, 1), as_of_date=end,
    )
    pnl = _profit_and_loss(db, organization_id, start, end)
    budget_vs_actual = budget.budget_vs_actual(
        db, organization_id, start, end, books_known=pnl["status"] != "unknown",
    )
    view = {
        "status": "unknown" if pnl["status"] == "unknown" and not cashflow.get("months") else "ready",
        "cashflow": cashflow,
        "pnl": pnl,
        "budget_vs_actual": budget_vs_actual,
        "provider_calls": 0,
        "freshness": {
            "cashflow": "books" if cashflow.get("months") else "unknown",
            "pnl": pnl["status"],
            "budget_vs_actual": budget_vs_actual["status"],
            "published": False,
        },
    }
    return redact_public_view(view)


def redact_public_view(view: dict) -> dict:
    """Remove internal ids and staff identity from a dashboard view before it is shown on /d/."""
    if not isinstance(view, dict):
        return view
    if "budget_vs_actual" in view:
        view = dict(view)
        view["budget_vs_actual"] = budget.redact_public(view["budget_vs_actual"])
    cashflow = view.get("cashflow")
    if not isinstance(cashflow, dict) or "coverage" not in cashflow:
        return view
    copied = dict(view)
    cash = dict(cashflow)
    original = cash.get("coverage")
    cash["coverage"] = redact_public_coverage(original)
    if (
        isinstance(original, dict) and isinstance(cash["coverage"], dict)
        and original.get("message") and cash.get("message") == original.get("message")
    ):
        cash["message"] = cash["coverage"].get("message")
    copied["cashflow"] = cash
    return copied


def publish_view(db, dashboard, view: dict, *, day: date | None = None) -> dict:
    """Store one snapshot per dashboard per day.

    A second publish on that day keeps the same row and replaces the view.
    """
    day = day or date.today()
    encoded = json.dumps(view, sort_keys=True, ensure_ascii=False, default=str)
    digest = hashlib.sha256(encoded.encode()).hexdigest()
    from ...models import PublishedSnapshot
    row = (
        db.query(PublishedSnapshot)
        .filter_by(dashboard_id=dashboard.id, refreshed_day=day)
        .first()
    )
    if row is None:
        row = PublishedSnapshot(
            dashboard_id=dashboard.id,
            refreshed_day=day,
            snapshot_at=datetime.utcnow(),
            plan_version=None,
            view_model=view,
            freshness=view.get("freshness") or {},
            content_sha256=digest,
            provider_calls=0,
        )
        db.add(row)
        db.flush()
    else:
        row.snapshot_at = datetime.utcnow()
        row.view_model = view
        row.freshness = view.get("freshness") or {}
        row.content_sha256 = digest
        row.provider_calls = 0
    dashboard.current_snapshot_id = row.id
    _pipeline(db, dashboard.primary_organization_id, day)
    db.commit()
    db.refresh(row)
    return {
        "id": row.id,
        "refreshed_day": row.refreshed_day.isoformat(),
        "content_sha256": row.content_sha256,
        "provider_calls": row.provider_calls,
    }


def _profit_and_loss(db, organization_id: int, start: date, end: date) -> dict:
    has_books = any((
        db.query(Invoice.id).filter(
            Invoice.organization_id == organization_id,
            Invoice.issue_date >= start,
            Invoice.issue_date <= end,
        ).first(),
        db.query(Bill.id).filter(
            Bill.organization_id == organization_id,
            Bill.issue_date >= start,
            Bill.issue_date <= end,
        ).first(),
        db.query(Expense.id).filter(
            Expense.organization_id == organization_id,
            Expense.expense_date >= start,
            Expense.expense_date <= end,
        ).first(),
    ))
    if not has_books:
        return {
            "status": "unknown",
            "total_revenue": None,
            "total_expenses": None,
            "net_income_before_tax": None,
            "tax_expense": None,
            "message": "אין מסמכי הכנסה או הוצאה בתקופה — הרווח וההפסד לא ידוע.",
        }
    report = FinancialReportsService(db).generate_profit_loss(
        organization_id, start, end, compare_previous=False,
    )
    return {
        "status": "ready",
        "total_revenue": report.total_revenue,
        "total_expenses": report.total_expenses,
        "net_income_before_tax": report.net_income_before_tax,
        "tax_expense": None,
        "message": "מס לא חושב. הערכה של 23% אינה מוצגת כמספר.",
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
    }


def _pipeline(db, organization_id: int, day: date) -> None:
    row = (
        db.query(PipelineRun)
        .filter_by(organization_id=organization_id, run_day=day, step="snapshot")
        .first()
    )
    if row is None:
        db.add(PipelineRun(
            organization_id=organization_id,
            run_day=day,
            step="snapshot",
            status="succeeded",
            started_at=datetime.utcnow(),
            finished_at=datetime.utcnow(),
            counts={"provider_calls": 0},
        ))
    else:
        row.status = "succeeded"
        row.finished_at = datetime.utcnow()
        row.counts = {"provider_calls": 0}
