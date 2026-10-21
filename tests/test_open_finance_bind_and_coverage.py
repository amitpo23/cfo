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
    BankTransaction, IntegrationConnection, OfAccountClassification,
    OnboardingTask, Organization, OrganizationMembership, SumitCompany,
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
        assert "לפני תחילת כיסוי" in report["coverage"]["message"]
        from cfo.services.bank_coverage import refresh_coverage_alert
        refresh_coverage_alert(db, org_id)
        db.commit()
        assert db.query(Alert).filter_by(
            organization_id=org_id, alert_type="coverage_accounts_withheld", status="active",
        ).count() == 0
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
        assert "לא מסווג" in report["coverage"]["message"]
        assert report["coverage"]["excluded_accounts"][0]["reason"] == "UNCLASSIFIED"
        assert "אינו מקושר" not in report["coverage"]["message"]
        alert = db.query(Alert).filter_by(
            organization_id=org_id, alert_type="coverage_accounts_withheld",
        ).one()
        assert str(alert.status.value if hasattr(alert.status, "value") else alert.status) == "active"
        assert "Unlinked 1662" in alert.message and "לא מסווג" in alert.message
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
        assert "לא מסווג" in report["coverage"]["message"]
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
        assert "Leumi" in message and "1662" in message and "לא מסווג" in message
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
        assert "לא מסווג" in report["coverage"]["message"]
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
        assert "9999" in message and "Discount" in message and "לא מסווג" in message
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


def test_independent_account_counts_fully_and_is_named_in_the_alert(fresh_org):
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
        assert "לא מסווג" in report["coverage"]["message"]
        classify_open_finance_account(
            db, org_id, account_id, state="INDEPENDENT", coverage_id=None, actor_id=actor_id,
        )
    with SessionLocal() as db:
        outflows, report = _october_outflows(db, org_id)
        assert outflows == 8500.0
        message = report["coverage"]["message"]
        assert "לא מסווג" not in message
        assert "נספר במלואו" in message and "עצמאי" in message and "Iso" in message
        assert "classified_by_user_id" not in message
        line = report["coverage"]["excluded_accounts"][0]
        assert line["reason"] == "INDEPENDENT"
        assert "כניסות" in message and "יציאות" in message
        alert = db.query(Alert).filter_by(
            organization_id=org_id, alert_type="coverage_accounts_withheld",
        ).one()
        assert _status_value(alert) == "active"
        assert "עצמאי" in alert.message and "Iso" in alert.message
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


def _headers_for(user, role):
    return {"Authorization": "Bearer " + create_access_token(
        data={"sub": str(user.id), "role": role.value, "org_id": user.organization_id},
    )}


def test_independent_is_refused_when_the_number_ends_with_a_local_suffix(fresh_org):
    office = fresh_org()
    with SessionLocal() as db:
        org_id = _bind_covered_import(db, office["org_id"], "514002011", "class-p1")
        account = _provider_account(db, org_id, "of-1662", "12-1662")
        _provider_tx(db, org_id, account, "p1-1013", date(2026, 10, 13), "-6000.00")
        db.commit()
        from cfo.services.bank_coverage import classify_open_finance_account
        actor = db.query(User).filter_by(organization_id=office["org_id"]).one()
        with pytest.raises(OpenFinanceBindError, match="INDEPENDENT is refused"):
            classify_open_finance_account(
                db, org_id, account.id, state="INDEPENDENT", coverage_id=None, actor_id=actor.id,
            )
        state = db.query(OfAccountClassification).filter_by(account_id=account.id).one()
        assert state.state == "BOUND"
        outflows, _report = _october_outflows(db, org_id)
        assert outflows == 6000.0


def test_independent_route_refuses_a_covered_account_with_409(client, fresh_org):
    office = fresh_org()
    with SessionLocal() as db:
        org_id = _bind_covered_import(db, office["org_id"], "514002012", "class-p1-route")
        account = _provider_account(db, org_id, "of-1662", "12-1662")
        db.commit()
        account_id = account.id
    response = client.post(
        f"/api/admin/organizations/{org_id}/open-finance/accounts/{account_id}/classification",
        headers=office["headers"],
        json={"state": "INDEPENDENT"},
    )
    assert response.status_code == 409, response.text
    assert "INDEPENDENT is refused" in response.text
    with SessionLocal() as db:
        state = db.query(OfAccountClassification).filter_by(account_id=account_id).one()
        assert state.state == "BOUND"


def test_second_bound_to_the_same_coverage_is_refused(fresh_org):
    office = fresh_org()
    with SessionLocal() as db:
        org_id = _bind_covered_import(db, office["org_id"], "514002013", "class-p1b")
        first = _provider_account(db, org_id, "of-a", "12-1662")
        second = _provider_account(db, org_id, "of-b", "12-1662")
        for account, external in ((first, "a"), (second, "b")):
            _provider_tx(db, org_id, account, f"{external}-1015", date(2026, 10, 15), "-700.00", "Post cutoff")
        db.commit()
        coverage = db.query(AccountSourceCoverage).filter_by(organization_id=org_id).one()
        actor = db.query(User).filter_by(organization_id=office["org_id"]).one()
        from cfo.services.bank_coverage import classify_open_finance_account
        classify_open_finance_account(
            db, org_id, first.id, state="BOUND", coverage_id=coverage.id, actor_id=actor.id,
        )
        with pytest.raises(OpenFinanceBindError, match="already bound"):
            classify_open_finance_account(
                db, org_id, second.id, state="BOUND", coverage_id=coverage.id, actor_id=actor.id,
            )
        outflows, report = _october_outflows(db, org_id)
        assert outflows == 6700.0
        assert "כפול" in report["coverage"]["message"]
        assert "1662" in report["coverage"]["message"]
        duplicate = next(item for item in report["coverage"]["excluded_accounts"] if item["reason"] == "duplicate")
        assert duplicate["reason"] == "duplicate"


def test_database_rejects_a_second_bound_row_for_one_coverage(fresh_org):
    office = fresh_org()["org_id"]
    with SessionLocal() as db:
        org_id = _bind_covered_import(db, office, "514002014", "class-unique")
        coverage = db.query(AccountSourceCoverage).filter_by(organization_id=org_id).one()
        first = _provider_account(db, org_id, "of-a", "12-1662")
        second = _provider_account(db, org_id, "of-b", "31-8888")
        assert db.query(OfAccountClassification).filter_by(account_id=first.id, state="BOUND").count() == 1
        db.add(OfAccountClassification(
            organization_id=org_id, account_id=second.id, state="BOUND", coverage_id=coverage.id,
        ))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()


@pytest.mark.parametrize("admin_bound", [False, True])
def test_duplicate_digit_rows_count_one_account(fresh_org, admin_bound):
    office = fresh_org()
    with SessionLocal() as db:
        org_id = _bind_covered_import(
            db, office["org_id"],
            "514002015" if admin_bound else "514002016",
            f"class-p3-{admin_bound}",
        )
        old = _provider_account(db, org_id, "of-old", "12-1662")
        _provider_tx(db, org_id, old, "o-1013", date(2026, 10, 13), "-6000.00")
        _provider_tx(db, org_id, old, "o-1015", date(2026, 10, 15), "-700.00", "Post cutoff")
        db.commit()
        if admin_bound:
            coverage = db.query(AccountSourceCoverage).filter_by(organization_id=org_id).one()
            actor = db.query(User).filter_by(organization_id=office["org_id"]).one()
            from cfo.services.bank_coverage import classify_open_finance_account
            classify_open_finance_account(
                db, org_id, old.id, state="BOUND", coverage_id=coverage.id, actor_id=actor.id,
            )
        new = _provider_account(db, org_id, "of-new", "12-1662")
        _provider_tx(db, org_id, new, "n-1013", date(2026, 10, 13), "-6000.00")
        _provider_tx(db, org_id, new, "n-1015", date(2026, 10, 15), "-700.00", "Post cutoff")
        db.commit()
        outflows, report = _october_outflows(db, org_id)
        assert outflows == 6700.0
        assert "כפול" in report["coverage"]["message"]
        assert "••••1662" in report["coverage"]["message"]
        assert any(item["reason"] == "duplicate" for item in report["coverage"]["excluded_accounts"])


def test_renewal_carries_bound_onto_the_new_consent_row(fresh_org):
    office = fresh_org()["org_id"]
    with SessionLocal() as db:
        org_id = _bind_covered_import(db, office, "514002017", "carry-old")
        actor = db.query(User).filter_by(organization_id=office).one()
        old = Account(
            organization_id=org_id, name="old", account_type=AccountType.BANK,
            source="open_finance", external_id="of-old", currency="ILS",
            provider_account_number="12-1662", open_finance_connection_id="carry-old",
        )
        db.add(old)
        db.flush()
        from cfo.services.bank_coverage import attach_provider_account, classify_open_finance_account
        attach_provider_account(db, old)
        coverage = db.query(AccountSourceCoverage).filter_by(organization_id=org_id).one()
        classify_open_finance_account(
            db, org_id, old.id, state="BOUND", coverage_id=coverage.id, actor_id=actor.id,
        )
        db.add(BankConnection(
            organization_id=org_id, source="open_finance",
            connection_id="carry-new", status="INACTIVE",
        ))
        new = Account(
            organization_id=org_id, name="new", account_type=AccountType.BANK,
            source="open_finance", external_id="of-new", currency="ILS",
            provider_account_number="12-1662", open_finance_connection_id="carry-new",
        )
        db.add(new)
        db.flush()
        attach_provider_account(db, new)
        _provider_tx(db, org_id, old, "o-1015", date(2026, 10, 15), "-700.00", "Post cutoff")
        _provider_tx(db, org_id, new, "n-1015", date(2026, 10, 15), "-700.00", "Post cutoff")
        from cfo.services.bank_coverage import supersede_other_live_consents
        supersede_other_live_consents(db, org_id, "carry-new")
        new_conn = db.query(BankConnection).filter_by(connection_id="carry-new").one()
        new_conn.status = "ACTIVE"
        db.commit()
        moved = db.query(OfAccountClassification).filter_by(account_id=new.id).one()
        assert moved.state == "BOUND"
        assert moved.coverage_id == coverage.id
        assert moved.classified_by_user_id == actor.id
        assert db.query(OfAccountClassification).filter_by(account_id=old.id).count() == 0
        outflows, report = _october_outflows(db, org_id)
        assert outflows == 6700.0
        assert "כפול" in report["coverage"]["message"]


def test_numberless_account_stays_unclassified(fresh_org):
    office = fresh_org()["org_id"]
    with SessionLocal() as db:
        org_id = _bind_covered_import(db, office, "514002018", "class-empty")
        blank = Account(
            organization_id=org_id, name="No number", account_type=AccountType.BANK,
            source="open_finance", external_id="of-blank", currency="ILS",
            provider_account_number=None,
        )
        db.add(blank)
        db.flush()
        from cfo.services.bank_coverage import attach_provider_account
        attach_provider_account(db, blank)
        db.commit()
        assert db.query(OfAccountClassification).filter_by(account_id=blank.id).count() == 0


def test_withheld_amount_is_net_plus_inflow_and_outflow(fresh_org):
    office = fresh_org()["org_id"]
    with SessionLocal() as db:
        org_id = _bind_covered_import(db, office, "514002019", "class-net")
        other = Account(
            organization_id=org_id, name="Other bank", account_type=AccountType.BANK,
            source="open_finance", external_id="of-net", currency="ILS",
            provider_account_number="31-9999",
        )
        db.add(other)
        db.flush()
        _provider_tx(db, org_id, other, "net-in", date(2026, 10, 1), "1000.00", "In")
        _provider_tx(db, org_id, other, "net-out", date(2026, 10, 2), "-1000.00", "Out")
        from cfo.services.bank_coverage import record_unattached_coverage_alert
        record_unattached_coverage_alert(db, org_id)
        db.commit()
        _outflows, report = _october_outflows(db, org_id)
        line = next(item for item in report["coverage"]["excluded_accounts"] if item["reason"] == "UNCLASSIFIED")
        assert line["net_amount"] == 0.0
        assert line["inflow_amount"] == 1000.0
        assert line["outflow_amount"] == 1000.0
        assert "2000" not in report["coverage"]["message"]
        assert "כניסות 1000.00" in report["coverage"]["message"]
        assert "יציאות 1000.00" in report["coverage"]["message"]


def test_public_coverage_note_hides_internal_ids():
    from cfo.services.bank_coverage import redact_public_coverage
    note = redact_public_coverage({
        "excluded_count": 1,
        "organization_id": 9,
        "message": "Other bank ••••9999: -10.00 (כניסות 0.00, יציאות 10.00) לא נספר (לא מסווג)",
        "excluded_accounts": [{
            "account_id": 41,
            "coverage_id": 8,
            "organization_id": 9,
            "classified_by_user_id": 3,
            "label": "Other bank",
            "masked_number": "••••9999",
            "reason": "UNCLASSIFIED",
            "net_amount": -10.0,
            "inflow_amount": 0.0,
            "outflow_amount": 10.0,
        }],
    })
    assert "organization_id" not in note
    account = note["excluded_accounts"][0]
    assert account["label"] == "Other bank"
    assert account["masked_number"] == "••••9999"
    assert account["reason"] == "UNCLASSIFIED"
    for key in ("account_id", "coverage_id", "organization_id", "classified_by_user_id"):
        assert key not in account
    assert "41" not in note["message"]


def test_local_import_and_deletion_recompute_the_alert(fresh_org):
    office = fresh_org()
    with SessionLocal() as db:
        client = _import_bank(db, office["org_id"], "514002020")
        org_id = client["target_organization_id"]
        account = db.query(Account).filter_by(organization_id=org_id, source=local.SOURCE).one()
        bind_existing_connection(
            db, org_id, connection_id="class-p4", status="ACTIVE",
            coverage={"local_account_id": account.id, "covers_from": date(2026, 10, 14),
                      "bank_account_suffix": "1662"},
        )
        other = Account(
            organization_id=org_id, name="Other bank", account_type=AccountType.BANK,
            source="open_finance", external_id="of-p4", currency="ILS",
            provider_account_number="31-9999",
        )
        db.add(other)
        db.flush()
        _provider_tx(db, org_id, other, "p4-1001", date(2026, 10, 1), "-2500.00", "Other")
        from cfo.services.bank_coverage import record_unattached_coverage_alert
        record_unattached_coverage_alert(db, org_id)
        db.commit()
        assert _status_value(db.query(Alert).filter_by(
            organization_id=org_id, alert_type="coverage_accounts_withheld",
        ).one()) == "active"
        db.query(BankTransaction).filter_by(
            organization_id=org_id, source=local.SOURCE, transaction_date=date(2026, 10, 13),
        ).delete()
        db.commit()
        assert _status_value(db.query(Alert).filter_by(
            organization_id=org_id, alert_type="coverage_accounts_withheld",
        ).one()) == "resolved"
        local.import_reviewed_source(db, office["org_id"], client["id"], {
            "kind": "bank", "source_name": "reviewed-later.json", "source_sha256": "e" * 64,
            "observed_at": "2026-10-20T12:00:00Z", "bank_account_suffix": "1662",
            "rows": [{"external_id": "local-1018", "date": "2026-10-18", "amount": "-10.00",
                      "description": "late local", "currency": "ILS"}],
        })
        alert = db.query(Alert).filter_by(
            organization_id=org_id, alert_type="coverage_accounts_withheld",
        ).one()
        assert _status_value(alert) == "active"
        assert "לא מסווג" in alert.message


def test_classification_requires_office_admin_of_a_different_office(client, fresh_org):
    office = fresh_org()
    client_home = fresh_org()
    super_home = fresh_org()
    with SessionLocal() as db:
        org_id = _bind_covered_import(db, office["org_id"], "514002021", "class-authz")
        other = Account(
            organization_id=org_id, name="Other bank", account_type=AccountType.BANK,
            source="open_finance", external_id="of-authz", currency="ILS",
            provider_account_number="31-9999",
        )
        db.add(other)
        db.flush()
        client_user = db.query(User).filter_by(organization_id=client_home["org_id"]).one()
        db.add(OrganizationMembership(
            organization_id=org_id, user_id=client_user.id, role=UserRole.ADMIN, status="active",
        ))
        super_user = db.query(User).filter_by(organization_id=super_home["org_id"]).one()
        super_user.role = UserRole.SUPER_ADMIN
        db.commit()
        account_id = other.id
        client_headers = _headers_for(client_user, UserRole.ADMIN)
        super_headers = _headers_for(super_user, UserRole.SUPER_ADMIN)
    url = f"/api/admin/organizations/{org_id}/open-finance/accounts/{account_id}/classification"
    body = {"state": "INDEPENDENT"}
    assert client.post(url, headers=client_headers, json=body).status_code == 403
    assert client.post(url, headers=super_headers, json=body).status_code == 403
    assert client.post(url, headers=office["headers"], json=body).status_code == 200
    with SessionLocal() as db:
        for row in db.query(SumitCompany).filter_by(target_organization_id=org_id):
            row.status = "inactive"
        db.query(OfAccountClassification).filter_by(account_id=account_id).delete()
        db.commit()
    assert client.post(url, headers=client_headers, json=body).status_code == 403
    assert client.post(url, headers=super_headers, json=body).status_code == 403
    assert client.post(url, headers=office["headers"], json=body).status_code == 403


def _strings_and_keys(value):
    """Every string value and dict key in a JSON payload, recursively."""
    if isinstance(value, dict):
        for key, item in value.items():
            yield str(key)
            yield from _strings_and_keys(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _strings_and_keys(item)
    elif isinstance(value, str):
        yield value


def _assert_no_staff_identity(payload, secrets):
    for text in _strings_and_keys(payload):
        for secret in secrets:
            assert secret.casefold() not in text.casefold(), (secret, text)
        assert "user_id" not in text and "actor" not in text, text


@pytest.mark.parametrize("full_name, tax_id", [
    ("Zerubavel Quintanilla-Staffer", "514002301"),
    ("", "514002302"),
])
def test_public_dashboard_never_names_the_staff_member_behind_independent(client, fresh_org, full_name, tax_id):
    from cfo.models import AuditLog, ClientDashboard, PublishedSnapshot
    from cfo.services.bank_coverage import classify_open_finance_account
    from cfo.services.dashboards import view_model

    office = fresh_org()
    local_part = f"quintanilla.staffer{tax_id}"
    email = f"{local_part}@privacy-example.co.il"
    slug = f"privacy-{tax_id}"
    with SessionLocal() as db:
        org_id = _bind_covered_import(db, office["org_id"], tax_id, f"priv-{tax_id}")
        staff = User(
            organization_id=office["org_id"], email=email, password_hash="x",
            full_name=full_name, role=UserRole.ADMIN, is_active=True, token_version=0,
        )
        db.add(staff)
        other = _provider_account(db, org_id, f"of-priv-{tax_id}", "31-9999")
        _provider_tx(db, org_id, other, f"of-priv-tx-{tax_id}", date(2026, 10, 1), "-2500.00")
        db.commit()
        staff_id = staff.id
        account_id = other.id
        classify_open_finance_account(
            db, org_id, account_id, state="INDEPENDENT", coverage_id=None, actor_id=staff_id,
        )
        dashboard = ClientDashboard(
            slug=slug, title="פרטיות", primary_organization_id=org_id,
            template="generic", access_mode="public", status="active",
        )
        db.add(dashboard)
        db.commit()
        dashboard_id = dashboard.id

        # Internal views and the audit trail keep the full identity.
        shown = full_name or email
        note = LiveCashFlowService(db, org_id).monthly_cash_flow(
            months=10, as_of_date=date.today(),
        )["coverage"]
        assert shown in note["message"]
        assert note["excluded_accounts"][0]["actor_name"] == shown
        alert = db.query(Alert).filter_by(
            organization_id=org_id, alert_type="coverage_accounts_withheld",
        ).one()
        assert shown in alert.message
        assert alert.meta["accounts"][0]["actor_name"] == shown
        audit = db.query(AuditLog).filter_by(
            organization_id=org_id, action="CLASSIFY_OPEN_FINANCE_ACCOUNT",
        ).one()
        assert audit.user_id == staff_id
        klass = db.query(OfAccountClassification).filter_by(account_id=account_id).one()
        assert klass.classified_by_user_id == staff_id

    secrets = [email, local_part] + ([full_name] + full_name.split() if full_name else [])
    label = "נקבע על ידי משרד הנהלת החשבונות ב-"

    live = client.get(f"/api/public/d/{slug}")
    assert live.status_code == 200, live.text
    assert live.json()["source"] == "live"
    _assert_no_staff_identity(live.json(), secrets)
    assert label in live.json()["cashflow"]["coverage"]["message"]

    with SessionLocal() as db:
        row = db.get(ClientDashboard, dashboard_id)
        view_model.publish_view(db, row, view_model.build_view(
            db, org_id, date(date.today().year, 1, 1), date.today(),
        ))
    published = client.get(f"/api/public/d/{slug}")
    assert published.status_code == 200, published.text
    assert published.json()["source"] == "snapshot"
    _assert_no_staff_identity(published.json(), secrets)
    assert label in published.json()["cashflow"]["coverage"]["message"]

    # A snapshot stored before this redaction existed still carries the name.
    with SessionLocal() as db:
        cashflow = LiveCashFlowService(db, org_id).monthly_cash_flow(
            months=10, as_of_date=date.today(),
        )
        cashflow["message"] = cashflow["coverage"]["message"]
        assert shown in cashflow["message"]
        snapshot_id = db.get(ClientDashboard, dashboard_id).current_snapshot_id
        snap = db.get(PublishedSnapshot, snapshot_id)
        snap.view_model = {
            "status": "ready", "cashflow": cashflow,
            "pnl": {"status": "unknown"}, "provider_calls": 0,
        }
        db.commit()
    legacy = client.get(f"/api/public/d/{slug}")
    assert legacy.status_code == 200, legacy.text
    _assert_no_staff_identity(legacy.json(), secrets)
    cash = legacy.json()["cashflow"]
    assert label in cash["coverage"]["message"]
    assert cash["message"] == cash["coverage"]["message"]
