"""S4 (ספרינט זהות-מושקו, 25/08/2026) — לוח פיילוט read-only ל-WhatsApp
(5 ארגונים). קריטריון ההצלחה מהתוכנית: 'שאילתה אחת עונה כמה עלה השבוע
ומה נשבר'. משתמש בקונבנציית session_id הקיימת (wa-/tg- prefix, ר'
_apply_moshko_filters ב-admin.py) — אין מנוע חדש, רק צירוף.
"""
from datetime import datetime, timedelta

from cfo.database import SessionLocal
from cfo.models import ChatMessage, LLMUsage, MoshkoGap
from cfo.services.moshko_pilot_summary import compute_pilot_summary


def _wa_session(n=1):
    return f"wa-{n}"


def _mk_usage(db, org_id, *, session_id, cost_usd="0.01"):
    row = LLMUsage(
        organization_id=org_id, session_id=session_id, provider="anthropic",
        model="claude-sonnet-5", input_tokens=100, output_tokens=50,
        cost_usd=cost_usd, purpose="chat",
    )
    db.add(row)
    db.flush()
    return row


def _mk_message(db, org_id, *, session_id, role="assistant"):
    row = ChatMessage(
        organization_id=org_id, user_id=1, session_id=session_id,
        role=role, content="תשובה",
    )
    db.add(row)
    db.flush()
    return row


def _mk_gap(db, org_id, *, session_id, status="open"):
    row = MoshkoGap(
        organization_id=org_id, user_id=1, session_id=session_id,
        question="שאלה", answer="תשובה", gap_kind="tool_failed", status=status,
    )
    db.add(row)
    db.flush()
    return row


def test_only_whatsapp_sessions_counted_not_web(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _mk_usage(db, org_id, session_id="wa-1", cost_usd="0.02")
        _mk_usage(db, org_id, session_id="web-session-x", cost_usd="99.00")
        db.commit()

        summary = compute_pilot_summary(db, organization_id=org_id)

        assert float(summary["cost_usd_total"]) == 0.02
    finally:
        db.close()


def test_counts_llm_calls_turns_and_gaps_together(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _mk_usage(db, org_id, session_id="wa-1", cost_usd="0.01")
        _mk_usage(db, org_id, session_id="wa-1", cost_usd="0.01")
        _mk_message(db, org_id, session_id="wa-1")
        _mk_gap(db, org_id, session_id="wa-1", status="open")
        db.commit()

        summary = compute_pilot_summary(db, organization_id=org_id)

        assert summary["llm_calls"] == 2
        assert float(summary["cost_usd_total"]) == 0.02
        assert summary["assistant_turns"] == 1
        assert summary["gaps_opened"] == 1
        assert summary["gaps_still_open"] == 1
    finally:
        db.close()


def test_resolved_gaps_are_not_counted_as_still_open(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        _mk_gap(db, org_id, session_id="wa-1", status="open")
        _mk_gap(db, org_id, session_id="wa-1", status="answered")
        db.commit()

        summary = compute_pilot_summary(db, organization_id=org_id)

        assert summary["gaps_opened"] == 2
        assert summary["gaps_still_open"] == 1
    finally:
        db.close()


def test_no_pilot_data_yet_is_honest_zero_not_error(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        summary = compute_pilot_summary(db, organization_id=org_id)

        assert summary["llm_calls"] == 0
        assert float(summary["cost_usd_total"]) == 0.0
        assert summary["assistant_turns"] == 0
        assert summary["gaps_opened"] == 0
    finally:
        db.close()


def test_period_filter(fresh_org):
    org_id = fresh_org()["org_id"]
    db = SessionLocal()
    try:
        recent = _mk_usage(db, org_id, session_id="wa-1", cost_usd="0.01")
        old = _mk_usage(db, org_id, session_id="wa-2", cost_usd="9.00")
        db.commit()
        old.created_at = datetime.utcnow() - timedelta(days=30)
        db.commit()

        summary = compute_pilot_summary(db, organization_id=org_id, since=datetime.utcnow() - timedelta(days=7))

        assert float(summary["cost_usd_total"]) == 0.01
    finally:
        db.close()
