"""Owner decisions of 2026-10-23 (Rezef ops guardrails).

1. Open Finance nightly refresh: off the schedule, refused unless a flag is on.
2. Daily WhatsApp alerts: off the schedule; proactive WhatsApp push needs a flag.
3. SUMIT: one scheduled read-only pull per ISO week, inside the monthly cap,
   keeping at least 10 calls for on-demand admin work.

Zero network: provider paths are replaced before any route runs.
"""
from __future__ import annotations

import json
from pathlib import Path

from cfo.config import Settings, settings

ROOT = Path(__file__).resolve().parents[1]
CRON_HEADERS = {"Authorization": "Bearer test-cron-secret"}


def _scheduled_paths() -> set[str]:
    config = json.loads((ROOT / "vercel.json").read_text())
    return {job["path"] for job in config["crons"]}


# ------------------------------------------------- 1. Open Finance nightly

def test_open_finance_nightly_cron_is_not_scheduled():
    assert "/api/cron/sync-open-finance" not in _scheduled_paths()


def test_open_finance_scheduled_sync_flag_defaults_off():
    assert Settings(_env_file=None).open_finance_scheduled_sync_enabled is False


def test_open_finance_cron_refuses_an_unattended_run_while_the_flag_is_off(client, monkeypatch):
    from cfo.api.routes import cron

    monkeypatch.setattr(settings, "open_finance_scheduled_sync_enabled", False)

    async def must_not_run(_db, _targets):
        raise AssertionError("Open Finance sync loop was reached")

    def must_not_claim(*_args, **_kwargs):
        raise AssertionError("Open Finance attempt budget was claimed")

    monkeypatch.setattr(cron, "_run_sync_targets", must_not_run)
    monkeypatch.setattr(cron, "_claim_open_finance_sync_attempt", must_not_claim)

    response = client.get("/api/cron/sync-open-finance", headers=CRON_HEADERS)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["skipped"] == "open_finance_scheduled_sync_disabled"
    assert body["results"] == []


def test_open_finance_cron_still_requires_the_cron_secret(client):
    assert client.get("/api/cron/sync-open-finance").status_code == 401


def test_open_finance_cron_runs_its_gates_once_the_flag_is_on(client, monkeypatch):
    from cfo.api.routes import cron

    monkeypatch.setattr(settings, "open_finance_scheduled_sync_enabled", True)
    reached: list[set] = []

    async def record(_db, targets):
        reached.append(set(targets))
        return []

    monkeypatch.setattr(cron, "roster_sync_targets", lambda _db: [])
    monkeypatch.setattr(cron, "_run_sync_targets", record)

    response = client.get("/api/cron/sync-open-finance", headers=CRON_HEADERS)

    assert response.status_code == 200, response.text
    assert response.json().get("skipped") != "open_finance_scheduled_sync_disabled"
    assert len(reached) == 1


# ------------------------------------------------- 2. WhatsApp daily alerts

def test_daily_channel_alerts_cron_is_not_scheduled():
    assert "/api/cron/channel-alerts" not in _scheduled_paths()


def test_whatsapp_push_flag_defaults_off():
    assert Settings(_env_file=None).whatsapp_push_enabled is False


def _whatsapp_and_telegram_org(fresh_org, monkeypatch, tag):
    from datetime import datetime, timedelta, timezone

    from cfo.database import SessionLocal
    from cfo.services import channel_notifier as notifier
    from tests.test_channel_notifier import _FakeGateway, _FakeWhatsAppGateway, _make_identity

    monkeypatch.setattr(settings, "telegram_bot_token", "tg-token", raising=False)
    monkeypatch.setattr(settings, "whatsapp_phone_number_id", "phone-id", raising=False)
    monkeypatch.setattr(settings, "whatsapp_access_token", "wa-token", raising=False)
    monkeypatch.setattr(notifier, "is_quiet_hours", lambda *a, **kw: False)
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _make_identity(db, org_id, external_id=f"ops-tg-{tag}", provider="telegram")
        _make_identity(
            db, org_id, external_id=f"97250000{tag}", provider="whatsapp",
            last_inbound_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )
    finally:
        db.close()
    return org_id, _FakeGateway(), _FakeWhatsAppGateway()


_TAGS = iter(range(7100, 7200))


def test_whatsapp_push_is_skipped_while_the_flag_is_off_and_telegram_still_sends(fresh_org, monkeypatch):
    import asyncio

    from cfo.database import SessionLocal
    from cfo.services import channel_notifier as notifier

    monkeypatch.setattr(settings, "whatsapp_push_enabled", False)
    tag = next(_TAGS)
    org_id, telegram, whatsapp = _whatsapp_and_telegram_org(fresh_org, monkeypatch, tag)
    db = SessionLocal()
    try:
        result = asyncio.run(notifier.push_to_organization(
            db, org_id, "התרעה", severity="critical",
            gateways={"telegram": telegram, "whatsapp": whatsapp},
        ))
    finally:
        db.close()

    assert result["status"] == "sent"
    assert result["sent"] == 1 and result["push_disabled"] == 1
    assert telegram.sent == [(f"ops-tg-{tag}", "התרעה")]
    assert whatsapp.sent == [] and whatsapp.templates == []


def test_whatsapp_only_organization_reports_push_disabled(fresh_org, monkeypatch):
    import asyncio
    from datetime import datetime, timedelta, timezone

    from cfo.database import SessionLocal
    from cfo.services import channel_notifier as notifier
    from tests.test_channel_notifier import _FakeWhatsAppGateway, _make_identity

    monkeypatch.setattr(settings, "whatsapp_push_enabled", False)
    monkeypatch.setattr(settings, "whatsapp_phone_number_id", "phone-id", raising=False)
    monkeypatch.setattr(settings, "whatsapp_access_token", "wa-token", raising=False)
    org_id = fresh_org()["org_id"]
    gateway = _FakeWhatsAppGateway()
    db = SessionLocal()
    try:
        _make_identity(
            db, org_id, external_id="972500007099", provider="whatsapp",
            last_inbound_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )
        result = asyncio.run(notifier.push_to_organization(
            db, org_id, "התרעה", severity="critical", gateway=gateway, provider="whatsapp",
        ))
    finally:
        db.close()

    assert result["status"] == "push_disabled"
    assert result["sent"] == 0 and result["push_disabled"] == 1
    assert gateway.sent == []


def test_whatsapp_push_goes_out_once_the_flag_is_on(fresh_org, monkeypatch):
    import asyncio

    from cfo.database import SessionLocal
    from cfo.services import channel_notifier as notifier

    monkeypatch.setattr(settings, "whatsapp_push_enabled", True)
    tag = next(_TAGS)
    org_id, telegram, whatsapp = _whatsapp_and_telegram_org(fresh_org, monkeypatch, tag)
    db = SessionLocal()
    try:
        result = asyncio.run(notifier.push_to_organization(
            db, org_id, "התרעה", severity="critical",
            gateways={"telegram": telegram, "whatsapp": whatsapp},
        ))
    finally:
        db.close()

    assert result["sent"] == 2 and result["push_disabled"] == 0
    assert whatsapp.sent == [(f"97250000{tag}", "התרעה")]


# ------------------------------------------------- 3. SUMIT weekly pull

import pytest  # noqa: E402

WEEKLY = "/api/cron/sumit-weekly-pull"


@pytest.fixture
def clean_budgets(client):
    from cfo.database import SessionLocal
    from cfo.models import ProviderRequestBudget

    def _clear():
        db = SessionLocal()
        try:
            db.query(ProviderRequestBudget).delete()
            db.commit()
        finally:
            db.close()

    _clear()
    yield
    _clear()


def _seed_account_used(used: int) -> None:
    from cfo.database import SessionLocal
    from cfo.services.sumit_request_budget import (
        ACCOUNT_REQUEST_SCOPE, SumitRequestLimiter, _db_now, _utc_windows,
        account_monthly_request_limit,
    )

    db = SessionLocal()
    try:
        with db.begin():
            now = _db_now(db)
            SumitRequestLimiter._seed_window_floor(
                db, scope_key=ACCOUNT_REQUEST_SCOPE, organization_id=None, window_kind="month",
                window_start=_utc_windows(now)[2], used=used,
                limit_value=account_monthly_request_limit(), now=now,
            )
    finally:
        db.close()


def _account_used() -> int:
    from cfo.database import SessionLocal
    from cfo.services.sumit_request_budget import account_month_used

    db = SessionLocal()
    try:
        return account_month_used(db)
    finally:
        db.close()


def _weekly_rows() -> int:
    from cfo.database import SessionLocal
    from cfo.models import ProviderRequestBudget
    from cfo.services.sumit_weekly_pull import WEEKLY_PULL_SCOPE

    db = SessionLocal()
    try:
        return db.query(ProviderRequestBudget).filter_by(scope_key=WEEKLY_PULL_SCOPE).count()
    finally:
        db.close()


def _arm_weekly_pull(monkeypatch, *, claims_per_org: int = 0, calls_per_org: int = 1):
    """Flag on, provider loop replaced by one that only claims budget slots (DB only)."""
    from cfo.api.routes import cron
    from cfo.services.sumit_request_budget import SumitRequestLimiter

    monkeypatch.setattr(settings, "sumit_weekly_pull_enabled", True)
    monkeypatch.setattr(settings, "sumit_weekly_pull_calls_per_org", calls_per_org)
    monkeypatch.setattr(cron, "roster_sync_targets", lambda _db: [])
    monkeypatch.setattr(cron, "_daily_budget_gate", lambda *_a, **_k: None)
    monkeypatch.setattr(cron, "_per_key_daily_gate", lambda *_a, **_k: None)
    runs: list[dict] = []

    async def fake_run(_db, targets, *, pull_expenses=True):
        runs.append({"targets": set(targets), "pull_expenses": pull_expenses})
        for org_id, _source in sorted(targets)[:1]:
            limiter = SumitRequestLimiter(org_id)
            for _ in range(claims_per_org):
                limiter.claim("/accounting/documents/list/")
        return [{"organization_id": org_id, "source": source} for org_id, source in sorted(targets)]

    monkeypatch.setattr(cron, "_run_sync_targets", fake_run)
    return runs


def test_sumit_weekly_pull_is_scheduled_once_a_week():
    config = json.loads((ROOT / "vercel.json").read_text())
    weekly = [job for job in config["crons"] if job["path"] == WEEKLY]
    assert weekly == [{"path": WEEKLY, "schedule": "0 3 * * 0"}]


def test_sumit_weekly_pull_flag_defaults_off_and_reserve_never_drops_below_10():
    loaded = Settings(_env_file=None)
    assert loaded.sumit_weekly_pull_enabled is False
    assert loaded.sumit_weekly_pull_reserve_calls == 10
    assert Settings(_env_file=None, sumit_weekly_pull_reserve_calls=3).sumit_weekly_pull_reserve_calls == 10


def test_live_monthly_cap_is_still_50_for_the_whole_account():
    from cfo.services.sumit_request_budget import LIVE_ACCOUNT_REQUEST_HARD_CAP

    assert LIVE_ACCOUNT_REQUEST_HARD_CAP == 50
    assert Settings(_env_file=None, sumit_live_monthly_request_limit=500).sumit_live_monthly_request_limit == 50


def test_weekly_pull_does_nothing_while_the_flag_is_off(client, clean_budgets, monkeypatch):
    from cfo.api.routes import cron

    monkeypatch.setattr(settings, "sumit_weekly_pull_enabled", False)

    async def must_not_run(*_a, **_k):
        raise AssertionError("SUMIT sync loop was reached")

    monkeypatch.setattr(cron, "_run_sync_targets", must_not_run)
    response = client.get(WEEKLY, headers=CRON_HEADERS)

    assert response.status_code == 200, response.text
    assert response.json()["skipped"] == "sumit_weekly_pull_disabled"
    assert _weekly_rows() == 0


def test_weekly_pull_requires_the_cron_secret(client):
    assert client.get(WEEKLY).status_code == 401


def test_weekly_pull_runs_once_per_iso_week(client, clean_budgets, monkeypatch):
    runs = _arm_weekly_pull(monkeypatch)

    first = client.get(WEEKLY, headers=CRON_HEADERS)
    second = client.get(WEEKLY, headers=CRON_HEADERS)

    assert first.status_code == 200, first.text
    assert first.json()["synced"] >= 1 and first.json()["week"]
    assert second.json()["skipped"] == "already_pulled_this_week"
    assert second.json()["week"] == first.json()["week"]
    assert len(runs) == 1
    assert _weekly_rows() == 1


def test_weekly_pull_is_read_only_and_skips_the_expense_pull(client, clean_budgets, monkeypatch):
    runs = _arm_weekly_pull(monkeypatch)

    assert client.get(WEEKLY, headers=CRON_HEADERS).status_code == 200
    assert runs and runs[0]["pull_expenses"] is False


def test_weekly_pull_skips_when_it_would_eat_into_the_on_demand_reserve(client, clean_budgets, monkeypatch):
    from cfo.services.sumit_request_budget import account_monthly_request_limit

    runs = _arm_weekly_pull(monkeypatch)
    limit = account_monthly_request_limit()
    # Exactly the reserve is left: nothing for the pull.
    _seed_account_used(limit - 10)

    response = client.get(WEEKLY, headers=CRON_HEADERS)

    body = response.json()
    assert body["skipped"] == "sumit_monthly_quota_reserved"
    assert body["quota"]["remaining"] == 10
    assert body["quota"]["available_for_weekly_pull"] == 0
    assert runs == []
    # A skipped week is not claimed: a later run this week may still try.
    assert _weekly_rows() == 0


def test_weekly_pull_skips_when_the_estimate_exceeds_the_cap_under_live(client, clean_budgets, monkeypatch):
    runs = _arm_weekly_pull(monkeypatch, calls_per_org=41)
    monkeypatch.setattr(settings, "sumit_environment", "live")

    body = client.get(WEEKLY, headers=CRON_HEADERS).json()

    assert body["skipped"] == "sumit_monthly_quota_reserved"
    assert body["quota"]["limit"] == 50 and body["quota"]["available_for_weekly_pull"] == 40
    assert body["estimated_calls"] >= 41
    assert runs == []


def test_weekly_pull_logs_the_calls_it_used(client, clean_budgets, monkeypatch, caplog):
    import logging

    _arm_weekly_pull(monkeypatch, claims_per_org=3)

    with caplog.at_level(logging.INFO, logger="cfo.api.routes.cron"):
        body = client.get(WEEKLY, headers=CRON_HEADERS).json()

    assert body["calls_used"] == 3
    assert body["month_used_after"] == body["quota_before"]["used"] + 3
    assert any("3 calls used" in record.getMessage() for record in caplog.records)


def test_weekly_pull_logs_why_a_ran_org_made_no_calls(client, clean_budgets, monkeypatch, caplog):
    """A target that entered the sync loop must log status and the skip/error reason.

    The summary line only counts orgs in ``to_run`` and calls committed. A
    connector refusal or an entity error stays in ``results`` and is invisible
    in that line. The response body is unchanged.
    """
    import logging

    from cfo.api.routes import cron

    _arm_weekly_pull(monkeypatch, claims_per_org=0)

    async def fake_run(_db, targets, *, pull_expenses=True):
        assert pull_expenses is False
        assert targets
        return [
            {
                "organization_id": 7,
                "source": "sumit",
                "status": "partial",
                "error_summary": "1 entity types had errors",
                "counts": {
                    "invoices": {
                        "error": "refusing to call SUMIT (/accounting/documents/list/) with a placeholder API key",
                    },
                    "bills": {"skipped_circuit_open": True, "circuit_open_until": "2026-10-25T12:00:00"},
                    "accounts": {"created": 5},
                },
            },
            {
                "organization_id": 8,
                "source": "sumit",
                "error": "Provider access is disabled for this import-only organization",
            },
        ]

    monkeypatch.setattr(cron, "_run_sync_targets", fake_run)

    with caplog.at_level(logging.INFO, logger="cfo.api.routes.cron"):
        body = client.get(WEEKLY, headers=CRON_HEADERS).json()

    assert body["calls_used"] == 0
    assert body["synced"] >= 1
    assert [item["organization_id"] for item in body["results"]] == [7, 8]
    assert body["results"][0]["counts"]["accounts"] == {"created": 5}
    messages = [record.getMessage() for record in caplog.records]
    assert any(
        "org=7" in message
        and "source=sumit" in message
        and "status=partial" in message
        and "placeholder API key" in message
        and "bills: circuit_open" in message
        and "created" not in message
        and "circuit_open_until" not in message
        for message in messages
    )
    assert any(
        "org=8" in message
        and "status=error" in message
        and "Provider access is disabled" in message
        for message in messages
    )


def test_weekly_pull_logs_a_gate_skip_that_never_enters_the_sync(client, clean_budgets, monkeypatch, caplog):
    """Daily-budget and per-key skips are 0 calls and must be logged too."""
    import logging

    from cfo.api.routes import cron

    _arm_weekly_pull(monkeypatch, claims_per_org=0)

    def daily_gate(_db, org_id, source):
        return {
            "organization_id": org_id,
            "source": source,
            "skipped": "daily_budget",
            "last_success_at": "2026-10-25T00:00:00",
            "next_eligible_at": "2026-10-25T20:00:00",
        }

    monkeypatch.setattr(cron, "_daily_budget_gate", daily_gate)

    with caplog.at_level(logging.INFO, logger="cfo.api.routes.cron"):
        body = client.get(WEEKLY, headers=CRON_HEADERS).json()

    assert body["calls_used"] == 0
    assert body["synced"] == 0
    assert body["results"]
    assert all(item["skipped"] == "daily_budget" for item in body["results"])
    messages = [record.getMessage() for record in caplog.records]
    assert any(
        "org=1" in message and "status=skipped" in message and "skipped=daily_budget" in message
        for message in messages
    )


def test_scheduled_pull_guard_keeps_the_reserve_at_the_request_boundary(client, clean_budgets):
    from cfo.services.sumit_request_budget import (
        SumitRequestBudgetExceeded, SumitRequestLimiter, account_monthly_request_limit,
        scheduled_pull_guard,
    )

    limit = account_monthly_request_limit()
    _seed_account_used(limit - 11)
    limiter = SumitRequestLimiter(1)
    with scheduled_pull_guard(reserve=10):
        limiter.claim("/accounting/documents/list/")
        with pytest.raises(SumitRequestBudgetExceeded):
            limiter.claim("/accounting/documents/list/")
    assert _account_used() == limit - 10
    # Outside the guard, on-demand work can still use the reserve.
    limiter.claim("/accounting/documents/list/")
    assert _account_used() == limit - 9


def test_scheduled_pull_guard_refuses_write_and_paid_endpoints(client, clean_budgets):
    from cfo.services.sumit_request_budget import (
        SumitRequestBudgetExceeded, SumitRequestLimiter, scheduled_pull_guard,
    )

    limiter = SumitRequestLimiter(1)
    with scheduled_pull_guard(reserve=10):
        for endpoint in (
            "/accounting/documents/create/",
            "/books/transactions/createbatch/",
            "/accounting/documents/getpdf/",
        ):
            with pytest.raises(SumitRequestBudgetExceeded):
                limiter.claim(endpoint)
        limiter.claim("/accounting/documents/list/")
    assert _account_used() == 1


def test_iso_week_follows_israel_time_and_starts_on_monday():
    from datetime import datetime, timezone

    from cfo.services.sumit_weekly_pull import iso_week

    sunday_run = datetime(2026, 10, 25, 3, 0, tzinfo=timezone.utc)   # Sun 05:00 Israel
    monday = datetime(2026, 10, 25, 22, 30, tzinfo=timezone.utc)     # Mon 00:30 Israel
    assert iso_week(sunday_run)[0] == "2026-W43"
    assert iso_week(monday)[0] == "2026-W44"
    assert iso_week(sunday_run)[1] == datetime(2026, 10, 18, 21, 0, tzinfo=timezone.utc)


def test_admin_status_shows_calls_left_and_the_last_weekly_pull(
    client, clean_budgets, monkeypatch, platform_admin,
):
    _arm_weekly_pull(monkeypatch, claims_per_org=2)
    path = "/api/admin/cost-protection-status"

    before = client.get(path, headers=platform_admin["headers"]).json()["sumit"]["weekly_pull"]
    assert before["enabled"] is True and before["last_pull"] is None
    assert before["quota"]["used"] == 0 and before["quota"]["reserve_for_on_demand"] == 10
    assert before["provider_calls"] == 0

    week = client.get(WEEKLY, headers=CRON_HEADERS).json()["week"]
    after = client.get(path, headers=platform_admin["headers"]).json()
    pull = after["sumit"]["weekly_pull"]
    assert pull["last_pull"]["week"] == week
    assert pull["last_pull"]["calls_used"] == 2
    assert pull["quota"]["remaining"] == pull["quota"]["limit"] - 2
    assert after["open_finance"]["scheduled_sync_enabled"] is False
    assert after["channels"]["whatsapp_push_enabled"] is False


def test_admin_status_is_super_admin_only(client, owner):
    assert client.get("/api/admin/cost-protection-status", headers=owner["headers"]).status_code in (401, 403)


# ------------------------------------------------- freshness thresholds

@pytest.mark.parametrize("age, status", [
    (0, "fresh"), (3, "fresh"), (4, "aging"), (7, "aging"), (8, "stale"),
    (10, "stale"), (12, "stale"), (30, "stale"),
])
def test_freshness_thresholds_live_in_one_place(age, status):
    from cfo.services.dashboards import freshness

    assert freshness.FRESHNESS_THRESHOLDS == (("fresh", 3), ("aging", 7))
    assert freshness.age_status(age) == status


def test_ten_to_twelve_day_old_food_group_import_is_not_labelled_fresh(fresh_org):
    from datetime import date, timedelta
    from decimal import Decimal

    from cfo.database import SessionLocal
    from cfo.models import BankTransaction, JournalEntry
    from cfo.services.dashboards import freshness

    org_id = fresh_org()["org_id"]
    today = date(2026, 10, 23)
    with SessionLocal() as db:
        db.add(BankTransaction(
            organization_id=org_id, transaction_date=today - timedelta(days=10),
            amount=Decimal("-5"), description="עמלה", source="reviewed_local_import",
            external_id="ops-fg-bank-1",
        ))
        db.add(JournalEntry(
            organization_id=org_id, entry_date=today - timedelta(days=12),
            source="reviewed_local_import", memo="פוד גרופ",
        ))
        db.commit()
        section = freshness.build_freshness(db, org_id, today=today)

    by_kind = {item["kind"]: item for item in section["items"]}
    for kind, age in (("bank", 10), ("journal", 12)):
        item = by_kind[kind]
        assert (item["age_days"], item["status"], item["status_label"]) == (age, "stale", "לא עדכני")
        assert item["status_label"] != "עדכני"
    assert section["stale_count"] == 2
    assert "עד 3 ימים" in section["rule"] and "עד 7 ימים" in section["rule"]


def test_a_five_day_old_import_is_aging(fresh_org):
    from datetime import date, timedelta
    from decimal import Decimal

    from cfo.database import SessionLocal
    from cfo.models import BankTransaction
    from cfo.services.dashboards import freshness

    org_id = fresh_org()["org_id"]
    today = date(2026, 10, 23)
    with SessionLocal() as db:
        db.add(BankTransaction(
            organization_id=org_id, transaction_date=today - timedelta(days=5),
            amount=Decimal("-5"), description="עמלה", source="reviewed_local_import",
            external_id="ops-fg-bank-2",
        ))
        db.commit()
        section = freshness.build_freshness(db, org_id, today=today)

    item = section["items"][0]
    assert (item["status"], item["status_label"]) == ("aging", "מתיישן")
    assert section["aging_count"] == 1 and section["stale_count"] == 0


# ------------------------------------------------- 4. portal runbooks rule

def test_agents_md_allows_only_the_approved_portal_runbooks_with_a_go_per_final_save():
    text = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    section = text.split("## פורטל SUMIT", 1)[1].split("\n## ", 1)[0]
    for runbook in (
        "cfo:close-batch", "cfo:export-to-hashavshevet", "cfo:find-duplicate-transactions",
        "cfo:month-end-review", "sumit-file-expenses",
    ):
        assert runbook in section, runbook
    assert "שמירה כמסמך סופי" in section and "GO מפורש של עמית בכל" in section
    assert "50 קריאות בחודש לכל החשבון" in section
    for flag in ("OPEN_FINANCE_SCHEDULED_SYNC_ENABLED", "WHATSAPP_PUSH_ENABLED", "SUMIT_WEEKLY_PULL_ENABLED"):
        assert flag in text, flag
