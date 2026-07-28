"""Package H (2026-07-27b plan) — automatic ownership matching + the super
admin's decision queue.

The sole "super admin" is the business owner — there is no separate "org
admin" who self-declares ownership. honest-null: identification is automatic
by default; a human decision is required ONLY when the three identifiers
(Organization.tax_id, Account.owner_national_id from Open Finance's
ownerInfo, and SUMIT's CorporateNumber) fail to converge.
"""
from datetime import datetime, timezone

import pytest

from cfo.auth import create_access_token
from cfo.database import SessionLocal
from cfo.models import Account, AccountType, AuditLog, Organization, User, UserRole
from cfo.services.account_ownership import (
    normalize_israeli_id,
    ownership_status,
    review_queue,
)
from cfo.services.open_finance_connector import OpenFinanceConnector


# --------------------------------------------------------------------- #
# normalize_israeli_id
# --------------------------------------------------------------------- #
def test_normalize_israeli_id_strips_dashes_and_spaces():
    assert normalize_israeli_id("512-345-678") == "512345678"
    assert normalize_israeli_id(" 512 345 678 ") == "512345678"


def test_normalize_israeli_id_empty_and_none():
    assert normalize_israeli_id(None) is None
    assert normalize_israeli_id("") is None
    assert normalize_israeli_id("   ") is None
    assert normalize_israeli_id("--") is None


def test_normalize_israeli_id_plain_digits_unchanged():
    assert normalize_israeli_id("512345678") == "512345678"


# --------------------------------------------------------------------- #
# ownership_status — DB fixtures
# --------------------------------------------------------------------- #
@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def _make_account(db, org_id, *, owner_national_id=None, owner_name=None, external_id, source="open_finance"):
    acc = Account(
        organization_id=org_id,
        name="Bank Leumi Checking",
        account_type=AccountType.BANK,
        source=source,
        external_id=external_id,
        balance=1000,
        currency="ILS",
        owner_national_id=owner_national_id,
        owner_name=owner_name,
    )
    db.add(acc)
    db.commit()
    return acc


def test_matched_when_tax_id_and_bank_owner_agree(db, fresh_org):
    org_id = fresh_org()["org_id"]
    org = db.query(Organization).filter(Organization.id == org_id).first()
    org.tax_id = "512345678"
    db.commit()
    _make_account(db, org_id, owner_national_id="512345678", owner_name="Acme Ltd", external_id="oo-1")

    result = ownership_status(db, org_id)
    assert result["status"] == "matched"
    assert result["sources"]["organization_tax_id"] == "512345678"
    assert result["sources"]["bank_owner_national_id"] == ["512345678"]


def test_matched_when_all_three_sources_agree(db, fresh_org):
    org_id = fresh_org()["org_id"]
    org = db.query(Organization).filter(Organization.id == org_id).first()
    org.tax_id = "512-345-678"
    db.commit()
    _make_account(db, org_id, owner_national_id="512345678", external_id="oo-2")

    result = ownership_status(db, org_id, sumit_corporate_number="512 345 678")
    assert result["status"] == "matched"
    assert result["sources"]["sumit_corporate_number"] == "512 345 678"


def test_needs_review_on_contradiction_shows_all_three_sources(db, fresh_org):
    org_id = fresh_org()["org_id"]
    org = db.query(Organization).filter(Organization.id == org_id).first()
    org.tax_id = "512345678"
    db.commit()
    _make_account(db, org_id, owner_national_id="999999999", external_id="oo-3")

    result = ownership_status(db, org_id, sumit_corporate_number="777777777")
    assert result["status"] == "needs_review"
    assert set(result["sources"].keys()) == {
        "organization_tax_id",
        "bank_owner_national_id",
        "sumit_corporate_number",
    }
    assert result["sources"]["organization_tax_id"] == "512345678"
    assert result["sources"]["bank_owner_national_id"] == ["999999999"]
    assert result["sources"]["sumit_corporate_number"] == "777777777"


def test_needs_review_when_multiple_accounts_have_different_owners(db, fresh_org):
    org_id = fresh_org()["org_id"]
    org = db.query(Organization).filter(Organization.id == org_id).first()
    org.tax_id = "512345678"
    db.commit()
    _make_account(db, org_id, owner_national_id="512345678", external_id="oo-4a")
    _make_account(db, org_id, owner_national_id="111111111", external_id="oo-4b")

    result = ownership_status(db, org_id)
    assert result["status"] == "needs_review"


def test_insufficient_data_when_tax_id_missing(db, fresh_org):
    org_id = fresh_org()["org_id"]
    _make_account(db, org_id, owner_national_id="512345678", external_id="oo-5")

    result = ownership_status(db, org_id)
    assert result["status"] == "insufficient_data"
    assert result["sources"]["organization_tax_id"] is None


def test_insufficient_data_when_no_account_has_owner_national_id_yet(db, fresh_org):
    org_id = fresh_org()["org_id"]
    org = db.query(Organization).filter(Organization.id == org_id).first()
    org.tax_id = "512345678"
    db.commit()
    _make_account(db, org_id, owner_national_id=None, external_id="oo-6")

    result = ownership_status(db, org_id)
    assert result["status"] == "insufficient_data"


def test_no_bank_connection_when_no_accounts(db, fresh_org):
    org_id = fresh_org()["org_id"]
    org = db.query(Organization).filter(Organization.id == org_id).first()
    org.tax_id = "512345678"
    db.commit()

    result = ownership_status(db, org_id)
    assert result["status"] == "no_bank_connection"
    assert result["accounts"] == []


def test_no_bank_connection_ignores_non_open_finance_accounts(db, fresh_org):
    org_id = fresh_org()["org_id"]
    org = db.query(Organization).filter(Organization.id == org_id).first()
    org.tax_id = "512345678"
    db.commit()
    _make_account(db, org_id, owner_national_id="512345678", external_id="oo-7", source="sumit")

    result = ownership_status(db, org_id)
    assert result["status"] == "no_bank_connection"


def test_manual_override_forces_matched_and_stops_contradicting(db, fresh_org):
    org_id = fresh_org()["org_id"]
    org = db.query(Organization).filter(Organization.id == org_id).first()
    org.tax_id = "512345678"
    org.ownership_reviewed_at = datetime.now(timezone.utc)
    db.commit()
    # Even with a raw contradiction present, the manual decision wins.
    _make_account(db, org_id, owner_national_id="999999999", external_id="oo-8")

    result = ownership_status(db, org_id)
    assert result["status"] == "matched"
    assert result["reason"] == 'הוכרע ידנית ע"י מנהל המערכת'


def test_ownership_status_unknown_org_raises(db):
    with pytest.raises(ValueError):
        ownership_status(db, 999999)


# --------------------------------------------------------------------- #
# review_queue
# --------------------------------------------------------------------- #
def test_review_queue_excludes_matched_orgs(db, fresh_org):
    matched_org = fresh_org()["org_id"]
    org = db.query(Organization).filter(Organization.id == matched_org).first()
    org.tax_id = "512345678"
    db.commit()
    _make_account(db, matched_org, owner_national_id="512345678", external_id="oo-9")

    review_org = fresh_org()["org_id"]
    org2 = db.query(Organization).filter(Organization.id == review_org).first()
    org2.tax_id = "512345678"
    db.commit()
    _make_account(db, review_org, owner_national_id="000000000", external_id="oo-10")

    queue = review_queue(db)
    org_ids_in_queue = {item["organization_id"] for item in queue}
    assert matched_org not in org_ids_in_queue
    assert review_org in org_ids_in_queue


def test_review_queue_sorts_needs_review_before_insufficient_data(db, fresh_org):
    needs_review_org = fresh_org()["org_id"]
    org = db.query(Organization).filter(Organization.id == needs_review_org).first()
    org.tax_id = "512345678"
    db.commit()
    _make_account(db, needs_review_org, owner_national_id="000000000", external_id="oo-11")

    insufficient_org = fresh_org()["org_id"]
    # Has a synced OF account (so it's not "no_bank_connection") but no
    # tax_id yet -> insufficient_data, which must still sort AFTER
    # needs_review even though this org was registered later (higher id).
    _make_account(db, insufficient_org, owner_national_id="222222222", external_id="oo-12")

    queue = review_queue(db)
    statuses_by_org = {item["organization_id"]: item["status"] for item in queue}
    needs_review_index = next(i for i, item in enumerate(queue) if item["organization_id"] == needs_review_org)
    insufficient_index = next(i for i, item in enumerate(queue) if item["organization_id"] == insufficient_org)
    assert needs_review_index < insufficient_index
    assert statuses_by_org[needs_review_org] == "needs_review"
    assert statuses_by_org[insufficient_org] == "insufficient_data"


# --------------------------------------------------------------------- #
# connector normalization — ownerInfo extraction
# --------------------------------------------------------------------- #
def _connector():
    return OpenFinanceConnector("cid", "secret", "user-1")


def test_normalize_account_extracts_owner_info():
    conn = _connector()
    a = conn._normalize_account({
        "id": "acc-1",
        "accountName": "עו\"ש",
        "currency": "ILS",
        "balances": [],
        "ownerInfo": {"nationalId": "512-345-678", "fullName": "עמית פורת"},
    })
    assert a.owner_national_id == "512345678"
    assert a.owner_name == "עמית פורת"


def test_normalize_account_owner_info_snake_case_key_variant():
    conn = _connector()
    a = conn._normalize_account({
        "id": "acc-2",
        "balances": [],
        "owner_info": {"nationalId": "123456782"},
    })
    assert a.owner_national_id == "123456782"


def test_normalize_account_owner_info_lowercase_key_variant():
    conn = _connector()
    a = conn._normalize_account({
        "id": "acc-3",
        "balances": [],
        "ownerinfo": {"national_id": "987654321", "full_name": "Some Owner"},
    })
    assert a.owner_national_id == "987654321"
    assert a.owner_name == "Some Owner"


def test_normalize_account_missing_owner_info_is_none():
    conn = _connector()
    a = conn._normalize_account({"id": "acc-4", "balances": []})
    assert a.owner_national_id is None
    assert a.owner_name is None


# --------------------------------------------------------------------- #
# admin endpoints
# --------------------------------------------------------------------- #
@pytest.fixture
def moshko_super_admin(client, fresh_org):
    """A fresh org's first user, promoted to SUPER_ADMIN (owner's ruling: the
    only 'super admin' role, matching tests/test_admin_migrate.py's pattern)."""
    actor = fresh_org()
    db = SessionLocal()
    try:
        user = (
            db.query(User)
            .filter(User.organization_id == actor["org_id"])
            .order_by(User.id)
            .first()
        )
        user.role = UserRole.SUPER_ADMIN
        db.commit()
        token = create_access_token(
            data={
                "sub": str(user.id),
                "role": UserRole.SUPER_ADMIN.value,
                "org_id": user.organization_id,
            }
        )
        user_id = user.id
    finally:
        db.close()
    return {"headers": {"Authorization": f"Bearer {token}"}, "user_id": user_id}


def test_ownership_review_requires_super_admin(client, owner):
    resp = client.get("/api/admin/moshko/ownership-review", headers=owner["headers"])
    assert resp.status_code == 403


def test_ownership_review_returns_queue_for_super_admin(client, moshko_super_admin, fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        org = db.query(Organization).filter(Organization.id == org_id).first()
        org.tax_id = "512345678"
        db.commit()
        _make_account(db, org_id, owner_national_id="000000000", external_id="oo-admin-1")
    finally:
        db.close()

    resp = client.get("/api/admin/moshko/ownership-review", headers=moshko_super_admin["headers"])
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert any(item["organization_id"] == org_id for item in body)


def test_resolve_marks_matched_and_writes_audit_log(client, moshko_super_admin, fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        org = db.query(Organization).filter(Organization.id == org_id).first()
        org.tax_id = "512345678"
        db.commit()
        acc = _make_account(db, org_id, owner_national_id="000000000", external_id="oo-admin-2")
        account_id = acc.id
    finally:
        db.close()

    resp = client.post(
        f"/api/admin/moshko/ownership-review/{org_id}/resolve",
        json={"account_id": account_id},
        headers=moshko_super_admin["headers"],
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "matched"

    db = SessionLocal()
    try:
        org = db.query(Organization).filter(Organization.id == org_id).first()
        assert org.ownership_reviewed_at is not None
        acc = db.query(Account).filter(Account.id == account_id).first()
        assert acc.is_primary_business_account is True

        log = (
            db.query(AuditLog)
            .filter(AuditLog.organization_id == org_id, AuditLog.action == "RESOLVE")
            .order_by(AuditLog.id.desc())
            .first()
        )
        assert log is not None
        assert log.entity_type == "OwnershipReview"
    finally:
        db.close()

    # Resolved org must drop out of the queue.
    resp2 = client.get("/api/admin/moshko/ownership-review", headers=moshko_super_admin["headers"])
    assert resp2.status_code == 200
    assert all(item["organization_id"] != org_id for item in resp2.json())


def test_resolve_optionally_updates_tax_id(client, moshko_super_admin, fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        acc = _make_account(db, org_id, owner_national_id="512345678", external_id="oo-admin-3")
        account_id = acc.id
    finally:
        db.close()

    resp = client.post(
        f"/api/admin/moshko/ownership-review/{org_id}/resolve",
        json={"account_id": account_id, "tax_id": "512345678"},
        headers=moshko_super_admin["headers"],
    )
    assert resp.status_code == 200, resp.text

    db = SessionLocal()
    try:
        org = db.query(Organization).filter(Organization.id == org_id).first()
        assert org.tax_id == "512345678"
    finally:
        db.close()


def test_resolve_requires_super_admin(client, owner, fresh_org):
    org_id = fresh_org()["org_id"]
    resp = client.post(
        f"/api/admin/moshko/ownership-review/{org_id}/resolve",
        json={"account_id": 1},
        headers=owner["headers"],
    )
    assert resp.status_code == 403


def test_resolve_rejects_account_from_a_different_organization(client, moshko_super_admin, fresh_org):
    org_a = fresh_org()["org_id"]
    org_b = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        acc = _make_account(db, org_b, owner_national_id="512345678", external_id="oo-admin-4")
        account_id = acc.id
    finally:
        db.close()

    resp = client.post(
        f"/api/admin/moshko/ownership-review/{org_a}/resolve",
        json={"account_id": account_id},
        headers=moshko_super_admin["headers"],
    )
    assert resp.status_code in (400, 404)


# --------------------------------------------------------------------- #
# isolation between organizations
# --------------------------------------------------------------------- #
def test_ownership_status_is_isolated_between_organizations(db, fresh_org):
    org_a = fresh_org()["org_id"]
    org_b = fresh_org()["org_id"]

    org_a_row = db.query(Organization).filter(Organization.id == org_a).first()
    org_a_row.tax_id = "512345678"
    db.commit()
    _make_account(db, org_a, owner_national_id="512345678", external_id="oo-iso-a")

    org_b_row = db.query(Organization).filter(Organization.id == org_b).first()
    org_b_row.tax_id = "111111111"
    db.commit()
    _make_account(db, org_b, owner_national_id="999999999", external_id="oo-iso-b")

    result_a = ownership_status(db, org_a)
    result_b = ownership_status(db, org_b)
    assert result_a["status"] == "matched"
    assert result_b["status"] == "needs_review"
