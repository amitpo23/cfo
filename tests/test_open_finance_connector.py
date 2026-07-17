"""Tests for OpenFinanceConnector normalization of real Open Finance shapes."""
from datetime import date
from decimal import Decimal

from cfo.services.open_finance_connector import OpenFinanceConnector


def _connector():
    return OpenFinanceConnector("cid", "secret", "user-1")


def test_normalize_transaction_real_shape():
    conn = _connector()
    raw = {
        "id": "tx-1",
        "accountId": "acc-9",
        "amount": {
            "originalAmount": {"amount": -50.0, "currency": "USD"},
            "chargedAmount": {"amount": -185.5, "currency": "ILS"},
        },
        "description": {"description": "תשלום בכרטיס", "additionalInfo": "x"},
        "merchantName": "Some Shop",
        "date": {"bookingDate": "2026-06-05", "transactionDate": "2026-06-04"},
        "category": {"main": "SHOPPING", "sub": "ONLINE"},
    }
    t = conn._normalize_transaction(raw)
    assert t.external_id == "open_finance:tx-1"
    assert t.account_external_id == "open_finance:acc-9"
    # chargedAmount preferred over originalAmount; sign preserved.
    assert t.amount == Decimal("-185.5")
    assert t.currency == "ILS"
    assert t.description == "תשלום בכרטיס"
    assert t.transaction_date == date(2026, 6, 5)
    # raw is preserved for the insights engine.
    assert t.raw_data["category"]["main"] == "SHOPPING"


def test_normalize_transaction_falls_back_to_merchant_name():
    conn = _connector()
    raw = {"SK": "sk-2", "amount": {"amount": -10, "currency": "ILS"}, "merchantName": "Kiosk"}
    t = conn._normalize_transaction(raw)
    assert t.external_id == "open_finance:sk-2"
    assert t.description == "Kiosk"


def test_normalize_account_real_shape():
    conn = _connector()
    raw = {
        "id": "acc-1",
        "accountName": "עו\"ש",
        "currency": "ILS",
        "balances": [{"amount": 1234.56, "currency": "ILS", "balanceType": "current"}],
        "accountType": "CACC",
    }
    a = conn._normalize_account(raw)
    assert a.external_id == "open_finance:acc-1"
    assert a.name == 'עו"ש'
    assert a.balance == Decimal("1234.56")
    assert a.currency == "ILS"


def test_items_and_next_handles_array_and_object():
    from cfo.services.open_finance_connector import _items_and_next
    assert _items_and_next([{"a": 1}]) == ([{"a": 1}], None)
    assert _items_and_next({"items": [{"b": 2}], "nextPage": "p2"}) == ([{"b": 2}], "p2")
    assert _items_and_next(None) == ([], None)


# --------------------------------------------------------------------------- #
# connection scoping — multi-tenant isolation (org2 mizrahi vs org1 hapoalim)
# --------------------------------------------------------------------------- #
import asyncio


class _RecordingClient:
    """Captures the kwargs the connector sends to the Open Finance client."""

    def __init__(self):
        self.calls = []

    async def list_accounts(self, **kw):
        self.calls.append(("accounts", kw))
        return {"items": [], "nextPage": None}

    async def list_transactions(self, **kw):
        self.calls.append(("transactions", kw))
        return {"items": [], "nextPage": None}

    async def close(self):
        pass


def test_connector_scopes_fetches_to_configured_connection():
    """שני תיקים חיים תחת אותו משתמש Financy — בלי connectionId הסנכרון של
    org 1 היה שואב את תנועות הבנק של org 2 (זיהום חוצה-דיירים)."""
    conn = OpenFinanceConnector("cid", "secret", "user-1",
                                connection_id="01KXAVNTTRPWY55HJYSPHY1ZSK")
    rec = _RecordingClient()
    conn.client = rec
    asyncio.run(conn.fetch_accounts())
    asyncio.run(conn.fetch_bank_transactions())
    assert rec.calls[0][1]["connection_id"] == "01KXAVNTTRPWY55HJYSPHY1ZSK"
    assert rec.calls[1][1]["connection_id"] == "01KXAVNTTRPWY55HJYSPHY1ZSK"


def test_connector_without_connection_id_sends_none():
    conn = OpenFinanceConnector("cid", "secret", "user-1")
    rec = _RecordingClient()
    conn.client = rec
    asyncio.run(conn.fetch_accounts())
    assert rec.calls[0][1]["connection_id"] is None


def test_factory_passes_connection_id_from_credentials(fresh_org, monkeypatch):
    from cfo.database import SessionLocal
    from cfo.services.sync_engine import get_connector_for_org
    from cfo.models import IntegrationConnection
    from cfo.services.credentials_vault import encrypt_credentials

    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        db.add(IntegrationConnection(
            organization_id=org_id, source="open_finance", status="active",
            credentials_encrypted=encrypt_credentials({
                "client_id": "cid", "client_secret": "sec",
                "user_id": "u@example.com",
                "connection_id": "01KXAVNTTRPWY55HJYSPHY1ZSK",
            }),
        ))
        db.commit()
        connector, conn_id, source = get_connector_for_org(db, org_id, "open_finance")
        assert source == "open_finance"
        assert connector.connection_id == "01KXAVNTTRPWY55HJYSPHY1ZSK"
    finally:
        db.close()
