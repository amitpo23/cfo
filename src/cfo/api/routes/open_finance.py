"""
Open Finance API routes — full surface of the Financy / Open Finance integration
plus the Bank Intelligence layer (insights) and bank reconciliation.

Mounted at /api/open-finance. Every route is organization-scoped. HTTP wrappers are
thin pass-throughs over `OpenFinanceClient`; the value-add endpoints are
`/insights/*` and `/reconcile/*`.
"""
from __future__ import annotations

import logging
import secrets
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ...database import get_db_session
from ..dependencies import get_current_org_id
from ...config import settings
from ...models import (
    BankConnection, BankTransaction, CfoInsight, IntegrationConnection,
    OpenFinancePayment,
)
from ...services.open_finance_client import OpenFinanceClient, OpenFinanceError
from ...services.credentials_vault import decrypt_credentials
from ...services import bank_insights, bank_reconciliation, reconciliation_dispatch

logger = logging.getLogger(__name__)
router = APIRouter()

# Insight types produced by the bank-intelligence engine (for listing).
BANK_INSIGHT_TYPES = {
    "duplicate_charge", "subscription", "installment_ending", "bank_fees",
    "category_spike", "cashflow_forecast", "savings_opportunity", "anomaly",
    "risk_signal", "aggregate_balance", "portfolio_summary", "portfolio_position",
}


# ---------------------------------------------------------------------- #
# client resolution
# ---------------------------------------------------------------------- #
def get_open_finance_client(db: Session, org_id: int) -> OpenFinanceClient:
    """Build an OpenFinanceClient from org-scoped credentials (or env for org 1)."""
    from ...models import IntegrationConnection

    conn = (
        db.query(IntegrationConnection)
        .filter(
            IntegrationConnection.organization_id == org_id,
            IntegrationConnection.source == "open_finance",
            IntegrationConnection.status == "active",
        )
        .first()
    )
    creds: dict[str, Any] = {}
    if conn and conn.credentials_encrypted:
        creds = decrypt_credentials(conn.credentials_encrypted) or {}

    env_allowed = org_id == 1
    client_id = creds.get("client_id") or (settings.open_finance_client_id if env_allowed else None)
    client_secret = creds.get("client_secret") or (settings.open_finance_client_secret if env_allowed else None)
    user_id = creds.get("user_id") or (settings.open_finance_user_id if env_allowed else None)

    missing = [n for n, v in {
        "OPEN_FINANCE_CLIENT_ID": client_id,
        "OPEN_FINANCE_CLIENT_SECRET": client_secret,
        "OPEN_FINANCE_USER_ID": user_id,
    }.items() if not v]
    if missing:
        raise HTTPException(400, f"Open Finance not configured: {', '.join(missing)}")

    v2_base = (creds.get("api_base_url") or settings.open_finance_api_base_url).rstrip("/")
    v3_loans_base = v2_base[:-3] + "/v3/loans" if v2_base.endswith("/v2") else None
    return OpenFinanceClient(
        client_id, client_secret, user_id,
        oauth_url=creds.get("oauth_url") or settings.open_finance_oauth_url,
        v2_base=v2_base, v3_loans_base=v3_loans_base,
    )


async def _call(coro):
    """Await an OpenFinanceClient coroutine, translating API errors to HTTP."""
    try:
        return await coro
    except OpenFinanceError as exc:
        raise HTTPException(status_code=exc.status_code or 502, detail=exc.message)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("Open Finance call failed")
        raise HTTPException(502, f"Open Finance error: {exc}")


async def _run(db, org_id, fn):
    """Build a client, run fn(client), translate errors, always close. Keeps the
    many thin pass-through routes a single line each."""
    client = get_open_finance_client(db, org_id)
    try:
        return await _call(fn(client))
    finally:
        await client.close()


# ====================================================================== #
# CONNECTIONS — consent journey
# ====================================================================== #
class CreateConnectionRequest(BaseModel):
    provider_ids: Optional[list[str]] = None
    redirect_url: Optional[str] = None
    language: str = "he"
    include_fake_providers: bool = False
    iframe: bool = False
    psu_id: Optional[str] = None


@router.post("/connections")
async def create_connection(
    body: CreateConnectionRequest,
    org_id: int = Depends(get_current_org_id),
    db: Session = Depends(get_db_session),
):
    """Start a bank consent journey; returns connectUrl for the user to complete."""
    client = get_open_finance_client(db, org_id)
    try:
        payload = await _call(client.create_connection(_clean({
            "providerIds": body.provider_ids,
            "redirectUrl": body.redirect_url,
            "language": body.language,
            "includeFakeProviders": body.include_fake_providers,
            "iframe": body.iframe,
            "psuId": body.psu_id,
        })))
        connection_id = payload.get("id")
        connect_url = payload.get("connectUrl")
        # Persist the consent-journey state.
        row = BankConnection(
            organization_id=org_id, source="open_finance",
            connection_id=connection_id, connect_url=connect_url,
            status="INACTIVE", psu_id=body.psu_id, raw_data=payload,
        )
        db.add(row)
        db.commit()
        return {"connection_id": connection_id, "connect_url": connect_url}
    finally:
        await client.close()


@router.get("/connections")
async def list_connections(
    live: bool = Query(False, description="Fetch live from Open Finance instead of local cache"),
    org_id: int = Depends(get_current_org_id),
    db: Session = Depends(get_db_session),
):
    if live:
        client = get_open_finance_client(db, org_id)
        try:
            return await _call(client.list_connections())
        finally:
            await client.close()
    rows = (
        db.query(BankConnection)
        .filter(BankConnection.organization_id == org_id)
        .order_by(BankConnection.created_at.desc())
        .all()
    )
    return {"items": [_bank_connection_dict(r) for r in rows], "count": len(rows)}


@router.get("/connections/{connection_id}")
async def get_connection(connection_id: str, org_id: int = Depends(get_current_org_id), db: Session = Depends(get_db_session)):
    client = get_open_finance_client(db, org_id)
    try:
        return await _call(client.get_connection(connection_id))
    finally:
        await client.close()


@router.delete("/connections/{connection_id}")
async def delete_connection(connection_id: str, org_id: int = Depends(get_current_org_id), db: Session = Depends(get_db_session)):
    client = get_open_finance_client(db, org_id)
    try:
        await _call(client.delete_connection(connection_id))
    finally:
        await client.close()
    row = db.query(BankConnection).filter(
        BankConnection.organization_id == org_id,
        BankConnection.connection_id == connection_id,
    ).first()
    if row:
        row.status = "REVOKED"
        db.commit()
    return {"deleted": True}


@router.post("/connections/{connection_id}/refresh")
async def refresh_connection(connection_id: str, org_id: int = Depends(get_current_org_id), db: Session = Depends(get_db_session)):
    client = get_open_finance_client(db, org_id)
    try:
        await _call(client.refresh_connection(connection_id))
        return {"refreshed": True}
    finally:
        await client.close()


# ====================================================================== #
# DATA — accounts, transactions, reports
# ====================================================================== #
@router.get("/accounts")
async def list_accounts(
    connection_id: Optional[str] = None,
    org_id: int = Depends(get_current_org_id), db: Session = Depends(get_db_session),
):
    client = get_open_finance_client(db, org_id)
    try:
        return await _call(client.list_accounts(connection_id=connection_id))
    finally:
        await client.close()


@router.get("/accounts/{account_id}")
async def get_account(account_id: str, org_id: int = Depends(get_current_org_id), db: Session = Depends(get_db_session)):
    client = get_open_finance_client(db, org_id)
    try:
        return await _call(client.get_account(account_id))
    finally:
        await client.close()


@router.get("/transactions")
async def list_transactions(
    account_id: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    next_page: Optional[str] = None,
    org_id: int = Depends(get_current_org_id), db: Session = Depends(get_db_session),
):
    client = get_open_finance_client(db, org_id)
    try:
        return await _call(client.list_transactions(
            account_id=account_id, date_from=date_from, date_to=date_to, next_page=next_page,
        ))
    finally:
        await client.close()


@router.get("/monthly-report")
async def monthly_report(org_id: int = Depends(get_current_org_id), db: Session = Depends(get_db_session)):
    client = get_open_finance_client(db, org_id)
    try:
        return await _call(client.get_monthly_report())
    finally:
        await client.close()


@router.get("/securities")
async def securities(org_id: int = Depends(get_current_org_id), db: Session = Depends(get_db_session)):
    client = get_open_finance_client(db, org_id)
    try:
        return await _call(client.get_extended_securities())
    finally:
        await client.close()


@router.get("/providers")
async def providers(include_fake: bool = False, org_id: int = Depends(get_current_org_id), db: Session = Depends(get_db_session)):
    client = get_open_finance_client(db, org_id)
    try:
        return await _call(client.list_providers(include_fake_providers=include_fake or None))
    finally:
        await client.close()


@router.get("/bank-branches")
async def bank_branches(bank_code: str = Query(...), org_id: int = Depends(get_current_org_id), db: Session = Depends(get_db_session)):
    client = get_open_finance_client(db, org_id)
    try:
        return await _call(client.list_bank_branches(bank_code))
    finally:
        await client.close()


# ====================================================================== #
# INSIGHTS — bank intelligence
# ====================================================================== #
@router.post("/insights/generate")
async def generate_insights(
    org_id: int = Depends(get_current_org_id),
    db: Session = Depends(get_db_session),
    include_monthly_report: bool = Query(True),
):
    """Run the insights engine over stored bank transactions and upsert results."""
    rows = (
        db.query(BankTransaction)
        .filter(BankTransaction.organization_id == org_id)
        .all()
    )
    txns = [
        bank_insights.txn_from_raw(
            external_id=str(r.external_id or r.id),
            tx_date=r.transaction_date,
            amount=float(r.amount),
            currency=r.currency or "ILS",
            description=r.description or "",
            raw=r.raw_data,
            account_id=str(r.account_id) if r.account_id else None,
        )
        for r in rows if r.transaction_date is not None
    ]

    # Server-side enrichment (monthly report + securities) is optional; insights are
    # still generated from stored transactions even when Open Finance credentials are
    # absent or the calls fail. One client is reused for both fetches.
    monthly = None
    securities = None
    if include_monthly_report:
        client = None
        try:
            client = get_open_finance_client(db, org_id)
            try:
                monthly = await client.get_monthly_report()
            except Exception as exc:  # noqa: BLE001
                logger.info("monthly report unavailable for insights: %s", exc)
            try:
                securities = await client.get_extended_securities()
            except Exception as exc:  # noqa: BLE001
                logger.info("extended-securities unavailable for insights: %s", exc)
        except Exception as exc:  # noqa: BLE001 — client build failed (no creds)
            logger.info("Open Finance client unavailable for insights: %s", exc)
        finally:
            if client is not None:
                await client.close()

    insights = bank_insights.generate_insights(
        txns, monthly_report=monthly, securities=securities,
    )
    created, updated = _upsert_insights(db, org_id, insights)
    # Batch-level sign sanity check — surfaces a flipped-convention provider the
    # moment real bank data flows (raw sign stays primary; we don't force it).
    sign_warning = bank_insights.validate_sign_convention(txns)
    return {"generated": len(insights), "created": created, "updated": updated,
            "transactions_analyzed": len(txns), "sign_warning": sign_warning}


@router.get("/insights")
async def list_insights(
    status: Optional[str] = Query(None),
    org_id: int = Depends(get_current_org_id),
    db: Session = Depends(get_db_session),
):
    q = db.query(CfoInsight).filter(
        CfoInsight.organization_id == org_id,
        CfoInsight.insight_type.in_(BANK_INSIGHT_TYPES),
    )
    if status:
        q = q.filter(CfoInsight.status == status)
    rows = q.order_by(CfoInsight.created_at.desc()).all()
    return {"items": [_insight_dict(r) for r in rows], "count": len(rows)}


@router.post("/insights/{insight_id}/status")
async def set_insight_status(
    insight_id: int, status: str = Body(..., embed=True),
    org_id: int = Depends(get_current_org_id), db: Session = Depends(get_db_session),
):
    row = db.query(CfoInsight).filter(
        CfoInsight.id == insight_id, CfoInsight.organization_id == org_id,
    ).first()
    if not row:
        raise HTTPException(404, "Insight not found")
    row.status = status
    if status == "resolved":
        row.resolved_at = datetime.now(timezone.utc)
    db.commit()
    return {"id": insight_id, "status": status}


# ====================================================================== #
# RECONCILIATION
# ====================================================================== #
@router.post("/reconcile")
async def reconcile(
    persist: bool = Query(True),
    org_id: int = Depends(get_current_org_id),
    db: Session = Depends(get_db_session),
):
    return bank_reconciliation.reconcile_organization(db, org_id, persist=persist)


@router.post("/reconcile/sumit-dispatch")
async def dispatch_reconciliation_to_sumit(
    dry_run: bool = Query(False),
    org_id: int = Depends(get_current_org_id),
    db: Session = Depends(get_db_session),
):
    return await reconciliation_dispatch.dispatch_reconciliation_to_sumit(
        db, org_id, dry_run=dry_run
    )


# ====================================================================== #
# PAYMENTS (B)
# ====================================================================== #
@router.post("/payments")
async def create_payment(body: dict = Body(...), org_id: int = Depends(get_current_org_id), db: Session = Depends(get_db_session)):
    client = get_open_finance_client(db, org_id)
    try:
        return await _call(client.create_payment(body))
    finally:
        await client.close()


@router.get("/payments")
async def list_payments(org_id: int = Depends(get_current_org_id), db: Session = Depends(get_db_session)):
    client = get_open_finance_client(db, org_id)
    try:
        return await _call(client.list_payments())
    finally:
        await client.close()


@router.get("/payments/{payment_id}")
async def get_payment(payment_id: str, org_id: int = Depends(get_current_org_id), db: Session = Depends(get_db_session)):
    client = get_open_finance_client(db, org_id)
    try:
        return await _call(client.get_payment(payment_id))
    finally:
        await client.close()


@router.delete("/payments/{payment_id}")
async def cancel_payment(payment_id: str, org_id: int = Depends(get_current_org_id), db: Session = Depends(get_db_session)):
    client = get_open_finance_client(db, org_id)
    try:
        return await _call(client.cancel_payment(payment_id)) or {"cancelled": True}
    finally:
        await client.close()


@router.post("/payments/{payment_id}/refund")
async def refund_payment(payment_id: str, body: dict = Body(...), org_id: int = Depends(get_current_org_id), db: Session = Depends(get_db_session)):
    client = get_open_finance_client(db, org_id)
    try:
        return await _call(client.refund_payment(
            payment_id, description=body.get("description", ""), amount=body.get("amount", 0),
            psu_id=body.get("psu_id"), phone_number=body.get("phone_number"),
            send_sms=body.get("send_sms", False),
        ))
    finally:
        await client.close()


@router.get("/payments/{payment_id}/status")
async def payment_status(payment_id: str, org_id: int = Depends(get_current_org_id), db: Session = Depends(get_db_session)):
    client = get_open_finance_client(db, org_id)
    try:
        return await _call(client.get_payment_status(payment_id))
    finally:
        await client.close()


@router.post("/payments/init")
async def init_payment(body: dict = Body(...), org_id: int = Depends(get_current_org_id), db: Session = Depends(get_db_session)):
    client = get_open_finance_client(db, org_id)
    try:
        return await _call(client.init_payment(body))
    finally:
        await client.close()


# ---- Mandates ---- #
@router.post("/mandates")
async def create_mandate(body: dict = Body(...), org_id: int = Depends(get_current_org_id), db: Session = Depends(get_db_session)):
    client = get_open_finance_client(db, org_id)
    try:
        return await _call(client.create_mandate(body))
    finally:
        await client.close()


@router.get("/mandates/{resource_id}")
async def get_mandate(resource_id: str, org_id: int = Depends(get_current_org_id), db: Session = Depends(get_db_session)):
    client = get_open_finance_client(db, org_id)
    try:
        return await _call(client.get_mandate(resource_id))
    finally:
        await client.close()


@router.delete("/mandates/{resource_id}")
async def delete_mandate(resource_id: str, org_id: int = Depends(get_current_org_id), db: Session = Depends(get_db_session)):
    client = get_open_finance_client(db, org_id)
    try:
        return await _call(client.delete_mandate(resource_id)) or {"deleted": True}
    finally:
        await client.close()


# ====================================================================== #
# CREDIT-SESSIONS (C)
# ====================================================================== #
@router.post("/credit-sessions")
async def create_credit_session(body: dict = Body(...), org_id: int = Depends(get_current_org_id), db: Session = Depends(get_db_session)):
    client = get_open_finance_client(db, org_id)
    try:
        return await _call(client.create_credit_session(body))
    finally:
        await client.close()


@router.get("/credit-sessions")
async def list_credit_sessions(scope: str = "user", org_id: int = Depends(get_current_org_id), db: Session = Depends(get_db_session)):
    client = get_open_finance_client(db, org_id)
    try:
        return await _call(client.list_credit_sessions(scope))
    finally:
        await client.close()


@router.get("/credit-sessions/{session_id}")
async def get_credit_session(session_id: str, org_id: int = Depends(get_current_org_id), db: Session = Depends(get_db_session)):
    client = get_open_finance_client(db, org_id)
    try:
        return await _call(client.get_credit_session(session_id))
    finally:
        await client.close()


@router.post("/decision/{customer_id}")
async def create_decision(customer_id: str, org_id: int = Depends(get_current_org_id), db: Session = Depends(get_db_session)):
    client = get_open_finance_client(db, org_id)
    try:
        return await _call(client.create_decision(customer_id))
    finally:
        await client.close()


@router.get("/decision/{job_id}")
async def get_decision(job_id: str, org_id: int = Depends(get_current_org_id), db: Session = Depends(get_db_session)):
    client = get_open_finance_client(db, org_id)
    try:
        return await _call(client.get_decision(job_id))
    finally:
        await client.close()


# ====================================================================== #
# CUSTOMERS (C - CRM)
# ====================================================================== #
@router.get("/customers")
async def list_customers(org_id: int = Depends(get_current_org_id), db: Session = Depends(get_db_session)):
    client = get_open_finance_client(db, org_id)
    try:
        return await _call(client.list_customers())
    finally:
        await client.close()


@router.post("/customers")
async def create_customer(body: dict = Body(...), org_id: int = Depends(get_current_org_id), db: Session = Depends(get_db_session)):
    client = get_open_finance_client(db, org_id)
    try:
        return await _call(client.create_customer(body))
    finally:
        await client.close()


@router.get("/customers/{customer_id}")
async def get_customer(customer_id: str, org_id: int = Depends(get_current_org_id), db: Session = Depends(get_db_session)):
    client = get_open_finance_client(db, org_id)
    try:
        return await _call(client.get_customer(customer_id))
    finally:
        await client.close()


# ====================================================================== #
# MERCHANTS (C)
# ====================================================================== #
@router.get("/merchants")
async def list_merchants(org_id: int = Depends(get_current_org_id), db: Session = Depends(get_db_session)):
    client = get_open_finance_client(db, org_id)
    try:
        return await _call(client.list_merchants())
    finally:
        await client.close()


@router.post("/merchants")
async def create_merchant(body: dict = Body(...), org_id: int = Depends(get_current_org_id), db: Session = Depends(get_db_session)):
    client = get_open_finance_client(db, org_id)
    try:
        return await _call(client.create_merchant(body))
    finally:
        await client.close()


# ====================================================================== #
# FULL COVERAGE — remaining B/C endpoints (thin pass-throughs over the client)
# ====================================================================== #
# --- Payments / ATM (B) --- #
@router.patch("/payments/sandbox/{payment_id}")
async def sandbox_payment_status(payment_id: str, status: str = Body(..., embed=True),
                                 org_id: int = Depends(get_current_org_id), db: Session = Depends(get_db_session)):
    return await _run(db, org_id, lambda c: c.update_sandbox_payment_status(payment_id, status))


@router.get("/atm/{payment_id}")
async def atm_code(payment_id: str, org_id: int = Depends(get_current_org_id), db: Session = Depends(get_db_session)):
    return await _run(db, org_id, lambda c: c.get_atm_code(payment_id))


@router.post("/atm/verify")
async def atm_verify(body: dict = Body(...), org_id: int = Depends(get_current_org_id), db: Session = Depends(get_db_session)):
    return await _run(db, org_id, lambda c: c.verify_atm_code(
        atm_id=body.get("atm_id"), atm_code=body.get("atm_code"),
        amount=body.get("amount"), atm_date=body.get("atm_date")))


@router.get("/mandates/{resource_id}/status")
async def mandate_status(resource_id: str, org_id: int = Depends(get_current_org_id), db: Session = Depends(get_db_session)):
    return await _run(db, org_id, lambda c: c.get_mandate_status(resource_id))


# --- Credit sessions / leads / decision / scoring (C) --- #
@router.post("/credit-sessions/with-agent")
async def credit_session_with_agent(body: dict = Body(...), org_id: int = Depends(get_current_org_id), db: Session = Depends(get_db_session)):
    return await _run(db, org_id, lambda c: c.create_credit_session_with_agent(body))


@router.delete("/credit-sessions/{session_id}")
async def delete_credit_session(session_id: str, org_id: int = Depends(get_current_org_id), db: Session = Depends(get_db_session)):
    return await _run(db, org_id, lambda c: c.delete_credit_session(session_id)) or {"deleted": True}


@router.get("/credit-sessions/{session_id}/files")
async def credit_session_files(session_id: str, org_id: int = Depends(get_current_org_id), db: Session = Depends(get_db_session)):
    return await _run(db, org_id, lambda c: c.get_credit_session_files(session_id))


@router.post("/credit-sessions/{session_id}/files")
async def upload_credit_session_file(session_id: str, body: dict = Body(...), org_id: int = Depends(get_current_org_id), db: Session = Depends(get_db_session)):
    return await _run(db, org_id, lambda c: c.upload_credit_session_file(
        session_id, api_name=body.get("api_name"), file=body.get("file")))


@router.post("/credit-sessions/{session_id}/dnb")
async def credit_session_dnb(session_id: str, body: dict = Body(...), org_id: int = Depends(get_current_org_id), db: Session = Depends(get_db_session)):
    return await _run(db, org_id, lambda c: c.get_dnb_company_info_pdf(session_id, body))


@router.get("/credit-leads")
async def list_credit_leads(scope: str = "user", org_id: int = Depends(get_current_org_id), db: Session = Depends(get_db_session)):
    return await _run(db, org_id, lambda c: c.list_credit_leads(scope))


@router.get("/credit-leads/{lead_id}")
async def get_credit_lead(lead_id: str, org_id: int = Depends(get_current_org_id), db: Session = Depends(get_db_session)):
    return await _run(db, org_id, lambda c: c.get_credit_lead(lead_id))


@router.delete("/credit-leads/{lead_id}")
async def delete_credit_lead(lead_id: str, org_id: int = Depends(get_current_org_id), db: Session = Depends(get_db_session)):
    return await _run(db, org_id, lambda c: c.delete_credit_lead(lead_id)) or {"deleted": True}


@router.post("/decision-extended/{customer_id}")
async def create_decision_extended(customer_id: str, org_id: int = Depends(get_current_org_id), db: Session = Depends(get_db_session)):
    return await _run(db, org_id, lambda c: c.create_decision_extended(customer_id))


@router.get("/decision-extended/{job_id}")
async def get_decision_extended(job_id: str, org_id: int = Depends(get_current_org_id), db: Session = Depends(get_db_session)):
    return await _run(db, org_id, lambda c: c.get_decision_extended(job_id))


@router.post("/private-scoring/{customer_id}")
async def create_private_scoring(customer_id: str, org_id: int = Depends(get_current_org_id), db: Session = Depends(get_db_session)):
    return await _run(db, org_id, lambda c: c.create_private_scoring(customer_id))


@router.get("/private-scoring/{job_id}")
async def get_private_scoring(job_id: str, org_id: int = Depends(get_current_org_id), db: Session = Depends(get_db_session)):
    return await _run(db, org_id, lambda c: c.get_private_scoring(job_id))


# --- Customers / CRM (C) --- #
@router.patch("/customers/{customer_id}")
async def update_customer(customer_id: str, body: dict = Body(...), org_id: int = Depends(get_current_org_id), db: Session = Depends(get_db_session)):
    return await _run(db, org_id, lambda c: c.update_customer(customer_id, body)) or {"updated": True}


@router.delete("/customers/{customer_id}")
async def delete_customer(customer_id: str, org_id: int = Depends(get_current_org_id), db: Session = Depends(get_db_session)):
    return await _run(db, org_id, lambda c: c.delete_customer(customer_id)) or {"deleted": True}


@router.get("/customers/{customer_id}/contacts/{contact_id}")
async def customer_contact(customer_id: str, contact_id: str, org_id: int = Depends(get_current_org_id), db: Session = Depends(get_db_session)):
    return await _run(db, org_id, lambda c: c.get_customer_contact(customer_id, contact_id))


@router.get("/customers/{customer_id}/balances")
async def customer_balances(customer_id: str, org_id: int = Depends(get_current_org_id), db: Session = Depends(get_db_session)):
    return await _run(db, org_id, lambda c: c.get_customer_balances(customer_id))


@router.get("/customers/{customer_id}/financial-relations")
async def customer_financial_relations(customer_id: str, org_id: int = Depends(get_current_org_id), db: Session = Depends(get_db_session)):
    return await _run(db, org_id, lambda c: c.get_customer_financial_relations(customer_id))


@router.get("/customers/{customer_id}/invoices")
async def customer_invoices(customer_id: str, org_id: int = Depends(get_current_org_id), db: Session = Depends(get_db_session)):
    return await _run(db, org_id, lambda c: c.list_customer_invoices(customer_id))


@router.post("/customers/{customer_id}/files/{kind}")
async def upload_customer_file(customer_id: str, kind: str, body: dict = Body(...), org_id: int = Depends(get_current_org_id), db: Session = Depends(get_db_session)):
    """kind: invoice | financial-report | checking-account | other."""
    if kind == "invoice":
        fn = lambda c: c.upload_customer_invoice(customer_id, body)
    elif kind == "financial-report":
        fn = lambda c: c.upload_customer_financial_report(customer_id, body)
    elif kind == "checking-account":
        fn = lambda c: c.upload_customer_checking_account(customer_id, body)
    else:
        fn = lambda c: c.upload_customer_other_file(customer_id, api_name=body.get("api_name"), file=body.get("file"))
    return await _run(db, org_id, fn) or {"uploaded": True}


@router.get("/customers/{customer_id}/osh/accounts")
async def customer_osh_accounts(customer_id: str, org_id: int = Depends(get_current_org_id), db: Session = Depends(get_db_session)):
    return await _run(db, org_id, lambda c: c.list_osh_accounts(customer_id))


@router.get("/customers/{customer_id}/osh/accounts/{account_id}")
async def customer_osh_transactions(customer_id: str, account_id: str, org_id: int = Depends(get_current_org_id), db: Session = Depends(get_db_session)):
    return await _run(db, org_id, lambda c: c.list_osh_transactions(customer_id, account_id))


# --- Merchants (C) --- #
@router.get("/merchants/{merchant_id}")
async def get_merchant(merchant_id: str, org_id: int = Depends(get_current_org_id), db: Session = Depends(get_db_session)):
    return await _run(db, org_id, lambda c: c.get_merchant(merchant_id))


@router.put("/merchants/{merchant_id}")
async def update_merchant(merchant_id: str, body: dict = Body(...), org_id: int = Depends(get_current_org_id), db: Session = Depends(get_db_session)):
    return await _run(db, org_id, lambda c: c.update_merchant(merchant_id, body))


@router.delete("/merchants/{merchant_id}")
async def delete_merchant(merchant_id: str, org_id: int = Depends(get_current_org_id), db: Session = Depends(get_db_session)):
    return await _run(db, org_id, lambda c: c.delete_merchant(merchant_id)) or {"deleted": True}


# --- Reports / data (A extras) --- #
@router.post("/financial-report/{customer_id}")
async def create_financial_report(customer_id: str, org_id: int = Depends(get_current_org_id), db: Session = Depends(get_db_session)):
    return await _run(db, org_id, lambda c: c.create_financial_report(customer_id))


@router.get("/financial-report/{job_id}")
async def get_financial_report(job_id: str, with_pdf: bool = False, org_id: int = Depends(get_current_org_id), db: Session = Depends(get_db_session)):
    return await _run(db, org_id, lambda c: c.get_financial_report(job_id, with_pdf=with_pdf))


@router.post("/aggregations")
async def aggregations(body: dict = Body(...), org_id: int = Depends(get_current_org_id), db: Session = Depends(get_db_session)):
    return await _run(db, org_id, lambda c: c.get_aggregations(body.get("user_ids", [])))


@router.post("/aggregate-email")
async def aggregate_email(body: dict = Body(...), org_id: int = Depends(get_current_org_id), db: Session = Depends(get_db_session)):
    return await _run(db, org_id, lambda c: c.send_financial_data_email(
        details_to_share=body.get("details_to_share", []), email=body.get("email")))


@router.post("/account-verification")
async def account_verification(body: dict = Body(...), org_id: int = Depends(get_current_org_id), db: Session = Depends(get_db_session)):
    return await _run(db, org_id, lambda c: c.verify_account_number(
        account_number=body.get("account_number"), account_iban_number=body.get("account_iban_number")))


@router.patch("/transactions/{sk}")
async def update_transaction(sk: str, body: dict = Body(...), org_id: int = Depends(get_current_org_id), db: Session = Depends(get_db_session)):
    return await _run(db, org_id, lambda c: c.update_transaction(
        sk, main_category=body.get("main_category"), sub_category=body.get("sub_category"),
        classification=body.get("classification"), labels=body.get("labels"))) or {"updated": True}


# --- Communication (C) --- #
@router.post("/communication/whatsapp")
async def send_whatsapp(body: dict = Body(...), org_id: int = Depends(get_current_org_id), db: Session = Depends(get_db_session)):
    return await _run(db, org_id, lambda c: c.send_whatsapp_link(body=body.get("body", ""), from_=body.get("from", ""))) or {"sent": True}


# ====================================================================== #
# WEBHOOKS — Open Finance event receiver (no signature scheme documented)
# ====================================================================== #
@router.post("/webhooks")
async def webhook(
    request: Request,
    x_webhook_secret: Optional[str] = Header(None),
    db: Session = Depends(get_db_session),
):
    """Receive Connection/Payment/Session events and update local state."""
    if settings.open_finance_webhook_secret and not secrets.compare_digest(
        x_webhook_secret or "",
        settings.open_finance_webhook_secret,
    ):
        raise HTTPException(401, "invalid webhook credentials")

    try:
        event = await request.json()
    except Exception:  # noqa: BLE001
        raise HTTPException(400, "invalid JSON")

    # --- Connection Status Change: {connectionId, connectionStatus, bankName, ...}
    connection_id = event.get("connectionId")
    if connection_id:
        row = db.query(BankConnection).filter(
            BankConnection.connection_id == connection_id,
        ).first()
        if row:
            if event.get("connectionStatus"):
                row.status = event["connectionStatus"]
            if event.get("bankName"):
                row.bank_name = event["bankName"]
            err = event.get("connectionError")
            if isinstance(err, dict) and err.get("message"):
                row.last_error = err["message"]
            row.last_refresh_at = datetime.now(timezone.utc)
            db.commit()

    # --- Payment Status Change: {paymentId, paymentStatus, userId, orgId, ...}
    # No connectionId on payment events; the org is resolved via the OF user_id
    # stored in the org's IntegrationConnection credentials (env fallback = org 1).
    payment_id = event.get("paymentId")
    if payment_id:
        org_id = _resolve_org_from_of_user(db, event.get("userId"))
        # Fallback: if the event also carries a connectionId mapping to a known
        # BankConnection, use that org (defensive — payment events normally omit
        # connectionId, but this honours a richer/legacy payload shape).
        if org_id is None and connection_id:
            conn = db.query(BankConnection).filter(
                BankConnection.connection_id == connection_id,
            ).first()
            if conn:
                org_id = conn.organization_id
        if org_id is None:
            logger.info(
                "Open Finance payment webhook unattributable (paymentId=%s, userId=%s) — skipping",
                payment_id, event.get("userId"),
            )
        else:
            _upsert_open_finance_payment(db, org_id, payment_id, event)

    # M1b — bidirectional webhooks: also feed the event into the targeted
    # delta-sync service (SyncEngine, scoped entity types) so a completed
    # bank connection or payment update is reflected without waiting for the
    # next cron poll. Never allowed to affect the ack below.
    from ...services.webhook_delta_sync import handle_open_finance_event
    delta_sync_result = await handle_open_finance_event(db, event)

    logger.info("Open Finance webhook received: keys=%s", list(event.keys()))
    return {"received": True, "delta_sync": delta_sync_result}


# ---------------------------------------------------------------------- #
# helpers
# ---------------------------------------------------------------------- #
def _resolve_org_from_of_user(db: Session, of_user_id: Optional[str]) -> Optional[int]:
    """Map an Open Finance ``userId`` to a local organization_id.

    The OF ``orgId`` in the webhook is Open Finance's own tenant id (a different
    namespace from our ``Organization.id``) and must NOT be used as a FK. The
    linking key the rest of the integration uses is the OF ``user_id`` stored in
    the org's IntegrationConnection credentials. For org 1 we also honour the
    env-configured user id, mirroring ``get_open_finance_client``.
    """
    if not of_user_id:
        return None
    rows = (
        db.query(IntegrationConnection)
        .filter(IntegrationConnection.source == "open_finance")
        .all()
    )
    for conn in rows:
        creds = decrypt_credentials(conn.credentials_encrypted) or {}
        cred_user = creds.get("user_id")
        if not cred_user and conn.organization_id == 1:
            cred_user = settings.open_finance_user_id
        if cred_user and str(cred_user) == str(of_user_id):
            return conn.organization_id
    return None


def _upsert_open_finance_payment(db: Session, org_id: int, payment_id: str, event: dict) -> None:
    """Idempotently upsert an OpenFinancePayment from a webhook event.

    Only fields actually present in the event are written, so a status-only
    delivery never clobbers an amount/currency populated from a status poll.
    """
    row = (
        db.query(OpenFinancePayment)
        .filter(
            OpenFinancePayment.organization_id == org_id,
            OpenFinancePayment.external_payment_id == payment_id,
        )
        .first()
    )
    if row is None:
        row = OpenFinancePayment(
            organization_id=org_id, external_payment_id=payment_id,
        )
        db.add(row)

    status = event.get("paymentStatus") or event.get("status")
    if status is not None:
        row.status = status
    # amount/currency are not in the standard Payment Status Change webhook, but
    # honour them if a richer payload ever carries them.
    amount = event.get("amount")
    if amount is not None:
        try:
            row.amount = Decimal(str(amount))
        except (InvalidOperation, ValueError):
            logger.info("OF payment %s: unparseable amount %r", payment_id, amount)
    currency = event.get("currency")
    if currency is not None:
        row.currency = currency
    row.raw_data = event
    db.commit()


def _upsert_insights(db: Session, org_id: int, insights: list[dict]) -> tuple[int, int]:
    created = updated = 0
    for ins in insights:
        row = db.query(CfoInsight).filter(
            CfoInsight.organization_id == org_id,
            CfoInsight.fingerprint == ins["fingerprint"],
        ).first()
        if row:
            row.severity = ins["severity"]
            row.title = ins["title"]
            row.message = ins["message"]
            row.evidence = ins["evidence"]
            row.recommended_action = ins["recommended_action"]
            if row.status == "resolved":
                row.status = "active"
            updated += 1
        else:
            db.add(CfoInsight(
                organization_id=org_id,
                fingerprint=ins["fingerprint"],
                insight_type=ins["insight_type"],
                severity=ins["severity"],
                title=ins["title"],
                message=ins["message"],
                evidence=ins["evidence"],
                recommended_action=ins["recommended_action"],
                status="active",
            ))
            created += 1
    db.commit()
    return created, updated


def _insight_dict(r: CfoInsight) -> dict:
    return {
        "id": r.id, "type": r.insight_type, "severity": r.severity,
        "title": r.title, "message": r.message, "evidence": r.evidence,
        "recommended_action": r.recommended_action, "status": r.status,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


def _bank_connection_dict(r: BankConnection) -> dict:
    return {
        "id": r.id, "connection_id": r.connection_id, "provider_id": r.provider_id,
        "bank_name": r.bank_name, "status": r.status, "connect_url": r.connect_url,
        "accounts_count": r.accounts_count, "transactions_count": r.transactions_count,
        "last_refresh_at": r.last_refresh_at.isoformat() if r.last_refresh_at else None,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


def _clean(d: dict) -> dict:
    return {k: v for k, v in d.items() if v is not None}
