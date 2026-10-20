"""Existing Open Finance consents bind without a provider call.

Reviewed local imports stay in the sum until covers_from. Overlap is linked
by fingerprint and excluded, never deleted. One connection id cannot belong
to two organizations, and the nightly gates are not cleared by the bind.
"""
from datetime import date, datetime
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from cfo.auth import create_access_token
from cfo.database import SessionLocal
from cfo.models import (
    Account, AccountSourceCoverage, AccountType, Alert, BankConnection,
    BankTransaction, IntegrationConnection, OnboardingTask, Organization,
    SyncCheckpoint, SyncRun, User, UserRole,
)
from cfo.services import local_client_service as local
from cfo.services.bank_coverage import (
    OpenFinanceBindError, bind_existing_connection, link_coverage_overlap,
)
from cfo.services.live_cash_flow_service import LiveCashFlowService
from cfo.services.sync_engine import SOURCE_CHECKPOINT_ENTITY, get_connector_for_org


CONNECTION = "01M4RHJB51K4BVH7J5XT63G2S2"


def _super(headers_org):
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.organization_id == headers_org["org_id"]).first()
        user.role = UserRole.SUPER_ADMIN
        db.commit()
        token = create_access_token(data={
            "sub": str(user.id), "role": UserRole.SUPER_ADMIN.value,
            "org_id": user.organization_id,
        })
        return {"headers": {"Authorization": f"Bearer {token}"}, "org_id": user.organization_id}
    finally:
        db.close()


def _import_bank(db, office_id, tax_id="514000166"):
    client = local.register_local_client(db, office_id, name="Foodgroup Test", tax_id=tax_id)
    payload = {
        "kind": "bank",
        "source_name": "reviewed-1662.json",
        "source_sha256": "a" * 64,
        "observed_at": "2026-10-15T12:00:00Z",
        "bank_account_suffix": "1662",
        "rows": [
            {"external_id": "local-jul", "date": "2026-07-21", "amount": "1000.00",
             "description": "Customer receipt", "currency": "ILS"},
            {"external_id": "local-oct", "date": "2026-10-13", "amount": "-6000.00",
             "description": "Supplier payment", "currency": "ILS"},
        ],
    }
    local.import_reviewed_source(db, office_id, client["id"], payload)
    return client


def test_bind_does_not_call_the_provider_or_start_sync(fresh_org, monkeypatch):
    def explode(*_args, **_kwargs):
        raise AssertionError("provider client must not be constructed")

    monkeypatch.setattr("cfo.services.open_finance_connector.OpenFinanceConnector", explode)
    monkeypatch.setattr("cfo.services.open_finance_onboarding.start_bank_connection", explode)
    office = fresh_org()["org_id"]
    with SessionLocal() as db:
        client = _import_bank(db, office)
        org_id = client["target_organization_id"]
        account = db.query(Account).filter_by(organization_id=org_id, source=local.SOURCE).one()
        result = bind_existing_connection(
            db, org_id, connection_id=CONNECTION + "-first", status="ACTIVE",
            coverage={"local_account_id": account.id, "covers_from": date(2026, 10, 14),
                      "bank_account_suffix": "1662"},
        )
        assert result["provider_calls"] == 0
        assert result["kickoff_sync"] is False
        assert result["connect_url"] is None
        assert result["onboarding_tasks_created"] == 0
        assert result["mode"] == "hybrid"
        assert db.query(OnboardingTask).filter_by(organization_id=org_id).count() == 0
        assert db.query(SyncRun).filter_by(organization_id=org_id).count() == 0
        assert db.query(SyncCheckpoint).filter_by(organization_id=org_id).count() == 0
        row = db.query(BankConnection).filter_by(organization_id=org_id).one()
        assert row.connection_id == CONNECTION + "-first" and row.connect_url is None
        again = bind_existing_connection(db, org_id, connection_id=CONNECTION + "-first", status="ACTIVE")
        assert again["created"] is False
        assert db.query(BankConnection).filter_by(connection_id=CONNECTION + "-first").count() == 1
        with pytest.raises(ValueError, match="disabled"):
            get_connector_for_org(db, org_id, "sumit")


def test_connection_cannot_attach_to_a_second_organization(fresh_org):
    office = fresh_org()["org_id"]
    other = fresh_org()["org_id"]
    with SessionLocal() as db:
        client = _import_bank(db, office, "514000167")
        org_id = client["target_organization_id"]
        bind_existing_connection(db, org_id, connection_id=CONNECTION + "-second", status="CONNECTED")
        with pytest.raises(OpenFinanceBindError, match="another organization"):
            bind_existing_connection(db, other, connection_id=CONNECTION + "-second", status="ACTIVE")
        assert db.query(BankConnection).filter_by(organization_id=other).count() == 0


def test_database_rejects_a_second_row_for_the_same_connection(fresh_org):
    org_a, org_b = fresh_org()["org_id"], fresh_org()["org_id"]
    with SessionLocal() as db:
        db.add(BankConnection(organization_id=org_a, source="open_finance",
                              connection_id="unique-consent", status="ACTIVE"))
        db.commit()
        db.add(BankConnection(organization_id=org_b, source="open_finance",
                              connection_id="unique-consent", status="ACTIVE"))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()


def test_non_syncable_status_is_refused_and_gates_still_apply(fresh_org):
    office = fresh_org()["org_id"]
    with SessionLocal() as db:
        client = local.register_local_client(db, office, name="Gate Test", tax_id="514000168")
        org_id = client["target_organization_id"]
        with pytest.raises(OpenFinanceBindError, match="ACTIVE"):
            bind_existing_connection(db, org_id, connection_id="consent-pending", status="PENDING")
        bind_existing_connection(db, org_id, connection_id="consent-live", status="COMPLETED")
        from cfo.api.routes.cron import _daily_budget_gate, _of_consent_gate
        assert _of_consent_gate(db, org_id) is None
        db.add(SyncCheckpoint(
            organization_id=org_id, source="open_finance",
            entity_type=SOURCE_CHECKPOINT_ENTITY, last_success_at=datetime.utcnow(),
        ))
        db.commit()
        gated = _daily_budget_gate(db, org_id, "open_finance")
        assert gated["skipped"] == "daily_budget"


def test_provider_rows_inside_local_coverage_are_not_double_counted(fresh_org):
    office = fresh_org()["org_id"]
    with SessionLocal() as db:
        client = _import_bank(db, office, "514000169")
        org_id = client["target_organization_id"]
        local_account = db.query(Account).filter_by(organization_id=org_id, source=local.SOURCE).one()
        bind_existing_connection(
            db, org_id, connection_id="consent-coverage", status="ACTIVE",
            coverage={"local_account_id": local_account.id, "covers_from": date(2026, 10, 14),
                      "bank_account_suffix": "1662"},
        )
        provider = Account(
            organization_id=org_id, name="Bank 1662", account_type=AccountType.BANK,
            source="open_finance", external_id="of-account-1662", currency="ILS",
            provider_account_number="12-1662", open_finance_connection_id="consent-coverage",
        )
        db.add(provider)
        db.flush()
        from cfo.services.bank_coverage import attach_provider_account
        attach_provider_account(db, provider)
        db.add(BankTransaction(
            organization_id=org_id, source="open_finance", external_id="of-dup",
            account_id=provider.id, transaction_date=date(2026, 10, 13),
            amount=Decimal("-6000.00"), description=" supplier   payment ", currency="ILS",
        ))
        db.add(BankTransaction(
            organization_id=org_id, source="open_finance", external_id="of-new",
            account_id=provider.id, transaction_date=date(2026, 10, 14),
            amount=Decimal("-80.00"), description="Card charge", currency="ILS",
        ))
        db.add(BankTransaction(
            organization_id=org_id, source="open_finance", external_id="of-unmatched",
            account_id=provider.id, transaction_date=date(2026, 9, 1),
            amount=Decimal("25.00"), description="Not in the file", currency="ILS",
        ))
        db.add(BankTransaction(
            organization_id=org_id, source=None, external_id="legacy-null-source",
            transaction_date=date(2026, 8, 1), amount=Decimal("7.00"),
            description="Manual observation", currency="ILS",
        ))
        db.add(BankTransaction(
            organization_id=org_id, source=local.SOURCE, external_id="bank:1662:local-after",
            account_id=local_account.id, transaction_date=date(2026, 10, 14),
            amount=Decimal("-50.00"), description="Only in the file", currency="ILS",
        ))
        db.commit()
        linked = link_coverage_overlap(db, org_id)
        db.commit()
        assert linked["matched"] == 1
        duplicate = db.query(BankTransaction).filter_by(external_id="of-dup").one()
        assert duplicate.superseded_by_id is not None
        kept = db.query(BankTransaction).filter_by(
            organization_id=org_id, external_id="bank:1662:local-oct",
        ).one()
        assert kept.superseded_by_id is None
        report = LiveCashFlowService(db, org_id).monthly_cash_flow(
            months=6, as_of_date=date(2026, 10, 20),
        )
        july = next(m for m in report["months"] if m["month"] == "2026-07")
        october = next(m for m in report["months"] if m["month"] == "2026-10")
        august = next(m for m in report["months"] if m["month"] == "2026-08")
        assert july["inflows"] == 1000.0
        assert october["outflows"] == 6080.0
        assert august["inflows"] == 7.0
        assert report["coverage"]["matched_count"] == 1
        assert report["coverage"]["unmatched_count"] == 0
        assert "Bank 1662" in report["coverage"]["message"]
        assert "before covers_from" in report["coverage"]["message"]
        assert "לא הותאמו" not in report["coverage"]["message"]
        assert "ולכן לא נכללו" not in report["coverage"]["message"]
        assert db.query(BankTransaction).filter_by(organization_id=org_id).count() == 7


def test_non_manual_bank_transaction_requires_an_external_id(fresh_org):
    org_id = fresh_org()["org_id"]
    with SessionLocal() as db:
        db.add(BankTransaction(
            organization_id=org_id, source="open_finance", external_id=None,
            transaction_date=date(2026, 10, 1), amount=Decimal("1.00"),
        ))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()


def test_bind_route_is_super_admin_and_db_only(client, fresh_org, monkeypatch):
    def explode(*_args, **_kwargs):
        raise AssertionError("provider client must not be constructed")

    monkeypatch.setattr("cfo.services.open_finance_connector.OpenFinanceConnector", explode)
    owner = fresh_org()
    denied = client.post(
        f"/api/admin/organizations/{owner['org_id']}/open-finance/bind",
        headers=owner["headers"],
        json={"connection_id": "route-consent", "status": "ACTIVE"},
    )
    assert denied.status_code in (401, 403)
    admin = _super(owner)
    allowed = client.post(
        f"/api/admin/organizations/{owner['org_id']}/open-finance/bind",
        headers=admin["headers"],
        json={"connection_id": "route-consent", "status": "ACTIVE"},
    )
    assert allowed.status_code == 200, allowed.text
    body = allowed.json()
    assert body["provider_calls"] == 0 and body["connect_url"] is None
    assert body["kickoff_sync"] is False


def test_covers_from_must_follow_the_last_local_row(fresh_org):
    office = fresh_org()["org_id"]
    with SessionLocal() as db:
        client = _import_bank(db, office, "514000170")
        org_id = client["target_organization_id"]
        account = db.query(Account).filter_by(organization_id=org_id, source=local.SOURCE).one()
        with pytest.raises(OpenFinanceBindError, match="after the last reviewed"):
            bind_existing_connection(
                db, org_id, connection_id="consent-boundary", status="ACTIVE",
                coverage={"local_account_id": account.id, "covers_from": date(2026, 10, 13),
                          "bank_account_suffix": "1662"},
            )
        result = bind_existing_connection(
            db, org_id, connection_id="consent-boundary", status="ACTIVE",
            coverage={"local_account_id": account.id, "covers_from": date(2026, 10, 14),
                      "bank_account_suffix": "1662"},
        )
        assert result["coverage"]["covers_from"] == "2026-10-14"


def test_unattached_coverage_excludes_provider_rows_before_the_boundary(fresh_org):
    office = fresh_org()["org_id"]
    with SessionLocal() as db:
        client = _import_bank(db, office, "514000171")
        org_id = client["target_organization_id"]
        local_account = db.query(Account).filter_by(organization_id=org_id, source=local.SOURCE).one()
        bind_existing_connection(
            db, org_id, connection_id="consent-unattached", status="ACTIVE",
            coverage={"local_account_id": local_account.id, "covers_from": date(2026, 10, 14),
                      "bank_account_suffix": "1662"},
        )
        provider = Account(
            organization_id=org_id, name="Unlinked 1662", account_type=AccountType.BANK,
            source="open_finance", external_id="of-unlinked", currency="ILS",
            provider_account_number=None,
        )
        db.add(provider)
        db.flush()
        db.add(BankTransaction(
            organization_id=org_id, source="open_finance", external_id="of-before",
            account_id=provider.id, transaction_date=date(2026, 10, 13),
            amount=Decimal("-6000.00"), description="Supplier payment", currency="ILS",
        ))
        db.add(BankTransaction(
            organization_id=org_id, source="open_finance", external_id="of-after",
            account_id=provider.id, transaction_date=date(2026, 10, 14),
            amount=Decimal("-15.00"), description="After the boundary", currency="ILS",
        ))
        from cfo.services.bank_coverage import attach_provider_account
        attach_provider_account(db, provider)
        db.commit()
        report = LiveCashFlowService(db, org_id).monthly_cash_flow(
            months=6, as_of_date=date(2026, 10, 20),
        )
        october = next(m for m in report["months"] if m["month"] == "2026-10")
        assert october["outflows"] == 6015.0
        assert report["coverage"]["provider_account_linked"] is False
        assert "Unlinked 1662" in report["coverage"]["message"]
        assert "UNCLASSIFIED" in report["coverage"]["message"]
        assert "אינו מקושר" not in report["coverage"]["message"]
        alert = db.query(Alert).filter_by(
            organization_id=org_id, alert_type="coverage_accounts_withheld",
        ).one()
        assert str(alert.status.value if hasattr(alert.status, "value") else alert.status) == "active"
        assert "Unlinked 1662" in alert.message and "UNCLASSIFIED" in alert.message
        assert db.query(Alert).filter_by(
            organization_id=org_id, alert_type="coverage_provider_unattached",
            status="active",
        ).count() == 0


def test_zero_unmatched_does_not_keep_an_overlap_row(fresh_org):
    office = fresh_org()["org_id"]
    with SessionLocal() as db:
        client = _import_bank(db, office, "514000172")
        org_id = client["target_organization_id"]
        local_account = db.query(Account).filter_by(organization_id=org_id, source=local.SOURCE).one()
        bind_existing_connection(
            db, org_id, connection_id="consent-matched", status="ACTIVE",
            coverage={"local_account_id": local_account.id, "covers_from": date(2026, 10, 14),
                      "bank_account_suffix": "1662"},
        )
        provider = Account(
            organization_id=org_id, name="Bank 1662", account_type=AccountType.BANK,
            source="open_finance", external_id="of-matched-acct", currency="ILS",
            provider_account_number="12-1662",
        )
        db.add(provider)
        db.flush()
        from cfo.services.bank_coverage import attach_provider_account
        attach_provider_account(db, provider)
        db.add(BankTransaction(
            organization_id=org_id, source="open_finance", external_id="of-same",
            account_id=provider.id, transaction_date=date(2026, 10, 13),
            amount=Decimal("-6000.00"), description="Supplier payment", currency="ILS",
        ))
        db.commit()
        linked = link_coverage_overlap(db, org_id)
        db.commit()
        assert linked["matched"] == 1
        report = LiveCashFlowService(db, org_id).monthly_cash_flow(
            months=6, as_of_date=date(2026, 10, 20),
        )
        october = next(m for m in report["months"] if m["month"] == "2026-10")
        assert october["outflows"] == 6000.0
        assert report["coverage"]["unmatched_count"] == 0
        assert report["coverage"]["matched_count"] == 1
        assert report["coverage"]["message"]
        assert "לא הותאמו" not in report["coverage"]["message"]


def test_provider_account_matches_the_1662_digit_suffix(fresh_org):
    office = fresh_org()["org_id"]
    with SessionLocal() as db:
        client = _import_bank(db, office, "514000173")
        org_id = client["target_organization_id"]
        local_account = db.query(Account).filter_by(organization_id=org_id, source=local.SOURCE).one()
        assert local_account.external_id == "local-bank:1662"
        bind_existing_connection(
            db, org_id, connection_id="consent-suffix", status="ACTIVE",
            coverage={"local_account_id": local_account.id, "covers_from": date(2026, 10, 14),
                      "bank_account_suffix": "1662"},
        )
        from cfo.services.bank_coverage import attach_provider_account
        coverage = db.query(AccountSourceCoverage).filter_by(organization_id=org_id).one()
        unrelated = Account(
            organization_id=org_id, name="Different bank", account_type=AccountType.BANK,
            source="open_finance", external_id="of-other-bank-tail", currency="ILS",
            provider_account_number="31-9999",
        )
        db.add(unrelated)
        db.flush()
        attach_provider_account(db, unrelated)
        db.refresh(coverage)
        assert coverage.superseded_by_account_id is None
        embedded = Account(
            organization_id=org_id, name="Suffix inside a longer number", account_type=AccountType.BANK,
            source="open_finance", external_id="of-embedded-tail", currency="ILS",
            provider_account_number="IL-12-16620",
        )
        db.add(embedded)
        db.flush()
        attach_provider_account(db, embedded)
        db.refresh(coverage)
        assert coverage.superseded_by_account_id is None
        provider = Account(
            organization_id=org_id, name="Masked 1662", account_type=AccountType.BANK,
            source="open_finance", external_id="of-suffix", currency="ILS",
            provider_account_number="IL-12-1662",
        )
        db.add(provider)
        db.flush()
        attach_provider_account(db, provider)
        db.refresh(coverage)
        assert coverage.superseded_by_account_id == provider.id


def test_second_active_open_finance_connection_is_refused(fresh_org):
    org_id = fresh_org()["org_id"]
    with SessionLocal() as db:
        bind_existing_connection(db, org_id, connection_id="consent-one", status="ACTIVE")
        with pytest.raises(OpenFinanceBindError, match="active Open Finance"):
            bind_existing_connection(db, org_id, connection_id="consent-two", status="CONNECTED")
        db.add(BankConnection(
            organization_id=org_id, source="open_finance",
            connection_id="consent-direct", status="ACTIVE",
        ))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
        expired = BankConnection(
            organization_id=org_id, source="open_finance",
            connection_id="consent-expired", status="EXPIRED",
        )
        db.add(expired)
        db.commit()
        assert db.query(BankConnection).filter_by(organization_id=org_id, status="ACTIVE").count() == 1


def test_overlap_is_linked_once_per_sync_page(fresh_org, monkeypatch):
    import asyncio

    from cfo.services.connector_base import FetchResult, NormalizedBankTransaction
    from cfo.services.sync_engine import SyncEngine

    calls = {"n": 0}

    def counted(db, org_id):
        calls["n"] += 1
        return {"matched": 0}

    monkeypatch.setattr("cfo.services.bank_coverage.link_coverage_overlap", counted)
    org_id = fresh_org()["org_id"]

    class Page:
        async def fetch_bank_transactions(self, updated_since=None, cursor=None):
            return FetchResult(items=[
                NormalizedBankTransaction(
                    external_id=f"page-{i}", transaction_date=date(2026, 10, 1),
                    description="row", amount=Decimal("1.00"),
                )
                for i in range(3)
            ])

        def __getattr__(self, name):
            async def empty(**_kwargs):
                return FetchResult()
            return empty

    with SessionLocal() as db:
        engine = SyncEngine(db, Page(), org_id, "open_finance")
        result = asyncio.run(engine._sync_entity_type("bank_transactions"))
        assert result["created"] == 3
    assert calls["n"] == 1


def test_covers_from_that_leaves_a_gap_is_rejected(fresh_org):
    office = fresh_org()["org_id"]
    with SessionLocal() as db:
        client = _import_bank(db, office, "514000174")
        org_id = client["target_organization_id"]
        account = db.query(Account).filter_by(organization_id=org_id, source=local.SOURCE).one()
        with pytest.raises(OpenFinanceBindError, match="day after the last reviewed"):
            bind_existing_connection(
                db, org_id, connection_id="consent-gap", status="ACTIVE",
                coverage={"local_account_id": account.id, "covers_from": date(2026, 10, 17),
                          "bank_account_suffix": "1662"},
            )


def test_gap_days_after_the_local_import_stay_in_the_sum(fresh_org):
    office = fresh_org()["org_id"]
    with SessionLocal() as db:
        client = _import_bank(db, office, "514000175")
        org_id = client["target_organization_id"]
        local_account = db.query(Account).filter_by(organization_id=org_id, source=local.SOURCE).one()
        bind_existing_connection(
            db, org_id, connection_id="consent-gap-sum", status="ACTIVE",
            coverage={"local_account_id": local_account.id, "covers_from": date(2026, 10, 14),
                      "bank_account_suffix": "1662"},
        )
        coverage = db.query(AccountSourceCoverage).filter_by(organization_id=org_id).one()
        coverage.covers_from = date(2026, 10, 17)
        provider = Account(
            organization_id=org_id, name="Bank 1662", account_type=AccountType.BANK,
            source="open_finance", external_id="of-gap", currency="ILS",
            provider_account_number="12-1662",
        )
        db.add(provider)
        db.flush()
        from cfo.services.bank_coverage import attach_provider_account
        attach_provider_account(db, provider)
        db.add(BankTransaction(
            organization_id=org_id, source="open_finance", external_id="of-1014",
            account_id=provider.id, transaction_date=date(2026, 10, 14),
            amount=Decimal("-700.00"), description="Gap day", currency="ILS",
        ))
        db.add(BankTransaction(
            organization_id=org_id, source="open_finance", external_id="of-1018",
            account_id=provider.id, transaction_date=date(2026, 10, 18),
            amount=Decimal("-30.00"), description="After coverage", currency="ILS",
        ))
        db.commit()
        report = LiveCashFlowService(db, org_id).monthly_cash_flow(
            months=6, as_of_date=date(2026, 10, 31),
        )
        october = next(m for m in report["months"] if m["month"] == "2026-10")
        assert october["outflows"] == 6730.0
        assert report["coverage"]["excluded_count"] == 0


def test_unclassified_numbered_account_is_excluded_until_declared_independent(fresh_org):
    """A parseable number is not proof of another bank. It stays UNCLASSIFIED."""
    office = fresh_org()["org_id"]
    with SessionLocal() as db:
        client = _import_bank(db, office, "514000176")
        org_id = client["target_organization_id"]
        local_account = db.query(Account).filter_by(organization_id=org_id, source=local.SOURCE).one()
        bind_existing_connection(
            db, org_id, connection_id="consent-other-bank", status="ACTIVE",
            coverage={"local_account_id": local_account.id, "covers_from": date(2026, 10, 14),
                      "bank_account_suffix": "1662"},
        )
        other = Account(
            organization_id=org_id, name="Other bank", account_type=AccountType.BANK,
            source="open_finance", external_id="of-other-bank", currency="ILS",
            provider_account_number="31-9999",
        )
        db.add(other)
        db.flush()
        db.add(BankTransaction(
            organization_id=org_id, source="open_finance", external_id="of-other-1001",
            account_id=other.id, transaction_date=date(2026, 10, 1),
            amount=Decimal("-2500.00"), description="Other bank", currency="ILS",
        ))
        from cfo.services.bank_coverage import record_unattached_coverage_alert
        record_unattached_coverage_alert(db, org_id)
        db.commit()
        report = LiveCashFlowService(db, org_id).monthly_cash_flow(
            months=6, as_of_date=date(2026, 10, 31),
        )
        october = next(m for m in report["months"] if m["month"] == "2026-10")
        assert october["outflows"] == 6000.0
        assert "Other bank" in report["coverage"]["message"]
        assert "UNCLASSIFIED" in report["coverage"]["message"]
        assert "9999" in report["coverage"]["message"]
        assert report["coverage"]["unmatched_count"] == 0


def test_bind_commits_the_unattached_alert_and_a_read_does_not(fresh_org):
    office = fresh_org()["org_id"]
    with SessionLocal() as db:
        client = _import_bank(db, office, "514000177")
        org_id = client["target_organization_id"]
        local_account = db.query(Account).filter_by(organization_id=org_id, source=local.SOURCE).one()
        local_id = local_account.id
        db.add(AccountSourceCoverage(
            organization_id=org_id, local_account_id=local_id, source=local.SOURCE,
            covers_from=date(2026, 10, 14), bank_account_suffix="1662",
        ))
        db.commit()
    reader = SessionLocal()
    try:
        LiveCashFlowService(reader, org_id).monthly_cash_flow(
            months=6, as_of_date=date(2026, 10, 31),
        )
    finally:
        reader.close()
    with SessionLocal() as db:
        assert db.query(Alert).filter_by(organization_id=org_id).count() == 0
        bind_existing_connection(
            db, org_id, connection_id="consent-alert", status="ACTIVE",
            coverage={"local_account_id": local_id, "covers_from": date(2026, 10, 14),
                      "bank_account_suffix": "1662"},
        )
        assert db.query(Alert).filter_by(
            organization_id=org_id, alert_type="coverage_provider_unattached", status="active",
        ).count() == 0
        provider = Account(
            organization_id=org_id, name="Unlinked feed", account_type=AccountType.BANK,
            source="open_finance", external_id="of-alert-feed", currency="ILS",
            provider_account_number=None,
        )
        db.add(provider)
        db.flush()
        db.add(BankTransaction(
            organization_id=org_id, source="open_finance", external_id="of-alert-tx",
            account_id=provider.id, transaction_date=date(2026, 10, 13),
            amount=Decimal("-6000.00"), description="Supplier payment", currency="ILS",
        ))
        from cfo.services.bank_coverage import attach_provider_account
        attach_provider_account(db, provider)
        db.commit()
    with SessionLocal() as db:
        assert db.query(Alert).filter_by(
            organization_id=org_id, alert_type="coverage_accounts_withheld", status="active",
        ).count() == 1
    reader = SessionLocal()
    try:
        LiveCashFlowService(reader, org_id).monthly_cash_flow(
            months=6, as_of_date=date(2026, 10, 31),
        )
    finally:
        reader.close()
    with SessionLocal() as db:
        assert db.query(Alert).filter_by(
            organization_id=org_id, alert_type="coverage_accounts_withheld", status="active",
        ).count() == 1


def test_sync_commits_the_unattached_coverage_alert(fresh_org):
    import asyncio

    from cfo.services.connector_base import FetchResult
    from cfo.services.sync_engine import SyncEngine

    org_id = fresh_org()["org_id"]
    with SessionLocal() as db:
        account = Account(
            organization_id=org_id, name="Local", account_type=AccountType.BANK,
            source=local.SOURCE, external_id="local-bank:1662", currency="ILS",
        )
        db.add(account)
        db.flush()
        db.add(AccountSourceCoverage(
            organization_id=org_id, local_account_id=account.id, source=local.SOURCE,
            covers_from=date(2026, 10, 14), bank_account_suffix="1662",
        ))
        feed = Account(
            organization_id=org_id, name="Unlinked feed", account_type=AccountType.BANK,
            source="open_finance", external_id="of-sync-feed", currency="ILS",
            provider_account_number=None,
        )
        db.add(feed)
        db.flush()
        db.add(BankTransaction(
            organization_id=org_id, source="open_finance", external_id="of-sync-tx",
            account_id=feed.id, transaction_date=date(2026, 10, 1),
            amount=Decimal("-20.00"), description="Before the import", currency="ILS",
        ))
        db.commit()

    class Page:
        async def fetch_bank_transactions(self, updated_since=None, cursor=None):
            return FetchResult(items=[])

        def __getattr__(self, _name):
            async def empty(**_kwargs):
                return FetchResult()
            return empty

    with SessionLocal() as db:
        engine = SyncEngine(db, Page(), org_id, "open_finance")
        asyncio.run(engine._sync_entity_type("bank_transactions"))
    with SessionLocal() as db:
        assert db.query(Alert).filter_by(
            organization_id=org_id, alert_type="coverage_accounts_withheld", status="active",
        ).count() == 1


def test_renewed_consent_supersedes_the_previous_active_one(fresh_org, monkeypatch):
    import asyncio

    org_id = fresh_org()["org_id"]
    with SessionLocal() as db:
        bind_existing_connection(db, org_id, connection_id="old-consent", status="ACTIVE")
        db.add(BankConnection(
            organization_id=org_id, source="open_finance",
            connection_id="new-consent", status="INACTIVE",
        ))
        db.commit()

    class _Client:
        async def get_connection(self, connection_id):
            assert connection_id == "new-consent"
            return {"status": "ACTIVE", "providerFriendlyId": "leumi"}

        async def close(self):
            return None

    monkeypatch.setattr(
        "cfo.api.routes.open_finance.get_open_finance_client",
        lambda *_args, **_kwargs: _Client(),
    )
    from cfo.services.open_finance_onboarding import get_connection_status

    async def _run():
        db = SessionLocal()
        try:
            return await get_connection_status(db, org_id, "new-consent")
        finally:
            db.close()

    result = asyncio.run(_run())
    assert result["status"] == "ACTIVE"
    with SessionLocal() as db:
        old = db.query(BankConnection).filter_by(connection_id="old-consent").one()
        new = db.query(BankConnection).filter_by(connection_id="new-consent").one()
        assert old.status == "SUPERSEDED"
        assert new.status == "ACTIVE"


def _provider_account(db, org_id, external_id, number):
    from cfo.services.bank_coverage import attach_provider_account

    account = Account(
        organization_id=org_id, name=external_id, account_type=AccountType.BANK,
        source="open_finance", external_id=external_id, currency="ILS",
        provider_account_number=number,
    )
    db.add(account)
    db.flush()
    attach_provider_account(db, account)
    return account


def _provider_tx(db, org_id, account, external_id, day, amount, description="Supplier payment"):
    db.add(BankTransaction(
        organization_id=org_id, source="open_finance", external_id=external_id,
        account_id=account.id, transaction_date=day, amount=Decimal(amount),
        description=description, currency="ILS",
    ))


def _october_outflows(db, org_id):
    report = LiveCashFlowService(db, org_id).monthly_cash_flow(
        months=6, as_of_date=date(2026, 10, 31),
    )
    october = next(month for month in report["months"] if month["month"] == "2026-10")
    return october["outflows"], report


def _bind_covered_import(db, office_id, tax_id, connection_id):
    client = _import_bank(db, office_id, tax_id)
    org_id = client["target_organization_id"]
    account = db.query(Account).filter_by(organization_id=org_id, source=local.SOURCE).one()
    bind_existing_connection(
        db, org_id, connection_id=connection_id, status="ACTIVE",
        coverage={"local_account_id": account.id, "covers_from": date(2026, 10, 14),
                  "bank_account_suffix": "1662"},
    )
    db.commit()
    return org_id


def test_renewed_account_row_with_the_same_number_is_not_counted_twice(fresh_org):
    """A new consent creates a second Account row for the same bank number.

    The coverage is already bound to the first row, so the new row must still
    use that coverage's cutoff. The local import's -6,000 is the only October
    outflow.
    """
    office = fresh_org()["org_id"]
    with SessionLocal() as db:
        org_id = _bind_covered_import(db, office, "514001005", "renew-row")
        _provider_account(db, org_id, "of-acct-consent1", "12-1662")
        second = _provider_account(db, org_id, "of-acct-consent2", "12-1662")
        _provider_tx(db, org_id, second, "c2-1013", date(2026, 10, 13), "-6000.00")
        db.commit()
        outflows, report = _october_outflows(db, org_id)
        assert outflows == 6000.0
        assert report["coverage"]["excluded_count"] >= 1


def test_suffix_contained_before_a_sub_account_is_not_counted_twice(fresh_org):
    """``1662-01`` contains the suffix even though it does not end with it."""
    office = fresh_org()["org_id"]
    with SessionLocal() as db:
        org_id = _bind_covered_import(db, office, "514001006", "suffix-inside")
        feed = _provider_account(db, org_id, "of-1662-01", "1662-01")
        _provider_tx(db, org_id, feed, "f-1013", date(2026, 10, 13), "-6000.00")
        db.commit()
        outflows, report = _october_outflows(db, org_id)
        assert outflows == 6000.0
        assert report["coverage"]["excluded_count"] >= 1


def test_longer_number_that_contains_the_suffix_stays_out_of_the_sum(fresh_org):
    """Over-match fails closed: ``31-16629999`` contains ``1662``."""
    office = fresh_org()["org_id"]
    with SessionLocal() as db:
        org_id = _bind_covered_import(db, office, "514001007", "over-match")
        feed = _provider_account(db, org_id, "of-embedded", "31-16629999")
        _provider_tx(db, org_id, feed, "e-1013", date(2026, 10, 13), "-6000.00")
        db.commit()
        outflows, report = _october_outflows(db, org_id)
        assert outflows == 6000.0
        assert report["coverage"]["message"]


def test_coverage_suffix_must_be_exactly_four_digits(fresh_org):
    office = fresh_org()["org_id"]
    with SessionLocal() as db:
        client = _import_bank(db, office, "514001008")
        org_id = client["target_organization_id"]
        account = db.query(Account).filter_by(organization_id=org_id, source=local.SOURCE).one()
        for suffix in (None, "", "166", "16620", "16-62"):
            with pytest.raises(OpenFinanceBindError, match="exactly 4 digits"):
                bind_existing_connection(
                    db, org_id, connection_id=f"suffix-{suffix}", status="ACTIVE",
                    coverage={"local_account_id": account.id, "covers_from": date(2026, 10, 14),
                              "bank_account_suffix": suffix},
                )


def test_status_refresh_stores_uppercase(fresh_org, monkeypatch):
    import asyncio

    org_id = fresh_org()["org_id"]
    with SessionLocal() as db:
        bind_existing_connection(db, org_id, connection_id="old-lower", status="ACTIVE")
        db.add(BankConnection(
            organization_id=org_id, source="open_finance",
            connection_id="new-lower", status="INACTIVE",
        ))
        db.commit()

    class _Client:
        async def get_connection(self, connection_id):
            return {"status": "active", "providerFriendlyId": "leumi"}

        async def close(self):
            return None

    monkeypatch.setattr(
        "cfo.api.routes.open_finance.get_open_finance_client",
        lambda *_args, **_kwargs: _Client(),
    )
    from cfo.services.open_finance_onboarding import get_connection_status

    async def _run():
        db = SessionLocal()
        try:
            return await get_connection_status(db, org_id, "new-lower")
        finally:
            db.close()

    result = asyncio.run(_run())
    assert result["status"] == "ACTIVE"
    with SessionLocal() as db:
        old = db.query(BankConnection).filter_by(connection_id="old-lower").one()
        new = db.query(BankConnection).filter_by(connection_id="new-lower").one()
        assert old.status == "SUPERSEDED"
        assert new.status == "ACTIVE"


def test_concurrent_consent_refresh_one_wins_and_one_is_409(fresh_org, monkeypatch):
    """Two refreshes overlap. One consent becomes ACTIVE; the other stays INACTIVE."""
    import asyncio
    import threading
    import time

    from cfo.services.open_finance_onboarding import OpenFinanceError, get_connection_status

    org_id = fresh_org()["org_id"]
    with SessionLocal() as db:
        bind_existing_connection(db, org_id, connection_id="race-old", status="ACTIVE")
        db.add(BankConnection(
            organization_id=org_id, source="open_finance",
            connection_id="race-a", status="INACTIVE",
        ))
        db.add(BankConnection(
            organization_id=org_id, source="open_finance",
            connection_id="race-b", status="INACTIVE",
        ))
        db.commit()

    class _Client:
        async def get_connection(self, _connection_id):
            return {"status": "ACTIVE"}

        async def close(self):
            return None

    monkeypatch.setattr(
        "cfo.api.routes.open_finance.get_open_finance_client",
        lambda *_args, **_kwargs: _Client(),
    )
    start = threading.Barrier(2, timeout=10)
    real_supersede = __import__(
        "cfo.services.open_finance_onboarding", fromlist=["supersede_other_live_consents"],
    ).supersede_other_live_consents

    def _overlap(db, organization_id, connection_id):
        start.wait()
        real_supersede(db, organization_id, connection_id)
        time.sleep(0.4)

    monkeypatch.setattr(
        "cfo.services.open_finance_onboarding.supersede_other_live_consents",
        _overlap,
    )

    outcomes = {}

    def _refresh(connection_id):
        async def _run():
            db = SessionLocal()
            try:
                return await get_connection_status(db, org_id, connection_id)
            finally:
                db.close()

        try:
            outcomes[connection_id] = ("ok", asyncio.run(_run()))
        except OpenFinanceError as exc:
            outcomes[connection_id] = ("error", exc.status_code, str(exc))
        except Exception as exc:
            outcomes[connection_id] = ("unexpected", type(exc).__name__, str(exc))

    threads = [
        threading.Thread(target=_refresh, args=("race-a",)),
        threading.Thread(target=_refresh, args=("race-b",)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)

    assert set(outcomes) == {"race-a", "race-b"}
    kinds = sorted(item[0] for item in outcomes.values())
    assert kinds == ["error", "ok"], outcomes
    error = next(item for item in outcomes.values() if item[0] == "error")
    assert error[1] == 409
    assert "active Open Finance" in error[2]
    with SessionLocal() as db:
        statuses = {
            row.connection_id: row.status
            for row in db.query(BankConnection).filter_by(organization_id=org_id)
        }
    assert statuses["race-old"] == "SUPERSEDED"
    live = {statuses["race-a"], statuses["race-b"]}
    assert live == {"ACTIVE", "INACTIVE"}


def _status_value(alert) -> str:
    status = alert.status
    return str(status.value if hasattr(status, "value") else status)


def test_second_account_without_a_number_is_not_counted_twice(fresh_org):
    """A is UNCLASSIFIED when the number lives only in the name."""
    office = fresh_org()["org_id"]
    with SessionLocal() as db:
        org_id = _bind_covered_import(db, office, "514002001", "class-a")
        _provider_account(db, org_id, "of-1", "12-1662")
        second = Account(
            organization_id=org_id, name="Leumi IL62-0108-0000-0000-1662",
            account_type=AccountType.BANK, source="open_finance", external_id="of-2",
            currency="ILS", provider_account_number=None,
        )
        db.add(second)
        db.flush()
        from cfo.services.bank_coverage import attach_provider_account
        attach_provider_account(db, second)
        _provider_tx(db, org_id, second, "s-1013", date(2026, 10, 13), "-6000.00")
        from cfo.services.bank_coverage import record_unattached_coverage_alert
        record_unattached_coverage_alert(db, org_id)
        db.commit()
        outflows, report = _october_outflows(db, org_id)
        assert outflows == 6000.0
        message = report["coverage"]["message"]
        assert "Leumi" in message and "1662" in message and "UNCLASSIFIED" in message
        assert report["coverage"]["unmatched_count"] == 0


def test_second_local_import_without_coverage_is_not_counted_twice(fresh_org):
    """B: a local import with no coverage still withholds the matching feed."""
    office = fresh_org()["org_id"]
    with SessionLocal() as db:
        client = _import_bank(db, office, "514002002")
        org_id = client["target_organization_id"]
        account = db.query(Account).filter_by(organization_id=org_id, source=local.SOURCE).one()
        bind_existing_connection(
            db, org_id, connection_id="class-b", status="ACTIVE",
            coverage={"local_account_id": account.id, "covers_from": date(2026, 10, 14),
                      "bank_account_suffix": "1662"},
        )
        local.import_reviewed_source(db, office, client["id"], {
            "kind": "bank", "source_name": "reviewed-5555.json", "source_sha256": "b" * 64,
            "observed_at": "2026-10-15T12:00:00Z", "bank_account_suffix": "5555",
            "rows": [{"external_id": "l5-1010", "date": "2026-10-10", "amount": "-400.00",
                      "description": "Rent", "currency": "ILS"}],
        })
        feed = _provider_account(db, org_id, "of-5555", "20-5555")
        _provider_tx(db, org_id, feed, "f5-1010", date(2026, 10, 10), "-400.00", "Rent")
        db.commit()
        outflows, report = _october_outflows(db, org_id)
        assert outflows == 6400.0
        assert "UNCLASSIFIED" in report["coverage"]["message"]
        assert "5555" in report["coverage"]["message"]


def test_overmatch_names_the_excluded_account_in_the_note_and_the_alert(fresh_org):
    """C: 31-16629999 stays out, and the note and alert name it."""
    office = fresh_org()["org_id"]
    with SessionLocal() as db:
        org_id = _bind_covered_import(db, office, "514002003", "class-c")
        _provider_account(db, org_id, "of-1662", "12-1662")
        other = Account(
            organization_id=org_id, name="Discount 31-16629999", account_type=AccountType.BANK,
            source="open_finance", external_id="of-other", currency="ILS",
            provider_account_number="31-16629999",
        )
        db.add(other)
        db.flush()
        from cfo.services.bank_coverage import attach_provider_account, record_unattached_coverage_alert
        attach_provider_account(db, other)
        _provider_tx(db, org_id, other, "o-1001", date(2026, 10, 1), "-2500.00", "Other bank")
        record_unattached_coverage_alert(db, org_id)
        db.commit()
        outflows, report = _october_outflows(db, org_id)
        assert outflows == 6000.0
        message = report["coverage"]["message"]
        assert "9999" in message and "Discount" in message and "UNCLASSIFIED" in message
        assert report["coverage"]["unmatched_count"] == 0
        alert = db.query(Alert).filter_by(
            organization_id=org_id, alert_type="coverage_accounts_withheld",
        ).one()
        assert _status_value(alert) == "active"
        assert "9999" in (alert.message or "") and "Discount" in (alert.message or "")
        assert db.query(Alert).filter_by(
            organization_id=org_id, alert_type="coverage_provider_unattached", status="active",
        ).count() == 0


def test_two_coverages_keep_only_the_post_cutoff_feed(fresh_org):
    office = fresh_org()["org_id"]
    with SessionLocal() as db:
        client = _import_bank(db, office, "514002004")
        org_id = client["target_organization_id"]
        account = db.query(Account).filter_by(organization_id=org_id, source=local.SOURCE).one()
        bind_existing_connection(
            db, org_id, connection_id="class-d", status="ACTIVE",
            coverage={"local_account_id": account.id, "covers_from": date(2026, 10, 14),
                      "bank_account_suffix": "1662"},
        )
        local.import_reviewed_source(db, office, client["id"], {
            "kind": "bank", "source_name": "reviewed-5555.json", "source_sha256": "c" * 64,
            "observed_at": "2026-10-15T12:00:00Z", "bank_account_suffix": "5555",
            "rows": [{"external_id": "l5-1010", "date": "2026-10-10", "amount": "-400.00",
                      "description": "Rent", "currency": "ILS"}],
        })
        second = next(
            row for row in db.query(Account).filter_by(organization_id=org_id, source=local.SOURCE)
            if (row.external_id or "").endswith("5555")
        )
        bind_existing_connection(
            db, org_id, connection_id="class-d", status="ACTIVE",
            coverage={"local_account_id": second.id, "covers_from": date(2026, 10, 11),
                      "bank_account_suffix": "5555"},
        )
        first = _provider_account(db, org_id, "of-1662", "12-1662")
        feed = _provider_account(db, org_id, "of-5555", "20-5555")
        _provider_tx(db, org_id, first, "f1-1013", date(2026, 10, 13), "-6000.00")
        _provider_tx(db, org_id, feed, "f5-1010", date(2026, 10, 10), "-400.00", "Rent")
        _provider_tx(db, org_id, feed, "f5-1012", date(2026, 10, 12), "-50.00", "After 5555 cutoff")
        db.commit()
        outflows, _report = _october_outflows(db, org_id)
        assert outflows == 6450.0


def test_independent_account_counts_fully_and_resolves_the_alert(fresh_org):
    office = fresh_org()
    with SessionLocal() as db:
        user = db.query(User).filter_by(organization_id=office["org_id"]).one()
        client = _import_bank(db, office["org_id"], "514002007")
        org_id = client["target_organization_id"]
        local_account = db.query(Account).filter_by(organization_id=org_id, source=local.SOURCE).one()
        bind_existing_connection(
            db, org_id, connection_id="class-ind", status="ACTIVE",
            coverage={"local_account_id": local_account.id, "covers_from": date(2026, 10, 14),
                      "bank_account_suffix": "1662"},
        )
        other = Account(
            organization_id=org_id, name="Other bank", account_type=AccountType.BANK,
            source="open_finance", external_id="of-independent", currency="ILS",
            provider_account_number="31-9999",
        )
        db.add(other)
        db.flush()
        db.add(BankTransaction(
            organization_id=org_id, source="open_finance", external_id="of-ind-tx",
            account_id=other.id, transaction_date=date(2026, 10, 1),
            amount=Decimal("-2500.00"), description="Other bank", currency="ILS",
        ))
        from cfo.services.bank_coverage import classify_open_finance_account, record_unattached_coverage_alert
        record_unattached_coverage_alert(db, org_id)
        db.commit()
        account_id = other.id
        actor_id = user.id
        outflows, report = _october_outflows(db, org_id)
        assert outflows == 6000.0
        assert "UNCLASSIFIED" in report["coverage"]["message"]
        classify_open_finance_account(
            db, org_id, account_id, state="INDEPENDENT", coverage_id=None, actor_id=actor_id,
        )
    with SessionLocal() as db:
        outflows, report = _october_outflows(db, org_id)
        assert outflows == 8500.0
        assert report["coverage"]["message"] is None or "UNCLASSIFIED" not in (report["coverage"]["message"] or "")
        alert = db.query(Alert).filter_by(
            organization_id=org_id, alert_type="coverage_accounts_withheld",
        ).one()
        assert _status_value(alert) == "resolved"
        from cfo.models import AuditLog
        audit = db.query(AuditLog).filter_by(
            organization_id=org_id, action="CLASSIFY_OPEN_FINANCE_ACCOUNT",
        ).one()
        assert audit.entity_id == account_id
        assert audit.details["state"] == "INDEPENDENT"


def test_org_without_a_local_import_counts_every_provider_row(fresh_org):
    org_id = fresh_org()["org_id"]
    with SessionLocal() as db:
        account = Account(
            organization_id=org_id, name="Only feed", account_type=AccountType.BANK,
            source="open_finance", external_id="of-only", currency="ILS",
            provider_account_number="31-9999",
        )
        db.add(account)
        db.flush()
        db.add(BankTransaction(
            organization_id=org_id, source="open_finance", external_id="of-only-tx",
            account_id=account.id, transaction_date=date(2026, 10, 1),
            amount=Decimal("-2500.00"), description="Feed only", currency="ILS",
        ))
        db.commit()
        outflows, report = _october_outflows(db, org_id)
        assert outflows == 2500.0
        assert report.get("coverage") is None


def test_non_admin_cannot_classify_an_open_finance_account(client, fresh_org):
    office = fresh_org()
    outsider = fresh_org()
    with SessionLocal() as db:
        client_row = _import_bank(db, office["org_id"], "514002008")
        org_id = client_row["target_organization_id"]
        local_account = db.query(Account).filter_by(organization_id=org_id, source=local.SOURCE).one()
        bind_existing_connection(
            db, org_id, connection_id="class-auth", status="ACTIVE",
            coverage={"local_account_id": local_account.id, "covers_from": date(2026, 10, 14),
                      "bank_account_suffix": "1662"},
        )
        other = Account(
            organization_id=org_id, name="Other bank", account_type=AccountType.BANK,
            source="open_finance", external_id="of-auth", currency="ILS",
            provider_account_number="31-9999",
        )
        db.add(other)
        db.commit()
        account_id = other.id
        coverage = db.query(AccountSourceCoverage).filter_by(organization_id=org_id).one()
        coverage_id = coverage.id
    denied = client.post(
        f"/api/admin/organizations/{org_id}/open-finance/accounts/{account_id}/classification",
        headers=outsider["headers"],
        json={"state": "INDEPENDENT"},
    )
    assert denied.status_code == 403
    allowed = client.post(
        f"/api/admin/organizations/{org_id}/open-finance/accounts/{account_id}/classification",
        headers=office["headers"],
        json={"state": "BOUND", "coverage_id": coverage_id},
    )
    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["state"] == "BOUND"
    with SessionLocal() as db:
        from cfo.models import AuditLog
        audit = db.query(AuditLog).filter_by(
            organization_id=org_id, action="CLASSIFY_OPEN_FINANCE_ACCOUNT",
        ).one()
        assert audit.details["coverage_id"] == coverage_id
