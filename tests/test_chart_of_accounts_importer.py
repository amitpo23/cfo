"""Offline Hashavshevet chart-of-accounts ingestion.

The importer writes into the existing ``accounts`` data plane.  These tests
deliberately use a private SQLite database and never initialize a connector.
"""

from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from cfo.models import (
    Account,
    AccountImportChange,
    AccountType,
    Base,
    Organization,
)
from cfo.services.chart_of_accounts_importer import import_chart_of_accounts


SOURCE_FILE_HASH = (
    "b8898e662ad1236fa303c46d1277e085"
    "7e86e6c1b79f3660aa610c5fd4c21022"
)
OBSERVED_AT = datetime(2026, 7, 29, 12, 0, tzinfo=timezone.utc)
CSV_FIELDS = [
    "source_account_code",
    "account_name",
    "estimated_classification",
    "sort_code",
    "vat_key",
    "tax_id",
    "withholding_tax_percent",
    "withholding_tax_valid_until",
    "mdb_dumi_status",
    "mdb_source_confirmed",
]


@pytest.fixture
def db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'coa.db'}")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add_all(
        [
            Organization(id=5, name="עומר ועודד פורת בע״מ", tax_id="558402376"),
            Organization(id=6, name="ארגון בידוד"),
        ]
    )
    session.commit()
    try:
        yield session
    finally:
        session.close()


def _write_csv(path: Path, rows: list[dict]) -> Path:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return path


def _active_row(**overrides) -> dict:
    row = {
        "source_account_code": "210001",
        "account_name": "מע״מ תשומות",
        "estimated_classification": "מע״מ",
        "sort_code": "210",
        "vat_key": "13",
        "tax_id": "",
        "withholding_tax_percent": "",
        "withholding_tax_valid_until": "",
        "mdb_dumi_status": "0",
        "mdb_source_confirmed": "true",
    }
    row.update(overrides)
    return row


def _historic_row(**overrides) -> dict:
    row = {
        "source_account_code": "400065",
        "account_name": "גרר חמודי שעראוי",
        "estimated_classification": "ספק",
        "sort_code": "400",
        "vat_key": "",
        "tax_id": "055206213",
        "withholding_tax_percent": "",
        "withholding_tax_valid_until": "",
        "mdb_dumi_status": "3",
        "mdb_source_confirmed": "true",
    }
    row.update(overrides)
    return row


def test_first_import_creates_accounts_with_provenance_and_history(db, tmp_path):
    source = _write_csv(tmp_path / "accounts.csv", [_active_row(), _historic_row()])

    result = import_chart_of_accounts(
        db,
        organization_id=5,
        csv_path=source,
        source_file_hash=SOURCE_FILE_HASH,
        observed_at=OBSERVED_AT,
    )

    assert result.as_dict() == {
        "total": 2,
        "inserted": 2,
        "updated": 0,
        "unchanged": 0,
        "changes": [],
    }
    accounts = (
        db.query(Account)
        .filter(Account.organization_id == 5)
        .order_by(Account.source_account_code)
        .all()
    )
    assert [account.source_account_code for account in accounts] == ["210001", "400065"]

    vat_account, historic_account = accounts
    assert vat_account.source_name == "מע״מ תשומות"
    assert vat_account.source_classification == "מע״מ"
    assert vat_account.account_type == AccountType.OTHER
    assert vat_account.vat_key == "13"
    assert vat_account.is_active is True
    assert vat_account.is_historical is False
    assert vat_account.source == "hashavshevet_mdb"
    assert vat_account.external_id == "210001"
    assert vat_account.row_hash and len(vat_account.row_hash) == 64
    assert vat_account.source_file_hash == SOURCE_FILE_HASH
    assert vat_account.observed_at is not None
    assert vat_account.synced_at is not None
    assert vat_account.sumit_account_code is None
    assert vat_account.balance is None

    assert historic_account.account_type == AccountType.ACCOUNTS_PAYABLE
    assert historic_account.tax_id == "055206213"
    assert historic_account.is_active is False
    assert historic_account.is_historical is True


def test_second_import_is_idempotent(db, tmp_path):
    source = _write_csv(tmp_path / "accounts.csv", [_active_row(), _historic_row()])
    first = import_chart_of_accounts(
        db, 5, source, SOURCE_FILE_HASH, observed_at=OBSERVED_AT
    )
    before = {
        account.source_account_code: (account.row_hash, account.synced_at)
        for account in db.query(Account).filter(Account.organization_id == 5)
    }

    second = import_chart_of_accounts(
        db, 5, source, SOURCE_FILE_HASH, observed_at=OBSERVED_AT
    )
    after = {
        account.source_account_code: (account.row_hash, account.synced_at)
        for account in db.query(Account).filter(Account.organization_id == 5)
    }

    assert first.inserted == 2
    assert second.inserted == 0
    assert second.updated == 0
    assert second.unchanged == 2
    assert before == after
    assert db.query(AccountImportChange).count() == 0


def test_same_source_code_is_isolated_by_organization(db, tmp_path):
    source = _write_csv(tmp_path / "accounts.csv", [_active_row()])

    result_org5 = import_chart_of_accounts(
        db, 5, source, SOURCE_FILE_HASH, observed_at=OBSERVED_AT
    )
    result_org6 = import_chart_of_accounts(
        db, 6, source, SOURCE_FILE_HASH, observed_at=OBSERVED_AT
    )

    assert result_org5.inserted == 1
    assert result_org6.inserted == 1
    assert db.query(Account).filter(Account.organization_id == 5).count() == 1
    assert db.query(Account).filter(Account.organization_id == 6).count() == 1


def test_unique_constraint_rejects_duplicate_org_and_source_code(db):
    shared = dict(
        organization_id=5,
        name="כרטיס",
        source_name="כרטיס",
        source_account_code="400001",
        source_classification="ספק",
        account_type=AccountType.ACCOUNTS_PAYABLE,
        source="hashavshevet_mdb",
        external_id="400001",
        is_active=True,
        is_historical=False,
    )
    db.add(Account(**shared))
    db.commit()

    db.add(Account(**{**shared, "external_id": "different-external-id"}))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_name_and_vat_key_diff_updates_with_persistent_audit(db, tmp_path):
    original = _write_csv(tmp_path / "original.csv", [_active_row()])
    import_chart_of_accounts(
        db, 5, original, SOURCE_FILE_HASH, observed_at=OBSERVED_AT
    )
    account = db.query(Account).filter_by(
        organization_id=5, source_account_code="210001"
    ).one()
    account.sumit_account_code = "SUMIT-READBACK-LATER"
    db.commit()

    changed = _write_csv(
        tmp_path / "changed.csv",
        [_active_row(account_name="מע״מ תשומות מעודכן", vat_key="14")],
    )
    result = import_chart_of_accounts(
        db, 5, changed, SOURCE_FILE_HASH, observed_at=OBSERVED_AT
    )

    assert result.inserted == 0
    assert result.updated == 1
    assert result.unchanged == 0
    assert len(result.changes) == 1
    assert result.changes[0]["source_account_code"] == "210001"
    assert result.changes[0]["fields"] == {
        "source_name": {"old": "מע״מ תשומות", "new": "מע״מ תשומות מעודכן"},
        "vat_key": {"old": "13", "new": "14"},
    }

    db.refresh(account)
    assert account.source_name == "מע״מ תשומות מעודכן"
    assert account.name == "מע״מ תשומות מעודכן"
    assert account.vat_key == "14"
    # The offline importer must never erase a later SUMIT readback mapping.
    assert account.sumit_account_code == "SUMIT-READBACK-LATER"

    audit = db.query(AccountImportChange).one()
    assert audit.organization_id == 5
    assert audit.source_account_code == "210001"
    assert audit.changes == result.changes[0]["fields"]
    assert audit.source_file_hash == SOURCE_FILE_HASH

