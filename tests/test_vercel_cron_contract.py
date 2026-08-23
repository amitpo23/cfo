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
#
# 21/08/2026 — אישור בעלים ("מאשר") ל-SWOT הבקרה (REZEF_CONTROL_SWOT) סעיף
# W6.8: החזרת שכבת הבקרה היומית. מה רץ: bank-gap-scan (03:15) — פערי
# בנק↔מסמכים; bookkeeper-morning (03:45) — המחזור המלא (parity, אנומליות,
# data_quality, revenue_watch, action_reaper, בריף). תקציב: **אפס קריאות
# SUMIT** — מוכח בטסט test_morning_cycle_makes_zero_sumit_network_calls
# (וה-SMS של הבריף כבוי כברירת מחדל + מגודר בשער הפעולות-בתשלום).
# ראיית הצלחה: CfoInsight/DailySnapshot/MorningBrief מתרעננים יומית.
#
# 23/08/2026 — אישור בעלים מפורש (ציטוט): "אפשר שמאז האירוע, הסדר יחזור
# להיות כמו שצריך ומחזור אוטומטי מלא, אבל כמובן עם ההגבלות של ה-API Calls
# ל-SUMIT עם ההגדרה הקשיחה שלנו". החזרת המחזור האוטומטי המלא — 8 crons —
# תחת אותם שערי-עלות מבניים שכבר קיימים בקוד (לא הוקלו/לא נוספו כאן; רק
# אומתו לפני ההחזרה). פר-cron, מה רץ / תדירות / תקציב מדוד / ראיית הצלחה:
#
# 1. sync-sumit (01:30 UTC) — סנכרון SUMIT יומי לכל תיק. תקציב: שני שערים
#    בלתי-תלויים לפני כל קריאת רשת — (א) `_daily_budget_gate` ב-cron.py
#    (ריצה מוצלחת אחת פר (ארגון, מקור) פר 20h,
#    `settings.sumit_sync_min_interval_hours`, עם רצפה קשיחה של 20 ב-
#    `config.py.__post_init__`-style guard); (ב) `_per_key_daily_gate` →
#    `claim_daily_sync_run` ב-`sumit_request_budget.py` (ריצה אחת ליום
#    **פר-מפתח**, לא רק פר-ארגון — סוגר את המסלול שבו שני ארגונים חולקים
#    מפתח משרד אחד). מתחת לשניהם: `_make_request`/`_post_binary` ב-
#    `sumit_integration.py` מסרבים fail-closed (`SumitRequestBudgetRequired`)
#    בלי `request_limiter` אמיתי, ופעולות בתשלום (getpdf/getdetails/…)
#    עוברות גם את `assert_paid_action_within_quota`. ראיית הצלחה/הוכחה:
#    `tests/test_sumit_daily_sync_per_key.py` (למשל
#    `test_the_second_run_on_the_same_key_is_refused`,
#    `test_a_second_organization_cannot_spend_the_same_key_again`),
#    `tests/test_per_key_gate_uses_real_credentials.py`,
#    `tests/test_sync_call_protection.py::test_sumit_budget_gate_skips_within_interval`,
#    ושער-הרגרסיה הקבוע `tests/test_sumit_rate_limit_hard_rule.py`.
#
# 2. sync-open-finance (02:00 UTC) — סנכרון Open Finance יומי. תקציב: שלושה
#    שערים לפני קריאת רשת — `_of_consent_gate` ב-cron.py (fail-closed אם
#    מסע ה-consent המקומי אינו במצב בר-סנכרון), `_daily_budget_gate`
#    (ריצה מוצלחת אחת פר (ארגון, מקור) פר `of_sync_min_interval_hours`,
#    רצפה קשיחה 20h), ואז claim עמיד של ניסיון בטבלת המונים: עד שני ניסיונות
#    ביום פר-ארגון ו-cooldown עמיד אחרי כשל. כך retry אינו מפרש כשל כהיתר
#    לקריאת ספק נוספת. נשמר תחת מכסת ~500/חודש (RSF-025/021). ראיית
#    הצלחה: `tests/test_sync_call_protection.py::test_of_daily_budget_gate_skips_within_interval_and_allows_after`,
#    `::test_of_daily_budget_gate_allows_when_no_prior_success`,
#    `::test_of_consent_gate_stops_pending_journey_before_daily_budget`.
#
# 3. bank-gap-scan (03:15 UTC) — כפי שהיה: local-only, אפס קריאות ספק.
#    `services/bank_expense_gap.py` אינו מייבא `SumitIntegration`/httpx —
#    קורא רק `BankTransaction`/מסמכי הנה"ח מה-DB המקומי. אין טסט "אפס
#    רשת" ייעודי (בניגוד ל-bookkeeper-morning); הראיה כאן היא היעדר ייבוא
#    ספק בקוד עצמו (נבדק ב-grep על imports) בשילוב עם
#    `tests/test_bank_expense_gap.py` שמריץ את `scan_and_alert` על נתוני
#    fixture בלבד.
#
# 4. refresh-sumit-quota (03:30 UTC) — כפי שהיה: `listquotas` חינמית, פעם
#    ביום פר-ארגון (בלוק 20/08 למעלה — ללא שינוי).
#
# 5. bookkeeper-morning (03:45 UTC) — כפי שהיה: אפס קריאות SUMIT, מוכח
#    ב-`tests/test_sumit_call_discipline_w6.py::test_morning_cycle_makes_zero_sumit_network_calls`
#    (patches `SumitIntegration._make_request`/`_post_binary` ל-assert
#    שנכשל אם המחזור מגיע לרשת).
#
# 6. collection-reminders (04:00 UTC) — תזכורות גבייה SMS/מייל. תקציב:
#    שער רגולטורי ראשון — `Organization.collection_reminders_enabled`
#    (ברירת מחדל `False`, `models.py`); רק ארגונים ש-opted-in נכנסים
#    ללולאה כלל (`run_collection_reminders` ב-cron.py). שער שני: כל שליחת
#    SMS עוברת `sumit.send_sms` → `/sms/sms/send/`, שהוא חבר ב-
#    `PAID_ACTION_ENDPOINTS` ב-`sumit_integration.py` ולכן חוסה תחת אותו
#    שער פעולות-בתשלום (`_enforce_paid_action_budget` →
#    `assert_paid_action_within_quota`) ואותו `request_limiter` fail-closed
#    כמו כל קריאת SUMIT אחרת — אין נתיב עוקף. בנוסף כל מסירת ערוץ (גם מייל)
#    תובעת slot יומי עמיד פר-ארגון; ברירת המחדל והתקרה הקשיחה הן 20 למסירות
#    בריצה/יום. ראיית הצלחה:
#    `tests/test_collection_reminders.py::test_org_collection_defaults`
#    (ברירת מחדל False), `::test_collection_run_blocked_when_org_disabled`,
#    `::test_dispatch_sends_sms_and_records`.
#
# 7. roster-health (05:30 UTC) — local-only: `services/roster_coverage.py`
#    אינו מייבא ספק (רק models/SQLAlchemy) — קורא DB בלבד ומדווח. הדחיפה
#    היחידה היא `channel_notifier.push_to_organization` ל-Telegram/
#    WhatsApp. לפני הדחיפה נתבע תקציב עמיד משותף פר-ארגון (50/יום) עם
#    channel-alerts; חריגה מדווחת ומדלגת. כשל בדחיפה אינו מפיל את הבקרה. אין טסט
#    "אפס רשת" ייעודי; הראיה היא היעדר ייבוא ספק (grep) +
#    `tests/test_roster_coverage.py`.
#
# 8. channel-alerts (06:00 UTC) — דוחף CfoInsight חדשים בסיכון high/
#    critical לערוצי שיחה מקושרים. אותו מנגנון push כמו roster-health —
#    claim עמיד באותו scope יומי פר-ארגון ואז
#    `channel_notifier.push_to_organization`, לא קריאת SUMIT/OF כלל (רק
#    קורא `CfoInsight` מה-DB המקומי ושולח ל-Telegram/WhatsApp). חריגה מופיעה
#    ב-`budget_skipped` וב-`results`, ולא נבלעת. ראיית
#    הצלחה: `tests/test_channel_notifier.py`.
EXPECTED_DAILY_SCHEDULES: dict[str, str] = {
    "/api/cron/sync-sumit": "30 1 * * *",
    "/api/cron/sync-open-finance": "0 2 * * *",
    "/api/cron/bank-gap-scan": "15 3 * * *",
    "/api/cron/refresh-sumit-quota": "30 3 * * *",
    "/api/cron/bookkeeper-morning": "45 3 * * *",
    "/api/cron/collection-reminders": "0 4 * * *",
    "/api/cron/roster-health": "30 5 * * *",
    "/api/cron/channel-alerts": "0 6 * * *",
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
    # 23/08/2026: bookkeeper-morning הוחזר (החזרת המחזור האוטומטי המלא).
    # התנאי נשמר להגנה עתידית — אם הוא יוסר שוב, האילוץ מדלג בלי להיכשל
    # במקום להניח שהוא תמיד נוכח.
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
