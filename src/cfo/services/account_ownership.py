"""
Account ownership matching — Package H (2026-07-27b plan, section H).

The owner's ruling (2026-07-27): the sole "super admin" is the business owner
— there is no separate "org admin" role that self-declares ownership. The
default is that the system identifies ownership on its own; a human decision
is required ONLY when identification does not converge. That's honest-null:
ambiguity is a decision queue, never a guess.

The match is three-way and exact — not fuzzy name matching:
  - ``Organization.tax_id`` (עוסק מורשה / ח.פ, set by the bookkeeper)
  - ``Account.owner_national_id`` (Open Finance ``ownerInfo.nationalId``,
    extracted in ``open_finance_connector._normalize_account`` and persisted
    by the daily sync — see docs/OPEN_FINANCE_KNOWLEDGE_BASE.md:248)
  - SUMIT's ``CorporateNumber`` (from ``get_company_details``) — supplied by
    the caller as ``sumit_corporate_number``; this module makes NO network
    calls and never reaches out to SUMIT itself.

No I/O beyond the given ``Session``. No numbers are invented: ``sources``
in the returned dict always shows the raw values exactly as stored
(including ``None``) so the human reviewing the queue sees facts, not a
conclusion baked in by this function.
"""
from __future__ import annotations

from typing import Any, Optional

from sqlalchemy.orm import Session

from ..models import Account, Organization

# Statuses, in the severity order used to sort review_queue() (most urgent
# first): an outright contradiction between identifiers outranks merely
# missing data, which outranks having no bank connection to compare at all.
STATUS_NEEDS_REVIEW = "needs_review"
STATUS_INSUFFICIENT_DATA = "insufficient_data"
STATUS_NO_BANK_CONNECTION = "no_bank_connection"
STATUS_MATCHED = "matched"

_SEVERITY = {
    STATUS_NEEDS_REVIEW: 0,
    STATUS_INSUFFICIENT_DATA: 1,
    STATUS_NO_BANK_CONNECTION: 2,
}

MANUAL_OVERRIDE_REASON = 'הוכרע ידנית ע"י מנהל המערכת'


def normalize_israeli_id(value: Optional[str]) -> Optional[str]:
    """Digits-only Israeli national-id / ח.פ. Strips dashes/spaces/punctuation.

    Empty input (None, "", or a string with no digits at all) normalizes to
    None — never an empty string — so callers can treat "missing" uniformly.
    """
    if value is None:
        return None
    digits = "".join(ch for ch in str(value) if ch.isdigit())
    return digits or None


def _accounts_for_org(db: Session, organization_id: int) -> list[Account]:
    return (
        db.query(Account)
        .filter(
            Account.organization_id == organization_id,
            Account.source == "open_finance",
        )
        .order_by(Account.id.asc())
        .all()
    )


def _account_payload(account: Account) -> dict[str, Any]:
    return {
        "id": account.id,
        "name": account.name,
        "owner_national_id": account.owner_national_id,
        "owner_name": account.owner_name,
        "is_primary_business_account": bool(account.is_primary_business_account),
    }


def ownership_status(
    db: Session,
    organization_id: int,
    *,
    sumit_corporate_number: Optional[str] = None,
) -> dict[str, Any]:
    """Three-way reconciliation for a single organization. No network I/O.

    Returns ``{"status", "reason", "sources", "accounts"}``. ``sources`` holds
    the three raw identifiers as they are actually stored (honest-null — the
    reviewer sees facts, not this function's normalized comparison values).
    """
    org = db.query(Organization).filter(Organization.id == organization_id).first()
    if org is None:
        raise ValueError(f"organization {organization_id} not found")

    accounts = _accounts_for_org(db, organization_id)
    accounts_payload = [_account_payload(a) for a in accounts]
    sources = {
        "organization_tax_id": org.tax_id,
        "bank_owner_national_id": [a.owner_national_id for a in accounts],
        "sumit_corporate_number": sumit_corporate_number,
    }

    # A manual decision by the owner always wins and never re-enters the
    # queue, regardless of what the automatic identifiers say afterwards.
    if org.ownership_reviewed_at is not None:
        return {
            "status": STATUS_MATCHED,
            "reason": MANUAL_OVERRIDE_REASON,
            "sources": sources,
            "accounts": accounts_payload,
        }

    if not accounts:
        return {
            "status": STATUS_NO_BANK_CONNECTION,
            "reason": "לארגון אין חיבור Open Finance / חשבונות בנק מסונכרנים",
            "sources": sources,
            "accounts": accounts_payload,
        }

    normalized_tax_id = normalize_israeli_id(org.tax_id)
    if normalized_tax_id is None:
        return {
            "status": STATUS_INSUFFICIENT_DATA,
            "reason": "אין מספר עוסק/ח.פ רשום לארגון",
            "sources": sources,
            "accounts": accounts_payload,
        }

    normalized_bank_ids = sorted(
        {
            nid
            for nid in (normalize_israeli_id(a.owner_national_id) for a in accounts)
            if nid
        }
    )
    if not normalized_bank_ids:
        return {
            "status": STATUS_INSUFFICIENT_DATA,
            "reason": "טרם סונכרן מזהה בעלים (ownerInfo) מאף חשבון בנק",
            "sources": sources,
            "accounts": accounts_payload,
        }

    if len(normalized_bank_ids) > 1:
        # Multiple accounts with different owners and none marked primary —
        # ambiguous by construction; the owner must pick which is the
        # business account (POST .../resolve), not this function.
        return {
            "status": STATUS_NEEDS_REVIEW,
            "reason": "מספר חשבונות בנק עם מזהי בעלים שונים — יש לסמן את חשבון העסק הראשי",
            "sources": sources,
            "accounts": accounts_payload,
        }

    normalized_sumit = normalize_israeli_id(sumit_corporate_number)
    present: dict[str, str] = {"tax_id": normalized_tax_id, "bank": normalized_bank_ids[0]}
    if normalized_sumit:
        present["sumit"] = normalized_sumit

    distinct_values = set(present.values())
    if len(distinct_values) == 1:
        return {
            "status": STATUS_MATCHED,
            "reason": "כל המזהים הקיימים מתלכדים",
            "sources": sources,
            "accounts": accounts_payload,
        }

    return {
        "status": STATUS_NEEDS_REVIEW,
        "reason": "סתירה בין מזהי הבעלות (עוסק/ח.פ, חשבון בנק, SUMIT)",
        "sources": sources,
        "accounts": accounts_payload,
    }


def review_queue(db: Session) -> list[dict[str, Any]]:
    """Every organization whose ownership isn't ``matched``, most severe first.

    No ``sumit_corporate_number`` is available here (no network calls) — the
    queue reflects internal DB sources only; a resolver UI/endpoint may pass
    a fresher SUMIT number per-organization when it has one on hand.
    """
    orgs = db.query(Organization).order_by(Organization.id.asc()).all()
    queue: list[dict[str, Any]] = []
    for org in orgs:
        result = ownership_status(db, org.id)
        if result["status"] == STATUS_MATCHED:
            continue
        queue.append({
            "organization_id": org.id,
            "organization_name": org.name,
            **result,
        })
    queue.sort(key=lambda item: _SEVERITY.get(item["status"], 99))
    return queue
