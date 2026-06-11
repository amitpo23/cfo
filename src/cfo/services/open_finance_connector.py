"""
Open Finance connector for Israeli open-banking account and transaction data.
"""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Optional
import hashlib
import json
import logging

import httpx

from .connector_base import (
    AccountingConnector,
    FetchResult,
    NormalizedAccount,
    NormalizedBankTransaction,
)

logger = logging.getLogger(__name__)


class OpenFinanceConnector(AccountingConnector):
    """
    Connector for Open-Finance.ai / Financy account-information APIs.

    The API requires a customer-scoped access token created from clientId,
    clientSecret, and the caller's userId. Bank consent/connection creation is
    handled by Open Finance outside this connector.
    """

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        user_id: str,
        api_base_url: str = "https://api.open-finance.ai/v2",
        oauth_url: str = "https://api.open-finance.ai/oauth/token",
        timeout: float = 30.0,
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.user_id = user_id
        self.api_base_url = api_base_url.rstrip("/")
        self.oauth_url = oauth_url
        self._client = httpx.AsyncClient(timeout=timeout)
        self._access_token: Optional[str] = None

    async def _get_access_token(self) -> str:
        if self._access_token:
            return self._access_token

        response = await self._client.post(
            self.oauth_url,
            json={
                "userId": self.user_id,
                "clientId": self.client_id,
                "clientSecret": self.client_secret,
            },
        )
        response.raise_for_status()
        payload = response.json()
        token = payload.get("accessToken")
        if not token:
            raise ValueError("Open Finance token response did not include accessToken")
        self._access_token = token
        return token

    async def _get(self, path: str, params: Optional[dict[str, Any]] = None) -> dict:
        clean_params = {k: v for k, v in (params or {}).items() if v is not None}
        response = await self._client.get(
            f"{self.api_base_url}{path}",
            params=clean_params,
            headers={"Authorization": f"Bearer {await self._get_access_token()}"},
        )
        if response.status_code == 401:
            # Token expired mid-sync — refresh once and retry.
            self._access_token = None
            response = await self._client.get(
                f"{self.api_base_url}{path}",
                params=clean_params,
                headers={"Authorization": f"Bearer {await self._get_access_token()}"},
            )
        response.raise_for_status()
        return response.json()

    async def test_connection(self) -> bool:
        try:
            await self._get("/data/accounts", {"limit": 1})
            return True
        except Exception as exc:
            logger.error("Open Finance connection test failed: %s", exc)
            return False

    async def fetch_accounts(
        self,
        updated_since: Optional[datetime] = None,
        cursor: Optional[str] = None,
        page_size: int = 100,
    ) -> FetchResult:
        payload = await self._get(
            "/data/accounts",
            {
                "nextPage": cursor,
                "limit": min(page_size, 500),
                "includeDuplicates": 0,
                "sort": -1,
            },
        )

        accounts = [self._normalize_account(item) for item in payload.get("items", [])]
        next_page = payload.get("nextPage")
        return FetchResult(items=accounts, has_more=bool(next_page), next_cursor=next_page)

    async def fetch_bank_transactions(
        self,
        updated_since: Optional[datetime] = None,
        cursor: Optional[str] = None,
        page_size: int = 100,
    ) -> FetchResult:
        payload = await self._get(
            "/data/transactions",
            {
                "nextPage": cursor,
                "limit": None if updated_since else min(page_size, 500),
                "dateFrom": updated_since.date().isoformat() if updated_since else None,
                "includeDuplicates": 0,
                "sort": -1,
            },
        )

        transactions = [
            self._normalize_transaction(item)
            for item in payload.get("items", [])
        ]
        next_page = payload.get("nextPage")
        return FetchResult(items=transactions, has_more=bool(next_page), next_cursor=next_page)

    async def fetch_customers(self, *args, **kwargs) -> FetchResult:
        return FetchResult(items=[], has_more=False)

    async def fetch_vendors(self, *args, **kwargs) -> FetchResult:
        return FetchResult(items=[], has_more=False)

    async def fetch_invoices(self, *args, **kwargs) -> FetchResult:
        return FetchResult(items=[], has_more=False)

    async def fetch_bills(self, *args, **kwargs) -> FetchResult:
        return FetchResult(items=[], has_more=False)

    async def fetch_payments(self, *args, **kwargs) -> FetchResult:
        return FetchResult(items=[], has_more=False)

    async def fetch_journal_entries(self, *args, **kwargs) -> FetchResult:
        return FetchResult(items=[], has_more=False)

    async def close(self):
        await self._client.aclose()

    def _normalize_account(self, item: dict[str, Any]) -> NormalizedAccount:
        external_id = self._first_str(item, "id", "_id", "sk", "accountId") or self._stable_id(item)
        name = (
            self._first_str(item, "name", "displayName", "nickname", "accountName")
            or self._first_str(item, "accountNumber", "iban")
            or f"Open Finance Account {external_id}"
        )
        balance = self._decimal(
            self._nested_first(item, "balance", "currentBalance", "availableBalance", "amount")
        )

        return NormalizedAccount(
            external_id=f"open_finance:{external_id}",
            name=name,
            account_type="bank",
            currency=self._first_str(item, "currency") or "ILS",
            balance=balance,
            raw_data=item,
        )

    def _normalize_transaction(self, item: dict[str, Any]) -> NormalizedBankTransaction:
        external_id = self._first_str(item, "id", "_id", "sk", "transactionId") or self._stable_id(item)
        account_id = self._first_str(item, "accountId", "account_id")
        amount = self._decimal(
            self._nested_first(item, "amount", "transactionAmount", "value", "total")
        )

        direction = (self._first_str(item, "direction", "creditDebitIndicator", "type") or "").upper()
        if direction in {"DEBIT", "EXPENSE", "OUT", "WITHDRAWAL"} and amount > 0:
            amount = -amount

        return NormalizedBankTransaction(
            external_id=f"open_finance:{external_id}",
            account_external_id=f"open_finance:{account_id}" if account_id else None,
            transaction_date=self._date(item) or datetime.utcnow().date(),
            description=(
                self._first_str(item, "description", "memo", "merchantName", "counterpartyName")
                or self._first_str(item, "category")
            ),
            amount=amount,
            currency=self._first_str(item, "currency") or "ILS",
            raw_data=item,
        )

    def _date(self, item: dict[str, Any]):
        value = self._first_str(item, "date", "transactionDate", "bookingDate", "createdAt")
        if not value:
            return None
        try:
            if value.isdigit():
                # Epoch seconds or milliseconds.
                ts = int(value)
                if ts >= 1_000_000_000_000:
                    ts //= 1000
                return datetime.fromtimestamp(ts, tz=timezone.utc).date()
            return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
        except (ValueError, OSError, OverflowError):
            logger.warning("Open Finance record has unparseable date %r; skipping date", value)
            return None

    @staticmethod
    def _first_str(item: dict[str, Any], *keys: str) -> Optional[str]:
        for key in keys:
            value = item.get(key)
            if value not in (None, ""):
                return str(value)
        return None

    @staticmethod
    def _nested_first(item: dict[str, Any], *keys: str) -> Any:
        for key in keys:
            value = item.get(key)
            if isinstance(value, dict):
                value = value.get("amount") or value.get("value")
            if value not in (None, ""):
                return value
        return 0

    @staticmethod
    def _decimal(value: Any) -> Decimal:
        try:
            return Decimal(str(value or 0))
        except (InvalidOperation, ValueError):
            return Decimal("0")

    @staticmethod
    def _stable_id(item: dict[str, Any]) -> str:
        payload = json.dumps(item, sort_keys=True, default=str)
        return hashlib.sha256(payload.encode()).hexdigest()
