"""Bind an existing Open Finance consent without calling the provider.

The nightly gated sync is the only path that may fetch transactions. This
module writes the local connection, the coverage boundary, and the
fingerprint links. It does not build a connector, create an onboarding
checklist, or set a consent URL.
"""
from __future__ import annotations

import hashlib
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.attributes import flag_modified

from ..models import (
    Account,
    AccountSourceCoverage,
    Alert,
    OfAccountClassification,
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
    User,
)
from .credentials_vault import decrypt_credentials, encrypt_credentials

LOCAL_SOURCE = "reviewed_local_import"
HYBRID_MODE = "hybrid"
IMPORT_ONLY_MODE = "import_only"
SYNCABLE_STATUSES = frozenset({"ACTIVE", "CONNECTED", "COMPLETED"})
STATE_BOUND = "BOUND"
STATE_INDEPENDENT = "INDEPENDENT"
STATE_UNCLASSIFIED = "UNCLASSIFIED"
REASON_BEFORE_COVERAGE = "before covers_from"
REASON_DUPLICATE = "duplicate"
ALERT_WITHHELD = "coverage_accounts_withheld"
ALERT_UNATTACHED = "coverage_provider_unattached"
ALERT_REASONS = frozenset({STATE_UNCLASSIFIED, REASON_DUPLICATE, STATE_INDEPENDENT})
_REASON_HEBREW = {
    STATE_UNCLASSIFIED: "לא מסווג",
    REASON_BEFORE_COVERAGE: "לפני תחילת כיסוי",
    REASON_DUPLICATE: "כפול",
    STATE_INDEPENDENT: "עצמאי",
}
_PUBLIC_LINE_KEYS = (
    "label",
    "masked_number",
    "reason",
    "net_amount",
    "inflow_amount",
    "outflow_amount",
    "keeper_mask",
    "classified_on",
)
# /d/ is public: an INDEPENDENT decision is attributed to the office, never to a staff member.
PUBLIC_ACTOR_LABEL = "משרד הנהלת החשבונות"


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
        suggest_account_states(db, org_id)
        record_unattached_coverage_alert(db, org_id)
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


def _four_digit_suffix(value) -> str:
    token = _digit_tail(value)
    if len(token) == 4 and str(value).strip() == token:
        return token
    return ""


def attach_provider_account(db, account: Account) -> None:
    """Suggest BOUND when this account is the one unambiguous suffix match.

    The suggestion is the digit tail ending in exactly one coverage suffix,
    and exactly one Open Finance account ending in that suffix. Anything else
    stays UNCLASSIFIED. Callers commit. This does not write INDEPENDENT.
    """
    if account.source != "open_finance":
        return
    if account.id is None:
        db.flush()
    snaps = _bound_snapshots(db, account.organization_id)
    suggest_account_states(db, account.organization_id)
    _carry_bound_to_live_row(db, account.organization_id, None, snaps)
    record_unattached_coverage_alert(db, account.organization_id)


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


def _org_has_reviewed_local_import(db, org_id: int) -> bool:
    account = (
        db.query(Account.id)
        .filter(Account.organization_id == org_id, Account.source == LOCAL_SOURCE)
        .first()
    )
    if account is not None:
        return True
    return (
        db.query(BankTransaction.id)
        .filter(
            BankTransaction.organization_id == org_id,
            BankTransaction.source == LOCAL_SOURCE,
        )
        .first()
    ) is not None


def _latest_local_end(db, org_id: int):
    """Last reviewed local movement in the org, including banks with no coverage."""
    return (
        db.query(func.max(BankTransaction.transaction_date))
        .filter(
            BankTransaction.organization_id == org_id,
            BankTransaction.source == LOCAL_SOURCE,
        )
        .scalar()
    )


def _masked_number(account: Account | None) -> str:
    """Last four digits for display. The name is display-only, never a match key."""
    if account is None:
        return "••••"
    digits = _digit_tail(account.provider_account_number)
    if len(digits) >= 4:
        return "••••" + digits[-4:]
    name_digits = _digit_tail(account.name)
    if len(name_digits) >= 4:
        return "••••" + name_digits[-4:]
    return "••••"


def _flush_session(db) -> None:
    """Flush unless a hook called us from inside a flush.

    ``commit`` flushes again when ``after_flush`` left new alert rows, so
    skipping here avoids ``Session is already flushing``.
    """
    if getattr(db, "_flushing", False):
        return
    db.flush()


def _money(value: Decimal) -> float:
    return float(Decimal(value).quantize(Decimal("0.01")))


def _add_amount(bucket: dict, amount: Decimal) -> None:
    bucket["net"] += amount
    if amount > 0:
        bucket["inflow"] += amount
    elif amount < 0:
        bucket["outflow"] += -amount


def _actor_name(user: User | None) -> str:
    if user is None:
        return "משרד"
    name = (user.full_name or "").strip()
    if name:
        return name
    return (user.email or "").strip() or "משרד"


def _blocked_suffixes(db, org_id: int) -> set[str]:
    """Coverage suffixes and reviewed local ``local-bank:NNNN`` suffixes."""
    suffixes: set[str] = set()
    for cov in db.query(AccountSourceCoverage).filter_by(organization_id=org_id).all():
        token = _four_digit_suffix(cov.bank_account_suffix)
        if token:
            suffixes.add(token)
    for account in db.query(Account).filter(
        Account.organization_id == org_id, Account.source == LOCAL_SOURCE,
    ).all():
        external = account.external_id or ""
        token = external.split(":", 1)[1] if external.startswith("local-bank:") else ""
        digits = _digit_tail(token)
        if len(digits) >= 4:
            suffixes.add(digits[-4:])
    return suffixes


def _digits_end_with_blocked_suffix(db, org_id: int, account: Account) -> bool:
    digits = _digit_tail(account.provider_account_number)
    if not digits:
        return False
    return any(suffix and digits.endswith(suffix) for suffix in _blocked_suffixes(db, org_id))


def _coverage_unique_violation(exc: IntegrityError) -> bool:
    message = str(getattr(exc, "orig", exc)).lower()
    return "uq_of_class_coverage" in message or "of_account_classifications.coverage_id" in message


def _live_connection_ids(db, org_id: int, survivor_connection_id: str | None = None) -> set[str]:
    rows = (
        db.query(BankConnection.connection_id, BankConnection.status)
        .filter(
            BankConnection.organization_id == org_id,
            BankConnection.source == "open_finance",
        )
        .all()
    )
    live = {cid for cid, status in rows if cid and status in SYNCABLE_STATUSES}
    if survivor_connection_id:
        live.add(survivor_connection_id)
    return live


def _connection_statuses(db, org_id: int) -> dict[str, str]:
    rows = (
        db.query(BankConnection.connection_id, BankConnection.status)
        .filter(
            BankConnection.organization_id == org_id,
            BankConnection.source == "open_finance",
        )
        .all()
    )
    return {cid: status for cid, status in rows if cid}


def _of_accounts(db, org_id: int) -> list[Account]:
    return (
        db.query(Account)
        .filter(Account.organization_id == org_id, Account.source == "open_finance")
        .all()
    )


def _digit_groups(accounts: list[Account]) -> dict[str, list[Account]]:
    """Group numbered accounts. Empty digit strings are not a group."""
    groups: dict[str, list[Account]] = {}
    for account in accounts:
        digits = _digit_tail(account.provider_account_number)
        if not digits:
            continue
        groups.setdefault(digits, []).append(account)
    return groups


def _bound_snapshots(db, org_id: int) -> list[dict]:
    accounts = {row.id: row for row in _of_accounts(db, org_id)}
    snaps = []
    rows = (
        db.query(OfAccountClassification)
        .filter_by(organization_id=org_id, state=STATE_BOUND)
        .all()
    )
    for row in rows:
        account = accounts.get(row.account_id)
        snaps.append({
            "account_id": row.account_id,
            "digits": _digit_tail(account.provider_account_number) if account is not None else "",
            "coverage_id": row.coverage_id,
            "classified_by_user_id": row.classified_by_user_id,
            "classified_at": row.classified_at,
        })
    return snaps


def _carry_bound_to_live_row(db, org_id: int, survivor_connection_id: str | None, snaps: list[dict]) -> None:
    """Move BOUND onto the single live-consent row that shares the digit string.

    The donor row is deleted in this same transaction so the coverage unique
    index still holds. An admin decision already on the target is left as written
    when it is a different coverage.
    """
    if not snaps:
        return
    live_ids = _live_connection_ids(db, org_id, survivor_connection_id)
    if not live_ids:
        return
    groups = _digit_groups(_of_accounts(db, org_id))
    classes = {
        row.account_id: row
        for row in db.query(OfAccountClassification).filter_by(organization_id=org_id).all()
    }
    for snap in snaps:
        digits = snap["digits"]
        if not digits or snap["coverage_id"] is None:
            continue
        live_rows = [
            account for account in groups.get(digits, [])
            if account.open_finance_connection_id and account.open_finance_connection_id in live_ids
        ]
        if len(live_rows) != 1:
            continue
        target = live_rows[0]
        if target.id == snap["account_id"]:
            continue
        existing = classes.get(target.id)
        if (
            existing is not None
            and existing.classified_by_user_id is not None
            and not (existing.state == STATE_BOUND and existing.coverage_id == snap["coverage_id"])
        ):
            continue
        holders = [
            row for row in list(classes.values())
            if row.state == STATE_BOUND and row.coverage_id == snap["coverage_id"]
        ]
        for row in holders:
            db.delete(row)
            classes.pop(row.account_id, None)
        if existing is not None and existing.account_id in classes:
            db.delete(existing)
            classes.pop(target.id, None)
        _flush_session(db)
        moved = OfAccountClassification(
            organization_id=org_id,
            account_id=target.id,
            state=STATE_BOUND,
            coverage_id=snap["coverage_id"],
            classified_by_user_id=snap["classified_by_user_id"],
            classified_at=snap["classified_at"],
        )
        db.add(moved)
        _flush_session(db)
        classes[target.id] = moved
    _sync_coverage_pointers(db, org_id)


def _duplicate_index(db, org_id: int, classes: dict) -> dict[int, dict]:
    """One keeper per digit group. Prefer the ACTIVE consent, then BOUND, then newest."""
    statuses = _connection_statuses(db, org_id)
    index: dict[int, dict] = {}
    for group in _digit_groups(_of_accounts(db, org_id)).values():
        if len(group) < 2:
            continue

        def rank(account: Account):
            status = statuses.get(account.open_finance_connection_id or "")
            live = 2 if status == "ACTIVE" else 1 if status in SYNCABLE_STATUSES else 0
            klass = classes.get(account.id)
            bound = 1 if klass is not None and klass.state == STATE_BOUND else 0
            return (live, bound, account.id or 0)

        keeper = max(group, key=rank)
        mask = _masked_number(keeper)
        for account in group:
            index[account.id] = {
                "duplicate": account.id != keeper.id,
                "keeper_mask": mask,
            }
    return index


def suggest_account_states(db, org_id: int) -> None:
    """Auto-bind the one Open Finance account that ends with one coverage suffix.

    Admin classifications (``classified_by_user_id`` set) are left as written.
    A second account with the same ending removes the automatic bind. This
    never writes ``INDEPENDENT``.
    """
    if not _org_has_reviewed_local_import(db, org_id):
        return
    coverages = db.query(AccountSourceCoverage).filter_by(organization_id=org_id).all()
    by_suffix: dict[str, list] = {}
    for cov in coverages:
        suffix = _four_digit_suffix(cov.bank_account_suffix)
        if suffix:
            by_suffix.setdefault(suffix, []).append(cov)
    accounts = (
        db.query(Account)
        .filter(Account.organization_id == org_id, Account.source == "open_finance")
        .all()
    )
    classes = {
        row.account_id: row
        for row in db.query(OfAccountClassification).filter_by(organization_id=org_id).all()
    }
    ending: dict[str, list[Account]] = {suffix: [] for suffix in by_suffix}
    for account in accounts:
        digits = _digit_tail(account.provider_account_number)
        if not digits:
            continue
        for suffix in by_suffix:
            if digits.endswith(suffix):
                ending[suffix].append(account)
    chosen: dict[int, AccountSourceCoverage] = {}
    for suffix, owners in ending.items():
        covs = by_suffix[suffix]
        if len(covs) != 1 or len(owners) != 1:
            continue
        account = owners[0]
        existing = classes.get(account.id)
        if existing is not None and existing.classified_by_user_id is not None:
            continue
        chosen[account.id] = covs[0]
    taken = {
        row.coverage_id: row.account_id
        for row in classes.values()
        if row.state == STATE_BOUND and row.coverage_id is not None
    }
    chosen = {
        account_id: cov
        for account_id, cov in chosen.items()
        if taken.get(cov.id) in (None, account_id)
    }
    for account in accounts:
        existing = classes.get(account.id)
        if existing is not None and existing.classified_by_user_id is not None:
            continue
        target = chosen.get(account.id)
        if target is None:
            if existing is not None:
                db.delete(existing)
            continue
        if existing is None:
            db.add(OfAccountClassification(
                organization_id=org_id,
                account_id=account.id,
                state=STATE_BOUND,
                coverage_id=target.id,
            ))
        else:
            existing.state = STATE_BOUND
            existing.coverage_id = target.id
    db.flush()
    _sync_coverage_pointers(db, org_id)


def _sync_coverage_pointers(db, org_id: int) -> None:
    """Point each coverage at its single BOUND account, preferring an admin bind."""
    coverages = db.query(AccountSourceCoverage).filter_by(organization_id=org_id).all()
    bound = (
        db.query(OfAccountClassification)
        .filter(
            OfAccountClassification.organization_id == org_id,
            OfAccountClassification.state == STATE_BOUND,
        )
        .all()
    )
    for cov in coverages:
        owners = [row for row in bound if row.coverage_id == cov.id]
        admin = [row for row in owners if row.classified_by_user_id is not None]
        owner_ids = {row.account_id for row in owners}
        if len(admin) == 1:
            cov.superseded_by_account_id = admin[0].account_id
        elif len(owners) == 1:
            cov.superseded_by_account_id = owners[0].account_id
        elif cov.superseded_by_account_id not in owner_ids:
            cov.superseded_by_account_id = None
    db.flush()


def classify_open_finance_account(
    db, org_id: int, account_id: int, *, state: str, coverage_id: int | None, actor_id: int,
) -> dict:
    """Record an office-admin BOUND or INDEPENDENT decision and commit the audit row."""
    if actor_id is None:
        raise OpenFinanceBindError("An office admin must classify the account")
    if state not in (STATE_BOUND, STATE_INDEPENDENT):
        raise OpenFinanceBindError("State must be BOUND or INDEPENDENT")
    account = db.get(Account, account_id)
    if account is None or account.organization_id != org_id or account.source != "open_finance":
        raise OpenFinanceBindError("Open Finance account required")
    coverage = None
    if state == STATE_BOUND:
        coverage = db.get(AccountSourceCoverage, coverage_id) if coverage_id is not None else None
        if coverage is None or coverage.organization_id != org_id:
            raise OpenFinanceBindError("BOUND requires a coverage in this organization")
    elif coverage_id is not None:
        raise OpenFinanceBindError("INDEPENDENT does not take a coverage")
    if state == STATE_INDEPENDENT and _digits_end_with_blocked_suffix(db, org_id, account):
        raise OpenFinanceBindError(
            "INDEPENDENT is refused because this account number ends with a reviewed local import or coverage suffix"
        )
    if state == STATE_BOUND and coverage is not None:
        other = (
            db.query(OfAccountClassification)
            .filter(
                OfAccountClassification.coverage_id == coverage.id,
                OfAccountClassification.state == STATE_BOUND,
                OfAccountClassification.account_id != account.id,
            )
            .first()
        )
        if other is not None:
            raise OpenFinanceBindError("This coverage is already bound to an Open Finance account")
    try:
        row = db.query(OfAccountClassification).filter_by(account_id=account.id).first()
        now = datetime.utcnow()
        if row is None:
            row = OfAccountClassification(
                organization_id=org_id,
                account_id=account.id,
                state=state,
                coverage_id=coverage.id if coverage else None,
                classified_by_user_id=actor_id,
                classified_at=now,
            )
            db.add(row)
        else:
            row.organization_id = org_id
            row.state = state
            row.coverage_id = coverage.id if coverage else None
            row.classified_by_user_id = actor_id
            row.classified_at = now
        db.flush()
        suggest_account_states(db, org_id)
        refresh_coverage_alert(db, org_id)
        db.add(AuditLog(
            user_id=actor_id,
            organization_id=org_id,
            action="CLASSIFY_OPEN_FINANCE_ACCOUNT",
            entity_type="Account",
            entity_id=account.id,
            details={
                "state": state,
                "coverage_id": coverage.id if coverage else None,
                "account_id": account.id,
            },
        ))
        db.commit()
    except OpenFinanceBindError:
        db.rollback()
        raise
    except IntegrityError as exc:
        db.rollback()
        if _coverage_unique_violation(exc):
            raise OpenFinanceBindError(
                "This coverage is already bound to an Open Finance account"
            ) from exc
        raise
    except Exception:
        db.rollback()
        raise
    return {
        "organization_id": org_id,
        "account_id": account.id,
        "state": state,
        "coverage_id": coverage.id if coverage else None,
        "classified_by_user_id": actor_id,
    }


def cashflow_selection(db, org_id: int, start: date, end: date):
    """Rows that may be summed, plus the accounts withheld from that window.

    An organization with no reviewed local import is unchanged: every row
    counts and there is no coverage note. Otherwise each Open Finance
    account is BOUND, INDEPENDENT, or UNCLASSIFIED. This read does not
    write alerts.
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
    if not _org_has_reviewed_local_import(db, org_id):
        return [(row.transaction_date, row.amount) for row in rows], None
    ctx = _classification_context(db, org_id)
    visible, excluded, matched, lines = _lines_from(db, rows, ctx)
    note = {
        "excluded_count": excluded,
        "matched_count": matched,
        "unmatched_count": 0,
        "provider_account_linked": ctx["linked"],
        "excluded_accounts": lines,
        "message": _coverage_message(lines, excluded),
    }
    return visible, note


def _classification_context(db, org_id: int) -> dict:
    coverages = db.query(AccountSourceCoverage).filter_by(organization_id=org_id).all()
    classes = {
        row.account_id: row
        for row in db.query(OfAccountClassification).filter_by(organization_id=org_id).all()
    }
    bound_ids = {row.coverage_id for row in classes.values() if row.state == STATE_BOUND}
    actor_ids = {row.classified_by_user_id for row in classes.values() if row.classified_by_user_id}
    users = {}
    if actor_ids:
        users = {user.id: user for user in db.query(User).filter(User.id.in_(actor_ids)).all()}
    return {
        "classes": classes,
        "users": users,
        "duplicates": _duplicate_index(db, org_id, classes),
        "cutoffs": {cov.id: _effective_provider_cutoff(db, cov) for cov in coverages},
        "by_local": {cov.local_account_id: cov for cov in coverages},
        "last_end": _latest_local_end(db, org_id),
        "linked": all(cov.id in bound_ids for cov in coverages) if coverages else True,
    }


def _decision(row, ctx) -> tuple[bool, str | None, bool]:
    """Return (include, open-finance reason, fingerprint-matched).

    Local overlap is excluded without an account line and without counting
    as unmatched. A duplicate digit-group row is excluded on every date.
    ``INDEPENDENT`` counts on every date and is still named. ``BOUND`` counts
    from the effective coverage cutoff. ``UNCLASSIFIED`` counts only after
    the latest reviewed local import in the organization.
    """
    if row.source == "open_finance":
        duplicate = ctx["duplicates"].get(row.account_id)
        if duplicate and duplicate["duplicate"]:
            return False, REASON_DUPLICATE, False
    if row.superseded_by_id is not None:
        reason = REASON_BEFORE_COVERAGE if row.source == "open_finance" else None
        return False, reason, True
    if row.source == LOCAL_SOURCE:
        cov = ctx["by_local"].get(row.account_id)
        if cov is not None and row.transaction_date >= cov.covers_from:
            return False, None, False
        return True, None, False
    if row.source != "open_finance":
        return True, None, False
    klass = ctx["classes"].get(row.account_id)
    state = klass.state if klass is not None else STATE_UNCLASSIFIED
    if state == STATE_INDEPENDENT:
        return True, STATE_INDEPENDENT, False
    if state == STATE_BOUND and klass is not None and klass.coverage_id in ctx["cutoffs"]:
        if row.transaction_date < ctx["cutoffs"][klass.coverage_id]:
            return False, REASON_BEFORE_COVERAGE, False
        return True, None, False
    last_end = ctx["last_end"]
    if last_end is None or row.transaction_date <= last_end:
        return False, STATE_UNCLASSIFIED, False
    return True, None, False


def _lines_from(db, rows, ctx) -> tuple[list, int, int, list]:
    visible = []
    excluded = matched = 0
    buckets: dict[tuple[int, str], dict] = {}

    def bucket_for(account_id: int, reason: str) -> dict:
        key = (account_id, reason)
        found = buckets.get(key)
        if found is None:
            found = {"net": Decimal("0"), "inflow": Decimal("0"), "outflow": Decimal("0")}
            buckets[key] = found
        return found

    for row in rows:
        include, reason, is_matched = _decision(row, ctx)
        amount = row.amount if isinstance(row.amount, Decimal) else Decimal(str(row.amount or 0))
        if include:
            visible.append((row.transaction_date, row.amount))
            if reason == STATE_INDEPENDENT and row.account_id is not None:
                _add_amount(bucket_for(row.account_id, STATE_INDEPENDENT), amount)
            continue
        excluded += 1
        if is_matched:
            matched += 1
        if reason is None or row.account_id is None:
            continue
        _add_amount(bucket_for(row.account_id, reason), amount)
    for account_id, klass in ctx["classes"].items():
        if klass.state != STATE_INDEPENDENT:
            continue
        duplicate = ctx["duplicates"].get(account_id)
        if duplicate and duplicate["duplicate"]:
            continue
        bucket_for(account_id, STATE_INDEPENDENT)
    account_ids = {account_id for account_id, _reason in buckets}
    accounts = {}
    if account_ids:
        accounts = {
            account.id: account
            for account in db.query(Account).filter(Account.id.in_(account_ids)).all()
        }
    lines = []
    for (account_id, reason) in sorted(buckets):
        account = accounts.get(account_id)
        amounts = buckets[(account_id, reason)]
        klass = ctx["classes"].get(account_id)
        duplicate = ctx["duplicates"].get(account_id) or {}
        line = {
            "account_id": account_id,
            "label": account.name if account is not None and account.name else "חשבון בנק",
            "masked_number": _masked_number(account),
            "net_amount": _money(amounts["net"]),
            "inflow_amount": _money(amounts["inflow"]),
            "outflow_amount": _money(amounts["outflow"]),
            "reason": reason,
        }
        if reason == REASON_DUPLICATE:
            line["keeper_mask"] = duplicate.get("keeper_mask") or line["masked_number"]
        if reason == STATE_INDEPENDENT:
            user = ctx["users"].get(klass.classified_by_user_id) if klass is not None else None
            line["actor_name"] = _actor_name(user)
            line["classified_on"] = (
                klass.classified_at.date().isoformat()
                if klass is not None and klass.classified_at is not None else ""
            )
        lines.append(line)
    return visible, excluded, matched, lines


def _coverage_message(lines: list, excluded: int, *, public: bool = False) -> str | None:
    parts = []
    for item in lines:
        amounts = (
            f"{item['net_amount']:.2f} "
            f"(כניסות {item['inflow_amount']:.2f}, יציאות {item['outflow_amount']:.2f})"
        )
        label = f"{item['label']} {item['masked_number']}"
        reason = item["reason"]
        if reason == STATE_INDEPENDENT:
            actor = PUBLIC_ACTOR_LABEL if public else (item.get("actor_name") or "משרד")
            parts.append(
                f"{label}: {amounts} נספר במלואו "
                f"(עצמאי, נקבע על ידי {actor} ב-{item.get('classified_on') or ''})"
            )
            continue
        if reason == REASON_DUPLICATE:
            parts.append(
                f"{label}: {amounts} כפול של {item.get('keeper_mask') or item['masked_number']}, לא נספר"
            )
            continue
        hebrew = _REASON_HEBREW.get(reason, reason)
        parts.append(f"{label}: {amounts} לא נספר ({hebrew})")
    if excluded and not parts:
        parts.append("תנועות מקומיות אחרי תחילת הכיסוי לא נספרו.")
    return " ".join(parts) if parts else None


def redact_public_coverage(note):
    """Drop internal ids and staff identity from a coverage note before it is published on /d/.

    The message names the classifying user on INDEPENDENT lines, so it is
    rebuilt with the office label. Stored snapshots pass through here too.
    """
    if not isinstance(note, dict):
        return note
    cleaned = {}
    for key, value in note.items():
        if key == "excluded_accounts" or key.endswith("_id"):
            continue
        cleaned[key] = value
    accounts = []
    for item in note.get("excluded_accounts") or []:
        if not isinstance(item, dict):
            continue
        accounts.append({
            key: item[key]
            for key in _PUBLIC_LINE_KEYS
            if key in item and item[key] is not None
        })
    cleaned["excluded_accounts"] = accounts
    lines = [item for item in note.get("excluded_accounts") or [] if isinstance(item, dict)]
    if cleaned.get("message") and any(item.get("reason") == STATE_INDEPENDENT for item in lines):
        cleaned["message"] = _coverage_message(lines, note.get("excluded_count") or 0, public=True)
    return cleaned


def _resolve_active_alerts(db, org_id: int, alert_type: str) -> None:
    now = datetime.utcnow()
    rows = (
        db.query(Alert)
        .filter(
            Alert.organization_id == org_id,
            Alert.alert_type == alert_type,
            Alert.status == AlertStatus.ACTIVE,
        )
        .all()
    )
    for row in rows:
        row.status = AlertStatus.RESOLVED
        row.resolved_at = now


def refresh_coverage_alert(db, org_id: int) -> None:
    """One org alert naming every withheld Open Finance account.

    Callers commit. A cash-flow read must not call this. The alert names
    UNCLASSIFIED accounts, duplicate rows, and INDEPENDENT decisions.
    ``before covers_from`` stays in the note and does not keep the alert
    active. An empty alert list resolves it. A stale unattached alert is
    resolved on every refresh.
    """
    _flush_session(db)
    _resolve_active_alerts(db, org_id, ALERT_UNATTACHED)
    if not _org_has_reviewed_local_import(db, org_id):
        _resolve_active_alerts(db, org_id, ALERT_WITHHELD)
        _flush_session(db)
        return
    rows = (
        db.query(BankTransaction)
        .filter(
            BankTransaction.organization_id == org_id,
            BankTransaction.source == "open_finance",
        )
        .all()
    )
    _visible, _excluded, _matched, lines = _lines_from(db, rows, _classification_context(db, org_id))
    lines = [line for line in lines if line["reason"] in ALERT_REASONS]
    existing = (
        db.query(Alert)
        .filter(Alert.organization_id == org_id, Alert.alert_type == ALERT_WITHHELD)
        .order_by(Alert.id.desc())
        .first()
    )
    message = _coverage_message(lines, 0)
    if not lines:
        if existing is not None and existing.status == AlertStatus.ACTIVE:
            existing.status = AlertStatus.RESOLVED
            existing.resolved_at = datetime.utcnow()
            existing.meta = {"accounts": []}
        _flush_session(db)
        return
    payload = {"accounts": lines}
    if existing is None:
        db.add(Alert(
            organization_id=org_id,
            alert_type=ALERT_WITHHELD,
            severity=AlertSeverity.WARNING,
            title="סיווג חשבונות בנק",
            message=message,
            status=AlertStatus.ACTIVE,
            meta=payload,
        ))
    else:
        existing.status = AlertStatus.ACTIVE
        existing.resolved_at = None
        existing.title = "סיווג חשבונות בנק"
        existing.message = message
        existing.meta = payload
    _flush_session(db)


def record_unattached_coverage_alert(db, org_id: int) -> None:
    """Refresh the withheld-account alert and retire a stale unattached alert."""
    refresh_coverage_alert(db, org_id)


def supersede_other_live_consents(db, org_id: int, connection_id: str) -> None:
    """Retire other live consents so a renewal can become ACTIVE.

    The partial unique index allows one ACTIVE, CONNECTED, or COMPLETED
    Open Finance row per organization. ``SUPERSEDED`` is outside that list.
    BOUND state for the same account number moves onto the surviving consent
    in this transaction, before the new row can fall back to UNCLASSIFIED.
    """
    snaps = _bound_snapshots(db, org_id)
    rows = (
        db.query(BankConnection)
        .filter(
            BankConnection.organization_id == org_id,
            BankConnection.source == "open_finance",
            BankConnection.connection_id != connection_id,
            BankConnection.status.in_(tuple(SYNCABLE_STATUSES)),
        )
        .all()
    )
    for other in rows:
        other.status = "SUPERSEDED"
    _flush_session(db)
    _carry_bound_to_live_row(db, org_id, connection_id, snaps)


def _effective_provider_cutoff(db, cov) -> date:
    """First provider-authoritative day that does not leave a gap.

    Stored ``covers_from`` may be later than the day after the local import.
    Dates in that gap are not covered by a local row, so they stay in the sum.
    """
    last_local = (
        db.query(func.max(BankTransaction.transaction_date))
        .filter(
            BankTransaction.organization_id == cov.organization_id,
            BankTransaction.account_id == cov.local_account_id,
            BankTransaction.source == LOCAL_SOURCE,
        )
        .scalar()
    )
    if last_local is None:
        return cov.covers_from
    day_after = last_local + timedelta(days=1)
    if day_after < cov.covers_from:
        return day_after
    return cov.covers_from


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
    if last_local is not None and covers_from != last_local + timedelta(days=1):
        raise OpenFinanceBindError(
            "covers_from must be the day after the last reviewed local transaction"
        )
    suffix = _four_digit_suffix(suffix)
    if not suffix:
        raise OpenFinanceBindError("Coverage suffix must be exactly 4 digits")
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


from .coverage_alert_hooks import install as _install_coverage_alert_hooks

_install_coverage_alert_hooks()
