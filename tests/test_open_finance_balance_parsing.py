"""פענוח יתרות Open Finance לפי המבנה האמיתי (אומת חי, 2026-07-12):

    {"accountType":"SAVINGS","balances":[{"balanceType":"expected",
     "balanceAmount":{"currency":"ILS","amount":"28459.68"},
     "referenceDate":"2026-07-12"}]}

לפני התיקון, _account_balance קרא balances[0]["amount"] (שדה שטוח) ותמיד
קיבל 0 — כי הסכום מקונן תחת balanceAmount.amount כמחרוזת. גם account_type
תמיד נשמר "bank" ללא הבחנה בין עו"ש/חיסכון/הלוואה/כרטיס.
"""
from datetime import date, datetime
from decimal import Decimal

from cfo.services.open_finance_connector import OpenFinanceConnector, _account_balance, _account_balance_as_of


def _connector():
    return OpenFinanceConnector("cid", "secret", "user-1")


def test_account_balance_reads_nested_string_amount():
    item = {
        "accountType": "SAVINGS",
        "balances": [{
            "balanceType": "expected",
            "balanceAmount": {"currency": "ILS", "amount": "28459.68"},
            "referenceDate": "2026-07-12",
        }],
    }
    assert _account_balance(item) == Decimal("28459.68")


def test_account_balance_prefers_latest_reference_date_within_same_type():
    """שני closingBooked — הישן (מרץ 2025) לא אמור לגבור על החדש (יולי 2026)."""
    item = {
        "accountType": "LOAN",
        "balances": [
            {"balanceType": "closingBooked",
             "balanceAmount": {"amount": "11998.41", "currency": "ILS"},
             "referenceDate": "2026-07-10"},
            {"balanceType": "closingBooked",
             "balanceAmount": {"amount": "30000", "currency": "ILS"},
             "referenceDate": "2025-03-11"},
        ],
    }
    assert _account_balance(item) == Decimal("11998.41")


def test_account_balance_prefers_closing_booked_over_expected():
    item = {
        "balances": [
            {"balanceType": "expected",
             "balanceAmount": {"amount": "500", "currency": "ILS"},
             "referenceDate": "2026-07-12"},
            {"balanceType": "closingBooked",
             "balanceAmount": {"amount": "480", "currency": "ILS"},
             "referenceDate": "2026-07-11"},
        ],
    }
    assert _account_balance(item) == Decimal("480")


def test_account_balance_as_of_returns_reference_date():
    item = {
        "balances": [{
            "balanceType": "expected",
            "balanceAmount": {"amount": "100", "currency": "ILS"},
            "referenceDate": "2026-07-12",
        }],
    }
    assert _account_balance_as_of(item) == datetime(2026, 7, 12)


def test_account_balance_falls_back_to_flat_amount_legacy_shape():
    """תאימות עם הצורה הישנה (בלי balanceAmount מקונן) — לא נשבר."""
    item = {"balances": [{"amount": 1234.56, "currency": "ILS", "balanceType": "current"}]}
    assert _account_balance(item) == Decimal("1234.56")


def test_account_balance_empty_or_missing_balances_returns_zero():
    assert _account_balance({}) == Decimal("0")
    assert _account_balance({"balances": []}) == Decimal("0")


# --------------------------------------------------------------------- #
# account_type mapping + currency normalization (ILY -> ILS)
# --------------------------------------------------------------------- #
def test_normalize_account_maps_checking_to_bank():
    conn = _connector()
    a = conn._normalize_account({
        "id": "a1", "accountType": "CHECKING", "currency": "ILS",
        "balances": [{"balanceType": "closingBooked",
                     "balanceAmount": {"amount": "1000", "currency": "ILS"},
                     "referenceDate": "2026-07-12"}],
    })
    assert a.account_type == "bank"
    assert a.raw_account_type == "CHECKING"
    assert a.balance_as_of == datetime(2026, 7, 12)


def test_normalize_account_maps_savings_to_asset():
    conn = _connector()
    raw = {
        "accountType": "SAVINGS", "currency": "ILS", "accountName": 'פר"י', "status": "blocked",
        "balances": [{"balanceType": "expected",
                     "balanceAmount": {"currency": "ILS", "amount": "28459.68"},
                     "referenceDate": "2026-07-12"}],
    }
    a = conn._normalize_account(raw)
    assert a.account_type == "asset"
    assert a.raw_account_type == "SAVINGS"
    assert a.balance == Decimal("28459.68")


def test_normalize_account_maps_loan_to_liability():
    conn = _connector()
    raw = {
        "accountType": "LOAN",
        "balances": [
            {"balanceType": "closingBooked", "balanceAmount": {"amount": "11998.41", "currency": "ILS"},
             "referenceDate": "2026-07-10"},
            {"balanceType": "closingBooked", "balanceAmount": {"amount": "30000", "currency": "ILS"},
             "referenceDate": "2025-03-11"},
        ],
    }
    a = conn._normalize_account(raw)
    assert a.account_type == "liability"
    assert a.raw_account_type == "LOAN"
    assert a.balance == Decimal("11998.41")


def test_normalize_account_maps_card_to_liability():
    conn = _connector()
    a = conn._normalize_account({
        "accountType": "CARD",
        "balances": [{"balanceType": "expected",
                     "balanceAmount": {"amount": "-3200", "currency": "ILS"},
                     "referenceDate": "2026-07-12"}],
    })
    assert a.account_type == "liability"
    assert a.raw_account_type == "CARD"


def test_normalize_account_normalizes_ily_currency_to_ils():
    """פגם ידוע של הספק — currency='ILY' חייב להתנרמל ל-'ILS'."""
    conn = _connector()
    a = conn._normalize_account({
        "accountType": "CHECKING", "currency": "ILY",
        "balances": [{"balanceType": "closingBooked",
                     "balanceAmount": {"amount": "100", "currency": "ILY"},
                     "referenceDate": "2026-07-12"}],
    })
    assert a.currency == "ILS"


def test_normalize_account_unknown_type_defaults_to_bank_and_preserves_old_test_shape():
    """תאימות עם test_normalize_account_real_shape הקיים — accountType='CACC' ללא
    מיפוי מפורש, וצורת balances שטוחה ישנה בלי balanceAmount מקונן."""
    conn = _connector()
    raw = {
        "id": "acc-1", "accountName": 'עו"ש', "currency": "ILS",
        "balances": [{"amount": 1234.56, "currency": "ILS", "balanceType": "current"}],
        "accountType": "CACC",
    }
    a = conn._normalize_account(raw)
    assert a.account_type == "bank"  # ברירת מחדל, כמו קודם
    assert a.balance == Decimal("1234.56")
