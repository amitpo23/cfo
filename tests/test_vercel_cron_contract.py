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
# 19/08/2026 16:05 — הנחיית בעלים מפורשת: "אין צורך בריצה יומית יזומה יותר
# תבטל את זה... תוודא שאין קריאות בשלב זה עד שנאשר תוכנית פעולה מקיפה
# ונאשר תכולה שלה". **כל** ה-crons הוסרו מ-vercel.json — לא רק אלה שנוגעים
# ב-SUMIT: שתי שרשראות ה-SMS (collection-reminders, bookkeeper-morning →
# morning_brief_service.send_sms) הגיעו ל-send_sms של SUMIT ונשענו עד כה רק
# על מתגי ה-env; sync-open-finance צורך מכסת Open Finance; והשאר בוטלו יחד
# איתם כחלק מ"אין ריצה יומית יזומה".
#
# רקע קודם: /api/cron/sync-sumit הוסר 19/08 בבוקר (עצירת חירום מלאה של
# אוטומציית SUMIT), וה-cron-ים של getdetails הוסרו 11/08 (פעולה בתשלום
# פר-מסמך עם תקרה שלא אומתה מול המחירון).
#
# להחזרת cron כלשהו נדרש: אישור בעלים מפורש לתוכנית שמגדירה מה רץ, באיזו
# תדירות, עם איזה תקציב נמדד, ומה ראיית ההצלחה.
#
# 20/08/2026 — אישור בעלים ("מאשר") לתוכנית העומק REZEF_DEEP_PLAN_2026-08-20
# סעיף W2.1: רענון יומי של מדידת המכסה. מה רץ: /api/cron/refresh-sumit-quota;
# תדירות: פעם ביום (03:30 UTC); תקציב: קריאת listquotas **חינמית** אחת
# לארגון ≈ 30 בחודש, עם שער עמיד של רענון אחד ליום פר-ארגון; ראיית הצלחה:
# פעולות בתשלום עוברות שער מבוסס-מדידה במקום חסימה גורפת ("קוד מת").
EXPECTED_DAILY_SCHEDULES: dict[str, str] = {
    "/api/cron/refresh-sumit-quota": "30 3 * * *",
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
    # כל עוד אין crons בכלל (הנחיית 19/08), אין מחזור בוקר לתזמן. אם/כאשר
    # bookkeeper-morning יוחזר, האילוץ המקורי חוזר לתוקף אוטומטית.
    schedules = _cron_config()
    if "/api/cron/bookkeeper-morning" not in schedules:
        assert schedules == EXPECTED_DAILY_SCHEDULES
        return
    schedule = schedules["/api/cron/bookkeeper-morning"]
    for year, month, day in ((2026, 1, 15), (2026, 7, 15)):
        local = _local_time(schedule, year=year, month=month, day=day)
        assert (local.hour, local.minute) <= (6, 45)


def test_every_deployed_cron_route_rejects_missing_secret(client):
    for path in _cron_config():
        response = client.get(path)
        assert response.status_code == 401, path
