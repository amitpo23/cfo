"""Open Finance amounts that arrive as formatted strings.

Production, 27/10/2026: two of a refresh's transactions were rejected with
"amount is missing or invalid" although their amount object carried an
``amount`` key. A numeric string with a thousands separator, spaces, a shekel
sign or a trailing minus is a readable amount; an empty or absent value is not,
and stays rejected. The rejection report now names the type of each value
(never the value), so the next refresh shows which case it was.
"""
from decimal import Decimal

import pytest

from cfo.services.open_finance_connector import OpenFinanceConnector, _amount_shape


def _tx(amount):
    return {"id": "t", "accountId": "a", "date": "2026-10-20",
            "amount": {"chargedAmount": {"amount": amount, "currency": "ILS"}}}


@pytest.mark.parametrize("raw, expected", [
    ("1,234.56", Decimal("1234.56")),
    ("-1,234.56", Decimal("-1234.56")),
    ("1,234.56-", Decimal("-1234.56")),
    (" 12 345.00 ", Decimal("12345.00")),
    ("₪ 99.90", Decimal("99.90")),
    (-185.5, Decimal("-185.5")),
])
def test_a_formatted_numeric_string_is_read(raw, expected):
    conn = OpenFinanceConnector("cid", "secret", "user-1")

    assert conn._normalize_transaction(_tx(raw)).amount == expected


@pytest.mark.parametrize("raw", ["", "   ", "N/A", "1.2.3"])
def test_an_unreadable_string_is_still_rejected(raw):
    conn = OpenFinanceConnector("cid", "secret", "user-1")

    with pytest.raises(ValueError):
        conn._normalize_transaction(_tx(raw))


def test_the_shape_names_the_type_of_each_value_and_never_the_value():
    shape = _amount_shape({"chargedAmount": {"amount": None, "currency": "ILS"},
                           "originalAmount": {"amount": "1,234.56", "currency": "ILS"}})

    assert shape == {"chargedAmount": {"amount": "NoneType", "currency": "str"},
                     "originalAmount": {"amount": "str", "currency": "str"}}
    assert "1,234.56" not in repr(shape)
