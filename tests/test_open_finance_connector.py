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
