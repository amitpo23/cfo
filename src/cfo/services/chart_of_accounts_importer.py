"""Offline, tenant-scoped import of a verified Hashavshevet account index."""

from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from sqlalchemy import null
from sqlalchemy.orm import Session

from ..models import (
    Account,
    AccountImportChange,
    AccountType,
    Organization,
)


SOURCE = "hashavshevet_mdb"
REQUIRED_COLUMNS = {
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
}

CLASSIFICATION_MAP = {
    "לקוח": AccountType.ACCOUNTS_RECEIVABLE,
    "ספק": AccountType.ACCOUNTS_PAYABLE,
    "בנק-קופה": AccountType.BANK,
    "הכנסה": AccountType.REVENUE,
    "הוצאה": AccountType.EXPENSE,
    "נכס": AccountType.ASSET,
    "הון": AccountType.EQUITY,
    # "מע״מ", "מוסדות" and "אחר" can be either debit or credit control
    # accounts.  Preserve the exact classification and do not guess direction.
    "מע\"מ": AccountType.OTHER,
    'מע"מ': AccountType.OTHER,
    "מע״מ": AccountType.OTHER,
    "מוסדות": AccountType.OTHER,
    "אחר": AccountType.OTHER,
}

SOURCE_FIELDS = (
    "source_name",
    "source_classification",
    "sort_code",
    "vat_key",
    "tax_id",
    "withholding_rate",
    "withholding_valid_until",
    "is_active",
    "is_historical",
    "source_status_code",
    "account_type",
)


class ImportValidationError(ValueError):
    """The CSV is not safe to ingest as MDB-confirmed source data."""


@dataclass
class ImportResult:
    total: int
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0
    changes: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "inserted": self.inserted,
            "updated": self.updated,
            "unchanged": self.unchanged,
            "changes": self.changes,
        }


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _decimal(value: str | None, field_name: str) -> Decimal | None:
    cleaned = _clean(value)
    if cleaned is None:
        return None
    try:
        return Decimal(cleaned)
    except InvalidOperation as exc:
        raise ImportValidationError(
            f"{field_name} is not a decimal: {cleaned!r}"
        ) from exc


def _date(value: str | None, field_name: str) -> date | None:
    cleaned = _clean(value)
    if cleaned is None:
        return None
    try:
        return date.fromisoformat(cleaned)
    except ValueError as exc:
        raise ImportValidationError(
            f"{field_name} is not an ISO date: {cleaned!r}"
        ) from exc


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, AccountType):
        return value.value
    return value


def _hash_payload(payload: dict[str, Any]) -> str:
    canonical = {
        key: _json_value(value)
        for key, value in sorted(payload.items())
    }
    encoded = json.dumps(
        canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validate_source_file_hash(value: str) -> str:
    cleaned = value.strip().lower()
    if len(cleaned) != 64:
        raise ImportValidationError("source_file_hash must be a SHA-256 hex digest")
    try:
        bytes.fromhex(cleaned)
    except ValueError as exc:
        raise ImportValidationError(
            "source_file_hash must be a SHA-256 hex digest"
        ) from exc
    return cleaned


def _parse_rows(csv_path: Path) -> list[dict[str, Any]]:
    with csv_path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        columns = set(reader.fieldnames or [])
        missing = sorted(REQUIRED_COLUMNS - columns)
        if missing:
            raise ImportValidationError(
                f"missing required CSV columns: {', '.join(missing)}"
            )
        raw_rows = list(reader)

    parsed: list[dict[str, Any]] = []
    seen_codes: set[str] = set()
    for line_number, row in enumerate(raw_rows, start=2):
        if (_clean(row.get("mdb_source_confirmed")) or "").lower() != "true":
            raise ImportValidationError(
                f"line {line_number}: mdb_source_confirmed must be true"
            )
        code = _clean(row.get("source_account_code"))
        if code is None:
            raise ImportValidationError(
                f"line {line_number}: source_account_code is required"
            )
        if code in seen_codes:
            raise ImportValidationError(
                f"line {line_number}: duplicate source_account_code {code!r}"
            )
        seen_codes.add(code)

        classification = _clean(row.get("estimated_classification"))
        account_type = CLASSIFICATION_MAP.get(classification or "", AccountType.OTHER)
        dumi_status = _clean(row.get("mdb_dumi_status"))
        if dumi_status not in {"0", "1", "3"}:
            raise ImportValidationError(
                f"line {line_number}: unsupported mdb_dumi_status {dumi_status!r}"
            )

        source_values = {
            "source_name": _clean(row.get("account_name")),
            "source_classification": classification,
            "sort_code": _clean(row.get("sort_code")),
            "vat_key": _clean(row.get("vat_key")),
            "tax_id": _clean(row.get("tax_id")),
            "withholding_rate": _decimal(
                row.get("withholding_tax_percent"), "withholding_tax_percent"
            ),
            "withholding_valid_until": _date(
                row.get("withholding_tax_valid_until"),
                "withholding_tax_valid_until",
            ),
            "is_active": dumi_status == "0",
            "is_historical": dumi_status == "3",
            "source_status_code": dumi_status,
            "account_type": account_type,
        }
        parsed.append(
            {
                "source_account_code": code,
                **source_values,
                "row_hash": _hash_payload(
                    {"source_account_code": code, **source_values}
                ),
            }
        )
    return parsed


def _field_changes(existing: Account, incoming: dict[str, Any]) -> dict[str, Any]:
    changes: dict[str, Any] = {}
    for field_name in SOURCE_FIELDS:
        old = getattr(existing, field_name)
        new = incoming[field_name]
        if old != new:
            changes[field_name] = {
                "old": _json_value(old),
                "new": _json_value(new),
            }
    return changes


def import_chart_of_accounts(
    db: Session,
    organization_id: int,
    csv_path: str | Path,
    source_file_hash: str,
    *,
    observed_at: datetime | None = None,
) -> ImportResult:
    """Import one verified CSV atomically into the existing Account model.

    ``sumit_account_code`` is intentionally never assigned here: only the
    separately authorized SUMIT readback may populate it.
    """

    path = Path(csv_path)
    if not path.is_file():
        raise ImportValidationError(f"CSV does not exist: {path}")
    digest = _validate_source_file_hash(source_file_hash)
    rows = _parse_rows(path)
    observed = observed_at or datetime.fromtimestamp(
        path.stat().st_mtime, tz=timezone.utc
    )
    synced = datetime.now(timezone.utc)

    if db.query(Organization.id).filter(Organization.id == organization_id).first() is None:
        raise ImportValidationError(f"organization_id={organization_id} does not exist")

    existing_by_code = {
        account.source_account_code: account
        for account in db.query(Account).filter(
            Account.organization_id == organization_id,
            Account.source_account_code.in_(
                [row["source_account_code"] for row in rows]
            ),
        )
    }
    result = ImportResult(total=len(rows))

    try:
        for incoming in rows:
            code = incoming["source_account_code"]
            existing = existing_by_code.get(code)
            display_name = incoming["source_name"] or code

            if existing is None:
                account = Account(
                    organization_id=organization_id,
                    name=display_name,
                    external_id=code,
                    source=SOURCE,
                    # Account.balance has a legacy Python default of zero.
                    # This index-only import has no balance observation, so
                    # force SQL NULL instead of fabricating ₪0.00.
                    balance=null(),
                    currency="ILS",
                    source_account_code=code,
                    source_file_hash=digest,
                    observed_at=observed,
                    synced_at=synced,
                    row_hash=incoming["row_hash"],
                    **{key: incoming[key] for key in SOURCE_FIELDS},
                )
                db.add(account)
                existing_by_code[code] = account
                result.inserted += 1
                continue

            if existing.row_hash == incoming["row_hash"]:
                result.unchanged += 1
                continue

            changes = _field_changes(existing, incoming)
            old_row_hash = existing.row_hash
            existing.name = display_name
            existing.external_id = code
            existing.source = SOURCE
            for field_name in SOURCE_FIELDS:
                setattr(existing, field_name, incoming[field_name])
            existing.row_hash = incoming["row_hash"]
            existing.source_file_hash = digest
            existing.observed_at = observed
            existing.synced_at = synced
            db.flush()

            audit = AccountImportChange(
                organization_id=organization_id,
                account_id=existing.id,
                source_account_code=code,
                source_file_hash=digest,
                old_row_hash=old_row_hash,
                new_row_hash=incoming["row_hash"],
                changes=changes,
                changed_at=synced,
            )
            db.add(audit)
            result.updated += 1
            result.changes.append(
                {"source_account_code": code, "fields": changes}
            )

        db.commit()
    except Exception:
        db.rollback()
        raise

    return result
