"""The unifying engine (המנוע המאחד) — one command surface over every service.

Aggregates the whole platform for an organization into a single snapshot:
SUMIT books (real), the derived double-entry ledger, synthesis, insights,
aging, and connection health. Each section carries a `state` tag so the
accountant always knows what's grounded in real data vs derived vs unvalidated:

    real        — pulled from SUMIT / our DB of synced documents
    derived     — computed by us from real documents (ledger, reports) — לבדיקת רו"ח
    unvalidated — Open-Finance-dependent, not yet verified on live bank data

`run_pipeline` is READ-ONLY over already-synced data. It does NOT trigger a SUMIT
sync (outward + rate-limited) — syncing stays an explicit, separate action.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from . import ledger_service, daily_reports_service, financial_synthesis, document_anomalies

REAL, DERIVED, UNVALIDATED = "real", "derived", "unvalidated"


def status(db, organization_id: int) -> dict[str, Any]:
    """Connection health + data counts — what the engine has to work with."""
    from ..models import (Invoice, Bill, Expense, BankTransaction, Employee,
                          IntegrationConnection, CfoInsight)

    def _count(model):
        return db.query(model).filter(model.organization_id == organization_id).count()

    from ..config import settings

    connections = db.query(IntegrationConnection).filter(
        IntegrationConnection.organization_id == organization_id).all()
    providers = {c.source: (c.status == "active") for c in connections}

    # Env credentials apply only to the default org (id 1) — mirror the logic in
    # /api/integration/status so the org where SUMIT actually works isn't reported
    # as disconnected just because it has no IntegrationConnection row.
    env_allowed = organization_id == 1
    sumit_ok = providers.get("sumit", False) or (env_allowed and bool(settings.sumit_api_key))
    of_ok = providers.get("open_finance", False) or (env_allowed and all([
        settings.open_finance_client_id,
        settings.open_finance_client_secret,
        settings.open_finance_user_id,
    ]))

    counts = {
        "invoices": _count(Invoice),
        "bills": _count(Bill),
        "expenses": _count(Expense),
        "bank_transactions": _count(BankTransaction),
        "employees": _count(Employee),
        "insights": _count(CfoInsight),
    }
    return {
        "organization_id": organization_id,
        "connections": {
            "sumit": sumit_ok,
            "open_finance": of_ok,
        },
        "counts": counts,
        "bank_data_validated": False,  # flips true once a real consent journey lands
        "ready": counts["invoices"] + counts["bills"] + counts["expenses"] > 0,
    }


def run_pipeline(db, organization_id: int, *, year: int | None = None,
                 month: int | None = None) -> dict[str, Any]:
    """Single command: assemble the unified financial picture from stored data."""
    today = date.today()
    year = year or today.year
    month = month or today.month

    stages: list[dict[str, Any]] = []

    # 1) Derived double-entry ledger + trial-balance invariant.
    tb = ledger_service.trial_balance(db, organization_id)
    stages.append({
        "stage": "ledger", "state": DERIVED,
        "summary": {
            "balanced": tb["balanced"],
            "entry_count": tb["entry_count"],
            "total_debit": tb["total_debit"],
            "total_credit": tb["total_credit"],
        },
        "disclaimer": ledger_service.DISCLAIMER,
    })

    # 2) Cross-source synthesis (books vs bank) — required-actions worklist + VAT.
    try:
        syn = financial_synthesis.synthesize_organization(db, organization_id)
        stages.append({
            "stage": "synthesis", "state": UNVALIDATED,  # leans on bank data
            "summary": {
                "required_actions": syn["action_count"],
                "vat": syn["vat_summary"],
                "reconciliation": syn["reconciliation"],
            },
        })
    except Exception as exc:  # noqa: BLE001
        stages.append({"stage": "synthesis", "state": UNVALIDATED, "error": str(exc)})

    # 3) Aging (AR / AP) — real document balances.
    stages.append({
        "stage": "aging", "state": REAL,
        "summary": {
            "ar": daily_reports_service.ar_aging(db, organization_id, today)["total"],
            "ap": daily_reports_service.ap_aging(db, organization_id, today)["total"],
        },
    })

    # 4) Intra-month cumulative P&L (derived from real documents).
    pl = daily_reports_service.cumulative_pl(db, organization_id, year, month)
    stages.append({
        "stage": "cumulative_pl", "state": DERIVED,
        "summary": {"period": pl["period"], **pl["totals"]},
    })

    # 5) Document anomalies — catch filing mistakes (outliers, missing allocation,
    #    supplier filed as customer) over real documents.
    anomalies = document_anomalies.detect_document_anomalies(db, organization_id)
    stages.append({
        "stage": "anomalies", "state": REAL,
        "summary": {"count": len(anomalies)},
        "findings": anomalies,
    })

    return {
        "organization_id": organization_id,
        "period": f"{year}-{month:02d}",
        "status": status(db, organization_id),
        "stages": stages,
        "legend": {
            REAL: "מבוסס נתוני SUMIT/מסמכים מסונכרנים",
            DERIVED: "מחושב על-ידינו מהמסמכים — לבדיקת רו\"ח",
            UNVALIDATED: "תלוי Open Finance — טרם אומת על נתון בנק חי",
        },
    }
