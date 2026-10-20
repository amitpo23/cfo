"""Office-owned import-only clients. No provider imports, credentials or queues.

Reviewed journals retain the source chart. They are archived under a distinct
source, excluded from the derived ledger until an explicit chart mapping exists.
Bank observations are provisional imported evidence, never live BOOKED records.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import re

from sqlalchemy import null, text

from ..models import (
    Account, AccountType, AuditLog, BankTransaction, DailySnapshot,
    IntegrationConnection, IntegrationType, JournalEntry, Organization,
    SumitCompany, SyncRun,
)

SOURCE = "reviewed_local_import"
MODE = "import_only"


def _stamp(value):
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def _lock(db, key):
    if db.get_bind().dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": key})


def _local_client(db, office_id, client_id):
    row = db.query(SumitCompany).filter_by(id=client_id, office_organization_id=office_id).first()
    mode = (row.raw_data or {}).get("mode") if row else None
    if not row or not row.target_organization_id or mode not in (MODE, "hybrid"):
        raise ValueError("Import-only client not found in this office")
    org = db.get(Organization, row.target_organization_id)
    if not org or not org.is_active or (org.settings or {}).get("provider_calls_allowed") is not False:
        raise ValueError("Import-only client identity or mode changed")
    active = db.query(IntegrationConnection).filter_by(organization_id=org.id, status="active").all()
    if mode == MODE and active:
        raise ValueError("Import-only client has an active provider connection")
    if mode == "hybrid" and (len(active) != 1 or active[0].source != "open_finance"):
        raise ValueError("Hybrid client requires exactly one active Open Finance connection")
    return row, org


def register_local_client(db, office_id, *, name, tax_id, actor_id=None):
    name, tax_id = str(name).strip(), str(tax_id).strip()
    if not name or len(name) > 255 or not re.fullmatch(r"\d{9}", tax_id):
        raise ValueError("Client name and nine-digit verified tax identity are required")
    office = db.get(Organization, office_id)
    if not office or not office.is_active:
        raise ValueError("Active office required")
    try:
        # Global identity lock prevents simultaneous offices creating two tenants.
        _lock(db, "local-client-tax:" + tax_id)
        matches = db.query(Organization).filter(Organization.tax_id == tax_id).all()
        key = "local-tax:" + tax_id
        roster = db.query(SumitCompany).filter_by(office_organization_id=office_id, company_id=key).first()
        if matches:
            if len(matches) != 1 or not roster or roster.target_organization_id != matches[0].id:
                raise ValueError("Existing tax identity belongs to another office or tenant")
            _, org = _local_client(db, office_id, roster.id)
            if org.name != name:
                raise ValueError("Existing client identity name differs")
        else:
            if roster:
                raise ValueError("Existing office identity is inconsistent")
            org = Organization(name=name, tax_id=tax_id, integration_type=IntegrationType.MANUAL,
                               is_active=True, collection_reminders_enabled=False,
                               morning_brief_email_enabled=False, morning_brief_sms_enabled=False,
                               settings={"mode": MODE, "provider_calls_allowed": False,
                                         "financial_coverage": "reviewed_sources_only"})
            db.add(org); db.flush()
            roster = SumitCompany(office_organization_id=office_id, company_id=key, name=name,
                                  status="active", target_organization_id=org.id,
                                  raw_data={"mode": MODE, "provider_company_id": None,
                                            "automation": {"state": "disabled", "reason": MODE}})
            db.add(roster); db.flush()
            db.add(AuditLog(user_id=actor_id, organization_id=org.id, action="CREATE_IMPORT_ONLY_CLIENT",
                            entity_type="Organization", entity_id=org.id,
                            details={"office_id": office_id, "tax_id": tax_id, "mode": MODE,
                                     "provider_calls": 0, "provider_credentials_copied": False}))
        db.commit()
        return {"id": roster.id, "name": org.name, "tax_id": tax_id, "target_organization_id": org.id,
                "company_id": None, "roster_key": key, "mode": MODE, "provider_calls": 0,
                "automation": {"state": "disabled"}}
    except Exception:
        db.rollback()
        raise


def _amount(value):
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError("Invalid source amount") from None
    if not number.is_finite() or abs(number) >= Decimal("1000000000") or number != number.quantize(Decimal("0.01")):
        raise ValueError("Invalid source amount or precision")
    return format(number, ".2f")


def _validate_bundle(payload):
    expected = {"kind", "source_name", "source_sha256", "observed_at", "bank_account_suffix", "rows"}
    if not isinstance(payload, dict) or set(payload) - expected:
        raise ValueError("Unknown source fields")
    kind = payload.get("kind")
    if kind not in ("journal", "bank"):
        raise ValueError("Source kind must be journal or bank")
    name, sha = payload.get("source_name"), payload.get("source_sha256")
    if not isinstance(name, str) or not 1 <= len(name) <= 255 or "/" in name or "\\" in name:
        raise ValueError("Source filename required")
    if not isinstance(sha, str) or not re.fullmatch(r"[a-f0-9]{64}", sha):
        raise ValueError("Source SHA256 required")
    try:
        observed = datetime.fromisoformat(str(payload.get("observed_at", "")).replace("Z", "+00:00"))
        if observed.utcoffset() is None:
            raise ValueError()
        observed = observed.astimezone(timezone.utc)
        if observed > datetime.now(timezone.utc):
            raise ValueError()
    except (ValueError, TypeError):
        raise ValueError("Valid observed_at with timezone required") from None
    suffix = payload.get("bank_account_suffix")
    if kind == "bank" and (not isinstance(suffix, str) or not re.fullmatch(r"\d{4,20}", suffix)):
        raise ValueError("Verified source bank suffix required")
    rows = payload.get("rows")
    if not isinstance(rows, list) or not 1 <= len(rows) <= 5000:
        raise ValueError("Source must contain 1 to 5000 rows")
    normalized, ids = [], set()
    fields = {"external_id", "date", "amount", "description", "currency", "original"}
    if kind == "journal":
        fields |= {"debit_account", "credit_account"}
    for row in rows:
        if not isinstance(row, dict) or set(row) - fields:
            raise ValueError("Unknown source row fields")
        identity = row.get("external_id")
        if not isinstance(identity, str) or not 1 <= len(identity) <= 150 or identity in ids:
            raise ValueError("Missing or duplicate source row identity")
        ids.add(identity)
        try:
            day = date.fromisoformat(row.get("date", ""))
        except (TypeError, ValueError):
            raise ValueError("Valid source date required") from None
        if day > observed.date():
            raise ValueError("Source row date is after observation")
        if row.get("currency") != "ILS":
            raise ValueError("Only explicit ILS source amounts are supported")
        description = row.get("description") or ""
        if not isinstance(description, str) or len(description) > 500:
            raise ValueError("Invalid source description")
        value = {"external_id": identity, "date": day.isoformat(), "amount": _amount(row.get("amount")),
                 "description": description, "currency": "ILS"}
        if kind == "journal":
            for side in ("debit_account", "credit_account"):
                code = row.get(side) or ""
                if not isinstance(code, str) or (code and not re.fullmatch(r"[A-Za-z0-9_.:-]{1,60}", code)):
                    raise ValueError("Invalid source account code")
                value[side] = code
            if not value["debit_account"] and not value["credit_account"]:
                raise ValueError("Source journal has no account sides")
        content_hash = hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        original = row.get("original", row)
        if not isinstance(original, dict) or len(json.dumps(original, ensure_ascii=False)) > 15000:
            raise ValueError("Source original must be a bounded object")
        normalized.append((value, content_hash, original))
    return kind, name, sha, observed, suffix, normalized


def import_reviewed_source(db, office_id, client_id, payload, *, actor_id=None):
    kind, name, sha, observed, suffix, rows = _validate_bundle(payload)
    try:
        client, org = _local_client(db, office_id, client_id)
        _lock(db, "local-client-import:" + str(org.id))
        model = JournalEntry if kind == "journal" else BankTransaction
        prefix = "journal:" if kind == "journal" else "bank:" + suffix + ":"
        existing = {r.external_id: r for r in db.query(model).filter_by(organization_id=org.id, source=SOURCE).all()}
        # Resolve all conflicts before creating any account or source row.
        for row, digest, _ in rows:
            old = existing.get(prefix + row["external_id"])
            if old and old.payload_hash != digest:
                raise ValueError("Source identity conflict; correction requires explicit review")
        account = None
        if kind == "bank":
            account = db.query(Account).filter_by(organization_id=org.id, source=SOURCE,
                                                  external_id="local-bank:" + suffix).first()
            if not account:
                account = Account(organization_id=org.id, name="Imported bank " + suffix,
                                  account_type=AccountType.BANK, source=SOURCE, balance=null(),
                                  currency="ILS", external_id="local-bank:" + suffix,
                                  raw_account_type="CHECKING")
                db.add(account); db.flush()
        inserted = unchanged = 0
        for row, digest, original in rows:
            external_id = prefix + row["external_id"]
            if external_id in existing:
                unchanged += 1
                continue
            evidence = {"source_name": name, "source_sha256": sha, "source_observed_at": observed.isoformat(),
                        "original": original, "normalized": row, "source_account_suffix": suffix,
                        "reporting_status": "source_chart_unmapped" if kind == "journal" else "imported_observation",
                        "official_posting": False, "provider_calls": 0}
            if kind == "journal":
                amount = Decimal(row["amount"])
                debit, credit = row["debit_account"], row["credit_account"]
                if amount < 0:
                    debit, credit = credit, debit
                    amount = -amount
                lines = []
                if debit:
                    lines.append({"account": debit, "debit": str(amount), "credit": "0.00"})
                if credit:
                    lines.append({"account": credit, "debit": "0.00", "credit": str(amount)})
                new = JournalEntry(organization_id=org.id, source=SOURCE, external_id=external_id,
                                   entry_date=date.fromisoformat(row["date"]), memo=row["description"],
                                   lines=lines, raw_data=evidence, payload_hash=digest)
            else:
                tx_date = date.fromisoformat(row["date"])
                from .bank_coverage import content_fingerprint
                new = BankTransaction(organization_id=org.id, source=SOURCE, external_id=external_id,
                                      account_id=account.id, transaction_date=tx_date,
                                      amount=Decimal(row["amount"]), description=row["description"],
                                      currency="ILS", is_provisional=True, is_reconciled=False,
                                      raw_data=evidence, payload_hash=digest,
                                      content_fingerprint=content_fingerprint(tx_date, row["amount"], row["description"]))
            db.add(new)
            inserted += 1
        if inserted:
            db.add(AuditLog(user_id=actor_id, organization_id=org.id, action="IMPORT_REVIEWED_SOURCE",
                            entity_type="Organization", entity_id=org.id,
                            details={"kind": kind, "source_name": name, "source_sha256": sha,
                                     "observed_at": observed.isoformat(), "inserted": inserted,
                                     "unchanged": unchanged, "provider_calls": 0,
                                     "source_account_suffix": suffix}))
        db.commit()
        return {"organization_id": org.id, "kind": kind, "inserted": inserted, "unchanged": unchanged,
                "source_sha256": sha, "mode": MODE, "provider_calls": 0}
    except Exception:
        db.rollback()
        raise


def local_client_coverage(db, office_id):
    """DB-only coverage enumerates roster entries even when no sync ever ran."""
    now = datetime.now(timezone.utc)
    clients = []
    roster = db.query(SumitCompany).filter_by(office_organization_id=office_id, status="active").all()
    for client in roster:
        if not client.target_organization_id:
            continue
        org = db.get(Organization, client.target_organization_id)
        if not org or not org.is_active:
            continue
        mode = (client.raw_data or {}).get("mode", "connected")
        connections = {c.source: c for c in db.query(IntegrationConnection).filter_by(organization_id=org.id).all()}
        sources = {}
        for source in ("open_finance", "sumit"):
            conn = connections.get(source)
            latest = db.query(SyncRun).filter_by(organization_id=org.id, source=source).order_by(SyncRun.started_at.desc()).first()
            finished = _stamp(latest.finished_at) if latest else None
            age = (now - datetime.fromisoformat(finished)).total_seconds() / 3600 if finished else None
            fresh = bool(conn and conn.status == "active" and latest and
                         str(getattr(latest.status, "value", latest.status)).lower() == "completed" and
                         age is not None and 0 <= age <= 36)
            status = "current" if fresh else ("stale" if conn and conn.status == "active" else
                     ("disabled" if source == "sumit" and mode in (MODE, "hybrid") else "not_connected"))
            sources[source] = {"status": status, "last_run_at": finished, "connection_status": conn.status if conn else None}
        snapshot = db.query(DailySnapshot).filter_by(organization_id=org.id).order_by(DailySnapshot.snapshot_date.desc()).first()
        imports = db.query(AuditLog).filter_by(organization_id=org.id, action="IMPORT_REVIEWED_SOURCE").order_by(AuditLog.id.desc()).all()
        clients.append({"organization_id": org.id, "name": org.name, "mode": mode,
                        "sources": sources,
                        "morning_cycle": {"status": ("current" if snapshot.snapshot_date == now.date() else "stale") if snapshot else "not_run",
                                          "date": snapshot.snapshot_date.isoformat() if snapshot else None,
                                          "result": snapshot.cycle_status if snapshot else None},
                        "reviewed_imports": [r.details for r in imports[:20]],
                        "financial_coverage": (
                            "reviewed_sources_only" if mode == MODE
                            else "reviewed_local_plus_open_finance" if mode == "hybrid"
                            else "provider_sources")})
    return {"checked_at": now.isoformat(), "clients": clients, "provider_calls": 0}
