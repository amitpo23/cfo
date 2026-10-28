"""Phase B of the card "available" column: store and show the bank's available amount.

Production, 27/10/2026: "how much is free on my cards" had no answer. A card's
stored balance is the last statement (``closingBooked``); the bank's open to buy
(``interimAvailable``, ISO 20022 ITAV) was read only as a fallback balance and
then lost. It now lands in ``accounts.available_limit`` (revision k40a1b2c3d4e)
and the liquidity tab shows each card's limit next to what is still available.

Honest null: an absent or unreadable ``interimAvailable`` is ``None``, never 0,
and never derived from ``creditLimit`` minus the balance. A payload that omits it
does not erase a known value, the same rule as ``credit_limit``. No provider calls.
"""
from datetime import date, datetime
from decimal import Decimal

import pytest

from cfo.database import SessionLocal, init_db
from cfo.models import Account, AccountType, Organization
from cfo.services.connector_base import NormalizedAccount
from cfo.services.dashboards import liquidity
from cfo.services.open_finance_connector import OpenFinanceConnector
from cfo.services.sync_engine import SyncEngine

TODAY = date(2026, 10, 27)


@pytest.fixture(autouse=True, scope="module")
def _ensure_schema():
    init_db()


def _connector():
    return OpenFinanceConnector("cid", "secret", "user-1")


def _card_payload(balances, **extra):
    return {"id": "card-1", "accountType": "CARD", "currency": "ILS", "balances": balances, **extra}


def _entry(balance_type, amount, ref="2026-10-26"):
    return {"balanceType": balance_type, "balanceAmount": {"amount": amount, "currency": "ILS"}, "referenceDate": ref}


# ---------------------------------------------------------------- normalization
def test_the_card_open_to_buy_is_read_from_interim_available():
    account = _connector()._normalize_account(_card_payload([
        _entry("closingBooked", "-3200.00"),
        _entry("interimBooked", "-850.00"),
        _entry("interimAvailable", "11950.00"),
    ], creditLimit=16000))

    assert account.available_limit == Decimal("11950.00")
    assert account.balance == Decimal("-3200.00")
    assert account.credit_limit == Decimal("16000")


def test_the_latest_interim_available_wins():
    account = _connector()._normalize_account(_card_payload([
        _entry("interimAvailable", "9000", ref="2026-10-20"),
        _entry("interimAvailable", "7500", ref="2026-10-26"),
    ]))

    assert account.available_limit == Decimal("7500")


def test_a_formatted_amount_string_is_read():
    account = _connector()._normalize_account(_card_payload([_entry("interimAvailable", "12,345.60")]))

    assert account.available_limit == Decimal("12345.60")


@pytest.mark.parametrize("balances", [
    [],
    [_entry("closingBooked", "-3200")],
    [_entry("interimAvailable", None)],
    [_entry("interimAvailable", "")],
    [_entry("interimAvailable", "n/a")],
    [{"balanceType": "interimAvailable", "referenceDate": "2026-10-26"}],
])
def test_no_readable_interim_available_is_unknown_not_zero(balances):
    account = _connector()._normalize_account(_card_payload(balances, creditLimit=16000))

    assert account.available_limit is None


# ---------------------------------------------------------------- persistence
@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def _org(db):
    org = Organization(name="Cards Co", is_active=True)
    db.add(org)
    db.flush()
    return org.id


def _engine(db, org_id):
    return SyncEngine(db, connector=_connector(), organization_id=org_id, source="open_finance")


def _item(available):
    return NormalizedAccount(
        external_id="open_finance:card-7", name="Visa 1234", account_type="liability",
        balance=Decimal("-3200"), raw_account_type="CARD", credit_limit=Decimal("16000"),
        available_limit=available,
    )


def _row(db, org_id):
    return db.query(Account).filter(
        Account.organization_id == org_id, Account.external_id == "open_finance:card-7",
    ).one()


def test_sync_stores_it_on_create_and_update(db):
    org_id = _org(db)
    engine = _engine(db, org_id)

    assert engine._upsert_account(_item(Decimal("11950"))) == "created"
    db.commit()
    assert _row(db, org_id).available_limit == Decimal("11950")

    assert engine._upsert_account(_item(Decimal("10400"))) == "updated"
    db.commit()
    assert _row(db, org_id).available_limit == Decimal("10400")


def test_a_payload_without_it_keeps_the_known_value(db):
    org_id = _org(db)
    engine = _engine(db, org_id)
    engine._upsert_account(_item(Decimal("11950")))
    db.commit()

    engine._upsert_account(_item(None))
    db.commit()

    assert _row(db, org_id).available_limit == Decimal("11950")


# ---------------------------------------------------------------- liquidity
def _card(db, org_id, name, *, balance, limit, available):
    db.add(Account(
        organization_id=org_id, name=name, account_type=AccountType.LIABILITY, raw_account_type="CARD",
        balance=Decimal(str(balance)), source="open_finance", balance_as_of=datetime(2026, 10, 26),
        external_id=f"of-{name}", credit_limit=None if limit is None else Decimal(str(limit)),
        available_limit=None if available is None else Decimal(str(available)),
    ))


def _build(db, org_id):
    return liquidity.build_liquidity(db, org_id, date(2026, 7, 1), TODAY, plan=None, classified=[], today=TODAY)


def test_each_card_shows_its_limit_and_what_is_available():
    with SessionLocal() as db:
        org_id = _org(db)
        _card(db, org_id, "Visa", balance=-3200, limit=16000, available=11950)
        _card(db, org_id, "Isracard", balance=-500, limit=None, available=None)
        db.commit()

        result = _build(db, org_id)

    cards = {card["name"]: card for card in result["cards"]}
    assert cards["Visa"]["credit_limit"] == 16000.0
    assert cards["Visa"]["available"] == 11950.0
    assert cards["Isracard"]["credit_limit"] is None
    assert cards["Isracard"]["available"] is None
    assert result["card_summary"] == {
        "available": None, "available_known": 11950.0, "available_unknown": 1,
        "credit_limit": None, "credit_limit_known": 16000.0, "credit_limit_unknown": 1,
        "balance": 3700.0, "balance_known": 3700.0, "balance_unknown": 0,
    }


def test_the_card_total_is_known_only_when_every_card_is_known():
    with SessionLocal() as db:
        org_id = _org(db)
        _card(db, org_id, "Visa", balance=-3200, limit=16000, available=11950)
        _card(db, org_id, "Max", balance=-1000, limit=5000, available=4000)
        db.commit()

        result = _build(db, org_id)

    assert result["card_summary"]["available"] == 15950.0
    assert result["card_summary"]["credit_limit"] == 21000.0


def test_the_combined_view_lists_every_entity_card():
    sections = [
        {"label": "A", "liquidity": {"cards": [{"name": "Visa", "balance": 3200.0, "credit_limit": 16000.0,
                                                "available": 11950.0, "as_of": "2026-10-26"}]}},
        {"label": "B", "liquidity": {"cards": [{"name": "Max", "balance": 1000.0, "credit_limit": None,
                                                "available": None, "as_of": "2026-10-26"}]}},
    ]

    combined = liquidity.combine(sections)

    assert [(card["entity"], card["name"]) for card in combined["cards"]] == [("A", "Visa"), ("B", "Max")]
    assert combined["card_summary"]["available"] is None
    assert combined["card_summary"]["available_known"] == 11950.0
