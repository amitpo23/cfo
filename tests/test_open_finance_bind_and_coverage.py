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
        assert report["coverage"]["unmatched_count"] == 2
        assert "לא הותאמו" in report["coverage"]["message"]
        assert "כי התאריך שלהן שייך למקור האחר" in report["coverage"]["message"]
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
            provider_account_number="99-0000",
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
        db.commit()
        report = LiveCashFlowService(db, org_id).monthly_cash_flow(
            months=6, as_of_date=date(2026, 10, 20),
        )
        october = next(m for m in report["months"] if m["month"] == "2026-10")
        assert october["outflows"] == 6015.0
        assert report["coverage"]["provider_account_linked"] is False
        assert "אינו מקושר" in report["coverage"]["message"]
        alert = db.query(Alert).filter_by(
            organization_id=org_id, alert_type="coverage_provider_unattached",
        ).one()
        assert str(alert.status.value if hasattr(alert.status, "value") else alert.status) == "active"


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
        provider = Account(
            organization_id=org_id, name="Masked 1662", account_type=AccountType.BANK,
            source="open_finance", external_id="of-suffix", currency="ILS",
            provider_account_number="IL-12-1662",
        )
        other = Account(
            organization_id=org_id, name="Different tail", account_type=AccountType.BANK,
            source="open_finance", external_id="of-other-tail", currency="ILS",
            provider_account_number="IL-12-16620",
        )
        db.add_all([provider, other])
        db.flush()
        from cfo.services.bank_coverage import attach_provider_account
        attach_provider_account(db, other)
        coverage = db.query(AccountSourceCoverage).filter_by(organization_id=org_id).one()
        assert coverage.superseded_by_account_id is None
        attach_provider_account(db, provider)
        db.flush()
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
