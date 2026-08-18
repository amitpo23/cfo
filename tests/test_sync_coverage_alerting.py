"""בקרת הכיסוי חייבת להשאיר עקבה — לא רק push לערוץ מת.

**הממצא (18/08/2026), מדוד.** שער-המפתח שנפרס ב-17/08 דילג על org2 ו-org5
במשך יממה שלמה. `/cron/roster-health` רץ ב-05:30 ולא התריע. שתי סיבות
נפרדות, שתיהן אמיתיות:

**1. ההתרעה נזרקת.** `scheduled_roster_health` שולח **רק** דרך
`push_to_organization` — כלומר טלגרם/וואטסאפ. כל הערוצים ריקים בפרוד
(`TELEGRAM_BOT_TOKEN` אינו מוגדר, `WHATSAPP_*` ריקים). אפס אזכורי
`CfoInsight` ב-`roster_coverage.py` וב-handler. כלומר הבקרה מחשבת ממצא
מדויק וזורקת אותו.

**2. הסף רחב מדי לכשל יומי.** `STALE_AFTER_HOURS = 48`. ארגון שפספס
סנכרון יומי אחד עומד על ~24–28 שעות — מתחת לסף. הבקרה נועדה לתפוס תיק
שנשר לשבועות (org2 ב-17/07, org3 ב-06/07), לא כשל של יום.

**התיקון:** הממצא נשמר כ-`CfoInsight` באותה תבנית fingerprint של
`parity_service.check_and_alert`, ונוסף שער יומי נפרד. עקבה ב-DB אינה
תלויה בערוץ, ולכן היא נראית ב-UI גם כשאין טלגרם.
"""
from datetime import datetime, timedelta

import pytest

from cfo.database import SessionLocal
from cfo.models import CfoInsight, IntegrationConnection, SyncCheckpoint
from cfo.services import roster_coverage
from cfo.services.sync_engine import SOURCE_CHECKPOINT_ENTITY


def _seed(db, org_id: int, *, hours_ago: float):
    db.add(IntegrationConnection(
        organization_id=org_id, source="sumit", status="active",
    ))
    db.add(SyncCheckpoint(
        organization_id=org_id, source="sumit",
        entity_type=SOURCE_CHECKPOINT_ENTITY,
        last_success_at=datetime.utcnow() - timedelta(hours=hours_ago),
    ))
    db.commit()


# ==================================================================== #
# הסף היומי
# ==================================================================== #
def test_a_single_missed_daily_sync_is_detected(client, fresh_org):
    """**התרחיש שקרה בפועל.** 28 שעות — מתחת ל-48 של בקרת הנשירה, אבל
    זה בדיוק יום שאבד."""
    db = SessionLocal()
    org_id = fresh_org()["org_id"]
    _seed(db, org_id, hours_ago=28)

    missed = roster_coverage.missed_daily_sync(db)

    assert org_id in {m["organization_id"] for m in missed}


def test_a_normal_daily_cadence_is_not_flagged(client, fresh_org):
    """שער נגדי: ריצה של הבוקר אינה כשל. סף שמתריע על 20 שעות היה
    מתריע כל יום ומאמן להתעלם."""
    db = SessionLocal()
    org_id = fresh_org()["org_id"]
    _seed(db, org_id, hours_ago=6)

    missed = roster_coverage.missed_daily_sync(db)

    assert org_id not in {m["organization_id"] for m in missed}


def test_the_threshold_sits_between_a_daily_run_and_the_dropout_gate():
    """הסף חייב להיות רחב מספיק לעיכוב cron, וצר מספיק כדי לתפוס יום
    שאבד — כלומר בין 24 ל-48."""
    assert 24 < roster_coverage.MISSED_DAILY_AFTER_HOURS < roster_coverage.STALE_AFTER_HOURS


def test_an_inactive_connection_is_not_reported_as_missed(client, fresh_org):
    """שער נגדי: ארגון שהושבת במכוון אינו 'פספס סנכרון' — הוא כבר
    מדווח ע"י בקרת הנשירה, ודיווח כפול מייצר רעש."""
    db = SessionLocal()
    org_id = fresh_org()["org_id"]
    db.add(IntegrationConnection(
        organization_id=org_id, source="sumit", status="paused",
    ))
    db.add(SyncCheckpoint(
        organization_id=org_id, source="sumit",
        entity_type=SOURCE_CHECKPOINT_ENTITY,
        last_success_at=datetime.utcnow() - timedelta(hours=100),
    ))
    db.commit()

    missed = roster_coverage.missed_daily_sync(db)

    assert org_id not in {m["organization_id"] for m in missed}


# ==================================================================== #
# העקבה ב-DB — לא תלויה בערוץ
# ==================================================================== #
def test_the_finding_is_persisted_as_an_insight(client, fresh_org):
    """הלב. `push_to_organization` הוא הצינור היחיד היום, וכל הערוצים
    ריקים בפרוד — כלומר הממצא נזרק. עקבה ב-DB נראית ב-UI תמיד."""
    db = SessionLocal()
    org_id = fresh_org()["org_id"]
    _seed(db, org_id, hours_ago=30)

    roster_coverage.persist_coverage_findings(db)

    rows = db.query(CfoInsight).filter(
        CfoInsight.organization_id == org_id,
        CfoInsight.insight_type == roster_coverage.INSIGHT_TYPE,
    ).all()
    assert rows, "הממצא לא נשמר — יאבד שוב כשהערוצים מתים"


def test_repeated_runs_do_not_duplicate_the_insight(client, fresh_org):
    """הבקרה רצה כל יום. בלי fingerprint היינו מייצרים התראה חדשה בכל
    בוקר על אותו ארגון."""
    db = SessionLocal()
    org_id = fresh_org()["org_id"]
    _seed(db, org_id, hours_ago=30)

    roster_coverage.persist_coverage_findings(db)
    roster_coverage.persist_coverage_findings(db)

    count = db.query(CfoInsight).filter(
        CfoInsight.organization_id == org_id,
        CfoInsight.insight_type == roster_coverage.INSIGHT_TYPE,
    ).count()
    assert count == 1


def test_recovery_resolves_the_insight(client, fresh_org):
    """ארגון שחזר לסנכרן — ההתראה נסגרת. התראה שאינה נסגרת הופכת לרעש
    קבוע, ואז איש אינו מאמין לה."""
    db = SessionLocal()
    org_id = fresh_org()["org_id"]
    _seed(db, org_id, hours_ago=30)
    roster_coverage.persist_coverage_findings(db)

    cp = db.query(SyncCheckpoint).filter(
        SyncCheckpoint.organization_id == org_id).first()
    cp.last_success_at = datetime.utcnow() - timedelta(hours=2)
    db.commit()

    roster_coverage.persist_coverage_findings(db)

    row = db.query(CfoInsight).filter(
        CfoInsight.organization_id == org_id,
        CfoInsight.insight_type == roster_coverage.INSIGHT_TYPE,
    ).one()
    assert row.status == "resolved"


def test_the_cron_persists_and_does_not_depend_on_a_channel(client):
    """שער חיווט: ה-handler חייב לשמור, ולא רק לדחוף. אחרת התיקון קיים
    ואינו על המסלול — הכשל שחזר בסשן הזה שלוש פעמים."""
    import inspect

    from cfo.api.routes import cron

    src = inspect.getsource(cron.scheduled_roster_health)
    assert "persist_coverage_findings" in src
