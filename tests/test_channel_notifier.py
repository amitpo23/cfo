"""Package B of docs/superpowers/plans/2026-07-27-moshko-full-bot.md —
proactive push to conversational channels: opt-in, quiet hours, the morning
brief's third delivery channel, and /cron/channel-alerts. Zero network:
TelegramGateway is always faked or its construction guarded off entirely."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from cfo.config import settings
from cfo.database import SessionLocal
from cfo.models import CfoInsight, ChannelIdentity, User
from cfo.services import channel_notifier as notifier
from cfo.services import morning_brief_service as brief_svc

TODAY = date(2026, 7, 20)
ISRAEL = ZoneInfo("Asia/Jerusalem")


def _row_user_id(db, org_id: int) -> int:
    return db.query(User).filter(User.organization_id == org_id).first().id


def _make_identity(
    db, org_id, *, external_id, push_enabled=None, verified=True, revoked=False,
    last_push_at=None, provider="telegram", last_inbound_at=None,
):
    identity = ChannelIdentity(
        organization_id=org_id,
        user_id=_row_user_id(db, org_id),
        provider=provider,
        external_id=external_id,
        verified_at=datetime.utcnow() if verified else None,
        revoked_at=datetime.utcnow() if revoked else None,
        push_enabled=push_enabled,
        last_push_at=last_push_at,
        last_inbound_at=last_inbound_at,
    )
    db.add(identity)
    db.commit()
    db.refresh(identity)
    return identity


def _mk_insight(db, org_id, *, severity="high", title="בעיה", created_at=None, fingerprint=None):
    row = CfoInsight(
        organization_id=org_id,
        fingerprint=fingerprint or f"insight:{title}:{severity}:{created_at}",
        insight_type="test_insight",
        severity=severity,
        title=title,
        message="הודעה",
        status="active",
    )
    db.add(row)
    db.flush()
    if created_at is not None:
        row.created_at = created_at
    db.commit()
    db.refresh(row)
    return row


class _FakeGateway:
    def __init__(self, fail_for=None):
        self.sent: list[tuple[str, str]] = []
        self.fail_for = set(fail_for or ())

    async def send_text(self, chat_id, text):
        if chat_id in self.fail_for:
            raise RuntimeError("boom")
        self.sent.append((chat_id, text))


class _FakeWhatsAppGateway(_FakeGateway):
    def __init__(self, fail_for=None):
        super().__init__(fail_for=fail_for)
        self.templates: list[tuple[str, str, str, list[str]]] = []

    async def send_template(self, chat_id, template_name, language_code, variables):
        self.templates.append((chat_id, template_name, language_code, variables))


def _minimal_brief(org_id, status="yellow"):
    return {
        "organization_id": org_id,
        "organization_name": "חברת בדיקה",
        "date": TODAY.isoformat(),
        "status": status,
    }


# --------------------------------------------------------------------- #
# is_quiet_hours
# --------------------------------------------------------------------- #
def test_is_quiet_hours_true_at_night():
    now = datetime(2026, 7, 20, 23, 0, tzinfo=ISRAEL)
    assert notifier.is_quiet_hours(now) is True


def test_is_quiet_hours_false_mid_morning():
    now = datetime(2026, 7, 20, 10, 0, tzinfo=ISRAEL)
    assert notifier.is_quiet_hours(now) is False


def test_is_quiet_hours_converts_from_other_timezone():
    from zoneinfo import ZoneInfo as ZI
    # 21:00 UTC == 00:00 Israel (summer, UTC+3) -> quiet
    now = datetime(2026, 7, 20, 21, 0, tzinfo=ZI("UTC"))
    assert notifier.is_quiet_hours(now) is True


# --------------------------------------------------------------------- #
# recipients_for — verified / revoked / push_enabled filters
# --------------------------------------------------------------------- #
def test_recipients_for_excludes_unverified_revoked_and_opted_out(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        ok = _make_identity(db, org_id, external_id="chat-ok")
        _make_identity(db, org_id, external_id="chat-unverified", verified=False)
        _make_identity(db, org_id, external_id="chat-revoked", revoked=True)
        _make_identity(db, org_id, external_id="chat-optout", push_enabled=False)
        # push_enabled=None (never set) must count as enabled, same as True
        also_ok = _make_identity(db, org_id, external_id="chat-null-enabled", push_enabled=None)

        found = notifier.recipients_for(db, org_id)
        found_ids = {i.external_id for i in found}
        assert found_ids == {"chat-ok", "chat-null-enabled"}
        assert ok.id in [i.id for i in found]
        assert also_ok.id in [i.id for i in found]
    finally:
        db.close()


# --------------------------------------------------------------------- #
# push_to_organization
# --------------------------------------------------------------------- #
def test_push_not_configured_without_token_and_gateway_never_built(fresh_org, monkeypatch):
    import asyncio
    import cfo.services.channel_gateway as gateway_module

    monkeypatch.setattr(settings, "telegram_bot_token", None, raising=False)

    def _boom(*a, **kw):
        raise AssertionError("TelegramGateway must not be constructed without a token")

    monkeypatch.setattr(gateway_module, "TelegramGateway", _boom)

    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _make_identity(db, org_id, external_id="chat-not-configured")
        result = asyncio.run(notifier.push_to_organization(db, org_id, "hi"))
        assert result["status"] == "not_configured"
        assert result["sent"] == 0
    finally:
        db.close()


def test_push_quiet_hours_blocks_info_but_not_critical(fresh_org, monkeypatch):
    import asyncio

    monkeypatch.setattr(settings, "telegram_bot_token", "dummy-token", raising=False)
    monkeypatch.setattr(notifier, "is_quiet_hours", lambda *a, **kw: True)

    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _make_identity(db, org_id, external_id="chat-quiet")
        gateway = _FakeGateway()

        blocked = asyncio.run(
            notifier.push_to_organization(db, org_id, "info msg", severity="info", gateway=gateway)
        )
        assert blocked["status"] == "quiet_hours"
        assert blocked["skipped"] == 1
        assert gateway.sent == []

        allowed = asyncio.run(
            notifier.push_to_organization(db, org_id, "critical msg", severity="critical", gateway=gateway)
        )
        assert allowed["status"] == "sent"
        assert gateway.sent == [("chat-quiet", "critical msg")]
    finally:
        db.close()


def test_push_one_recipient_failure_does_not_block_others_and_never_raises(fresh_org, monkeypatch):
    import asyncio

    monkeypatch.setattr(settings, "telegram_bot_token", "dummy-token", raising=False)
    monkeypatch.setattr(notifier, "is_quiet_hours", lambda *a, **kw: False)

    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        good = _make_identity(db, org_id, external_id="chat-good")
        bad = _make_identity(db, org_id, external_id="chat-bad")
        gateway = _FakeGateway(fail_for={"chat-bad"})

        result = asyncio.run(
            notifier.push_to_organization(db, org_id, "hello", gateway=gateway)
        )
        assert result["sent"] == 1
        assert result["failed"] == 1
        assert result["status"] == "sent"
        assert gateway.sent == [("chat-good", "hello")]

        db.refresh(good)
        db.refresh(bad)
        assert good.last_push_at is not None
        assert bad.last_push_at is None
    finally:
        db.close()


def test_push_last_push_at_updated_only_on_success(fresh_org, monkeypatch):
    import asyncio

    monkeypatch.setattr(settings, "telegram_bot_token", "dummy-token", raising=False)
    monkeypatch.setattr(notifier, "is_quiet_hours", lambda *a, **kw: False)

    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        identity = _make_identity(db, org_id, external_id="chat-last-push")
        assert identity.last_push_at is None
        gateway = _FakeGateway()

        asyncio.run(notifier.push_to_organization(db, org_id, "hi", gateway=gateway))

        db.refresh(identity)
        assert identity.last_push_at is not None
    finally:
        db.close()


def test_push_no_recipients_status(fresh_org, monkeypatch):
    import asyncio

    monkeypatch.setattr(settings, "telegram_bot_token", "dummy-token", raising=False)

    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        result = asyncio.run(notifier.push_to_organization(db, org_id, "hi", gateway=_FakeGateway()))
        assert result["status"] == "no_recipients"
        assert result["sent"] == 0
    finally:
        db.close()


def test_whatsapp_push_uses_provider_specific_configuration_and_gateway(fresh_org, monkeypatch):
    import asyncio

    monkeypatch.setattr(settings, "telegram_bot_token", None, raising=False)
    monkeypatch.setattr(settings, "whatsapp_phone_number_id", "phone-id", raising=False)
    monkeypatch.setattr(settings, "whatsapp_access_token", "wa-token", raising=False)
    monkeypatch.setattr(notifier, "is_quiet_hours", lambda *a, **kw: False)
    now = datetime(2026, 7, 20, 12, 0, tzinfo=ZoneInfo("UTC"))

    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _make_identity(
            db, org_id, external_id="972500000001", provider="whatsapp",
            last_inbound_at=now - timedelta(hours=1),
        )
        gateway = _FakeWhatsAppGateway()
        result = asyncio.run(notifier.push_to_organization(
            db, org_id, "שלום בוואטסאפ", provider="whatsapp", gateway=gateway, now=now,
        ))
        assert result["status"] == "sent"
        assert gateway.sent == [("972500000001", "שלום בוואטסאפ")]
    finally:
        db.close()


def test_whatsapp_outside_service_window_without_template_is_explicit(fresh_org, monkeypatch):
    import asyncio

    monkeypatch.setattr(settings, "whatsapp_phone_number_id", "phone-id", raising=False)
    monkeypatch.setattr(settings, "whatsapp_access_token", "wa-token", raising=False)
    monkeypatch.setattr(settings, "whatsapp_push_template_name", None, raising=False)
    monkeypatch.setattr(notifier, "is_quiet_hours", lambda *a, **kw: False)
    now = datetime(2026, 7, 20, 12, 0, tzinfo=ZoneInfo("UTC"))

    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _make_identity(
            db, org_id, external_id="972500000002", provider="whatsapp",
            last_inbound_at=now - timedelta(hours=25),
        )
        gateway = _FakeWhatsAppGateway()
        result = asyncio.run(notifier.push_to_organization(
            db, org_id, "התראה", provider="whatsapp", gateway=gateway, now=now,
        ))
        assert result["status"] == "outside_service_window"
        assert result["sent"] == 0
        assert result["outside_service_window"] == 1
        assert gateway.sent == []
        assert gateway.templates == []
    finally:
        db.close()


def test_whatsapp_outside_window_uses_configured_template(fresh_org, monkeypatch):
    import asyncio

    monkeypatch.setattr(settings, "whatsapp_phone_number_id", "phone-id", raising=False)
    monkeypatch.setattr(settings, "whatsapp_access_token", "wa-token", raising=False)
    monkeypatch.setattr(settings, "whatsapp_push_template_name", "rezef_alert", raising=False)
    monkeypatch.setattr(settings, "whatsapp_push_template_language", "he", raising=False)
    monkeypatch.setattr(notifier, "is_quiet_hours", lambda *a, **kw: False)
    now = datetime(2026, 7, 20, 12, 0, tzinfo=ZoneInfo("UTC"))

    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _make_identity(
            db, org_id, external_id="972500000003", provider="whatsapp",
            last_inbound_at=now - timedelta(days=2),
        )
        gateway = _FakeWhatsAppGateway()
        result = asyncio.run(notifier.push_to_organization(
            db, org_id, "התראת תזרים", provider="whatsapp", gateway=gateway, now=now,
        ))
        assert result["status"] == "sent"
        assert gateway.sent == []
        assert gateway.templates == [("972500000003", "rezef_alert", "he", ["התראת תזרים"])]
    finally:
        db.close()


# --------------------------------------------------------------------- #
# morning_brief_service — third channel
# --------------------------------------------------------------------- #
def test_morning_brief_channel_delivery_and_idempotency(fresh_org, monkeypatch):
    calls = []

    async def _fake_push(db, org_id, text, *, severity="info", provider="telegram", gateway=None, force=False):
        calls.append(severity)
        return {"status": "sent", "sent": 1, "failed": 0, "skipped": 0}

    import cfo.services.channel_notifier as notifier_module
    monkeypatch.setattr(notifier_module, "push_to_organization", _fake_push)

    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        brief = _minimal_brief(org_id)
        r1 = brief_svc.persist_and_deliver(db, org_id, TODAY, brief)
        assert r1["channels"]["channel"]["status"] == "sent"
        assert len(calls) == 1

        r2 = brief_svc.persist_and_deliver(db, org_id, TODAY, brief)
        assert r2["channels"]["channel"]["status"] == "skipped"
        assert r2["channels"]["channel"]["reason"] == "already_delivered_today"
        assert len(calls) == 1

        r3 = brief_svc.persist_and_deliver(db, org_id, TODAY, brief, force=True)
        assert r3["channels"]["channel"]["status"] == "sent"
        assert len(calls) == 2
    finally:
        db.close()


def test_morning_brief_channel_skips_quietly_without_token(fresh_org, monkeypatch):
    monkeypatch.setattr(settings, "telegram_bot_token", None, raising=False)

    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        result = brief_svc.persist_and_deliver(db, org_id, TODAY, _minimal_brief(org_id))
        assert result["channels"]["channel"]["status"] == "skipped"
        assert result["channels"]["channel"]["reason"] == "not_configured"
        assert "channel" not in result["delivered_channels"]
    finally:
        db.close()


def test_morning_brief_channel_severity_high_when_red(fresh_org, monkeypatch):
    calls = []

    async def _fake_push(db, org_id, text, *, severity="info", provider="telegram", gateway=None, force=False):
        calls.append(severity)
        return {"status": "sent", "sent": 1, "failed": 0, "skipped": 0}

    import cfo.services.channel_notifier as notifier_module
    monkeypatch.setattr(notifier_module, "push_to_organization", _fake_push)

    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        brief_svc.persist_and_deliver(db, org_id, TODAY, _minimal_brief(org_id, status="red"))
        assert calls == ["high"]
    finally:
        db.close()


# --------------------------------------------------------------------- #
# /cron/channel-alerts
# --------------------------------------------------------------------- #
def test_channel_alerts_cron_rejects_wrong_secret(client):
    r = client.get("/api/cron/channel-alerts", headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 401


def test_channel_alerts_cron_only_pushes_high_or_critical_and_dedupes(fresh_org, monkeypatch, client):
    monkeypatch.setattr(settings, "telegram_bot_token", "dummy-token", raising=False)
    monkeypatch.setattr(notifier, "is_quiet_hours", lambda *a, **kw: False)

    import cfo.services.channel_gateway as gateway_module

    gateway = _FakeGateway()
    monkeypatch.setattr(gateway_module, "TelegramGateway", lambda *a, **kw: gateway)

    iso = fresh_org()
    org_id = iso["org_id"]
    db = SessionLocal()
    try:
        _make_identity(db, org_id, external_id="chat-cron")

        # Never pushed before -> falls back to a 24h lookback: an insight
        # older than 24h must NOT be picked up (first-run flood guard).
        _mk_insight(
            db, org_id, severity="high", title="ישן מדי",
            created_at=datetime.utcnow() - timedelta(hours=30),
        )
        # Within the 24h window and high severity -> should be pushed.
        fresh_high = _mk_insight(
            db, org_id, severity="high", title="חדש בסיכון גבוה",
            created_at=datetime.utcnow() - timedelta(hours=1),
        )
        # medium severity -> never pushed regardless of recency.
        _mk_insight(
            db, org_id, severity="medium", title="לא רלוונטי",
            created_at=datetime.utcnow() - timedelta(minutes=5),
        )
    finally:
        db.close()

    headers = {"Authorization": f"Bearer {settings.cron_secret}"}
    r1 = client.get("/api/cron/channel-alerts", headers=headers)
    assert r1.status_code == 200, r1.text
    body1 = r1.json()
    assert body1["insights"] == 1  # only the fresh "high" one, not the old or the medium
    assert body1["pushed"] == 1
    assert len(gateway.sent) == 1
    assert "חדש בסיכון גבוה" in gateway.sent[0][1]

    # Second run: last_push_at has advanced past fresh_high's created_at, so
    # the exact same insight must NOT be pushed again.
    gateway.sent.clear()
    r2 = client.get("/api/cron/channel-alerts", headers=headers)
    assert r2.status_code == 200, r2.text
    body2 = r2.json()
    assert body2["insights"] == 0
    assert body2["pushed"] == 0
    assert gateway.sent == []


def test_channel_alerts_cron_pushes_to_whatsapp_only_organization(
    fresh_org, monkeypatch, client,
):
    monkeypatch.setattr(settings, "telegram_bot_token", None, raising=False)
    monkeypatch.setattr(settings, "whatsapp_phone_number_id", "phone-id", raising=False)
    monkeypatch.setattr(settings, "whatsapp_access_token", "wa-token", raising=False)
    monkeypatch.setattr(notifier, "is_quiet_hours", lambda *a, **kw: False)

    import cfo.services.whatsapp_gateway as gateway_module

    gateway = _FakeWhatsAppGateway()
    monkeypatch.setattr(gateway_module, "WhatsAppGateway", lambda *a, **kw: gateway)

    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _make_identity(
            db, org_id, external_id="972500000099", provider="whatsapp",
            last_inbound_at=datetime.now(ZoneInfo("UTC")) - timedelta(hours=1),
        )
        _mk_insight(
            db, org_id, severity="critical", title="התראת וואטסאפ",
            created_at=datetime.utcnow() - timedelta(minutes=5),
        )
    finally:
        db.close()

    response = client.get(
        "/api/cron/channel-alerts",
        headers={"Authorization": f"Bearer {settings.cron_secret}"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["pushed"] >= 1
    assert gateway.sent and "התראת וואטסאפ" in gateway.sent[0][1]
