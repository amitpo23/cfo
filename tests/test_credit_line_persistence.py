"""PR1 of the bookkeeper daily-cycle plan — persist Open Finance credit-limit data.

`creditLimit` is a top-level numeric field on the OF Account object for ANY
account type (also CHECKING overdraft framework); credit frameworks (מסגרת
חח"ד) also appear as accountType=LOAN rows. `interimAvailable` is the
AVAILABLE credit (open-to-buy), not the limit and not usage — it must NEVER
be used to derive credit_limit. When creditLimit is absent, credit_limit
stays NULL (honest-null), never 0 and never derived from another field.

Covers: connector normalization (docs/open_finance_api_reference/get_data-accounts.md
~line 339), SyncEngine._upsert_account persistence (create + update, without
clobbering an existing value on a payload that omits the field), and every
account serializer exposed to the API: GET /accounts, GET /accounts/{id},
DashboardService's cash_by_account (per-account CHECKING breakdown), and
bank_query_service.get_bank_position (the AI-chat account listing).
"""
from datetime import datetime
from decimal import Decimal

import pytest

from cfo.database import SessionLocal
from cfo.models import Account, AccountType
from cfo.services.connector_base import NormalizedAccount
from cfo.services.open_finance_connector import OpenFinanceConnector
from cfo.services.sync_engine import SyncEngine


def _connector():
    return OpenFinanceConnector("cid", "secret", "user-1")


# --------------------------------------------------------------------- #
# normalization: _normalize_account extracts top-level creditLimit
# --------------------------------------------------------------------- #
def test_normalize_account_extracts_numeric_credit_limit():
    conn = _connector()
    a = conn._normalize_account({
        "id": "a1", "accountType": "CHECKING", "currency": "ILS", "creditLimit": 15000,
        "balances": [{"balanceType": "closingBooked",
                     "balanceAmount": {"amount": "1000", "currency": "ILS"},
                     "referenceDate": "2026-07-12"}],
    })
    assert a.credit_limit == Decimal("15000")


def test_normalize_account_extracts_string_credit_limit():
    conn = _connector()
    a = conn._normalize_account({
        "id": "a1", "accountType": "CHECKING", "currency": "ILS", "creditLimit": "15000",
        "balances": [],
    })
    assert a.credit_limit == Decimal("15000")


def test_normalize_account_absent_credit_limit_is_none():
    conn = _connector()
    a = conn._normalize_account({
        "id": "a1", "accountType": "CHECKING", "currency": "ILS",
        "balances": [],
    })
    assert a.credit_limit is None


def test_normalize_account_garbage_credit_limit_is_none():
    conn = _connector()
    a = conn._normalize_account({
        "id": "a1", "accountType": "CHECKING", "currency": "ILS", "creditLimit": "not-a-number",
        "balances": [],
    })
    assert a.credit_limit is None


def test_normalize_account_loan_row_without_credit_limit_is_none_not_derived():
    """LOAN row (מסגרת אשראי) with only interimAvailable must NOT derive a limit."""
    conn = _connector()
    a = conn._normalize_account({
        "accountType": "LOAN",
        "creditLimit": None,
        "balances": [
            {"balanceType": "interimAvailable",
             "balanceAmount": {"amount": "8000", "currency": "ILS"},
             "referenceDate": "2026-07-12"},
        ],
    })
    assert a.credit_limit is None


def test_normalize_account_loan_row_with_credit_limit_extracted():
    conn = _connector()
    a = conn._normalize_account({
        "accountType": "LOAN", "creditLimit": 50000,
        "balances": [{"balanceType": "closingBooked",
                     "balanceAmount": {"amount": "-12000", "currency": "ILS"},
                     "referenceDate": "2026-07-12"}],
    })
    assert a.account_type == "liability"
    assert a.credit_limit == Decimal("50000")


# --------------------------------------------------------------------- #
# _upsert_account persistence: create / update / preserve-on-omit
# --------------------------------------------------------------------- #
@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def _engine(db, org_id):
    return SyncEngine(db, connector=_connector(), organization_id=org_id, source="open_finance")


def test_upsert_account_create_persists_credit_limit(db, fresh_org):
    org = fresh_org()
    engine = _engine(db, org["org_id"])
    item = NormalizedAccount(
        external_id="open_finance:cl-1", name="Bank Leumi Checking",
        account_type="bank", balance=Decimal("1000"), credit_limit=Decimal("20000"),
    )
    action = engine._upsert_account(item)
    db.commit()
    assert action == "created"

    row = db.query(Account).filter(
        Account.organization_id == org["org_id"], Account.external_id == "open_finance:cl-1",
    ).first()
    assert row.credit_limit == Decimal("20000")


def test_upsert_account_persists_open_finance_connection_id(db, fresh_org):
    org = fresh_org()
    engine = _engine(db, org["org_id"])
    item = NormalizedAccount(
        external_id="open_finance:conn-map", name="Mapped bank",
        account_type="bank", open_finance_connection_id="conn-source-evidence",
    )
    engine._upsert_account(item)
    db.commit()

    row = db.query(Account).filter(
        Account.organization_id == org["org_id"],
        Account.external_id == "open_finance:conn-map",
    ).one()
    assert row.open_finance_connection_id == "conn-source-evidence"


def test_upsert_account_update_overwrites_with_new_value(db, fresh_org):
    org = fresh_org()
    engine = _engine(db, org["org_id"])
    item = NormalizedAccount(
        external_id="open_finance:cl-2", name="Bank Leumi Checking",
        account_type="bank", balance=Decimal("1000"), credit_limit=Decimal("20000"),
    )
    engine._upsert_account(item)
    db.commit()

    item2 = NormalizedAccount(
        external_id="open_finance:cl-2", name="Bank Leumi Checking",
        account_type="bank", balance=Decimal("1100"), credit_limit=Decimal("25000"),
    )
    action = engine._upsert_account(item2)
    db.commit()
    assert action == "updated"

    row = db.query(Account).filter(
        Account.organization_id == org["org_id"], Account.external_id == "open_finance:cl-2",
    ).first()
    assert row.credit_limit == Decimal("25000")


def test_upsert_account_update_with_none_preserves_existing_credit_limit(db, fresh_org):
    """A sync payload that omits creditLimit must never NULL-out a previously
    known value — Open Finance doesn't guarantee the field on every page/poll."""
    org = fresh_org()
    engine = _engine(db, org["org_id"])
    item = NormalizedAccount(
        external_id="open_finance:cl-3", name="Bank Leumi Checking",
        account_type="bank", balance=Decimal("1000"), credit_limit=Decimal("20000"),
    )
    engine._upsert_account(item)
    db.commit()

    item2 = NormalizedAccount(
        external_id="open_finance:cl-3", name="Bank Leumi Checking",
        account_type="bank", balance=Decimal("1100"), credit_limit=None,
    )
    action = engine._upsert_account(item2)
    db.commit()
    assert action == "updated"

    row = db.query(Account).filter(
        Account.organization_id == org["org_id"], Account.external_id == "open_finance:cl-3",
    ).first()
    assert row.credit_limit == Decimal("20000")  # preserved, not clobbered


# --------------------------------------------------------------------- #
# API serialization: GET /accounts, GET /accounts/{id}
# --------------------------------------------------------------------- #
def test_accounts_route_includes_credit_limit(client, owner):
    org_id = owner["user"]["organization_id"]
    db = SessionLocal()
    try:
        acc = Account(
            organization_id=org_id, name="Bank Hapoalim Checking",
            account_type=AccountType.BANK, source="open_finance",
            external_id="open_finance:cl-api-1", balance=1000, currency="ILS",
            credit_limit=Decimal("30000"),
        )
        db.add(acc)
        db.commit()
    finally:
        db.close()

    r = client.get("/api/open-finance/accounts", headers=owner["headers"])
    assert r.status_code == 200, r.text
    body = r.json()
    match = next(a for a in body["items"] if a["external_id"] == "open_finance:cl-api-1")
    assert match["credit_limit"] == 30000.0

    # GET /accounts/{account_id} is matched by the synced external_id (bare form).
    r2 = client.get("/api/open-finance/accounts/cl-api-1", headers=owner["headers"])
    assert r2.status_code == 200, r2.text
    assert r2.json()["credit_limit"] == 30000.0


def test_accounts_route_credit_limit_null_when_unknown(client, owner):
    org_id = owner["user"]["organization_id"]
    db = SessionLocal()
    try:
        db.add(Account(
            organization_id=org_id, name="Bank Hapoalim Savings",
            account_type=AccountType.ASSET, source="open_finance",
            external_id="open_finance:cl-api-2", balance=500, currency="ILS",
        ))
        db.commit()
    finally:
        db.close()

    r = client.get("/api/open-finance/accounts", headers=owner["headers"])
    assert r.status_code == 200, r.text
    body = r.json()
    match = next(a for a in body["items"] if a["external_id"] == "open_finance:cl-api-2")
    assert match["credit_limit"] is None


# --------------------------------------------------------------------- #
# dashboard: cash_by_account (per-account CHECKING breakdown) surfaces it too
# --------------------------------------------------------------------- #
def test_dashboard_cash_by_account_includes_credit_limit(fresh_org):
    from cfo.services.dashboard_service import DashboardService

    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        db.add(Account(
            organization_id=org_id, name='עו"ש', account_type=AccountType.BANK,
            balance=Decimal("1000"), source="open_finance",
            balance_as_of=datetime(2026, 7, 12), raw_account_type="CHECKING",
            credit_limit=Decimal("10000"),
        ))
        db.commit()

        overview = DashboardService(db, org_id).get_overview()
        entry = overview["cash_by_account"][0]
        assert entry["credit_limit"] == 10000.0
    finally:
        db.close()


def test_dashboard_cash_by_account_credit_limit_null_when_unknown(fresh_org):
    from cfo.services.dashboard_service import DashboardService

    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        db.add(Account(
            organization_id=org_id, name='עו"ש', account_type=AccountType.BANK,
            balance=Decimal("1000"), source="open_finance",
            balance_as_of=datetime(2026, 7, 12), raw_account_type="CHECKING",
        ))
        db.commit()

        overview = DashboardService(db, org_id).get_overview()
        entry = overview["cash_by_account"][0]
        assert entry["credit_limit"] is None
    finally:
        db.close()


# --------------------------------------------------------------------- #
# AI chat's account listing (bank_query_service.get_bank_position)
# --------------------------------------------------------------------- #
def test_bank_position_includes_credit_limit(fresh_org):
    from cfo.services.bank_query_service import get_bank_position

    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        db.add(Account(
            organization_id=org_id, name="Bank Leumi Checking",
            account_type=AccountType.BANK, source="open_finance",
            external_id="open_finance:bp-1", balance=1000, currency="ILS",
            credit_limit=Decimal("12000"),
        ))
        db.commit()

        result = get_bank_position(db, org_id)
        entry = next(a for a in result["accounts"] if a["external_id"] == "open_finance:bp-1")
        assert entry["credit_limit"] == 12000.0
    finally:
        db.close()


def test_bank_position_credit_limit_null_when_unknown(fresh_org):
    from cfo.services.bank_query_service import get_bank_position

    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        db.add(Account(
            organization_id=org_id, name="Bank Leumi Savings",
            account_type=AccountType.ASSET, source="open_finance",
            external_id="open_finance:bp-2", balance=500, currency="ILS",
        ))
        db.commit()

        result = get_bank_position(db, org_id)
        entry = next(a for a in result["accounts"] if a["external_id"] == "open_finance:bp-2")
        assert entry["credit_limit"] is None
    finally:
        db.close()
