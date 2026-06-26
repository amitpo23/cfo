"""
Full async client for the Open Finance / Financy API.

Covers every documented endpoint across both service bases:
  * v2       -> https://{prefix}.open-finance.ai/v2   (connections, accounts,
               transactions, reports, decisions, payments, atm, mandates,
               merchants, providers, bank-branches, aggregations, communication)
  * v3/loans -> https://{prefix}.open-finance.ai/v3/loans  (credit-sessions, customers)

Authentication is OAuth2 client-credentials: POST /oauth/token with
{userId, clientId, clientSecret} -> {accessToken, tokenType, expiresIn(ms)}.
The same bearer token is used for every call; it is cached until shortly before
`expiresIn` elapses and refreshed automatically (also on a 401).

See docs/open-finance/API_REFERENCE.md for the exact field shapes.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)


class OpenFinanceError(RuntimeError):
    """Raised when the Open Finance API returns an error response."""

    def __init__(self, status_code: int, message: str, payload: Any = None):
        super().__init__(f"Open Finance API error {status_code}: {message}")
        self.status_code = status_code
        self.message = message
        self.payload = payload


class OpenFinanceClient:
    """Thin, complete async wrapper over the Open Finance REST API."""

    DEFAULT_OAUTH_URL = "https://api.open-finance.ai/oauth/token"

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        user_id: str,
        *,
        api_prefix: str = "api",
        oauth_url: Optional[str] = None,
        v2_base: Optional[str] = None,
        v3_loans_base: Optional[str] = None,
        timeout: float = 30.0,
        token_skew_seconds: float = 30.0,
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.user_id = user_id
        self.oauth_url = oauth_url or self.DEFAULT_OAUTH_URL
        host = f"https://{api_prefix}.open-finance.ai"
        self.v2_base = (v2_base or f"{host}/v2").rstrip("/")
        self.v3_loans_base = (v3_loans_base or f"{host}/v3/loans").rstrip("/")
        self._client = httpx.AsyncClient(timeout=timeout)
        self._token: Optional[str] = None
        self._token_expiry: float = 0.0
        self._token_skew = token_skew_seconds

    # ------------------------------------------------------------------ #
    # Auth + transport
    # ------------------------------------------------------------------ #
    async def _get_token(self, force: bool = False) -> str:
        now = time.time()
        if not force and self._token and now < self._token_expiry - self._token_skew:
            return self._token

        resp = await self._client.post(
            self.oauth_url,
            json={
                "userId": self.user_id,
                "clientId": self.client_id,
                "clientSecret": self.client_secret,
            },
        )
        if resp.status_code >= 400:
            raise OpenFinanceError(resp.status_code, "token request failed", _safe_json(resp))
        payload = resp.json()
        token = payload.get("accessToken")
        if not token:
            raise OpenFinanceError(resp.status_code, "token response missing accessToken", payload)
        # expiresIn is in milliseconds.
        expires_in_ms = payload.get("expiresIn")
        try:
            ttl = float(expires_in_ms) / 1000.0 if expires_in_ms else 3600.0
        except (TypeError, ValueError):
            ttl = 3600.0
        self._token = token
        self._token_expiry = now + ttl
        return token

    async def _request(
        self,
        method: str,
        base: str,
        path: str,
        *,
        params: Optional[dict[str, Any]] = None,
        json: Optional[Any] = None,
        extra_headers: Optional[dict[str, str]] = None,
    ) -> Any:
        url = f"{base}{path}"
        clean_params = _clean(params)

        async def _do() -> httpx.Response:
            headers = {"Authorization": f"Bearer {await self._get_token()}"}
            if json is not None:
                headers["Content-Type"] = "application/json"
            if extra_headers:
                headers.update(extra_headers)
            return await self._client.request(
                method, url, params=clean_params, json=json, headers=headers
            )

        resp = await _do()
        if resp.status_code == 401:
            # Token may have expired mid-flight; refresh once and retry.
            await self._get_token(force=True)
            resp = await _do()

        if resp.status_code >= 400:
            payload = _safe_json(resp)
            message = (payload or {}).get("message") if isinstance(payload, dict) else None
            raise OpenFinanceError(resp.status_code, message or resp.text[:200], payload)

        if resp.status_code == 204 or not resp.content:
            return None
        return _safe_json(resp)

    # convenience verbs ------------------------------------------------- #
    async def _v2_get(self, path, **kw):
        return await self._request("GET", self.v2_base, path, **kw)

    async def _v2_post(self, path, **kw):
        return await self._request("POST", self.v2_base, path, **kw)

    async def _v2_patch(self, path, **kw):
        return await self._request("PATCH", self.v2_base, path, **kw)

    async def _v2_put(self, path, **kw):
        return await self._request("PUT", self.v2_base, path, **kw)

    async def _v2_delete(self, path, **kw):
        return await self._request("DELETE", self.v2_base, path, **kw)

    async def _loans_get(self, path, **kw):
        return await self._request("GET", self.v3_loans_base, path, **kw)

    async def _loans_post(self, path, **kw):
        return await self._request("POST", self.v3_loans_base, path, **kw)

    async def _loans_patch(self, path, **kw):
        return await self._request("PATCH", self.v3_loans_base, path, **kw)

    async def _loans_delete(self, path, **kw):
        return await self._request("DELETE", self.v3_loans_base, path, **kw)

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "OpenFinanceClient":
        return self

    async def __aexit__(self, *exc) -> None:
        await self.close()

    async def ping(self) -> bool:
        """Lightweight credential/connectivity check."""
        try:
            await self._get_token(force=True)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.error("Open Finance ping failed: %s", exc)
            return False

    # ================================================================== #
    # CONNECTIONS (v2)
    # ================================================================== #
    async def list_connections(
        self,
        *,
        customer_id=None,
        contact_id=None,
        status=None,
        limit=None,
        sort=None,
        next_page=None,
    ):
        return await self._v2_get(
            "/connections",
            params={
                "customerId": customer_id,
                "contactId": contact_id,
                "status": status,
                "limit": limit,
                "sort": sort,
                "nextPage": next_page,
            },
        )

    async def create_connection(self, body: dict[str, Any]):
        """Create a bank connection (consent journey). Response carries `connectUrl`."""
        return await self._v2_post("/connections", json=body)

    async def get_connection(self, connection_id: str):
        return await self._v2_get(f"/connections/{connection_id}")

    async def delete_connection(self, connection_id: str):
        return await self._v2_delete(f"/connections/{connection_id}")

    async def refresh_connection(self, connection_id: str):
        return await self._v2_get(f"/connections/refresh/{connection_id}")

    async def refresh_all_connections(self, user_id: Optional[str] = None):
        return await self._v2_get(f"/connections/{user_id or self.user_id}/refresh")

    async def init_open_banking_connection(self, body: dict[str, Any]):
        return await self._v2_post("/connect/open-banking-init", json=body)

    async def finalize_open_banking_connection(self, *, state, code=None, error=None):
        return await self._v2_get(
            "/connect/open-banking-finalize",
            params={"state": state, "code": code, "error": error},
        )

    # ================================================================== #
    # ACCOUNTS (v2)
    # ================================================================== #
    async def list_accounts(
        self,
        *,
        connection_id=None,
        account_type=None,
        include_duplicates=0,
        sort=-1,
        limit=500,
        next_page=None,
    ):
        return await self._v2_get(
            "/data/accounts",
            params={
                "connectionId": connection_id,
                "accountType": account_type,
                "includeDuplicates": include_duplicates,
                "sort": sort,
                "limit": limit,
                "nextPage": next_page,
            },
        )

    async def get_account(self, account_id: str):
        return await self._v2_get(f"/data/accounts/{account_id}")

    async def verify_account_number(self, *, account_number=None, account_iban_number=None):
        return await self._v2_post(
            "/account-number-verification",
            json=_clean({"accountNumber": account_number, "accountIbanNumber": account_iban_number}),
        )

    # ================================================================== #
    # TRANSACTIONS (v2)
    # ================================================================== #
    async def list_transactions(
        self,
        *,
        account_id=None,
        connection_id=None,
        provider_id=None,
        type=None,
        date_from=None,
        date_to=None,
        include_duplicates=0,
        sort=-1,
        limit=None,
        next_page=None,
    ):
        # `limit` and date filters are mutually exclusive per the API.
        params = {
            "accountId": account_id,
            "connectionId": connection_id,
            "providerId": provider_id,
            "type": type,
            "includeDuplicates": include_duplicates,
            "sort": sort,
            "nextPage": next_page,
        }
        if date_from or date_to:
            params["dateFrom"] = date_from
            params["dateTo"] = date_to
        else:
            params["limit"] = limit if limit is not None else 500
        return await self._v2_get("/data/transactions", params=params)

    async def get_transaction(self, sk: str):
        return await self._v2_get(f"/data/transactions/{sk}")

    async def update_transaction(
        self,
        sk: str,
        *,
        customer_id=None,
        main_category=None,
        sub_category=None,
        classification=None,
        classification_source=None,
        labels=None,
    ):
        return await self._v2_patch(
            f"/data/transactions/{sk}",
            json=_clean({
                "transactionSk": sk,
                "customerId": customer_id,
                "mainCategory": main_category,
                "subCategory": sub_category,
                "classification": classification,
                "classificationSource": classification_source,
                "labels": labels,
            }),
        )

    # ================================================================== #
    # REPORTS & ANALYTICS (v2)
    # ================================================================== #
    async def create_financial_report(self, customer_id: str):
        return await self._v2_post(f"/financial-report/{customer_id}")

    async def get_financial_report(self, job_id: str, *, with_pdf=False):
        return await self._v2_get(
            f"/financial-report/{job_id}", params={"withPdf": "1" if with_pdf else None}
        )

    async def get_monthly_report(self, user_id: Optional[str] = None):
        return await self._v2_get(f"/data/monthly-report/{user_id or self.user_id}")

    async def get_extended_securities(self):
        return await self._v2_get("/data/extended-securities")

    async def send_financial_data_email(self, *, details_to_share: list[str], email: str):
        return await self._v2_post(
            "/aggregate/financial-data-email",
            json={"detailsToShare": details_to_share, "email": email},
        )

    async def get_aggregations(self, user_ids: list[dict[str, Any]]):
        return await self._v2_post("/aggregations", json={"userIds": user_ids})

    # ================================================================== #
    # DECISION / SCORING (v2)
    # ================================================================== #
    async def create_decision(self, customer_id: str):
        return await self._v2_post(f"/decision/{customer_id}")

    async def get_decision(self, job_id: str):
        return await self._v2_get(f"/decision/{job_id}")

    async def create_decision_extended(self, customer_id: str):
        return await self._v2_post(f"/decision-extended/{customer_id}")

    async def get_decision_extended(self, job_id: str):
        return await self._v2_get(f"/decision-extended/{job_id}")

    async def create_private_scoring(self, customer_id: str):
        return await self._v2_post(f"/private-scoring/{customer_id}")

    async def get_private_scoring(self, job_id: str):
        return await self._v2_get(f"/private-scoring/{job_id}")

    # ================================================================== #
    # PAYMENTS (v2)
    # ================================================================== #
    async def create_payment(self, body: dict[str, Any]):
        return await self._v2_post("/payments", json=body)

    async def list_payments(self, *, limit=None, sort=None, next_page=None):
        return await self._v2_get(
            "/payments", params={"limit": limit, "sort": sort, "nextPage": next_page}
        )

    async def get_payment(self, payment_id: str):
        return await self._v2_get(f"/payments/{payment_id}")

    async def cancel_payment(self, payment_id: str):
        return await self._v2_delete(f"/payments/{payment_id}")

    async def refund_payment(
        self, payment_id: str, *, description: str, amount: float,
        psu_id=None, psu_corporate_id=None, phone_number=None, send_sms=False,
    ):
        return await self._v2_post(
            f"/payments/{payment_id}/refund",
            json=_clean({
                "description": description,
                "amount": amount,
                "psuId": psu_id,
                "psuCorporateId": psu_corporate_id,
                "phoneNumber": phone_number,
                "sendSMS": send_sms,
            }),
        )

    async def get_payment_status(self, payment_id: str):
        return await self._v2_get(f"/payments/{payment_id}/status")

    async def update_sandbox_payment_status(self, payment_id: str, status: str):
        return await self._v2_patch(f"/payments/sandbox/{payment_id}", json={"status": status})

    async def init_payment(self, body: dict[str, Any]):
        """POST /pay/open-banking-init — single, periodic, bulk, or RTP."""
        return await self._v2_post("/pay/open-banking-init", json=body)

    async def get_atm_code(self, payment_id: str):
        return await self._v2_get(f"/atm/code/{payment_id}")

    async def verify_atm_code(self, *, atm_id, atm_code, amount, atm_date):
        return await self._v2_post(
            "/atm/verify",
            json={"atmId": atm_id, "atmCode": atm_code, "amount": amount, "atmDate": atm_date},
        )

    # ================================================================== #
    # MANDATES (v2)
    # ================================================================== #
    async def create_mandate(self, body: dict[str, Any], *, psu_ip_address=None):
        headers = {"psu-ip-address": psu_ip_address} if psu_ip_address else None
        return await self._v2_post("/v2/mandates", json=body, extra_headers=headers)

    async def delete_mandate(self, resource_id: str):
        return await self._v2_delete(f"/v2/mandates/{resource_id}")

    async def get_mandate(self, resource_id: str):
        return await self._v2_get(f"/v2/mandates/{resource_id}")

    async def get_mandate_status(self, resource_id: str):
        return await self._v2_get(f"/v2/mandates/{resource_id}/status")

    # ================================================================== #
    # MERCHANTS / PROVIDERS / BANK BRANCHES (v2)
    # ================================================================== #
    async def list_merchants(self, *, limit=None, sort=None, next_page=None):
        return await self._v2_get(
            "/merchants", params={"limit": limit, "sort": sort, "nextPage": next_page}
        )

    async def create_merchant(self, body: dict[str, Any]):
        return await self._v2_post("/merchants", json=body)

    async def get_merchant(self, merchant_id: str):
        return await self._v2_get(f"/merchants/{merchant_id}")

    async def update_merchant(self, merchant_id: str, body: dict[str, Any]):
        return await self._v2_put(f"/merchants/{merchant_id}", json=body)

    async def delete_merchant(self, merchant_id: str):
        return await self._v2_delete(f"/merchants/{merchant_id}")

    async def list_providers(self, *, include_fake_providers=None):
        return await self._v2_get(
            "/providers", params={"includeFakeProviders": include_fake_providers}
        )

    async def list_bank_branches(self, bank_code: str):
        return await self._v2_get("/bank-branches", params={"bankCode": bank_code})

    # ================================================================== #
    # CREDIT-SESSIONS / LOANS (v3/loans)
    # ================================================================== #
    async def create_credit_session(self, body: dict[str, Any]):
        return await self._loans_post("/credit-sessions", json=body)

    async def create_credit_session_with_agent(self, body: dict[str, Any]):
        return await self._loans_post("/credit-sessions/create-with-agent", json=body)

    async def list_credit_sessions(self, scope: str = "user", *, sync_data=None):
        # scope: advisor | org | user
        return await self._loans_get(
            f"/credit-sessions/converted/{scope}", params={"syncData": sync_data}
        )

    async def get_credit_session(self, session_id: str):
        return await self._loans_get(f"/credit-sessions/converted/{session_id}")

    async def delete_credit_session(self, session_id: str):
        return await self._loans_delete(f"/credit-sessions/converted/{session_id}")

    async def get_credit_session_files(self, session_id: str):
        return await self._loans_get(f"/credit-sessions/converted/{session_id}/files/other")

    async def upload_credit_session_file(self, session_id: str, *, api_name: str, file: dict):
        return await self._loans_post(
            f"/credit-sessions/converted/{session_id}/files/other",
            json={"apiName": api_name, "file": file},
        )

    async def get_dnb_company_info_pdf(self, session_id: str, body: dict[str, Any]):
        return await self._loans_post(f"/credit-sessions/{session_id}/dnb/company-info-pdf", json=body)

    async def list_credit_leads(self, scope: str = "user"):
        return await self._loans_get(f"/credit-sessions/lead/{scope}")

    async def get_credit_lead(self, lead_id: str):
        return await self._loans_get(f"/credit-sessions/lead/{lead_id}")

    async def delete_credit_lead(self, lead_id: str):
        return await self._loans_delete(f"/credit-sessions/lead/{lead_id}")

    async def get_credit_lead_files(self, lead_id: str):
        return await self._loans_get(f"/credit-sessions/lead/{lead_id}/files/other")

    async def upload_credit_lead_file(self, lead_id: str, *, api_name: str, file: dict):
        return await self._loans_post(
            f"/credit-sessions/lead/{lead_id}/files/other",
            json={"apiName": api_name, "file": file},
        )

    # ================================================================== #
    # CUSTOMERS / CRM (v3/loans)
    # ================================================================== #
    async def list_customers(
        self, *, limit=None, next_page=None, use_crm=None, sync_data=None, type=None, use_phone=None
    ):
        return await self._loans_get(
            "/customers",
            params={
                "limit": limit, "nextPage": next_page, "useCrm": use_crm,
                "syncData": sync_data, "type": type, "usePhone": use_phone,
            },
        )

    async def create_customer(self, body: dict[str, Any]):
        # use_crm / sync_data are required by the API.
        body.setdefault("useCrm", False)
        body.setdefault("syncData", False)
        return await self._loans_post("/customers", json=body)

    async def get_customer(self, customer_id: str):
        return await self._loans_get(f"/customers/{customer_id}")

    async def update_customer(self, customer_id: str, body: dict[str, Any]):
        return await self._loans_patch(f"/customers/{customer_id}", json=body)

    async def delete_customer(self, customer_id: str):
        return await self._loans_delete(f"/customers/{customer_id}")

    async def get_customer_contact(self, customer_id: str, contact_id: str):
        return await self._loans_get(f"/customers/{customer_id}/contacts/{contact_id}")

    async def get_customer_balances(self, customer_id: str, *, sort=None, limit=None, next_page=None):
        return await self._loans_get(
            f"/customers/{customer_id}/files/balances",
            params={"sort": sort, "limit": limit, "nextPage": next_page},
        )

    async def upload_customer_checking_account(self, customer_id: str, body: dict[str, Any]):
        return await self._loans_post(f"/customers/{customer_id}/files/checking-account", json=body)

    async def get_customer_financial_relations(self, customer_id: str, *, sort=None, limit=None, next_page=None):
        return await self._loans_get(
            f"/customers/{customer_id}/files/financial-relations",
            params={"sort": sort, "limit": limit, "nextPage": next_page},
        )

    async def upload_customer_financial_report(self, customer_id: str, body: dict[str, Any]):
        return await self._loans_post(f"/customers/{customer_id}/files/financial-report", json=body)

    async def share_customer_financial_report(self, customer_id: str, *, file: str, session_id: str):
        return await self._loans_post(
            f"/customers/{customer_id}/files/financial-report/share-with-agent",
            json={"file": file, "sessionId": session_id},
        )

    async def upload_customer_invoice(self, customer_id: str, body: dict[str, Any]):
        return await self._loans_post(f"/customers/{customer_id}/files/invoice", json=body)

    async def list_customer_invoices(self, customer_id: str, *, sort=None, limit=None, next_page=None):
        return await self._loans_get(
            f"/customers/{customer_id}/files/invoices",
            params={"sort": sort, "limit": limit, "nextPage": next_page},
        )

    async def delete_customer_invoice(self, customer_id: str, pcn_id: str):
        return await self._loans_delete(f"/customers/{customer_id}/files/invoice/{pcn_id}")

    async def get_customer_other_file(self, customer_id: str):
        return await self._loans_get(f"/customers/{customer_id}/files/other")

    async def upload_customer_other_file(self, customer_id: str, *, api_name: str, file: dict, use_crm=None):
        return await self._loans_post(
            f"/customers/{customer_id}/files/other",
            json=_clean({"apiName": api_name, "file": file, "useCrm": use_crm}),
        )

    async def list_osh_accounts(self, customer_id: str, *, sort=None, limit=None, next_page=None):
        return await self._loans_get(
            f"/customers/{customer_id}/osh/accounts",
            params={"sort": sort, "limit": limit, "nextPage": next_page},
        )

    async def update_osh_account(self, *, account_id, customer_id, credit_limit=None, balance=None):
        return await self._loans_patch(
            "/customers/osh/accounts",
            json=_clean({
                "accountId": account_id, "customerId": customer_id,
                "creditLimit": credit_limit, "balance": balance,
            }),
        )

    async def list_osh_transactions(self, customer_id: str, account_id: str, *, sort=None, limit=None, next_page=None):
        return await self._loans_get(
            f"/customers/{customer_id}/osh/accounts/{account_id}",
            params={"sort": sort, "limit": limit, "nextPage": next_page},
        )

    async def delete_osh_account(self, customer_id: str, account_id: str):
        return await self._loans_delete(f"/customers/{customer_id}/osh/accounts/{account_id}")

    async def update_osh_transaction(
        self, *, transaction_sk, main_category=None, sub_category=None,
        classification=None, classification_source=None, labels=None,
    ):
        return await self._loans_patch(
            "/customers/osh/transactions",
            json=_clean({
                "transactionSk": transaction_sk, "mainCategory": main_category,
                "subCategory": sub_category, "classification": classification,
                "classificationSource": classification_source, "labels": labels,
            }),
        )

    # ================================================================== #
    # COMMUNICATION (v2)
    # ================================================================== #
    async def send_whatsapp_link(self, *, body: str, from_: str):
        # Field names are capitalized on the API.
        return await self._v2_post("/v2/completion/wh/incoming", json={"Body": body, "From": from_})


# ---------------------------------------------------------------------- #
# helpers
# ---------------------------------------------------------------------- #
def _clean(params: Optional[dict[str, Any]]) -> dict[str, Any]:
    """Drop keys whose value is None (keeps 0 / False / '')."""
    if not params:
        return {}
    return {k: v for k, v in params.items() if v is not None}


def _safe_json(resp: httpx.Response) -> Any:
    try:
        return resp.json()
    except Exception:  # noqa: BLE001
        return None
