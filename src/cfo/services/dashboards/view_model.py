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
from . import (
    activity_quality, balance_sheet as balance_sheet_report, books, books_pnl, budget,
    cash_forecast, cash_statement, cashflow_truth, forecast, freshness, liquidity,
)

MAX_RANGE_DAYS = 366


def _plan_version(db, dashboard_id: int) -> str:
    from ...models import DashboardPlan
    row = db.get(DashboardPlan, dashboard_id)
    return row.version if row is not None else ""


def dashboard_revision(db, dashboard) -> dict:
    """A cheap token the open dashboard polls. It changes when the plan or a budget row changes."""
    from sqlalchemy import func
    from ...models import Budget
    latest = db.query(func.max(Budget.updated_at)).filter(
        Budget.organization_id == dashboard.primary_organization_id,
    ).scalar()
    return {
        "plan_version": _plan_version(db, dashboard.id) or None,
        "budget_updated_at": latest.isoformat() if latest is not None else None,
        "provider_calls": 0,
    }


def snapshot_is_current(db, dashboard, snapshot) -> bool:
    """A published snapshot is current only while the plan and budget rows it was built from are unchanged.

    A snapshot from before plan versions were stored stays until the plan or a
    budget row is newer than it.
    """
    if snapshot is None:
        return False
    from sqlalchemy import func
    from ...models import Budget, DashboardPlan
    plan = db.get(DashboardPlan, dashboard.id)
    current = plan.version if plan is not None else ""
    if snapshot.plan_version is not None and snapshot.plan_version != current:
        return False
    if snapshot.plan_version is None and plan is not None and plan.updated_at and snapshot.snapshot_at:
        if plan.updated_at > snapshot.snapshot_at:
            return False
    latest = db.query(func.max(Budget.updated_at)).filter(
        Budget.organization_id == dashboard.primary_organization_id,
    ).scalar()
    if latest is not None and snapshot.snapshot_at is not None and latest > snapshot.snapshot_at:
        return False
    return True


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
    division_pnl = books_pnl.books_pnl(
        db, organization_id, start=start, end=end, plan=plan,
    )
    budget_vs_actual = budget.with_driver_rows(budget.budget_vs_actual(
        db, organization_id, start, end, books_known=pnl["status"] != "unknown",
        pnl_months=pnl.get("months"), reports=reports,
    ), plan)
    position = liquidity.build_liquidity(db, organization_id, start, end, plan=plan, entity_id=entity_id,
                                         classified=filed, today=date.today())
    balance = balance_sheet_report.build_balance_sheet(db, organization_id, end)
    outlook = forecast.build_forecast(
        pnl.get("months") or [], as_of=end, plan=plan, debt_service=position["debt_service"],
        budget_sums=plan_budget_sums(plan) if with_budget else None,
        opening_balance=position["position"]["balance"],
    )
    view = {
        "status": "unknown" if pnl["status"] == "unknown" and not cashflow.get("months") else "ready",
        "cashflow": cashflow,
        "pnl": pnl,
        "books_pnl": division_pnl,
        "budget_vs_actual": budget_vs_actual,
        "card_breakdown": bank_status.card_breakdown(db, organization_id, start, end),
        "liquidity": position,
        "forecast": outlook,
        "sources": freshness.build_freshness(db, organization_id),
        "cash_statement": cash_statement.build_cash_statement(filed, start, end, outlook),
        "balance_sheet": balance,
        "provider_calls": 0,
        "freshness": {
            "cashflow": "books" if cashflow.get("months") else "unknown",
            "pnl": pnl["status"],
            "pnl_basis": pnl.get("basis"),
            "books_pnl": division_pnl.get("basis"),
            "budget_vs_actual": budget_vs_actual["status"],
            "liquidity": position["status"],
            "forecast": outlook["status"],
            "balance_sheet": balance["status"],
            "published": False,
        },
    }
    as_of_today = date.today()
    from .budget_fill import with_history_assumptions
    forecast_plan = with_history_assumptions(db, organization_id, plan, as_of_today)
    view["cash_forecast"] = cashflow_truth.published_forecast(
        view, plan=forecast_plan, organization_id=organization_id, label=None, today=as_of_today,
        apply_budget_rules=with_budget,
    )
    view["cashflow_source"] = cashflow_truth.scaffold(
        as_of=as_of_today, plan=plan, organization_id=organization_id,
        opening=position["position"].get("balance"),
        opening_as_of=position["position"].get("as_of"),
        credit_limit=position["position"].get("limit"),
        documents=_ap_documents(db, organization_id),
        bank_txns=_bank_rows(filed),
        checks=position.get("checks"),
    )
    view["cashflow_source"]["forecast"] = view["cash_forecast"]
    from .liquidity_today import build_liquidity_today
    view["liquidity_today"] = build_liquidity_today(position, view["cash_forecast"], today=as_of_today)
    view["freshness"]["cash_forecast"] = view["cash_forecast"]["status"]
    view["freshness"]["cashflow_source"] = "ready" if view["cashflow_source"]["publishable"] else "unknown"
    return redact_public_view(view)


def _ap_documents(db, organization_id: int) -> list[dict]:
    """Supplier bills already in the database. A matched payment is not still open."""
    from ...models import Bill, BillStatus
    from ..open_payables import confirmed_cover
    cover = confirmed_cover(db, organization_id)
    rows = db.query(Bill).filter(
        Bill.organization_id == organization_id,
        Bill.status.notin_([BillStatus.DRAFT, BillStatus.VOID]),
    ).all()
    documents = []
    for bill in rows:
        gross = float(bill.total or 0)
        if gross <= 0 or bill.issue_date is None:
            continue
        paid = max(float(bill.paid_amount or 0), float(cover.get(bill.id, 0)))
        documents.append({
            "id": bill.id,
            "kind": "AP",
            "supplier_id": bill.vendor_id or bill.bill_number or str(bill.id),
            "supplier_name": bill.bill_number or "",
            "doc_ref": bill.bill_number or str(bill.id),
            "doc_date": bill.issue_date.isoformat(),
            "gross": gross,
            "paid_gross": paid,
        })
    return documents


def _bank_rows(filed) -> list[dict]:
    """Bank rows already read for this view, shaped for the coverage check."""
    from .filing import FALLBACK_RULES, UNRESOLVED, displayed_counterparty
    rows = []
    for txn, filed_row in filed or []:
        category = filed_row.category
        rows.append({
            "id": txn.id,
            "booking_date": txn.date,
            "amount": txn.amount,
            "description": txn.description,
            "counterparty": displayed_counterparty(txn),
            "category": None if category in UNRESOLVED or filed_row.filed_by == "default" and category in FALLBACK_RULES else category,
            "unclassified": category in UNRESOLVED or (filed_row.filed_by == "default" and category in FALLBACK_RULES),
            "is_internal_transfer": category == "intercompany",
            "is_financing": category in {"loans_in", "loans_out", "check_discounting"},
            "is_card_charge": category == "card_bills",
            "status": "BOOKED",
        })
    return rows


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
    if isinstance(view.get("cashflow_source"), dict) and "organization_id" in view["cashflow_source"]:
        view = dict(view)
        source = dict(view["cashflow_source"])
        source.pop("organization_id", None)
        view["cashflow_source"] = source
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
            plan_version=_plan_version(db, dashboard.id),
            view_model=view,
            freshness=view.get("freshness") or {},
            content_sha256=digest,
            provider_calls=0,
        )
        db.add(row)
        db.flush()
    else:
        row.snapshot_at = datetime.utcnow()
        row.plan_version = _plan_version(db, dashboard.id)
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
