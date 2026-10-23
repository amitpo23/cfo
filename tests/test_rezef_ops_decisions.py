"""Owner decisions of 2026-10-23 (Rezef ops guardrails).

1. Open Finance nightly refresh: off the schedule, refused unless a flag is on.
2. Daily WhatsApp alerts: off the schedule; proactive WhatsApp push needs a flag.

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
