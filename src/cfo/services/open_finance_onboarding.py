"""M2c — in-Rezef Open Finance bank-connection journey (multi-business onboarding).

Per the Open Finance auth model, the platform's clientId/clientSecret are
shared across every org (see get_open_finance_client / get_connector_for_org),
while `userId` is an identifier Rezef chooses per user. Historically only
org 1 worked, because its OF `userId` came from a one-off Financy signup and
was only ever wired via env vars.

This module lets ANY org self-onboard to Open Finance from inside Rezef:
  1. ensure_of_identity — idempotently provisions an org-scoped userId
     (`rezef-org-<id>`) stored in the org's IntegrationConnection.
  2. start_bank_connection — calls POST /v2/connections with that identity
     and hands back the connectUrl for the business owner to complete the
     bank consent journey (allowBusiness=True so company accounts work too).
  3. get_connection_status — proxies GET /v2/connections/{id} with an honest,
     documented status (including the PARTIALLY_AUTHORIZED shared-account
     case — see docs/OPEN_FINANCE_KNOWLEDGE_BASE.md section 9).
"""
from __future__ import annotations

from typing import Any, Optional

from sqlalchemy.orm import Session

from ..models import BankConnection, IntegrationConnection
from .open_finance_client import OpenFinanceError
from .credentials_vault import decrypt_credentials, encrypt_credentials

# Hebrew explanations for the connection statuses the UI/chat needs to
# surface honestly rather than papering over with a generic "pending".
_STATUS_EXPLANATIONS = {
    "PARTIALLY_AUTHORIZED": (
        "בחשבון משותף אושר עד כה רק על ידי בעל חשבון אחד — יתר בעלי החשבון "
        "חייבים לאשר גם הם לפני שהחיבור יהפוך לפעיל."
    ),
}


def _org_user_id(org_id: int) -> str:
    return f"rezef-org-{org_id}"


def ensure_of_identity(db: Session, org_id: int) -> IntegrationConnection:
    """Idempotently ensure an active open_finance IntegrationConnection for
    org_id whose stored credentials carry a `user_id`.

    Org 1 (the pilot) is left alone if it already has a row with empty
    credentials — the env fallback in get_open_finance_client/
    get_connector_for_org covers it. Every other org gets a deterministic
    `rezef-org-<id>` userId written into its stored credentials the first
    time (or if a row exists without one yet); client_id/client_secret are
    NOT stored per-org since those fall back to the shared platform env
    credentials for any org.
    """
    conn = (
        db.query(IntegrationConnection)
        .filter(
            IntegrationConnection.organization_id == org_id,
            IntegrationConnection.source == "open_finance",
        )
        .first()
    )

    if conn is None:
        creds: dict[str, Any] = {}
        if org_id != 1:
            creds["user_id"] = _org_user_id(org_id)
        conn = IntegrationConnection(
            organization_id=org_id,
            source="open_finance",
            status="active",
            credentials_encrypted=encrypt_credentials(creds),
        )
        db.add(conn)
        db.commit()
        db.refresh(conn)
        return conn

    if conn.status != "active":
        conn.status = "active"

    if org_id == 1:
        # Leave org 1 alone — env fallback covers an empty-credentials row.
        db.commit()
        return conn

    creds = decrypt_credentials(conn.credentials_encrypted) or {}
    if not creds.get("user_id"):
        creds["user_id"] = _org_user_id(org_id)
        conn.credentials_encrypted = encrypt_credentials(creds)

    db.commit()
    db.refresh(conn)
    return conn


def local_bank_connection(
    db: Session,
    org_id: int,
    connection_id: str,
) -> BankConnection:
    """Resolve a provider connection id inside one tenant before any live call."""
    row = (
        db.query(BankConnection)
        .filter(
            BankConnection.organization_id == org_id,
            BankConnection.connection_id == connection_id,
        )
        .first()
    )
    if row is None:
        raise OpenFinanceError(
            404,
            "Open Finance connection not found for this organization",
        )
    return row


def persist_connection_journey(
    db: Session,
    org_id: int,
    payload: dict[str, Any],
    *,
    psu_id: Optional[str] = None,
) -> BankConnection:
    """Validate and persist the provider's consent-journey response.

    Both stable provider fields are mandatory. Returning a successful response
    with a null id or URL would leave an untraceable consent and must fail
    closed.
    """
    if not isinstance(payload, dict):
        raise OpenFinanceError(
            502,
            "connection response is not an object",
            payload,
        )
    connection_id = payload.get("id")
    connect_url = payload.get("connectUrl")
    if not connection_id or not connect_url:
        raise OpenFinanceError(
            502,
            "connection response missing id or connectUrl",
            payload,
        )

    row = (
        db.query(BankConnection)
        .filter(
            BankConnection.organization_id == org_id,
            BankConnection.connection_id == str(connection_id),
        )
        .first()
    )
    if row is None:
        row = BankConnection(
            organization_id=org_id,
            source="open_finance",
            connection_id=str(connection_id),
        )
        db.add(row)
    row.connect_url = str(connect_url)
    row.status = payload.get("status") or "INACTIVE"
    row.psu_id = psu_id
    row.provider_id = (
        payload.get("providerFriendlyId")
        or payload.get("providerId")
        or row.provider_id
    )
    row.raw_data = payload
    db.flush()
    return row


async def start_bank_connection(
    db: Session,
    org_id: int,
    *,
    psu_id: Optional[str] = None,
    psu_corporate_id: Optional[str] = None,
    provider_ids: Optional[list[str]] = None,
    redirect_url: Optional[str] = None,
    language: str = "he",
) -> dict[str, Any]:
    """Ensure the org's Open Finance identity, start a bank consent journey
    (allowBusiness=True so company/corporate accounts can connect too), and
    persist the returned connection id under the org's IntegrationConnection.

    Returns {"connection_id", "connect_url"}.
    """
    from ..api.routes.open_finance import get_open_finance_client, _clean

    conn = ensure_of_identity(db, org_id)

    client = get_open_finance_client(db, org_id)
    try:
        body = _clean({
            "psuId": psu_id,
            "psuCorporateId": psu_corporate_id,
            "providerIds": provider_ids,
            "redirectUrl": redirect_url,
            "language": language,
            "allowBusiness": True,
        })
        payload = await client.create_connection(body)
    finally:
        await client.close()

    bank_connection = persist_connection_journey(
        db,
        org_id,
        payload,
        psu_id=psu_id,
    )
    connection_id = bank_connection.connection_id
    connect_url = bank_connection.connect_url

    creds = decrypt_credentials(conn.credentials_encrypted) or {}
    of_connection_ids = list(creds.get("of_connection_ids") or [])
    if connection_id and connection_id not in of_connection_ids:
        of_connection_ids.append(connection_id)
    creds["of_connection_ids"] = of_connection_ids
    conn.credentials_encrypted = encrypt_credentials(creds)
    db.add(conn)
    db.commit()

    return {"connection_id": connection_id, "connect_url": connect_url}


async def get_connection_status(db: Session, org_id: int, connection_id: str) -> dict[str, Any]:
    """Proxy GET /v2/connections/{id}, returning an honest status shape.

    {status, provider, expiry, accounts, last_fetched, explanation?}
    `explanation` is only present for statuses that need clarifying (e.g.
    PARTIALLY_AUTHORIZED on a shared account).
    """
    from ..api.routes.open_finance import get_open_finance_client

    row = local_bank_connection(db, org_id, connection_id)

    client = get_open_finance_client(db, org_id)
    try:
        payload = await client.get_connection(connection_id)
    finally:
        await client.close()

    if not isinstance(payload, dict):
        raise OpenFinanceError(
            502,
            "connection status response is not an object",
            payload,
        )
    status = payload.get("status") or payload.get("connectionStatus")
    if not status:
        raise OpenFinanceError(
            502,
            "connection status response missing status",
            payload,
        )
    row.status = status
    row.provider_id = (
        payload.get("providerFriendlyId")
        or payload.get("providerId")
        or row.provider_id
    )
    row.bank_name = payload.get("bankName") or row.bank_name
    accounts = payload.get("accounts")
    if isinstance(accounts, list):
        row.accounts_count = len(accounts)
    elif isinstance(accounts, int):
        row.accounts_count = accounts
    row.raw_data = payload
    db.commit()

    result: dict[str, Any] = {
        "status": status,
        "provider": payload.get("providerFriendlyId") or payload.get("provider") or payload.get("bankName"),
        "expiry": payload.get("expiryDate") or payload.get("expiry"),
        "accounts": payload.get("accounts"),
        "last_fetched": payload.get("lastFetched") or payload.get("lastRefreshAt") or payload.get("updatedAt"),
    }
    explanation = _STATUS_EXPLANATIONS.get(status)
    if explanation:
        result["explanation"] = explanation
    return result
