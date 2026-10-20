"""Bind an existing Open Finance consent without calling the provider.

The nightly gated sync is the only path that may fetch transactions. This
module writes the local connection, the coverage boundary, and the
fingerprint links. It does not build a connector, create an onboarding
checklist, or set a consent URL.
"""
from __future__ import annotations

import hashlib
from datetime import date
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.attributes import flag_modified

from ..models import (
    Account,
    AccountSourceCoverage,
    Alert,
    AlertSeverity,
    AlertStatus,
    AuditLog,
    BankConnection,
    BankTransaction,
    IntegrationConnection,
    OnboardingTask,
    Organization,
    SumitCompany,
    SyncCheckpoint,
    SyncRun,
)
from .credentials_vault import decrypt_credentials, encrypt_credentials

LOCAL_SOURCE = "reviewed_local_import"
HYBRID_MODE = "hybrid"
IMPORT_ONLY_MODE = "import_only"
SYNCABLE_STATUSES = frozenset({"ACTIVE", "CONNECTED", "COMPLETED"})


class OpenFinanceBindError(ValueError):
    """The bind was refused before any provider call."""


def content_fingerprint(tx_date: date, amount, description) -> str:
    """Identity of a movement that does not include the account id.

    The reviewed local account and the provider account are different rows
    for the same bank suffix, so the account id must not be part of the key.
    """
    quantized = Decimal(str(amount)).quantize(Decimal("0.01"))
    text = " ".join(str(description or "").casefold().split())
    raw = f"{tx_date.isoformat()}|{format(quantized, 'f')}|{text}"
    return hashlib.sha256(raw.encode()).hexdigest()


def bind_existing_connection(
    db,
    org_id: int,
    *,
    connection_id: str,
    status: str,
    actor_id: int | None = None,
    bank_name: str | None = None,
    provider_id: str | None = None,
    coverage: dict | None = None,
) -> dict:
    """Attach a provider connection id that already exists outside Rezef.

    Idempotent for the same organization. A connection id already stored for
    another organization is refused. No network, no onboarding task, no
    connect URL, and no sync checkpoint.
    """
    org = db.get(Organization, org_id)
    if org is None or not org.is_active:
        raise OpenFinanceBindError("Active organization required")
    connection_id = str(connection_id or "").strip()
    if not connection_id or len(connection_id) > 255 or any(ch.isspace() for ch in connection_id):
        raise OpenFinanceBindError("Provider connection id required")
    status = str(status or "").strip().upper()
    if status not in SYNCABLE_STATUSES:
        raise OpenFinanceBindError("Connection status must be ACTIVE, CONNECTED, or COMPLETED")

    tasks_before = db.query(OnboardingTask).filter_by(organization_id=org_id).count()
    runs_before = db.query(SyncRun).filter_by(organization_id=org_id, source="open_finance").count()
    checkpoints_before = db.query(SyncCheckpoint).filter_by(
        organization_id=org_id, source="open_finance",
    ).count()

    try:
        existing = (
            db.query(BankConnection)
            .filter(
                BankConnection.source == "open_finance",
                BankConnection.connection_id == connection_id,
            )
            .all()
        )
        other = [row for row in existing if row.organization_id != org_id]
        if other:
            raise OpenFinanceBindError("Open Finance connection is already attached to another organization")
        _refuse_second_active_open_finance(db, org_id, connection_id)
        row = existing[0] if existing else None
        created = row is None
        if row is None:
            _refuse_conflicting_provider(db, org)
            row = BankConnection(
                organization_id=org_id,
                source="open_finance",
                connection_id=connection_id,
                status=status,
                connect_url=None,
            )
            db.add(row)
        else:
            row.status = status
        if bank_name:
            row.bank_name = bank_name
        if provider_id:
            row.provider_id = provider_id
        db.flush()

        integration = _ensure_integration(db, org, connection_id)
        _mark_hybrid_if_import_only(db, org)
        coverage_out = None
        if coverage is not None:
            coverage_out = _record_coverage(db, org_id, coverage)
        if created or coverage_out is not None:
            db.add(AuditLog(
                user_id=actor_id,
                organization_id=org_id,
                action="BIND_OPEN_FINANCE_CONNECTION",
                entity_type="BankConnection",
                entity_id=row.id,
                details={
                    "connection_id": connection_id,
                    "status": status,
                    "provider_calls": 0,
                    "kickoff_sync": False,
                    "connect_url_set": False,
                    "coverage": coverage_out,
                },
            ))
        db.commit()
    except OpenFinanceBindError:
        db.rollback()
        raise
    except IntegrityError as exc:
        db.rollback()
        detail = str(getattr(exc, "orig", exc))
        if "uq_bankconn_one_active_open_finance" in detail:
            raise OpenFinanceBindError(
                "Organization already has an active Open Finance connection"
            ) from exc
        raise OpenFinanceBindError(
            "Open Finance connection is already attached to another organization"
        ) from exc
    except Exception:
        db.rollback()
        raise

    db.refresh(row)
    tasks_after = db.query(OnboardingTask).filter_by(organization_id=org_id).count()
    runs_after = db.query(SyncRun).filter_by(organization_id=org_id, source="open_finance").count()
    checkpoints_after = db.query(SyncCheckpoint).filter_by(
        organization_id=org_id, source="open_finance",
    ).count()
    if tasks_after != tasks_before or runs_after != runs_before or checkpoints_after != checkpoints_before:
        raise OpenFinanceBindError("Bind changed onboarding or sync state")
    return {
        "organization_id": org_id,
        "connection_id": connection_id,
        "bank_connection_id": row.id,
        "integration_connection_id": integration.id,
        "status": row.status,
        "connect_url": row.connect_url,
        "created": created,
        "kickoff_sync": False,
        "provider_calls": 0,
        "onboarding_tasks_created": 0,
        "mode": (org.settings or {}).get("mode"),
        "coverage": coverage_out,
    }


def _digit_tail(value) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def attach_provider_account(db, account: Account) -> None:
    """Point a coverage row at the provider account with the same bank suffix.

    The match is the digit tail, so ``local-bank:1662`` and a provider
    number such as ``12-1662`` both resolve to the suffix ``1662``.
    """
    number = _digit_tail(account.provider_account_number)
    if account.source != "open_finance" or not number:
        return
    if account.id is None:
        db.flush()
    rows = (
        db.query(AccountSourceCoverage)
        .filter(
            AccountSourceCoverage.organization_id == account.organization_id,
            AccountSourceCoverage.superseded_by_account_id.is_(None),
        )
        .all()
    )
    for row in rows:
        suffix = _digit_tail(row.bank_account_suffix)
        if suffix and number.endswith(suffix):
            row.superseded_by_account_id = account.id


def link_coverage_overlap(db, org_id: int) -> dict:
    """Pair overlap rows by fingerprint. Neither side is deleted.

    Provider rows before ``covers_from`` point at the local row. Local rows
    on or after ``covers_from`` point at the provider row. Matching is
    one-to-one inside each side of the boundary.
    """
    matched = 0
    coverages = db.query(AccountSourceCoverage).filter_by(organization_id=org_id).all()
    for cov in coverages:
        local_rows = (
            db.query(BankTransaction)
            .filter(
                BankTransaction.organization_id == org_id,
                BankTransaction.account_id == cov.local_account_id,
                BankTransaction.source == LOCAL_SOURCE,
            )
            .all()
        )
        provider_rows = []
        if cov.superseded_by_account_id is not None:
            provider_rows = (
                db.query(BankTransaction)
                .filter(
                    BankTransaction.organization_id == org_id,
                    BankTransaction.account_id == cov.superseded_by_account_id,
                    BankTransaction.source == "open_finance",
                )
                .all()
            )
        matched += _pair(
            [row for row in provider_rows if row.transaction_date < cov.covers_from],
            [row for row in local_rows if row.transaction_date < cov.covers_from],
        )
        matched += _pair(
            [row for row in local_rows if row.transaction_date >= cov.covers_from],
            [row for row in provider_rows if row.transaction_date >= cov.covers_from],
        )
    return {"matched": matched}


def cashflow_selection(db, org_id: int, start: date, end: date):
    """Rows that may be summed, plus an honest overlap report.

    A missing coverage row leaves every row in the window unchanged. NULL
    source is not treated as a reviewed import.
    """
    rows = (
        db.query(BankTransaction)
        .filter(
            BankTransaction.organization_id == org_id,
            BankTransaction.transaction_date >= start,
            BankTransaction.transaction_date <= end,
        )
        .all()
    )
    coverages = db.query(AccountSourceCoverage).filter_by(organization_id=org_id).all()
    if not coverages:
        return [(row.transaction_date, row.amount) for row in rows], None

    by_local = {cov.local_account_id: cov for cov in coverages}
    by_provider = {
        cov.superseded_by_account_id: cov
        for cov in coverages
        if cov.superseded_by_account_id is not None
    }
    unattached = [cov for cov in coverages if cov.superseded_by_account_id is None]
    if unattached:
        _alert_unattached_provider(db, org_id)
    visible = []
    excluded = matched = unmatched = 0
    for row in rows:
        keep, overlap = _keep_row(row, by_local, by_provider, unattached)
        if keep:
            visible.append((row.transaction_date, row.amount))
            continue
        if not overlap:
            visible.append((row.transaction_date, row.amount))
            continue
        excluded += 1
        if row.superseded_by_id is not None:
            matched += 1
        else:
            unmatched += 1
    note = {
        "excluded_count": excluded,
        "matched_count": matched,
        "unmatched_count": unmatched,
        "provider_account_linked": not unattached,
        "message": _coverage_message(excluded, unmatched, bool(unattached)),
    }
    return visible, note


def _coverage_message(excluded: int, unmatched: int, unattached: bool) -> str | None:
    """Explain exclusion by the coverage date. A zero unmatched count is not a gate."""
    parts = []
    if unattached:
        parts.append(
            "חשבון הבנק של הספק אינו מקושר לשורת הכיסוי, "
            "ולכן תנועות הבנק שלפני תחילת הכיסוי לא נספרו."
        )
    if excluded:
        parts.append(
            f"{excluded} תנועות לא נכנסו לסכום כי התאריך שלהן שייך למקור האחר."
        )
    if unmatched:
        parts.append(
            f"{unmatched} תנועות בחלון החפיפה לא הותאמו לתנועה במקור האחר; "
            "ההחרגה אינה תלויה במספר הזה."
        )
    return " ".join(parts) if parts else None


def _alert_unattached_provider(db, org_id: int) -> None:
    """One active alert when a coverage row has no provider account. Flush only."""
    existing = (
        db.query(Alert)
        .filter(
            Alert.organization_id == org_id,
            Alert.alert_type == "coverage_provider_unattached",
            Alert.status == AlertStatus.ACTIVE,
        )
        .first()
    )
    if existing is not None:
        return
    db.add(Alert(
        organization_id=org_id,
        alert_type="coverage_provider_unattached",
        severity=AlertSeverity.WARNING,
        title="חשבון הבנק אינו מקושר לכיסוי",
        message="קיימת שורת כיסוי בלי חשבון ספק. תנועות הבנק שלפני תחילת הכיסוי לא נספרו.",
        status=AlertStatus.ACTIVE,
        meta={"reason": "coverage_without_provider_account"},
    ))
    db.flush()


def _keep_row(row, by_local, by_provider, unattached) -> tuple[bool, bool]:
    """Return (include_in_sum, is_coverage_overlap)."""
    if row.superseded_by_id is not None:
        return False, True
    source = row.source
    if source == LOCAL_SOURCE:
        cov = by_local.get(row.account_id)
        if cov is not None and row.transaction_date >= cov.covers_from:
            return False, True
        return True, False
    if source == "open_finance":
        cov = by_provider.get(row.account_id)
        if cov is not None and row.transaction_date < cov.covers_from:
            return False, True
        # No provider account on the coverage row: the feed cannot be
        # attributed, so every provider row before the boundary stays out.
        if cov is None and unattached and any(
            row.transaction_date < item.covers_from for item in unattached
        ):
            return False, True
        return True, False
    return True, False


def _pair(duplicates, survivors) -> int:
    consumed: set[int] = set()
    fingerprints = {}
    for row in survivors:
        if row.superseded_by_id is not None:
            continue
        fingerprints.setdefault(_fingerprint_of(row), []).append(row)
    matched = 0
    for row in duplicates:
        if row.superseded_by_id is not None:
            continue
        bucket = fingerprints.get(_fingerprint_of(row)) or []
        survivor = next((item for item in bucket if item.id not in consumed), None)
        if survivor is None:
            continue
        consumed.add(survivor.id)
        row.superseded_by_id = survivor.id
        if row.content_fingerprint is None:
            row.content_fingerprint = _fingerprint_of(row)
        matched += 1
    return matched


def _fingerprint_of(row: BankTransaction) -> str:
    if row.content_fingerprint:
        return row.content_fingerprint
    digest = content_fingerprint(row.transaction_date, row.amount, row.description)
    row.content_fingerprint = digest
    return digest


def _refuse_second_active_open_finance(db, org_id: int, connection_id: str) -> None:
    """One live Open Finance consent per organization."""
    rows = (
        db.query(BankConnection)
        .filter(
            BankConnection.organization_id == org_id,
            BankConnection.source == "open_finance",
            BankConnection.status.in_(tuple(SYNCABLE_STATUSES)),
        )
        .all()
    )
    if any(row.connection_id != connection_id for row in rows):
        raise OpenFinanceBindError(
            "Organization already has an active Open Finance connection"
        )


def _refuse_conflicting_provider(db, org: Organization) -> None:
    settings = org.settings or {}
    restricted = (
        settings.get("provider_calls_allowed") is False
        or settings.get("mode") in {IMPORT_ONLY_MODE, HYBRID_MODE}
    )
    if not restricted:
        return
    active = (
        db.query(IntegrationConnection)
        .filter_by(organization_id=org.id, status="active")
        .all()
    )
    if any(conn.source != "open_finance" for conn in active):
        raise OpenFinanceBindError(
            "Hybrid organizations cannot keep another active provider connection"
        )
    if len([conn for conn in active if conn.source == "open_finance"]) > 1:
        raise OpenFinanceBindError(
            "Hybrid organizations require exactly one active Open Finance connection"
        )


def _ensure_integration(db, org: Organization, connection_id: str) -> IntegrationConnection:
    conn = (
        db.query(IntegrationConnection)
        .filter_by(organization_id=org.id, source="open_finance")
        .first()
    )
    if conn is None:
        conn = IntegrationConnection(
            organization_id=org.id,
            source="open_finance",
            status="active",
            credentials_encrypted=encrypt_credentials({
                "connection_id": connection_id,
                "of_connection_ids": [connection_id],
            }),
            config={"kickoff_sync": False},
        )
        db.add(conn)
        db.flush()
        return conn
    _refuse_conflicting_provider(db, org)
    creds = decrypt_credentials(conn.credentials_encrypted) or {}
    creds["connection_id"] = connection_id
    ids = list(creds.get("of_connection_ids") or [])
    if connection_id not in ids:
        ids.append(connection_id)
    creds["of_connection_ids"] = ids
    conn.credentials_encrypted = encrypt_credentials(creds)
    conn.status = "active"
    config = dict(conn.config or {})
    config["kickoff_sync"] = False
    conn.config = config
    flag_modified(conn, "config")
    db.flush()
    return conn


def _mark_hybrid_if_import_only(db, org: Organization) -> None:
    settings = dict(org.settings or {})
    if settings.get("provider_calls_allowed") is not False and settings.get("mode") != IMPORT_ONLY_MODE:
        return
    settings["mode"] = HYBRID_MODE
    settings["provider_calls_allowed"] = False
    org.settings = settings
    flag_modified(org, "settings")
    roster = (
        db.query(SumitCompany)
        .filter_by(target_organization_id=org.id)
        .all()
    )
    for row in roster:
        raw = dict(row.raw_data or {})
        if raw.get("mode") == IMPORT_ONLY_MODE:
            raw["mode"] = HYBRID_MODE
            raw["automation"] = {"state": "disabled", "reason": HYBRID_MODE}
            row.raw_data = raw
            flag_modified(row, "raw_data")


def _record_coverage(db, org_id: int, coverage: dict) -> dict:
    local_account_id = coverage.get("local_account_id")
    covers_from = coverage.get("covers_from")
    suffix = coverage.get("bank_account_suffix")
    if not isinstance(covers_from, date):
        raise OpenFinanceBindError("Coverage requires a covers_from date")
    account = db.get(Account, local_account_id)
    if account is None or account.organization_id != org_id:
        raise OpenFinanceBindError("Coverage account is not in this organization")
    if account.source != LOCAL_SOURCE:
        raise OpenFinanceBindError("Coverage boundary applies to a reviewed local import")
    last_local = (
        db.query(func.max(BankTransaction.transaction_date))
        .filter(
            BankTransaction.organization_id == org_id,
            BankTransaction.account_id == account.id,
            BankTransaction.source == LOCAL_SOURCE,
        )
        .scalar()
    )
    if last_local is not None and covers_from <= last_local:
        raise OpenFinanceBindError(
            "covers_from must be after the last reviewed local transaction"
        )
    if suffix is not None:
        suffix = str(suffix)
        if account.external_id and not str(account.external_id).endswith(suffix):
            raise OpenFinanceBindError("Coverage suffix does not match the local account")
    row = (
        db.query(AccountSourceCoverage)
        .filter_by(organization_id=org_id, local_account_id=account.id, source=LOCAL_SOURCE)
        .first()
    )
    if row is None:
        row = AccountSourceCoverage(
            organization_id=org_id,
            local_account_id=account.id,
            source=LOCAL_SOURCE,
            covers_from=covers_from,
            bank_account_suffix=suffix,
        )
        db.add(row)
    elif row.covers_from != covers_from or (suffix and row.bank_account_suffix not in (None, suffix)):
        raise OpenFinanceBindError("Coverage boundary already recorded with a different date")
    elif suffix and row.bank_account_suffix is None:
        row.bank_account_suffix = suffix
    db.flush()
    return {
        "local_account_id": account.id,
        "covers_from": covers_from.isoformat(),
        "bank_account_suffix": row.bank_account_suffix,
    }
