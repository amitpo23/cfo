"""Owner decisions of 2026-10-23 (Rezef ops guardrails).

1. Open Finance nightly refresh: off the schedule, refused unless a flag is on.

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
