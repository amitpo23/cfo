"""Stagger SUMIT orgs across separate per-minute windows (25/08/2026,
הנחיית בעלים אחרי בדיקה חיה על אליהב כהן/org2).

ממצא: `_run_sync_targets` הריץ את כל ארגוני-SUMIT הפעילים ברצף תוך
שניות בודדות בתוך אותה דקת-UTC — כל ארגון צריך עד 9 קריאות רשת
אמיתיות לריצה מלאה, מול תקציב **גלובלי** (כל הארגונים יחד) של 10
קריאות/דקה. שלושה ארגונים יחד = עד 27 קריאות בתוך אותה דקה, פי-2.7
מהתקציב — רוב הקריאות נחסמות fail-closed ("SUMIT global minute
request budget exceeded"), והמסמכים הפיננסיים (invoices/bills/
payments/customers) נופלים.

התיקון: המתנה בין ארגוני-SUMIT עוקבים כך שכל אחד נופל בדקת-UTC
משלו, ומקבל את מלוא ה-10/דקה לעצמו. לא נוגע ב-Open Finance (תקציב
נפרד, לא משותף) — ההמתנה חלה רק בין שני יעדי-sumit עוקבים."""
import asyncio


def test_stagger_sleeps_between_consecutive_sumit_targets(monkeypatch):
    from cfo.api.routes import cron

    sleep_calls = []

    async def fake_sleep(seconds):
        sleep_calls.append(seconds)

    monkeypatch.setattr(cron.asyncio, "sleep", fake_sleep)

    def fake_get_connector_for_org(db, org_id, source):
        return object(), None, source

    class _FakeSyncRun:
        id = 1
        status = None
        counts = {}
        error_summary = None

    async def fake_run_full_sync(self, *a, **kw):
        return _FakeSyncRun()

    from cfo.services.sync_engine import SyncEngine
    monkeypatch.setattr(SyncEngine, "run_full_sync", fake_run_full_sync)
    monkeypatch.setattr(cron, "get_connector_for_org", fake_get_connector_for_org)
    monkeypatch.setattr(
        cron, "run_post_sync_tasks",
        lambda *a, **kw: _async_return({}),
    )
    monkeypatch.setattr(cron, "mark_client_loop_result", lambda *a, **kw: None)

    targets = {(1, "sumit"), (2, "sumit"), (5, "sumit")}

    class _FakeDB:
        def commit(self):
            pass

    asyncio.run(cron._run_sync_targets(_FakeDB(), targets))

    # 3 sumit targets -> 2 waits between them, none before the first.
    assert len(sleep_calls) == 2
    assert all(s == cron.SUMIT_INTER_ORG_STAGGER_SECONDS for s in sleep_calls)


def test_stagger_does_not_apply_to_open_finance_targets(monkeypatch):
    from cfo.api.routes import cron

    sleep_calls = []

    async def fake_sleep(seconds):
        sleep_calls.append(seconds)

    monkeypatch.setattr(cron.asyncio, "sleep", fake_sleep)

    def fake_get_connector_for_org(db, org_id, source):
        return object(), None, source

    class _FakeSyncRun:
        id = 1
        status = None
        counts = {}
        error_summary = None

    async def fake_run_full_sync(self, *a, **kw):
        return _FakeSyncRun()

    from cfo.services.sync_engine import SyncEngine
    monkeypatch.setattr(SyncEngine, "run_full_sync", fake_run_full_sync)
    monkeypatch.setattr(cron, "get_connector_for_org", fake_get_connector_for_org)
    monkeypatch.setattr(
        cron, "run_post_sync_tasks",
        lambda *a, **kw: _async_return({}),
    )
    monkeypatch.setattr(cron, "mark_client_loop_result", lambda *a, **kw: None)

    targets = {(1, "open_finance"), (2, "open_finance")}

    class _FakeDB:
        def commit(self):
            pass

    asyncio.run(cron._run_sync_targets(_FakeDB(), targets))

    assert sleep_calls == []


async def _async_return(value):
    return value
