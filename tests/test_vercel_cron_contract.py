"""Offline deployment contract for Vercel's UTC cron scheduler."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
ISRAEL = ZoneInfo("Asia/Jerusalem")

# Vercel evaluates all expressions in UTC. These times preserve dependency
# order and finish the full morning cycle before 08:00 Israel in winter and
# summer without duplicate/DST-triggered provider calls.
EXPECTED_DAILY_SCHEDULES = {
    "/api/cron/sync-sumit": "30 1 * * *",
    "/api/cron/sync-open-finance": "0 2 * * *",
    "/api/cron/enrich-expenses": "15 2 * * *",
    "/api/cron/process-ocr": "45 2 * * *",
    "/api/cron/bank-gap-scan": "15 3 * * *",
    "/api/cron/bookkeeper-morning": "45 3 * * *",
    "/api/cron/collection-reminders": "0 4 * * *",
}


def _cron_config() -> dict[str, str]:
    config = json.loads((ROOT / "vercel.json").read_text())
    jobs = config["crons"]
    paths = [job["path"] for job in jobs]
    assert len(paths) == len(set(paths)), "duplicate cron path would double-run a job"
    return {job["path"]: job["schedule"] for job in jobs}


def _local_time(expression: str, *, year: int, month: int, day: int) -> datetime:
    minute, hour, dom, cron_month, dow = expression.split()
    assert (dom, cron_month, dow) == ("*", "*", "*")
    return datetime(
        year, month, day, int(hour), int(minute), tzinfo=timezone.utc
    ).astimezone(ISRAEL)


def test_vercel_crons_use_one_daily_utc_schedule_in_dependency_order():
    schedules = _cron_config()
    assert schedules == EXPECTED_DAILY_SCHEDULES

    ordered_paths = list(EXPECTED_DAILY_SCHEDULES)
    utc_minutes = [
        int(schedules[path].split()[1]) * 60 + int(schedules[path].split()[0])
        for path in ordered_paths
    ]
    assert utc_minutes == sorted(utc_minutes)


def test_morning_cycle_finishes_before_0800_israel_in_winter_and_summer():
    schedule = _cron_config()["/api/cron/bookkeeper-morning"]
    for year, month, day in ((2026, 1, 15), (2026, 7, 15)):
        local = _local_time(schedule, year=year, month=month, day=day)
        assert (local.hour, local.minute) <= (6, 45)


def test_every_deployed_cron_route_rejects_missing_secret(client):
    for path in _cron_config():
        response = client.get(path)
        assert response.status_code == 401, path
