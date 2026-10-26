"""בדיקת מוכנות מושקו — offline, בוליאנים בלבד.

עונה "מה חסר כדי שמושקו יעבוד בוואטסאפ/טלגרם" בלי לחשוף אף סוד ובלי
קריאת רשת. הבדיקות שותלות ערך-זקיף בכל סוד ומוודאות שהוא לא מופיע בתשובה
ולא בלוג, ושכל עלה בתשובה הוא bool.
"""
from __future__ import annotations

import json
import logging

import pytest

from cfo import config as config_module
from cfo.auth import create_access_token
from cfo.database import SessionLocal
from cfo.models import User, UserRole
from cfo.services.moshko_readiness import moshko_readiness

SECRET_FIELDS = (
    "anthropic_api_key", "whatsapp_access_token", "whatsapp_phone_number_id",
    "whatsapp_app_secret", "whatsapp_verify_token", "telegram_bot_token", "telegram_webhook_secret",
)


def _leaves(value):
    if isinstance(value, dict):
        for item in value.values():
            yield from _leaves(item)
    else:
        yield value


@pytest.fixture
def all_set(monkeypatch):
    for field in SECRET_FIELDS:
        monkeypatch.setattr(config_module.settings, field, f"SENTINEL-{field}")
    monkeypatch.setattr(config_module.settings, "whatsapp_push_enabled", True)


@pytest.fixture
def none_set(monkeypatch):
    for field in SECRET_FIELDS:
        monkeypatch.setattr(config_module.settings, field, None)
    monkeypatch.setattr(config_module.settings, "whatsapp_push_enabled", False)


def test_everything_configured_reads_true_and_leaks_nothing(all_set, caplog):
    caplog.set_level(logging.DEBUG)
    result = moshko_readiness()

    assert all(isinstance(leaf, bool) for leaf in _leaves(result)), result
    assert result["llm"]["api_key_configured"] is True
    assert result["whatsapp"] == {
        "access_token": True, "phone_number_id": True, "app_secret": True,
        "verify_token": True, "ready": True,
    }
    assert result["telegram"] == {"bot_token": True, "webhook_secret": True, "ready": True}
    assert result["push"]["whatsapp_push_enabled"] is True
    assert result["report_pdf"]["hebrew_font_available"] is True
    assert result["ready_to_chat"] is True

    dumped = json.dumps(result)
    assert "SENTINEL" not in dumped
    assert "SENTINEL" not in caplog.text


def test_nothing_configured_reads_false(none_set):
    result = moshko_readiness()

    assert all(isinstance(leaf, bool) for leaf in _leaves(result)), result
    assert result["llm"]["api_key_configured"] is False
    assert result["whatsapp"]["ready"] is False
    assert result["telegram"]["ready"] is False
    assert result["push"]["whatsapp_push_enabled"] is False
    assert result["ready_to_chat"] is False


def test_whatsapp_is_ready_only_with_all_four_settings(all_set, monkeypatch):
    monkeypatch.setattr(config_module.settings, "whatsapp_app_secret", "")
    result = moshko_readiness()
    assert result["whatsapp"]["app_secret"] is False
    assert result["whatsapp"]["ready"] is False
    # Telegram alone still lets Moshko answer.
    assert result["ready_to_chat"] is True


def test_readiness_makes_no_network_call(all_set, monkeypatch):
    import httpx

    def _boom(*_args, **_kwargs):  # pragma: no cover - must not run
        raise AssertionError("readiness must not touch the network")

    monkeypatch.setattr(httpx.AsyncClient, "request", _boom)
    monkeypatch.setattr(httpx.Client, "request", _boom)
    moshko_readiness()


# ------------------------------------------------------------------ endpoint

PATH = "/api/admin/moshko-readiness"


@pytest.fixture
def super_admin(client, fresh_org):
    actor = fresh_org()
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.organization_id == actor["org_id"]).first()
        user.role = UserRole.SUPER_ADMIN
        db.commit()
        token = create_access_token(data={
            "sub": str(user.id), "role": UserRole.SUPER_ADMIN.value, "org_id": user.organization_id,
        })
    finally:
        db.close()
    return {"Authorization": f"Bearer {token}"}


def test_endpoint_is_super_admin_only(client, fresh_org):
    assert client.get(PATH, headers=fresh_org()["headers"]).status_code in (401, 403)


def test_endpoint_returns_booleans_only_and_no_secret(client, super_admin, all_set):
    response = client.get(PATH, headers=super_admin)

    assert response.status_code == 200, response.text
    body = response.json()
    assert all(isinstance(leaf, bool) for leaf in _leaves(body)), body
    assert "SENTINEL" not in response.text
    assert body["whatsapp"]["ready"] is True
