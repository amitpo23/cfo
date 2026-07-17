"""
Open Finance connector for Israeli open-banking account and transaction data.

Implements the `AccountingConnector` contract used by the sync engine, delegating
all HTTP to `OpenFinanceClient`. Transaction/account normalization follows the real
Open Finance response shapes (see docs/open-finance/API_REFERENCE.md); the complete
raw record is preserved in `raw_data` so the insights engine can read the rich fields
(category, merchantName, installments, isDuplicate, markupFee, balancePerEndDay).
"""
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Optional
import hashlib
import json
import logging

from .connector_base import (
    AccountingConnector,
    FetchResult,
    NormalizedAccount,
    NormalizedBankTransaction,
)
from .open_finance_client import OpenFinanceClient

logger = logging.getLogger(__name__)


class OpenFinanceConnector(AccountingConnector):
    """Connector for Open-Finance.ai / Financy account-information APIs."""

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        user_id: str,
        api_base_url: str = "https://api.open-finance.ai/v2",
        oauth_url: str = "https://api.open-finance.ai/oauth/token",
        timeout: float = 30.0,
        connection_id: "Optional[str]" = None,
    ):
        # Derive the host prefix from the configured v2 base so v3/loans lines up too.
        v2_base = api_base_url.rstrip("/")
        v3_loans_base = v2_base[:-3] + "/v3/loans" if v2_base.endswith("/v2") else None
        self.client = OpenFinanceClient(
            client_id,
            client_secret,
            user_id,
            oauth_url=oauth_url,
            v2_base=v2_base,
            v3_loans_base=v3_loans_base,
            timeout=timeout,
        )
        self.user_id = user_id
        # כמה תיקים (orgs) חיים תחת אותו משתמש Financy — כל org חייב להסתנכרן
        # רק מהחיבור הבנקאי שלו, אחרת תנועות של לקוח אחד מזהמות תיק של אחר.
        self.connection_id = connection_id

    async def test_connection(self) -> bool:
        try:
            await self.client.list_accounts(limit=1)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.error("Open Finance connection test failed: %s", exc)
            return False

    async def fetch_accounts(
        self,
        updated_since: Optional[datetime] = None,
        cursor: Optional[str] = None,
        page_size: int = 100,
    ) -> FetchResult:
        payload = await self.client.list_accounts(
            next_page=cursor, limit=min(page_size, 500), include_duplicates=0, sort=-1,
            connection_id=self.connection_id,
        )
        items, next_page = _items_and_next(payload)
        accounts = [self._normalize_account(item) for item in items]
        return FetchResult(items=accounts, has_more=bool(next_page), next_cursor=next_page)

    async def fetch_bank_transactions(
        self,
        updated_since: Optional[datetime] = None,
        cursor: Optional[str] = None,
        page_size: int = 100,
    ) -> FetchResult:
        date_from = updated_since.date().isoformat() if updated_since else None
        payload = await self.client.list_transactions(
            next_page=cursor,
            limit=None if date_from else min(page_size, 500),
            date_from=date_from,
            include_duplicates=0,
            sort=-1,
            connection_id=self.connection_id,
        )
        items, next_page = _items_and_next(payload)
        transactions = [self._normalize_transaction(item) for item in items]
        return FetchResult(items=transactions, has_more=bool(next_page), next_cursor=next_page)

    # --- connections (not part of AccountingConnector, used by sync routes) --- #
    async def fetch_connections(self) -> list[dict[str, Any]]:
        payload = await self.client.list_connections()
        items, _ = _items_and_next(payload)
        return items

    # --- unsupported entity types (Open Finance has no AR/AP concept) --- #
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
        await self.client.close()

    # ------------------------------------------------------------------ #
    # normalization (real Open Finance shapes)
    # ------------------------------------------------------------------ #
    def _normalize_account(self, item: dict[str, Any]) -> NormalizedAccount:
        external_id = (
            _first_str(item, "id", "externalId", "accountId", "SK")
            or _stable_id(item)
        )
        name = (
            _first_str(item, "accountName", "product")
            or _first_str(item, "accountNumber")
            or f"Open Finance Account {external_id}"
        )
        balance = _account_balance(item)
        currency = _normalize_currency(_first_str(item, "currency") or _balance_currency(item) or "ILS")
        account_type, raw_account_type = _map_account_type(item)
        return NormalizedAccount(
            external_id=f"open_finance:{external_id}",
            name=name,
            account_type=account_type,
            currency=currency,
            balance=balance,
            raw_data=item,
            balance_as_of=_account_balance_as_of(item),
            raw_account_type=raw_account_type,
        )

    def _normalize_transaction(self, item: dict[str, Any]) -> NormalizedBankTransaction:
        external_id = _first_str(item, "id", "SK", "transactionProviderIdentifier") or _stable_id(item)
        account_id = _first_str(item, "accountId", "accountNumber")
        amount, currency = _transaction_amount(item)
        description = _transaction_description(item)
        return NormalizedBankTransaction(
            external_id=f"open_finance:{external_id}",
            account_external_id=f"open_finance:{account_id}" if account_id else None,
            transaction_date=_transaction_date(item) or datetime.now(timezone.utc).date(),
            description=description,
            amount=amount,
            currency=currency or "ILS",
            raw_data=item,
        )


# ---------------------------------------------------------------------- #
# field extraction helpers (module-level, easily unit-testable)
# ---------------------------------------------------------------------- #
def _items_and_next(payload: Any) -> tuple[list[dict], Optional[str]]:
    """Open Finance returns either {items, nextPage} or a bare array."""
    if isinstance(payload, list):
        return payload, None
    if isinstance(payload, dict):
        return payload.get("items", []) or [], payload.get("nextPage")
    return [], None


# עדיפות בין balanceType כשיש כמה רשומות יתרה לאותו חשבון (מספר קטן = עדיף).
# closingBooked (יתרה סגורה/מאושרת) > expected (צפויה) > interimAvailable > אחר.
_BALANCE_TYPE_PRIORITY = {"closingBooked": 0, "expected": 1, "interimAvailable": 2}


def _select_balance_entry(item: dict[str, Any]) -> Optional[dict[str, Any]]:
    """בוחר רשומת balance אחת מתוך balances[] של Open Finance.

    הצורה האמיתית (אומתה חי): balances[] = [{balanceType, balanceAmount:
    {amount: "<string>", currency}, referenceDate}, ...] — לעיתים כמה רשומות
    לאותו חשבון (למשל הלוואה עם closingBooked היסטורי וגם עדכני). בוחרים קודם
    לפי עדיפות balanceType, ותוך קבוצת העדיפות הגבוהה ביותר — לפי referenceDate
    המאוחר ביותר (כדי לא ליפול על יתרה ישנה בטעות).
    """
    balances = item.get("balances")
    if not isinstance(balances, list) or not balances:
        return None
    entries = [b for b in balances if isinstance(b, dict)]
    if not entries:
        return None

    def _priority(entry: dict[str, Any]) -> int:
        return _BALANCE_TYPE_PRIORITY.get(entry.get("balanceType"), 99)

    best_priority = min(_priority(e) for e in entries)
    candidates = [e for e in entries if _priority(e) == best_priority]

    def _ref_date(entry: dict[str, Any]):
        return _parse_date(entry.get("referenceDate")) or date.min

    return max(candidates, key=_ref_date)


def _account_balance(item: dict[str, Any]) -> Decimal:
    entry = _select_balance_entry(item)
    if entry is None:
        return _decimal(0)
    amount_obj = entry.get("balanceAmount")
    if isinstance(amount_obj, dict):
        return _decimal(amount_obj.get("amount"))
    # תאימות עם צורה שטוחה ישנה (amount ישירות על הרשומה, לא מקונן)
    return _decimal(entry.get("amount"))


def _account_balance_as_of(item: dict[str, Any]) -> Optional[datetime]:
    entry = _select_balance_entry(item)
    if entry is None:
        return None
    ref_date = _parse_date(entry.get("referenceDate"))
    if ref_date is None:
        return None
    return datetime.combine(ref_date, datetime.min.time())


def _balance_currency(item: dict[str, Any]) -> Optional[str]:
    entry = _select_balance_entry(item)
    if entry is None:
        return None
    amount_obj = entry.get("balanceAmount")
    if isinstance(amount_obj, dict) and amount_obj.get("currency"):
        return amount_obj.get("currency")
    return entry.get("currency")


# CHECKING (עו"ש) -> bank; SAVINGS (חיסכון/פיקדון) -> asset; LOAN/CARD
# (הלוואה/כרטיס אשראי, שתיהן התחייבות) -> liability. אומת חי מול payload אמיתי
# (2026-07-12). ברירת מחדל "bank" לסוגים לא ידועים (כמו קוד PSD2 גנרי CACC),
# תואם את ההתנהגות הקודמת (account_type="bank" קבוע לכולם).
_ACCOUNT_TYPE_MAP = {
    "CHECKING": "bank",
    "SAVINGS": "asset",
    "LOAN": "liability",
    "CARD": "liability",
}


def _map_account_type(item: dict[str, Any]) -> tuple[str, Optional[str]]:
    raw = item.get("accountType")
    if not raw:
        return "bank", None
    raw_type = str(raw).upper()
    return _ACCOUNT_TYPE_MAP.get(raw_type, "bank"), raw_type


# פגם ידוע של הספק: currency="ILY" מוחזר לפעמים במקום "ILS" (עו"ש בעיקר).
def _normalize_currency(currency: Optional[str]) -> str:
    if not currency:
        return "ILS"
    upper = str(currency).upper()
    return "ILS" if upper == "ILY" else upper


def _transaction_amount(item: dict[str, Any]) -> tuple[Decimal, Optional[str]]:
    """amount.{chargedAmount|originalAmount}.{amount,currency}.

    Sign convention (positive = inflow, negative = outflow) is preserved as the API
    returns it — the raw sign stays primary, so a refund inside an expense category
    keeps its (correct) positive sign. The convention is verified at the BATCH level
    by bank_insights.validate_sign_convention(): the first time a real bank connects,
    if income-categorized txns skew negative it flags that this provider emits
    positive-for-debit and the sign here must flip. Until then this is unvalidated.
    """
    amount_obj = item.get("amount")
    if isinstance(amount_obj, dict):
        for key in ("chargedAmount", "originalAmount"):
            sub = amount_obj.get(key)
            if isinstance(sub, dict) and sub.get("amount") is not None:
                return _decimal(sub.get("amount")), sub.get("currency")
        if amount_obj.get("amount") is not None:
            return _decimal(amount_obj.get("amount")), amount_obj.get("currency")
    # flat fallback
    return _decimal(amount_obj if amount_obj is not None else 0), _first_str(item, "currency")


def _transaction_description(item: dict[str, Any]) -> Optional[str]:
    desc = item.get("description")
    if isinstance(desc, dict):
        text = desc.get("description") or desc.get("additionalInfo")
        if text:
            return str(text)
    elif isinstance(desc, str) and desc:
        return desc
    return _first_str(item, "merchantName", "details", "code")


def _transaction_date(item: dict[str, Any]):
    date_obj = item.get("date")
    raw = None
    if isinstance(date_obj, dict):
        raw = date_obj.get("bookingDate") or date_obj.get("transactionDate") or date_obj.get("valueDate")
    elif isinstance(date_obj, str):
        raw = date_obj
    if not raw:
        raw = _first_str(item, "createdAt")
    return _parse_date(raw)


def _parse_date(value: Optional[str]):
    if not value:
        return None
    value = str(value)
    try:
        if value.isdigit():
            ts = int(value)
            if ts >= 1_000_000_000_000:
                ts //= 1000
            return datetime.fromtimestamp(ts, tz=timezone.utc).date()
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except (ValueError, OSError, OverflowError):
        logger.warning("Open Finance record has unparseable date %r; skipping date", value)
        return None


def _first_str(item: dict[str, Any], *keys: str) -> Optional[str]:
    for key in keys:
        value = item.get(key)
        if value not in (None, ""):
            return str(value)
    return None


def _decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value if value not in (None, "") else 0))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _stable_id(item: dict[str, Any]) -> str:
    payload = json.dumps(item, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()
