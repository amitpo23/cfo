"""Codified onboarding data-mapping pipeline.

When a business connects an integration (enters its SUMIT / Open Finance credentials),
we run a FIXED checklist of ingestion steps to map ALL of its data and reconcile it
against the source — re-running incomplete/failed steps until the whole checklist
completes. This codifies, once and for every future business, the manual onboarding
done for the first live osek (where the document sync had silently dropped expenses and
older history). Each step is persisted as an OnboardingTask row so progress survives
restarts and the same checklist runs identically for every tenant.

The reconcile step is the "until full completion" guarantee: onboarding is not done
until the document counts in our DB match the counts reported live by the source.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Optional

logger = logging.getLogger(__name__)

# The fixed, ordered checklist. Add a step here + a handler in _HANDLERS to extend it
# for every business; existing onboardings pick the new step up on their next run.
ONBOARDING_STEPS: list[dict[str, str]] = [
    {"step": "test_connection", "label": "בדיקת חיבור למקור"},
    {"step": "sync_documents", "label": "סנכרון מסמכים: לקוחות, חשבוניות, הוצאות, קבלות"},
    {"step": "reconcile", "label": "אימות: ספירת מסמכים ב-DB מול המקור"},
    {"step": "financial_snapshot", "label": "חישוב תמונת רווח-והפסד / מע\"מ"},
]

# Income = SUMIT DocumentType 0 (Invoice), Expense = 15 (ExpenseInvoice). See
# memory sumit-document-type-codes.
_SUMIT_INCOME_TYPE = "0"
_SUMIT_EXPENSE_TYPE = "15"


def ensure_tasks(db, organization_id: int, source: str = "sumit") -> None:
    """Materialize one OnboardingTask row per checklist step (idempotent)."""
    from ..models import OnboardingTask

    existing = {
        t.step
        for t in db.query(OnboardingTask).filter(
            OnboardingTask.organization_id == organization_id,
            OnboardingTask.source == source,
        ).all()
    }
    for seq, spec in enumerate(ONBOARDING_STEPS):
        if spec["step"] in existing:
            continue
        db.add(OnboardingTask(
            organization_id=organization_id, source=source,
            step=spec["step"], seq=seq, status="pending",
        ))
    db.commit()


def status(db, organization_id: int, source: str = "sumit") -> dict[str, Any]:
    """Return the checklist with per-step status, plus an overall flag."""
    from ..models import OnboardingTask

    ensure_tasks(db, organization_id, source)
    rows = db.query(OnboardingTask).filter(
        OnboardingTask.organization_id == organization_id,
        OnboardingTask.source == source,
    ).order_by(OnboardingTask.seq).all()
    labels = {s["step"]: s["label"] for s in ONBOARDING_STEPS}
    steps = [{
        "step": r.step,
        "label": labels.get(r.step, r.step),
        "status": r.status,
        "result": r.result or {},
        "error": r.error,
        "attempts": r.attempts,
        "completed_at": r.completed_at.isoformat() if r.completed_at else None,
    } for r in rows]
    complete = bool(rows) and all(r.status == "completed" for r in rows)
    return {
        "organization_id": organization_id,
        "source": source,
        "complete": complete,
        "steps": steps,
    }


async def run_onboarding_bg(organization_id: int, source: str = "sumit") -> None:
    """Background entrypoint: opens its own DB session (the request's is already closed).

    Used to auto-map a business's data the moment it connects an integration. Errors
    are swallowed (logged) — the OnboardingTask rows carry the per-step status for the UI.
    """
    from ..database import SessionLocal

    db = SessionLocal()
    try:
        await run_onboarding(db, organization_id, source)
    except Exception:  # noqa: BLE001
        logger.exception("background onboarding failed for org %s", organization_id)
    finally:
        db.close()


async def run_onboarding(db, organization_id: int, source: str = "sumit",
                         force: bool = False) -> dict[str, Any]:
    """Run the checklist in order; stop at the first step that fails.

    Resumable: completed steps are skipped (unless force=True). The same call can be
    re-invoked to continue after a transient failure or to re-reconcile.
    """
    from ..models import OnboardingTask
    from .sync_engine import get_connector_for_org

    ensure_tasks(db, organization_id, source)

    connector = None
    try:
        connector, conn_id, resolved = get_connector_for_org(db, organization_id, source)
    except Exception as exc:
        # Can't even resolve credentials — surface on the first step.
        first = db.query(OnboardingTask).filter(
            OnboardingTask.organization_id == organization_id,
            OnboardingTask.source == source,
        ).order_by(OnboardingTask.seq).first()
        if first:
            first.status = "failed"
            first.error = f"connection unavailable: {exc}"
            db.commit()
        return status(db, organization_id, source)

    rows = db.query(OnboardingTask).filter(
        OnboardingTask.organization_id == organization_id,
        OnboardingTask.source == source,
    ).order_by(OnboardingTask.seq).all()

    ctx = {"connector": connector, "conn_id": conn_id, "source": resolved}
    for row in rows:
        if row.status == "completed" and not force:
            continue
        handler = _HANDLERS.get(row.step)
        if handler is None:
            row.status = "skipped"
            db.commit()
            continue
        row.status = "running"
        row.started_at = datetime.now(timezone.utc)
        row.attempts = (row.attempts or 0) + 1
        db.commit()
        try:
            result = await handler(db, organization_id, ctx)
            ok = bool(result.get("ok", True))
            row.result = {k: v for k, v in result.items() if k != "ok"}
            row.status = "completed" if ok else "failed"
            row.error = None if ok else result.get("message", "step did not reconcile")
            row.completed_at = datetime.now(timezone.utc) if ok else None
            db.commit()
            if not ok:
                break  # do not proceed past an unreconciled step
        except Exception as exc:  # noqa: BLE001 — record and stop
            logger.exception("onboarding step %s failed", row.step)
            row.status = "failed"
            row.error = str(exc)[:500]
            db.commit()
            break

    return status(db, organization_id, source)


# --------------------------------------------------------------------------- #
# Step handlers — each returns a dict; {"ok": False, "message": ...} marks the
# step (and the run) as not-yet-complete without raising.
# --------------------------------------------------------------------------- #
async def _h_test_connection(db, org_id: int, ctx: dict) -> dict:
    ok = await ctx["connector"].test_connection()
    return {"ok": bool(ok), "message": None if ok else "source connection test failed"}


async def _h_sync_documents(db, org_id: int, ctx: dict) -> dict:
    from .sync_engine import SyncEngine

    engine = SyncEngine(db, ctx["connector"], org_id, ctx["source"], ctx["conn_id"])
    run = await engine.run_full_sync()
    return {
        "ok": True,
        "status": run.status.value if run.status else None,
        "counts": run.counts or {},
    }


async def _sumit_count(connector, type_code: str) -> int:
    """Authoritative live count of one SUMIT document type (paginated)."""
    client = await connector._get_client()
    async with client:
        docs = await connector._list_documents_all(client, type_code, None)
    return len(docs)


async def _h_reconcile(db, org_id: int, ctx: dict) -> dict:
    """Compare DB document counts to the live source counts; complete only on match."""
    from ..models import Invoice, Bill

    if ctx["source"] != "sumit":
        return {"ok": True, "note": "reconcile implemented for sumit only"}

    connector = ctx["connector"]
    src_income = await _sumit_count(connector, _SUMIT_INCOME_TYPE)
    src_expense = await _sumit_count(connector, _SUMIT_EXPENSE_TYPE)
    db_income = db.query(Invoice).filter(
        Invoice.organization_id == org_id, Invoice.source == "sumit").count()
    db_expense = db.query(Bill).filter(
        Bill.organization_id == org_id, Bill.source == "sumit").count()

    income_ok = db_income >= src_income
    expense_ok = db_expense >= src_expense
    ok = income_ok and expense_ok
    return {
        "ok": ok,
        "message": None if ok else (
            f"incomplete: income {db_income}/{src_income}, expense {db_expense}/{src_expense}"
        ),
        "income": {"db": db_income, "source": src_income},
        "expense": {"db": db_expense, "source": src_expense},
    }


def _net(total, vat) -> float:
    return float((total or 0)) - float((vat or 0))


async def _h_financial_snapshot(db, org_id: int, ctx: dict) -> dict:
    """Cache a current-year P&L / VAT snapshot derived from the synced documents."""
    from sqlalchemy import func
    from ..models import Invoice, Bill

    year = date.today().year
    y0, y1 = date(year, 1, 1), date(year, 12, 31)

    inv = db.query(
        func.count(Invoice.id), func.coalesce(func.sum(Invoice.subtotal), 0),
        func.coalesce(func.sum(Invoice.tax), 0),
    ).filter(
        Invoice.organization_id == org_id,
        Invoice.issue_date >= y0, Invoice.issue_date <= y1,
    ).first()
    bil = db.query(
        func.count(Bill.id), func.coalesce(func.sum(Bill.subtotal), 0),
        func.coalesce(func.sum(Bill.tax), 0),
    ).filter(
        Bill.organization_id == org_id,
        Bill.issue_date >= y0, Bill.issue_date <= y1,
    ).first()

    revenue = round(float(inv[1] or 0), 2)
    expenses = round(abs(float(bil[1] or 0)), 2)
    output_vat = round(float(inv[2] or 0), 2)
    input_vat = round(abs(float(bil[2] or 0)), 2)
    return {
        "ok": True,
        "year": year,
        "revenue_net": revenue,
        "expenses_net": expenses,
        "profit_net": round(revenue - expenses, 2),
        "vat_to_pay": round(output_vat - input_vat, 2),
        "invoice_count": int(inv[0] or 0),
        "bill_count": int(bil[0] or 0),
        "derived": True,
        "disclaimer": "נגזר מהמסמכים — לא הספרים הרשמיים. לבדיקת רו\"ח.",
    }


_HANDLERS = {
    "test_connection": _h_test_connection,
    "sync_documents": _h_sync_documents,
    "reconcile": _h_reconcile,
    "financial_snapshot": _h_financial_snapshot,
}
