"""Live cash-flow and profit-and-loss for one organization.

Both inputs are Books already in the database. This module does not construct
a SUMIT or Open Finance client. Missing books are unknown, not zero.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime

from ...models import PipelineRun
from ..bank_coverage import redact_public_coverage
from ..financial_reports_service import FinancialReportsService
from ..live_cash_flow_service import LiveCashFlowService
from .. import bank_status
from . import activity_quality, books, budget, cash_forecast, cash_statement, forecast, freshness, liquidity

MAX_RANGE_DAYS = 366


def plan_payload(db, dashboard_id: int | None) -> dict | None:
    """The dashboard's management plan (decisions, filing rules, closed months)."""
    if dashboard_id is None:
        return None
    from ...models import DashboardPlan
    row = db.get(DashboardPlan, dashboard_id)
    return row.payload if row is not None and isinstance(row.payload, dict) else None


def plan_budget_sums(plan: dict | None) -> dict | None:
    """Monthly budget per kind from the plan's lines; None when the plan has none or is invalid."""
    from .plan_budget import PlanBudgetError, monthly_line_sums, validate_budget_lines
    try:
        lines = validate_budget_lines(plan or {})
    except PlanBudgetError:
        return None
    return monthly_line_sums(lines) if lines else None


def build_view(db, organization_id: int, start: date, end: date, *, plan: dict | None = None,
               entity_id: int | None = None, with_budget: bool = True) -> dict:
    if end < start:
        raise ValueError("end date is before the start date")
    if (end - start).days > MAX_RANGE_DAYS:
        raise ValueError("date range is longer than 366 days")
    months = (end.year - start.year) * 12 + (end.month - start.month) + 1
    cashflow = LiveCashFlowService(db, organization_id).monthly_cash_flow(
        months=max(months, 1), as_of_date=end,
    )
    cashflow = dict(cashflow)
    cashflow["basis"] = "booked_only"
    cashflow["pending"] = bank_status.pending_summary(db, organization_id, start, end)
    cashflow = activity_quality.adjust_cashflow(db, organization_id, cashflow, plan)
    # One read of the organization's documents and one filing of its bank rows,
    # shared by the P&L, budget vs actual and liquidity of this view.
    reports = FinancialReportsService(db, memoize=True)
    filed = books.classified_bank(db, organization_id, start, end, plan)
    pnl = _profit_and_loss(db, organization_id, start, end, plan=plan, filed=filed, reports=reports)
    budget_vs_actual = budget.budget_vs_actual(
        db, organization_id, start, end, books_known=pnl["status"] != "unknown",
        pnl_months=pnl.get("months"), reports=reports,
    )
    position = liquidity.build_liquidity(db, organization_id, start, end, plan=plan, entity_id=entity_id,
                                         classified=filed)
    outlook = forecast.build_forecast(
        pnl.get("months") or [], as_of=end, plan=plan, debt_service=position["debt_service"],
        budget_sums=plan_budget_sums(plan) if with_budget else None,
        opening_balance=position["position"]["balance"],
    )
    view = {
        "status": "unknown" if pnl["status"] == "unknown" and not cashflow.get("months") else "ready",
        "cashflow": cashflow,
        "pnl": pnl,
        "budget_vs_actual": budget_vs_actual,
        "card_breakdown": bank_status.card_breakdown(db, organization_id, start, end),
        "liquidity": position,
        "forecast": outlook,
        "sources": freshness.build_freshness(db, organization_id),
        "cash_statement": cash_statement.build_cash_statement(filed, start, end, outlook),
        "provider_calls": 0,
        "freshness": {
            "cashflow": "books" if cashflow.get("months") else "unknown",
            "pnl": pnl["status"],
            "pnl_basis": pnl.get("basis"),
            "budget_vs_actual": budget_vs_actual["status"],
            "liquidity": position["status"],
            "forecast": outlook["status"],
            "published": False,
        },
    }
    view["cash_forecast"] = cash_forecast.build_entity_forecast(
        view, plan=plan, organization_id=organization_id, label=None, today=end,
    )
    view["freshness"]["cash_forecast"] = view["cash_forecast"]["status"]
    return redact_public_view(view)


def redact_public_view(view: dict) -> dict:
    """Remove internal ids and staff identity from a dashboard view before it is shown on /d/."""
    if not isinstance(view, dict):
        return view
    if "entities" in view or "combined" in view or "office_organization_id" in view:
        view = _redact_entities(view)
    if "budget_vs_actual" in view:
        view = dict(view)
        view["budget_vs_actual"] = budget.redact_public(view["budget_vs_actual"])
    if "liquidity" in view:
        view = dict(view)
        view["liquidity"] = liquidity.redact_public(view["liquidity"])
    if "sources" in view:
        view = dict(view)
        view["sources"] = freshness.redact_public(view["sources"])
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


def _redact_entities(view: dict) -> dict:
    """Multi-entity views: no organization or account ids on /d/, each section redacted."""
    copied = {key: value for key, value in view.items() if key != "office_organization_id"}
    if isinstance(view.get("entities"), list):
        copied["entities"] = [
            {
                "label": section.get("label"),
                "role": section.get("role"),
                "accounts": [
                    {"display_label": account.get("display_label")}
                    for account in section.get("accounts") or [] if isinstance(account, dict)
                ],
                "view": redact_public_view(section.get("view")),
            }
            for section in view["entities"] if isinstance(section, dict)
        ]
    if isinstance(view.get("combined"), dict):
        combined = dict(view["combined"])
        if "budget_vs_actual" in combined:
            combined["budget_vs_actual"] = budget.redact_public(combined["budget_vs_actual"])
        if "sources" in combined:
            combined["sources"] = freshness.redact_public(combined["sources"])
        copied["combined"] = combined
    return copied


def publish_view(db, dashboard, view: dict, *, day: date | None = None) -> dict:
    """Store one snapshot per dashboard per day.

    A second publish on that day keeps the same row and replaces the view.
    """
    day = day or date.today()
    books.assert_publishable((view or {}).get("pnl"))
    for section in (view or {}).get("entities") or []:
        if isinstance(section, dict):
            books.assert_publishable((section.get("view") or {}).get("pnl"))
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


def _profit_and_loss(db, organization_id: int, start: date, end: date, *, plan: dict | None = None,
                     filed=None, reports: FinancialReportsService | None = None) -> dict:
    """P&L of the window, one source per month (see ``books``)."""
    reports = reports or FinancialReportsService(db, memoize=True)
    monthly = books.monthly_pnl(db, organization_id, start, end, plan=plan, filed=filed, reports=reports)
    basis = monthly["basis"]
    if basis == "unknown":
        return {
            "status": "unknown",
            "basis": basis,
            "months": monthly["months"],
            "total_revenue": None,
            "total_expenses": None,
            "net_income_before_tax": None,
            "tax_expense": None,
            "message": "אין מסמכי הכנסה או הוצאה ואין תנועות בנק בתקופה — הרווח וההפסד לא ידוע.",
        }
    if basis == books.LEDGER:
        report = reports.generate_profit_loss(
            organization_id, start, end, compare_previous=False,
        )
        total_revenue = report.total_revenue
        total_expenses = report.total_expenses
        net = report.net_income_before_tax
        message = "מס לא חושב. הערכה של 23% אינה מוצגת כמספר."
    else:
        total_revenue = monthly["total_revenue"]
        total_expenses = monthly["total_expenses"]
        net = monthly["net"]
        cash_months = [m["month"] for m in monthly["months"] if m["source"] == books.CASH_BASIS]
        message = (
            "בסיס מזומן: " + ", ".join(cash_months)
            + " חושבו מתנועות בנק מסווגות (BOOKED בלבד, ללא מע״מ), כי הספרים בחודשים אלה חלקיים או חסרים."
            " כל חודש מחושב ממקור אחד בלבד. מס לא חושב."
        )
    return {
        "status": "ready",
        "basis": basis,
        "months": monthly["months"],
        "total_revenue": total_revenue,
        "total_expenses": total_expenses,
        "net_income_before_tax": net,
        "tax_expense": None,
        "message": message,
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
