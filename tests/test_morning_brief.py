"""PR5 of the bookkeeper daily-cycle plan — the 08:00 morning brief: compose,
persist, render (Hebrew RTL), deliver. See
src/cfo/services/morning_brief_service.py module docstring for the full
rationale and src/cfo/services/morning_cycle_service.py for how step 8 wires
this in after `debtors`.
"""
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from cfo.database import SessionLocal
from cfo.models import CfoInsight, Contact, ContactType, DailySnapshot, Invoice, InvoiceStatus, MorningBrief, Organization
from cfo.services import morning_brief_service as svc
from cfo.services import morning_cycle_service as cycle_svc

TODAY = date(2026, 7, 20)  # day 20 -> outside the 1-9 payroll window, 3 days to the 23rd deadline


def _mk_insight(db, org_id, insight_type, *, status="active", severity="high",
                 title="כותרת", message="הודעה", evidence=None, fingerprint=None):
    row = CfoInsight(
        organization_id=org_id, fingerprint=fingerprint or f"{insight_type}:{title}",
        insight_type=insight_type, severity=severity, title=title, message=message,
        evidence=evidence or {}, status=status,
    )
    db.add(row)
    db.flush()
    return row


# --------------------------------------------------------------------- #
# compose_brief — live cycle_result path, reds ordering
# --------------------------------------------------------------------- #
def test_compose_brief_reds_ordering_from_live_cycle_result(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _mk_insight(db, org_id, "bank_anomaly", severity="critical",
                    title="שיק חוזר: ₪500 בתאריך 2026-07-20",
                    evidence={"date": TODAY.isoformat(), "kind": "bounced_check"})
        _mk_insight(db, org_id, "credit_line_breach", severity="critical",
                    title="חריגה ממסגרת האשראי הבנקאית — 2026-07-22")
        _mk_insight(db, org_id, "parity_mismatch", severity="high",
                    title="אי-התאמת התאמה משולשת יומית — bank_vs_books (2026-07)")
        db.commit()

        cycle_result = {
            "cycle_status": "red",
            "steps": {
                "daily_close": {"status": "ok", "result": {"snapshot": {
                    "cash_balance": 1000.0, "ar_total": 0.0, "ap_total": 0.0,
                    "month_net_profit": 0.0, "undocumented_total": 0.0,
                    "data_quality_issues": 0, "unreconciled_count": 0,
                    "open_expense_drafts": 5, "exceptions_over_48h": 0,
                    "parity_status": "mismatch", "credit_headroom": -500.0,
                    "credit_breach_date": date(2026, 7, 22),
                    "cycle_status": "red", "days_to_next_deadline": 2,
                    "open_items": {},
                }}},
                "debtors": {"status": "ok", "result": {
                    "total_receivable": 0.0,
                    "aging_summary": {
                        "current": {"count": 0, "amount": 0.0},
                        "31_60": {"count": 0, "amount": 0.0},
                        "61_90": {"count": 0, "amount": 0.0},
                        "90plus": {"count": 0, "amount": 0.0},
                    },
                    "top_overdue": [],
                }},
            },
        }

        brief = svc.compose_brief(db, org_id, TODAY, cycle_result=cycle_result)
        assert brief["status"] == "red"
        red_types = [r["type"] for r in brief["reds"]]
        assert red_types == ["bank_anomaly", "credit_line_breach", "parity_mismatch", "deadline_risk"]
        assert brief["cash"]["balance"] == 1000.0
        assert brief["cash"]["credit_headroom"] == -500.0
        assert brief["cash"]["breach_date"] == "2026-07-22"
        assert brief["deadline"]["days_left"] == 2
    finally:
        db.close()


def test_compose_brief_payroll_reminder_only_days_1_to_9(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        brief_in_window = svc.compose_brief(db, org_id, date(2026, 7, 5))
        brief_out_of_window = svc.compose_brief(db, org_id, date(2026, 7, 20))

        assert any(r["type"] == "payroll_reminder" for r in brief_in_window["reds"])
        assert not any(r["type"] == "payroll_reminder" for r in brief_out_of_window["reds"])
        # It's a static reminder, never a computed one — always hedged.
        payroll_red = next(r for r in brief_in_window["reds"] if r["type"] == "payroll_reminder")
        assert "אם יש עובדים" in payroll_red["title"]
    finally:
        db.close()


# --------------------------------------------------------------------- #
# compose_brief — persisted-state path (no cycle_result)
# --------------------------------------------------------------------- #
def test_compose_brief_from_persisted_state_after_full_cycle(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        result = cycle_svc.run_morning_cycle(db, org_id, TODAY, force=True)
        assert result["status"] == "ok"

        brief = svc.compose_brief(db, org_id, TODAY)  # no cycle_result -> persisted state
        snap = db.query(DailySnapshot).filter(
            DailySnapshot.organization_id == org_id, DailySnapshot.snapshot_date == TODAY,
        ).first()
        assert brief["status"] == snap.cycle_status
        assert brief["queues"]["drafts"] == snap.open_expense_drafts
        assert brief["deadline"]["days_left"] == snap.days_to_next_deadline
        assert brief["freshness"]["as_of"] is not None
    finally:
        db.close()


def test_compose_brief_honest_null_when_nothing_persisted_yet(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        brief = svc.compose_brief(db, org_id, TODAY)
        assert brief["cash"]["balance"] is None
        assert brief["cash"]["reason"] is not None
        assert brief["queues"]["drafts"] is None
        assert brief["status"] == "unknown"
        assert brief["freshness"]["as_of"] is None
        assert brief["freshness"]["reason"] is not None

        subject, text, html = svc.render_hebrew(brief)
        # Never fabricate a 0 for the missing cash balance — it must render
        # as an explicit "no data" marker, not "₪0" (a real zero balance
        # would be indistinguishable from "no data" if we did that).
        assert "מזומן: — (אין נתון)" in text
        assert "אין נתון" in html
        assert "—" in text
        assert "—" in html
    finally:
        db.close()


# --------------------------------------------------------------------- #
# render_hebrew — subject/emoji, RTL, reds-first
# --------------------------------------------------------------------- #
@pytest.mark.parametrize("status,expected_emoji", [
    ("green", "🟢"), ("yellow", "🟡"), ("red", "🔴"), ("unknown", "⚪"),
])
def test_render_hebrew_subject_emoji_per_status(status, expected_emoji):
    brief = {
        "organization_name": "חברת בדיקה", "date": "2026-07-20", "status": status,
        "reds": [], "cash": {}, "queues": {}, "debtors": {}, "parity": {},
        "deadline": {}, "freshness": {}, "collapsed_greens": [],
    }
    subject, text, html = svc.render_hebrew(brief)
    assert expected_emoji in subject
    assert "20/07" in subject
    assert "חברת בדיקה" in subject


def test_render_hebrew_rtl_and_reds_first():
    brief = {
        "organization_name": "חברת בדיקה", "date": "2026-07-20", "status": "red",
        "reds": [{"type": "bank_anomaly", "severity": "critical",
                   "title": "שיק חוזר: ₪500", "message": None}],
        "cash": {"balance": 1000.0, "as_of": "2026-07-20T05:00:00Z",
                  "credit_headroom": None, "breach_date": None, "reason": None},
        "queues": {"drafts": 3, "exceptions_over_48h": 0, "unreconciled": 1},
        "debtors": {"total_overdue": 0.0, "top": []},
        "parity": {"status": "ok"},
        "deadline": {"next_date": "2026-07-23", "days_left": 3},
        "freshness": {"as_of": "2026-07-20T05:00:00Z", "reason": None},
        "collapsed_greens": ["התאמה משולשת: תקינה"],
    }
    subject, text, html = svc.render_hebrew(brief)
    assert 'dir="rtl"' in html
    red_pos = html.index("שיק חוזר")
    cash_heading_pos = html.index("מזומן")
    assert red_pos < cash_heading_pos


# --------------------------------------------------------------------- #
# persist_and_deliver — idempotency, email gating, SMS gating
# --------------------------------------------------------------------- #
def _minimal_brief(org_id, status="yellow"):
    return {
        "organization_id": org_id, "organization_name": "חברת בדיקה",
        "date": TODAY.isoformat(), "status": status,
        "reds": ([{"type": "bank_anomaly", "severity": "critical", "title": "בעיה דחופה", "message": None}]
                 if status == "red" else []),
        "cash": {"balance": 1000.0, "as_of": "2026-07-20T05:00:00Z", "credit_headroom": None,
                  "breach_date": None, "reason": None},
        "queues": {"drafts": 1, "exceptions_over_48h": 0, "unreconciled": 0},
        "debtors": {"total_overdue": 0.0, "top": []},
        "parity": {"status": "ok"},
        "deadline": {"next_date": "2026-07-23", "days_left": 3},
        "freshness": {"as_of": "2026-07-20T05:00:00Z", "reason": None},
        "collapsed_greens": ["התאמה משולשת: תקינה"],
    }


def test_persist_creates_single_row_and_is_upserted_on_second_call(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        brief = _minimal_brief(org_id)
        svc.persist_and_deliver(db, org_id, TODAY, brief)
        svc.persist_and_deliver(db, org_id, TODAY, brief)

        count = db.query(MorningBrief).filter(
            MorningBrief.organization_id == org_id, MorningBrief.brief_date == TODAY,
        ).count()
        assert count == 1
    finally:
        db.close()


def test_email_skipped_with_reason_when_smtp_not_configured(fresh_org, monkeypatch):
    from cfo.config import settings

    monkeypatch.setattr(settings, "smtp_host", None, raising=False)
    monkeypatch.setattr(settings, "smtp_from", None, raising=False)

    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        result = svc.persist_and_deliver(db, org_id, TODAY, _minimal_brief(org_id))
        assert result["channels"]["email"]["status"] == "skipped"
        assert result["channels"]["email"]["reason"] == "smtp_not_configured"
        assert "email" not in result["delivered_channels"]
    finally:
        db.close()


def test_email_skipped_when_org_disabled(fresh_org, monkeypatch):
    from cfo.config import settings
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.com", raising=False)
    monkeypatch.setattr(settings, "smtp_from", "brief@example.com", raising=False)

    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        org = db.get(Organization, org_id)
        org.morning_brief_email_enabled = False
        org.morning_brief_recipients = "owner@example.com"
        db.commit()

        result = svc.persist_and_deliver(db, org_id, TODAY, _minimal_brief(org_id))
        assert result["channels"]["email"]["status"] == "skipped"
        assert result["channels"]["email"]["reason"] == "org_disabled"
    finally:
        db.close()


def test_email_idempotency_and_force_redelivery(fresh_org, monkeypatch):
    from cfo.config import settings
    import cfo.services.email_sender as email_sender_module

    monkeypatch.setattr(settings, "smtp_host", "smtp.example.com", raising=False)
    monkeypatch.setattr(settings, "smtp_from", "brief@example.com", raising=False)

    sent_calls = []

    async def _fake_send(to, subject, body, settings_):
        sent_calls.append(to)
        return True

    monkeypatch.setattr(email_sender_module, "send_email_smtp", _fake_send)

    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        org = db.get(Organization, org_id)
        org.morning_brief_recipients = "owner@example.com"
        db.commit()

        brief = _minimal_brief(org_id)
        r1 = svc.persist_and_deliver(db, org_id, TODAY, brief)
        assert r1["channels"]["email"]["status"] == "sent"
        assert len(sent_calls) == 1

        r2 = svc.persist_and_deliver(db, org_id, TODAY, brief)
        assert r2["channels"]["email"]["status"] == "skipped"
        assert r2["channels"]["email"]["reason"] == "already_delivered_today"
        assert len(sent_calls) == 1  # not re-sent

        r3 = svc.persist_and_deliver(db, org_id, TODAY, brief, force=True)
        assert r3["channels"]["email"]["status"] == "sent"
        assert len(sent_calls) == 2  # force re-delivers
    finally:
        db.close()


def test_sms_only_sent_when_red_and_opted_in(fresh_org, monkeypatch):
    import cfo.api.dependencies as deps_module

    sms_calls = []

    class _FakeSumit:
        async def send_sms(self, sms):
            sms_calls.append(sms.phone_number)
            return True

    monkeypatch.setattr(deps_module, "sumit_for_org", lambda db, org_id: _FakeSumit())

    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        org = db.get(Organization, org_id)
        org.phone = "0500000000"
        db.commit()

        # yellow + opted in -> SMS not sent (only red triggers SMS)
        org.morning_brief_sms_enabled = True
        db.commit()
        result_yellow = svc.persist_and_deliver(db, org_id, TODAY, _minimal_brief(org_id, status="yellow"))
        assert result_yellow["channels"]["sms"]["status"] == "skipped"
        assert result_yellow["channels"]["sms"]["reason"] == "not_red"
        assert sms_calls == []

        # red + NOT opted in -> SMS not sent
        org.morning_brief_sms_enabled = False
        db.commit()
        result_red_disabled = svc.persist_and_deliver(
            db, org_id, TODAY + timedelta(days=1), _minimal_brief(org_id, status="red"))
        assert result_red_disabled["channels"]["sms"]["status"] == "skipped"
        assert result_red_disabled["channels"]["sms"]["reason"] == "org_disabled"
        assert sms_calls == []

        # red + opted in -> SMS sent, one line
        org.morning_brief_sms_enabled = True
        db.commit()
        result_red_enabled = svc.persist_and_deliver(
            db, org_id, TODAY + timedelta(days=2), _minimal_brief(org_id, status="red"))
        assert result_red_enabled["channels"]["sms"]["status"] == "sent"
        assert sms_calls == ["0500000000"]
    finally:
        db.close()


# --------------------------------------------------------------------- #
# routes
# --------------------------------------------------------------------- #
def test_morning_brief_route_returns_payload(client, fresh_org):
    iso = fresh_org()
    org_id = iso["org_id"]
    db = SessionLocal()
    try:
        cycle_svc.run_morning_cycle(db, org_id, TODAY, force=True)
    finally:
        db.close()

    r = client.get("/api/daily-reports/morning-brief", headers=iso["headers"])
    assert r.status_code == 200
    body = r.json()
    assert body["exists"] is True
    assert body["payload"] is not None
    assert "status" in body


def test_morning_brief_route_empty_state_no_404(client, fresh_org):
    iso = fresh_org()
    r = client.get("/api/daily-reports/morning-brief", headers=iso["headers"])
    assert r.status_code == 200
    assert r.json()["exists"] is False


def test_morning_brief_history_route_empty_is_not_404(client, fresh_org):
    iso = fresh_org()
    r = client.get("/api/daily-reports/morning-brief/history", params={"days": 30}, headers=iso["headers"])
    assert r.status_code == 200
    body = r.json()
    assert body["history"] == []


def test_morning_brief_history_route_lists_composed_briefs(client, fresh_org):
    iso = fresh_org()
    org_id = iso["org_id"]
    db = SessionLocal()
    try:
        cycle_svc.run_morning_cycle(db, org_id, TODAY, force=True)
    finally:
        db.close()

    # חלון ההיסטוריה נמדד מ-date.today() האמיתי בעוד TODAY קבוע — חלון
    # קשיח של 30 נשבר ברגע שהמרחק ביניהם עובר 30 יום (קרה ב-2026-08-20).
    window = min((date.today() - TODAY).days + 1, 365)
    r = client.get("/api/daily-reports/morning-brief/history", params={"days": window}, headers=iso["headers"])
    assert r.status_code == 200
    history = r.json()["history"]
    assert len(history) == 1
    assert history[0]["brief_date"] == TODAY.isoformat()
    assert "reds_count" in history[0]


# --------------------------------------------------------------------- #
# morning_cycle_service integration — step 8 present, isolated failure
# --------------------------------------------------------------------- #
def test_morning_cycle_wires_morning_brief_as_step_8(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        result = cycle_svc.run_morning_cycle(db, org_id, TODAY, force=True)
        assert result["status"] == "ok"
        assert "morning_brief" in result["steps"]
        assert result["steps"]["morning_brief"]["status"] == "ok"

        row = db.query(MorningBrief).filter(
            MorningBrief.organization_id == org_id, MorningBrief.brief_date == TODAY,
        ).first()
        assert row is not None
    finally:
        db.close()


def test_morning_brief_step_failure_does_not_fail_the_cycle(fresh_org, monkeypatch):
    import cfo.services.morning_brief_service as brief_module

    def _boom(db, org_id, today, cycle_result=None):
        raise RuntimeError("morning brief boom")

    monkeypatch.setattr(brief_module, "compose_brief", _boom)

    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        result = cycle_svc.run_morning_cycle(db, org_id, TODAY, force=True)
        assert result["status"] == "ok"
        assert result["steps"]["morning_brief"]["status"] == "error"
        assert "morning brief boom" in result["steps"]["morning_brief"]["error"]
        # Everything before it still succeeded.
        assert result["steps"]["daily_close"]["status"] == "ok"
        assert result["steps"]["debtors"]["status"] == "ok"
    finally:
        db.close()
